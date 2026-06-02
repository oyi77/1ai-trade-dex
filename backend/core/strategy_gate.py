"""Strategy Gating Pipeline — Paper → Fronttest → Shadow → Live.

Every strategy must pass through this pipeline before live capital is at risk:

1. PAPER TRADE: Run in paper mode (no real $)
2. FRONTTEST VALIDATION: Auto-check after 14d trial:
   - Min 20 trades settled via Gamma
   - Win rate ≥ 55%
   - Net PnL > 0
3. SHADOW MODE: Run in shadow (parallel to live, no real orders)
4. LIVE GATE: Final approval before real capital deployment

The gate is enforced in strategy_executor.py before ANY live order.
"""

from __future__ import annotations
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from backend.config import settings
from backend.models.database import StrategyConfig
from loguru import logger

# Minimum thresholds for each pipeline stage
STAGE_REQUIREMENTS = {
    "paper": {
        "min_trades": 5,
        "min_days": 3,
        "description": "Run in paper mode to generate initial signals",
    },
    "fronttest": {
        "min_trades": 20,
        "min_days": 7,
        "min_win_rate": 0.55,
        "min_pnl": 0.0,
        "description": "Validate paper performance meets profitability thresholds",
    },
    "shadow": {
        "min_trades": 30,
        "min_days": 7,
        "min_win_rate": 0.50,
        "min_pnl": 0.0,
        "max_drawdown": 0.15,
        "description": "Run parallel to live without executing real orders",
    },
    "live": {
        "description": "Full live execution with real capital",
    },
}

# Which strategies are currently allowed to skip shadow (pre-validated)
SHADOW_EXEMPT = set()


class StrategyGate:
    """Gate controller — checks if a strategy can advance to the next pipeline stage."""

    @staticmethod
    def get_stage(strategy_name: str, db: Session) -> str:
        """Return the current pipeline stage for a strategy."""
        cfg = db.query(StrategyConfig).filter_by(strategy_name=strategy_name).first()
        if not cfg:
            return "paper"
        mode = (cfg.mode or "paper").lower()
        if mode == "live":
            return "live"
        if mode == "shadow":
            return "shadow"
        if cfg.enabled:
            return "fronttest"
        return "paper"

    @staticmethod
    def can_execute_live(strategy_name: str, db: Session) -> tuple[bool, str]:
        """Can this strategy execute live trades RIGHT NOW?"""
        stage = StrategyGate.get_stage(strategy_name, db)
        logger.info(f"[StrategyGate] {strategy_name}: stage={stage}")

        if stage == "live":
            return True, "live mode active"

        if stage in ("shadow", "fronttest"):
            return False, f"still in {stage} stage, not live"

        # Paper mode
        return False, "paper mode only"

    @staticmethod
    def can_advance_to_live(strategy_name: str, db: Session) -> dict:
        """Check if strategy meets ALL requirements for live promotion."""
        cfg = db.query(StrategyConfig).filter_by(strategy_name=strategy_name).first()
        if not cfg:
            return {"approved": False, "reason": "strategy config not found"}

        # Paper: enough trades
        paper_count = _count_paper_trades(strategy_name, db)
        if paper_count < STAGE_REQUIREMENTS["fronttest"]["min_trades"]:
            return {
                "approved": False,
                "reason": f"paper trades ({paper_count}) < minimum ({STAGE_REQUIREMENTS['fronttest']['min_trades']})",
                "paper_trades": paper_count,
                "required_trades": STAGE_REQUIREMENTS["fronttest"]["min_trades"],
            }

        # Fronttest: win rate + PnL
        fronttest = _check_fronttest(strategy_name, db)
        if not fronttest["passed"]:
            return fronttest

        # Shadow mode check (paper-only strats skip shadow for now)
        if strategy_name not in SHADOW_EXEMPT:
            shadow = _check_shadow(strategy_name, db)
            if not shadow["passed"]:
                return shadow

        return {
            "approved": True,
            "reason": "passed all gates — ready for live",
            "paper_trades": paper_count,
            "fronttest": fronttest,
        }

    @staticmethod
    def auto_promote(db: Session) -> list[dict]:
        """Auto-promote strategies that meet the next stage requirements."""
        from backend.models.database import StrategyConfig

        results = []
        configs = db.query(StrategyConfig).all()

        for cfg in configs:
            name = cfg.strategy_name
            # Skip strategies in rehab — let rehab pipeline handle them
            if cfg.disabled_at is not None:
                continue
            stage = StrategyGate.get_stage(name, db)
            promoted = False

            if stage == "paper" and cfg.enabled:
                # Check if enough paper trades to enter fronttest
                paper_count = _count_paper_trades(name, db)
                if paper_count >= STAGE_REQUIREMENTS["fronttest"]["min_trades"]:
                    logger.info(
                        f"[GATE] {name}: paper→fronttest ({paper_count} trades)"
                    )
                    promoted = True

            elif stage == "fronttest":
                check = StrategyGate.can_advance_to_live(name, db)
                if check["approved"]:
                    if name in SHADOW_EXEMPT:
                        # Skip shadow, go directly to live
                        cfg.mode = "live"
                        db.commit()
                        results.append(
                            {"strategy": name, "from": "fronttest", "to": "live"}
                        )
                        logger.info(
                            f"[GATE] {name}: fronttest→live (exempt from shadow)"
                        )
                    else:
                        cfg.mode = "shadow"
                        db.commit()
                        results.append(
                            {"strategy": name, "from": "fronttest", "to": "shadow"}
                        )
                        logger.info(f"[GATE] {name}: fronttest→shadow")
                    promoted = True

            elif stage == "shadow":
                check = StrategyGate.can_advance_to_live(name, db)
                if check["approved"]:
                    cfg.mode = "live"
                    db.commit()
                    results.append({"strategy": name, "from": "shadow", "to": "live"})
                    logger.info(f"[GATE] {name}: shadow→live")
                    promoted = True

            if promoted:
                results.append({"strategy": name, "stage": stage})

        return results


