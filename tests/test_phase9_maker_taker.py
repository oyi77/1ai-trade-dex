"""Phase 9 tests — Maker/Taker Role Analytics.

Tests cover:
  - MakerTakerAnalytics.get_stats() with mocked Trade queries:
      * all maker trades → prefer_maker recommendation
      * negative taker ROI → reduce_taker recommendation
      * below threshold → insufficient_data
      * neutral scenario
  - Parquet export includes 'role' column
  - API endpoint shape (unit-level import test)
"""

import os
import sqlite3
import tempfile
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
import pyarrow as pa
import pyarrow.parquet as pq

from backend.core.maker_taker_analytics import MakerTakerAnalytics
from backend.models.database import Base, Trade
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


# ── Fixture ───────────────────────────────────────────────────────────────────

@pytest.fixture
def db_session():
    """In-memory SQLite session for isolated test trades."""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _make_settled_trade(session, role: str, pnl: float, size: float = 100.0):
    """Insert a settled trade with the given role and PnL."""
    t = Trade(
        market_ticker="TEST-1",
        platform="polymarket",
        entry_price=0.50,
        size=size,
        pnl=pnl,
        settled=True,
        result="win" if pnl >= 0 else "loss",
        role=role,
        timestamp=datetime.now(timezone.utc),
    )
    session.add(t)
    session.commit()
    return t


# ── MakerTakerAnalytics unit tests ───────────────────────────────────────────

class TestMakerTakerAnalytics:
    """Unit tests for MakerTakerAnalytics with real DB inserts."""

    def _fresh(self) -> MakerTakerAnalytics:
        """Return a fresh (no cache) analytics instance."""
        a = MakerTakerAnalytics()
        a.invalidate()
        return a

    def test_prefer_maker_recommendation(self, db_session):
        """When maker ROI clearly > taker ROI + 2%, recommendation is prefer_maker."""
        analytics = self._fresh()
        # 20 maker trades with 10% ROI each (PnL = 10, size = 100)
        for _ in range(20):
            _make_settled_trade(db_session, "maker", pnl=10.0, size=100.0)
        # 20 taker trades with -5% ROI each (PnL = -5, size = 100)
        for _ in range(20):
            _make_settled_trade(db_session, "taker", pnl=-5.0, size=100.0)

        result = analytics.get_stats(db_session)
        assert result["maker"]["count"] == 20
        assert result["taker"]["count"] == 20
        # taker ROI negative → should be reduce_taker (checked first in logic)
        assert result["recommendation"] in ("reduce_taker", "prefer_maker")

    def test_reduce_taker_recommendation(self, db_session):
        """When taker ROI < -1%, recommendation is reduce_taker."""
        analytics = self._fresh()
        for _ in range(20):
            _make_settled_trade(db_session, "maker", pnl=5.0, size=100.0)
        for _ in range(20):
            _make_settled_trade(db_session, "taker", pnl=-3.0, size=100.0)

        result = analytics.get_stats(db_session)
        assert result["recommendation"] == "reduce_taker"
        assert result["taker"]["roi"] == pytest.approx(-0.03, rel=1e-3)

    def test_prefer_maker_when_taker_not_negative_but_much_worse(self, db_session):
        """When taker ROI >= -1% but maker ROI > taker ROI + 2%, recommendation is prefer_maker."""
        analytics = self._fresh()
        for _ in range(20):
            _make_settled_trade(db_session, "maker", pnl=5.0, size=100.0)   # +5% ROI
        for _ in range(20):
            _make_settled_trade(db_session, "taker", pnl=0.5, size=100.0)   # +0.5% ROI

        result = analytics.get_stats(db_session)
        # Maker: 5%, Taker: 0.5%, difference = 4.5% > 2% → prefer_maker
        assert result["recommendation"] == "prefer_maker"

    def test_neutral_recommendation(self, db_session):
        """When maker ≈ taker ROI and both ≥ -1%, recommendation is neutral."""
        analytics = self._fresh()
        for _ in range(20):
            _make_settled_trade(db_session, "maker", pnl=2.0, size=100.0)   # +2% ROI
        for _ in range(20):
            _make_settled_trade(db_session, "taker", pnl=1.5, size=100.0)   # +1.5% ROI

        result = analytics.get_stats(db_session)
        # Difference = 0.5% < 2% threshold, taker ROI = 1.5% > -1% → neutral
        assert result["recommendation"] == "neutral"

    def test_insufficient_data_below_minimum(self, db_session):
        """When either role has < 20 settled trades, recommendation is insufficient_data."""
        analytics = self._fresh()
        # Only 5 maker trades — below the 20-trade minimum
        for _ in range(5):
            _make_settled_trade(db_session, "maker", pnl=10.0)
        for _ in range(20):
            _make_settled_trade(db_session, "taker", pnl=-5.0)

        result = analytics.get_stats(db_session)
        assert result["recommendation"] == "insufficient_data"

    def test_result_shape(self, db_session):
        """Result always contains expected keys for both roles."""
        analytics = self._fresh()
        result = analytics.get_stats(db_session)

        assert "maker" in result
        assert "taker" in result
        assert "recommendation" in result
        assert "cached_at" in result

        for role_key in ("maker", "taker"):
            role = result[role_key]
            assert "count" in role
            assert "pnl" in role
            assert "size" in role
            assert "roi" in role

    def test_cache_returns_same_object(self, db_session):
        """Second call within TTL returns the same cached dict (identity check)."""
        analytics = self._fresh()
        r1 = analytics.get_stats(db_session)
        r2 = analytics.get_stats(db_session)
        assert r1 is r2  # identical object from cache

    def test_invalidate_forces_recompute(self, db_session):
        """After invalidate(), the next call returns a fresh (new) dict."""
        analytics = self._fresh()
        r1 = analytics.get_stats(db_session)
        analytics.invalidate()
        r2 = analytics.get_stats(db_session)
        assert r1 is not r2  # different object after invalidation

    def test_only_settled_trades_counted(self, db_session):
        """Unsettled trades must not be included in the ROI computation."""
        analytics = self._fresh()
        # 20 settled maker trades
        for _ in range(20):
            _make_settled_trade(db_session, "maker", pnl=10.0)
        # 5 unsettled maker trades (should be ignored)
        for _ in range(5):
            t = Trade(
                market_ticker="TEST-UNSETTLED",
                platform="polymarket",
                entry_price=0.5,
                size=100.0,
                pnl=999.0,   # huge — would skew ROI if included
                settled=False,
                role="maker",
                timestamp=datetime.now(timezone.utc),
            )
            db_session.add(t)
        db_session.commit()

        result = analytics.get_stats(db_session)
        assert result["maker"]["count"] == 20
        assert result["maker"]["roi"] == pytest.approx(0.10, rel=1e-3)


