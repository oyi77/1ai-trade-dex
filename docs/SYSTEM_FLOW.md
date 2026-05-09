# PolyEdge System Flow — Complete Technical Reference

> **Audience**: Engineers, AI agents, and operators who need to understand how every subsystem connects.
>
> **Conventions**: All diagrams use Mermaid syntax. File paths are relative to project root.

---

## 1. High-Level Architecture

```mermaid
graph TB
    subgraph Frontend["Frontend (React 18 + TypeScript + Vite)"]
        D[Dashboard]
        A[Admin Panel]
        S[Signals Table]
        T[Trades Table]
        G[GlobeView]
        AG[AGI Control]
    end

    subgraph API["API Layer (FastAPI)"]
        R[REST Routes<br/>81 endpoints]
        WS[WebSocket/SSE<br/>Market ticks + Whale alerts]
        MW[Middleware<br/>CORS + Prometheus + Auth]
    end

    subgraph Core["Core Engine"]
        ORC[Orchestrator]
        SCH[APScheduler]
        RM[RiskManager]
        STX[StrategyExecutor]
        AT[AutoTrader]
        SET[Settlement Engine]
    end

    subgraph Strategies["9 Strategies"]
        BTC[BTC Momentum]
        WEA[Weather EMOS]
        COPY[Copy Trader]
        MM[Market Maker]
        KAL[Kalshi Arb]
        ORC2[BTC Oracle]
        BOND[Bond Scanner]
        WHALE[Whale PNL]
        RT[Realtime Scanner]
    end

    subgraph AGI["AGI Intelligence Layer"]
        PROM[AutonomousPromoter]
        HEALTH[StrategyHealthMonitor]
        FORENS[TradeForensics]
        ALLOC[BankrollAllocator]
        REGIME[RegimeDetector]
        KGRAPH[KnowledgeGraph]
    end

    subgraph Data["Data Sources"]
        CLOB[Polymarket CLOB]
        KALS[Kalshi API]
        CRYPTO[Coinbase/Kraken/Binance]
        WEATHER[Open-Meteo GFS]
    end

    subgraph Storage["Storage & Infra"]
        DB[(SQLite / PostgreSQL)]
        Q[Job Queue<br/>Redis → SQLite fallback]
        CACHE[Cache Layer]
        PROM2[Prometheus Metrics]
    end

    Frontend -->|REST polling<br/>TanStack Query| API
    Frontend -->|SSE stream| WS
    API --> Core
    Core --> Strategies
    Core --> AGI
    Strategies --> Data
    Core --> Storage
    AGI --> Storage
```

---

## 2. Startup Sequence

```mermaid
sequenceDiagram
    participant Main as __main__.py
    participant Orch as Orchestrator
    participant DB as Database
    participant CLOB as CLOB Client
    participant Reg as Strategy Registry
    participant Sched as APScheduler
    participant API as FastAPI
    participant TG as Telegram Bot

    Main->>Orch: main()
    Orch->>DB: init_db() — create all tables
    Orch->>DB: seed BotState (paper/testnet/live)
    Orch->>DB: seed preset risk profiles
    Orch->>CLOB: init_clob_client()
    Note over CLOB: Connects to Polymarket<br/>Polygon L2
    Orch->>Reg: load_all_strategies()
    Note over Reg: @register_strategy decorator<br/>auto-discovers all 9 strategies
    Reg-->>Orch: strategy_map
    Orch->>DB: upsert StrategyConfig for each
    Orch->>Sched: configure_jobs()
    Note over Sched: Schedules:<br/>BTC scan (60s),<br/>Weather scan (configurable),<br/>Settlement (120s),<br/>Auto-trader (configurable),<br/>AGI promotion (6h),<br/>Bankroll allocation (daily),<br/>Health check (15min)
    Orch->>API: start_uvicorn()
    Note over API: FastAPI on port 8000<br/>Lifespan handler manages<br/>DB session pool + scheduler
    opt TELEGRAM_BOT_TOKEN set
        Orch->>TG: start_bot()
    end
    Note over Orch: System running.<br/>Scheduler fires jobs,<br/>API serves requests.
```

### Environment-Driven Feature Flags

| Flag | Default | Controls |
|------|---------|----------|
| `ACTIVE_MODES` | `paper` | Which modes run (comma-separated) |
| `SHADOW_MODE` | `false` | Observe-only, no trade execution |
| `AI_ENABLED` | `true` | Master toggle for AI signal analysis |
| `AUTO_TRADER_ENABLED` | `true` | Auto-execute high-confidence signals |
| `AGI_AUTO_PROMOTE` | `false` | Allow paper→live without human approval |
| `AGI_STRATEGY_HEALTH_ENABLED` | `true` | Auto-disable killed strategies |
| `AGI_BANKROLL_ALLOCATION_ENABLED` | `false` | Daily capital reallocation |
| `JOB_WORKER_ENABLED` | `false` | Redis/SQLite job queue |
| `WEATHER_ENABLED` | `true` | Weather market scanning |
| `KALSHI_ENABLED` | `false` | Kalshi platform integration |
| `WHALE_LISTENER_ENABLED` | `false` | Whale position tracking |
| `POLYMARKET_WS_ENABLED` | `true` | Real-time market data via WebSocket |

---

## 3. Signal Generation Flow

