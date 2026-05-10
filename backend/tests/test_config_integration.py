"""Integration tests for centralized configuration system.

Validates that environment variables flow through settings correctly,
extended settings are accessible, and the config priority
(Database -> Env -> Defaults) is respected.
"""

import os
import pytest
from unittest.mock import patch

from backend.config import Settings
from backend.config_extensions import ExtendedSettings, UnifiedSettings


class TestSettingsPriority:
    def test_default_values(self):
        settings = Settings(
            DATABASE_URL="sqlite:///./test.db",
            INITIAL_BANKROLL=100.0,
            KELLY_FRACTION=0.05,
            MIN_EDGE_THRESHOLD=0.05,
        )
        assert settings.INITIAL_BANKROLL == 100.0
        assert settings.KELLY_FRACTION == 0.05
        assert settings.MIN_EDGE_THRESHOLD == 0.05
        assert settings.TRADING_MODE == "paper"
        assert settings.AI_PROVIDER == "groq"

    def test_env_overrides_defaults(self):
        with patch.dict(os.environ, {
            "INITIAL_BANKROLL": "500.0",
            "MIN_EDGE_THRESHOLD": "0.15",
            "AI_PROVIDER": "claude",
        }):
            settings = Settings()
            assert settings.INITIAL_BANKROLL == 500.0
            assert settings.MIN_EDGE_THRESHOLD == 0.15
            assert settings.AI_PROVIDER == "claude"

    def test_active_modes_parsing(self):
        with patch.dict(os.environ, {"ACTIVE_MODES": "paper,testnet", "POLYMARKET_PRIVATE_KEY": "0x1234567890123456789012345678901234567890123456789012345678901234"}):
            settings = Settings()
            assert settings.active_modes_set == {"paper", "testnet"}
            assert settings.is_mode_active("paper")
            assert settings.is_mode_active("testnet")
            assert not settings.is_mode_active("live")

    def test_active_modes_defaults_to_paper(self):
        with patch.dict(os.environ, {"ACTIVE_MODES": "invalid_mode"}):
            settings = Settings()
            assert settings.active_modes_set == {"paper"}

    def test_simulation_mode(self):
        with patch.dict(os.environ, {"ACTIVE_MODES": "paper"}):
            settings = Settings()
            assert settings.SIMULATION_MODE is True

        with patch.dict(os.environ, {"ACTIVE_MODES": "live", "POLYMARKET_PRIVATE_KEY": "0x1234567890123456789012345678901234567890123456789012345678901234"}):
            settings = Settings()
            assert settings.SIMULATION_MODE is False

    def test_trading_mode_property(self):
        with patch.dict(os.environ, {"ACTIVE_MODES": "testnet,paper", "POLYMARKET_PRIVATE_KEY": "0x1234567890123456789012345678901234567890123456789012345678901234"}):
            settings = Settings()
            assert settings.TRADING_MODE == "testnet"

        with patch.dict(os.environ, {"ACTIVE_MODES": "paper"}):
            settings = Settings()
            assert settings.TRADING_MODE == "paper"


class TestExtendedSettings:
    def test_extended_defaults(self):
        settings = ExtendedSettings()
        assert settings.POLYGON_RPC_URL is not None
        assert settings.MIROFISH_API_TIMEOUT == 10.0
        assert settings.MIROFISH_ENABLED is True

    def test_extended_env_override(self):
        with patch.dict(os.environ, {
            "MIROFISH_API_URL": "https://custom-api.example.com",
            "POLYGON_RPC_URL": "https://custom-rpc.example.com",
        }):
            settings = ExtendedSettings()
            assert settings.MIROFISH_API_URL == "https://custom-api.example.com"
            assert settings.POLYGON_RPC_URL == "https://custom-rpc.example.com"

    def test_extended_inherits_base_settings(self):
        settings = UnifiedSettings()
        assert hasattr(settings, 'INITIAL_BANKROLL')
        assert hasattr(settings, 'MIROFISH_API_URL')
        assert hasattr(settings, 'MIROFISH_ENABLED')


class TestRiskSettings:
    def test_risk_env_overrides(self):
        with patch.dict(os.environ, {
            "DAILY_LOSS_LIMIT": "10.0",
            "MAX_TRADE_SIZE": "20.0",
            "DAILY_DRAWDOWN_LIMIT_PCT": "0.15",
        }):
            settings = Settings()
            assert settings.DAILY_LOSS_LIMIT == 10.0
            assert settings.MAX_TRADE_SIZE == 20.0
            assert settings.DAILY_DRAWDOWN_LIMIT_PCT == 0.15


class TestDatabaseSettings:
    def test_default_database_url(self):
        settings = Settings()
        assert "sqlite" in settings.DATABASE_URL

    def test_custom_database_url(self):
        with patch.dict(os.environ, {"DATABASE_URL": "postgresql://user:pass@localhost/mydb"}):
            settings = Settings()
            assert settings.DATABASE_URL == "postgresql://user:pass@localhost/mydb"

    def test_job_queue_defaults(self):
        settings = Settings()
        assert settings.JOB_WORKER_ENABLED is True
        assert "sqlite" in settings.JOB_QUEUE_URL
        assert settings.JOB_TIMEOUT_SECONDS == 300


class TestFeatureFlags:
    def test_default_feature_flags(self):
        settings = Settings()
        assert settings.WHALE_LISTENER_ENABLED is False
        assert settings.NEWS_FEED_ENABLED is False
        assert settings.ARBITRAGE_DETECTOR_ENABLED is False

    def test_feature_flag_overrides(self):
        with patch.dict(os.environ, {
            "WHALE_LISTENER_ENABLED": "true",
            "ARBITRAGE_DETECTOR_ENABLED": "true",
        }):
            settings = Settings()
            assert settings.WHALE_LISTENER_ENABLED is True
            assert settings.ARBITRAGE_DETECTOR_ENABLED is True
            assert settings.NEWS_FEED_ENABLED is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
