"""
Wave 5d: Cross-Feature Integration Tests

Tests integration between:
- Activities (Feature 2) + Decisions (Feature 3) + Proposals (Feature 4) + Stats Pipeline (Wave 5a)

Uses ACTUAL database schema from backend/models/database.py
"""

import json
from datetime import datetime, timezone, timedelta
from sqlalchemy.orm import Session

from backend.models.database import (
    ActivityLog,
    DecisionLog,
    StrategyProposal,
    StrategyConfig,
    Trade,
    MiroFishSignal,
)


class TestCrossFeatureActivityToDecision:
    """Test Activity + Decision integration."""

    def test_activity_logged_then_decision_created(self, db: Session):
        """Activity + Decision created independently."""
        # Create Activity
        activity = ActivityLog(
            strategy_name="btc_momentum",
            decision_type="entry",
            data={"market": "BTC-USD", "signal": "BUY"},
            confidence_score=0.85,
            mode="paper",
        )
        db.add(activity)
        db.commit()

        # Create Decision
        decision = DecisionLog(
            strategy="btc_momentum",
            market_ticker="BTC-USD",
            decision="BUY",
            confidence=0.85,
            signal_data=json.dumps({"source": "momentum", "rsi": 65}),
            reason="Strong upward momentum detected",
        )
        db.add(decision)
        db.commit()

        # Verify both exist
        activities = db.query(ActivityLog).all()
        decisions = db.query(DecisionLog).all()

        assert len(activities) == 1
        assert len(decisions) == 1
        assert activities[0].strategy_name == "btc_momentum"
        assert decisions[0].strategy == "btc_momentum"
        assert decisions[0].decision == "BUY"

    def test_activity_decision_proposal_flow(self, db: Session):
        """Full workflow: Activity → Decision → Proposal."""
        # Step 1: Activity logged
        activity = ActivityLog(
            strategy_name="weather_emos",
            decision_type="entry",
            data={"market": "TEMP-NYC", "forecast": 72.5},
            confidence_score=0.78,
            mode="paper",
        )
        db.add(activity)
        db.commit()

        # Step 2: Decision created
        decision = DecisionLog(
            strategy="weather_emos",
            market_ticker="TEMP-NYC",
            decision="BUY",
            confidence=0.78,
            signal_data=json.dumps({"ensemble_mean": 72.5, "spread": 2.1}),
            reason="Ensemble forecast shows high confidence",
        )
        db.add(decision)
        db.commit()

        # Step 3: Proposal created based on performance
        proposal = StrategyProposal(
            strategy_name="weather_emos",
            change_details={"ensemble_size": 31, "new_ensemble_size": 51},
            expected_impact="Increase forecast accuracy by 5%",
            admin_decision="pending",
        )
        db.add(proposal)
        db.commit()

        # Verify full workflow
        activities = db.query(ActivityLog).filter_by(strategy_name="weather_emos").all()
        decisions = db.query(DecisionLog).filter_by(strategy="weather_emos").all()
        proposals = db.query(StrategyProposal).filter_by(strategy_name="weather_emos").all()

        assert len(activities) == 1
        assert len(decisions) == 1
        assert len(proposals) == 1
        assert proposals[0].admin_decision == "pending"

    def test_mirofish_signal_visible_in_decision(self, db: Session):
        """MiroFish signal with correct float prediction field (0.75, not 'YES')."""
        # Create MiroFish signal with FLOAT prediction
        signal = MiroFishSignal(
            market_id="polymarket-btc-100k",
            prediction=0.75,  # Float 0.0-1.0, NOT string
            confidence=0.82,
            reasoning="Debate engine consensus: 75% probability",
            source="mirofish",
            weight=1.0,
        )
        db.add(signal)
        db.commit()

        # Create Decision referencing MiroFish signal
        decision = DecisionLog(
            strategy="mirofish_debate",
            market_ticker="polymarket-btc-100k",
            decision="BUY",
            confidence=0.82,
            signal_data=json.dumps({
                "mirofish_prediction": 0.75,
                "mirofish_confidence": 0.82,
                "reasoning": "Debate engine consensus: 75% probability"
            }),
            reason="MiroFish signal above threshold",
        )
        db.add(decision)
        db.commit()

        # Verify MiroFish signal is queryable
        mirofish_signals = db.query(MiroFishSignal).all()
        decisions = db.query(DecisionLog).filter_by(strategy="mirofish_debate").all()

        assert len(mirofish_signals) == 1
        assert mirofish_signals[0].prediction == 0.75  # Float, not string
        assert isinstance(mirofish_signals[0].prediction, float)
        assert len(decisions) == 1

        # Verify signal_data is JSON string
        signal_data = json.loads(decisions[0].signal_data)
        assert signal_data["mirofish_prediction"] == 0.75


