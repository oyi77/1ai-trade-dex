"""FastAPI backend for BTC 5-min trading bot dashboard."""

import asyncio

from fastapi import (
    FastAPI,
    Depends,
    WebSocket,
    Request,
)
from sqlalchemy import func
from sqlalchemy.orm import Session
from datetime import datetime, timezone
from typing import List


from backend.config import settings
from backend.models.database import (
    get_db,
    BotState,
)

# Wallet creation support
try:
    from eth_account import Account
except ImportError:
    Account = None
    from loguru import logger as _import_logger

    _import_logger.warning("eth_account not available - wallet creation disabled")
from backend.api.auth import router as auth_router
from backend.api.markets import router as markets_router
from backend.api.trading import (
    router as trading_router,
)
from backend.api.copy_trading import router as copy_trading_router
from backend.api.arbitrage import router as arbitrage_router
from backend.api.market_intel import router as market_intel_router
from backend.api.auto_trader import router as auto_trader_router
from backend.api.system import health_check as system_liveness_check, router as system_router
from backend.api.backtest import router as backtest_router
from backend.api.wallets import router as wallets_router
from backend.api.wallet_allocations import router as wallet_allocations_router
from backend.api.copy_policy import router as copy_policy_router
from backend.api.analytics import router as analytics_router
from backend.api.settings import router as settings_router
from backend.api.activities import router as activities_router
from backend.api.proposals import router as proposals_router
from backend.api.events.sse_router import router as events_router
from backend.api.agi_routes import router as agi_router
from backend.api.admin import router as admin_router
from backend.api.brain import router as brain_router
from backend.api.errors import router as errors_router
from backend.api.metrics_endpoint import router as metrics_router
from backend.api.alerts import router as alerts_router

# Plugin system API routers
from backend.api.v1.ai_providers import router as ai_providers_router
from backend.api.v1.data_sources import router as data_sources_router
from backend.api.v1.market_providers import router as market_providers_router

# HFT shared data service
from backend.data.shared_service import router as shared_data_router
from backend.api.learning import router as learning_router

from backend.api.lifespan import lifespan
from pydantic import BaseModel
from loguru import logger







app = FastAPI(
    title="BTC 5-Min Trading Bot",
    description="Polymarket BTC Up/Down 5-minute market trading bot",
    version="3.0.0",
    lifespan=lifespan,
)

from fastapi.responses import JSONResponse  # noqa: E402

@app.exception_handler(Exception)
async def production_exception_handler(request: Request, exc: Exception):
    from loguru import logger as _err_logger
    _err_logger.opt(exception=exc).error(
        "Unhandled exception on {method} {path}: {exc}",
        method=request.method,
        path=request.url.path,
        exc=exc,
    )
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )

origins = [o.strip() for o in settings.CORS_ORIGINS.split(",") if o.strip()]
# app.add_middleware(
#     CORSMiddleware,
#     allow_origins=origins,
#     allow_credentials=True,
#     allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
#     allow_headers=["*"],
# )
# # from backend.api.rate_limiter import RateLimiterMiddleware  # noqa: E402
# # from backend.api.versioning import APIVersionMiddleware  # noqa: E402
# # from backend.api.timeout_middleware import TimeoutMiddleware  # noqa: E402
#
# # app.add_middleware(TimeoutMiddleware)
# # app.add_middleware(RateLimiterMiddleware, requests_per_minute=100)
# # app.add_middleware(APIVersionMiddleware)

