# Event-Driven WebSocket-First Architecture Migration

## TL;DR

> **Current**: APScheduler fires `strategy_cycle_job` every 300s → strategy calls REST API → hit rate limits → 0 signals
> **Target**: Strategy subscribes to WebSocket event bus → event arrives → evaluate → decision → trade. REST only as fallback when WS disconnects.
> **Deliverables**: Event bus centralizer, strategy WS subscription layer, REST fallback wrappers, scheduler deprecation for strategy cycles.
> **Estimated Effort**: Large
> **Parallel Execution**: YES - 4 waves
> **Critical Path**: Event Bus → Strategy Migrations → REST Fallback → Scheduler Cleanup

---

## Context

### Current Architecture (Push-Driven Timer)

```
APScheduler (timer) → strategy_cycle_job() → strategy.run_cycle() → REST API calls → signals → trade
                                                                     ↓
                                                             429 rate limits
```

Every strategy fires on a timer, polls REST APIs for data, even when no market activity exists. The CLOB Market WebSocket already connects and receives real-time `book`, `price_change`, `last_trade_price`, `market_resolved` events but **no strategy consumes them**. The `OrderbookRouter` dispatches events to `OrderbookCache` only — strategies never subscribe.

### Target Architecture (Pull-Driven Events)

```
CLOB Market WS → Event Bus → Strategy.subscribe(token_ids) → handler(event) → evaluate → decision → trade
                                                                                        ↓
                                                                              REST fallback handler
```

Strategies register interest in specific tokens/event types. When an event fires, the handler runs. No polling, no wasted cycles, no 429s. REST API used only when WebSocket disconnects or for data that has no WS equivalent.

### Why This Matters

| Metric | Current (Timer) | Target (Event-Driven) |
|--------|----------------|----------------------|
| API calls/strategy/day | 288 (300s interval) | 0 (WS only) |
| 429 rate limits | Frequent | Eliminated |
| Signal latency | Up to 300s | <1s (real-time event) |
| CPU waste | 288 cycles × 0 decisions | 0 cycles when silent |
| Market data freshness | Up to 300s stale | Real-time |

### What CAN Be WebSocket

| Data Source | WS Endpoint | Event Types |
|------------|-------------|-------------|
| Order books | `ws-subscriptions-clob.polymarket.com/ws/market` | `book`, `price_change`, `best_bid_ask` |
| Market trades | Same | `last_trade_price` |
| Market resolution | Same (custom_feature_enabled) | `market_resolved` |
| New markets | Same (custom_feature_enabled) | `new_market` |
| Tick size changes | Same | `tick_size_change` |
| My orders | `ws-subscriptions-clob.polymarket.com/ws/user` | `order`, `trade` |
| My trades | Same | `trade` (MATCHED→MINED→CONFIRMED) |
| Crypto prices | `ws-live-data.polymarket.com` (RTDS) | `crypto_prices` |
| Equity prices | Same | `equity_prices` |

### What CANNOT Be WebSocket (Must Stay REST)

| Data Source | Why | Mitigation |
|------------|-----|-----------|
| **Whale positions** (`/positions?user=ADDR`) | No WS endpoint exists | Cache + long interval (600s) + backoff |
| **Leaderboard** | No WS endpoint exists | Cache + interval (900s) |
| **Gamma API markets** | `/markets` for discovery, no WS stream | Use `new_market` WS for incremental, REST for initial load |
| **Kalshi API** | No WS support | Circuit breaker + backoff |
| **Open-Meteo (weather)** | No WS support | Already 300s, low volume |
| **CEX price feeds** | No WS in our system | Already breakered; RTDS covers some |
| **Polygon RPC (USDC balance)** | No WS | Already low frequency |

### Research Findings

- **CLOB Market WS** already connected in `lifespan.py:154-220`, receiving events → `OrderbookRouter` → `OrderbookCache`. Strategy subscription layer missing.
- **CLOB User WS** already available (`polymarket_websocket.py`). Could track own orders/trades in real-time.
- **RTDS** available for crypto/equity prices. Not yet connected.
- Rate limits: Data API 150 req/10s (`/positions`), Gamma 300 req/10s (`/markets`). WebSocket has no documented rate limit.

---

## Work Objectives

### Core Objective
Replace timer-driven strategy execution with event-driven subscription model. Strategies register interest in specific market events. Events trigger evaluation. REST API used only as fallback when WebSocket disconnects.

### Concrete Deliverables
- `backend/core/event_bus.py` — Centralized WS event bus with strategy subscription management
- `backend/core/ws_strategy_bridge.py` — Adapter: WS event → strategy handler invocation
- `backend/strategies/base.py` — `BaseStrategy` gains `subscribe_events()`, `on_market_event()`, REST fallback wrapper
- Updated `backend/core/orchestrator.py` — Strategy registration via event bus, not APScheduler
- Updated `backend/api/lifespan.py` — WS token subscription at startup with strategy-supplied token lists
- Updated strategies: `btc_oracle`, `weather_emos`, `whale_frontrun`, `copy_trader`, `universal_scanner`
- Migrated scheduler: strategy cycles removed; AGI, settlement, heartbeat jobs remain on APScheduler

### Definition of Done
- [ ] All 7 active strategies subscribe to WS events for their tracked tokens
- [ ] `strategy_cycle_job` removed from APScheduler
- [ ] 0 REST API calls during normal operation (only on WS disconnect)
- [ ] REST fallback activates within 30s of WS disconnect
- [ ] REST fallback respects rate limits and circuit breakers
- [ ] `pytest backend/tests/ -x` passes with new event-driven architecture