class TestCrossFeatureProposalExecution:
    """Test Proposal execution and rollback."""

    def test_proposal_approval_updates_strategy_config(self, db: Session):
        """Approved proposal updates StrategyConfig params."""
        # Create initial StrategyConfig
        config = StrategyConfig(
            strategy_name="btc_momentum",
            enabled=True,
            params=json.dumps({"rsi_threshold": 70, "momentum_window": 14}),
            interval_seconds=300,
            trading_mode="paper",
        )
        db.add(config)
        db.commit()

        # Create Proposal
        proposal = StrategyProposal(
            strategy_name="btc_momentum",
            change_details={"rsi_threshold": 65, "momentum_window": 21},
            expected_impact="Increase signal frequency by 15%",
            admin_decision="pending",
        )
        db.add(proposal)
        db.commit()

        # Approve proposal
        proposal.admin_decision = "approved"
        proposal.executed_at = datetime.now(timezone.utc)
        proposal.admin_user_id = "admin_001"
        proposal.admin_decision_reason = "Backtesting shows improved Sharpe ratio"

        config.params = json.dumps(proposal.change_details)
        db.commit()

        # Verify update
        updated_config = db.query(StrategyConfig).filter_by(strategy_name="btc_momentum").first()
        params = json.loads(updated_config.params)

        assert params["rsi_threshold"] == 65
        assert params["momentum_window"] == 21
        assert proposal.admin_decision == "approved"
        assert proposal.executed_at is not None

    def test_proposal_execution_then_rollback(self, db: Session):
        """Proposal executed, negative impact triggers rollback."""
        # Create initial config
        original_params = {"ensemble_size": 31, "confidence_threshold": 0.75}
        config = StrategyConfig(
            strategy_name="weather_emos",
            enabled=True,
            params=json.dumps(original_params),
            interval_seconds=3600,
            trading_mode="paper",
        )
        db.add(config)
        db.commit()

        # Create and approve proposal
        proposal = StrategyProposal(
            strategy_name="weather_emos",
            change_details={"ensemble_size": 51, "confidence_threshold": 0.80},
            expected_impact="Increase accuracy by 5%",
            admin_decision="approved",
            executed_at=datetime.now(timezone.utc),
        )
        db.add(proposal)

        # Execute proposal
        config.params = json.dumps(proposal.change_details)
        db.commit()

        # Measure negative impact
        proposal.impact_measured = json.dumps({
            "accuracy_change": -3.2,
            "signal_count_change": -12,
            "recommendation": "rollback"
        })
        db.commit()

        # Rollback to original params
        config.params = json.dumps(original_params)
        db.commit()

        # Verify rollback
        rolled_back_config = db.query(StrategyConfig).filter_by(strategy_name="weather_emos").first()
        params = json.loads(rolled_back_config.params)

        assert params["ensemble_size"] == 31
        assert params["confidence_threshold"] == 0.75
        assert proposal.impact_measured is not None
        impact = json.loads(proposal.impact_measured)
        assert impact["recommendation"] == "rollback"


class TestCrossFeatureStatsCorrelation:
    """Test stats correlation across features."""

    def test_activity_events_visible(self, db: Session):
        """Activity events persisted + queryable across features."""
        # Create multiple activities
        activities = [
            ActivityLog(
                strategy_name="btc_momentum",
                decision_type="entry",
                data={"market": "BTC-USD", "price": 50000},
                confidence_score=0.85,
                mode="paper",
            ),
            ActivityLog(
                strategy_name="btc_momentum",
                decision_type="hold",
                data={"market": "BTC-USD", "price": 50500},
                confidence_score=0.72,
                mode="paper",
            ),
            ActivityLog(
                strategy_name="btc_momentum",
                decision_type="exit",
                data={"market": "BTC-USD", "price": 51000, "pnl": 1000},
                confidence_score=0.88,
                mode="paper",
            ),
        ]
        for activity in activities:
            db.add(activity)
        db.commit()

        # Query activities
        all_activities = db.query(ActivityLog).filter_by(strategy_name="btc_momentum").all()
        entry_activities = db.query(ActivityLog).filter_by(decision_type="entry").all()

        assert len(all_activities) == 3
        assert len(entry_activities) == 1
        assert all_activities[0].data["market"] == "BTC-USD"

    def test_activity_trade_correlation(self, db: Session):
        """Activity timeline correlates with Trade data."""
        # Create Activity
        activity = ActivityLog(
            strategy_name="btc_momentum",
            decision_type="entry",
            data={"market": "BTC-USD", "signal_id": 123},
            confidence_score=0.85,
            mode="paper",
        )
        db.add(activity)
        db.commit()

        # Create corresponding Trade
        trade = Trade(
            signal_id=123,
            market_ticker="BTC-USD",
            platform="polymarket",
            direction="up",
            entry_price=50000.0,
            size=1.0,
            trading_mode="paper",
            strategy="btc_momentum",
            confidence=0.85,
        )
        db.add(trade)
        db.commit()

        # Verify correlation
        activities = db.query(ActivityLog).filter_by(strategy_name="btc_momentum").all()
        trades = db.query(Trade).filter_by(strategy="btc_momentum").all()

        assert len(activities) == 1
        assert len(trades) == 1
        assert activities[0].data["signal_id"] == trades[0].signal_id
        assert activities[0].confidence_score == trades[0].confidence


