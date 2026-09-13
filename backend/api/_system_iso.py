"""Carved verbatim out of ``backend/api/system.py`` — statements moved, no logic changed."""

from .system import (
    BaseModel,
    BotState,
    Optional,
)

from . import system as _facade

def _iso(dt) -> str | None:
    """Safely convert a datetime or string to ISO format.

    SQLite stores dates as strings, PostgreSQL as datetime objects.
    This handles both cases without crashing.
    """
    if dt is None:
        return None
    if isinstance(dt, _facade.datetime):
        return dt.isoformat()
    if isinstance(dt, str):
        return dt  # Already a string from SQLite
    return str(dt)
class SyncMetadata(BaseModel):
    """Metadata about database synchronization state."""

    last_synced_at: _facade.Optional[_facade.datetime] = None
    orphaned_count: int = 0
    external_imports_count: int = 0
class BotStats(BaseModel):
    bankroll: float
    available_balance: float = 0.0
    total_balance: float = 0.0
    total_trades: int
    winning_trades: int
    win_rate: float
    total_pnl: float
    realized_pnl: float = 0.0
    account_pnl: float = 0.0
    is_running: bool
    last_run: _facade.Optional[_facade.datetime]
    initial_bankroll: float = 10000.0
    paper_pnl: float = 0.0
    paper_bankroll: float = 10000.0
    paper_trades: int = 0
    paper_wins: int = 0
    paper_win_rate: float = 0.0
    testnet_pnl: float = 0.0
    testnet_bankroll: float = 100.0
    testnet_trades: int = 0
    testnet_wins: int = 0
    testnet_win_rate: float = 0.0
    mode: str = "paper"
    pnl_source: str = "botstate"
    paper: dict = {}
    testnet: dict = {}
    live: dict = {}
    live_ledger_pnl: float = 0.0
    live_profile_pnl: float = 0.0
    live_profile_traded_count: _facade.Optional[int] = None
    live_ledger_trades: int = 0
    live_ledger_wins: int = 0
    live_profile_closed_count: _facade.Optional[int] = None
    live_profile_winning_count: _facade.Optional[int] = None
    live_profile_open_count: _facade.Optional[int] = None
    live_profile_stale_open_count: _facade.Optional[int] = None
    live_profile_redeemable_count: _facade.Optional[int] = None
    active_mode: _facade.List[str] = ["paper"]
    open_exposure: float = 0.0
    open_trades: int = 0
    settled_trades: int = 0
    settled_wins: int = 0
    unrealized_pnl: float = 0.0
    position_cost: float = 0.0
    position_market_value: float = 0.0
    pusd_balance: float = 0.0
    sync_metadata: _facade.Optional[SyncMetadata] = None
def _live_cache_values(
    live_state: Optional[BotState],
) -> tuple[float, float, int, int, float]:
    """Return live account-equity cache values and initial capital basis.

    Live mode is externally reconciled.  The historical Trade ledger remains
    useful for learning/analytics, but dashboard account P&L must come from
    BotState.total_pnl (external equity - initial capital), not the sum of old
    imported/backfilled ledger rows.
    """

    initial = float(
        live_state.live_initial_bankroll
        if live_state and live_state.live_initial_bankroll is not None
        else _facade.settings.INITIAL_BANKROLL
    )
    bankroll = float(
        live_state.bankroll
        if live_state and live_state.bankroll is not None
        else initial
    )
    pnl = float(
        live_state.total_pnl
        if live_state and live_state.total_pnl is not None
        else bankroll - initial
    )
    trades = int(live_state.total_trades or 0) if live_state else 0
    wins = int(live_state.winning_trades or 0) if live_state else 0
    return bankroll, pnl, trades, wins, initial
def _available_simulated_bankroll(
    raw_bankroll: Optional[float], fallback: float
) -> float:
    """Return non-negative available bankroll for simulated modes.

    Paper/testnet accounts can have negative cumulative PnL, but available cash
    cannot be below zero. Keep historical PnL negative while preventing
    impossible negative balances from driving dashboards and sizing summaries.
    """

    bankroll = fallback if raw_bankroll is None else float(raw_bankroll)
    return max(0.0, bankroll)
class EventResponse(BaseModel):
    timestamp: str
    type: str
    message: str
    data: dict = {}