### Must Have
- Event bus with pub/sub for all strategy types
- WS → strategy handler dispatch within 100ms
- REST fallback that auto-activates on WS disconnect
- Circuit breaker prevents fallback REST from overwhelming APIs
- All existing signal/trade attribution preserved (track_name, strategy)

### Must NOT Have (Guardrails)
- Strategy must NOT call REST APIs when WS is connected and delivering data
- Strategy must NOT spawn its own WebSocket connections (use shared event bus)
- Event bus must NOT block — handlers run in background tasks
- Must NOT remove APScheduler entirely — only strategy cycles removed; AGI, settlement, heartbeat, wallet sync jobs remain
- Must NOT break paper mode — event-driven execution must work in paper mode
- Must NOT lose attribution — `track_name` and `strategy` fields preserved

---

## Verification Strategy

### Test Decision
- **Infrastructure exists**: YES (pytest)
- **Automated tests**: Tests-after implementation
- **Framework**: pytest + pytest-asyncio
- **QA Policy**: Every task includes agent-executed QA scenarios using tmux/curl/log inspection

### QA Policy
- **CLI/TUI**: `interactive_bash` (tmux) — Run bot, tail logs, inject WS events, verify strategy response
- **API**: `Bash` (curl) — Health endpoints, event bus status
- **Evidence**: `.sisyphus/evidence/task-{N}-{scenario-slug}.txt`

---

## Execution Strategy

### Parallel Execution Waves

```
Wave 1 (Foundation — unblocks everything):
├── Task 1: Event Bus core — pub/sub, subscription management, dispatch [deep]
├── Task 2: WS → Event Bus bridge — route CLOB WS events into event bus [deep]
├── Task 3: Strategy subscription interface — BaseStrategy gains subscribe/handler methods [deep]
├── Task 4: WS token discovery — strategy declares tokens → lifespan subscribes them [quick]
├── Task 5: REST fallback wrapper — auto-detect WS disconnect, safe REST with backoff [unspecified-high]
└── Task 6: Event bus health endpoint — API endpoint to check subscription state [quick]

Wave 2 (Strategy Migrations — MAX PARALLEL):
├── Task 7: Migrate btc_oracle to event-driven [deep]
├── Task 8: Migrate whale_frontrun to event-driven [deep]
├── Task 9: Migrate copy_trader to event-driven [deep]
├── Task 10: Migrate weather_emos to event-driven [deep]
├── Task 11: Migrate universal_scanner to event-driven [unspecified-high]
├── Task 12: Migrate whale_pnl_tracker to event-driven [unspecified-high]
└── Task 13: Migrate kalshi_arb to event-driven (Kalshi has no WS — REST-only with backoff) [quick]

Wave 3 (RTDS + Scheduler Cleanup):
├── Task 14: Connect RTDS WebSocket for crypto/equity price feeds [unspecified-high]
├── Task 15: Remove strategy_cycle_job from APScheduler [quick]
├── Task 16: Remove strategy intervals from seed config (lifespan.py) [quick]
├── Task 17: Remove interval_seconds from strategy_config table [quick]
└── Task 18: Update docs — architecture, README, project-structure [writing]

Wave FINAL (Verification):
├── Task F1: Plan compliance audit (oracle)
├── Task F2: Code quality review (unspecified-high)
├── Task F3: Real manual QA — run bot, inject WS events, verify trades (unspecified-high + tmux)
└── Task F4: Scope fidelity check (deep)
```

### Critical Path
Task 1 (Event Bus) → Task 2 (WS Bridge) → Task 4 (Token Discovery) → Tasks 7-13 (Strategy Migrations) → Task 15 (Scheduler Cleanup) → F1-F4

### Dependency Matrix

| Task | Depends On | Blocks |
|------|-----------|--------|
| 1 | — | 2,3,4,6 |
| 2 | 1 | 7-13 |
| 3 | 1 | 7-13 |
| 4 | 1,2 | 7-13 |
| 5 | 1 | 7-13 |
| 6 | 1 | F1 |
| 7 | 2,3,4,5 | 15 |
| 8 | 2,3,4,5 | 15 |
| 9 | 2,3,4,5 | 15 |
| 10 | 2,3,4,5 | 15 |
| 11 | 2,3,4,5 | 15 |
| 12 | 2,3,4,5 | 15 |
| 13 | 5 | 15 |
| 14 | 2 | — |
| 15 | 7-13 | F1 |
| 16 | 15 | F1 |
| 17 | 15 | F2 |
| 18 | 7-14 | F1 |

### Agent Dispatch Summary

- **Wave 1**: 6 tasks — T1→T3 `deep`, T4 `quick`, T5 `unspecified-high`, T6 `quick`
- **Wave 2**: 7 tasks — T7→T10 `deep`, T11,T12 `unspecified-high`, T13 `quick`
- **Wave 3**: 5 tasks — T14 `unspecified-high`, T15→T17 `quick`, T18 `writing`
- **Wave FINAL**: 4 tasks — F1 `oracle`, F2 `unspecified-high`, F3 `unspecified-high`, F4 `deep`

---

## TODOs

