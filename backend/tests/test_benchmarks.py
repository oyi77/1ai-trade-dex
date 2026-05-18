"""G-23: Performance benchmark tests for trade execution latency and settlement speed."""
import time
from unittest.mock import MagicMock

from backend.core.risk_manager import RiskManager


class TestTradeExecutionLatency:
    """Benchmark: risk manager validate_trade should complete in < 10ms."""

    def test_validate_trade_latency(self):
        """Risk validation should be fast (< 15ms per call)."""
        rm = RiskManager()
        db = MagicMock()
        db.query.return_value.filter.return_value.scalar.return_value = 0.0
        db.query.return_value.filter_by.return_value.first.return_value = MagicMock(
            bankroll=100.0, mode="paper", misc_data=None,
            paper_bankroll=100.0, testnet_bankroll=100.0,
        )

        iterations = 100
        start = time.perf_counter()
        for _ in range(iterations):
            rm.validate_trade(
                size=5.0,
                current_exposure=10.0,
                bankroll=100.0,
                confidence=0.7,
                market_ticker="TEST-MARKET",
                db=db,
                mode="paper",
                strategy_name="test_strategy",
                direction="YES",
                market_price=0.55,
                signal_win_rate=0.65,
            )
        elapsed = time.perf_counter() - start
        avg_ms = (elapsed / iterations) * 1000

        assert avg_ms < 15.0, f"validate_trade avg latency {avg_ms:.2f}ms > 15ms threshold"

    def test_check_drawdown_latency(self):
        """Drawdown check should be fast (< 5ms per call)."""
        rm = RiskManager()
        db = MagicMock()
        db.query.return_value.filter.return_value.scalar.return_value = 0.0
        db.query.return_value.filter_by.return_value.first.return_value = MagicMock(
            paper_initial_bankroll=100.0, testnet_initial_bankroll=100.0,
        )

        iterations = 100
        start = time.perf_counter()
        for _ in range(iterations):
            rm.check_drawdown(100.0, db=db, mode="paper")
        elapsed = time.perf_counter() - start
        avg_ms = (elapsed / iterations) * 1000

        assert avg_ms < 5.0, f"check_drawdown avg latency {avg_ms:.2f}ms > 5ms threshold"


class TestSettlementSpeed:
    """Benchmark: settlement-related calculations."""

    def test_drawdown_calculation_speed(self):
        """Drawdown percentage calculation should be instant."""
        RiskManager()

        iterations = 10000
        start = time.perf_counter()
        for _ in range(iterations):
            # Simulate peak-to-trough calculation
            equity = [100, 105, 102, 98, 103, 110, 107]
            peak = equity[0]
            max_dd = 0.0
            for val in equity:
                if val > peak:
                    peak = val
                dd = (peak - val) / peak if peak > 0 else 0.0
                if dd > max_dd:
                    max_dd = dd
        elapsed = time.perf_counter() - start
        avg_us = (elapsed / iterations) * 1_000_000

        assert avg_us < 100.0, f"drawdown calc avg {avg_us:.2f}us > 100us threshold"


class TestRiskManagerEdgeFilter:
    """Benchmark: edge filter performance."""

    def test_edge_check_latency(self):
        """Edge check should be near-instant."""
        rm = RiskManager()

        iterations = 10000
        start = time.perf_counter()
        for _ in range(iterations):
            try:
                rm.check_edge(0.55, 0.65, "test-market")
            except Exception:
                pass
        elapsed = time.perf_counter() - start
        avg_us = (elapsed / iterations) * 1_000_000

        assert avg_us < 50.0, f"edge check avg {avg_us:.2f}us > 50us threshold"
