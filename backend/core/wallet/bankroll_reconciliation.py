"""DEPRECATED: Use backend.core.bankroll_reconciliation instead.

BotState bankroll reconciliation utilities.

The Trade table is the durable ledger. BotState bankroll fields are derived
caches used for sizing, dashboards, and fast risk checks; when old accounting
bugs corrupt those caches, recompute them from source-of-truth data instead of
mutating or deleting historical trades.


This module will be removed in a future release.
"""

from __future__ import annotations
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Iterable, Optional

from sqlalchemy import case, func, update
from sqlalchemy.orm import Session

from backend.config import settings
from backend.models.audit_logger import log_audit_event
from backend.models.database import BotState, Trade

from loguru import logger


@dataclass
class BankrollReconciliationReport:
    """One-mode reconciliation result."""

    mode: str
    source: str
    applied: bool
    old_bankroll: float
    new_bankroll: float
    old_total_pnl: float
    new_total_pnl: float
    old_trade_count: int
    new_trade_count: int
    old_win_count: int
    new_win_count: int
    open_exposure: float
    realized_pnl: float
    drift_bankroll: float
    drift_pnl: float
    pm_portfolio_value: Optional[float] = None
    warnings: list[str] = field(default_factory=list)

    @property
    def has_drift(self) -> bool:
        return (
            abs(self.drift_bankroll) > 0.01
            or abs(self.drift_pnl) > 0.01
            or self.old_trade_count != self.new_trade_count
            or self.old_win_count != self.new_win_count
        )

    def to_dict(self) -> dict:
        data = asdict(self)
        data["has_drift"] = self.has_drift
        return data


@dataclass(frozen=True)
class PolymarketProfileTradeStats:
    """Profile-level Polymarket market-count statistics."""

    traded_count: int
    closed_count: int
    winning_count: int
    losing_count: int
    open_position_count: int = 0
    stale_open_position_count: int = 0
    redeemable_position_count: int = 0
    open_position_value: float = 0.0
    open_position_initial_value: float = 0.0

    @property
    def win_rate(self) -> float:
        denominator = self.winning_count + self.losing_count
        return self.winning_count / denominator if denominator > 0 else 0.0


def get_polymarket_wallet_address() -> Optional[str]:
    """Return the wallet/proxy address used by Polymarket Data API."""

    return settings.POLYMARKET_BUILDER_ADDRESS or settings.POLYMARKET_WALLET_ADDRESS


async def fetch_pm_open_position_value(wallet: Optional[str] = None) -> Optional[float]:
    """Fetch open-position market value from Polymarket Data API.

    The /value endpoint excludes idle USDC cash, so it is not total account
    equity by itself. Total live equity is cash balance + this open value.

    Returns None on missing wallet, non-200 responses, malformed payloads, or
    transient network failures. Callers decide whether that is fatal.
    """

    wallet_address = wallet or get_polymarket_wallet_address()
    if not wallet_address:
        return None

    try:
        import httpx

        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(
                f"{settings.DATA_API_URL}/value",
                params={"user": wallet_address.lower()},
            )
        if resp.status_code != 200:
            logger.warning(
                "PM open position value fetch returned HTTP %s for wallet %s",
                resp.status_code,
                wallet_address[:10],
            )
            return None

        data = resp.json()
        if isinstance(data, list) and data:
            value = data[0].get("value", 0)
        elif isinstance(data, dict):
            value = data.get("value", 0)
        else:
            return None

        return float(value)
    except Exception as exc:
        logger.warning("PM open position value fetch failed: %s", exc)
        return None


async def fetch_pm_portfolio_value(wallet: Optional[str] = None) -> Optional[float]:
    """Backward-compatible alias for open-position value."""

    return await fetch_pm_open_position_value(wallet)


