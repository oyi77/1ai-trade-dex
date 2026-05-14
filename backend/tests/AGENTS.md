<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-04-10 | Updated: 2026-05-09 -->

# backend/tests

## Purpose
Comprehensive unit and integration test suite for PolyEdge backend. `conftest.py` provides shared pytest fixtures (in-memory SQLite, test database session, FastAPI TestClient) and stubs heavy dependencies (APScheduler, scheduler module) before app imports to avoid crashes in CI. Tests cover: API endpoints (health, admin, strategies, trading, decisions, phase2), core trading logic (arbitrage detection, auto-trader, risk management, strategy executor, circuit breaker), data aggregators (feeds, market analyzers, sentiment), queue/cache layer (Redis + SQLite implementations, crash recovery), market scanning strategies, and settlement/dispute tracking.

## Key Files

| File | Description |
|------|-------------|
| `conftest.py` | Pytest configuration: stubs APScheduler, creates in-memory SQLite DB, patches database module, seeds BotState, redirects heartbeat SessionLocal |
| `test_api_health.py` | Health check endpoint tests |
| `test_api_admin.py` | Admin endpoint tests (bot control, config updates) |
| `test_api_strategies.py` | Strategy configuration and listing endpoints |
| `test_api_trades.py` | Trade history, approval workflows, decision logging |
| `test_api_decisions.py` | Signal approval/rejection workflow tests |
| `test_api_dashboard.py` | Dashboard data aggregation endpoint |
| `test_scheduler_queue_mode.py` | Scheduler queue-mode regression tests, including keeping `settlement_check` scheduled while market scans are worker-routed |
| `test_auto_redeem_scheduler.py` | Scheduled auto-redeem safety tests for missing credentials, dry-run defaults, and scheduler wiring |
| `test_api_phase2.py` | Phase 2 feature tests (whale listener, news, auto-trader, arbitrage) |
| `test_auto_trader.py` | Auto-trader signal → trade execution pipeline |
| `test_strategy_executor.py` | Strategy cycle execution, error handling, context wiring |
| `test_arb_executor.py` | Arbitrage detection: intra-market, cross-platform, negrisk |
| `test_arbitrage_detector.py` | Arbitrage scoring and opportunity ranking |
| `test_general_scanner.py` | General market scanner logic and filtering |
| `test_bond_scanner.py` | Bond-specific market scanning |
| `test_aggregator.py` | Market data aggregation from multiple feeds |
| `test_feed_aggregator.py` | Feed-level data aggregation and validation |
| `test_market_analyzer.py` | Market technical analysis and edge detection |
| `test_market_maker.py` | Market maker quote generation and inventory management |
| `test_market_risk.py` | Market risk calculations (volatility, max position size) |
| `test_risk_manager.py` | Risk limits enforcement (daily loss, drawdown, max position) |
| `test_circuit_breaker.py` | Circuit breaker trip conditions and recovery |
| `test_portfolio.py` | Portfolio P&L tracking, equity curve |
| `test_prediction_engine.py` | AI prediction model inference |
| `test_training_pipeline.py` | Model training and backtesting pipeline |
| `test_sentiment_analyzer.py` | News sentiment analysis |
| `test_whale_scoring.py` | Whale account scoring and tracking |
| `test_settlement.py` | Trade settlement tracking and dispute resolution |
| `test_shadow_mode.py` | Paper trading mode isolation |
| `test_dispute_tracker.py` | Dispute detection and resolution |
| `test_notification_router.py` | Event notification routing to Telegram, dashboard |
| `test_alert_engine.py` | Alert generation and delivery |
| `test_db_session_boundaries.py` | Regression tests that guard against holding DB sessions open across awaited network work |
| `test_ensemble.py` | Multi-signal ensemble and confidence weighting |
| `test_goldsky_client.py` | Goldsky webhooks and data ingestion |
| `test_polygon_listener.py` | Polygon.io listener integration |
| `test_orderbook.py` | Order book modeling and price inference |
| `test_validators.py` | Input validation (market data, orders, signals) |
| `test_wash_trade.py` | Wash trade detection |
| `test_structured_logger.py` | Structured logging output and format validation |
| `test_retry.py` | Retry logic and exponential backoff |
| `test_preflight.py` | Pre-flight health checks before trading |
| `test_orchestrator_wiring.py` | Full Orchestrator startup and shutdown (integration test) |
| `test_backtester.py` | Backtesting engine with historical data replay |
| `test_bayesian_optimizer.py` | Hyperparameter tuning via Bayesian optimization |
| `test_agi_integration.py` | AGI system integration tests |
| `test_agi_promotion_pipeline.py` | Autonomous experiment promotion pipeline tests |
| `test_agi_benchmarks.py` | AGI strategy performance and benchmarking |
| `test_mirofish_integration.py` | External dual-debate system integration |
| `test_mirofish_debate_integration.py` | Debate engine and validation system tests |
| `test_knowledge_graph.py` | Knowledge graph storage and retrieval tests |
| `test_audit_trail.py` | Audit logging and compliance tracking tests |
| `test_auto_improve.py` | Self-improvement and learning loop tests |
| `test_websocket.py` | WebSocket connection and real-time data tests |
| `test_wallet_reconciliation_e2e.py` | End-to-end wallet reconciliation tests |

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `test_queue/` | Queue layer tests: SQLite, Redis implementations, worker pool, crash recovery, migration (see `test_queue/AGENTS.md`) |

