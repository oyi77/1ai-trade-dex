"""Trade settlement logic using Polymarket API. Helpers live in settlement_helpers.py.

BASELINE_SETTLEMENT_QUERIES (Phase 0 — 2026-05-27):
  Per settlement cycle, DB query count = 2 + 8*N1 + 7*N2
  where N1 = trades_to_close (reconciliation path), N2 = pending trades (normal path).

  Shared queries (2):
    1. reconcile_positions → db.query(Trade).filter(settled=False)  [settlement_helpers.py:1459]
    2. pending trades → db.query(Trade).filter(settled=False | pnl=None)  [settlement.py:382]

  Per-trade queries in reconciliation path (8 per trade):
    3. Trade by ID — db.query(Trade).filter(Trade.id == trade_id)  [settlement.py:236] ← N+1
    4. TradeContext by trade_id  [settlement_helpers.py:1230]
    5. DecisionLog by market_ticker  [settlement_helpers.py:1232]
    6. Signal by signal_id  [settlement_helpers.py:1252]
    7. learner Trade by ID (separate session)  [settlement_helpers.py:1329]
    8. BotState.first()  [settlement_helpers.py:1377]
    9. strategy_performance_registry → ALL settled trades for strategy  [strategy_performance_registry.py:240]
    10. coverage days → 2 queries (first/last trade timestamp)  [strategy_performance_registry.py:427,433]

  Per-trade queries in normal path (7 per trade — no Trade-by-ID lookup):
    Items 4-10 above (process_settled_trade internals)

  Typical cycle (N1=5, N2=5): 2 + 40 + 35 = 77 DB round-trips
  External API calls excluded: fetch_resolution_for_trade, _resolve_markets, clob.get_trader_positions
"""

from .helpers import _ensure_session, _fetch_pm_portfolio_value, _settlement_lock, _closed_unresolved_grace
from .btc_settle import _settle_btc_5min_trade
from .settlement_core import settle_pending_trades
from .learning import _run_learning_pipeline_background
from .bot_state import update_bot_state_with_settlements, reconcile_bot_state

# Re-export for test monkeypatch compatibility
from backend.core.settlement.settlement_helpers import _resolve_markets

__all__ = [
    "settle_pending_trades",
    "update_bot_state_with_settlements",
    "reconcile_bot_state",
    "_ensure_session",
    "_fetch_pm_portfolio_value",
    "_settle_btc_5min_trade",
    "_run_learning_pipeline_background",
    "_settlement_lock",
    "_closed_unresolved_grace",
]