async def fetch_pm_total_equity(wallet: Optional[str] = None) -> Optional[float]:
    """Fetch live total equity as USDC cash + PM open-position value."""

    open_value = await fetch_pm_open_position_value(wallet)
    if open_value is None:
        return None

    wallet_address = wallet or get_polymarket_wallet_address()
    if not wallet_address:
        return None

    cash = 0.0
    try:
        import httpx
        from backend.config import settings

        tokens = {
            "USDC.e": settings.USDC_E_ADDRESS,
            "USDC Native": settings.USDC_NATIVE_ADDRESS,
            "pUSD": settings.PUSD_ADDRESS,
        }

        rpc_url = settings.QUICKNODE_RPC_URL

        async with httpx.AsyncClient(timeout=10.0) as client:
            for name, addr in tokens.items():
                data = "0x70a08231000000000000000000000000" + wallet_address.lower()[2:]
                payload = {
                    "jsonrpc": "2.0",
                    "method": "eth_call",
                    "params": [{"to": addr, "data": data}, "latest"],
                    "id": 1,
                }
                try:
                    res = await client.post(
                        rpc_url,
                        json=payload,
                        headers={"User-Agent": "polyedge-finance"},
                    )
                    if res.status_code == 200 and "result" in res.json():
                        hex_val = res.json()["result"]
                        if hex_val == "0x" or not hex_val:
                            hex_val = "0x0"
                        cash += int(hex_val, 16) / 1e6
                except Exception as e:
                    logger.warning(
                        f"Failed to fetch {name} balance in reconciliation: {e}"
                    )

        logger.info(f"Total cash balance from RPC: ${cash:.2f}")
    except Exception as exc:
        logger.warning("Polygon RPC cash fetch failed, falling back to CLOB: %s", exc)
        # 2. Fallback to CLOB API if RPC fails
        try:
            from backend.data.polymarket_clob import clob_from_settings

            clob = clob_from_settings(mode="live")
            async with clob:
                await clob.create_or_derive_api_key()
                balance = await clob.get_wallet_balance()
            if balance.get("error"):
                logger.warning(
                    "CLOB cash balance fetch failed: %s", balance.get("error")
                )
                return None
            cash = float(balance.get("usdc_balance") or 0.0)
        except Exception as clob_exc:
            logger.warning("CLOB cash balance fetch failed: %s", clob_exc)
            return None

    return round(cash + float(open_value), 6)


async def fetch_pm_profile_pnl(wallet: Optional[str] = None) -> Optional[float]:
    """Fetch Polymarket profile/account PnL from the public user PnL API.

    This matches the public profile/dashboard series semantics more closely than
    the local settled-trade ledger. Returns the latest cumulative profile PnL
    point when available.
    """

    wallet_address = wallet or get_polymarket_wallet_address()
    if not wallet_address:
        return None

    try:
        import httpx

        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(
                "https://user-pnl-api.polymarket.com/user-pnl",
                params={
                    "user_address": wallet_address.lower(),
                    "interval": "all",
                    "fidelity": "1d",
                },
                headers={"User-Agent": "polyedge-finance"},
            )

        if resp.status_code != 200:
            logger.warning(
                "PM profile PnL fetch returned HTTP %s for wallet %s",
                resp.status_code,
                wallet_address[:10],
            )
            return None

        data = resp.json()
        if not isinstance(data, list) or not data:
            return None

        latest = data[-1]
        if not isinstance(latest, dict):
            return None

        pnl_value = latest.get("p")
        if pnl_value is None:
            return None

        return round(float(pnl_value), 6)
    except Exception as exc:
        logger.warning("PM profile PnL fetch failed: %s", exc)
        return None


async def fetch_pm_traded_count(wallet: Optional[str] = None) -> Optional[int]:
    """Fetch Polymarket profile "markets traded" count for a wallet.

    Polymarket's public profile "Predictions" total is backed by the Data API
    `/traded` endpoint. This is a market/profile-level count, not equivalent to
    the local Trade ledger row count where one market/order can produce multiple
    rows across settlement, import, and strategy bookkeeping paths.
    """

    wallet_address = wallet or get_polymarket_wallet_address()
    if not wallet_address:
        return None

    try:
        import httpx

        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(
                f"{settings.DATA_API_URL}/traded",
                params={"user": wallet_address.lower()},
                headers={"User-Agent": "polyedge-finance"},
            )

        if resp.status_code != 200:
            logger.warning(
                "PM traded-count fetch returned HTTP %s for wallet %s",
                resp.status_code,
                wallet_address[:10],
            )
            return None

        data = resp.json()
        if not isinstance(data, dict):
            return None

        traded = data.get("traded")
        if traded is None:
            return None

        return int(traded)
    except Exception as exc:
        logger.warning("PM traded-count fetch failed: %s", exc)
        return None