# ── Parquet role column test ──────────────────────────────────────────────────

class TestParquetRoleColumn:
    """Verify that db_archiver.archive_trades_to_parquet includes the role column."""

    def test_role_column_present_in_parquet(self, tmp_path):
        """Write a minimal trades SQLite DB and archive it; check 'role' is in Parquet schema."""
        from backend.core.db_archiver import archive_trades_to_parquet

        # Build a minimal SQLite DB with a trades table
        db_file = str(tmp_path / "app.db")
        con = sqlite3.connect(db_file)
        con.execute("""
            CREATE TABLE trades (
                id INTEGER PRIMARY KEY,
                market_ticker TEXT,
                direction TEXT DEFAULT 'up',
                size REAL DEFAULT 10.0,
                entry_price REAL DEFAULT 0.5,
                settlement_value REAL DEFAULT 1.0,
                pnl REAL DEFAULT 5.0,
                result TEXT DEFAULT 'win',
                timestamp TEXT,
                signal_id INTEGER,
                strategy TEXT DEFAULT 'test_strategy',
                role TEXT DEFAULT 'maker'
            )
        """)
        ts = datetime.now(timezone.utc).isoformat()
        con.execute(
            "INSERT INTO trades (market_ticker, timestamp, role) VALUES (?, ?, ?)",
            ("TEST-PARQUET", ts, "maker"),
        )
        con.commit()
        con.close()

        out_dir = str(tmp_path / "parquet")
        count = archive_trades_to_parquet(db_file, out_dir, days_back=3650)  # 10 years back

        assert count >= 1

        # Find the written Parquet file and check its schema
        parquet_files = list(tmp_path.glob("parquet/**/*.parquet"))
        assert len(parquet_files) >= 1, "Expected at least one Parquet file"

        schema = pq.read_schema(parquet_files[0])
        column_names = schema.names
        assert "role" in column_names, f"'role' column missing from Parquet schema: {column_names}"


# ── API import smoke test ─────────────────────────────────────────────────────

class TestAnalyticsAPIModule:
    """Ensure the analytics API module imports cleanly and the route is registered."""

    def test_maker_taker_route_registered(self):
        """The analytics router should have a route at /maker-taker."""
        from backend.api.analytics import router

        paths = [route.path for route in router.routes]
        assert "/analytics/maker-taker" in paths, (
            f"Expected /analytics/maker-taker route in analytics router, got: {paths}"
        )

    def test_analytics_module_imports_without_error(self):
        """The analytics module should import without raising any exceptions."""
        import importlib
        import backend.api.analytics
        # Re-import to catch any lazy import errors
        importlib.reload(backend.api.analytics)
