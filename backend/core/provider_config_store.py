"""ProviderConfigStore — flexible credential and config store for market providers.

Reads config values from the ``provider_credentials`` DB table first; falls
back to environment variables when no DB row exists.  Secrets (``is_secret=True``)
are stored Fernet-encrypted in the DB and decrypted transparently on read.

This eliminates per-provider ENV var sprawl: any number of providers can be
added at runtime through the admin UI or API without touching ``.env``.

**ENV var fallback convention** (used when no DB row exists):
    ``{PROVIDER_NAME_UPPER}_{CONFIG_KEY_UPPER}``
    e.g.  provider_name="azuro", config_key="graph_url" → ``AZURO_GRAPH_URL``

**Usage**::

    from backend.core.provider_config_store import provider_config

    value = provider_config.get("azuro", "graph_url",
                                 default="https://api.thegraph.com/...")
    provider_config.upsert(db, "azuro", "private_key", key_value, is_secret=True)
"""

from __future__ import annotations

import os
from typing import Optional

from loguru import logger
from sqlalchemy.orm import Session


def _env_key(provider_name: str, config_key: str) -> str:
    """Return the conventional ENV var name for a provider config key."""
    return f"{provider_name.upper()}_{config_key.upper()}"


def _get_fernet():
    """Return a Fernet instance from WALLET_FERNET_KEY env var, or None if absent."""
    raw = os.getenv("WALLET_FERNET_KEY", "")
    if not raw:
        return None
    try:
        from cryptography.fernet import Fernet

        return Fernet(raw.encode())
    except Exception as exc:
        logger.warning("ProviderConfigStore: invalid WALLET_FERNET_KEY — {}", exc)
        return None


