"""Database models — re-exports from domain-specific modules. Backward-compatible."""
from backend.models.base_db import *  # noqa: F401,F403
from backend.models.trade_db import *  # noqa: F401,F403
from backend.models.botstate_db import *  # noqa: F401,F403
from backend.models.strategy_db import *  # noqa: F401,F403
from backend.models.signal_db import *  # noqa: F401,F403
from backend.models.wallet_db import *  # noqa: F401,F403
from backend.models.settlement_db import *  # noqa: F401,F403
from backend.models.audit_db import *  # noqa: F401,F403
from backend.models.misc_db import *  # noqa: F401,F403

# Re-import to ensure table registration without failing on circular import orderings.
try:
    from backend.core.strategy_performance_registry import (
        StrategyPerformanceSnapshot as StrategyPerformanceSnapshot,
    )
except ImportError as exc:
    from loguru import logger
    logger.debug(
        "Deferred StrategyPerformanceSnapshot registration during database import: {}",
        exc,
    )