```mermaid
flowchart TD
    SCH[APScheduler tick] --> JOB[job handler<br/>scan_and_trade_job<br/>weather_scan_and_trade_job<br/>etc.]
    JOB --> STRAT[Strategy.run_cycle<br/>context]
    STRAT --> SIG[List of TradingSignal]
    SIG --> AT[AutoTrader.route_signal]
    
    AT --> CONF{confidence >=<br/>threshold?}
    CONF -->|No, paper mode<br/>threshold = 0.45| REJECT1[Log low confidence<br/>record_signal rejected_confidence]
    CONF -->|Yes| RM[RiskManager.validate_trade]
    
    RM --> DL{Daily loss<br/>breaker enabled<br/>for mode?}
    DL -->|No, paper mode| SKIP1[Skip daily loss check]
    DL -->|Yes| DLEXceeded{Daily loss<br/>exceeded?}
    DLEXceeded -->|Yes| REJECT2[REJECTED_DAILY_LOSS]
    
    SKIP1 --> DW{Drawdown breaker<br/>enabled for mode?}
    DLEXceeded -->|No| DW
    DW -->|No, paper mode| SKIP2[Skip drawdown check]
    DW -->|Yes| DBREACH{Drawdown<br/>breached?}
    DBREACH -->|Yes| REJECT3[REJECTED_DRAWDOWN_BREAKER]
    DBREACH -->|No| UNS
    SKIP2 --> UNS
    
    UNS{Unsettled trade<br/>for this market?}
    UNS -->|Yes| REJECT4[REJECTED_UNSETTLED]
    UNS -->|No| POS[Position size check<br/>MAX_POSITION_FRACTION]
    
    POS --> EXP[Exposure check<br/>MAX_TOTAL_EXPOSURE_FRACTION]
    EXP -->|Exceeded| CAP[Cap size to remaining<br/>or reject]
    EXP -->|OK| SLIP{Slippage<br/>check}
    
    SLIP -->|Exceeded| REJECT5[REJECTED_SLIPPAGE]
    SLIP -->|OK| ALLOC[Strategy allocation<br/>cap check]
    
    ALLOC -->|Exhausted| REJECT6[REJECTED_ALLOCATION]
    ALLOC -->|Capped| ADJ[Adjusted size]
    ALLOC -->|OK| ADJ2[Original size approved]
    
    ADJ --> APPROVE[RiskDecision<br/>allowed=True]
    ADJ2 --> APPROVE
    
    REJECT1 --> REC[TradeAttempt<br/>record_rejected]
    REJECT2 --> REC
    REJECT3 --> REC
    REJECT4 --> REC
    REJECT5 --> REC
    REJECT6 --> REC
    
    APPROVE --> EXEC[StrategyExecutor<br/>execute_decision]
    
    style SKIP1 fill:#2d6a4f,color:#fff
    style SKIP2 fill:#2d6a4f,color:#fff
    style REJECT2 fill:#e63946,color:#fff
    style REJECT3 fill:#e63946,color:#fff
    style APPROVE fill:#2d6a4f,color:#fff
```

### Per-Mode Breaker Configuration

| Mode | Drawdown Breaker | Daily Loss Limit | Confidence Threshold | Min Order |
|------|-----------------|-------------------|---------------------|-----------|
| **paper** | ❌ Disabled | ❌ Disabled | 0.45 (relaxed) | $1 |
| **testnet** | ✅ Enabled | ✅ Enabled | AUTO_APPROVE_MIN_CONFIDENCE | $5 |
| **live** | ✅ Enabled | ✅ Enabled | AUTO_APPROVE_MIN_CONFIDENCE | $5 |
| **shadow** | N/A (no trades) | N/A (no trades) | N/A | N/A |

Configurable via `DRAWDOWN_BREAKER_ENABLED_PER_MODE` and `DAILY_LOSS_LIMIT_ENABLED_PER_MODE` dicts.

---

## 4. Trade Execution Flow

```mermaid
flowchart TD
    DECISION[RiskDecision<br/>allowed=True, adjusted_size] --> MODE{effective_mode?}
    
    MODE -->|paper| PAPER[Create Trade row in DB<br/>no CLOB order placed<br/>set trading_mode='paper']
    MODE -->|testnet| TESTNET[Place CLOB order<br/>on Polygon Amoy L2<br/>set trading_mode='testnet']
    MODE -->|live| LIVE[Place CLOB order<br/>on Polygon mainnet<br/>set trading_mode='live']
    
    PAPER --> TA[Record TradeAttempt<br/>phase=execution<br/>outcome=executed]
    TESTNET --> TA
    LIVE --> TA
    
    TA --> EVENT[publish_event<br/>trade_executed]
    EVENT --> SSE[SSE push to<br/>dashboard clients]
    
    PAPER --> BOTSTATE[Update BotState<br/>paper_pnl, paper_trades]
    TESTNET --> BOTSTATE2[Update BotState<br/>testnet_pnl, testnet_trades]
    LIVE --> BOTSTATE3[Update BotState<br/>via bankroll_reconciliation<br/>CLOB + Data API]
```

### Bankroll Source of Truth (ADR-002)

```mermaid
flowchart LR
    subgraph Live_Mode["Live Mode"]
        CLOB2[CLOB USDC balance] --> ADD[+]
        POS[Polymarket Data API<br/>open position value] --> ADD
        ADD --> LIVE_EQ[BotState.bankroll<br/>Authoritative live equity]
    end
    
    subgraph Paper_Testnet["Paper / Testnet Mode"]
        INIT2[initial_bankroll<br/>paper_initial_bankroll] --> CALC
        REALIZED[Sum of settled Trade.pnl<br/>for matching trading_mode] --> CALC
        CALC --> PAPER_EQ[BotState.paper_pnl / testnet_pnl<br/>Ledger-derived]
    end
    
    LIVE_EQ --> DASH[Dashboard shows<br/>live equity curve]
    PAPER_EQ --> DASH2[Dashboard shows<br/>paper/testnet equity]
```

> **Critical**: Never recompute live equity from local ledger. Live `BotState.bankroll` and `total_pnl` come from external sources only. See `docs/architecture/adr-002-live-equity-source.md`.

---

## 5. Settlement Engine

```mermaid
flowchart TD
    SCHED[settlement_job<br/>runs every 120s] --> FETCH[Fetch resolved markets<br/>from Gamma API + Data API]
    
    FETCH --> MATCH[Match unresolved Trade rows<br/>to market outcomes]
    
    MATCH --> OUTCOME{Outcome available?}
    OUTCOME -->|No| WAIT[Skip — retry next cycle]
    OUTCOME -->|Yes| PNL[Calculate PnL per trade]
    
    PNL --> DIR{Trade direction<br/>vs outcome}
    DIR -->|direction='up'<br/>outcome=1.0| WIN[PnL = (1 - entry_price) × size]
    DIR -->|direction='up'<br/>outcome=0.0| LOSS[PnL = -entry_price × size]
    DIR -->|direction='down'<br/>outcome=0.0| LOSS
    DIR -->|direction='down'<br/>outcome=1.0| WIN2[PnL = (1 - entry_price) × size<br/>(went down, we bet down)]
    
    WIN --> SETTLE[Mark Trade.settled=True<br/>Set Trade.pnl and result]
    LOSS --> SETTLE
    WIN2 --> SETTLE
    
    SETTLE --> UPDATE[Update BotState totals:<br/>total_pnl, winning_trades]
    UPDATE --> FORENSICS{Trade.pnl < 0?}
    FORENSICS -->|Yes| ANALYZE[TradeForensics.analyze_losing_trade<br/>Diagnose root cause]
    FORENSICS -->|No| SKIP3[Continue]
    
    ANALYZE --> HEALTH[StrategyHealthMonitor.assess<br/>Update strategy health metrics]
    HEALTH --> KILL{Health status = 'killed'?}
    KILL -->|Yes| DISABLE[Auto-disable strategy<br/>in StrategyConfig]
    KILL -->|No| CONTINUE[Continue]
    
    DISABLE --> EVENT2[publish_event settlement_completed]
    CONTINUE --> EVENT2
    SKIP3 --> EVENT2
    EVENT2 --> SSE2[SSE push to dashboard]
```