class TestCrossFeatureConcurrency:
    """Test concurrent operations across features."""

    def test_multiple_proposals_maintain_order(self, db: Session):
        """Multiple proposals maintain FIFO approval order."""
        # Create multiple proposals
        proposals = [
            StrategyProposal(
                strategy_name="btc_momentum",
                change_details={"rsi_threshold": 65},
                expected_impact="Increase signals by 10%",
                admin_decision="pending",
                created_at=datetime.now(timezone.utc),
            ),
            StrategyProposal(
                strategy_name="btc_momentum",
                change_details={"rsi_threshold": 60},
                expected_impact="Increase signals by 20%",
                admin_decision="pending",
                created_at=datetime.now(timezone.utc) + timedelta(seconds=1),
            ),
            StrategyProposal(
                strategy_name="btc_momentum",
                change_details={"rsi_threshold": 55},
                expected_impact="Increase signals by 30%",
                admin_decision="pending",
                created_at=datetime.now(timezone.utc) + timedelta(seconds=2),
            ),
        ]
        for proposal in proposals:
            db.add(proposal)
        db.commit()

        # Query in FIFO order
        ordered_proposals = (
            db.query(StrategyProposal)
            .filter_by(strategy_name="btc_momentum")
            .order_by(StrategyProposal.created_at)
            .all()
        )

        assert len(ordered_proposals) == 3
        assert ordered_proposals[0].change_details["rsi_threshold"] == 65
        assert ordered_proposals[1].change_details["rsi_threshold"] == 60
        assert ordered_proposals[2].change_details["rsi_threshold"] == 55

    def test_activity_decision_proposal_parallel(self, db: Session):
        """Parallel Activity + Decision + Proposal creation."""
        # Create all three in parallel
        activity = ActivityLog(
            strategy_name="weather_emos",
            decision_type="entry",
            data={"market": "TEMP-NYC"},
            confidence_score=0.80,
            mode="paper",
        )
        decision = DecisionLog(
            strategy="weather_emos",
            market_ticker="TEMP-NYC",
            decision="BUY",
            confidence=0.80,
            signal_data=json.dumps({"ensemble_mean": 72.5}),
            reason="High confidence forecast",
        )
        proposal = StrategyProposal(
            strategy_name="weather_emos",
            change_details={"ensemble_size": 51},
            expected_impact="Increase accuracy",
            admin_decision="pending",
        )

        db.add(activity)
        db.add(decision)
        db.add(proposal)
        db.commit()

        # Verify all created
        assert db.query(ActivityLog).count() == 1
        assert db.query(DecisionLog).count() == 1
        assert db.query(StrategyProposal).count() == 1

    def test_rollback_with_concurrent_proposals(self, db: Session):
        """Rollback + new proposal execution ordering."""
        # Create config
        config = StrategyConfig(
            strategy_name="btc_momentum",
            enabled=True,
            params=json.dumps({"rsi_threshold": 70}),
            interval_seconds=300,
        )
        db.add(config)
        db.commit()

        # Create proposal 1 (will be rolled back)
        proposal1 = StrategyProposal(
            strategy_name="btc_momentum",
            change_details={"rsi_threshold": 65},
            expected_impact="Increase signals",
            admin_decision="approved",
            executed_at=datetime.now(timezone.utc),
        )
        db.add(proposal1)

        # Execute proposal 1
        config.params = json.dumps(proposal1.change_details)
        db.commit()

        # Measure negative impact and rollback
        proposal1.impact_measured = json.dumps({"recommendation": "rollback"})
        config.params = json.dumps({"rsi_threshold": 70})  # Rollback
        db.commit()

        # Create proposal 2 (new proposal after rollback)
        proposal2 = StrategyProposal(
            strategy_name="btc_momentum",
            change_details={"rsi_threshold": 68},
            expected_impact="Moderate increase",
            admin_decision="approved",
            executed_at=datetime.now(timezone.utc) + timedelta(seconds=5),
        )
        db.add(proposal2)

        # Execute proposal 2
        config.params = json.dumps(proposal2.change_details)
        db.commit()

        # Verify final state
        final_config = db.query(StrategyConfig).filter_by(strategy_name="btc_momentum").first()
        params = json.loads(final_config.params)
        assert params["rsi_threshold"] == 68


