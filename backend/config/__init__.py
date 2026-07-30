"""Configuration settings for the BTC 5-min trading bot."""

import os
from dataclasses import dataclass

from loguru import logger

try:
    from dotenv import load_dotenv

    load_dotenv(override=True)
except ImportError:
    logger.debug("python-dotenv not installed — using raw env vars")

# Re-export path constants
from .paths import ROOT_DIR, DB_PATH  # noqa: F401

# Mixin imports — each provides a category of configuration fields
from .mixins.api_urls import APIUrlsMixin
from .mixins.strategy import StrategyParamsMixin
from .mixins.risk import RiskMixin
from .mixins.agi import AGIMixin


@dataclass
class ConfigRegistry(APIUrlsMixin, StrategyParamsMixin, RiskMixin, AGIMixin):
    """
    Centralized configuration registry with categorized access.

    This is the single source of truth for all configuration in PolyEdge.
    All settings are organized by domain (API_ENDPOINTS, RATE_LIMITS, etc.)
    and validated at startup to fail fast with clear error messages.

    Settings are read from environment variables (via .env file), falling
    back to the hardcoded class defaults when not set.
    """

    def __init__(self):
        import dataclasses
        from dataclasses import Field, MISSING

        all_fields = {}
        for f in dataclasses.fields(self):
            if f.default is not MISSING:
                all_fields[f.name] = f.default
            elif f.default_factory is not MISSING:
                all_fields[f.name] = f.default_factory()
            else:
                all_fields[f.name] = (
                    f.type()
                    if f.type in (dict, list, set, str, int, float, bool)
                    else None
                )

        for name, value in self.__class__.__dict__.items():
            if (
                name.startswith("_")
                or callable(value)
                or isinstance(value, (staticmethod, classmethod, property, Field))
            ):
                continue
            if name not in all_fields:
                all_fields[name] = value

        for name, default in all_fields.items():
            env_val = os.environ.get(name)
            if env_val is not None:
                if isinstance(default, bool):
                    setattr(self, name, env_val.lower() in ("true", "1", "yes"))
                elif isinstance(default, int):
                    setattr(self, name, int(env_val))
                elif isinstance(default, float):
                    setattr(self, name, float(env_val))
                elif isinstance(default, (dict, list)):
                    try:
                        import ast

                        setattr(self, name, ast.literal_eval(env_val))
                    except Exception:
                        setattr(self, name, default)
                else:
                    setattr(self, name, env_val)
            else:
                setattr(self, name, default)

    # ------------------------------------------------------------------
    # Derived Properties
    # ------------------------------------------------------------------

    @property
    def active_modes_set(self) -> set[str]:
        valid = {"paper", "testnet", "live"}
        modes = {m.strip() for m in self.ACTIVE_MODES.split(",") if m.strip()}
        return modes & valid or {"paper"}

    def is_mode_active(self, mode: str) -> bool:
        return mode in self.active_modes_set

    @property
    def TRADING_MODE(self) -> str:
        override = getattr(self, "_trading_mode_override", None)
        if override:
            return override
        env_val = os.environ.get("TRADING_MODE")
        if env_val:
            return env_val
        modes = self.active_modes_set
        if "live" in modes:
            return "live"
        if "testnet" in modes:
            return "testnet"
        return "paper"

    @TRADING_MODE.setter
    def TRADING_MODE(self, value: str) -> None:
        self._trading_mode_override = value

    @TRADING_MODE.deleter
    def TRADING_MODE(self) -> None:
        if hasattr(self, "_trading_mode_override"):
            del self._trading_mode_override

    @property
    def SIMULATION_MODE(self) -> bool:
        override = getattr(self, "_simulation_mode_override", None)
        if override is not None:
            return override
        return "live" not in self.active_modes_set

    @SIMULATION_MODE.setter
    def SIMULATION_MODE(self, value: bool) -> None:
        self._simulation_mode_override = value

    @SIMULATION_MODE.deleter
    def SIMULATION_MODE(self) -> None:
        if hasattr(self, "_simulation_mode_override"):
            del self._simulation_mode_override

    # ------------------------------------------------------------------
    # Database helpers
    # ------------------------------------------------------------------

    @property
    def is_postgres(self) -> bool:
        return "postgresql" in self.DATABASE_URL

    @property
    def is_sqlite(self) -> bool:
        return "sqlite" in self.DATABASE_URL

    def validate_database_url(self) -> list[str]:
        issues = []

        if not self.DATABASE_URL:
            issues.append("DATABASE_URL is required")
            return issues

        if (
            self.DATABASE_URL.startswith("mysql://")
            and "+pymysql" not in self.DATABASE_URL
        ):
            logger.warning(
                "MySQL DATABASE_URL detected without '+pymysql'. "
                "Consider using 'mysql+pymysql://' for better compatibility."
            )

        valid_schemes = ("sqlite://", "postgresql://", "mysql+pymysql://", "mysql://")
        if not any(self.DATABASE_URL.startswith(s) for s in valid_schemes):
            issues.append(f"Invalid DATABASE_URL scheme, got: {self.DATABASE_URL}")

        return issues

    # ------------------------------------------------------------------
    # VALIDATION - Validation methods
    # ------------------------------------------------------------------

    def validate(self) -> list[str]:
        """
        Validate all configuration values.

        Returns:
            List of validation issues (empty if valid)
        """
        issues: list[str] = []

        if not self.DATABASE_URL:
            issues.append("DATABASE_URL is required")

        if not self.GAMMA_API_URL:
            issues.append("GAMMA_API_URL is required")

        api_urls = [
            self.GAMMA_API_URL,
            self.DATA_API_URL,
            self.CLOB_API_URL,
            self.KALSHI_API_URL,
            self.BINANCE_API_URL,
            self.COINBASE_API_URL,
            self.TAVILY_API_URL,
            self.MIROFISH_API_URL,
        ]

        for url in api_urls:
            if url and not url.startswith(("http://", "https://", "wss://", "ws://")):
                issues.append(f"Invalid URL format: {url}")

        if self.RATE_LIMIT_GAMMA <= 0:
            issues.append("RATE_LIMIT_GAMMA must be positive")
        if self.RATE_LIMIT_KALSHI <= 0:
            issues.append("RATE_LIMIT_KALSHI must be positive")
        if self.RATE_LIMIT_CRYPTO <= 0:
            issues.append("RATE_LIMIT_CRYPTO must be positive")

        if self.RATE_LIMIT_BACKOFF_BASE < 1.0:
            issues.append("RATE_LIMIT_BACKOFF_BASE must be >= 1.0")
        if self.RATE_LIMIT_MAX_DELAY < self.RATE_LIMIT_BACKOFF_BASE:
            issues.append("RATE_LIMIT_MAX_DELAY must be >= RATE_LIMIT_BACKOFF_BASE")

        if self.PORT < 1 or self.PORT > 65535:
            issues.append(f"PORT must be between 1 and 65535, got {self.PORT}")

        risky_floats = [
            ("KELLY_FRACTION", self.KELLY_FRACTION, 0.0, 0.5),
            ("MAX_POSITION_FRACTION", self.MAX_POSITION_FRACTION, 0.0, 1.0),
            ("MAX_TOTAL_EXPOSURE_FRACTION", self.MAX_TOTAL_EXPOSURE_FRACTION, 0.0, 1.0),
            ("SLIPPAGE_TOLERANCE", self.SLIPPAGE_TOLERANCE, 0.0, 0.1),
            ("DAILY_DRAWDOWN_LIMIT_PCT", self.DAILY_DRAWDOWN_LIMIT_PCT, 0.0, 0.5),
            ("WEEKLY_DRAWDOWN_LIMIT_PCT", self.WEEKLY_DRAWDOWN_LIMIT_PCT, 0.0, 0.5),
            ("DAILY_LOSS_FLOOR_PCT", self.DAILY_LOSS_FLOOR_PCT, -0.5, 0.0),
            ("WEEKLY_LOSS_FLOOR_PCT", self.WEEKLY_LOSS_FLOOR_PCT, -0.5, 0.0),
            ("AI_SIGNAL_WEIGHT", self.AI_SIGNAL_WEIGHT, 0.0, 0.5),
            ("HFT_POSITION_SIZE_PCT", self.HFT_POSITION_SIZE_PCT, 0.01, 1.0),
            (
                "WEATHER_MAX_BANKROLL_FRACTION",
                self.WEATHER_MAX_BANKROLL_FRACTION,
                0.0,
                1.0,
            ),
            ("HFT_ARB_MIN_PROFIT", self.HFT_ARB_MIN_PROFIT, 0.0, 1.0),
            ("HFT_WHALE_MIN_SCORE", self.HFT_WHALE_MIN_SCORE, 0.0, 1.0),
            (
                "HFT_EXECUTION_AUTO_EXECUTE_MIN_CONFIDENCE",
                self.HFT_EXECUTION_AUTO_EXECUTE_MIN_CONFIDENCE,
                0.0,
                1.0,
            ),
        ]

        for name, value, min_val, max_val in risky_floats:
            if not (min_val <= value <= max_val):
                issues.append(
                    f"{name} must be between {min_val} and {max_val}, got {value}"
                )

        risky_ints = [
            ("HFT_MAX_POSITION_USD", self.HFT_MAX_POSITION_USD, 100, 100000),
            ("MAX_TRADES_PER_WINDOW", self.MAX_TRADES_PER_WINDOW, 1, 1000),
            ("MAX_TRADES_PER_SCAN", self.MAX_TRADES_PER_SCAN, 1, 1000),
            ("AUTO_TRADER_BATCH_SIZE", self.AUTO_TRADER_BATCH_SIZE, 1, 1000),
            ("MAX_TOTAL_PENDING_TRADES", self.MAX_TOTAL_PENDING_TRADES, 1, 1000),
            ("STALE_TRADE_HOURS", self.STALE_TRADE_HOURS, 1, 720),
            ("SCANNER_PAGE_SIZE", self.SCANNER_PAGE_SIZE, 100, 1000),
            ("SCANNER_SEMAPHORE_LIMIT", self.SCANNER_SEMAPHORE_LIMIT, 10, 100),
            ("SCANNER_MAX_MARKETS", self.SCANNER_MAX_MARKETS, 1000, 100000),
            ("MIN_TIME_REMAINING", self.MIN_TIME_REMAINING, 1, 3600),
            ("MAX_TIME_REMAINING", self.MAX_TIME_REMAINING, 60, 7200),
        ]

        for name, value, min_val, max_val in risky_ints:
            if not (min_val <= value <= max_val):
                issues.append(
                    f"{name} must be between {min_val} and {max_val}, got {value}"
                )

        if self.SCAN_INTERVAL_SECONDS < 5:
            issues.append(
                f"SCAN_INTERVAL_SECONDS too aggressive: {self.SCAN_INTERVAL_SECONDS}s (min: 5s)"
            )
        if self.SETTLEMENT_INTERVAL_SECONDS < 30:
            issues.append(
                f"SETTLEMENT_INTERVAL_SECONDS too aggressive: {self.SETTLEMENT_INTERVAL_SECONDS}s (min: 30s)"
            )

        if not self.WALLET_FERNET_KEY:
            issues.append(
                "WALLET_FERNET_KEY is empty — wallet encryption disabled: private keys stored in plaintext. This is safe for dev/paper-only but NOT for live production trading."
            )

        if self.HFT_SCANNER_CIRCUIT_BREAKER_THRESHOLD < 1:
            issues.append("HFT_SCANNER_CIRCUIT_BREAKER_THRESHOLD must be >= 1")
        if self.HFT_SCANNER_CIRCUIT_BREAKER_TIMEOUT < 1:
            issues.append("HFT_SCANNER_CIRCUIT_BREAKER_TIMEOUT must be >= 1s")

        if self.REGISTRY_MIN_WIN_RATE < 0 or self.REGISTRY_MIN_WIN_RATE > 1:
            issues.append(
                f"REGISTRY_MIN_WIN_RATE must be 0-1, got {self.REGISTRY_MIN_WIN_RATE}"
            )
        if self.REGISTRY_MIN_ROI < -1:
            issues.append(
                f"REGISTRY_MIN_ROI must be >= -1, got {self.REGISTRY_MIN_ROI}"
            )

        positive_ints = [
            ("SCAN_INTERVAL_SECONDS", self.SCAN_INTERVAL_SECONDS),
            ("SETTLEMENT_INTERVAL_SECONDS", self.SETTLEMENT_INTERVAL_SECONDS),
            ("AGI_PROMOTION_INTERVAL_HOURS", self.AGI_PROMOTION_INTERVAL_HOURS),
            (
                "AGI_HEALTH_CHECK_INTERVAL_MINUTES",
                self.AGI_HEALTH_CHECK_INTERVAL_MINUTES,
            ),
            ("JOB_TIMEOUT_SECONDS", self.JOB_TIMEOUT_SECONDS),
            ("MAX_CONCURRENT_JOBS", self.MAX_CONCURRENT_JOBS),
            ("DB_EXECUTOR_MAX_WORKERS", self.DB_EXECUTOR_MAX_WORKERS),
            (
                "AGI_CALIBRATION_CHECK_INTERVAL_HOURS",
                self.AGI_CALIBRATION_CHECK_INTERVAL_HOURS,
            ),
            ("AUTO_IMPROVE_INTERVAL_DAYS", self.AUTO_IMPROVE_INTERVAL_DAYS),
            ("SELF_REVIEW_INTERVAL_DAYS", self.SELF_REVIEW_INTERVAL_DAYS),
            ("RESEARCH_PIPELINE_INTERVAL_HOURS", self.RESEARCH_PIPELINE_INTERVAL_HOURS),
            (
                "AGI_IMPROVEMENT_CYCLE_INTERVAL_HOURS",
                self.AGI_IMPROVEMENT_CYCLE_INTERVAL_HOURS,
            ),
            (
                "HISTORICAL_DATA_COLLECTOR_INTERVAL_HOURS",
                self.HISTORICAL_DATA_COLLECTOR_INTERVAL_HOURS,
            ),
            ("ARBITRAGE_SCAN_INTERVAL_SECONDS", self.ARBITRAGE_SCAN_INTERVAL_SECONDS),
            ("NEWS_FEED_INTERVAL_SECONDS", self.NEWS_FEED_INTERVAL_SECONDS),
            ("AGI_MUTATION_INTERVAL_HOURS", self.AGI_MUTATION_INTERVAL_HOURS),
            ("AGI_CROSSOVER_INTERVAL_HOURS", self.AGI_CROSSOVER_INTERVAL_HOURS),
            ("MUTATION_CYCLE_INTERVAL_HOURS", self.MUTATION_CYCLE_INTERVAL_HOURS),
            ("CROSSOVER_CYCLE_INTERVAL_HOURS", self.CROSSOVER_CYCLE_INTERVAL_HOURS),
            ("NECROMANCY_INTERVAL_DAYS", self.NECROMANCY_INTERVAL_DAYS),
            ("AGI_REHAB_COOLDOWN_DAYS", self.AGI_REHAB_COOLDOWN_DAYS),
            ("AGI_REHAB_MIN_TRADES", self.AGI_REHAB_MIN_TRADES),
            ("AGI_PROMOTER_SHADOW_MIN_TRADES", self.AGI_PROMOTER_SHADOW_MIN_TRADES),
            ("AGI_PROMOTER_SHADOW_MIN_DAYS", self.AGI_PROMOTER_SHADOW_MIN_DAYS),
            ("AGI_PROMOTER_PAPER_MIN_TRADES", self.AGI_PROMOTER_PAPER_MIN_TRADES),
            ("AGI_PROMOTER_PAPER_MIN_DAYS", self.AGI_PROMOTER_PAPER_MIN_DAYS),
            ("AGI_FRONTTEST_DAYS", self.AGI_FRONTTEST_DAYS),
            ("AGI_FRONTTEST_MIN_TRADES", self.AGI_FRONTTEST_MIN_TRADES),
            ("AGI_MAX_IMPROVEMENT_ATTEMPTS", self.AGI_MAX_IMPROVEMENT_ATTEMPTS),
            ("AGI_DEMOTION_RETRY_LIMIT", self.AGI_DEMOTION_RETRY_LIMIT),
            ("AGI_LIVE_TRIAL_DAYS", self.AGI_LIVE_TRIAL_DAYS),
            ("AGI_LIVE_TRIAL_MIN_TRADES", self.AGI_LIVE_TRIAL_MIN_TRADES),
            ("AGI_REHAB_LITE_COOLDOWN_HOURS", self.AGI_REHAB_LITE_COOLDOWN_HOURS),
            ("AGI_REHAB_LITE_RE_DISABLE_HOURS", self.AGI_REHAB_LITE_RE_DISABLE_HOURS),
            ("AGI_AUTO_DISABLE_MIN_TRADES", self.AGI_AUTO_DISABLE_MIN_TRADES),
            ("AGI_AUTO_DISABLE_MIN_TRADES_LIFETIME", self.AGI_AUTO_DISABLE_MIN_TRADES_LIFETIME),
            ("CACHE_TTL_SECONDS", self.CACHE_TTL_SECONDS),
            ("DB_BACKUP_INTERVAL_HOURS", self.DB_BACKUP_INTERVAL_HOURS),
            ("DB_BACKUP_RETENTION_DAYS", self.DB_BACKUP_RETENTION_DAYS),
            (
                "HISTORICAL_DATA_COLLECTOR_INTERVAL_HOURS",
                self.HISTORICAL_DATA_COLLECTOR_INTERVAL_HOURS,
            ),
            ("AGI_HEALTH_ORPHAN_MAX_AGE_DAYS", self.AGI_HEALTH_ORPHAN_MAX_AGE_DAYS),
            ("MAX_TOPUPS", self.MAX_TOPUPS),
            ("DEBATE_CYCLE_TIMEOUT", self.DEBATE_CYCLE_TIMEOUT),
            ("ACTIVITY_DB_TRANSACTION_TIMEOUT", self.ACTIVITY_DB_TRANSACTION_TIMEOUT),
            ("WEBSOCKET_ACTIVITY_LATENCY_SLA", self.WEBSOCKET_ACTIVITY_LATENCY_SLA),
            ("PAPER_MIN_ORDER_USDC", self.PAPER_MIN_ORDER_USDC),
            ("MIN_ORDER_USDC", self.MIN_ORDER_USDC),
            ("SCANNER_MIN_EDGE", int(self.SCANNER_MIN_EDGE * 100)),
            (
                "SCANNER_STALE_THRESHOLD_SECONDS",
                int(self.SCANNER_STALE_THRESHOLD_SECONDS * 10),
            ),
            ("SCANNER_MAX_MARKETS", self.SCANNER_MAX_MARKETS),
        ]

        for name, value in positive_ints:
            if value < 1:
                issues.append(f"{name} must be >= 1, got {value}")

        positive_floats = [
            ("RATE_LIMIT_BACKOFF_BASE", self.RATE_LIMIT_BACKOFF_BASE),
            ("RATE_LIMIT_MAX_DELAY", self.RATE_LIMIT_MAX_DELAY),
            ("DEBATE_TIMEOUT_SECONDS", self.DEBATE_TIMEOUT_SECONDS),
            ("MIROFISH_API_TIMEOUT", self.MIROFISH_API_TIMEOUT),
            ("MIN_DEBATE_EDGE", self.MIN_DEBATE_EDGE),
            ("MIN_EDGE_THRESHOLD", self.MIN_EDGE_THRESHOLD),
            ("MAX_ENTRY_PRICE", self.MAX_ENTRY_PRICE),
            ("KELLY_FRACTION", self.KELLY_FRACTION),
            ("DAILY_LOSS_LIMIT", self.DAILY_LOSS_LIMIT),
            ("MAX_TRADE_SIZE", self.MAX_TRADE_SIZE),
            ("INITIAL_BANKROLL", self.INITIAL_BANKROLL),
        ]

        for name, value in positive_floats:
            if value < 0:
                issues.append(f"{name} must be >= 0, got {value}")

        return issues