---

## 6. AGI Autonomy & Experiment Lifecycle

```mermaid
stateDiagram-v2
    [*] --> DRAFT: Strategy proposed<br/>or synthesized
    
    DRAFT --> SHADOW: SHADOW criteria met<br/>≥0 trades, ≥0 days
    
    SHADOW --> PAPER: PAPER criteria met<br/>≥100 trades, ≥7 days<br/>≥45% win rate<br/>≤25% max drawdown<br/>Sharpe ≥ 0.3
    
    PAPER --> LIVE_TRIAL: LIVE_TRIAL criteria met<br/>≥50 trades, ≥3 days<br/>≥50% win rate<br/>Sharpe ≥ 0.5<br/>≤20% max drawdown
    
    LIVE_TRIAL --> LIVE_PROMOTED: LIVE_PROMOTED criteria met<br/>Sustained performance<br/>over trial period
    
    LIVE_PROMOTED --> RETIRED: Health kill detected<br/>Win rate < 5% OR<br/>Sharpe < -2.0 AND drawdown > 50%
    
    SHADOW --> RETIRED: Health kill
    PAPER --> RETIRED: Health kill
    DRAFT --> RETIRED: Abandoned
    
    LIVE_PROMOTED --> PAPER: Degraded<br/>(demotion loop,<br/>auto-demote enabled)
    LIVE_TRIAL --> PAPER: Degraded<br/>(demotion loop)
    
    note right of SHADOW: No trade execution<br/>Logs signals only<br/>ShadowRunner records<br/>in-memory ShadowTrade
    note right of PAPER: Creates Trade rows in DB<br/>No CLOB orders<br/>Paper bankroll tracking
    note right of LIVE_TRIAL: Limited real CLOB orders<br/>Small position sizes<br/>Trial period validation
    note right of LIVE_PROMOTED: Full real CLOB orders<br/>Real USDC at risk<br/>Bankroll from external API
    
    state RETIRED {
        [*] --> Disabled
        Disabled --> CoolingOff: After cooldown period
        CoolingOff --> [*]: Rehabilitation check<br/>≥50% recent win rate<br/>+ positive PnL
    }
```

### Full Promotion Pipeline: DRAFT → SHADOW → PAPER → LIVE_TRIAL → LIVE_PROMOTED

The AGI experiment lifecycle follows a five-stage promotion pipeline with demotion loops:

1. **DRAFT** — Strategy proposed by human or synthesized by `StrategySynthesizer`. No trade execution. Must pass 4-gate validation before entering SHADOW.
2. **SHADOW** — Signal logging only; `ShadowRunner` records in-memory `ShadowTrade` objects. The `shadow_validation_job` recalculates per-genome fitness from settled shadow trades, syncs `GenomePerformance`, and evaluates stage gates for promotion to PAPER.
3. **PAPER** — Creates `Trade` rows in DB with simulated bankroll. No CLOB orders. Strategies that degrade from LIVE_TRIAL or LIVE_PROMOTED are demoted back here with parameter improvement via `ForensicsIntegration`.
4. **LIVE_TRIAL** — Limited real CLOB orders with small position sizes. Validates that strategy performance translates from paper to live conditions.
5. **LIVE_PROMOTED** — Full real CLOB orders with real USDC at risk. Bankroll sourced from external CLOB + Data API (ADR-002).

**Demotion loop**: LIVE_PROMOTED → PAPER (if auto-demote enabled and health degrades). Demoted strategies receive parameter overhaul via `ForensicsIntegration._has_active_experiment()` which excludes RETIRED genomes.

### Genome Evolution Pipeline

```mermaid
flowchart TD
    subgraph Genome_Evolution["Genome Evolution Pipeline"]
        MUT[Mutation<br/>Random parameter perturbation<br/>of existing genomes]
        CROSS[Crossover<br/>Combine chromosomes from<br/>two parent genomes]
        FIT[Fitness Refresh<br/>Recalculate fitness from<br/>settled ShadowTrade data]
        REB[Population Rebalance<br/>Adjust genome population<br/>based on fitness rankings]
    end
    
    MUT --> NEW_GENOME[New StrategyGenome]
    CROSS --> NEW_GENOME
    NEW_GENOME --> VALIDATE[4-Gate Validation<br/>syntax → lint → backtest → sandbox]
    VALIDATE -->|Pass| SHADOW_STAGE[Enter SHADOW stage<br/>ShadowRunner tracks signals]
    VALIDATE -->|Fail| DISCARD[Discard genome<br/>Log validation failure]
    
    FIT --> UPDATE_PERF[Update GenomePerformance<br/>win_rate, sharpe, max_drawdown]
    UPDATE_PERF --> GATE_CHECK{Stage gate<br/>criteria met?}
    GATE_CHECK -->|Yes| PROMOTE_STAGE[Promote to next stage]
    GATE_CHECK -->|No| CONTINUE[Continue in current stage]
    
    REB --> RANK[StrategyRanker<br/>Rank by fitness + health]
    RANK --> ALLOC[BankrollAllocator<br/>Allocate capital by rank]
```

The genome evolution pipeline (`backend/application/strategy/genome_compiler.py`, `backend/application/strategy/genome_strategy.py`) operates as follows:

- **Mutation**: Random perturbation of existing genome chromosomes (entry, exit, risk, execution parameters)
- **Crossover**: Combines chromosomes from two parent genomes to produce offspring
- **Fitness Refresh**: `shadow_validation_job` recalculates per-genome fitness from settled `ShadowTrade` records, syncing `GenomePerformance` metrics
- **Population Rebalance**: `StrategyRanker` adjusts the active genome population based on fitness rankings, culling underperformers and promoting strong candidates

### 4-Gate Strategy Synthesis Validation