## For AI Agents

### Working In This Directory

1. **conftest.py Setup**:
   - Stubs APScheduler BEFORE any imports (lines 14-24)
   - Creates in-memory SQLite DB (lines 31-38)
   - Patches `backend.models.database` module globals (lines 44-45)
   - Creates all tables via `Base.metadata.create_all()` (line 48)
   - Seeds BotState row so `/api/stats` doesn't 404 (lines 62-77)
   - Patches heartbeat module's SessionLocal reference (lines 55-59)
   - This allows all tests to use a fresh, isolated DB per test

2. **Test DB Isolation**:
   - Each test gets a transaction-scoped session
   - conftest's `TestSessionLocal()` creates a new session per test
   - No state leakage between tests
   - Tables are rolled back (or recreated) between tests if using transaction rollback

3. **API Tests Pattern**:
   ```python
   from fastapi.testclient import TestClient
   from backend.api.main import app
   
   def test_health_endpoint():
       client = TestClient(app)
       resp = client.get("/api/health")
       assert resp.status_code == 200
   ```

4. **Strategy Tests Pattern**:
   ```python
   import pytest
   from unittest.mock import AsyncMock
   from backend.strategies.my_strategy import MyStrategy
   from backend.strategies.base import StrategyContext
   
   @pytest.mark.asyncio
   async def test_my_strategy():
       ctx = StrategyContext(...)
       strategy = MyStrategy()
       result = await strategy.run_cycle(ctx)
       assert result.trades_attempted >= 0
   ```

5. **Mocking External APIs**:
   - Mock `httpx.AsyncClient` for external API calls
   - Mock Polymarket CLOB client for order placement
   - Use `unittest.mock.patch` or `pytest-mock` fixture
   - Example: `test_general_scanner.py` mocks Gamma API responses

6. **Error Path Testing**:
   - Test exception handling in strategies
   - Verify errors are logged, not silently swallowed
   - Verify `CycleResult.errors` list is populated
   - Test graceful degradation on API failure

### Testing Requirements

1. **Run All Tests**:
   ```bash
   pytest backend/tests/ -v
   ```

2. **Run Specific Test File**:
   ```bash
   pytest backend/tests/test_api_health.py -v
   pytest backend/tests/test_strategy_executor.py -v
   ```

3. **Run with Coverage**:
   ```bash
   pytest backend/tests/ --cov=backend --cov-report=html
   ```

4. **Run Async Tests Only**:
   ```bash
   pytest backend/tests/ -k "async" -v
   ```

5. **Key Test Categories**:
   - **API Tests**: Validate HTTP endpoints, status codes, response schemas
   - **Strategy Tests**: Unit test strategy logic in isolation
   - **Integration Tests**: `test_orchestrator_wiring.py` validates full startup
   - **Queue Tests**: `test_queue/` validates job queue layer
   - **Risk Tests**: Verify risk limits are enforced

6. **CI Requirements**:
   - All tests must pass on commit (GitHub Actions)
   - No hardcoded API keys or credentials in test files
   - Tests must be deterministic (no flaky timeouts)
   - Use `pytest.mark.slow` for long-running tests to skip in quick CI runs

### Common Patterns

1. **Fixture Usage**:
   ```python
   def test_something(test_db):
       # test_db is a fresh SQLAlchemy session from conftest
       signal = test_db.query(Signal).first()
       assert signal is not None
   ```

2. **Async Test Decorator**:
   ```python
   @pytest.mark.asyncio
   async def test_async_strategy():
       result = await strategy.run_cycle(ctx)
       assert result is not None
   ```

3. **Mocking Pattern**:
   ```python
   from unittest.mock import patch, AsyncMock
   
   @patch("httpx.AsyncClient.get")
   async def test_api_call(mock_get):
       mock_get.return_value = AsyncMock(status_code=200, json=...)
       # test code
   ```

4. **Database Setup in Test**:
   ```python
   def test_trade_settlement(test_db):
       trade = Trade(entry_price=0.55, exit_price=0.60, ...)
       test_db.add(trade)
       test_db.commit()
       # Test settlement logic
   ```

5. **Settings Override**:
   ```python
   from backend.config import settings
   
   def test_with_custom_settings(monkeypatch):
       monkeypatch.setenv("SHADOW_MODE", "true")
       # Test code runs with shadow mode enabled
   ```

6. **API TestClient**:
   ```python
   from fastapi.testclient import TestClient
   from backend.api.main import app
   
   client = TestClient(app)
   response = client.post("/api/trading/decisions/approve/123", json={...})
   assert response.status_code == 200
   ```

## Dependencies

### Internal
- `backend.config` — Settings singleton (via conftest patches)
- `backend.models.database` — SQLAlchemy models (in-memory DB per test)
- `backend.api.main` — FastAPI app (for API tests)
- `backend.strategies.*` — Strategy implementations (unit test imports)
- `backend.core.*` — Trading logic modules (dependency testing)
- `backend.data.*` — Data feed modules (mocked in tests)

### External
- `pytest` — Test framework
- `pytest-asyncio` — Async test support
- `pytest-cov` — Coverage reporting
- `sqlalchemy` — ORM (in-memory DB)
- `fastapi` — API framework (TestClient)
- `unittest.mock` — Mocking (MagicMock, AsyncMock, patch)
- `httpx` — Async HTTP (mocked in tests)

<!-- MANUAL: -->
