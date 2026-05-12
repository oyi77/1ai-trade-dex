"""Tests for ShadowRunner in backend.core.shadow_mode."""

from uuid import uuid4
from backend.core.shadow_mode import ShadowRunner, ShadowTrade
from backend.models.database import ShadowTrade as DBSHadowTrade


def test_record_and_settle_win():
    """Record a trade and settle it as a win — P&L should be positive."""
    runner = ShadowRunner()
    trade = runner.record_signal(
        market_ticker="BTC-UP-12345",
        direction="up",
        entry_price=0.55,
        size=100.0,
        model_prob=0.70,
        strategy="btc_5min",
    )
    assert isinstance(trade, ShadowTrade)
    assert trade.settled is False

    # settlement_value=1.0 means UP won
    runner.settle("BTC-UP-12345", settlement_value=1.0)

    assert trade.settled is True
    assert trade.pnl is not None
    assert trade.pnl > 0  # (1.0 - 0.55) * 100 = 45.0
    assert abs(trade.pnl - 45.0) < 1e-6


def test_settle_loss():
    """Record a trade and settle it as a loss — P&L should be negative."""
    runner = ShadowRunner()
    trade = runner.record_signal(
        market_ticker="BTC-UP-99999",
        direction="up",
        entry_price=0.60,
        size=50.0,
        model_prob=0.65,
        strategy="btc_5min",
    )
    # settlement_value=0.0 means DOWN won (up loses)
    runner.settle("BTC-UP-99999", settlement_value=0.0)

    assert trade.settled is True
    assert trade.pnl is not None
    assert trade.pnl < 0  # -0.60 * 50 = -30.0
    assert abs(trade.pnl - (-30.0)) < 1e-6


def test_performance_metrics():
    """Multiple trades verify win_rate and total_pnl are computed correctly."""
    runner = ShadowRunner()

    # Trade 1: win — direction=up, settlement=1.0
    runner.record_signal("MKT-A", "up", 0.50, 100.0, 0.70, "strat_a")
    runner.settle("MKT-A", 1.0)  # pnl = (1-0.5)*100 = 50

    # Trade 2: loss — direction=down, settlement=1.0 (up won, down loses)
    runner.record_signal("MKT-B", "down", 0.40, 80.0, 0.65, "strat_a")
    runner.settle("MKT-B", 1.0)  # pnl = -0.40*80 = -32

    # Trade 3: win — direction=down, settlement=0.0 (down won)
    runner.record_signal("MKT-C", "down", 0.45, 60.0, 0.60, "strat_b")
    runner.settle("MKT-C", 0.0)  # pnl = (1-0.45)*60 = 33

    perf = runner.get_performance()

    assert perf.total_trades == 3
    assert perf.settled_trades == 3
    assert abs(perf.total_pnl - (50.0 - 32.0 + 33.0)) < 1e-6  # 51.0
    assert abs(perf.win_rate - (2 / 3)) < 1e-6
    assert "strat_a" in perf.strategy_breakdown
    assert "strat_b" in perf.strategy_breakdown
    assert abs(perf.strategy_breakdown["strat_a"] - (50.0 - 32.0)) < 1e-6
    assert abs(perf.strategy_breakdown["strat_b"] - 33.0) < 1e-6


def test_compare_with_live():
    """compare_with_live returns correct shadow vs live comparison."""
    runner = ShadowRunner()

    runner.record_signal("MKT-X", "up", 0.50, 100.0, 0.75, "strat_x")
    runner.settle("MKT-X", 1.0)  # pnl = 50.0

    result = runner.compare_with_live(live_pnl=30.0)

    assert result["shadow_pnl"] == 50.0
    assert result["live_pnl"] == 30.0
    assert abs(result["difference"] - 20.0) < 1e-6
    assert result["shadow_better"] is True

    # Case where shadow is worse
    result2 = runner.compare_with_live(live_pnl=80.0)
    assert result2["shadow_better"] is False
    assert abs(result2["difference"] - (50.0 - 80.0)) < 1e-6


