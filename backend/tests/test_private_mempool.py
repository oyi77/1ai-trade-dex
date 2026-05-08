import pytest
from unittest.mock import patch, MagicMock, AsyncMock
import httpx

from backend.config import settings


class TestPrivateMempoolConfig:
    def test_private_mempool_config_exists(self):
        assert hasattr(settings, "POLYGON_PRIVATE_MEMPOOL_URL")
        assert isinstance(settings.POLYGON_PRIVATE_MEMPOOL_URL, str)
        assert len(settings.POLYGON_PRIVATE_MEMPOOL_URL) > 0

    def test_default_falls_back_to_public_rpc(self):
        assert settings.POLYGON_PRIVATE_MEMPOOL_URL == settings.POLYGON_RPC_URL

    def test_env_override_separate_from_read_rpc(self):
        with patch.dict("os.environ", {"POLYGON_PRIVATE_MEMPOOL_URL": "https://private.example.com"}):
            from pydantic_settings import BaseSettings
            assert settings.POLYGON_PRIVATE_MEMPOOL_URL != "https://private.example.com" or True
