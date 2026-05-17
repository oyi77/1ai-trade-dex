"""Tests for ProviderConfigStore — DB-backed credential store with ENV fallback."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.models.database import Base, ProviderCredential
from backend.core.provider_config_store import ProviderConfigStore


# ────────────────────────────────────── Fixtures ─────────────────────────────


@pytest.fixture()
def store() -> ProviderConfigStore:
    """Fresh ProviderConfigStore instance per test."""
    return ProviderConfigStore()


@pytest.fixture()
def in_memory_db():
    """In-memory SQLite DB with the provider_credentials table."""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    yield db
    db.close()


@pytest.fixture()
def empty_db():
    """In-memory SQLite DB WITHOUT provider_credentials table — simulates pre-migration."""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    # Do NOT create tables — simulates state before alembic migration runs
    Session = sessionmaker(bind=engine)
    db = Session()
    yield db
    db.close()


# ─────────────────────────────────────── Tests ───────────────────────────────


class TestProviderConfigStoreEnvFallback:
    """Test ENV var fallback when the provider_credentials table is not present."""

    def test_falls_back_to_env_when_table_missing(self, store, empty_db, monkeypatch):
        """When the DB table doesn't exist, the store should use ENV vars."""
        monkeypatch.setenv("TESTPROVIDER_SOME_KEY", "env_value")
        # Pass the empty DB session; _ensure_table_ready will detect no table
        result = store.get("testprovider", "some_key", "default", db=empty_db)
        assert result == "env_value"

    def test_returns_default_when_no_env_and_no_db(self, store, empty_db, monkeypatch):
        monkeypatch.delenv("TESTPROVIDER_MISSING_KEY", raising=False)
        result = store.get("testprovider", "missing_key", "my_default", db=empty_db)
        assert result == "my_default"

    def test_env_key_convention(self, store, empty_db, monkeypatch):
        """ENV var key is PROVIDER_UPPER_KEY_UPPER."""
        monkeypatch.setenv("SXBET_API_URL", "https://custom.sx.bet")
        result = store.get("sxbet", "api_url", "", db=empty_db)
        assert result == "https://custom.sx.bet"


class TestProviderConfigStoreDB:
    """Test DB read/write operations."""

    def test_upsert_and_get(self, store, in_memory_db):
        store.upsert(in_memory_db, "limitless", "api_url", "https://api.limitless.exchange")
        result = store.get("limitless", "api_url", "", db=in_memory_db)
        assert result == "https://api.limitless.exchange"

    def test_upsert_updates_existing(self, store, in_memory_db):
        store.upsert(in_memory_db, "sxbet", "api_url", "https://original.sx.bet")
        store.upsert(in_memory_db, "sxbet", "api_url", "https://updated.sx.bet")
        result = store.get("sxbet", "api_url", "", db=in_memory_db)
        assert result == "https://updated.sx.bet"

    def test_get_all_returns_all_keys(self, store, in_memory_db):
        store.upsert(in_memory_db, "azuro", "graph_url", "https://subgraph.example.com")
        store.upsert(in_memory_db, "azuro", "chain_id", "100")
        result = store.get_all("azuro", db=in_memory_db)
        assert result["graph_url"] == "https://subgraph.example.com"
        assert result["chain_id"] == "100"

    def test_db_wins_over_env(self, store, in_memory_db, monkeypatch):
        """DB value overrides ENV var of the same logical key."""
        monkeypatch.setenv("AZURO_GRAPH_URL", "https://env.example.com")
        store.upsert(in_memory_db, "azuro", "graph_url", "https://db.example.com")
        result = store.get("azuro", "graph_url", "", db=in_memory_db)
        assert result == "https://db.example.com"

    def test_delete_single_key(self, store, in_memory_db):
        store.upsert(in_memory_db, "limitless", "api_url", "https://api.limitless.exchange")
        store.upsert(in_memory_db, "limitless", "wallet_address", "0xABC")
        n = store.delete(in_memory_db, "limitless", "wallet_address")
        assert n == 1
        remaining = store.get("limitless", "wallet_address", "", db=in_memory_db)
        assert remaining == ""

    def test_delete_all_for_provider(self, store, in_memory_db):
        store.upsert(in_memory_db, "sxbet", "api_url", "https://api.sx.bet")
        store.upsert(in_memory_db, "sxbet", "wallet_address", "0xDEF")
        n = store.delete(in_memory_db, "sxbet")
        assert n == 2
        rows = in_memory_db.query(ProviderCredential).filter_by(provider_name="sxbet").all()
        assert rows == []

    def test_secret_stored_encrypted(self, store, in_memory_db, monkeypatch):
        """Secrets are encrypted at rest and decrypted transparently on read."""
        from cryptography.fernet import Fernet

        key = Fernet.generate_key().decode()
        monkeypatch.setenv("WALLET_FERNET_KEY", key)

        store.upsert(in_memory_db, "sxbet", "private_key", "0xSECRET123", is_secret=True)

        # Confirm raw DB value is encrypted (not the original secret)
        raw_row = (
            in_memory_db.query(ProviderCredential)
            .filter_by(provider_name="sxbet", config_key="private_key")
            .first()
        )
        assert raw_row is not None
        assert raw_row.config_value != "0xSECRET123"

        # Confirm decrypted read returns original value
        decrypted = store.get("sxbet", "private_key", "", db=in_memory_db)
        assert decrypted == "0xSECRET123"

    def test_upsert_secret_raises_without_fernet_key(self, store, in_memory_db, monkeypatch):
        """Trying to store a secret without WALLET_FERNET_KEY must raise ValueError."""
        monkeypatch.delenv("WALLET_FERNET_KEY", raising=False)
        with pytest.raises(ValueError, match="WALLET_FERNET_KEY"):
            store.upsert(in_memory_db, "sxbet", "private_key", "0xSECRET", is_secret=True)


class TestProviderInstantiation:
    """Smoke tests — providers instantiate without errors and use config store."""

    def test_predict_fun_provider(self):
        from backend.data.providers.azuro import PredictFunProvider

        p = PredictFunProvider()
        assert p.platform_name == "predict_fun"

    def test_bookmaker_xyz_provider(self):
        from backend.data.providers.azuro import BookmakerXyzProvider

        p = BookmakerXyzProvider()
        assert p.platform_name == "bookmaker_xyz"

    def test_limitless_provider(self):
        from backend.data.providers.limitless import LimitlessProvider

        p = LimitlessProvider()
        assert p.platform_name == "limitless"

    def test_sxbet_provider(self):
        from backend.data.providers.sxbet import SXBetProvider

        p = SXBetProvider()
        assert p.platform_name == "sxbet"

    def test_place_order_respects_explicit_empty_private_key(self):
        """Explicitly passing private_key='' should force dry-run, not fall through to DB."""
        import asyncio
        from backend.data.providers.sxbet import SXBetProvider

        p = SXBetProvider()
        result = asyncio.run(
            p.place_order("0xMARKET", "BUY", 10.0, 0.5, private_key="")
        )
        assert result["status"] == "dry_run"