class TestDBSessionShadowRunner:
    """Tests for persistent DB-backed ShadowRunner (Task 14)."""

    @classmethod
    def setup_class(cls):
        """Setup test class - clear any existing data."""
        from backend.application.strategy.shadow_runner import DBSessionShadowRunner
        runner = DBSessionShadowRunner()
        try:
            runner.clear_all_trades()
        except Exception:
            pass  # Ignore errors during setup

    def setup_method(self):
        """Setup each test method - clear any existing data."""
        from backend.application.strategy.shadow_runner import DBSessionShadowRunner
        runner = DBSessionShadowRunner()
        try:
            runner.clear_all_trades()
        except Exception:
            pass  # Ignore errors during setup

    def test_record_signal_persists_to_db(self):
        """Test that record_signal persists to database."""
        from backend.application.strategy.shadow_runner import DBSessionShadowRunner

        runner = DBSessionShadowRunner()

        # Record a signal
        trade = runner.record_signal(
            market_ticker="BTC-UP-12345",
            direction="up",
            entry_price=0.55,
            size=100.0,
            model_prob=0.70,
            strategy="btc_5min",
            genome_id="test_genome_1",
            predicted_outcome=0.65,
        )

        # Verify it was persisted
        assert trade.id is not None
        assert trade.market_ticker == "BTC-UP-12345"
        assert trade.direction == "up"
        assert trade.entry_price == 0.55
        assert trade.size == 100.0
        assert trade.model_probability == 0.70
        assert trade.genome_id == "test_genome_1"
        assert trade.predicted_outcome == 0.65
        assert trade.settled is False

        # Verify count increased
        count = runner.get_trades_count()
        assert count == 1

    def test_settle_calculates_pnl_and_accuracy(self):
        """Test that settle calculates P&L and accuracy score correctly."""
        from backend.application.strategy.shadow_runner import DBSessionShadowRunner

        runner = DBSessionShadowRunner()
        unique_ticker = f"SHADOW-TEST-PNL-{uuid4().hex[:8]}"

        trade = runner.record_signal(
            market_ticker=unique_ticker,
            direction="up",
            entry_price=0.55,
            size=100.0,
            model_prob=0.70,
            strategy="btc_5min",
            genome_id="test_genome_1",
            predicted_outcome=0.65,
        )

        trade_id = trade.id

        runner.settle(market_ticker=unique_ticker, settlement_value=1.0, actual_outcome=0.55)

        from backend.models.database import SessionLocal, ShadowTrade
        db = SessionLocal()
        try:
            settled_trade = db.query(ShadowTrade).filter_by(id=trade_id).first()
            assert settled_trade is not None, f"Trade {trade_id} not found in DB"
            assert settled_trade.settled is True
            assert settled_trade.settlement_value == 1.0
            assert settled_trade.pnl == (1.0 - 0.55) * 100.0
            assert settled_trade.accuracy_score == abs(0.65 - 0.55)
            assert settled_trade.actual_outcome == 0.55
        finally:
            db.close()

    def test_persistence_across_restart(self):
        """Test that shadow trades persist across process restart."""
        from backend.application.strategy.shadow_runner import DBSessionShadowRunner

        # First "process" - record some trades
        runner1 = DBSessionShadowRunner()

        runner1.record_signal(
            market_ticker="BTC-UP-12345",
            direction="up",
            entry_price=0.55,
            size=100.0,
            model_prob=0.70,
            strategy="btc_5min",
        )
        runner1.record_signal(
            market_ticker="BTC-DOWN-67890",
            direction="down",
            entry_price=0.45,
            size=50.0,
            model_prob=0.30,
            strategy="btc_5min",
        )

        count_before = runner1.get_trades_count()
        assert count_before == 2

        # Second "process" - create new instance
        runner2 = DBSessionShadowRunner()
        count_after = runner2.get_trades_count()

        # Verify data persisted
        assert count_after == 2

    def test_performance_aggregation(self):
        """Test that get_performance returns correct aggregate metrics."""
        from backend.application.strategy.shadow_runner import DBSessionShadowRunner

        runner = DBSessionShadowRunner()

        # Record some trades
        runner.record_signal(
            market_ticker="BTC-UP-12345",
            direction="up",
            entry_price=0.55,
            size=100.0,
            model_prob=0.70,
            strategy="btc_5min",
        )
        runner.record_signal(
            market_ticker="BTC-DOWN-67890",
            direction="down",
            entry_price=0.45,
            size=50.0,
            model_prob=0.30,
            strategy="btc_5min",
        )

        # Settle them
        runner.settle("BTC-UP-12345", settlement_value=1.0)  # Win
        runner.settle("BTC-DOWN-67890", settlement_value=1.0)  # Loss (down but settled at 1.0)

        # Get performance
        perf = runner.get_performance()

        # Verify metrics
        assert perf.total_trades == 2
        assert perf.settled_trades == 2
        assert perf.win_rate == 0.5  # 1 win, 1 loss
        assert abs(perf.avg_edge) < 1e-6  # Average of (model_prob - entry_price) should be close to 0
        assert "btc_5min" in perf.strategy_breakdown

    def test_genome_specific_performance(self):
        """Test that get_performance filters by genome_id correctly."""
        from backend.application.strategy.shadow_runner import DBSessionShadowRunner

        runner = DBSessionShadowRunner()

        # Record trades for different genomes
        runner.record_signal(
            market_ticker="BTC-UP-12345",
            direction="up",
            entry_price=0.55,
            size=100.0,
            model_prob=0.70,
            strategy="btc_5min",
            genome_id="test_genome_1",
        )
        runner.record_signal(
            market_ticker="BTC-DOWN-67890",
            direction="down",
            entry_price=0.45,
            size=50.0,
            model_prob=0.30,
            strategy="btc_5min",
            genome_id="test_genome_2",
        )

        # Settle them
        runner.settle("BTC-UP-12345", settlement_value=1.0)
        runner.settle("BTC-DOWN-67890", settlement_value=0.0)

        # Get performance for genome 1
        perf1 = runner.get_performance(genome_id="test_genome_1")
        assert perf1.total_trades == 1
        assert perf1.settled_trades == 1

        # Get performance for genome 2
        perf2 = runner.get_performance(genome_id="test_genome_2")
        assert perf2.total_trades == 1
        assert perf2.settled_trades == 1

        # Get overall performance
        perf_all = runner.get_performance()
        assert perf_all.total_trades == 2
        assert perf_all.settled_trades == 2

    def test_promotion_eligibility_accuracy_above_threshold(self):
        """Test promotion eligibility with accuracy above 60% and sufficient time."""
        from backend.application.strategy.shadow_runner import DBSessionShadowRunner
        from datetime import datetime, timedelta, timezone

        runner = DBSessionShadowRunner()

        # Record trades with high accuracy (within 0.2 of predicted)
        now = datetime.now(timezone.utc)
        _two_days_ago = now - timedelta(days=2)

        # Add trades with accurate predictions (within 0.2)
        runner.record_signal(
            market_ticker='BTC-UP-2001',
            direction='up',
            entry_price=0.50,
            size=100.0,
            model_prob=0.70,
            strategy='btc_5min',
            genome_id="test_genome_100",
            predicted_outcome=0.65
        )
        runner.settle('BTC-UP-2001', settlement_value=1.0, actual_outcome=0.63)  # Within 0.2 of 0.65

        runner.record_signal(
            market_ticker='BTC-UP-2002',
            direction='up',
            entry_price=0.45,
            size=100.0,
            model_prob=0.65,
            strategy='btc_5min',
            genome_id="test_genome_100",
            predicted_outcome=0.60
        )
        runner.settle('BTC-UP-2002', settlement_value=1.0, actual_outcome=0.58)  # Within 0.2 of 0.60

        # Evaluate eligibility
        eligibility = runner.evaluate_promotion_eligibility(genome_id="test_genome_100")

        assert eligibility['total_trades'] == 2
        assert eligibility['accuracy'] >= 1.0  # Both trades accurate
        assert eligibility['days_active'] <= 1  # Less than 1 day old
        assert not eligibility['eligible']  # Not enough days
        assert 'Less than 1 day' in eligibility['reason']

    def test_promotion_eligibility_accuracy_below_threshold(self):
        """Test promotion eligibility with accuracy below 60%."""
        from backend.application.strategy.shadow_runner import DBSessionShadowRunner
        from datetime import datetime, timedelta, timezone

        runner = DBSessionShadowRunner()

        # Record trades with low accuracy (outside 0.2 of predicted)
        now = datetime.now(timezone.utc)
        two_days_ago = now - timedelta(days=2)

        # Add trades with inaccurate predictions (outside 0.2)
        runner.record_signal(
            market_ticker='BTC-UP-3001',
            direction='up',
            entry_price=0.50,
            size=100.0,
            model_prob=0.70,
            strategy='btc_5min',
            genome_id="test_genome_200",
            predicted_outcome=0.85
        )
        # Set timestamp to 2 days ago to ensure sufficient days
        runner._get_db().query(DBSHadowTrade).filter_by(market_ticker='BTC-UP-3001').update({'timestamp': two_days_ago})
        runner._get_db().commit()
        runner.settle('BTC-UP-3001', settlement_value=1.0, actual_outcome=0.50)  # Outside 0.2 of 0.85

        runner.record_signal(
            market_ticker='BTC-UP-3002',
            direction='up',
            entry_price=0.45,
            size=100.0,
            model_prob=0.65,
            strategy='btc_5min',
            genome_id="test_genome_200",
            predicted_outcome=0.80
        )
        runner._get_db().query(DBSHadowTrade).filter_by(market_ticker='BTC-UP-3002').update({'timestamp': two_days_ago})
        runner._get_db().commit()
        runner.settle('BTC-UP-3002', settlement_value=1.0, actual_outcome=0.55)  # Outside 0.2 of 0.80

        # Evaluate eligibility
        eligibility = runner.evaluate_promotion_eligibility(genome_id="test_genome_200")

        assert eligibility['total_trades'] == 2
        assert eligibility['accuracy'] == 0.0  # No accurate trades
        assert eligibility['days_active'] >= 2.0  # Sufficient days
        assert not eligibility['eligible']
        assert 'Accuracy below 60%' in eligibility['reason']

    def test_promotion_eligibility_no_trades(self):
        """Test promotion eligibility with no trades."""
        from backend.application.strategy.shadow_runner import DBSessionShadowRunner

        runner = DBSessionShadowRunner()

        # Evaluate eligibility for genome with no trades
        eligibility = runner.evaluate_promotion_eligibility(genome_id="test_genome_999")

        assert eligibility['total_trades'] == 0
        assert eligibility['accuracy'] == 0.0
        assert eligibility['days_active'] == 0.0
        assert not eligibility['eligible']
        assert 'No trades' in eligibility['reason']

    def test_promotion_eligibility_eligible(self):
        """Test promotion eligibility with all criteria met."""
        from backend.application.strategy.shadow_runner import DBSessionShadowRunner
        from datetime import datetime, timedelta, timezone

        runner = DBSessionShadowRunner()

        # Record trades with high accuracy and sufficient time
        now = datetime.now(timezone.utc)
        two_days_ago = now - timedelta(days=2)

        # Add trades with accurate predictions (within 0.2) from 2 days ago
        runner.record_signal(
            market_ticker='BTC-UP-4001',
            direction='up',
            entry_price=0.50,
            size=100.0,
            model_prob=0.70,
            strategy='btc_5min',
            genome_id="test_genome_300",
            predicted_outcome=0.65
        )
        # Manually set timestamp to 2 days ago to simulate older trades
        runner._get_db().query(DBSHadowTrade).filter_by(market_ticker='BTC-UP-4001').update({'timestamp': two_days_ago})
        runner._get_db().commit()
        runner.settle('BTC-UP-4001', settlement_value=1.0, actual_outcome=0.63)  # Within 0.2 of 0.65

        runner.record_signal(
            market_ticker='BTC-UP-4002',
            direction='up',
            entry_price=0.45,
            size=100.0,
            model_prob=0.65,
            strategy='btc_5min',
            genome_id="test_genome_300",
            predicted_outcome=0.60
        )
        runner._get_db().query(DBSHadowTrade).filter_by(market_ticker='BTC-UP-4002').update({'timestamp': two_days_ago})
        runner._get_db().commit()
        runner.settle('BTC-UP-4002', settlement_value=1.0, actual_outcome=0.58)  # Within 0.2 of 0.60

        # Evaluate eligibility
        eligibility = runner.evaluate_promotion_eligibility(genome_id="test_genome_300")

        assert eligibility['total_trades'] == 2
        assert eligibility['accuracy'] >= 1.0  # Both trades accurate
        assert eligibility['days_active'] >= 2.0  # At least 2 days old
        assert eligibility['eligible']  # Meets all criteria
        assert eligibility['reason'] == 'Eligible for promotion'
