"""HFT Configuration — feature flags and performance settings for HFT strategies."""

from pydantic import BaseModel, Field


class HFTScannerConfig(BaseModel):
    PARALLEL_LIMIT: int = Field(default=50, ge=10, le=200)
    MAX_MARKETS: int = Field(default=10000, ge=1000, le=100000)
    STALE_THRESHOLD_SEC: float = Field(default=5.0, ge=1.0, le=60.0)
    PAGE_SIZE: int = Field(default=500, ge=100, le=1000)
    MIN_EDGE: float = Field(default=0.02, ge=0.0, le=1.0)
    MIN_VOLUME: float = Field(default=1000.0, ge=0.0)
    MAX_RETRIES: int = Field(default=3, ge=1, le=10)
    CIRCUIT_BREAKER_THRESHOLD: int = Field(default=5, ge=1, le=20)
    CIRCUIT_BREAKER_TIMEOUT: float = Field(default=60.0, ge=1.0, le=300.0)


class HFTExecutionConfig(BaseModel):
    AUTO_EXECUTE: bool = Field(default=True)
    AUTO_EXECUTE_MIN_CONFIDENCE: float = Field(default=0.7, ge=0.0, le=1.0)
    POSITION_SIZE_PCT: float = Field(default=0.25, ge=0.01, le=1.0)
    MAX_POSITION_USD: float = Field(default=1000.0, ge=10.0)
    MAX_TOTAL_EXPOSURE: float = Field(default=5000.0, ge=100.0)
    IDEMPOTENCY_TTL_SEC: int = Field(default=30, ge=5, le=300)


class HFTWhaleConfig(BaseModel):
    MIN_SIZE_USD: float = Field(default=10000.0, ge=1000.0)
    MIN_SCORE: float = Field(default=0.8, ge=0.0, le=1.0)
    FRONTRUN_DELAY_MS: int = Field(default=50, ge=10, le=500)
    SELL_DELAY_MS: int = Field(default=1000, ge=100, le=10000)
    MAX_RECONNECT_RETRIES: int = Field(default=5, ge=1, le=20)
    WS_RECONNECT_DELAY_BASE: float = Field(default=0.1, ge=0.01)


class HFTArbConfig(BaseModel):
    MIN_PROFIT: float = Field(default=0.02, ge=0.0)
    POLYMARKET_FEE: float = Field(default=0.01, ge=0.0, le=0.1)
    KALSHI_FEE: float = Field(default=0.01, ge=0.0, le=0.1)
    EXECUTION_MAX_RETRIES: int = Field(default=3, ge=1, le=10)
    PENDING_QUEUE_TTL_SEC: int = Field(default=300, ge=60, le=3600)


class HFTLatencyConfig(BaseModel):
    MAX_SCAN_LATENCY_MS: float = Field(default=1000.0, ge=100.0)
    MAX_EXECUTION_LATENCY_MS: float = Field(default=50.0, ge=10.0)
    LATENCY_ALERT_THRESHOLD_MS: float = Field(default=100.0, ge=10.0)
    CACHE_TTL_SEC: float = Field(default=1.0, ge=0.1, le=10.0)


class HFTConfig(BaseModel):
    scanner: HFTScannerConfig = Field(default_factory=HFTScannerConfig)
    execution: HFTExecutionConfig = Field(default_factory=HFTExecutionConfig)
    whale: HFTWhaleConfig = Field(default_factory=HFTWhaleConfig)
    arb: HFTArbConfig = Field(default_factory=HFTArbConfig)
    latency: HFTLatencyConfig = Field(default_factory=HFTLatencyConfig)

    def validate_flags(self) -> list[str]:
        """Validate flag combinations. Returns list of issues."""
        issues = []
        if self.execution.AUTO_EXECUTE and self.execution.AUTO_EXECUTE_MIN_CONFIDENCE < 0.3:
            issues.append("AUTO_EXECUTE_MIN_CONFIDENCE very low for auto-execute mode")
        if self.scanner.PARALLEL_LIMIT > 100 and self.scanner.STALE_THRESHOLD_SEC < 3.0:
            issues.append("High parallelism with low stale threshold may cause stale data")
        return issues


hft_settings = HFTConfig()