```mermaid
flowchart LR
    INPUT[StrategySynthesizer<br/>LLM-generated strategy] --> G1[Gate 1: Syntax<br/>Python AST parse<br/>No syntax errors]
    G1 -->|Pass| G2[Gate 2: Lint<br/>Pylint static analysis<br/>No critical errors]
    G2 -->|Pass| G3[Gate 3: Backtest<br/>Historical performance<br/>Positive expected value]
    G3 -->|Pass| G4[Gate 4: Sandbox<br/>Live paper execution<br/>No runtime errors]
    G4 -->|Pass| SHADOW[Enter SHADOW stage]
    
    G1 -->|Fail| REJECT1[Log syntax error<br/>Discard genome]
    G2 -->|Fail| REJECT2[Log lint errors<br/>Discard genome]
    G3 -->|Fail| REJECT3[Log backtest failure<br/>Discard genome]
    G4 -->|Fail| REJECT4[Log sandbox crash<br/>Discard genome]
```

The `StrategySynthesizer` (`backend/core/strategy_synthesizer.py`) uses LLM-powered strategy generation with a 4-gate validation pipeline. Only strategies that pass all four gates (syntax → lint → backtest → sandbox) enter the SHADOW stage. Failed genomes are discarded with detailed validation logs.

### Shadow-Trade Fitness Feedback Loop

```mermaid
flowchart TD
    SHADOW_JOB[shadow_validation_job<br/>Scheduled periodically] --> FETCH[Fetch settled<br/>ShadowTrade records]
    FETCH --> CALC[Recalculate per-genome<br/>fitness metrics<br/>win_rate, sharpe, max_drawdown]
    CALC --> SYNC[Sync GenomePerformance<br/>in database]
    SYNC --> GATE{Stage gate<br/>criteria met?}
    GATE -->|SHADOW → PAPER| PROMOTE_P[Promote to PAPER<br/>Create StrategyConfig]
    GATE -->|PAPER → LIVE_TRIAL| PROMOTE_L[Promote to LIVE_TRIAL<br/>Enable live execution]
    GATE -->|No| CHECK_HEALTH{Health check<br/>kill threshold?}
    CHECK_HEALTH -->|Yes| KILL[Auto-kill strategy<br/>Move to GRAVEYARD]
    CHECK_HEALTH -->|No| CONTINUE2[Continue in current stage]
```

The `shadow_validation_job` (`backend/application/agi/evolution_jobs.py`) is the canonical shadow-trade feedback loop. It recalculates per-genome fitness from settled `ShadowTrade` records, syncs `GenomePerformance`, promotes SHADOW→PAPER and PAPER→LIVE_TRIAL by metric gates, and auto-kills terminal performers to GRAVEYARD.

### Model Calibration Drift Check

```mermaid
flowchart TD
    CALIB_JOB[model_calibration_check_job<br/>Scheduled periodically] --> BRIER[Calculate Brier score<br/>for each strategy's<br/>prediction accuracy]
    BRIER --> DRIFT{Brier score<br/>drift detected?}
    DRIFT -->|Yes| RETRAIN[Trigger model retrain<br/>Adjust strategy parameters<br/>via auto_improve]
    DRIFT -->|No| STABLE[Continue monitoring<br/>No action needed]
```

The `model_calibration_check_job` (`backend/core/agi_jobs.py`) monitors prediction accuracy drift using Brier scores. When drift exceeds thresholds, it triggers model retraining and parameter adjustment via `auto_improve`.

### Autonomous Daemons

```mermaid
flowchart TD
    subgraph Scheduled_Jobs["APScheduler Jobs"]
        P6[autonomous_promotion_job<br/>every 6h]
        D[bankroll_allocation_job<br/>daily]
        H[health_check_job<br/>every 15min]
        N[nightly_review_job<br/>daily at 2am]
        S[settlement_job<br/>every 120s]
        BTC2[btc_scan_and_trade_job<br/>every 60s]
        WX[weather_scan_and_trade_job<br/>configurable]
        SV[shadow_validation_job<br/>periodic]
        MC[model_calibration_check_job<br/>periodic]
    end
    
    P6 --> PROM[AutonomousPromoter]
    PROM --> EVAL[Evaluate all experiments<br/>against stage criteria]
    EVAL --> PROMOTE[Promote passing<br/>experiments]
    EVAL --> RETIRE[Retire failing<br/>experiments]
    
    D --> ALLOC2[BankrollAllocator]
    ALLOC2 --> RANK[StrategyRanker.auto_allocate]
    RANK --> WRITE[Write allocations to<br/>BotState.misc_data]
    
    H --> AGI Health
    AGI Health[AGIHealthCheck]
    AGI Health --> CHECK[Validate strategy staleness,<br/>data freshness, budget,<br/>scheduler, orphans]
    
    N --> REVIEW[NightlyReview]
    REVIEW --> LOG2[Write markdown log<br/>to docs/agi-log/]
    
    SV --> FITNESS[Recalculate genome fitness<br/>from ShadowTrade data]
    FITNESS --> SYNC_PERF[Sync GenomePerformance]
    SYNC_PERF --> GATE_EVAL[Evaluate stage gates<br/>for promotion/demotion]
    
    MC --> BRIER[Calculate Brier scores<br/>Check calibration drift]
    BRIER --> DRIFT_CHECK{Drift detected?}
    DRIFT_CHECK -->|Yes| RETRAIN[Trigger model retrain<br/>via auto_improve]
    DRIFT_CHECK -->|No| MONITOR[Continue monitoring]
```

### Promotion Gate Criteria

| Transition | Min Trades | Min Days | Win Rate | Sharpe | Max Drawdown |
|-----------|-----------|----------|----------|--------|-------------|
| DRAFT → SHADOW | 0 | 0 | — | — | — |
| SHADOW → PAPER | 100 | 7 | ≥45% | ≥0.3 | ≤25% |
| PAPER → LIVE_TRIAL | 50 | 3 | ≥50% | ≥0.5 | ≤20% |
| LIVE_TRIAL → LIVE_PROMOTED | — | — | Sustained performance | — | — |
| Kill (any mode) | — | — | <5% | <−2.0 AND | >50% |

> **Note**: Crazy-tier strategies skip the 14-day minimum via `_get_strategy_risk_tier()` in `fronttest_validator.py`.

---

## 7. Risk Management — Detailed

