"""AGI core mixin — polling intervals, AGI autonomy, promotion, forensics, monitoring."""
from dataclasses import dataclass


@dataclass
class AGICoreMixin:
    """AGI core settings: polling intervals, job worker, AGI autonomy, promotion, forensics, monitoring."""

    # Scan intervals
    SCAN_INTERVAL_SECONDS: int = 120
    SETTLEMENT_INTERVAL_SECONDS: int = 120

    # Job intervals
    JOB_WORKER_ENABLED: bool = True
    JOB_QUEUE_URL: str = "sqlite:///./job_queue.db"
    JOB_TIMEOUT_SECONDS: int = 300
    MAX_CONCURRENT_JOBS: int = 1
    DB_EXECUTOR_MAX_WORKERS: int = 4

    # AGI intervals
    AGI_PROMOTION_INTERVAL_HOURS: int = 6
    AGI_HEALTH_CHECK_INTERVAL_MINUTES: int = 15
    AGI_BANKROLL_ALLOCATION_INTERVAL_DAYS: int = 1
    AGI_CALIBRATION_CHECK_INTERVAL_HOURS: int = 6
    AUTO_IMPROVE_INTERVAL_DAYS: int = 7
    SELF_REVIEW_INTERVAL_DAYS: int = 1
    RESEARCH_PIPELINE_INTERVAL_HOURS: int = 4
    AGI_IMPROVEMENT_CYCLE_INTERVAL_HOURS: int = 4
    HISTORICAL_DATA_COLLECTOR_INTERVAL_HOURS: int = 6
    ARBITRAGE_SCAN_INTERVAL_SECONDS: int = 30
    NEWS_FEED_INTERVAL_SECONDS: int = 600

    # Evolution engine intervals
    AGI_MUTATION_INTERVAL_HOURS: int = 6
    AGI_CROSSOVER_INTERVAL_HOURS: int = 24
    MUTATION_CYCLE_INTERVAL_HOURS: int = 6
    CROSSOVER_CYCLE_INTERVAL_HOURS: int = 168  # weekly
    NECROMANCY_INTERVAL_DAYS: int = 7

    # AGI Autonomy
    AGI_AUTO_PROMOTE: bool = True
    AGI_AUTO_ENABLE: bool = True
    AGI_STRATEGY_HEALTH_ENABLED: bool = True
    AGI_HEALTH_CHECK_ENABLED: bool = True
    AGI_REHABILITATION_ENABLED: bool = True
    AGI_BANKROLL_ALLOCATION_ENABLED: bool = True
    REGIME_ROUTING_ENABLED: bool = True
    ENABLE_PAIR_COST_ARB: bool = True
    USE_EVENT_BUS_HANDLERS: bool = True

    # Promotion thresholds
    REGISTRY_MIN_WIN_RATE: float = 0.30
    REGISTRY_MIN_ROI: float = -0.30

    # Rehabilitation
    AGI_REHAB_COOLDOWN_DAYS: int = 7
    AGI_REHAB_MIN_TRADES: int = 10
    AGI_REHAB_WIN_RATE_THRESHOLD: float = 0.50
    AGI_REHAB_ALLOCATION_PCT: float = 0.25  # graduated rehab starting allocation
    AGI_REHAB_LITE_COOLDOWN_HOURS: int = 1
    AGI_REHAB_LITE_RE_DISABLE_HOURS: int = 4
    AGI_REHAB_LITE_WIN_RATE_THRESHOLD: float = 0.30
    AGI_AUTO_DISABLE_MIN_TRADES: int = 5
    AGI_AUTO_DISABLE_MIN_TRADES_LIFETIME: int = 20

    # Promotion rules
    AGI_PROMOTER_SHADOW_MIN_TRADES: int = 100
    AGI_PROMOTER_SHADOW_MIN_DAYS: int = 7
    AGI_PROMOTER_SHADOW_MIN_WIN_RATE: float = 0.45
    AGI_PROMOTER_SHADOW_MAX_DRAWDOWN: float = 0.25
    AGI_PROMOTER_PAPER_MIN_TRADES: int = 50
    AGI_PROMOTER_PAPER_MIN_DAYS: int = 3
    AGI_PROMOTER_PAPER_MIN_WIN_RATE: float = 0.50
    AGI_PROMOTER_PAPER_MIN_SHARPE: float = 0.5
    AGI_PROMOTER_PAPER_MAX_DRAWDOWN: float = 0.20

    # Fronttest
    AGI_FRONTTEST_DAYS: int = 14
    AGI_FRONTTEST_MIN_TRADES: int = 10
    AGI_FRONTTEST_MIN_WIN_RATE: float = 0.40

    # Improvement cycles
    AGI_MAX_IMPROVEMENT_ATTEMPTS: int = 3
    AGI_DEMOTION_RETRY_LIMIT: int = 3
    AGI_BROKEN_STRATEGY_OVERHAUL_ENABLED: bool = True

    # Live trial
    LIVE_TRIAL_ENABLED: bool = True
    LIVE_TRIAL_BANKROLL_PCT: float = 0.01
    LIVE_TRIAL_DURATION_DAYS: int = 7
    LIVE_TRIAL_DEGRADATION_THRESHOLD: float = 0.80
    AGI_LIVE_TRIAL_DAYS: int = 7
    AGI_LIVE_TRIAL_MIN_TRADES: int = 10

    # LLM synthesis
    AGI_SYNTHESIS_DAILY_BUDGET: float = 2.00
    AGI_BUDGET_DAILY_LIMIT_USD: float = 2.00

    # Calibration
    AGI_BRIER_DRIFT_THRESHOLD: float = 0.25
    AGI_CALIBRATION_MIN_SAMPLES: int = 30

    # Forensics
    FORENSICS_AUTO_MUTATE: bool = True
    FORENSICS_MAX_MUTATIONS_PER_DAY: int = 3
    AGI_SELF_TUNE_INTERVAL_MINUTES: int = 30
    AGI_SELF_TUNE_IN_PAPER: bool = True

    # Self-debugger
    SELF_DEBUGGER_MAX_RECOVERY_ATTEMPTS: int = 3

    # Monitoring
    MONITORING_BACKUP_MAX_AGE_HOURS: float = 2.0
    MONITORING_PNL_TOLERANCE_PCT: float = 0.02