def _count_paper_trades(strategy_name: str, db: Session) -> int:
    """Count paper trades with real settlement (not simulated)."""
    from sqlalchemy import text

    return (
        db.execute(
            text("""
        SELECT COUNT(*) FROM trades
        WHERE strategy = :s AND trading_mode = 'paper'
          AND result IN ('win', 'loss')
          AND condition_id IS NOT NULL
    """),
            {"s": strategy_name},
        ).scalar()
        or 0
    )


def _check_fronttest(strategy_name: str, db: Session) -> dict:
    """Check fronttest requirements."""
    from backend.models.database import Trade

    trades = (
        db.query(Trade)
        .filter(
            Trade.strategy == strategy_name,
            Trade.trading_mode == "paper",
            Trade.result.in_(["win", "loss"]),
            Trade.condition_id.isnot(None),
        )
        .all()
    )

    if len(trades) < STAGE_REQUIREMENTS["fronttest"]["min_trades"]:
        return {
            "approved": False,
            "reason": f"fronttest: {len(trades)} verified trades < {STAGE_REQUIREMENTS['fronttest']['min_trades']}",
            "trades": len(trades),
            "required": STAGE_REQUIREMENTS["fronttest"]["min_trades"],
            "passed": False,
        }

    wins = sum(1 for t in trades if t.result == "win")
    wr = wins / len(trades)
    pnl = sum(t.pnl or 0.0 for t in trades)

    if wr < STAGE_REQUIREMENTS["fronttest"]["min_win_rate"]:
        return {
            "approved": False,
            "reason": f"fronttest win rate {wr:.1%} < {STAGE_REQUIREMENTS['fronttest']['min_win_rate']:.0%}",
            "win_rate": wr,
            "required_wr": STAGE_REQUIREMENTS["fronttest"]["min_win_rate"],
            "passed": False,
        }

    if pnl < STAGE_REQUIREMENTS["fronttest"]["min_pnl"]:
        return {
            "approved": False,
            "reason": f"fronttest PnL ${pnl:.2f} < ${STAGE_REQUIREMENTS['fronttest']['min_pnl']:.2f}",
            "pnl": pnl,
            "passed": False,
        }

    return {
        "approved": True,
        "passed": True,
        "trades": len(trades),
        "win_rate": wr,
        "pnl": pnl,
    }