# Global settings instance - provides access to all config via dataclass
settings = ConfigRegistry()


def _cfg(name: str, default=None):
    """Safe settings lookup — returns default for MagicMock in tests."""
    return getattr(settings, name, default)


# Startup validation - fail fast if config is invalid
from .validation import validate_startup  # noqa: E402

validate_startup()

# Log missing optional API keys
for _key in ["ANTHROPIC_API_KEY", "EXA_API_KEY", "SERPER_API_KEY"]:
    if not getattr(settings, _key, None):
        logger.debug(f"[Config] {_key} not set — fallback provider disabled")


if __name__ == "__main__":
    issues = settings.validate()
    if issues:
        print("Configuration validation errors:")
        for issue in issues:
            print(f"  - {issue}")
        raise ValueError(f"Configuration validation failed: {issues[:3]}")

    print("PolyEdge Configuration Loaded Successfully")
    print(f"  Trading mode: {settings.TRADING_MODE}")
    print(f"  Bankroll: ${settings.INITIAL_BANKROLL:.2f}")
    print(
        f"  API endpoints configured: {len([k for k in dir(settings) if k.endswith('_URL') and not k.startswith('_')])}"
    )
    print(f"  Jobs enabled: {settings.JOB_WORKER_ENABLED}")
    print(f"  AGI autonomy: {settings.AGI_AUTO_PROMOTE}")
