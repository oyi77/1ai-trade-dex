"""Tests for AGI test fixtures — verify all fixtures load correctly."""

from backend.tests.test_agi_integration_base import AGIIntegrationBase


class TestFixtureImports:
    def test_regime_data_bull(self, regime_data_bull):
        assert regime_data_bull["sma_50"] > regime_data_bull["sma_200"]
        assert regime_data_bull["atr_percentile"] < 0.5
        assert len(regime_data_bull["prices"]) >= 200

    def test_regime_data_bear(self, regime_data_bear):
        assert regime_data_bear["sma_50"] < regime_data_bear["sma_200"]
        assert regime_data_bear["atr_percentile"] > 0.5

    def test_regime_data_sideways(self, regime_data_sideways):
        assert abs(regime_data_sideways["sma_50"] - regime_data_sideways["sma_200"]) / regime_data_sideways["sma_200"] < 0.02

    def test_regime_data_crisis(self, regime_data_crisis):
        assert regime_data_crisis["drawdown"] > 0.15
        assert regime_data_crisis["atr_percentile"] > 0.9

    def test_sample_kg_entity(self, sample_kg_entity):
        assert sample_kg_entity.entity_type == "strategy"
        assert sample_kg_entity.entity_id == "btc_momentum"
        assert sample_kg_entity.properties["win_rate"] == 0.65

    def test_sample_kg_relation(self, sample_kg_relation):
        assert sample_kg_relation.from_entity == "btc_momentum"
        assert sample_kg_relation.to_entity == "bull_regime"
        assert sample_kg_relation.relation_type == "performs_well_in"

    def test_sample_strategy_block(self, sample_strategy_block):
        assert sample_strategy_block.signal_source == "whale_tracker"
        assert sample_strategy_block.filter == "min_volume_1000"

    def test_mock_llm_response(self, mock_llm_response):
        assert "strategy_code" in mock_llm_response
        assert "cost_usd" in mock_llm_response
        assert mock_llm_response["cost_usd"] > 0

    def test_mock_market_data(self, mock_market_data):
        assert len(mock_market_data["prices"]) >= 200
        assert mock_market_data["sma_50"] > mock_market_data["sma_200"]

    def test_agi_db_fixture(self, agi_db):
        from backend.models.kg_models import KGEntity as KGEntityModel
        entity = KGEntityModel(entity_type="test", entity_id="test_entity", properties={"key": "value"})
        agi_db.add(entity)
        agi_db.commit()
        fetched = agi_db.query(KGEntityModel).first()
        assert fetched.entity_id == "test_entity"


class TestShadowModeFixture:
    def test_shadow_mode_enforced(self, shadow_mode_settings):
        from backend.config import settings
        assert settings.ACTIVE_MODES == "paper"


class TestRiskBoundingFixture:
    def test_risk_bounding_settings(self, risk_bounding_settings):
        from backend.config import settings
        assert settings.MAX_TRADE_SIZE == 50.0
        assert settings.DAILY_LOSS_LIMIT == 100.0
        assert settings.KELLY_FRACTION == 0.5


class TestIntegrationBase:
    def test_shadow_mode_assertion(self):
        base = AGIIntegrationBase()

        class MockSettings:
            SHADOW_MODE = True

        base.assert_shadow_mode_enforced(MockSettings())

    def test_kg_integrity_assertion(self):
        from backend.core.knowledge_graph import KnowledgeGraph
        base = AGIIntegrationBase()
        kg = KnowledgeGraph()
        kg.add_entity("strategy", "test_strat", {"win_rate": 0.6})
        base.assert_kg_data_not_corrupted(kg, "test_strat")
