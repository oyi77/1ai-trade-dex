# Testing Guide

This document covers all testing infrastructure, test suites, and testing best practices for the Polyedge trading bot.

## Test Coverage

### Overall Coverage

**Target**: 70%+ across backend and frontend

**Current Coverage**:
- Backend: 70%+ (unit + integration tests)
- Frontend: 70%+ (component + E2E tests)

**Coverage Reports**:
```bash
# Backend coverage
pytest --cov=backend --cov-report=html
open htmlcov/index.html

# Frontend coverage
cd frontend
npm run test:coverage
open coverage/index.html
```

## Backend Testing

### Unit Tests

**Location**: `backend/tests/`

**Run All Unit Tests**:
```bash
pytest
```

**Run Specific Test File**:
```bash
pytest backend/tests/test_validation.py
```

**Run Specific Test**:
```bash
pytest backend/tests/test_validation.py::test_trade_validator_valid_trade
```

**Run with Verbose Output**:
```bash
pytest -v
```

**Run with Coverage**:
```bash
pytest --cov=backend --cov-report=term-missing
```

### Test Suites

#### Core Infrastructure Tests

**File**: `backend/tests/test_task_manager.py`

**Coverage**:
- TaskManager lifecycle (create, track, shutdown)
- Concurrent task handling
- Automatic cleanup on completion
- Graceful cancellation

**Run**:
```bash
pytest backend/tests/test_task_manager.py
```

#### Database Tests

**File**: `backend/tests/test_database.py`

**Coverage**:
- Connection pooling
- Query timeout handling
- Transaction management
- Migration verification

**Run**:
```bash
pytest backend/tests/test_database.py
```

#### Validation Tests

**File**: `backend/tests/test_data_validation.py`

**Coverage**:
- TradeValidator (32 tests)
- SignalValidator
- ApprovalValidator
- Validation error handling

**Run**:
```bash
pytest backend/tests/test_data_validation.py
```

#### Circuit Breaker Tests

**File**: `backend/tests/test_circuit_breaker.py`

**Coverage**:
- State transitions (CLOSED → OPEN → HALF_OPEN → CLOSED)
- Failure threshold detection
- Recovery timeout
- Fast-fail behavior

**Run**:
```bash
pytest backend/tests/test_circuit_breaker.py
```

#### Error Recovery Tests

**File**: `backend/tests/test_error_recovery.py`

**Coverage**:
- Circuit breaker recovery
- Redis fallback strategy
- WebSocket auto-reconnect
- API retry logic
- Rate limit handling

**Run**:
```bash
pytest backend/tests/test_error_recovery.py
```

#### Timeout Handling Tests

**File**: `backend/tests/test_timeout_handling.py`

**Coverage**:
- API request timeouts
- Database query timeouts
- External API timeouts
- Timeout middleware

**Run**:
```bash
pytest backend/tests/test_timeout_handling.py
```

#### Alert System Tests

**File**: `backend/tests/test_alert_manager.py`

**Coverage**:
- Alert creation and persistence
- Alert cooldown mechanism
- Error rate tracking
- System metrics monitoring

**Run**:
```bash
pytest backend/tests/test_alert_manager.py
```

#### Audit Trail Tests

**File**: `backend/tests/test_audit_trail.py`

**Coverage**:
- Audit log creation
- Event filtering
- Sensitive data redaction
- Audit log retrieval

**Run**:
```bash
pytest backend/tests/test_audit_trail.py
```

#### Genome Compiler Tests

**File**: `backend/tests/test_genome_compiler.py`

**Coverage**:
- StrategyGenome compilation to executable BaseStrategy subclass
- Chromosome mapping (entry, exit, risk, execution parameters)
- Genome validation and error handling
- Runtime strategy instantiation from genome templates

**Run**:
```bash
pytest backend/tests/test_genome_compiler.py
```

#### Evolution Jobs Feedback Loop Tests

**File**: `backend/tests/test_evolution_jobs_feedback_loop.py`

**Coverage**:
- Shadow-trade fitness recalculation from settled ShadowTrade records
- GenomePerformance sync and stage gate evaluation
- SHADOW→PAPER and PAPER→LIVE_TRIAL promotion by metric gates
- GRAVEYARD auto-kill for terminal performers
- Demotion loop handling

**Run**:
```bash
pytest backend/tests/test_evolution_jobs_feedback_loop.py
```

#### Bankroll Allocator Longshot Tests

**File**: `backend/tests/test_bankroll_allocator_longshot.py`

**Coverage**:
- StrategyRanker allocation with longshot/low-probability strategies
- Risk-tier-aware capital allocation caps
- Edge cases in bankroll distribution across strategies

**Run**:
```bash
pytest backend/tests/test_bankroll_allocator_longshot.py
```

#### Trade Role Classification Tests

**File**: `backend/tests/test_classify_trade_role.py`

**Coverage**:
- Trade role classification logic
- Signal attribution and strategy name tracking
- Auto-trader routing and role assignment

