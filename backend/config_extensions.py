from typing import Optional
from pydantic_settings import BaseSettings
from backend.config import settings as base_settings


class ExtendedSettings(BaseSettings):
    AGGRESSIVE_MODE_ENABLED: bool = False
    KELLY_TYPE: str = "quarter"
    KELLY_MAX_CAP: float = 0.50
    MULTI_AGENT_DEBATE_ENABLED: bool = True
    DEBATE_TIMEOUT_SECONDS: float = 10.0
    BULL_AGENT_ENABLED: bool = True
    BEAR_AGENT_ENABLED: bool = True
    RESEARCH_AGENT_ENABLED: bool = True
    EXPERIENCE_BUFFER_ENABLED: bool = True
    EXPERIENCE_BUFFER_MAX_SIZE: int = -1
    RL_TRAINER_ENABLED: bool = True
    RL_TRAINER_INTERVAL_HOURS: int = 1
    PERPETUAL_BACKTESTER_ENABLED: bool = True
    PERPETUAL_BACKTESTER_INTERVAL_MINUTES: int = 30
    DAILY_LOSS_LIMIT_ENABLED: bool = True
    CIRCUIT_BREAKER_ENABLED: bool = True
    MAX_CONCURRENT_POSITIONS: int = 3
    CONSECUTIVE_LOSS_LIMIT: int = 3
    BTC_MOMENTUM_ENABLED: bool = True
    MARKET_MAKER_ENABLED: bool = True
    KALSHI_ARB_ENABLED: bool = True
    MIROFISH_ENABLED: bool = True
    MIROFISH_API_URL: str = "https://polyedge-mirofish-api.aitradepulse.com"
    MIROFISH_API_KEY: Optional[str] = None
    MIROFISH_API_TIMEOUT: float = 10.0
    POLYGON_RPC_URL: str = "https://polygon-bor-rpc.publicnode.com"
    PORT: int = 8100
    RELOAD_ON_CHANGE: bool = True


extended_settings = ExtendedSettings()

_PYDANTIC_INTERNAL = frozenset({
    "model_fields", "model_computed_fields", "model_config",
    "model_fields_set", "model_construct", "model_dump", "model_json_schema",
    "model_validate", "model_post_init",
})


class UnifiedSettings:
    def __init__(self):
        for attr in dir(base_settings):
            if attr.startswith('_') or attr in _PYDANTIC_INTERNAL:
                continue
            setattr(self, attr, getattr(base_settings, attr))
        for attr in dir(extended_settings):
            if attr.startswith('_') or attr in _PYDANTIC_INTERNAL:
                continue
            setattr(self, attr, getattr(extended_settings, attr))

    def __getattr__(self, name):
        if name.startswith('_') or name in _PYDANTIC_INTERNAL:
            raise AttributeError(name)
        extended_val = getattr(extended_settings, name, None)
        if extended_val is not None:
            return extended_val
        return getattr(base_settings, name)


settings = UnifiedSettings()