app.include_router(auth_router, prefix="/api/v1")
app.include_router(markets_router, prefix="/api/v1")
app.include_router(trading_router, prefix="/api/v1")
app.include_router(copy_trading_router, prefix="/api/v1")
app.include_router(arbitrage_router, prefix="/api/v1")
app.include_router(market_intel_router, prefix="/api/v1")
app.include_router(auto_trader_router, prefix="/api/v1")
app.include_router(events_router, prefix="/api/v1")
app.include_router(system_router, prefix="/api/v1")
app.include_router(backtest_router, prefix="/api/v1")
app.include_router(wallets_router, prefix="/api/v1")
app.include_router(wallet_allocations_router, prefix="/api/v1")
app.include_router(copy_policy_router, prefix="/api/v1")
app.include_router(analytics_router, prefix="/api/v1")
app.include_router(settings_router, prefix="/api/v1")
app.include_router(activities_router, prefix="/api/v1")
app.include_router(proposals_router, prefix="/api/v1")
app.include_router(admin_router, prefix="/api/v1")
app.include_router(brain_router, prefix="/api/v1")
app.include_router(errors_router, prefix="/api/v1")
app.include_router(metrics_router, prefix="/api/v1")
app.include_router(alerts_router, prefix="/api/v1")
app.include_router(shared_data_router, prefix="/api/v1")
app.include_router(learning_router, prefix="/api/v1")

# Plugin system API routes
app.include_router(ai_providers_router, prefix="/api/v1")
app.include_router(data_sources_router, prefix="/api/v1")
app.include_router(market_providers_router, prefix="/api/v1")
app.include_router(agi_router, prefix="/api/v1/agi")

# Knowledge Graph router for Wave 10
from backend.api.agi.kg_router import kg_router  # noqa: E402
app.include_router(kg_router, prefix="/api/v1")

from backend.api.dashboard import router as dashboard_router  # noqa: E402
app.include_router(dashboard_router, prefix="/api/v1")

from backend.api.sync import router as sync_router  # noqa: E402
app.include_router(sync_router, prefix="/api/v1")

from backend.api.websockets_routes import router as websockets_router  # noqa: E402
from backend.api.events.sse_router import router as sse_events_router  # noqa: E402

app.include_router(sse_events_router, prefix="/api/v1")
app.include_router(websockets_router)


@app.get("/api/health", include_in_schema=False)
async def legacy_api_health_check():
    """Backward-compatible liveness alias for legacy monitors."""

    return await system_liveness_check()

# Add metrics middleware for automatic tracking
@app.middleware("http")
async def metrics_middleware_wrapper(request: Request, call_next):
    from backend.monitoring.middleware import metrics_middleware

    return await metrics_middleware(request, call_next)


# WebSocket connection manager
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception as e:
                logger.exception(
                    f"[api.main.ConnectionManager.broadcast] {type(e).__name__}: Failed to broadcast message to WebSocket connection: {e}"
                )


ws_manager = ConnectionManager()


# Pydantic response models
# Default backtest configuration values
_DEFAULT_MAX_TRADE_SIZE = 100.0
_DEFAULT_MIN_EDGE_THRESHOLD = 0.02
_DEFAULT_MARKET_TYPES = ["BTC"]
DEFAULT_SLIPPAGE_BPS = 5


class BacktestRequest(BaseModel):
    initial_bankroll: float = 1000.0
    max_trade_size: float = 100.0
    min_edge_threshold: float = 0.02
    start_date: str | None = None  # ISO format datetime
    end_date: str | None = None  # ISO format datetime
    market_types: list[str] = ["BTC", "Weather", "CopyTrader"]
    slippage_bps: int = 5  # basis points


class FrontendBacktestRequest(BaseModel):
    strategy_name: str
    start_date: str | None = None
    end_date: str | None = None
    initial_bankroll: float = 10000.0




