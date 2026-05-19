#!/usr/bin/env python3
"""Vilona Monitor — Generate real monitoring report from PolyEdge DB."""

import asyncio
import sys, json
import logging
from decimal import Decimal
sys.path.insert(0, "/home/openclaw/projects/polyedge")

from sqlalchemy import create_engine, text
from backend.config import settings
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)

def _fetch_real_equity():
    """Fetch real PM total equity (sync wrapper around async call)."""
    try:
        from backend.core.wallet.bankroll_reconciliation import fetch_pm_total_equity
        return asyncio.run(fetch_pm_total_equity())
    except Exception:
        return None

def main():
    engine = create_engine(settings.DATABASE_URL)
    report = {"strategies": {}, "accounts": {}, "heartbeats": {}, "anomalies": [], "summary": {}, "wallet_health": {}}

    with engine.connect() as conn:
        # ── All strategies ──
        rows = conn.execute(text("""
            SELECT strategy_name, enabled, trading_mode, mode, time_horizon, risk_tier, disabled_at
            FROM strategy_config ORDER BY strategy_name
        """)).fetchall()

        strategies = []
        for r in rows:
            strategies.append({
                "name": r[0], "enabled": r[1], "trading_mode": r[2] or r[3],
                "horizon": r[4], "risk": r[5], "disabled_at": str(r[6]) if r[6] else None
            })

        # ── Heartbeats (testnet) ──
        row = conn.execute(text("SELECT misc_data FROM bot_state WHERE mode='testnet'")).fetchone()
        now = datetime.now(timezone.utc)
        if row and row[0]:
            hb = row[0] if isinstance(row[0], dict) else json.loads(row[0])
            for k, v in sorted(hb.items()):
                if k.startswith("heartbeat:"):
                    name = k.replace("heartbeat:", "")
                    try:
                        ts = datetime.fromisoformat(v)
                        age_min = (now - ts).total_seconds() / 60
                        report["heartbeats"][name] = {"last_beat": v, "age_minutes": round(age_min, 1)}
                    except Exception as e:
                        logger.debug(f"Heartbeat parse error: {e}")

        # ── Strategy PnL (7d, LIVE only) ──
        rows = conn.execute(text("""
            SELECT strategy, COUNT(*) as trades,
                   COALESCE(SUM(CASE WHEN pnl > 0 THEN pnl ELSE 0 END), 0) as gross_win,
                   COALESCE(SUM(CASE WHEN pnl <= 0 THEN pnl ELSE 0 END), 0) as gross_loss,
                   COALESCE(SUM(pnl), 0) as total_pnl,
                   COALESCE(AVG(CASE WHEN pnl > 0 THEN 1.0 ELSE 0.0 END), 0) as wr
            FROM trades
            WHERE settled = true AND trading_mode = 'live'
                  AND timestamp >= NOW() - INTERVAL '7 days'
            GROUP BY strategy ORDER BY SUM(pnl) DESC
        """)).fetchall()

        for r in rows:
            pf = abs(r[2]/r[3]) if r[3] != 0 else 999
            report["strategies"][r[0]] = {
                "trades_7d": r[1], "gross_win": round(r[2], 2), "gross_loss": round(r[3], 2),
                "pnl_7d": round(r[4], 2), "win_rate": round(r[5], 4), "profit_factor": round(pf, 2)
            }

        # ── Bot state (accounts) ──
        rows = conn.execute(text("SELECT * FROM bot_state")).fetchall()
        cols = [c[0] for c in conn.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name = 'bot_state' ORDER BY ordinal_position")).fetchall()]

        for r in rows:
            d = dict(zip(cols, r))
            mode = d["mode"]
            report["accounts"][mode] = {
                "bankroll": float(d.get("bankroll") or 0),
                "total_trades": int(d.get("total_trades") or 0),
                "winning_trades": int(d.get("winning_trades") or 0),
                "total_pnl": float(d.get("total_pnl") or 0),
                "paper_bankroll": float(d.get("paper_bankroll") or 0),
                "paper_pnl": float(d.get("paper_pnl") or 0),
                "paper_trades": int(d.get("paper_trades") or 0),
                "paper_wins": int(d.get("paper_wins") or 0),
                "is_running": d.get("is_running", False),
                "last_run": str(d.get("last_run", "")),
            }

        # ── Live PnL from trades (source of truth) ──
        row = conn.execute(text("""
            SELECT COUNT(*) as trades,
                   COALESCE(SUM(CASE WHEN pnl > 0 THEN pnl ELSE 0 END), 0) as gross_win,
                   COALESCE(SUM(CASE WHEN pnl <= 0 THEN pnl ELSE 0 END), 0) as gross_loss,
                   COALESCE(SUM(pnl), 0) as total_pnl,
                   COALESCE(AVG(CASE WHEN pnl > 0 THEN 1.0 ELSE 0.0 END), 0) as wr
            FROM trades
            WHERE trading_mode = 'live' AND settled = true
        """)).fetchone()
        report["summary"]["live_total_trades"] = row[0]
        report["summary"]["live_total_pnl"] = round(float(row[3]), 2)
        report["summary"]["live_win_rate"] = round(float(row[4]), 4)
        report["summary"]["live_gross_win"] = round(float(row[1]), 2)
        report["summary"]["live_gross_loss"] = round(float(row[2]), 2)

        # ── Last 24h trades (LIVE only) ──
        rows = conn.execute(text("""
            SELECT COUNT(*), COALESCE(SUM(pnl), 0)
            FROM trades
            WHERE trading_mode = 'live'
                  AND timestamp >= NOW() - INTERVAL '24 hours'
        """)).fetchall()
        report["summary"]["trades_24h"] = rows[0][0]
        report["summary"]["pnl_24h"] = round(float(rows[0][1]), 2)

        # ── Open positions (LIVE only) ──
        rows = conn.execute(text("""
            SELECT strategy, market_slug, side, size, entry_price, timestamp
            FROM trades
            WHERE trading_mode = 'live' AND settled = false
            ORDER BY timestamp DESC
        """)).fetchall()
        report["summary"]["open_positions"] = len(rows)
        report["summary"]["open_exposure"] = round(sum(float(r[3] or 0) for r in rows), 2)

        # ── Wallet health: bot_state vs real equity ──
        real_equity = _fetch_real_equity()
        bot_live_bankroll = report["accounts"].get("live", {}).get("bankroll", 0)
        report["wallet_health"]["bot_state_bankroll"] = bot_live_bankroll
        report["wallet_health"]["real_equity"] = round(real_equity, 2) if real_equity is not None else None
        if real_equity is not None:
            drift = round(abs(bot_live_bankroll - real_equity), 2)
            report["wallet_health"]["drift"] = drift
            report["wallet_health"]["drift_pct"] = round(drift / real_equity * 100, 2) if real_equity > 0 else 0
        else:
            report["wallet_health"]["drift"] = None
            report["wallet_health"]["drift_pct"] = None

        # ── Anomalies ──
        # Check heartbeats
        for name, hb in report["heartbeats"].items():
            if hb["age_minutes"] > 60:
                report["anomalies"].append({
                    "type": "stale_heartbeat",
                    "strategy": name,
                    "detail": f"No heartbeat in {hb['age_minutes']:.0f}m",
                    "level": "warning" if hb["age_minutes"] < 240 else "critical"
                })

        # Check losing strategies
        for name, strat in report["strategies"].items():
            if strat["pnl_7d"] < -50 and strat["trades_7d"] >= 5:
                report["anomalies"].append({
                    "type": "losing_strategy",
                    "strategy": name,
                    "detail": f"PnL ${strat['pnl_7d']:.2f} over {strat['trades_7d']} trades",
                    "level": "critical" if strat["pnl_7d"] < -200 else "warning"
                })

        # WR RULE: Any strategy below 50% WR enters improvement stage
        for name, strat in report["strategies"].items():
            if strat["trades_7d"] >= 10 and strat["win_rate"] < 0.50:
                if strat["pnl_7d"] < 0:
                    report["anomalies"].append({
                        "type": "low_wr_critical",
                        "strategy": name,
                        "detail": f"WR {strat['win_rate']:.1%} + losing ${strat['pnl_7d']:.2f} — improvement stage required",
                        "level": "critical",
                        "action": "disable_and_audit"
                    })
                else:
                    report["anomalies"].append({
                        "type": "low_wr_warning",
                        "strategy": name,
                        "detail": f"WR {strat['win_rate']:.1%} but profitable ${strat['pnl_7d']:.2f} — monitor win sizing",
                        "level": "warning",
                        "action": "monitor"
                    })

        # Wallet drift anomaly
        wh = report["wallet_health"]
        if wh["drift"] is not None and wh["drift"] > 1.0:
            report["anomalies"].append({
                "type": "wallet_drift",
                "detail": f"Bot state ${wh['bot_state_bankroll']:.2f} vs real ${wh['real_equity']:.2f} — drift ${wh['drift']:.2f} ({wh['drift_pct']:.1f}%)",
                "level": "critical" if wh["drift"] > 10 else "warning"
            })

    class DecimalEncoder(json.JSONEncoder):
        def default(self, o):
            if isinstance(o, Decimal):
                return float(o)
            return super().default(o)

    print(json.dumps(report, indent=2, cls=DecimalEncoder))

if __name__ == "__main__":
    main()