async def fetch_pm_profile_trade_stats(
    wallet: Optional[str] = None,
) -> Optional[PolymarketProfileTradeStats]:
    """Fetch profile-aligned Polymarket trade count and closed-market W/L.

    `/traded` returns the public profile markets-traded count. The
    `/closed-positions` endpoint can include multiple rows for one market, so we
    group by market slug/condition and sum realized PnL before classifying each
    closed market as win/loss/flat.
    """

    wallet_address = wallet or get_polymarket_wallet_address()
    if not wallet_address:
        return None

    try:
        import httpx

        async with httpx.AsyncClient(
            timeout=12.0,
            headers={"User-Agent": "polyedge-finance"},
        ) as client:
            traded_resp = await client.get(
                f"{settings.DATA_API_URL}/traded",
                params={"user": wallet_address.lower()},
            )
            if traded_resp.status_code != 200:
                logger.warning(
                    "PM traded-count fetch returned HTTP %s for wallet %s",
                    traded_resp.status_code,
                    wallet_address[:10],
                )
                return None

            traded_data = traded_resp.json()
            if not isinstance(traded_data, dict) or traded_data.get("traded") is None:
                return None
            traded_count = int(traded_data["traded"])

            closed_pnl_by_market: dict[str, float] = {}
            offset = 0
            limit = 50
            while True:
                closed_resp = await client.get(
                    f"{settings.DATA_API_URL}/closed-positions",
                    params={
                        "user": wallet_address.lower(),
                        "limit": limit,
                        "offset": offset,
                    },
                )
                if closed_resp.status_code != 200:
                    logger.warning(
                        "PM closed-position fetch returned HTTP %s for wallet %s",
                        closed_resp.status_code,
                        wallet_address[:10],
                    )
                    return None

                rows = closed_resp.json()
                if not isinstance(rows, list):
                    return None
                if not rows:
                    break

                for row in rows:
                    if not isinstance(row, dict):
                        continue
                    market_key = (
                        row.get("slug") or row.get("conditionId") or row.get("asset")
                    )
                    if not market_key:
                        continue
                    realized = row.get("realizedPnl")
                    closed_pnl_by_market[str(market_key)] = closed_pnl_by_market.get(
                        str(market_key), 0.0
                    ) + float(realized or 0.0)

                if len(rows) < limit:
                    break
                offset += limit

            open_positions: list[dict] = []
            offset = 0
            while True:
                positions_resp = await client.get(
                    f"{settings.DATA_API_URL}/positions",
                    params={
                        "user": wallet_address.lower(),
                        "limit": limit,
                        "offset": offset,
                    },
                )
                if positions_resp.status_code != 200:
                    logger.warning(
                        "PM open-position fetch returned HTTP %s for wallet %s",
                        positions_resp.status_code,
                        wallet_address[:10],
                    )
                    return None

                position_rows = positions_resp.json()
                if not isinstance(position_rows, list):
                    return None
                if not position_rows:
                    break

                open_positions.extend(
                    row for row in position_rows if isinstance(row, dict)
                )
                if len(position_rows) < limit:
                    break
                offset += limit

            winning_count = sum(1 for pnl in closed_pnl_by_market.values() if pnl > 0)
            losing_count = sum(1 for pnl in closed_pnl_by_market.values() if pnl < 0)
            today = datetime.now(timezone.utc).date().isoformat()
            stale_open_position_count = sum(
                1
                for row in open_positions
                if str(row.get("endDate") or "")[:10] < today
            )
            redeemable_position_count = sum(
                1 for row in open_positions if bool(row.get("redeemable"))
            )
            open_position_value = sum(
                float(row.get("currentValue") or 0.0) for row in open_positions
            )
            open_position_initial_value = sum(
                float(row.get("initialValue") or 0.0) for row in open_positions
            )
            return PolymarketProfileTradeStats(
                traded_count=traded_count,
                closed_count=winning_count + losing_count,
                winning_count=winning_count,
                losing_count=losing_count,
                open_position_count=len(open_positions),
                stale_open_position_count=stale_open_position_count,
                redeemable_position_count=redeemable_position_count,
                open_position_value=round(open_position_value, 6),
                open_position_initial_value=round(open_position_initial_value, 6),
            )
    except Exception as exc:
        logger.warning("PM profile trade stats fetch failed: %s", exc)
        return None


