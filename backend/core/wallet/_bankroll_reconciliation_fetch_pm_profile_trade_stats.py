"""Carved verbatim out of ``backend/core/wallet/bankroll_reconciliation.py`` — statements moved, no logic changed."""

from __future__ import annotations

from ._bankroll_reconciliation_bankrollreconciliationreport import (
    BankrollReconciliationReport,
    PolymarketProfileTradeStats,
)

from .bankroll_reconciliation import (
    BotState,
    Optional,
    Session,
)

from . import bankroll_reconciliation as _facade

async def fetch_pm_profile_trade_stats(
    wallet: Optional[str] = None,
) -> Optional[PolymarketProfileTradeStats]:
    """Fetch profile-aligned Polymarket trade count and closed-market W/L.

    `/traded` returns the public profile markets-traded count. The
    `/closed-positions` endpoint can include multiple rows for one market, so we
    group by market slug/condition and sum realized PnL before classifying each
    closed market as win/loss/flat.
    """

    wallet_address = wallet or _facade.get_polymarket_wallet_address()
    if not wallet_address:
        return None

    try:
        import httpx

        async with httpx.AsyncClient(
            timeout=12.0,
            headers={"User-Agent": "polyedge-finance"},
        ) as client:
            traded_resp = await client.get(
                f"{_facade.settings.DATA_API_URL}/traded",
                params={"user": wallet_address.lower()},
            )
            if traded_resp.status_code != 200:
                _facade.logger.warning(
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
                    f"{_facade.settings.DATA_API_URL}/closed-positions",
                    params={
                        "user": wallet_address.lower(),
                        "limit": limit,
                        "offset": offset,
                    },
                )
                if closed_resp.status_code != 200:
                    _facade.logger.warning(
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
                    f"{_facade.settings.DATA_API_URL}/positions",
                    params={
                        "user": wallet_address.lower(),
                        "limit": limit,
                        "offset": offset,
                    },
                )
                if positions_resp.status_code != 200:
                    _facade.logger.warning(
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
            today = _facade.datetime.now(_facade.timezone.utc).date().isoformat()
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
            return _facade.PolymarketProfileTradeStats(
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
        _facade.logger.warning("PM profile trade stats fetch failed: %s", exc)
        return None
def _realized_trade_stats(db: Session, mode: str) -> tuple[int, float, int]:
    """Return count, realized PnL, and win count from settled ledger rows."""

    trade_count, realized_pnl, win_count = (
        db.query(
            _facade.func.count(_facade.Trade.id),
            _facade.func.coalesce(_facade.func.sum(_facade.Trade.pnl), 0.0),
            _facade.func.coalesce(_facade.func.sum(_facade.case((_facade.Trade.pnl > 0, 1), else_=0)), 0),
        )
        .filter(
            _facade.Trade.settled.is_(True),
            _facade.Trade.trading_mode == mode,
            _facade.Trade.pnl.isnot(None),
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
        db.query(_facade.func.coalesce(_facade.func.sum(_facade.Trade.size), 0.0))
        .filter(_facade.Trade.settled.is_(False), _facade.Trade.trading_mode == mode)
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
    return float(_facade.settings.INITIAL_BANKROLL)
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

    state.last_sync_at = _facade.datetime.now(_facade.timezone.utc)
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
        "last_sync_at": _facade.datetime.now(_facade.timezone.utc),
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
            # Live bankroll is PUSD cash synced by wallet_sync_job every 60s.
            # Do NOT overwrite with PM portfolio equity (which includes open
            # position values and drifts with token prices).
            new_bankroll = old_bankroll
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

    return _facade.BankrollReconciliationReport(
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
