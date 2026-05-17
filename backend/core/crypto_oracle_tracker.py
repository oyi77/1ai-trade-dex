"""Per-asset performance tracker for crypto oracle strategy.

Tracks trades in a dedicated SQLite table and provides rolling stats
per asset, per hour-of-day, per price bucket, and edge-decay detection.
"""
from __future__ import annotations

import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional


_DB_PATH = Path("data/crypto_oracle_performance.db")
_LOCK = threading.Lock()

_CREATE_SQL = """
CREATE TABLE IF NOT EXISTS crypto_oracle_performance (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    asset       TEXT    NOT NULL,
    direction   TEXT    NOT NULL,
    entry_price REAL    NOT NULL,
    market_mid  REAL    NOT NULL,
    window_time TEXT    NOT NULL,
    result      TEXT    NOT NULL,
    pnl         REAL    NOT NULL DEFAULT 0.0,
    recorded_at TEXT    NOT NULL
)
"""

_INSERT_SQL = """
INSERT INTO crypto_oracle_performance
    (asset, direction, entry_price, market_mid, window_time, result, pnl, recorded_at)
VALUES (?, ?, ?, ?, ?, ?, ?, ?)
"""


@dataclass
class AssetStats:
    """Rolling statistics for a single asset."""
    win_rate: float
    avg_pnl: float
    trade_count: int


def _get_conn() -> sqlite3.Connection:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_DB_PATH), check_same_thread=False)
    conn.execute(_CREATE_SQL)
    conn.commit()
    return conn


class CryptoOracleTracker:
    """Track per-asset, per-window performance for crypto oracle."""

    def __init__(self, db_path: Optional[Path] = None) -> None:
        self._db_path = db_path or _DB_PATH
        self._conn: Optional[sqlite3.Connection] = None

    def _ensure_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
            self._conn.execute(_CREATE_SQL)
            self._conn.commit()
        return self._conn

    def record_trade(
        self,
        asset: str,
        direction: str,
        entry_price: float,
        market_mid: float,
        window_time: datetime,
        result: str,
        pnl: float,
    ) -> None:
        """Record a completed trade."""
        conn = self._ensure_conn()
        now = datetime.now(timezone.utc).isoformat()
        wt = window_time.isoformat() if isinstance(window_time, datetime) else str(window_time)
        with _LOCK:
            conn.execute(
                _INSERT_SQL,
                (asset, direction, entry_price, market_mid, wt, result, pnl, now),
            )
            conn.commit()

    def get_asset_stats(self, asset: str, lookback_trades: int = 20) -> AssetStats:
        """Get rolling stats for an asset: WR, avg PnL, trade count."""
        conn = self._ensure_conn()
        with _LOCK:
            rows = conn.execute(
                "SELECT result, pnl FROM crypto_oracle_performance "
                "WHERE asset = ? ORDER BY id DESC LIMIT ?",
                (asset, lookback_trades),
            ).fetchall()

        if not rows:
            return AssetStats(win_rate=0.0, avg_pnl=0.0, trade_count=0)

        wins = sum(1 for r, _ in rows if r == "win")
        total_pnl = sum(p for _, p in rows)
        return AssetStats(
            win_rate=wins / len(rows),
            avg_pnl=total_pnl / len(rows),
            trade_count=len(rows),
        )

    def get_time_stats(self, lookback_hours: int = 24) -> Dict[int, float]:
        """Get WR by hour-of-day (UTC)."""
        conn = self._ensure_conn()
        cutoff = datetime.now(timezone.utc).isoformat()
        with _LOCK:
            rows = conn.execute(
                "SELECT window_time, result FROM crypto_oracle_performance "
                "WHERE recorded_at >= datetime(?, '-' || ? || ' hours')",
                (cutoff, lookback_hours),
            ).fetchall()

        hour_data: Dict[int, list[str]] = {}
        for wt, result in rows:
            try:
                dt = datetime.fromisoformat(wt)
                h = dt.hour
            except (ValueError, TypeError):
                continue
            hour_data.setdefault(h, []).append(result)

        return {
            h: sum(1 for r in results if r == "win") / len(results)
            for h, results in hour_data.items()
            if results
        }

    def get_bucket_stats(self, lookback_trades: int = 50) -> Dict[str, float]:
        """Get WR by price bucket (40-45c, 45-50c, 50-55c, 55-60c)."""
        conn = self._ensure_conn()
        with _LOCK:
            rows = conn.execute(
                "SELECT market_mid, result FROM crypto_oracle_performance "
                "ORDER BY id DESC LIMIT ?",
                (lookback_trades,),
            ).fetchall()

        buckets: Dict[str, list[str]] = {
            "40-45c": [], "45-50c": [], "50-55c": [], "55-60c": [],
        }
        for mid, result in rows:
            if 0.40 <= mid < 0.45:
                buckets["40-45c"].append(result)
            elif 0.45 <= mid < 0.50:
                buckets["45-50c"].append(result)
            elif 0.50 <= mid < 0.55:
                buckets["50-55c"].append(result)
            elif 0.55 <= mid < 0.60:
                buckets["55-60c"].append(result)

        return {
            k: sum(1 for r in v if r == "win") / len(v) if v else 0.0
            for k, v in buckets.items()
        }

    def detect_edge_decay(self, asset: str) -> bool:
        """Return True if WR drops below 55% after 20+ trades."""
        stats = self.get_asset_stats(asset, lookback_trades=50)
        if stats.trade_count < 20:
            return False
        return stats.win_rate < 0.55