# Core endpoints
@app.get("/api/v1/health/dependencies")
async def health_check(db: Session = Depends(get_db)):
    """Return system health including per-strategy heartbeat and dependency status."""
    checks = {}
    overall_status = "ok"

    try:
        db.execute(func.now())
        checks["database"] = {"status": "ok"}
    except Exception as e:
        checks["database"] = {"status": "error", "error": "database unavailable"}
        overall_status = "degraded"
        logger.error(
            f"[api.main.health_check] {type(e).__name__}: Database health check failed: {e}",
            exc_info=True
        )

    redis_url = getattr(settings, "JOB_QUEUE_URL", "")
    if redis_url.startswith("redis://"):
        try:
            from redis import Redis

            r = Redis.from_url(redis_url, socket_connect_timeout=2)
            r.ping()
            checks["redis"] = {"status": "ok"}
            r.close()
        except Exception as e:
            checks["redis"] = {"status": "error", "error": "redis unavailable"}
            if overall_status == "ok":
                overall_status = "degraded"
            logger.warning(
                f"[api.main.health_check] {type(e).__name__}: Redis health check failed: {e}",
                exc_info=True
            )
    else:
        checks["redis"] = {"status": "not_configured", "fallback": "sqlite"}

    # Polymarket CLOB connectivity. Keep this bounded: health checks must not
    # hang the API when an exchange/RPC dependency is slow.
    try:
        from backend.data.polymarket_clob import clob_from_settings

        client = clob_from_settings()
        balance = await asyncio.wait_for(client.get_wallet_balance(), timeout=5.0)
        if not balance.get("error"):
            checks["polymarket_clob"] = {
                "status": "ok",
                "balance": str(balance.get("usdc_balance", 0.0)),
            }
        else:
            checks["polymarket_clob"] = {
                "status": "error",
                "error": "wallet balance unavailable",
            }
            if overall_status == "ok":
                overall_status = "degraded"
    except asyncio.TimeoutError:
        checks["polymarket_clob"] = {"status": "error", "error": "health check timed out"}
        if overall_status == "ok":
            overall_status = "degraded"
        logger.warning("Polymarket CLOB health check timed out")
    except Exception as e:
        checks["polymarket_clob"] = {
            "status": "error",
            "error": "wallet balance unavailable",
        }
        if overall_status == "ok":
            overall_status = "degraded"
        logger.warning(
            f"[api.main.health_check] {type(e).__name__}: Polymarket CLOB health check failed: {e}",
        )

    try:
        from backend.core.heartbeat import get_strategy_health

        healths = get_strategy_health(db)
        all_healthy = all(h["healthy"] or h["lag_seconds"] is None for h in healths)
        if not all_healthy and overall_status == "ok":
            overall_status = "degraded"
    except Exception as e:
        healths = []
        logger.warning(
            f"[api.main.health_check] {type(e).__name__}: Failed to get strategy health: {e}",
            exc_info=True
        )
        if overall_status == "ok":
            overall_status = "degraded"

    try:
        from backend.models.database import engine
        pool = engine.pool
        checks["db_pool"] = {
            "status": "ok",
            "pool_size": pool.size(),
            "checked_out": pool.checkedout(),
            "overflow": pool.overflow(),
            "queue_size": pool.size() - pool.checkedout() - pool.overflow(),
        }
    except Exception as e:
        checks["db_pool"] = {"status": "error", "error": "db pool unavailable"}
        logger.warning(f"Failed to get pool stats: {e}")

    bot_state = db.query(BotState).first()
    agi_health = {}
    try:
        from backend.core.agi_event_handlers import check_agi_health
        agi_health = check_agi_health()
    except Exception as e:
        agi_health = {"status": "error", "error": "agi health unavailable"}
        logger.warning(f"Failed to get AGI health: {e}")

    response = {
        "status": overall_status,
        "dependencies": checks,
        "strategies": healths,
        "agi_events": agi_health,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "bot_running": bot_state.is_running if bot_state else False,
        "trading_mode": settings.TRADING_MODE,
    }
    db.rollback()
    return response





# =========================================================================
# Copy Trader endpoints
# =========================================================================


class ScoredTraderResponse(BaseModel):
    wallet: str
    pseudonym: str
    profit_30d: float
    win_rate: float
    total_trades: int
    unique_markets: int
    estimated_bankroll: float
    score: float
    market_diversity: float


class CopySignalResponse(BaseModel):
    source_wallet: str
    our_side: str
    our_outcome: str
    our_size: float
    market_price: float
    trader_score: float
    reasoning: str
    condition_id: str
    title: str
    timestamp: str


# =========================================================================
# Sync Status Endpoints
# =========================================================================








if __name__ == "__main__":
    import uvicorn
    from backend.core.config_service import get_setting

    uvicorn.run(app, host="0.0.0.0", port=int(get_setting("PORT", default="8100")))
