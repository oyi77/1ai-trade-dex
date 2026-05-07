"""Tests for new AGI implementation gaps: fronttest, health check, rehabilitation, forensics integration."""

import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from backend.models.database import (
    Base, Trade, StrategyConfig, StrategyProposal, BotState,
)
from backend.models.outcome_tables import StrategyOutcome
from backend.models.historical_data import HistoricalCandle, MarketOutcome, WeatherSnapshot


@pytest.fixture
def db():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def _seed_botstate(db):
    bot = BotState(
        mode="paper",
        bankroll=1000.0,
        total_pnl=50.0,
        total_trades=10,
        winning_trades=6,
    )
    db.add(bot)
    db.commit()


def _seed_outcomes(db, strategy, n_wins, n_losses):
    now = datetime.now(timezone.utc)
    for i in range(n_wins):
        db.add(StrategyOutcome(
            strategy=strategy,
            market_ticker=f"TEST_{i}",
            market_type="test",
            trading_mode="paper",
            direction="up",
            result="win",
            pnl=5.0,
            reward=5.0,
            settled_at=now - timedelta(minutes=i),
            trade_id=1000 + i,
        ))
    for i in range(n_losses):
        db.add(StrategyOutcome(
            strategy=strategy,
            market_ticker=f"TEST_L_{i}",
            market_type="test",
            trading_mode="paper",
            direction="up",
            result="loss",
            pnl=-3.0,
            reward=-3.0,
            settled_at=now - timedelta(minutes=i + n_wins),
            trade_id=2000 + i,
        ))
    db.commit()


class TestFronttestValidator:
    def test_rejects_before_trial_period(self, db):
        from backend.core.fronttest_validator import FronttestValidator

        proposal = StrategyProposal(
            strategy_name="btc_oracle",
            change_details={"kelly_fraction": 0.1},
            expected_impact="test",
            admin_decision="executed",
            executed_at=datetime.now(timezone.utc) - timedelta(days=3),
        )
        db.add(proposal)
        db.commit()

        v = FronttestValidator(trial_days=14, min_trades=5)
        result = v.can_go_live(proposal.id, db=db)
        assert result["approved"] is False
        assert "incomplete" in result["reason"]

    def test_approves_after_trial_with_good_win_rate(self, db):
        from backend.core.fronttest_validator import FronttestValidator

        proposal = StrategyProposal(
            strategy_name="btc_oracle",
            change_details={"kelly_fraction": 0.1},
            expected_impact="test",
            admin_decision="executed",
            executed_at=datetime.now(timezone.utc) - timedelta(days=15),
        )
        db.add(proposal)
        db.commit()

        executed = proposal.executed_at
        for i in range(12):
            db.add(Trade(
                strategy="btc_oracle",
                trading_mode="paper",
                market_ticker=f"T{i}",
                direction="up",
                entry_price=0.5,
                size=10.0,
                result="win" if i < 7 else "loss",
                pnl=5.0 if i < 7 else -5.0,
                settled=True,
                timestamp=executed + timedelta(days=1, hours=i),
            ))
        db.commit()

        v = FronttestValidator(trial_days=14, min_trades=10)
        result = v.can_go_live(proposal.id, db=db)
        assert result["approved"] is True
        assert result["trade_count"] >= 10

    def test_rejects_low_win_rate(self, db):
        from backend.core.fronttest_validator import FronttestValidator

        proposal = StrategyProposal(
            strategy_name="bad_strat",
            change_details={"kelly_fraction": 0.1},
            expected_impact="test",
            admin_decision="executed",
            executed_at=datetime.now(timezone.utc) - timedelta(days=15),
        )
        db.add(proposal)
        db.commit()

        for i in range(12):
            db.add(Trade(
                strategy="bad_strat",
                trading_mode="paper",
                market_ticker=f"T{i}",
                direction="up",
                entry_price=0.5,
                size=10.0,
                result="win" if i < 3 else "loss",
                pnl=5.0 if i < 3 else -5.0,
                settled=True,
                timestamp=proposal.executed_at + timedelta(days=1, hours=i),
            ))
        db.commit()

        v = FronttestValidator(trial_days=14, min_trades=10)
        result = v.can_go_live(proposal.id, db=db)
        assert result["approved"] is False
        assert "win rate" in result["reason"].lower()