```mermaid
flowchart TD
    subgraph Config_Layer["Configuration Layer"]
        CFG1[DRAWDOWN_BREAKER_ENABLED_PER_MODE<br/>paper: false, testnet: true, live: true]
        CFG2[DAILY_LOSS_LIMIT_ENABLED_PER_MODE<br/>paper: false, testnet: true, live: true]
        CFG3[MAX_POSITION_FRACTION: 0.08<br/>MAX_TOTAL_EXPOSURE_FRACTION: 0.70<br/>SLIPPAGE_TOLERANCE: 0.02]
        CFG4[Risk Profiles<br/>safe / normal / aggressive / extreme<br/>Override all thresholds at runtime]
        CFG5[AUTO_APPROVE_MIN_CONFIDENCE: 0.50<br/>PAPER threshold: 0.45]
    end
    
    subgraph Validation_Order["RiskManager.validate_trade() Validation Order"]
        step1[1. Confidence check<br/>paper: 0.45, others: AUTO_APPROVE_MIN_CONFIDENCE]
        step2[2. Daily loss limit<br/>SKIPPED if breaker disabled for mode]
        step3[3. Drawdown breaker<br/>SKIPPED if breaker disabled for mode]
        step4[4. Unsettled trade check<br/>No re-entry on same market]
        step5[5. Position size cap<br/>live: available_cash × MAX_POSITION_FRACTION<br/>paper: bankroll × MAX_POSITION_FRACTION]
        step6[6. Total exposure limit<br/>live: bankroll × MAX_TOTAL_EXPOSURE_FRACTION<br/>paper: (bankroll + exposure) × fraction]
        step7[7. Slippage tolerance<br/>Reject if slippage > SLIPPAGE_TOLERANCE]
        step8[8. Strategy allocation cap<br/>From BankrollAllocator]
        
        step1 --> step2 --> step3 --> step4 --> step5 --> step6 --> step7 --> step8
    end
    
    Config_Layer --> Validation_Order
    
    step8 --> RESULT[RiskDecision<br/>allowed, reason, adjusted_size]
```

### Drawdown Breaker Internals

```mermaid
flowchart TD
    CHECK[check_drawdown<br/>bankroll, db, mode] --> QUERY_D[Query: sum of Trade.pnl<br/>settled in last 24h<br/>WHERE trading_mode = mode<br/>AND NOT settlement_source LIKE 'backfill_%']
    
    CHECK --> QUERY_W[Query: sum of Trade.pnl<br/>settled in last 7d<br/>WHERE trading_mode = mode<br/>AND NOT settlement_source LIKE 'backfill_%']
    
    QUERY_D --> BASE[base_bankroll = max<br/>current_bankroll, mode_initial_bankroll]
    QUERY_W --> BASE
    
    BASE --> COMPARE_D{daily_pnl <=<br/>-daily_limit?}
    COMPARE_D -->|Yes| BREACH_D[24h loss exceeds<br/>DAILY_DRAWDOWN_LIMIT_PCT<br/>of base_bankroll]
    COMPARE_D -->|No| COMPARE_W{weekly_pnl <=<br/>-weekly_limit?}
    
    COMPARE_W -->|Yes| BREACH_W[7d loss exceeds<br/>WEEKLY_DRAWDOWN_LIMIT_PCT<br/>of base_bankroll]
    COMPARE_W -->|No| OK[DrawdownStatus<br/>is_breached = False]
    
    BREACH_D --> BLOCKED[DrawdownStatus<br/>is_breached = True<br/>breach_reason with details]
    BREACH_W --> BLOCKED
    
    style BREACH_D fill:#e63946,color:#fff
    style BREACH_W fill:#e63946,color:#fff
    style OK fill:#2d6a4f,color:#fff
    style BLOCKED fill:#e63946,color:#fff
```

---

## 8. Frontend Architecture

```mermaid
flowchart TD
    subgraph Pages["Pages"]
        DASH[Dashboard.tsx]
        ADMN[Admin.tsx]
        AGI2[AGIControl.tsx]
    end
    
    subgraph Dashboard_Components["Dashboard Components"]
        OV[OverviewTab<br/>Equity curve, P&L, bankroll]
        TRD[TradesTab<br/>Trade history, P&L]
        SIG2[SignalsTab<br/>Pending/approved/signals]
        CTRL[ControlRoomTab<br/>TradeAttempt ledger]
        DEB[DebateMonitorTab<br/>MiroFish dual-debate]
        STAT2[StatsTab<br/>Strategy performance]
    end
    
    subgraph Admin_Components["Admin Components"]
        STG2[StrategiesTab<br/>Enable/disable/configure]
        RSK[RiskTab<br/>Risk profiles, limits]
        CFG7[ConfigTab<br/>Runtime settings]
        SYS[SystemTab<br/>Health, mode, scheduler]
    end
    
    subgraph AGI_Components["AGI Components"]
        EMER2[EmergencyStop<br/>Kill all trading]
        GOAL2[GoalOverride<br/>Switch AGI objective]
        REG2[RegimeDisplay<br/>Market regime icon]
        EXP2[ExperimentsTab<br/>Promotion pipeline]
    end
    
    subgraph API_Layer["API Layer (api.ts)"]
        POLLS[TanStack Query<br/>pollFast 5s<br/>pollNormal 30s<br/>pollSlow 5min]
        ADMIN_API[adminApi<br/>cookie auth + CSRF]
    end
    
    DASH --> Dashboard_Components
    ADMN --> Admin_Components
    AGI2 --> AGI_Components
    
    Dashboard_Components --> POLLS
    Admin_Components --> ADMIN_API
    AGI_Components --> POLLS
```

### Polling Intervals

| Hook | Default | Used For |
|------|---------|----------|
| `VITE_POLL_FAST_MS` | 5000 | Trade updates, signal status |
| `VITE_POLL_NORMAL_MS` | 30000 | Dashboard overview, equity |
| `VITE_POLL_SLOW_MS` | 300000 | Strategy config, system status |
| `VITE_POLL_VERY_SLOW_MS` | 600000 | AGI experiments, promotion state |

### Auth Flow

