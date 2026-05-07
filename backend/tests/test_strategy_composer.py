
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.core.strategy_composer import (
    StrategyComposer,
    ComposedStrategy,
    StrategyBlock,
    BLOCK_CATALOG,
)
from backend.core.agi_types import MarketRegime
from backend.models.kg_models import Base, ExperimentRecord


def make_composer_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    composer = StrategyComposer(session=session)
    return composer, session, engine


class TestStrategyComposerCompose:
    def test_compose_creates_strategy(self):
        composer, _, _ = make_composer_session()
        blocks = [
            StrategyBlock(
                signal_source="whale_tracker_signal",
                filter="min_edge_005",
                position_sizer="kelly_sizer",
                risk_rule="max_1pct",
                exit_rule="take_profit_10pct",
            )
        ]
        result = composer.compose(blocks, name="whale_conservative")
        assert result.name == "whale_conservative"
        assert len(result.blocks) == 1
        assert result.status == "draft"

    def test_compose_multiple_blocks(self):
        composer, _, _ = make_composer_session()
        blocks = [
            StrategyBlock(
                signal_source="btc_momentum_signal",
                filter="min_confidence_07",
                position_sizer="fixed_01",
                risk_rule="max_2pct",
                exit_rule="stop_loss_5pct",
            ),
            StrategyBlock(
                signal_source="weather_signal",
                filter="volume_filter",
                position_sizer="half_kelly",
                risk_rule="daily_loss_5pct",
                exit_rule="trailing_stop_3pct",
            ),
        ]
        result = composer.compose(blocks, name="multi_signal")
        assert len(result.blocks) == 2


class TestStrategyComposerValidate:
    def test_validate_valid_composition(self):
        composer, _, _ = make_composer_session()
        blocks = [
            StrategyBlock(
                signal_source="whale_tracker_signal",
                filter="min_edge_005",
                position_sizer="kelly_sizer",
                risk_rule="max_1pct",
                exit_rule="take_profit_10pct",
            )
        ]
        composed = ComposedStrategy(name="valid", blocks=blocks)
        result = composer.validate_composition(composed)
        assert result.valid
        assert len(result.errors) == 0

    def test_validate_missing_risk_rule(self):
        composer, _, _ = make_composer_session()
        blocks = [
            StrategyBlock(
                signal_source="whale_tracker_signal",
                filter="min_edge_005",
                position_sizer="kelly_sizer",
                risk_rule="",
                exit_rule="take_profit_10pct",
            )
        ]
        composed = ComposedStrategy(name="no_risk", blocks=blocks)
        result = composer.validate_composition(composed)
        assert not result.valid
        assert any("risk_rule" in e for e in result.errors)

    def test_validate_missing_signal_source(self):
        composer, _, _ = make_composer_session()
        blocks = [
            StrategyBlock(
                signal_source="",
                filter="min_edge_005",
                position_sizer="kelly_sizer",
                risk_rule="max_1pct",
                exit_rule="take_profit_10pct",
            )
        ]
        composed = ComposedStrategy(name="no_signal", blocks=blocks)
        result = composer.validate_composition(composed)
        assert not result.valid
        assert any("signal_source" in e for e in result.errors)

    def test_validate_missing_position_sizer(self):
        composer, _, _ = make_composer_session()
        blocks = [
            StrategyBlock(
                signal_source="whale_tracker_signal",
                filter="min_edge_005",
                position_sizer="",
                risk_rule="max_1pct",
                exit_rule="take_profit_10pct",
            )
        ]
        composed = ComposedStrategy(name="no_sizer", blocks=blocks)
        result = composer.validate_composition(composed)
        assert not result.valid
        assert any("position_sizer" in e for e in result.errors)

    def test_validate_circular_reference(self):
        composer, _, _ = make_composer_session()
        blocks = [
            StrategyBlock(
                signal_source="whale_tracker_signal",
                filter="min_edge_005",
                position_sizer="kelly_sizer",
                risk_rule="max_1pct",
                exit_rule="take_profit_10pct",
            ),
            StrategyBlock(
                signal_source="whale_tracker_signal",
                filter="volume_filter",
                position_sizer="fixed_01",
                risk_rule="max_2pct",
                exit_rule="stop_loss_5pct",
            ),
        ]
        composed = ComposedStrategy(name="circular", blocks=blocks)
        result = composer.validate_composition(composed)
        assert not result.valid
        assert any("circular" in e for e in result.errors)

    def test_validate_invalid_signal_source(self):
        composer, _, _ = make_composer_session()
        blocks = [
            StrategyBlock(
                signal_source="invalid_source",
                filter="min_edge_005",
                position_sizer="kelly_sizer",
                risk_rule="max_1pct",
                exit_rule="take_profit_10pct",
            )
        ]
        composed = ComposedStrategy(name="invalid", blocks=blocks)
        result = composer.validate_composition(composed)
        assert not result.valid
        assert any("invalid_signal_source" in e for e in result.errors)

    def test_validate_no_blocks(self):
        composer, _, _ = make_composer_session()
        composed = ComposedStrategy(name="empty", blocks=[])
        result = composer.validate_composition(composed)
        assert not result.valid
        assert any("no_blocks" in e for e in result.errors)