class TestAGIHealthChecker:
    def test_all_healthy_when_no_issues(self, db):
        from backend.core.agi_health_check import AGIHealthChecker

        bot = db.query(BotState).filter(BotState.mode == "paper").first()
        if not bot:
            bot = BotState(mode="paper", bankroll=1000.0, total_pnl=50.0, total_trades=10, winning_trades=6)
            db.add(bot)
            db.commit()
        else:
            bot.bankroll = 1000.0
            bot.total_pnl = 50.0
            db.commit()

        db.add(Trade(
            strategy="test",
            trading_mode="paper",
            market_ticker="TEST",
            direction="up",
            entry_price=0.5,
            size=10.0,
            settled=True,
            timestamp=datetime.now(timezone.utc),
        ))
        db.commit()

        checker = AGIHealthChecker()
        results = checker.run_checks(db=db)
        assert results["summary"]["total"] > 0

    def test_budget_depleted_flagged(self, db):
        from backend.core.agi_health_check import AGIHealthChecker

        bot = db.query(BotState).filter(BotState.mode == "paper").first()
        if not bot:
            bot = BotState(mode="paper", bankroll=0.0, total_pnl=-1000.0, total_trades=50)
            db.add(bot)
            db.commit()
        else:
            bot.bankroll = 0.0
            bot.total_pnl = -1000.0
            db.commit()

        checker = AGIHealthChecker()
        with patch.object(checker, "_check_scheduler", return_value={"healthy": True, "job_count": 5}):
            budget = checker._check_budget(db)

        assert budget["healthy"] is False


class TestStrategyRehabilitator:
    def test_rehabilitates_eligible_strategy(self, db):
        from backend.core.strategy_rehabilitator import StrategyRehabilitator

        cfg = StrategyConfig(
            strategy_name="old_strat",
            enabled=False,
            interval_seconds=300,
        )
        db.add(cfg)

        old_ts = datetime.now(timezone.utc) - timedelta(days=14)
        for i in range(12):
            db.add(Trade(
                strategy="old_strat",
                trading_mode="paper",
                market_ticker=f"T{i}",
                direction="up",
                entry_price=0.5,
                size=10.0,
                result="win" if i < 7 else "loss",
                pnl=5.0 if i < 7 else -3.0,
                settled=True,
                timestamp=old_ts - timedelta(hours=i),
            ))
        db.commit()

        rehab = StrategyRehabilitator()
        result = rehab.run(db=db)
        assert "old_strat" in result

    def test_skips_recently_disabled(self, db):
        from backend.core.strategy_rehabilitator import StrategyRehabilitator

        cfg = StrategyConfig(
            strategy_name="recent_strat",
            enabled=False,
            interval_seconds=300,
        )
        db.add(cfg)

        db.add(Trade(
            strategy="recent_strat",
            trading_mode="paper",
            market_ticker="T",
            direction="up",
            entry_price=0.5,
            size=10.0,
            settled=True,
            timestamp=datetime.now(timezone.utc) - timedelta(hours=1),
        ))
        db.commit()

        rehab = StrategyRehabilitator()
        result = rehab.run(db=db)
        assert "recent_strat" not in result


class TestForensicsIntegration:
    def test_creates_proposal_for_losing_strategy(self, db):
        from backend.core.forensics_integration import generate_forensics_proposals

        _seed_outcomes(db, "bleeding_strat", 2, 8)

        ids = generate_forensics_proposals(lookback_hours=168, min_losses=5, db=db)
        assert len(ids) >= 1

        proposal = db.query(StrategyProposal).filter(StrategyProposal.id == ids[0]).first()
        assert proposal.strategy_name == "bleeding_strat"
        assert proposal.status == "pending"

    def test_skips_when_no_losses(self, db):
        from backend.core.forensics_integration import generate_forensics_proposals

        _seed_outcomes(db, "winning_strat", 10, 0)

        ids = generate_forensics_proposals(lookback_hours=168, min_losses=5, db=db)
        assert len(ids) == 0


class TestHistoricalDataModels:
    def test_candle_model(self, db):
        candle = HistoricalCandle(
            source="binance",
            symbol="BTCUSDT",
            timestamp=datetime.now(timezone.utc),
            open=50000.0,
            high=50100.0,
            low=49900.0,
            close=50050.0,
            volume=100.0,
            interval="1m",
        )
        db.add(candle)
        db.commit()

        fetched = db.query(HistoricalCandle).first()
        assert fetched.symbol == "BTCUSDT"
        assert fetched.close == 50050.0

    def test_market_outcome_model(self, db):
        outcome = MarketOutcome(
            market_ticker="BTC_UP_MAY3",
            platform="polymarket",
            outcome="yes",
            final_price=0.85,
            volume=50000.0,
        )
        db.add(outcome)
        db.commit()

        fetched = db.query(MarketOutcome).first()
        assert fetched.platform == "polymarket"
        assert fetched.final_price == 0.85

    def test_weather_snapshot_model(self, db):
        snap = WeatherSnapshot(
            city="nyc",
            timestamp=datetime.now(timezone.utc),
            temperature_f=72.0,
            temperature_c=22.2,
            humidity=55.0,
            source="open-meteo",
        )
        db.add(snap)
        db.commit()

        fetched = db.query(WeatherSnapshot).first()
        assert fetched.city == "nyc"
        assert fetched.temperature_f == 72.0
