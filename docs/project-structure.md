# Project Structure (v3.0 — May 2026)

**Note:** This file is a summary. See ARCHITECTURE.md for full system architecture including strategy gate, crypto oracle, and risk layer.

```
polyedge/
├── backend/
│   ├── api/
│   │   ├── main.py                 # FastAPI app, CORS, router registration
│   │   ├── auth/                   # Admin authentication, login/[forgot_otp/]reset
│   │   ├── markets.py              # Market data endpoints
│   │   ├── trading.py              # Trading endpoints
│   │   ├── system.py               # Admin/bot management (1773 lines)
│   │   ├── health.py               # Health check endpoint
│   │   ├── backtest.py             # Backtest API endpoints
│   │   ├── strategy_routes.py      # Strategy CRUD endpoints
│   │   ├── bot_control.py          # Bot start/stop/restart
│   │   ├── ws_manager_v2.py        # WebSocket management
│   │   ├── agi/                    # AGI Intelligence Layer API endpoints
│   │   └── admin/                  # Admin panel HTTP routes (settings, system)
│   ├── core/
│   │   ├── signals.py              # BTC signal generation
│   │   ├── weather_signals.py      # Weather signal generation
│   │   ├── event_bus.py            # Event publishing system
│   │   ├── errors.py               # Exception hierarchy
│   │   ├── orchestrator.py          # Central strategy coordination
│   │   ├── strategy_executor.py     # Strategy lifecycle management
│   │   ├── regime_detector.py       # Market regime classification
│   │   ├── knowledge_graph.py       # Entity-relationship memory with rollback
│   │   ├── strategy_composer.py     # Block-based strategy composition
│   │   ├── strategy_allocator.py    # Regime-aware capital allocation
│   │   ├── dynamic_prompt_engine.py # Evolving AI prompts based on outcomes
│   │   ├── agi_*.py                 # AGI engine, types, jobs, promotion pipeline
│   │   ├── self_debugger.py         # API failure diagnosis and recovery
│   │   ├── strategy_synthesizer.py  # LLM-driven Python strategy code generation
│   │   ├── experiment_runner.py     # Sandboxed strategy testing
│   │   ├── causal_reasoning.py      # Why-did-X-happen analysis
│   │   ├── llm_cost_tracker.py      # LLM spending budget enforcement
│   │   ├── risk/
│   │   │   ├── risk_manager.py      # Validate trades against position/portfolio risk
│   │   │   ├── risk_manager_hft.py  # HFT-specific risk controls
│   │   │   ├── risk_profiles.py     # Per-strategy risk profiles
│   │   │   ├── circuit_breaker.py   # Automatic trading halts
│   │   │   ├── circuit_breaker_pybreaker.py # PyBreaker-based circuit breaker
│   │   │   ├── position_sizer.py    # Position sizing logic
│   │   │   ├── exposure_limits.py   # Exposure limit enforcement
│   │   │   ├── crash_guardian.py    # Crash detection and recovery
│   │   │   ├── safety.py            # Safety checks
│   │   │   ├── sanity_checks.py     # Sanity validation
│   │   │   ├── correlation_monitor.py # Cross-strategy correlation
│   │   │   └── market_risk.py       # Market-level risk assessment
│   │   ├── scheduling/
│   │   │   ├── fronttest_scheduler.py # Fronttest job scheduling
│   │   │   ├── task_manager.py        # Task management and dispatch
│   │   │   ├── scheduler/             # Scheduler core (state, persistence, registration, etc.)
│   │   │   └── scheduling_strategies/ # Job strategies (market_scan, heartbeat, auto_trader, etc.)
│   │   ├── settlement/
│   │   │   ├── settlement.py        # Trade settlement (routes by market_type)
│   │   │   ├── settlement_helpers.py # Settlement helpers
│   │   │   ├── dispute_tracker.py   # Trade dispute resolution
│   │   │   └── auto_redeem.py       # Automatic position redemption
│   │   ├── wallet/
│   │   │   ├── wallet_reconciliation.py # Wallet state reconciliation
│   │   │   ├── wallet_router.py         # Wallet routing logic
│   │   │   ├── bankroll_allocator.py    # Bankroll allocation
│   │   │   ├── bankroll_reconciliation.py # Financial cache reconciliation
│   │   │   ├── botstate_ledger.py       # Bot state ledger
│   │   │   ├── equity_calculator.py     # Equity calculation
│   │   │   ├── wallet_auto_discovery.py # Auto-discover wallet addresses
│   │   │   └── registry.py              # Wallet registry
│   │   ├── edge/
│   │   │   ├── edge_calculator.py   # Strategy edge calculation
│   │   │   ├── edge_model.py        # Edge model management
│   │   │   ├── edge_router.py       # Edge routing logic
│   │   │   ├── edge_types.py        # Edge type definitions
│   │   │   ├── signal_pipeline.py   # Signal→decision pipeline
│   │   │   ├── exit_manager.py      # Exit strategy management
│   │   │   ├── market_scanner.py    # Market scanning
│   │   │   ├── probability_models.py # Probability estimation
│   │   │   ├── historical_edge_detector.py # Historical edge detection
│   │   │   ├── time_decay.py        # Edge time decay
│   │   │   ├── calibration_tracker.py # Calibration tracking
│   │   │   └── registry.py          # Edge component registry
│   │   ├── learning/
│   │   │   └── (model training, adaptation, and feedback modules)
│   │   ├── activity/               # Activity logging and audit trails
│   │   ├── execution_pipeline/      # Trade execution orchestration
│   │   ├── simulation/             # Paper/simulation execution
│   │   └── tests/                  # Core-level unit tests
│   ├── data/
│   │   ├── btc_markets.py          # Polymarket BTC market fetcher
│   │   ├── crypto.py               # BTC price + microstructure
│   │   ├── kalshi_client.py        # Kalshi API client (RSA-PSS auth)
│   │   ├── kalshi_markets.py       # Kalshi weather market fetcher (KXHIGH)
│   │   ├── weather.py              # Open-Meteo ensemble + NWS observations
│   │   ├── weather_markets.py      # Polymarket weather market fetcher
│   │   ├── markets.py              # Generic market wrapper
│   │   ├── rss_feed_aggregator.py  # RSS news feed aggregation
│   │   ├── economy.py              # Economic indicator data
│   │   ├── social_sentiment.py     # Social media sentiment
│   │   ├── onchain_metrics.py      # On-chain metrics
│   │   └── forecast_client.py      # Weather forecast API client
│   ├── clients/
│   │   ├── aster_client.py         # CCXT Aster DEX client
│   │   ├── azuro_client.py         # Azuro smart contract / GraphQL client
│   │   ├── bigbrain.py             # BigBrain HTTP prediction service client
│   │   ├── hyperliquid_client.py   # Hyperliquid Python SDK wrapper
│   │   ├── lighter_client.py       # CCXT Lighter DEX client
│   │   ├── limitless_client.py     # Limitless Exchange API client
│   │   ├── myriad_client.py        # Myriad REST API client
│   │   ├── ostium_client.py        # CCXT Ostium DEX client
│   │   ├── polymarket_sdk_client.py # Polymarket CLOB SDK client wrapper
│   │   ├── sxbet_client.py         # SX.Bet API client
│   │   ├── websearch.py            # Web search client (Tavily/Exa/etc.)
│   │   ├── alphaday_client.py      # AlphaDay API client
│   │   └── cryptocompare.py        # CryptoCompare price data
│   ├── models/
│   │   ├── database.py             # Re-exporter (29 lines); imports from domain files
│   │   ├── engine.py               # DB engine, recovery, migration helpers
│   │   ├── migration.py            # Alembic migration helpers
│   │   ├── recovery.py             # Crash recovery helpers
│   │   ├── trade_db.py             # Trade, HFTExecutionRecord, TradeAttempt
│   │   ├── strategy_db.py          # Strategy config, genome registry, proposals
│   │   ├── signal_db.py            # Signal, DecisionLog, AI log models
│   │   ├── wallet_db.py            # BTC prices, copy trade entries, wallet config
│   │   ├── trading_wallet.py       # Per-wallet credentials and allocations
│   │   ├── settlement_db.py        # Settlement events and transactions
│   │   ├── botstate_db.py          # Bot state and platform balances
│   │   ├── audit_db.py             # Activity/audit logs, settings, error logs
│   │   ├── kg_models.py            # Knowledge graph entities, relations, experiments
│   │   ├── misc_db.py              # Scheduler state, job queue, equity snapshots
│   │   ├── outcome_tables.py       # Strategy outcomes, health, evolution lineage
│   │   ├── hft_tables.py           # HFT signals and executions
│   │   ├── app_state.py            # App-wide state snapshots
│   │   ├── backtest.py             # Backtest run/trade storage
│   │   ├── historical_data.py      # Historical candles, outcomes, weather
│   │   ├── signal_log.py           # Per-signal instrumentation
│   │   └── genome_registry.py      # Genome persistence (22 model files total)
│   ├── markets/
│   │   ├── base_provider.py        # BaseMarketProvider abstract class
│   │   ├── provider_registry.py    # MarketProviderRegistry (auto-discovery)
│   │   ├── order_types.py          # Normalized domain order/position types
│   │   └── providers/              # 11 plug-and-play market providers
│   ├── strategies/                  # 20+ strategy implementations
│   │   ├── base.py                 # Strategy base class
│   │   ├── btc_strategies/         # BTC momentum, oracle, multi, copy trader
│   │   ├── weather_strategies/     # Weather-based strategy
│   │   └── various/                # Regime, hybrid, RL, genome strategies
│   ├── services/                    # Business logic services layer
│   ├── infrastructure/              # System infrastructure adapters
│   │   └── market_stream/           # Market data streaming
│   ├── application/
│   │   ├── strategy/
│   │   │   ├── genome_compiler.py   # Runtime genome→strategy compilation
│   │   │   └── genome_strategy.py   # Genome strategy template
│   │   └── agi/
│   │       └── evolution_jobs.py    # Shadow validation, mutation/crossover
│   ├── domain/
│   │   ├── evolution/
│   │   │   └── shadow_metrics.py    # Per-genome shadow trade metrics
│   │   └── (domain models for each bounded context)
│   ├── repositories/                # Data access layer (CRUD operations)
│   │   └── genome_repository.py     # Genome CRUD
│   ├── signals/                     # Signal processing pipeline
│   ├── sources/                     # Data source adapters
│   ├── monitoring/                  # Performance/cost monitoring
│   ├── rl/                          # Reinforcement learning modules
│   ├── mesh/                        # Mesh network coordination
│   ├── agents/                      # Agent orchestration
│   ├── evals/                       # Strategy/model evaluations
│   ├── utils/                       # Common utilities
│   ├── alembic/                     # Database migrations
│   ├── config.py                    # Pydantic-settings config
│   ├── config.example.yaml          # Example config file
│   ├── profit_dashboard.py          # Real-time profit tracking
│   └── cli.py                      # Command-line interface
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   │   ├── dashboard/
│   │   │   │   ├── OverviewTab.tsx   # Main 3-column overview
│   │   │   │   ├── TradesTab.tsx    # Trade history table
│   │   │   │   ├── SignalsTab.tsx   # Signal history table
│   │   │   │   ├── MarketsTab.tsx   # Market data tabs
│   │   │   │   ├── LeaderboardTab.tsx # Copy trader leaderboard
│   │   │   │   ├── DecisionsTab.tsx # Strategy decision logs
│   │   │   │   └── PerformanceTab.tsx # Metrics and charts
│   │   │   ├── admin/
│   │   │   │   ├── StrategiesTab.tsx # Strategy controls
│   │   │   │   ├── MarketWatchTab.tsx # Market watch CRUD
│   │   │   │   ├── WalletConfigTab.tsx # Wallet management
│   │   │   │   ├── CredentialsTab.tsx # Trading mode config
│   │   │   │   ├── TelegramTab.tsx # Telegram notifications
│   │   │   │   ├── RiskTab.tsx # Risk parameters
│   │   │   │   └── AITab.tsx # AI provider config
│   │   │   ├── AGIControlPanel.tsx   # AGI emergency stop, status, goal override
│   │   │   ├── DecisionAuditLog.tsx   # Paginated decision log with regime/goal filters
│   │   │   ├── StrategyComposerUI.tsx # Drag-to-compose strategy blocks interface
│   │   │   ├── RegimeDisplay.tsx      # Regime icons, confidence gauge, goal status
│   │   │   ├── GlobeView.tsx        # 3D globe with city markers
│   │   │   ├── EdgeDistribution.tsx # Edge distribution chart
│   │   │   ├── MicrostructurePanel.tsx # RSI gauge + indicator meters
│   │   │   ├── WeatherPanel.tsx     # Weather forecasts per city
│   │   │   ├── CalibrationPanel.tsx # Prediction accuracy tracking
│   │   │   ├── StatsCards.tsx       # Performance metrics
│   │   │   ├── SignalsTable.tsx     # BTC + Weather signals combined
│   │   │   ├── TradesTable.tsx      # Trade history
│   │   │   ├── EquityChart.tsx      # P&L chart
│   │   │   └── Terminal.tsx         # Event log + controls
│   │   ├── pages/
│   │   │   ├── Dashboard.tsx        # Main dashboard
│   │   │   ├── Admin.tsx            # Admin panel
│   │   │   └── AGIControl.tsx        # Tabbed AGI control page
│   │   ├── api/
│   │   │   ├── api.ts               # Main API client
│   │   │   └── agi.ts               # AGI API client with typed interfaces
│   │   └── types.ts                 # TypeScript interfaces
│   └── package.json
├── tests/                            # Integration tests (>472 total)
│   ├── test_agi_types.py
│   ├── test_kg_models.py
│   ├── test_regime_detector.py
│   ├── test_knowledge_graph.py
│   ├── test_strategy_allocator.py
│   ├── test_strategy_composer.py
│   ├── test_dynamic_prompt_engine.py
│   ├── test_agi_goal_engine.py
│   ├── test_self_debugger.py
│   ├── test_strategy_synthesizer.py
│   ├── test_causal_reasoning.py
│   ├── test_experiment_runner.py
│   ├── test_agi_orchestrator.py
│   ├── test_agi_api.py
│   ├── test_agi_integration.py
│   ├── test_llm_cost_tracker.py
│   ├── test_shadow_enforcement.py
│   ├── test_agi_promotion_pipeline.py
│   ├── test_agi_benchmarks.py
│   ├── test_agi_failure_injection.py
│   ├── test_genome_compiler.py
│   ├── test_evolution_jobs_feedback_loop.py
│   ├── test_scheduler_agi_jobs.py
│   ├── test_scheduler_queue_mode.py
│   ├── test_scheduling_strategies_runtime.py
│   ├── test_forecast_client.py
│   ├── test_rss_feed_aggregator.py
│   ├── test_event_bus.py
│   ├── test_orchestrator.py
│   ├── test_strategy_executor.py
│   ├── test_strategy_gate_api.py
│   ├── test_auto_redeem_job.py
│   ├── test_postgres_lock_timeouts.py
│   └── (50+ more test files)
├── requirements.txt
├── run.py
├── README.md
├── Makefile
├── .env.example
└── LICENSE
```
