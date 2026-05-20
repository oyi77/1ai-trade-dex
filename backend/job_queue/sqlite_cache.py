"""
SQLite-backed cache implementation using stdlib sqlite3.

Provides a simple key-value cache with TTL support, backed by a local SQLite
database. Thread-safe via a threading.Lock.

RQ-014: Redis cache with circuit-breaker fallback to SQLite
"""

import json
import sqlite3
import time
import threading
from typing import Optional, Any

from backend.job_queue.abstract import AbstractCache
from backend.config import settings


def _parse_sqlite_path(cache_url: str) -> str:
    """
    Parse a cache URL like 'sqlite:///./cache.db' to a file path.

    Strips the 'sqlite:///' prefix. Handles both relative and absolute paths.
    """
    if cache_url.startswith("sqlite:///"):
        return cache_url[len("sqlite:///") :]
    return cache_url


class SQLiteCache(AbstractCache):
    """
    SQLite-backed key-value cache using stdlib sqlite3.

    Schema: cache_kv (key TEXT PRIMARY KEY, value TEXT, expires_at REAL)

    Thread-safe via a threading.Lock. Values are JSON-serialized on write
    and JSON-deserialized on read. Expired entries are lazily pruned on get().
    """

    def __init__(self, db_path: Optional[str] = None):
        """
        Initialize the SQLite cache.

        Args:
            db_path: Path to the SQLite file. Defaults to parsed CACHE_URL from settings.
        """
        if db_path is None:
            db_path = _parse_sqlite_path(settings.CACHE_URL)
        self._db_path = db_path
        self._lock = threading.Lock()
        self._init_db()

    def _init_db(self) -> None:
        """Create the cache table if it doesn't exist."""
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            try:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS cache_kv (
                        key TEXT PRIMARY KEY,
                        value TEXT NOT NULL,
                        expires_at REAL
                    )
                    """
                )
                conn.commit()
            finally:
                conn.close()

    def get(self, key: str) -> Optional[Any]:
        """
        Retrieve a value from the cache.

        Returns None if the key doesn't exist or has expired.
        Expired entries are deleted on access.
        """
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            try:
                cursor = conn.execute(
                    "SELECT value, expires_at FROM cache_kv WHERE key = ?", (key,)
                )
                row = cursor.fetchone()
                if row is None:
                    return None

                value_str, expires_at = row
                now = time.time()
                if expires_at is not None and expires_at < now:
                    # Expired — delete and return None
                    conn.execute("DELETE FROM cache_kv WHERE key = ?", (key,))
                    conn.commit()
                    return None

                return json.loads(value_str)
            finally:
                conn.close()

    def set(self, key: str, value: Any, ttl_seconds: Optional[int] = None) -> None:
        """
        Store a value in the cache.

        Args:
            key: Cache key
            value: JSON-serializable value
            ttl_seconds: Time-to-live in seconds; None means no expiration

        Raises:
            ValueError: If value is not JSON-serializable
        """
        try:
            value_str = json.dumps(value)
        except (TypeError, ValueError) as e:
            raise ValueError(f"Value is not JSON-serializable: {e}") from e

        expires_at = (time.time() + ttl_seconds) if ttl_seconds is not None else None

        with self._lock:
            conn = sqlite3.connect(self._db_path)
            try:
                conn.execute(
                    """
                    INSERT INTO cache_kv (key, value, expires_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(key) DO UPDATE SET value=excluded.value, expires_at=excluded.expires_at
                    """,
                    (key, value_str, expires_at),
                )
                conn.commit()
            finally:
                conn.close()

    def delete(self, key: str) -> None:
        """Remove a key from the cache. No error if key doesn't exist."""
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            try:
                conn.execute("DELETE FROM cache_kv WHERE key = ?", (key,))
                conn.commit()
            finally:
                conn.close()

    def exists(self, key: str) -> bool:
        """
        Check if a key exists and hasn't expired.

        Returns True if key exists and is valid.
        """
        return self.get(key) is not None

    def flush(self) -> None:
        """Clear all cached data."""
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            try:
                conn.execute("DELETE FROM cache_kv")
                conn.commit()
            finally:
                conn.close()