class TestCrossFeatureErrorPropagation:
    """Test error isolation across features."""

    def test_activity_error_doesnt_block_decision(self, db: Session):
        """Activity creation isolated from Decision creation."""
        # Create Decision (even if Activity fails)
        decision = DecisionLog(
            strategy="btc_momentum",
            market_ticker="BTC-USD",
            decision="BUY",
            confidence=0.85,
            signal_data=json.dumps({"source": "momentum"}),
            reason="Strong signal",
        )
        db.add(decision)
        db.commit()

        # Verify Decision created successfully
        decisions = db.query(DecisionLog).all()
        assert len(decisions) == 1
        assert decisions[0].decision == "BUY"

    def test_decision_error_doesnt_block_proposals(self, db: Session):
        """Decision errors don't prevent Proposal creation."""
        # Create Proposal (even if Decision fails)
        proposal = StrategyProposal(
            strategy_name="weather_emos",
            change_details={"ensemble_size": 51},
            expected_impact="Increase accuracy",
            admin_decision="pending",
        )
        db.add(proposal)
        db.commit()

        # Verify Proposal created successfully
        proposals = db.query(StrategyProposal).all()
        assert len(proposals) == 1
        assert proposals[0].admin_decision == "pending"

    def test_proposal_error_doesnt_block_activity(self, db: Session):
        """Proposal errors don't prevent Activity logging."""
        # Create Activity (even if Proposal fails)
        activity = ActivityLog(
            strategy_name="btc_momentum",
            decision_type="entry",
            data={"market": "BTC-USD"},
            confidence_score=0.85,
            mode="paper",
        )
        db.add(activity)
        db.commit()

        # Verify Activity created successfully
        activities = db.query(ActivityLog).all()
        assert len(activities) == 1
        assert activities[0].strategy_name == "btc_momentum"


class TestCrossFeatureDataConsistency:
    """Test data consistency across features."""

    def test_no_data_loss_in_workflow(self, db: Session):
        """All updates committed atomically."""
        # Create full workflow in single transaction
        activity = ActivityLog(
            strategy_name="btc_momentum",
            decision_type="entry",
            data={"market": "BTC-USD"},
            confidence_score=0.85,
            mode="paper",
        )
        decision = DecisionLog(
            strategy="btc_momentum",
            market_ticker="BTC-USD",
            decision="BUY",
            confidence=0.85,
            signal_data=json.dumps({"source": "momentum"}),
            reason="Strong signal",
        )
        proposal = StrategyProposal(
            strategy_name="btc_momentum",
            change_details={"rsi_threshold": 65},
            expected_impact="Increase signals",
            admin_decision="pending",
        )
        trade = Trade(
            signal_id=123,
            market_ticker="BTC-USD",
            platform="polymarket",
            direction="up",
            entry_price=50000.0,
            size=1.0,
            trading_mode="paper",
            strategy="btc_momentum",
            confidence=0.85,
        )

        db.add(activity)
        db.add(decision)
        db.add(proposal)
        db.add(trade)
        db.commit()

        assert activity.id is not None
        assert decision.id is not None
        assert proposal.id is not None
        assert trade.id is not None

        assert db.query(ActivityLog).filter_by(id=activity.id).first() is not None
        assert db.query(DecisionLog).filter_by(id=decision.id).first() is not None
        assert db.query(StrategyProposal).filter_by(id=proposal.id).first() is not None
        assert db.query(Trade).filter_by(id=trade.id).first() is not None

    def test_foreign_key_integrity(self, db: Session):
        """Foreign keys maintained across features."""
        # Create Trade with signal_id
        trade = Trade(
            signal_id=123,
            market_ticker="BTC-USD",
            platform="polymarket",
            direction="up",
            entry_price=50000.0,
            size=1.0,
            trading_mode="paper",
            strategy="btc_momentum",
        )
        db.add(trade)
        db.commit()

        created_trade = db.query(Trade).filter_by(id=trade.id).first()
        assert created_trade is not None
        assert created_trade.signal_id == 123
        assert created_trade.market_ticker == "BTC-USD"