```mermaid
sequenceDiagram
    participant Browser
    participant FastAPI
    participant SessionStore

    Browser->>FastAPI: POST /admin/auth/login<br/>{username, password}
    FastAPI->>SessionStore: Create session<br/>(_SESSION_STORE in-memory, 24h TTL)
    SessionStore-->>FastAPI: session_id
    FastAPI-->>Browser: Set-Cookie: admin_session=<id><br/>httpOnly, secure, sameSite=strict<br/>+ CSRF token in response body
    Browser->>Browser: Store CSRF token<br/>in sessionStorage

    Browser->>FastAPI: GET /api/dashboard<br/>Cookie: admin_session=<id><br/>X-CSRF-Token: <token>
    FastAPI->>SessionStore: Validate session + CSRF
    SessionStore-->>FastAPI: Valid
    FastAPI-->>Browser: 200 OK + data

    Browser->>FastAPI: POST /admin/auth/logout
    FastAPI->>SessionStore: Delete session
    FastAPI-->>Browser: Clear cookie
```

---

## 9. Data Sources & External APIs

```mermaid
flowchart LR
    subgraph Market_Data["Market Data Sources"]
        CLOB_API[Polymarket CLOB API<br/>gamma-api.polymarket.com<br/>clob.polymarket.com]
        KALS_API[Kalshi API<br/>api.kalshi.com]
        GAMMA[Gamma Markets API<br/>Active + resolved markets]
        POLY_WS[Polymarket WebSocket<br/>Real-time orderbook]
    end
    
    subgraph Crypto_Data["Crypto Data Sources"]
        CB[Coinbase<br/>BTC/USDC candles]
        KR[Kraken<br/>BTC/USDC candles]
        BN[Binance<br/>BTC/USDC candles]
    end
    
    subgraph Weather_Data["Weather Data Sources"]
        OM[Open-Meteo API<br/>GFS ensemble 31 members]
        NWS[NWS API<br/>US temperature forecasts]
    end
    
    subgraph AI_Data["AI Providers"]
        CLAUDE[Anthropic Claude<br/>Signal analysis]
        GROQ[Groq Llama<br/>Fast inference]
        CUSTOM[Custom Provider<br/>Configurable endpoint]
        MIRO[MiroFish<br/>External dual debate]
    end
    
    subgraph Blockchain["Blockchain"]
        POLY[Polygon L2<br/>Mainnet: USDC + CLOB<br/>Amoy: Testnet USDC]
    end
    
    CLOB_API --> ORDER_MGR[Order Management<br/>Place, cancel, fill]
    KALS_API --> ARB[Arbitrage Detector<br/>Cross-platform gaps]
    GAMMA --> SCANNER[Market Scanner<br/>Active markets]
    POLY_WS --> WS_HANDLER[WebSocket Handler<br/>Real-time ticks]
    
    CB --> BTC_STR[BTC Momentum<br/>1m/5m/15m candles]
    KR --> BTC_STR
    BN --> BTC_STR
    
    OM --> WX_STR[Weather EMOS<br/>GFS ensemble forecast]
    NWS --> WX_STR
    
    CLAUDE --> ENSEMBLE[AI Ensemble<br/>Multi-provider aggregation]
    GROQ --> ENSEMBLE
    CUSTOM --> ENSEMBLE
    MIRO --> DEBATE[Dual Debate Engine<br/>Bull vs Bear + Judge]
```

---

## 10. Database Schema (Key Tables)

```mermaid
erDiagram
    BotState ||--o{ Trade : "has many"
    BotState {
        int id PK
        string mode "paper/testnet/live"
        float bankroll "Live: external equity"
        float total_pnl "Cumulative P&L"
        float paper_pnl "Paper mode P&L"
        float testnet_pnl "Testnet P&L"
        float paper_initial_bankroll "Paper starting capital"
        float testnet_initial_bankroll "Testnet starting capital"
        int total_trades
        int winning_trades
        string misc_data "JSON: allocations, flags"
    }
    
    Trade ||--o| Signal : "from signal"
    Trade {
        int id PK
        string market_ticker
        string direction "up/down"
        float entry_price
        float size
        string strategy "Which strategy"
        string trading_mode "paper/testnet/live"
        bool settled
        float pnl "Realized profit/loss"
        string result "win/loss/partial"
        datetime settlement_time
        string settlement_source "backfill_* excluded"
    }
    
    Signal {
        int id PK
        string market_ticker
        float model_probability
        float edge
        float confidence
        string strategy_name
        string status "pending/approved/rejected"
    }
    
    StrategyConfig {
        int id PK
        string name UK "Strategy identifier"
        bool enabled
        int interval_seconds
        string params_json "Strategy-specific config"
    }
    
    TradeAttempt {
        int id PK
        int signal_id FK
        string phase "signal_gate/risk_gate/execution"
        string reason_code "REJECTED_CONFIDENCE etc"
        float requested_size
        float adjusted_size
        string outcome "executed/rejected/skipped"
        datetime created_at
    }
    
    StrategyPerformanceSnapshot {
        int id PK
        string strategy_name
        float win_rate
        float sharpe
        float max_drawdown
        float brier_score
        datetime timestamp
    }
    
    RiskProfileRow {
        string name PK "safe/normal/aggressive/extreme"
        string display_name
        float kelly_fraction
        float max_trade_size
        float daily_drawdown_limit_pct
        float weekly_drawdown_limit_pct
        float auto_approve_min_confidence
    }
```

---

## 11. Job Queue Architecture (ADR-001)

```mermaid
flowchart TD
    JOB[Job Producer<br/>APScheduler + strategies] --> QUEUE{JOB_WORKER_ENABLED?}
    
    QUEUE -->|True| REDIS_Q[Redis Queue<br/>rq + arq<br/>Priority-based ordering]
    QUEUE -->|False| SQLITE_Q[SQLite Queue<br/>AsyncSQLiteQueue<br/>Fallback when no Redis]
    
    REDIS_Q --> WORKER[Job Worker Pool<br/>MAX_CONCURRENT_JOBS=1]
    SQLITE_Q --> WORKER2[Job Worker<br/>Same logic, SQLite backend]
    
    WORKER --> EXEC[Execute Job<br/>scan, settle, promote, etc.]
    WORKER2 --> EXEC
    
    EXEC --> RESULT{Success?}
    RESULT -->|Yes| COMPLETE[Mark complete]
    RESULT -->|No| RETRY[Retry with backoff<br/>max JOB_TIMEOUT_SECONDS]
    
    RETRY --> RESULT2{Retries exhausted?}
    RESULT2 -->|Yes| FAIL[Mark failed]
    RESULT2 -->|No| EXEC
```

---

## 12. Risk Profiles (ADR-005)