**Run**:
```bash
pytest backend/tests/test_classify_trade_role.py
```

### Integration Tests

**File**: `backend/tests/test_integration.py`

**Coverage**:
- End-to-end API workflows
- Database + API integration
- WebSocket + Redis integration
- Strategy execution flow

**Run**:
```bash
pytest backend/tests/test_integration.py
```

### API Tests

**File**: `backend/tests/test_api.py`

**Coverage**:
- All API endpoints
- Request validation
- Response formats
- Error handling
- Authentication

**Run**:
```bash
pytest backend/tests/test_api.py
```

### Performance Tests

**File**: `.sisyphus/performance/performance_test.py`

**Coverage**:
- API response time (p50, p95, p99)
- Database query performance
- Memory usage
- Regression detection

**Run**:
```bash
python .sisyphus/performance/performance_test.py
```

## Frontend Testing

### Component Tests

**Location**: `frontend/src/**/*.test.tsx`

**Run All Tests**:
```bash
cd frontend
npm test
```

**Run Specific Test**:
```bash
npm test -- EquityChart.test.tsx
```

**Run with Coverage**:
```bash
npm run test:coverage
```

**Watch Mode**:
```bash
npm test -- --watch
```

### Test Suites

#### Hook Tests

**Files**:
- `useWebSocket.test.ts` - WebSocket connection and reconnection
- `useAuth.test.ts` - Authentication flow
- `useStats.test.ts` - Statistics fetching
- `useBrainGraph.test.ts` - Brain graph data

**Coverage**:
- Hook lifecycle
- State management
- Error handling
- Cleanup functions

#### Component Tests

**Files**:
- `EquityChart.test.tsx` - Chart rendering and null safety
- `GlobeView.test.tsx` - 3D globe visualization
- `EdgeDistribution.test.tsx` - Signal distribution
- `WeatherPanel.test.tsx` - Weather data display

**Coverage**:
- Component rendering
- Props handling
- User interactions
- Loading states
- Error states

#### Utility Tests

**Files**:
- `retryFetch.test.ts` - Retry logic with exponential backoff
- `api.test.ts` - API client functions

**Coverage**:
- Retry behavior
- Error handling
- Timeout handling
- Response parsing

### E2E Tests

**Location**: `frontend/tests/e2e/`

**Framework**: Playwright

**Run All E2E Tests**:
```bash
cd frontend
npx playwright test
```

**Run Specific Test**:
```bash
npx playwright test dashboard.spec.ts
```

**Run in UI Mode**:
```bash
npx playwright test --ui
```

**Run in Debug Mode**:
```bash
npx playwright test --debug
```

**View Report**:
```bash
npx playwright show-report
```

### E2E Test Suites

#### Dashboard Tests

**File**: `frontend/tests/e2e/dashboard.spec.ts`

**Coverage**:
- Dashboard loads and displays data
- All tabs render correctly
- Tab navigation works
- Data updates in real-time

#### Trading Tests

**File**: `frontend/tests/e2e/trading.spec.ts`

**Coverage**:
- Start/stop bot controls
- Trading mode switching
- Trade execution flow
- Position management

#### Admin Tests

**File**: `frontend/tests/e2e/admin.spec.ts`

**Coverage**:
- Admin panel access
- Settings updates
- Strategy configuration
- System controls

#### Error Handling Tests

**File**: `frontend/tests/e2e/error-boundary.spec.ts`

**Coverage**:
- Error boundary catches errors
- Graceful error display
- Recovery mechanisms
- Fallback UI

#### Visual Tests

**File**: `frontend/tests/e2e/visual.spec.ts`

**Coverage**:
- Visual regression testing
- Screenshot comparison
- Layout consistency
- Responsive design

## Load Testing

### WebSocket Load Test

**Script**: `.sisyphus/load/websocket_load_test_simple.py`

**Test Parameters**:
- Concurrent clients: 500
- Test duration: 10 minutes
- Heartbeat interval: 30 seconds

**Run**:
```bash
python .sisyphus/load/websocket_load_test_simple.py
```

**Metrics**:
- Connection success rate
- Message delivery rate
- Latency (p50, p95, p99)
- Memory usage per connection
- CPU usage

**Results**:
- 500 concurrent clients: 100% success rate
- Zero connection drops
- Memory per connection: ~80KB
- CPU usage: 0%

### Rate Limit Test

**Script**: `tests/load/rate_limit_test.py`

**Test Coverage**:
- Per-endpoint rate limits
- Per-IP rate limits
- 429 response handling
- Retry-After header compliance

**Run**:
```bash
python tests/load/rate_limit_test.py
```

### Performance Regression Test

**Script**: `.sisyphus/performance/performance_test.py`

**Test Coverage**:
- API response time benchmarks
- Database query performance
- Memory usage tracking
- Regression detection

**Run**:
```bash
python .sisyphus/performance/performance_test.py
```

**Baseline Storage**: `.sisyphus/performance/baseline.json`