- [ ] 1. Event Bus Core

  **What to do**:
  - Create `backend/core/event_bus.py` — extend existing event bus with:
    - `subscribe(strategy_name, token_ids, event_types)` — register strategy interest
    - `unsubscribe(strategy_name)` — cleanup on strategy stop
    - `dispatch(event)` — route incoming WS events to registered strategies
  - Event types enum: `MARKET_BOOK`, `MARKET_PRICE_CHANGE`, `MARKET_TRADE`, `MARKET_RESOLVED`, `TICK_SIZE_CHANGE`
  - Handler invocation via `asyncio.create_task()` (non-blocking)
  - Track subscription stats for health endpoint
  - Error isolation: one handler crash doesn't affect others

  **Must NOT do**:
  - Block the WS event loop — all handlers run as background tasks
  - Create a singleton that prevents testing
  - Hardcode strategy names

  **Recommended Agent Profile**:
  - **Category**: `deep`
  - **Skills**: `[]`
  - **Reason**: Core infrastructure, must be right. Deep reasoning needed for async dispatch, error isolation, subscription lifecycle.

  **Parallelization**: Wave 1 — can run with T2,T3 in sub-order (T1→T2→T3)

  **References**:
  - `backend/core/event_bus.py` — existing event bus (SSE broadcast), extend not replace
  - `backend/infrastructure/market_stream/orderbook_router.py` — existing WS dispatch pattern (OrderbookRouter with handler registration)

  **Acceptance Criteria**:
  - [ ] `subscribe("btc_oracle", ["token_1"], ["last_trade_price"])` succeeds
  - [ ] `dispatch(event)` calls registered handler within 100ms
  - [ ] Handler exception logged, other handlers continue
  - [ ] `unsubscribe("btc_oracle")` removes all subscriptions

  **QA Scenarios**:
  ```
  Scenario: Happy path — subscribe and receive event
    Tool: interactive_bash (tmux)
    Preconditions: Event bus running, strategy subscribed
    Steps:
      1. python3 -c "from backend.core.event_bus import EventBus; ..."
      2. Subscribe strategy to token_id and event_type
      3. Dispatch a test event
      4. Assert handler was called with correct event data
    Expected Result: Handler receives event within 100ms, event data matches
    Evidence: .sisyphus/evidence/task-1-subscribe-dispatch.txt

  Scenario: Failure — handler crashes, others continue
    Tool: interactive_bash (tmux)
    Preconditions: Two strategies subscribed
    Steps:
      1. Register handler A (raises exception) and handler B (normal) for same event
      2. Dispatch event
      3. Assert handler A error logged
      4. Assert handler B executed successfully
    Expected Result: Handler B runs, handler A error logged, no crash
    Evidence: .sisyphus/evidence/task-1-error-isolation.txt
  ```

  **Commit**: YES
  - Message: `feat(event-bus): pub/sub dispatch with strategy subscription management`
  - Files: `backend/core/event_bus.py`