```mermaid
flowchart LR
    subgraph Safe["Safe Profile"]
        S_KELLY[Kelly: 0.10]
        S_SIZE[Max Trade: $3]
        S_POS[Position: 3%]
        S_EXP[Exposure: 30%]
        S_LOSS[Daily Loss: $2]
        S_DD_D[Daily DD: 5%]
        S_DD_W[Weekly DD: 10%]
        S_CONF[Min Confidence: 70%]
    end
    
    subgraph Normal["Normal Profile (default)"]
        N_KELLY[Kelly: 0.30]
        N_SIZE[Max Trade: $8]
        N_POS[Position: 8%]
        N_EXP[Exposure: 70%]
        N_LOSS[Daily Loss: $5]
        N_DD_D[Daily DD: 10%]
        N_DD_W[Weekly DD: 20%]
        N_CONF[Min Confidence: 50%]
    end
    
    subgraph Aggressive["Aggressive Profile"]
        A_KELLY[Kelly: 0.50]
        A_SIZE[Max Trade: $20]
        A_POS[Position: 15%]
        A_EXP[Exposure: 85%]
        A_LOSS[Daily Loss: $15]
        A_DD_D[Daily DD: 20%]
        A_DD_W[Weekly DD: 35%]
        A_CONF[Min Confidence: 35%]
    end
    
    subgraph Extreme["Extreme Profile"]
        E_KELLY[Kelly: 0.80]
        E_SIZE[Max Trade: $50]
        E_POS[Position: 25%]
        E_EXP[Exposure: 95%]
        E_LOSS[Daily Loss: $40]
        E_DD_D[Daily DD: 40%]
        E_DD_W[Weekly DD: 60%]
        E_CONF[Min Confidence: 20%]
    end
    
    API[PUT /api/risk/profiles/:name<br/>Runtime editable] --> Safe
    API --> Normal
    API --> Aggressive
    API --> Extreme
    
    Safe --> APPLY[apply_profile()<br/>Overwrites runtime settings]
    Normal --> APPLY
    Aggressive --> APPLY
    Extreme --> APPLY
    
    APPLY --> SETTINGS[settings.KELLY_FRACTION<br/>settings.MAX_TRADE_SIZE<br/>settings.DAILY_DRAWDOWN_LIMIT_PCT<br/>settings.WEEKLY_DRAWDOWN_LIMIT_PCT<br/>etc.]
```

> **Note**: Risk profiles override the per-mode breaker toggles' *thresholds* but not their *enabled/disabled* state. Paper mode's `DRAWDOWN_BREAKER_ENABLED_PER_MODE=false` means the breaker is completely skipped regardless of profile.

---

## 13. Configuration Reference — Risk & Trading

| Variable | Default | Description |
|----------|---------|-------------|
| `ACTIVE_MODES` | `paper` | Comma-separated active trading modes |
| `INITIAL_BANKROLL` | `100.0` | Starting capital (paper/testnet) |
| `KELLY_FRACTION` | `0.30` | Kelly criterion fraction for sizing |
| `MAX_POSITION_FRACTION` | `0.08` | Max 8% of bankroll per trade |
| `MAX_TOTAL_EXPOSURE_FRACTION` | `0.70` | Max 70% total portfolio exposure |
| `DAILY_DRAWDOWN_LIMIT_PCT` | `0.10` | 10% daily drawdown threshold |
| `WEEKLY_DRAWDOWN_LIMIT_PCT` | `0.20` | 20% weekly drawdown threshold |
| `DAILY_LOSS_LIMIT` | `5.0` | $5 absolute daily loss limit |
| `MAX_TRADE_SIZE` | `8.0` | Maximum single trade size (live) |
| `PAPER_MIN_ORDER_USDC` | `1.0` | Minimum paper trade size |
| `MIN_ORDER_USDC` | `5.0` | Minimum live trade size |
| `AUTO_APPROVE_MIN_CONFIDENCE` | `0.50` | Auto-approve threshold |
| `MIN_EDGE_THRESHOLD` | `0.30` | 30% minimum edge to trade |
| `SLIPPAGE_TOLERANCE` | `0.02` | 2% max slippage |
| `DRAWDOWN_BREAKER_ENABLED_PER_MODE` | `paper: false, testnet/live: true` | Per-mode drawdown breaker toggle |
| `DAILY_LOSS_LIMIT_ENABLED_PER_MODE` | `paper: false, testnet/live: true` | Per-mode daily loss limit toggle |
| `RISK_PROFILE` | `normal` | Profile preset: safe/normal/aggressive/extreme |

---

## 14. Deployment Architecture

```mermaid
flowchart TD
    subgraph Railway["Railway (Backend)"]
        API2[FastAPI<br/>uvicorn<br/>Port 8000]
        WORKER2[Queue Worker<br/>PM2 managed]
        SCHEDULER2[Scheduler<br/>PM2 managed]
    end
    
    subgraph Vercel["Vercel (Frontend)"]
        FE[React SPA<br/>Vite build<br/>Static hosting]
    end
    
    subgraph Data_Infra["Data Infrastructure"]
        DB2[(SQLite<br/>Primary DB)]
        REDIS2[(Redis<br/>Optional queue<br/>Falls back to SQLite)]
    end
    
    subgraph External["External Services"]
        POLY2[Polymarket CLOB<br/>+ Data API]
        KALS2[Kalshi API]
        CLAUDE2[Anthropic Claude]
        GROQ2[Groq API]
    end
    
    FE -->|REST API| API2
    API2 --> DB2
    API2 --> REDIS2
    WORKER2 --> REDIS2
    WORKER2 --> DB2
    SCHEDULER2 --> DB2
    API2 --> POLY2
    API2 --> KALS2
    SCHEDULER2 --> CLAUDE2
    SCHEDULER2 --> GROQ2
    
    subgraph PM2_Processes["PM2 Process Manager"]
        P1[API Server<br/>ecosystem.config.js]
        P2[Queue Worker<br/>ecosystem.config.js]
        P3[Scheduler<br/>ecosystem.config.js]
    end
    
    PM2_Processes --> Railway
```

---

## 15. Circuit Breaker Pattern