**Regression Thresholds**:
- API response time: <10% increase
- Memory usage: <20% increase
- Database queries: Should improve with pooling

## Test Data

### Test Database

**Location**: `test_polyedge.db`

**Setup**:
```bash
# Create test database
python -c "from backend.models.database import init_db; init_db()"

# Run migrations
alembic upgrade head
```

**Cleanup**:
```bash
rm test_polyedge.db
```

### Test Fixtures

**Location**: `backend/tests/conftest.py`

**Fixtures**:
- `db_session` - Database session for tests
- `client` - FastAPI test client
- `mock_redis` - Mock Redis client
- `mock_polymarket` - Mock Polymarket API
- `mock_kalshi` - Mock Kalshi API

**Usage**:
```python
def test_example(db_session, client):
    # Use fixtures in test
    response = client.get("/api/v1/dashboard")
    assert response.status_code == 200
```

## Testing Best Practices

### Unit Test Guidelines

1. **Test one thing per test**
   - Each test should verify a single behavior
   - Use descriptive test names

2. **Use fixtures for setup**
   - Avoid repetitive setup code
   - Share fixtures across tests

3. **Mock external dependencies**
   - Don't call real APIs in tests
   - Use mock objects for external services

4. **Test edge cases**
   - Test boundary conditions
   - Test error scenarios
   - Test null/empty inputs

5. **Keep tests fast**
   - Unit tests should run in milliseconds
   - Use in-memory databases
   - Avoid sleep() calls

### Integration Test Guidelines

1. **Test realistic workflows**
   - Test complete user journeys
   - Test cross-component interactions

2. **Use test database**
   - Isolate test data
   - Clean up after tests

3. **Test error recovery**
   - Test failure scenarios
   - Verify recovery mechanisms

4. **Verify side effects**
   - Check database state
   - Verify external API calls
   - Check log messages

### E2E Test Guidelines

1. **Test critical user flows**
   - Focus on high-value scenarios
   - Test happy path first

2. **Use stable selectors**
   - Use data-testid attributes
   - Avoid brittle CSS selectors

3. **Handle async operations**
   - Wait for elements to appear
   - Use proper timeouts
   - Avoid fixed delays

4. **Keep tests independent**
   - Each test should run standalone
   - Don't rely on test order
   - Clean up test data

5. **Run tests in CI/CD**
   - Automate test execution
   - Fail builds on test failures
   - Track test trends

## Continuous Integration

### GitHub Actions

**Workflow**: `.github/workflows/test.yml`

**Triggers**:
- Push to main branch
- Pull request creation
- Manual workflow dispatch

**Jobs**:
1. **Backend Tests**
   - Install dependencies
   - Run pytest with coverage
   - Upload coverage report

2. **Frontend Tests**
   - Install dependencies
   - Run component tests
   - Run E2E tests
   - Upload test results

3. **Lint**
   - Run ESLint (frontend)
   - Run Black (backend)
   - Run type checking

**Status Checks**:
- All tests must pass
- Coverage must be >70%
- No linting errors

## Test Maintenance

### Updating Tests

When changing code:
1. Update affected tests
2. Add tests for new features
3. Remove tests for deleted features
4. Run full test suite
5. Update test documentation

### Test Debt

Track test debt:
- Missing test coverage
- Flaky tests
- Slow tests
- Outdated tests

**Review quarterly**:
- Identify gaps in coverage
- Fix flaky tests
- Optimize slow tests
- Remove obsolete tests

### Test Metrics

Track over time:
- Test coverage percentage
- Test execution time
- Test failure rate
- Flaky test count

**Goals**:
- Coverage: >70% (maintain)
- Execution time: <5 minutes (backend), <10 minutes (E2E)
- Failure rate: <1%
- Flaky tests: 0

## Debugging Tests

### Backend Test Debugging

**Print Debug Info**:
```python
def test_example(db_session):
    result = some_function()
    print(f"Result: {result}")  # Will show in pytest output
    assert result == expected
```

**Run with Print Output**:
```bash
pytest -s  # Show print statements
```

**Run with PDB**:
```bash
pytest --pdb  # Drop into debugger on failure
```

**Run Single Test**:
```bash
pytest backend/tests/test_file.py::test_name -v
```

### Frontend Test Debugging

**Debug Component Tests**:
```bash
npm test -- --no-coverage --verbose
```

**Debug E2E Tests**:
```bash
# Run in headed mode
npx playwright test --headed

# Run in debug mode
npx playwright test --debug

# Run with trace
npx playwright test --trace on
```

**View Trace**:
```bash
npx playwright show-trace trace.zip
```

## Test Documentation

### Test Plan

Document test strategy:
- What to test
- How to test
- When to test
- Who tests

### Test Cases

Document test cases:
- Test ID
- Description
- Preconditions
- Steps
- Expected result
- Actual result

### Test Reports

Generate test reports:
- Coverage reports
- Test execution reports
- Performance reports
- Regression reports

**Store in**: `.sisyphus/evidence/`