def _check_shadow(strategy_name: str, db: Session) -> dict:
    """Check shadow mode requirements."""
    from backend.models.database import Trade

    trades = (
        db.query(Trade)
        .filter(
            Trade.strategy == strategy_name,
            Trade.trading_mode == "shadow",
            Trade.result.in_(["win", "loss"]),
        )
        .all()
    )

    if len(trades) < STAGE_REQUIREMENTS["shadow"]["min_trades"]:
        return {
            "approved": False,
            "reason": f"shadow: {len(trades)} trades < {STAGE_REQUIREMENTS['shadow']['min_trades']}",
            "trades": len(trades),
            "passed": False,
        }

    wins = sum(1 for t in trades if t.result == "win")
    wr = wins / len(trades)
    pnl = sum(t.pnl or 0.0 for t in trades)

    if wr < STAGE_REQUIREMENTS["shadow"]["min_win_rate"]:
        return {
            "approved": False,
            "reason": f"shadow win rate {wr:.1%} < {STAGE_REQUIREMENTS['shadow']['min_win_rate']:.0%}",
            "win_rate": wr,
            "passed": False,
        }

    if pnl < STAGE_REQUIREMENTS["shadow"]["min_pnl"]:
        return {
            "approved": False,
            "reason": f"shadow PnL ${pnl:.2f} < ${STAGE_REQUIREMENTS['shadow']['min_pnl']:.2f}",
            "pnl": pnl,
            "passed": False,
        }

    return {
        "approved": True,
        "passed": True,
        "trades": len(trades),
        "win_rate": wr,
        "pnl": pnl,
    }


# =========================================================================
# Risk Layer — auto-disable strategies that exceed loss thresholds
# =========================================================================

MAX_DAILY_LOSS_PER_STRATEGY = settings.RISK_MAX_DAILY_LOSS_PER_STRATEGY_USD
MAX_TOTAL_DRAWDOWN_PCT = settings.RISK_MAX_TOTAL_DRAWDOWN_PCT


def check_risk_and_disable(db) -> list[str]:
    """
    Check all enabled strategies against risk thresholds.
    Auto-disable any that exceed limits.
    Returns list of disabled strategy names.
    """
    from sqlalchemy import text

    disabled = []
    today = datetime.now(timezone.utc).date()

    # 1. Per-strategy daily loss check
    strats = db.execute(text("""
        SELECT strategy_name FROM strategy_config
        WHERE enabled = true AND mode = 'live'
    """)).fetchall()

    for (sname,) in strats:
        daily_loss = (
            db.execute(
                text("""
            SELECT COALESCE(SUM(pnl), 0) FROM trades
            WHERE strategy = :s AND trading_mode = 'live'
              AND DATE(timestamp) = :today
        """),
                {"s": sname, "today": today},
            ).scalar()
            or 0
        )

        if daily_loss < -MAX_DAILY_LOSS_PER_STRATEGY:
            from backend.models.database import StrategyConfig
            from backend.core.strategy_health import disable_for_rehab

            cfg = db.query(StrategyConfig).filter_by(strategy_name=sname).first()
            if cfg and cfg.enabled:
                disable_for_rehab(cfg)
                db.flush()
            disabled.append(
                f"{sname}: daily loss ${abs(daily_loss):.2f} > ${MAX_DAILY_LOSS_PER_STRATEGY}"
            )
            logger.warning(f"[RISK] Rehab {sname}: daily loss ${abs(daily_loss):.2f}")

    # 2. Total drawdown check
    total_pnl = db.execute(text("""
        SELECT COALESCE(SUM(pnl), 0) FROM trades
        WHERE trading_mode = 'live' AND settled = true
    """)).scalar() or 0

    # Use live_initial_bankroll from BotState as the session-start reference.
    # This is the capital the user began live trading with.
    from backend.models.database import BotState

    bot_state = db.query(BotState).filter_by(mode="live").first()
    if bot_state and bot_state.live_initial_bankroll is not None:
        initial = bot_state.live_initial_bankroll
    elif bot_state and bot_state.paper_initial_bankroll is not None:
        initial = bot_state.paper_initial_bankroll
    else:
        initial = 100.0
    drawdown_pct = abs(min(0, total_pnl)) / initial * 100

    if drawdown_pct > MAX_TOTAL_DRAWDOWN_PCT and total_pnl < 0:
        from backend.models.database import StrategyConfig
        from backend.core.strategy_health import disable_for_rehab

        live_strats = (
            db.query(StrategyConfig)
            .filter(
                StrategyConfig.mode == "live",
                StrategyConfig.enabled.is_(True),
            )
            .all()
        )
        for cfg in live_strats:
            disable_for_rehab(cfg)
        if live_strats:
            db.flush()
        disabled.append(
            f"ALL LIVE: drawdown {drawdown_pct:.1f}% > {MAX_TOTAL_DRAWDOWN_PCT}%"
        )
        logger.warning(
            f"[RISK] EMERGENCY: All live strats enter rehab ({drawdown_pct:.1f}% drawdown)"
        )

    if disabled:
        db.commit()

    return disabled