class TestStrategyComposerBacktest:
    def test_backtest_composed_returns_result(self):
        composer, _, _ = make_composer_session()
        blocks = [
            StrategyBlock(
                signal_source="whale_tracker_signal",
                filter="min_edge_005",
                position_sizer="kelly_sizer",
                risk_rule="max_1pct",
                exit_rule="take_profit_10pct",
            )
        ]
        composed = composer.compose(blocks, name="test_backtest")
        result = composer.backtest_composed(composed, MarketRegime.BULL)
        assert result.strategy_name == "test_backtest"
        assert result.regime == "bull"
        assert result.trades == 0
        assert result.win_rate == 0.0


class TestStrategyComposerRegister:
    def test_register_composed_returns_id(self):
        composer, session, _ = make_composer_session()
        blocks = [
            StrategyBlock(
                signal_source="whale_tracker_signal",
                filter="min_edge_005",
                position_sizer="kelly_sizer",
                risk_rule="max_1pct",
                exit_rule="take_profit_10pct",
            )
        ]
        composed = composer.compose(blocks, name="whale_conservative")
        experiment_id = composer.register_composed(composed)
        assert experiment_id is not None
        assert len(experiment_id) > 0
        assert composed.status == "shadow"
        assert composed.experiment_id == experiment_id

    def test_register_stored_in_experiment_record(self):
        composer, session, _ = make_composer_session()
        blocks = [
            StrategyBlock(
                signal_source="btc_momentum_signal",
                filter="min_confidence_07",
                position_sizer="fixed_01",
                risk_rule="max_2pct",
                exit_rule="take_profit_20pct",
            )
        ]
        composed = composer.compose(blocks, name="btc_momentum")
        experiment_id = composer.register_composed(composed)
        record = session.query(ExperimentRecord).filter_by(id=int(experiment_id)).first()
        assert record is not None
        assert record.name == "btc_momentum"
        assert record.status == "shadow"

    def test_register_invalid_composition_raises(self):
        composer, _, _ = make_composer_session()
        blocks = []
        composed = ComposedStrategy(name="invalid", blocks=blocks)
        with pytest.raises(ValueError, match="Cannot register"):
            composer.register_composed(composed)


class TestBLOCKCATALOG:
    def test_catalog_has_all_block_types(self):
        assert "signal_source" in BLOCK_CATALOG
        assert "filter" in BLOCK_CATALOG
        assert "position_sizer" in BLOCK_CATALOG
        assert "risk_rule" in BLOCK_CATALOG
        assert "exit_rule" in BLOCK_CATALOG

    def test_catalog_signal_sources_valid(self):
        assert "whale_tracker_signal" in BLOCK_CATALOG["signal_source"]
        assert "btc_momentum_signal" in BLOCK_CATALOG["signal_source"]

    def test_catalog_risk_rules_valid(self):
        assert "max_1pct" in BLOCK_CATALOG["risk_rule"]
        assert "daily_loss_5pct" in BLOCK_CATALOG["risk_rule"]