```mermaid
stateDiagram-v2
    [*] --> Closed: Normal operation
    
    Closed --> Open: failure_threshold<br/>consecutive failures reached
    Open --> HalfOpen: recovery_timeout<br/>elapsed (default 60s)
    HalfOpen --> Closed: Probing call<br/>succeeds
    HalfOpen --> Open: Probing call<br/>fails
    
    note right of Closed: All requests pass through<br/>Failure count resets on success
    note right of Open: All requests fail immediately<br/>No external API calls
    note right of HalfOpen: Single probing request<br/>If success → close circuit<br/>If failure → re-open
```

Each external API (Polymarket CLOB, Kalshi, Groq, Claude) has its own `CircuitBreaker` instance. See `backend/core/circuit_breaker.py`.

---

## 16. Error Handling & Resilience

```mermaid
flowchart TD
    REQ[API Request] --> CB{Circuit Breaker<br/>for this service}
    CB -->|Closed| API2[External API Call]
    CB -->|Open| FAIL[Fail Fast<br/>Return cached/error]
    CB -->|HalfOpen| PROBE[Single Probe Request]
    
    API2 --> RESULT{Success?}
    PROBE --> RESULT
    
    RESULT -->|Yes| RESET[Reset failure count<br/>Close circuit if half-open]
    RESULT -->|No, retryable| RETRY[Retry with exponential<br/>backoff + jitter<br/>see backend/core/retry.py]
    RESULT -->|No, permanent| FAIL2[Return error<br/>Increment failure count]
    
    RETRY --> API3[Retry attempt]
    API3 --> RESULT2{Success?}
    RESULT2 -->|Yes| RESET
    RESULT2 -->|No, max retries| FAIL3[Mark circuit open]
    
    FAIL3 --> CB2[Open circuit for<br/>recovery_timeout seconds]
```

---

## 17. Trade Attempt Observability (ADR-003)

```mermaid
flowchart LR
    SIGNAL[Signal generated] --> GATE[Signal Gate<br/>confidence >= threshold?]
    GATE -->|No| ATTEMPT1[TradeAttempt<br/>phase=signal_gate<br/>reason=REJECTED_CONFIDENCE<br/>outcome=skipped]
    GATE -->|Yes| RISK[Risk Gate<br/>RiskManager.validate_trade]
    
    RISK -->|Rejected| ATTEMPT2[TradeAttempt<br/>phase=risk_gate<br/>reason=REJECTED_DRAWDOWN_BREAKER<br/>or REJECTED_DAILY_LOSS etc.<br/>outcome=rejected]
    RISK -->|Approved| EXEC2[Execution<br/>StrategyExecutor]
    
    EXEC2 --> ATTEMPT3[TradeAttempt<br/>phase=execution<br/>requested_size vs adjusted_size<br/>outcome=executed/failed]
    
    ATTEMPT1 --> DASH2[Dashboard Control Room<br/>Explains why no trade was made<br/>without mutating historical Trade rows]
    ATTEMPT2 --> DASH2
    ATTEMPT3 --> DASH2
```

> **Critical Rule**: TradeAttempt rows are never mutated. Historical `Trade` rows are never rewritten to explain rejected attempts. See `docs/architecture/adr-003-trade-attempt-observability.md`.

---

## 18. Notification & Alerting

```mermaid
flowchart TD
    EVENT[Event Bus<br/>publish_event] --> ROUTER[notification_router.py]
    
    ROUTER --> TELEGRAM[Telegram Bot<br/>High-confidence signals<br/>Trade executions<br/>Settlement alerts]
    ROUTER --> DISCORD[Discord Webhook<br/>Optional notifications]
    ROUTER --> SSE2[SSE Stream<br/>/api/events/stream<br/>Real-time dashboard updates]
    
    subgraph Alert_Types["Alert Types"]
        TRADE_ALERT[Trade executed<br/>Signal approved/rejected]
        SETTLE_ALERT[Trade settled<br/>P&L result]
        HEALTH_ALERT[Strategy health<br/>killed/warned status]
        REGIME_ALERT[Regime change<br/>Bull/Bear/Sideways/Volatile]
        ERROR_ALERT[API failures<br/>Circuit breaker trips]
    end
    
    Alert_Types --> ROUTER
```

---

## 19. Key Architectural Decisions

| ADR | Title | Decision |
|-----|-------|----------|
| ADR-001 | Job Queue | Redis preferred with SQLite fallback; idempotency keys prevent duplicate processing |
| ADR-002 | Live Equity Source | Live `BotState.bankroll` from external CLOB+Data API, never recomputed from local ledger |
| ADR-003 | Trade Attempt Observability | Separate `TradeAttempt` ledger for rejected/failed attempts; never mutate `Trade` rows |
| ADR-004 | Bounded Autonomous Sizing | Strategy/AI may propose dynamic sizes, but `RiskManager` mandates and minimum-order gates are non-bypassable |
| ADR-005 | Risk Profiles | Four presets (safe/normal/aggressive/extreme) override all thresholds at runtime via API |
| ADR-006 | AGI Autonomy Framework | Paper→Live promotion requires human approval unless `AGI_AUTO_PROMOTE=true`; health-based kill checks are automatic |

---

## 20. Testing Strategy

```mermaid
flowchart TD
    subgraph Unit_Tests["Unit Tests (pytest)"]
        RM_TEST[test_risk_manager.py<br/>Drawdown, position, exposure]
        AT_TEST[test_auto_trader.py<br/>Signal routing, confidence]
        SE_TEST[test_strategy_executor.py<br/>Paper vs live execution]
        CB_TEST[test_circuit_breaker.py<br/>State transitions]
        SET_TEST[test_settlement.py<br/>P&L calculation, outcomes]
    end
    
    subgraph Integration_Tests["Integration Tests"]
        ORC[test_orchestrator_wiring.py<br/>Full startup with mocks]
        API_TEST[test_api_health.py<br/>HTTP endpoint tests]
    end
    
    subgraph E2E_Tests["E2E Tests (Playwright)"]
        FE_TEST[frontend/e2e/<br/>Dashboard interactions]
    end
    
    Unit_Tests --> RUN[pytest backend/tests/ -v]
    Integration_Tests --> RUN
    E2E_Tests --> RUN2[cd frontend && npx playwright test]
```

### Test Commands

```bash
# Backend unit tests
pytest backend/tests/ -v

# Specific test file
pytest backend/tests/test_risk_manager.py -v

# Frontend unit tests
cd frontend && npm test

# E2E tests
cd frontend && npx playwright test

# Type check
cd frontend && npx tsc --noEmit

# Build check
cd frontend && npx vite build

# Never run live trading tests without SHADOW_MODE=true
```