def _realized_trade_stats(db: Session, mode: str) -> tuple[int, float, int]:
    """Return count, realized PnL, and win count from settled ledger rows."""

    trade_count, realized_pnl, win_count = (
        db.query(
            func.count(Trade.id),
            func.coalesce(func.sum(func.coalesce(Trade.pnl, -Trade.size)), 0.0),
            func.coalesce(func.sum(case((Trade.result == "win", 1), else_=0)), 0),
        )
        .filter(
            Trade.settled.is_(True),
            Trade.trading_mode == mode,
            Trade.result.in_(("win", "loss", "closed")),
        )
        .first()
    )
    return (
        int(trade_count or 0),
        round(float(realized_pnl or 0.0), 2),
        int(win_count or 0),
    )


def _open_exposure(db: Session, mode: str) -> float:
    exposure = (
        db.query(func.coalesce(func.sum(Trade.size), 0.0))
        .filter(Trade.settled.is_(False), Trade.trading_mode == mode)
        .scalar()
    )
    return round(float(exposure or 0.0), 2)


def _initial_bankroll_for_mode(mode: str, state: Optional[BotState] = None) -> float:
    if (
        mode == "paper"
        and state is not None
        and state.paper_initial_bankroll is not None
    ):
        return float(state.paper_initial_bankroll)
    if (
        mode == "testnet"
        and state is not None
        and state.testnet_initial_bankroll is not None
    ):
        return float(state.testnet_initial_bankroll)
    if mode == "live" and state is not None and state.live_initial_bankroll is not None:
        return float(state.live_initial_bankroll)
    if mode == "testnet":
        return 100.0
    return float(settings.INITIAL_BANKROLL)


def _available_bankroll_for_mode(mode: str, bankroll: float) -> float:
    """Available bankroll/cash must never be negative in finance-facing state."""

    if mode in {"paper", "testnet"}:
        return max(0.0, bankroll)
    return bankroll


def _mode_bankroll(state: BotState, mode: str) -> float:
    if mode == "paper":
        return float(
            state.paper_bankroll
            if state.paper_bankroll is not None
            else state.bankroll or 0.0
        )
    if mode == "testnet":
        return float(
            state.testnet_bankroll
            if state.testnet_bankroll is not None
            else state.bankroll or 0.0
        )
    return float(state.bankroll if state.bankroll is not None else 0.0)


def _mode_pnl(state: BotState, mode: str) -> float:
    if mode == "paper":
        return float(state.paper_pnl or 0.0)
    if mode == "testnet":
        return float(state.testnet_pnl or 0.0)
    return float(state.total_pnl or 0.0)


def _mode_trade_count(state: BotState, mode: str) -> int:
    if mode == "paper":
        return int(state.paper_trades or 0)
    if mode == "testnet":
        return int(state.testnet_trades or 0)
    return int(state.total_trades or 0)


def _mode_win_count(state: BotState, mode: str) -> int:
    if mode == "paper":
        return int(state.paper_wins or 0)
    if mode == "testnet":
        return int(state.testnet_wins or 0)
    return int(state.winning_trades or 0)


def _set_mode_state(
    state: BotState,
    mode: str,
    bankroll: float,
    total_pnl: float,
    trade_count: int,
    win_count: int,
) -> None:
    """Update the canonical and compatibility fields for one mode."""

    if mode == "paper":
        state.bankroll = bankroll
        state.total_pnl = total_pnl
        state.total_trades = trade_count
        state.winning_trades = win_count
        state.paper_bankroll = bankroll
        state.paper_pnl = total_pnl
        state.paper_trades = trade_count
        state.paper_wins = win_count
    elif mode == "testnet":
        state.bankroll = bankroll
        state.total_pnl = total_pnl
        state.total_trades = trade_count
        state.winning_trades = win_count
        state.testnet_bankroll = bankroll
        state.testnet_pnl = total_pnl
        state.testnet_trades = trade_count
        state.testnet_wins = win_count
    else:
        state.bankroll = bankroll
        state.total_pnl = total_pnl
        state.total_trades = trade_count
        state.winning_trades = win_count

    state.last_sync_at = datetime.now(timezone.utc)