class ProviderConfigStore:
    """DB-backed credential store with ENV var fallback.

    All reads are synchronous (SELECT by PK) so they are safe in both sync
    and async contexts.  Network I/O is never performed here.
    """

    def __init__(self) -> None:
        self._table_ready: bool = False  # flips True once the table is confirmed to exist

    def _ensure_table_ready(self, db: Optional["Session"] = None) -> bool:
        """Return True if the provider_credentials table is accessible.

        When a custom ``db`` session is provided, that session's engine is
        inspected directly (without caching) — useful for tests.
        When no ``db`` is provided, the global engine is checked and the result
        is cached in ``_table_ready`` to avoid repeated introspection.
        """
        from sqlalchemy import inspect as sa_inspect

        if db is not None:
            # Per-session check: don't pollute the singleton cache
            try:
                return sa_inspect(db.bind).has_table("provider_credentials")
            except Exception:
                return False

        if self._table_ready:
            return True
        try:
            from backend.models.database import engine

            self._table_ready = sa_inspect(engine).has_table("provider_credentials")
        except Exception:
            self._table_ready = False
        return self._table_ready

    def get(
        self,
        provider_name: str,
        config_key: str,
        default: str = "",
        db: Optional[Session] = None,
    ) -> str:
        """Return the config value for ``(provider_name, config_key)``.

        Priority: DB row → ENV var → ``default``.

        Args:
            provider_name: e.g. ``"azuro"``, ``"limitless"``, ``"sxbet"``
            config_key:    e.g. ``"graph_url"``, ``"private_key"``
            default:       value to return when neither DB nor ENV has the key
            db:            optional SQLAlchemy session; if None a temporary
                           session is opened from :data:`SessionLocal`
        """
        # --- 1. Try DB ---
        if self._ensure_table_ready(db):
            try:
                row = self._fetch_row(provider_name, config_key, db)
                if row is not None and row.config_value is not None:
                    return self._decrypt(row.config_value, row.is_secret)
            except Exception as exc:
                logger.debug(
                    "ProviderConfigStore.get DB read failed ({}/{}) — falling back to env: {}",
                    provider_name,
                    config_key,
                    exc,
                )

        # --- 2. Try ENV var ---
        env_val = os.getenv(_env_key(provider_name, config_key), "")
        if env_val:
            return env_val

        return default

    def get_all(
        self,
        provider_name: str,
        db: Optional[Session] = None,
    ) -> dict[str, str]:
        """Return all config keys for a provider as a plain dict.

        Secrets are decrypted transparently.  DB values shadow ENV vars of
        the same name.
        """
        result: dict[str, str] = {}

        # --- 1. ENV vars (lowest priority) ---
        prefix = f"{provider_name.upper()}_"
        for env_key_raw, env_value in os.environ.items():
            if env_key_raw.startswith(prefix):
                cfg_key = env_key_raw[len(prefix):].lower()
                result[cfg_key] = env_value

        # --- 2. DB rows (override ENV vars) ---
        if self._ensure_table_ready(db):
            try:
                rows = self._fetch_all_rows(provider_name, db)
                for row in rows:
                    if row.config_value is not None:
                        result[row.config_key] = self._decrypt(
                            row.config_value, row.is_secret
                        )
            except Exception as exc:
                logger.debug(
                    "ProviderConfigStore.get_all DB read failed ({}) — env only: {}",
                    provider_name,
                    exc,
                )

        return result

    def upsert(
        self,
        db: Session,
        provider_name: str,
        config_key: str,
        config_value: str,
        is_secret: bool = False,
        description: Optional[str] = None,
    ) -> None:
        """Insert or update a config value in the DB.

        Secrets are Fernet-encrypted before storage.
        """
        from backend.models.database import ProviderCredential

        encrypted_value = self._encrypt(config_value) if is_secret else config_value

        row = (
            db.query(ProviderCredential)
            .filter_by(provider_name=provider_name, config_key=config_key)
            .first()
        )
        if row:
            row.config_value = encrypted_value
            row.is_secret = is_secret
            if description is not None:
                row.description = description
        else:
            row = ProviderCredential(
                provider_name=provider_name,
                config_key=config_key,
                config_value=encrypted_value,
                is_secret=is_secret,
                description=description,
            )
            db.add(row)
        db.commit()

    def delete(
        self,
        db: Session,
        provider_name: str,
        config_key: Optional[str] = None,
    ) -> int:
        """Delete one key (if config_key given) or all keys for a provider.

        Returns the number of rows deleted.
        """
        from backend.models.database import ProviderCredential

        q = db.query(ProviderCredential).filter_by(provider_name=provider_name)
        if config_key is not None:
            q = q.filter_by(config_key=config_key)
        n = q.count()
        q.delete()
        db.commit()
        return n

    # ------------------------------------------------------------------ private

    def _fetch_row(
        self,
        provider_name: str,
        config_key: str,
        db: Optional[Session],
    ):
        from backend.models.database import ProviderCredential

        if db is not None:
            return (
                db.query(ProviderCredential)
                .filter_by(provider_name=provider_name, config_key=config_key)
                .first()
            )

        from backend.models.database import SessionLocal

        _db = SessionLocal()
        try:
            return (
                _db.query(ProviderCredential)
                .filter_by(provider_name=provider_name, config_key=config_key)
                .first()
            )
        finally:
            _db.close()

    def _fetch_all_rows(
        self,
        provider_name: str,
        db: Optional[Session],
    ):
        from backend.models.database import ProviderCredential

        if db is not None:
            return (
                db.query(ProviderCredential)
                .filter_by(provider_name=provider_name)
                .all()
            )

        from backend.models.database import SessionLocal

        _db = SessionLocal()
        try:
            return (
                _db.query(ProviderCredential)
                .filter_by(provider_name=provider_name)
                .all()
            )
        finally:
            _db.close()

    def _encrypt(self, value: str) -> str:
        f = _get_fernet()
        if f is None:
            raise ValueError(
                "WALLET_FERNET_KEY is not set; cannot store secret credentials. "
                "Generate a key with: python -c \"from cryptography.fernet import Fernet; "
                "print(Fernet.generate_key().decode())\""
            )
        return f.encrypt(value.encode()).decode()

    def _decrypt(self, value: str, is_secret: bool) -> str:
        if not is_secret:
            return value
        f = _get_fernet()
        if f is None:
            logger.error(
                "ProviderConfigStore: WALLET_FERNET_KEY is not set but a secret credential "
                "was requested — returning raw DB value (likely encrypted). "
                "Set WALLET_FERNET_KEY to enable decryption."
            )
            return value
        try:
            return f.decrypt(value.encode()).decode()
        except Exception as exc:
            logger.error(
                "ProviderConfigStore: decryption failed (bad WALLET_FERNET_KEY?) — {}", exc
            )
            return value


# Module-level singleton — providers import this directly.
provider_config = ProviderConfigStore()