- [ ] 2. WS → Event Bus Bridge

  **What to do**:
  - Modify `backend/data/polymarket_websocket.py` or create adapter
  - Route incoming WS events from CLOB Market WS into the Event Bus
  - Parse raw WS messages into typed event objects
  - Handle `book`, `price_change`, `last_trade_price`, `tick_size_change`, `market_resolved`, `new_market`
  - Maintain the existing `OrderbookRouter` / `OrderbookCache` integration (don't break it)
  - Add event type tagging based on WS message fields

  **Must NOT do**:
  - Duplicate the WS connection — reuse existing `PolymarketWebSocket`
  - Remove existing `OrderbookCache` pipeline
  - Block the WS receive loop

  **Recommended Agent Profile**:
  - **Category**: `deep`
  - **Skills**: `[]`
  - **Reason**: Must integrate with existing polymorphic WS client code while adding event bus routing. Requires understanding of both systems.

  **Parallelization**: Wave 1 — depends on T1

  **References**:
  - `backend/data/polymarket_websocket.py` — existing WS client with callback registration (`on_orderbook`, `on_trade`)
  - `backend/data/ws_client.py` — generic WS client base
  - `backend/api/lifespan.py:177-212` — where WS callbacks are currently registered

  **Acceptance Criteria**:
  - [ ] CLOB WS `last_trade_price` event → Event Bus dispatch → strategy handler called
  - [ ] CLOB WS `book` event → Event Bus dispatch + OrderbookCache update (both fire)
  - [ ] CLOB WS `market_resolved` event → Event Bus dispatch → settlement handler triggered
  - [ ] WS disconnect → Event Bus receives `WS_DISCONNECTED` event → strategies activate REST fallback

  **QA Scenarios**:
  ```
  Scenario: Happy path — live trade event flows to strategy
    Tool: interactive_bash (tmux)
    Preconditions: CLOB WS connected, strategy subscribed to token
    Steps:
      1. Start bot with event bus
      2. Subscribe test strategy to a live token's last_trade_price
      3. Wait for real trade event on that token
      4. Assert strategy handler called with price, size, side from event
    Expected Result: Handler called with real trade data within 100ms of WS event
    Evidence: .sisyphus/evidence/task-2-live-trade.txt

  Scenario: Disconnect — WS drops, strategies get fallback notification
    Tool: interactive_bash (tmux)
    Preconditions: CLOB WS connected
    Steps:
      1. Kill WS connection (iptables drop or process kill)
      2. Assert Event Bus receives WS_DISCONNECTED
      3. Assert strategy fallback handlers activated
    Expected Result: Fallback mode active within 30s of disconnect
    Evidence: .sisyphus/evidence/task-2-disconnect-fallback.txt
  ```

  **Commit**: YES
  - Message: `feat(ws-bridge): route CLOB WS events into event bus for strategy dispatch`
  - Files: `backend/data/polymarket_websocket.py`, `backend/data/ws_event_bridge.py`

- [ ] 3. Strategy Subscription Interface

  **What to do**:
  - Add to `BaseStrategy`:
    - `subscribed_tokens: Set[str]` — token IDs this strategy wants
    - `subscribed_events: Set[str]` — event types to receive
    - `async def on_market_event(event: MarketEvent) -> Optional[dict]` — handler (returns decision or None)
    - `async def on_ws_disconnected()` — called when WS drops, activates REST fallback
    - `async def on_ws_reconnected()` — called when WS reconnects, deactivates REST fallback
  - `MarketEvent` dataclass: `token_id, event_type, data (dict), timestamp`
  - Strategy registration in orchestrator: `event_bus.subscribe(strategy_name, tokens, events)`
  - Deprecate `run_cycle()` — mark as legacy, keep for REST-only strategies
  - REST fallback wrapper uses existing `run_cycle()` logic with rate-limit protection

  **Must NOT do**:
  - Remove `run_cycle()` — REST-only strategies (kalshi_arb) still need it
  - Force all strategies to migrate at once — both modes coexist during transition

  **Recommended Agent Profile**:
  - **Category**: `deep`
  - **Skills**: `[]`
  - **Reason**: Changes the strategy contract. Must be backward-compatible and clean.

  **Parallelization**: Wave 1 — depends on T1

  **References**:
  - `backend/strategies/base.py` — `BaseStrategy` ABC, `StrategyContext`, `run_cycle()`
  - `backend/strategies/btc_oracle.py` — example strategy to model subscription against
  - `backend/core/strategy_executor.py:88-147` — `execute_decision()` used by handlers

  **Acceptance Criteria**:
  - [ ] `BaseStrategy` has `subscribed_tokens`, `subscribed_events`, `on_market_event()`
  - [ ] `on_market_event()` returns `Optional[dict]` (decision dict or None)
  - [ ] `on_ws_disconnected()` / `on_ws_reconnected()` implemented with default no-op
  - [ ] Existing strategies with `run_cycle()` still work unchanged
  - [ ] `execute_decision()` called from `on_market_event()` preserves track_name attribution

  **QA Scenarios**:
  ```
  Scenario: Happy path — strategy handles event, returns decision
    Tool: interactive_bash (tmux)
    Preconditions: Strategy subclass with on_market_event implemented
    Steps:
      1. Create event = MarketEvent(token_id="X", event_type="last_trade_price", data={...})
      2. Call strategy.on_market_event(event)
      3. Assert returns decision dict with decision="BUY", market_ticker, confidence
    Expected Result: Valid decision dict returned
    Evidence: .sisyphus/evidence/task-3-handler-decision.txt

  Scenario: No signal — handler returns None, no trade
    Tool: interactive_bash (tmux)
    Preconditions: Strategy subclass, uninteresting event
    Steps:
      1. Create event with small trade (below threshold)
      2. Call strategy.on_market_event(event)
      3. Assert returns None
    Expected Result: None returned, no trade executed
    Evidence: .sisyphus/evidence/task-3-handler-noop.txt
  ```

  **Commit**: YES
  - Message: `feat(strategy): add WS event subscription interface to BaseStrategy`
  - Files: `backend/strategies/base.py`, `backend/core/ws_strategy_bridge.py`

- [ ] 4. WS Token Discovery

  **What to do**:
  - Each strategy declares `subscribed_tokens` at registration time
  - Orchestrator collects all tokens across all strategies
  - Lifespan subscribes CLOB WS to the union of all tokens
  - Dynamic subscribe/unsubscribe when strategies start/stop
  - Token IDs from strategy's market knowledge, not hardcoded
  - For strategies that discover tokens dynamically (universal_scanner): re-subscribe when token list changes

  **Must NOT do**:
  - Subscribe to tokens without strategy registration — no wasted WS bandwidth
  - Subscribe to >200 tokens (POLYMARKET_WS_SUBSCRIPTION_LIMIT)

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: `[]`
  - **Reason**: Wiring task — connect existing components. Strategy provides tokens, lifespan subscribes them.

  **Parallelization**: Wave 1 — depends on T1,T2

  **References**:
  - `backend/api/lifespan.py:154-220` — existing WS startup with token subscription
  - `backend/data/polymarket_websocket.py:434` — `get_market_websocket(asset_ids)`
  - `backend/strategies/base.py` — StrategyContext provides market data

  **Acceptance Criteria**:
  - [ ] All active strategies report their `subscribed_tokens` at startup
  - [ ] CLOB WS subscribes to union of all strategy tokens
  - [ ] Log message: "WebSocket subscribed to N tokens across M strategies"
  - [ ] Dynamic subscribe when new strategy starts
  - [ ] Dynamic unsubscribe when strategy stops

  **QA Scenarios**:
  ```
  Scenario: Happy path — strategies provide tokens, WS subscribes
    Tool: interactive_bash (tmux)
    Preconditions: 2 strategies with different token sets
    Steps:
      1. Start orchestrator with strategies
      2. Check log: "WebSocket subscribed to N tokens across 2 strategies"
      3. Query event bus status endpoint
      4. Assert both strategies' tokens are in subscription list
    Expected Result: All tokens subscribed, strategies receive events
    Evidence: .sisyphus/evidence/task-4-token-discovery.txt
  ```

  **Commit**: YES
  - Message: `feat(ws): strategy-driven token discovery for WS subscription`
  - Files: `backend/api/lifespan.py`, `backend/core/orchestrator.py`

- [ ] 5. REST Fallback Wrapper

  **What to do**:
  - Create `backend/core/ws_fallback.py`
  - Context manager pattern: `async with ws_fallback(strategy, token_ids) as mode:`
  - Auto-detects WS state: `mode == "ws"` or `mode == "rest"`
  - When WS connected: forward events to `on_market_event()`
  - When WS disconnected: activate `run_cycle()` with rate-limit protection
  - Circuit breaker prevents aggressive REST polling during extended WS outages
  - Exponential backoff: 30s → 60s → 120s → 300s (max) between REST cycles
  - Logging: "strategy_name switched to REST fallback (WS disconnected for Xs)"

  **Must NOT do**:
  - Call REST APIs more frequently than 60s even in fallback
  - Override strategy-specific rate limits
  - Block strategy from receiving events when WS reconnects mid-cycle

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
  - **Skills**: `[]`
  - **Reason**: State machine + rate limiting logic. Medium complexity, high reliability requirement.

  **Parallelization**: Wave 1 — depends on T1

  **References**:
  - `backend/core/circuit_breaker.py` — existing breaker pattern for fallback protection
  - `backend/core/scheduling_strategies.py:700-808` — existing auto_trader REST polling with backoff
  - `backend/data/polymarket_websocket.py` — WS connection state tracking

  **Acceptance Criteria**:
  - [ ] WS connected → REST calls blocked, handlers use event data
  - [ ] WS disconnected → `on_ws_disconnected()` called → REST fallback activates within 30s
  - [ ] WS reconnected → `on_ws_reconnected()` called → REST fallback deactivates
  - [ ] REST fallback respects rate limits: max 1 call/60s, exponential backoff on 429
  - [ ] Circuit breaker opens after 5 consecutive REST failures → stops polling for 300s

  **QA Scenarios**:
  ```
  Scenario: WS healthy — no REST calls
    Tool: interactive_bash (tmux)
    Preconditions: WS connected, strategy subscribed
    Steps:
      1. Run bot for 5 minutes
      2. grep logs for "REST fallback"
      3. Assert 0 REST calls to Polymarket API
    Expected Result: 0 REST calls during WS uptime
    Evidence: .sisyphus/evidence/task-5-no-rest-calls.txt

  Scenario: WS drops — REST fallback with backoff
    Tool: interactive_bash (tmux)
    Preconditions: WS connected
    Steps:
      1. Kill WS connection
      2. Wait 30s — assert "switched to REST fallback" logged
      3. Check REST call interval: ≥60s between calls
      4. Check 429 handling: exponential backoff applied
    Expected Result: REST fallback active, intervals ≥60s, backoff on 429
    Evidence: .sisyphus/evidence/task-5-rest-fallback.txt
  ```

  **Commit**: YES
  - Message: `feat(fallback): WS-first execution with REST fallback and rate-limit protection`
  - Files: `backend/core/ws_fallback.py`

- [ ] 6. Event Bus Health Endpoint

  **What to do**:
  - Add `GET /api/v1/events/status` endpoint
  - Returns:
    - `ws_connected`: boolean
    - `subscriptions`: [{strategy, tokens, events, handler_count}]
    - `events_dispatched`: count since startup
    - `fallback_active`: [{strategy, mode, since}]
    - `latency_p50_ms`, `latency_p99_ms`
  - Add `GET /api/v1/events/strategies` — list all subscribed strategies with token/event details

  **Must NOT do**:
  - Expose sensitive data (wallet addresses, API keys)
  - Block on event bus lock during status query

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: `[]`
  - **Reason**: Simple API endpoint wiring. Read-only, no state mutation.

  **Parallelization**: Wave 1 — depends on T1

  **Acceptance Criteria**:
  - [ ] `GET /api/v1/events/status` returns valid JSON with all fields
  - [ ] `GET /api/v1/events/strategies` returns strategy subscription list
  - [ ] Both endpoints return within 100ms

  **QA Scenarios**:
  ```
  Scenario: Status endpoint returns subscription state
    Tool: Bash (curl)
    Preconditions: Bot running, strategies subscribed
    Steps:
      1. curl http://localhost:8000/api/v1/events/status | jq .
      2. Assert ws_connected = true
      3. Assert subscriptions array non-empty
      4. Assert each subscription has strategy, tokens, events fields
    Expected Result: Valid JSON with subscription state
    Evidence: .sisyphus/evidence/task-6-status.json
  ```

  **Commit**: YES
  - Message: `feat(api): event bus health and subscription status endpoints`
  - Files: `backend/api/events.py`
  - **References**: `backend/api/admin.py` — admin endpoint patterns for auth, `backend/core/event_bus.py` — event bus state to expose

- [ ] 7. Migrate btc_oracle to Event-Driven

  **What to do**:
  - Add `subscribed_tokens` and `subscribed_events` to `BtcOracleStrategy`
  - Implement `on_market_event()` — receives `last_trade_price` events for BTC tokens → evaluates oracle edge → returns decision dict or None
  - Convert existing `run_cycle()` logic into event handler: price comparison, edge calculation, direction detection
  - Register with event bus at startup via orchestrator
  - REST fallback: call existing `generate_btc_signal()` only when WS disconnected
  - Token discovery: `btc_markets.py` already knows BTC token IDs — pass them at registration

  **Must NOT do**:
  - Duplicate REST API calls when WS is connected
  - Change the signal/trade attribution (track_name="btc_oracle" preserved)

  **Recommended Agent Profile**: `deep` | **Parallel**: Wave 2 (with T8-T13) | **Depends**: T2,T3,T4,T5 | **References**: `backend/strategies/btc_oracle.py:220-299`, `backend/core/signals.py:284-299`

  **Acceptance Criteria**:
  - [ ] `subscribed_tokens` populated from active BTC markets
  - [ ] `on_market_event()` returns BUY decision when edge > threshold
  - [ ] `on_market_event()` returns None when no edge
  - [ ] REST fallback calls `generate_btc_signal()` only when WS disconnected
  - [ ] `track_name="btc_oracle"` preserved in signal/trade attribution

  **QA Scenarios**: Pattern from Task 3 — subscribe, inject trade event, verify decision or no-op. Evidence: `.sisyphus/evidence/task-7-btc-oracle.txt`

  **Commit**: YES — `feat(strategy): migrate btc_oracle to event-driven execution`

- [ ] 8. Migrate whale_frontrun to Event-Driven

  **What to do**:
  - Implement `on_market_event()` for `last_trade_price` events with large size (>=$10K)
  - When whale-sized trade detected → front-run decision
  - REST fallback: use fixed WalletConfig wallets with rate-limited polling
  - WS path replaces the broken `whale_monitor_ws` connection
  - Token subscription from active whale-tracked tokens

  **Must NOT do**: Reconnect to fake `ws.polymarket.com/whale` (already fixed). Don't poll REST when WS delivers events.

  **Recommended Agent Profile**: `deep` | **Parallel**: Wave 2 | **Depends**: T2,T3,T4,T5 | **References**: `backend/modules/data_feeds/whale_frontrun.py:97-177`, `backend/data/whale_monitor_ws.py`

  **Acceptance Criteria**:
  - [ ] Large trades (>=$10K) from WS trigger front-run decision
  - [ ] Small trades (<$10K) skipped
  - [ ] REST fallback uses WalletConfig wallets with proper `user=` param

  **QA Scenarios**: Inject large trade event → assert BUY decision. Inject small trade → assert None. Evidence: `.sisyphus/evidence/task-8-whale.txt`

  **Commit**: YES — `feat(strategy): migrate whale_frontrun to event-driven execution`

- [ ] 9. Migrate copy_trader to Event-Driven

  **What to do**:
  - Subscribe to leaderboard traders' token activity via WS
  - `on_market_event()` for `last_trade_price` → mirror trade proportionally
  - REST fallback: leaderboard API with long cache (900s)
  - Track copied positions via user channel `trade` events (own fills)

  **Must NOT do**: Hit leaderboard API more than once per 900s

  **Recommended Agent Profile**: `deep` | **Parallel**: Wave 2 | **Depends**: T2,T3,T4,T5 | **References**: `backend/modules/execution/copy_trader.py:331-550`, `backend/data/polymarket_clob.py:431`

  **Acceptance Criteria**:
  - [ ] Leaderboard trader's trade on WS → copy trade created
  - [ ] Position size proportional to Kelly fraction
  - [ ] REST leaderboard cache: max 1 call/900s

  **QA Scenarios**: Inject leaderboard trade → assert mirror trade. Evidence: `.sisyphus/evidence/task-9-copy-trader.txt`

  **Commit**: YES — `feat(strategy): migrate copy_trader to event-driven execution`

- [ ] 10. Migrate weather_emos to Event-Driven

  **What to do**:
  - Weather strategy is hybrid: WS for market data, REST for weather forecasts (Open-Meteo has no WS)
  - `on_market_event()` for weather token price changes → re-evaluate edge against forecast
  - REST fallback for forecast data: Open-Meteo 300s interval
  - Market resolution events auto-settle weather positions

  **Must NOT do**: Hit Open-Meteo more than once per 300s

  **Recommended Agent Profile**: `deep` | **Parallel**: Wave 2 | **Depends**: T2,T3,T4,T5 | **References**: `backend/modules/scanners/weather_emos.py:390-750`, `backend/data/weather.py:258`

  **Acceptance Criteria**:
  - [ ] Weather token price change → edge re-evaluated against forecast
  - [ ] Forecast cache valid for 300s
  - [ ] Market resolution → auto-settle

  **QA Scenarios**: Inject price change for weather token → assert edge check. Evidence: `.sisyphus/evidence/task-10-weather.txt`

  **Commit**: YES — `feat(strategy): migrate weather_emos to event-driven execution`

- [ ] 11. Migrate universal_scanner to Event-Driven

  **What to do**:
  - Dynamic token discovery via `new_market` events (custom_feature_enabled)
  - `on_market_event()` for `book` and `price_change` → scanner evaluates all subscribed tokens
  - Initial token load from Gamma API (one-time at startup, then WS incremental)
  - Re-subscribe when new markets appear

  **Must NOT do**: Continuously poll Gamma `/markets` — use `new_market` WS event for incremental

  **Recommended Agent Profile**: `unspecified-high` | **Parallel**: Wave 2 | **Depends**: T2,T3,T4,T5 | **References**: `backend/strategies/universal_scanner.py:120-220`, `backend/data/market_universe.py:64`

  **Acceptance Criteria**:
  - [ ] `new_market` event → token subscribed dynamically
  - [ ] Scanner evaluates all subscribed tokens on book/price events
  - [ ] Initial token load from Gamma API (startup only)

  **QA Scenarios**: Inject new_market event → assert token subscribed. Evidence: `.sisyphus/evidence/task-11-universal.txt`

  **Commit**: YES — `feat(strategy): migrate universal_scanner to event-driven execution`

- [ ] 12. Migrate whale_pnl_tracker to Event-Driven

  **What to do**:
  - Subscribe to whale-tracked tokens via WS
  - `on_market_event()` for `last_trade_price` → update whale PnL tracking
  - REST fallback: Data API `/positions?user=WALLET` with 300s interval
  - PnL threshold triggers signal when whale profit exceeds config

  **Must NOT do**: Hit `/positions` more than once per 300s per wallet

  **Recommended Agent Profile**: `unspecified-high` | **Parallel**: Wave 2 | **Depends**: T2,T3,T4,T5 | **References**: `backend/modules/data_feeds/whale_pnl_tracker.py`

  **QA Scenarios**: Inject whale trade → assert PnL updated. Evidence: `.sisyphus/evidence/task-12-whale-pnl.txt`

  **Commit**: YES — `feat(strategy): migrate whale_pnl_tracker to event-driven execution`

- [ ] 13. Migrate kalshi_arb to REST-Only (no WS available)

  **What to do**:
  - Kalshi has no WebSocket — this strategy stays REST-only
  - Keep `run_cycle()` but add circuit breaker and rate-limit protection
  - No event bus subscription needed
  - Label as `ws_mode = "unsupported"` for health endpoint visibility

  **Must NOT do**: Create fake WS connection. Don't remove from scheduler yet.

  **Recommended Agent Profile**: `quick` | **Parallel**: Wave 2 | **Depends**: T5 | **References**: `backend/data/kalshi_client.py:80`, `backend/modules/arbitrage/kalshi_arb.py:44`

  **Commit**: YES — `feat(strategy): add REST-only rate-limit protection to kalshi_arb`

  **QA Scenarios**:
  ```
  Scenario: Kalshi REST cycle respects rate limits
    Tool: interactive_bash (tmux)
    Preconditions: kalshi_arb enabled, 300s interval
    Steps:
      1. Start bot, wait for kalshi_arb cycle
      2. Check log: interval >= 300s between cycles
      3. Check kalshi_breaker state: CLOSED after successful call
    Expected Result: Cycle runs at 300s, breaker status healthy
    Evidence: .sisyphus/evidence/task-13-kalshi.txt
  ```

- [ ] 14. RTDS WebSocket for Crypto/Equity Prices

  **What to do**:
  - Connect RTDS WebSocket (`ws-live-data.polymarket.com`)
  - Subscribe to crypto_prices (BTC, ETH, SOL) and equity_prices (AAPL, TSLA)
  - Route into event bus for btc_oracle to consume instead of CEX REST APIs
  - PING every 5s per RTDS protocol

  **Must NOT do**: Continue hitting CEX REST APIs (Coinbase/Kraken/Binance) when RTDS is connected

  **Recommended Agent Profile**: `unspecified-high` | **Parallel**: Wave 3 | **Depends**: T2 | **References**: `backend/data/crypto.py:103-183`, RTDS docs: `ws-live-data.polymarket.com`

  **QA Scenarios**: Connect RTDS → assert BTC price events flowing. Evidence: `.sisyphus/evidence/task-14-rtds.txt`

  **Commit**: YES — `feat(rtds): connect real-time data socket for crypto/equity feeds`

- [ ] 15. Remove strategy_cycle_job from APScheduler

  **What to do**:
  - In `scheduler.py`, comment out `strategy_cycle_job` from `JOB_FUNCTION_REGISTRY` and all `schedule_strategy()` calls
  - Keep `scan_and_trade_job`, `settlement_job`, `heartbeat_job`, `auto_trader_job`, AGI jobs
  - Log deprecation warning if any strategy still calls `schedule_strategy()`
  - Remove strategy cycle intervals from seed config

  **Must NOT do**: Remove AGI, settlement, heartbeat, wallet sync, or market scan jobs

  **Recommended Agent Profile**: `quick` | **Parallel**: Wave 3 | **Depends**: T7-T13 | **References**: `backend/core/scheduler.py:361`, `backend/core/scheduling_strategies.py:838-967`

  **Commit**: YES — `chore(scheduler): remove strategy_cycle_job, keep AGI/settlement jobs`

  **QA Scenarios**:
  ```
  Scenario: strategy_cycle_job removed, other jobs survive
    Tool: interactive_bash (tmux)
    Preconditions: Bot running with migrated strategies
    Steps:
      1. pm2 logs polyedge-bot | grep "strategy_cycle_job" | wc -l → 0
      2. pm2 logs polyedge-bot | grep "settlement_job" | wc -l → >0
      3. pm2 logs polyedge-bot | grep "heartbeat_job" | wc -l → >0
      4. pm2 logs polyedge-bot | grep "AGI.*cycle\|promotion_job" | wc -l → >0
    Expected Result: 0 strategy_cycle_job, other jobs still running
    Evidence: .sisyphus/evidence/task-15-scheduler.txt
  ```

- [ ] 16. Clean Seed Config and Strategy Config

  **What to do**:
  - Remove `interval_seconds` from `lifespan.py` seed tuples (no longer needed)
  - Keep `enabled` and `params` — still needed for strategy initialization
  - Drop `interval_seconds` column from `StrategyConfig` OR keep as deprecated with default 0
  - Add `ws_mode` column to `StrategyConfig`: "event_driven", "rest_only", "hybrid"

  **Must NOT do**: Drop the column if it's referenced elsewhere (check first)

  **Recommended Agent Profile**: `quick` | **Parallel**: Wave 3 | **Depends**: T15 | **References**: `backend/api/lifespan.py:703-716`, `backend/models/database.py` (StrategyConfig model)

  **Commit**: YES — `chore(config): deprecate interval_seconds, add ws_mode to StrategyConfig`

  **QA Scenarios**:
  ```
  Scenario: ws_mode column added, interval_seconds deprecated
    Tool: Bash (sqlite3)
    Preconditions: Migration applied
    Steps:
      1. sqlite3 tradingbot.db "PRAGMA table_info(strategy_config)" | grep ws_mode
      2. Assert ws_mode column exists with values: event_driven, rest_only, hybrid
      3. Verify no strategy has interval_seconds in seed config (lifespan.py)
    Expected Result: ws_mode column present, seed config clean
    Evidence: .sisyphus/evidence/task-16-config.txt
  ```

- [ ] 17. Update Architecture and Project Docs

  **What to do**:
  - Update `ARCHITECTURE.md` — replace timer-driven diagram with event-driven architecture
  - Update `README.md` — mention event-driven WebSocket-first execution
  - Update `docs/project-structure.md` — add new event bus and fallback files
  - Update `backend/strategies/AGENTS.md` — document event-driven strategy contract
  - Update `IMPLEMENTATION_GAPS.md` — mark scheduler polling as fixed

  **Must NOT do**: Modify ADRs, delete existing content

  **Recommended Agent Profile**: `writing` | **Parallel**: Wave 3 | **Depends**: T7-T14 | **References**: existing docs files in project root and docs/

  **Commit**: YES — `docs: update architecture and docs for event-driven WS-first execution`

  **QA Scenarios**:
  ```
  Scenario: Architecture doc reflects event-driven design
    Tool: Bash (grep)
    Preconditions: All docs updated
    Steps:
      1. grep "Event Bus" ARCHITECTURE.md → found
      2. grep "WebSocket-first" README.md → found
      3. grep "ws_fallback.py" docs/project-structure.md → found
      4. grep "on_market_event" backend/strategies/AGENTS.md → found
    Expected Result: All 4 docs reference new event-driven architecture
    Evidence: .sisyphus/evidence/task-17-docs.txt
  ```

- [ ] 18. Integration Test Suite

  **What to do**:
  - Create `backend/tests/test_event_bus.py` — unit tests for pub/sub, dispatch, error isolation
  - Create `backend/tests/test_ws_fallback.py` — test WS connect/disconnect/reconnect state machine
  - Create `backend/tests/test_event_driven_strategies.py` — integration: mock WS events → strategy handler → trade
  - Verify all existing tests still pass (backward compatibility)

  **Must NOT do**: Hit real Polymarket APIs in tests — use mocks

  **Recommended Agent Profile**: `unspecified-high` | **Parallel**: Wave 3 (can run with T15-T17) | **Depends**: T1-T5 | **References**: `backend/tests/conftest.py` — existing test patterns

  **Acceptance Criteria**:
  - [ ] Mock WS event → strategy handler called → trade created
  - [ ] Mock WS disconnect → REST fallback activated
  - [ ] Mock WS reconnect → REST fallback deactivated
  - [ ] All existing tests pass unchanged

  **QA Scenarios**: Run full test suite. Evidence: `.sisyphus/evidence/task-18-tests.txt`

  **Commit**: YES — `test: event-driven strategy integration tests`

- [ ] F1. Plan Compliance Audit — `oracle`
  Read plan end-to-end. Verify:
  - All "Must Have" present in implementation
  - All "Must NOT Have" absent
  - Zero hardcoded strategy names
  - All signal/trade attribution preserved
  - REST fallback functional on demand
  Output: `Must Have [N/N] | Must NOT Have [N/N] | Tasks [N/N] | VERDICT: APPROVE/REJECT`

- [ ] F2. Code Quality Review — `unspecified-high`
  Run `ruff` + `pytest`. Check for:
  - No `as any`, `@ts-ignore`, empty catches, console.log leftovers
  - No hardcoded URLs or strategy names
  - Event handler timeout protection
  - Memory leaks in subscription management
  Output: `Lint [PASS/FAIL] | Tests [N pass/N fail] | Issues [N] | VERDICT`

- [ ] F3. Real Manual QA — `unspecified-high` + tmux
  - Start bot with event bus
  - Subscribe test strategy to live token
  - Wait for real trade event → verify handler called
  - Kill WS → verify REST fallback activates
  - Restore WS → verify REST fallback deactivates
  - Check all 7 strategies produce events/signals
  Output: `Scenarios [N/N pass] | Fallback [N/N] | Edge Cases [N tested] | VERDICT`

- [ ] F4. Scope Fidelity Check — `deep`
  For each task: verify "What to do" matches implementation diffs
  Check "Must NOT do" compliance
  Detect cross-task contamination
  Flag unaccounted changes
  Output: `Tasks [N/N compliant] | Contamination [CLEAN/N issues] | Unaccounted [CLEAN/N files] | VERDICT`

---

## Commit Strategy

- **Wave 1**: 6 commits — one per task
  - Commits 1-6: `feat(event-bus): ...`, `feat(ws-bridge): ...`, `feat(strategy): ...`, `feat(ws): ...`, `feat(fallback): ...`, `feat(api): ...`

- **Wave 2**: 7 commits — one per strategy migration
  - Commits 7-13: `feat(strategy): migrate {name} to event-driven execution`

- **Wave 3**: 5 commits
  - Commits 14-18: `feat(rtds): ...`, `chore(scheduler): ...`, `chore(config): ...`, `chore(db): ...`, `docs: ...`

- **Wave FINAL**: 1 commit after all 4 reviewers approve
  - `chore: final verification — all event-driven migrations complete`

---

## Success Criteria

### Verification Commands
```bash
# All tests pass
pytest backend/tests/ -x

# No strategy_cycle_job in scheduler logs
pm2 logs polyedge-bot | grep "strategy_cycle_job" | wc -l
# Expected: 0

# All strategies subscribed via event bus
curl http://localhost:8000/api/v1/events/strategies | jq '. | length'
# Expected: >= 7

# Zero REST calls during WS uptime (5 min window)
pm2 logs polyedge-bot --lines 1000 | grep "REST fallback" | wc -l
# Expected: 0

# REST fallback activates within 30s of WS kill
pm2 logs polyedge-bot | grep "switched to REST fallback"
# Expected: log line within 30s of WS disconnect
```

### Final Checklist
- [ ] All 7 active strategies migrated to event-driven
- [ ] 0 strategy_cycle_jobs in APScheduler
- [ ] WS events dispatch to strategies within 100ms
- [ ] REST fallback activates within 30s of WS disconnect
- [ ] REST fallback respects rate limits (≥60s between calls)
- [ ] Circuit breaker prevents aggressive REST during extended outages
- [ ] All signal/trade attribution preserved
- [ ] 0 hardcoded strategy names
- [ ] AGI, settlement, heartbeat, wallet sync jobs still on APScheduler
- [ ] Paper mode works with event-driven execution
- [ ] `pytest backend/tests/ -x` passes
- [ ] Health endpoint shows subscription state
- [ ] Docs updated (ARCHITECTURE.md, README.md, project-structure.md)