def _mode_update_values(
    state: BotState,
    mode: str,
    bankroll: float,
    total_pnl: float,
    trade_count: int,
    win_count: int,
) -> dict:
    """Return direct SQL update values for one BotState row.

    Updating by primary key avoids stale ORM rows for other modes re-flushing old
    financial values during unrelated commits in long-lived scheduler sessions.
    """

    values = {
        "bankroll": bankroll,
        "total_pnl": total_pnl,
        "total_trades": trade_count,
        "winning_trades": win_count,
        "last_sync_at": datetime.now(timezone.utc),
    }
    if mode == "paper":
        values.update(
            {
                "paper_bankroll": bankroll,
                "paper_pnl": total_pnl,
                "paper_trades": trade_count,
                "paper_wins": win_count,
            }
        )
    elif mode == "testnet":
        values.update(
            {
                "testnet_bankroll": bankroll,
                "testnet_pnl": total_pnl,
                "testnet_trades": trade_count,
                "testnet_wins": win_count,
            }
        )
    elif report_live_sync_error := getattr(state, "last_live_sync_error", None):
        values["last_live_sync_error"] = report_live_sync_error
    else:
        values["track_bankroll_realtime"] = bankroll
        values["track_pnl_realtime"] = total_pnl
    return values


def _snapshot_state(state: BotState, mode: str) -> dict:
    return {
        "mode": mode,
        "bankroll": _mode_bankroll(state, mode),
        "total_pnl": _mode_pnl(state, mode),
        "trade_count": _mode_trade_count(state, mode),
        "win_count": _mode_win_count(state, mode),
        "last_sync_at": state.last_sync_at.isoformat() if state.last_sync_at else None,
        "last_live_sync_error": state.last_live_sync_error,
    }


def _build_report(
    db: Session,
    state: BotState,
    mode: str,
    source: str,
    applied: bool,
    pm_portfolio_value: Optional[float],
) -> BankrollReconciliationReport:
    trade_count, realized_pnl, win_count = _realized_trade_stats(db, mode)
    open_exposure = _open_exposure(db, mode)
    old_bankroll = round(_mode_bankroll(state, mode), 2)
    old_total_pnl = round(_mode_pnl(state, mode), 2)

    warnings: list[str] = []
    if mode == "live":
        if pm_portfolio_value is None or pm_portfolio_value <= 0:
            new_bankroll = old_bankroll
            new_total_pnl = old_total_pnl
            warnings.append(
                "PM total equity unavailable; live bankroll cache was not changed"
            )
        else:
            new_bankroll = round(float(pm_portfolio_value), 2)
            # Live total_pnl uses realized PnL from settled trades,
            # not bankroll delta (CLOB balance excludes open positions)
            new_total_pnl = realized_pnl
    else:
        derived_bankroll = round(
            _initial_bankroll_for_mode(mode, state=state)
            + realized_pnl
            - open_exposure,
            2,
        )
        new_bankroll = round(_available_bankroll_for_mode(mode, derived_bankroll), 2)
        new_total_pnl = realized_pnl
        if derived_bankroll < 0:
            warnings.append(
                f"Derived {mode} available bankroll was negative (${derived_bankroll:.2f}); clamped to $0.00 while preserving PnL"
            )

    return BankrollReconciliationReport(
        mode=mode,
        source=source,
        applied=applied,
        old_bankroll=old_bankroll,
        new_bankroll=new_bankroll,
        old_total_pnl=old_total_pnl,
        new_total_pnl=new_total_pnl,
        old_trade_count=_mode_trade_count(state, mode),
        new_trade_count=trade_count,
        old_win_count=_mode_win_count(state, mode),
        new_win_count=win_count,
        open_exposure=open_exposure,
        realized_pnl=realized_pnl,
        drift_bankroll=round(abs(old_bankroll - new_bankroll), 2),
        drift_pnl=round(abs(old_total_pnl - new_total_pnl), 2),
        pm_portfolio_value=(
            round(float(pm_portfolio_value), 2)
            if pm_portfolio_value is not None
            else None
        ),
        warnings=warnings,
    )


