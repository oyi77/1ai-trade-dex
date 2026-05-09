# Project Structure

```
polyedge/
├── backend/
│   ├── api/
│   │   ├── main.py                 # FastAPI routes + dashboard
│   │   ├── auth.py                 # Admin authentication
│   │   ├── markets.py              # Market data endpoints
│   │   ├── trading.py              # Trading endpoints
│   │   ├── phase2.py               # Production Phase 2 endpoints
│   │   ├── system.py               # Admin/bot management
│   │   ├── ws_manager.py           # WebSocket management
│   │   └── agi_routes.py           # AGI Intelligence Layer API endpoints
│   ├── core/
│   │   ├── signals.py              # BTC signal generation
│   │   ├── weather_signals.py      # Weather signal generation
│   │   ├── scheduler.py            # Background jobs (BTC + weather)
│   │   ├── scheduling_strategies.py # Job strategy classes
│   │   ├── settlement.py           # Trade settlement (routes by market_type)
│   │   ├── settlement_helpers.py   # Settlement helper functions
│   │   ├── event_bus.py            # Event publishing system
│   │   ├── errors.py               # Exception hierarchy
│   │   ├── orchestrator.py          # Central strategy coordination
│   │   ├── bankroll_reconciliation.py # BotState financial cache reconciliation
│   │   ├── risk_manager.py          # Position limits, circuit breakers
│   │   ├── strategy_executor.py     # Strategy lifecycle management
│   │   ├── calibration.py          # Brier score, signal accuracy
│   │   ├── circuit_breaker.py       # Automatic trading halts
│   │   ├── regime_detector.py       # Market regime classification (bull/bear/sideways/volatile)
│   │   ├── knowledge_graph.py       # Persistent entity-relationship memory with rollback
│   │   ├── strategy_composer.py     # Block-based strategy composition
│   │   ├── strategy_allocator.py    # Regime-aware capital allocation
│   │   ├── dynamic_prompt_engine.py # Evolving AI prompts based on outcomes
│   │   ├── agi_goal_engine.py       # Regime-aware objective switching
│   │   ├── agi_orchestrator.py      # Unified AGI control loop
│   │   ├── agi_types.py             # AGI data types and enums
│   │   ├── agi_jobs.py              # AGI background job definitions
│   │   ├── agi_promotion_pipeline.py # shadow→paper→live promotion with manual approval
│   │   ├── self_debugger.py         # API failure diagnosis and recovery
│   │   ├── strategy_synthesizer.py  # LLM-driven Python strategy code generation
│   │   ├── experiment_runner.py     # Sandboxed strategy testing
│   │   ├── causal_reasoning.py      # Why-did-X-happen analysis
│   │   └── llm_cost_tracker.py      # LLM spending budget enforcement ($10/day cap)
│   ├── data/
│   │   ├── btc_markets.py          # Polymarket BTC market fetcher
│   │   ├── crypto.py               # BTC price + microstructure
│   │   ├── kalshi_client.py        # Kalshi API client (RSA-PSS auth)
│   │   ├── kalshi_markets.py       # Kalshi weather market fetcher (KXHIGH)
│   │   ├── weather.py              # Open-Meteo ensemble + NWS observations
│   │   ├── weather_markets.py      # Polymarket weather market fetcher
│   │   └── markets.py              # Generic market wrapper
│   ├── models/
│   │   ├── database.py             # SQLAlchemy models (market_type column)
│   │   ├── kg_models.py            # Knowledge graph SQLAlchemy models
│   │   └── genome_registry.py      # Genome persistence models (GenomeRegistry, GenomePerformance, GenomeShadowTrade)
│   ├── strategies/
│   │   ├── copy_trader.py          # Copy trading main logic
│   │   ├── wallet_sync.py          # Wallet sync helper
│   │   └── order_executor.py       # Order execution helper
│   ├── application/
│   │   ├── strategy/
│   │   │   ├── genome_compiler.py   # Runtime genome→strategy compilation
│   │   │   └── genome_strategy.py   # Genome strategy template (chromosome-mapped logic)
│   │   └── agi/
│   │       └── evolution_jobs.py    # Shadow validation, mutation/crossover, fitness feedback, diversity rebalance
│   ├── domain/
│   │   └── evolution/
│   │       └── shadow_metrics.py    # Per-genome shadow trade metrics (win rate, Sharpe, drawdown, fitness)
│   ├── repositories/
│   │   └── genome_repository.py     # Genome CRUD operations
│   └── config.py                   # All settings (BTC + weather)
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
├── backend/tests/
│   ├── test_agi_types.py            # AGI data types and enums tests
│   ├── test_kg_models.py            # Knowledge graph models tests
│   ├── test_regime_detector.py      # Regime detection tests
│   ├── test_knowledge_graph.py       # Knowledge graph core tests
│   ├── test_agi_fixtures.py         # AGI test fixtures
│   ├── test_strategy_allocator.py   # Regime-aware allocation tests
│   ├── test_kg_storage.py           # KG persistent storage tests
│   ├── test_strategy_composer.py    # Strategy composition tests
│   ├── test_dynamic_prompt_engine.py # Prompt evolution tests
│   ├── test_agi_goal_engine.py      # Goal engine tests
│   ├── test_self_debugger.py        # Self-debugger tests
│   ├── test_strategy_synthesizer.py  # Strategy synthesis tests
│   ├── test_causal_reasoning.py      # Causal reasoning tests
│   ├── test_experiment_runner.py     # Experiment runner tests
│   ├── test_agi_orchestrator.py      # AGI orchestrator tests
│   ├── test_agi_api.py               # AGI API endpoint tests
│   ├── test_agi_integration.py       # End-to-end AGI integration tests
│   ├── test_llm_cost_tracker.py      # LLM cost tracking tests
│   ├── test_shadow_enforcement.py    # Shadow mode enforcement audit tests
│   ├── test_agi_promotion_pipeline.py # Promotion pipeline tests
│   ├── test_agi_benchmarks.py        # Performance benchmark tests
│   ├── test_agi_failure_injection.py # Failure injection tests
│   ├── test_genome_compiler.py       # Genome compiler and strategy compilation tests
│   └── test_evolution_jobs_feedback_loop.py # Shadow validation fitness feedback loop tests
├── requirements.txt
├── run.py
└── README.md
```
