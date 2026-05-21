"""Tests for backend.monitoring.trade_journal."""

import csv
import os
import tempfile
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from backend.monitoring.trade_journal import (
    TradeJournal,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_trade(**overrides):
    """Return a mock Trade object with sensible defaults."""
    defaults = dict(
        id=1,
        market_ticker="BTC-5MIN",
        platform="polymarket",
        strategy="btc_oracle",
        trading_mode="paper",
        direction="up",
        entry_price=0.55,
        size=10.0,
        timestamp=datetime(2026, 5, 19, 12, 0, 0, tzinfo=timezone.utc),
        settled=True,
        result="win",
        pnl=4.5,
        settlement_value=1.0,
        confidence=0.72,
        model_probability=0.68,
        edge_at_entry=0.13,
        fee=0.01,
        slippage=0.002,
        source="bot",
    )
    defaults.update(overrides)
    t = MagicMock()
    for k, v in defaults.items():
        setattr(t, k, v)
    return t


def _mock_query_chain(mock_session, trades_for_all):
    """Set up a mock query chain where .all() returns *trades_for_all*.

    The chain supports: session.query().filter().order_by().limit().all()
    and also session.query().filter().all() (for summary/perf queries).
    """
    mock_query = MagicMock()
    mock_session.query.return_value = mock_query
    mock_query.filter.return_value = mock_query
    mock_query.order_by.return_value = mock_query
    mock_query.limit.return_value = mock_query
    mock_query.all.return_value = trades_for_all
    return mock_query


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestGetTrades:
    """get_trades returns filtered list of trade dicts."""

    def test_returns_list_of_dicts(self):
        trades = [_make_trade(id=1), _make_trade(id=2)]
        mock_session = MagicMock()
        _mock_query_chain(mock_session, trades)

        journal = TradeJournal(db_session=mock_session)
        result = journal.get_trades()

        assert len(result) == 2
        assert all(isinstance(r, dict) for r in result)
        assert result[0]["id"] == 1
        assert result[1]["id"] == 2

    def test_filter_by_strategy(self):
        trades = [_make_trade(strategy="line_move")]
        mock_session = MagicMock()
        _mock_query_chain(mock_session, trades)

        journal = TradeJournal(db_session=mock_session)
        result = journal.get_trades(strategy="line_move")

        assert len(result) == 1
        assert result[0]["strategy"] == "line_move"

    def test_filter_by_date_range(self):
        trades = [_make_trade()]
        mock_session = MagicMock()
        mock_query = _mock_query_chain(mock_session, trades)

        journal = TradeJournal(db_session=mock_session)
        result = journal.get_trades(
            start_date="2026-05-01T00:00:00",
            end_date="2026-05-31T23:59:59",
        )

        assert len(result) == 1
        # Two filter calls: one for start_date, one for end_date
        assert mock_query.filter.call_count >= 2


class TestGetDailySummary:
    """get_daily_summary computes correct totals for a day."""

    def test_correct_totals(self):
        trades = [
            _make_trade(id=1, pnl=5.0, size=10.0),
            _make_trade(id=2, pnl=-2.0, size=8.0),
            _make_trade(id=3, pnl=3.0, size=12.0),
        ]
        mock_session = MagicMock()
        mock_query = MagicMock()
        mock_session.query.return_value = mock_query
        mock_query.filter.return_value.all.return_value = trades

        journal = TradeJournal(db_session=mock_session)
        summary = journal.get_daily_summary(target_date="2026-05-19")

        assert summary.total_trades == 3
        assert summary.total_pnl == pytest.approx(6.0)
        assert summary.wins == 2
        assert summary.losses == 1
        assert summary.win_rate == pytest.approx(2 / 3)
        assert summary.volume == pytest.approx(16.5)  # sum(abs(size)*entry_price)
        assert summary.best_trade is not None
        assert summary.worst_trade is not None

    def test_empty_day(self):
        mock_session = MagicMock()
        mock_query = MagicMock()
        mock_session.query.return_value = mock_query
        mock_query.filter.return_value.all.return_value = []

        journal = TradeJournal(db_session=mock_session)
        summary = journal.get_daily_summary(target_date="2026-01-01")

        assert summary.total_trades == 0
        assert summary.total_pnl == 0.0
        assert summary.win_rate == 0.0
        assert summary.best_trade is None
        assert summary.worst_trade is None


class TestGetStrategyPerformance:
    """get_strategy_performance returns correct stats."""

    def test_correct_stats(self):
        trades = [
            _make_trade(id=1, strategy="btc_oracle", pnl=10.0),
            _make_trade(id=2, strategy="btc_oracle", pnl=-4.0),
            _make_trade(id=3, strategy="btc_oracle", pnl=6.0),
        ]
        mock_session = MagicMock()
        mock_query = MagicMock()
        mock_session.query.return_value = mock_query
        mock_query.filter.return_value.all.return_value = trades

        journal = TradeJournal(db_session=mock_session)
        perf = journal.get_strategy_performance("btc_oracle")

        assert perf.strategy == "btc_oracle"
        assert perf.total_trades == 3
        assert perf.total_pnl == pytest.approx(12.0)
        assert perf.avg_pnl == pytest.approx(4.0)
        assert perf.win_rate == pytest.approx(2 / 3)
        assert perf.best_trade is not None
        assert perf.worst_trade is not None

    def test_unknown_strategy(self):
        mock_session = MagicMock()
        mock_query = MagicMock()
        mock_session.query.return_value = mock_query
        mock_query.filter.return_value.all.return_value = []

        journal = TradeJournal(db_session=mock_session)
        perf = journal.get_strategy_performance("nonexistent")

        assert perf.total_trades == 0
        assert perf.total_pnl == 0.0
        assert perf.win_rate == 0.0


class TestExportCsv:
    """export_csv writes correct CSV file."""

    def test_creates_file_with_content(self):
        trades = [
            _make_trade(id=1, pnl=5.0),
            _make_trade(id=2, pnl=-2.0),
        ]
        mock_session = MagicMock()
        _mock_query_chain(mock_session, trades)

        journal = TradeJournal(db_session=mock_session)

        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "export.csv")
            result = journal.export_csv(output_path=path)

            assert result == path
            assert os.path.exists(path)

            with open(path, newline="") as f:
                reader = csv.DictReader(f)
                rows = list(reader)

            assert len(rows) == 2
            assert rows[0]["id"] == "1"
            assert rows[0]["pnl"] == "5.0"

    def test_empty_results_creates_header_only(self):
        mock_session = MagicMock()
        _mock_query_chain(mock_session, [])

        journal = TradeJournal(db_session=mock_session)

        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "empty.csv")
            journal.export_csv(output_path=path)

            assert os.path.exists(path)
            with open(path, newline="") as f:
                reader = csv.DictReader(f)
                rows = list(reader)
            assert len(rows) == 0