async def reconcile_bot_state(
    db: Session,
    modes: Iterable[str] = ("paper", "testnet", "live"),
    apply: bool = False,
    commit: bool = False,
    source: str = "runtime_reconcile",
) -> list[BankrollReconciliationReport]:
    """Reconcile BotState caches for selected modes.

    Set apply=False for dry-run reporting. When apply=True, callers may either
    commit themselves or pass commit=True for an atomic commit here.
    """

    reports: list[BankrollReconciliationReport] = []
    pm_portfolio_value: Optional[float] = None
    mode_list = tuple(modes)
    if "live" in mode_list:
        pm_portfolio_value = await fetch_pm_total_equity()

    previous_live_update_permission = db.info.get("allow_live_financial_update")
    db.info["allow_live_financial_update"] = True
    try:
        db.expire_all()
        for mode in mode_list:
            state = db.query(BotState).filter_by(mode=mode).first()
            if not state:
                logger.warning("No BotState found for mode=%s", mode)
                continue

            report = _build_report(
                db=db,
                state=state,
                mode=mode,
                source=source,
                applied=apply,
                pm_portfolio_value=pm_portfolio_value if mode == "live" else None,
            )
            reports.append(report)

            if apply and report.has_drift:
                old_state = _snapshot_state(state, mode)
                update_values = _mode_update_values(
                    state,
                    mode,
                    report.new_bankroll,
                    report.new_total_pnl,
                    report.new_trade_count,
                    report.new_win_count,
                )
                if mode == "live":
                    if report.pm_portfolio_value is None:
                        update_values["last_live_sync_error"] = (
                            "PM total equity unavailable"
                        )
                    else:
                        update_values["last_live_sync_error"] = None
                db.execute(
                    update(BotState)
                    .where(BotState.id == state.id, BotState.mode == mode)
                    .values(**update_values)
                )
                db.flush()
                db.refresh(state)
                log_audit_event(
                    db=db,
                    event_type="BOTSTATE_RECONCILED",
                    entity_type="BOT_STATE",
                    entity_id=mode,
                    old_value=old_state,
                    new_value={
                        **_snapshot_state(state, mode),
                        "report": report.to_dict(),
                    },
                    user_id=source,
                )
                try:
                    from backend.models.database import TransactionEvent

                    delta = report.new_bankroll - report.old_bankroll
                    event = TransactionEvent(
                        type="reconciliation_adjustment",
                        amount=delta,
                        balance_after=report.new_bankroll,
                        context={
                            "mode": mode,
                            "old_bankroll": report.old_bankroll,
                            "new_bankroll": report.new_bankroll,
                            "old_total_pnl": report.old_total_pnl,
                            "new_total_pnl": report.new_total_pnl,
                            "source": source,
                        },
                        note=f"Reconciliation {mode}: bankroll ${report.old_bankroll:.2f} → ${report.new_bankroll:.2f}",
                    )
                    db.add(event)
                except Exception as e:
                    logger.debug(
                        f"[reconciliation] TransactionEvent recording failed: {e}"
                    )
                logger.warning(
                    "BotState reconciled (%s): bankroll $%.2f -> $%.2f, pnl $%.2f -> $%.2f",
                    mode,
                    report.old_bankroll,
                    report.new_bankroll,
                    report.old_total_pnl,
                    report.new_total_pnl,
                )
            elif report.has_drift:
                logger.warning(
                    "BotState drift detected (%s): bankroll $%.2f -> $%.2f, pnl $%.2f -> $%.2f",
                    mode,
                    report.old_bankroll,
                    report.new_bankroll,
                    report.old_total_pnl,
                    report.new_total_pnl,
                )

        if apply and commit:
            db.commit()
            db.expire_all()
        return reports
    except Exception:
        if apply:
            db.rollback()
        logger.exception("BotState reconciliation failed")
        raise
    finally:
        if previous_live_update_permission is None:
            db.info.pop("allow_live_financial_update", None)
        else:
            db.info["allow_live_financial_update"] = previous_live_update_permission
