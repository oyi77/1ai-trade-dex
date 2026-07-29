"""strategy_executor package — execute strategy decisions across paper, testnet, and live modes."""

# Re-export all public symbols for backward compatibility.
# Tests and production code import from `backend.core.strategy_executor` directly.

import asyncio
from backend.config import settings, _cfg, settings as strategy_executor_settings

from backend.core.strategy_executor.locks import (
    _trade_locks,
    _trade_locks_mutex,
    _ensure_semaphore,
    _rate_limiter,
    _botstate_threading_lock,
    _get_asset_lock,
    _get_rate_limiter,
)

from backend.core.strategy_executor.helpers import (
    _is_lock_timeout_error,
    _lock_retry_delay,
    _BotStateLockRetry,
    _first_numeric_attr,
    _resolve_token_id_from_gamma,
)

from backend.core.strategy_executor.preflight import (
    _preflight_checks,
    _pre_trade_safety_checks,
    _get_current_exposure,
    _fetch_live_pusd_balance_sync,
    _fetch_orderbook_depth,
)

from backend.core.strategy_executor.recording import (
    _commit_with_retry,
    _update_botstate_after_trade,
    _record_unexpected_attempt_failure,
    _record_trade,
)

from backend.core.strategy_executor.paper_kalshi import _execute_decision_paper_or_kalshi

from backend.core.strategy_executor.live_clob import (
    _execute_hft_path,
    _maker_first_execute,
    _execute_decision_live_clob,
    _process_order_result,
)

from backend.core.strategy_executor.main import (
    execute_decision,
    execute_decisions,
    execute_quote,
    StrategyExecutor,
    MAKER_FIRST_ENABLED,
    MAKER_WAIT_SECONDS,
    MAKER_POLL_INTERVAL_SECONDS,
)

# Re-export for test monkeypatching backward compat
from backend.core.event_bus import _broadcast_event
from backend.core.validation import TradeValidator