"""Tests for GenomeCompiler - comprehensive edge case coverage."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from typing import Dict, Any

from backend.application.strategy.genome_compiler import (
    GenomeStrategy,
    compile_genome,
    DEFAULT_KELLY_FRACTION,
    DEFAULT_MAX_POSITION_FRACTION,
    DEFAULT_MAX_EXPOSURE_FRACTION,
    DEFAULT_MIN_CONFIDENCE,
    DEFAULT_TRIGGER_TYPE,
    DEFAULT_BANKROLL,
    DEFAULT_MAX_TRADE_SIZE,
    DEFAULT_CONFIDENCE_BASELINE,
    MARKET_LIMIT,
    TOP_MARKETS_TO_PROCESS
)
from backend.domain.genome.models import StrategyGenome
from backend.strategies.base import StrategyContext, CycleResult, MarketInfo


class TestGenomeCompiler:
    """Comprehensive tests for GenomeCompiler functionality."""

    @pytest.fixture
    def valid_genome(self) -> StrategyGenome:
        """Create a valid genome for testing."""
        return StrategyGenome(
            genome_id="test-genome-123",
            strategy_name="test_genome_strategy",
            archetype="test_archetype",
            chromosomes={
                "perception": {"indicators": ["rsi", "volume"]},
                "cognition": {
                    "entry_logic": {
                        "trigger_type": "threshold_cross",
                        "conditions": [
                            {"indicator": "rsi", "operator": ">", "value": 0.5, "weight": 1.0}
                        ],
                        "min_confidence": 0.6
                    }
                },
                "execution": {"order_type": "limit"},
                "risk": {
                    "kelly_fraction": 0.3,
                    "max_position_fraction": 0.1,
                    "max_total_exposure_fraction": 0.8
                },
                "meta": {"self_optimization_enabled": True}
            }
        )

    @pytest.fixture
    def mock_context(self) -> StrategyContext:
        """Create a mock strategy context."""
        ctx = MagicMock(spec=StrategyContext)
        ctx.db = MagicMock()
        ctx.bankroll = 2000.0
        return ctx

    def test_genome_strategy_initialization_valid_genome(self, valid_genome):
        """Test successful initialization with valid genome."""
        strategy = GenomeStrategy(valid_genome)

        assert strategy.genome == valid_genome
        assert strategy.name == f"genome_{valid_genome.genome_id[:8]}"
        assert strategy.description == f"Auto-evolved {valid_genome.archetype} strategy"
        assert strategy.category == valid_genome.archetype
        assert isinstance(strategy.default_params, dict)

    def test_genome_strategy_properties_computed_correctly(self, valid_genome):
        """Test that properties are computed correctly from genome."""
        strategy = GenomeStrategy(valid_genome)

        expected_name = f"genome_{valid_genome.genome_id[:8]}"
        expected_description = f"Auto-evolved {valid_genome.archetype} strategy"
        expected_category = valid_genome.archetype

        assert strategy.name == expected_name
        assert strategy.description == expected_description
        assert strategy.category == expected_category

    def test_chromosome_normalization_handles_pydantic_models(self, valid_genome):
        """Test that chromosome normalization works with Pydantic models."""
        # Mock a Pydantic model
        mock_pydantic = MagicMock()
        mock_pydantic.model_dump.return_value = {"test": "data"}

        genome_with_pydantic = StrategyGenome(
            genome_id="test-123",
            strategy_name="test_strategy",
            archetype="test",
            chromosomes=mock_pydantic
        )

        strategy = GenomeStrategy(genome_with_pydantic)
        assert strategy._chromosomes == {"test": "data"}

    def test_chromosome_normalization_handles_plain_dicts(self, valid_genome):
        """Test that chromosome normalization works with plain dicts."""
        plain_dict_chromosomes = {"perception": {"test": "value"}}
        genome_with_dict = StrategyGenome(
            genome_id="test-123",
            strategy_name="test_strategy",
            archetype="test",
            chromosomes=plain_dict_chromosomes
        )

        strategy = GenomeStrategy(genome_with_dict)
        assert strategy._chromosomes == plain_dict_chromosomes

    def test_chromosome_normalization_handles_unexpected_types(self, caplog):
        """Test that unexpected chromosome types are handled gracefully."""
        genome_with_invalid = StrategyGenome(
            genome_id="test-123",
            strategy_name="test_strategy",
            archetype="test",
            chromosomes="invalid_string"  # Not a dict or Pydantic model
        )

        with caplog.at_level("WARNING"):
            strategy = GenomeStrategy(genome_with_invalid)

        assert strategy._chromosomes == {}
        assert "Unexpected chromosome type" in caplog.text

    def test_normalize_chromosome_section_handles_all_types(self):
        """Test _normalize_chromosome_section handles various input types."""
        genome = StrategyGenome(
            genome_id="test-123",
            strategy_name="test_strategy",
            archetype="test",
            chromosomes={}
        )
        strategy = GenomeStrategy(genome)

        # Test None
        assert strategy._normalize_chromosome_section(None) == {}

        # Test dict
        assert strategy._normalize_chromosome_section({"key": "value"}) == {"key": "value"}

        # Test Pydantic model
        mock_model = MagicMock()
        mock_model.model_dump.return_value = {"pydantic": "data"}
        assert strategy._normalize_chromosome_section(mock_model) == {"pydantic": "data"}

        # Test convertible object
        class Convertible:
            def __iter__(self):
                return iter([("a", 1), ("b", 2)])

        assert strategy._normalize_chromosome_section(Convertible()) == {"a": 1, "b": 2}

    def test_normalize_chromosome_section_logs_warnings(self, caplog):
        """Test that _normalize_chromosome_section logs warnings for failures."""
        genome = StrategyGenome(
            genome_id="test-123",
            strategy_name="test_strategy",
            archetype="test",
            chromosomes={}
        )
        strategy = GenomeStrategy(genome)

        # Test Pydantic model that fails
        mock_model = MagicMock()
        mock_model.model_dump.side_effect = Exception("Model dump failed")

        with caplog.at_level("WARNING"):
            result = strategy._normalize_chromosome_section(mock_model)

        assert result == {}
        assert "Failed to normalize chromosome section" in caplog.text

    def test_build_params_uses_defaults_when_missing(self, valid_genome):
        """Test that _build_params uses defaults when chromosome data is missing."""
        # Create genome with minimal chromosomes
        minimal_genome = StrategyGenome(
            genome_id="test-123",
            strategy_name="test_strategy",
            archetype="test",
            chromosomes={
                "perception": {},
                "cognition": {},
                "execution": {},
                "risk": {},  # Empty risk section
                "meta": {}
            }
        )

        strategy = GenomeStrategy(minimal_genome)
        params = strategy._build_params()

        # Should use defaults
        assert params["kelly_fraction"] == DEFAULT_KELLY_FRACTION
        assert params["max_position_fraction"] == DEFAULT_MAX_POSITION_FRACTION
        assert params["max_total_exposure_fraction"] == DEFAULT_MAX_EXPOSURE_FRACTION

    def test_build_params_uses_chromosome_values(self, valid_genome):
        """Test that _build_params uses chromosome values when present."""
        strategy = GenomeStrategy(valid_genome)
        params = strategy._build_params()

        # Should use chromosome values
        assert params["kelly_fraction"] == 0.3
        assert params["max_position_fraction"] == 0.1
        assert params["max_total_exposure_fraction"] == 0.8

    @pytest.mark.asyncio
    async def test_fetch_markets_handles_empty_response(self, valid_genome, mock_context):
        """Test that _fetch_markets handles empty API responses."""
        strategy = GenomeStrategy(valid_genome)

        # Mock fetch_markets to return empty list
        with patch('backend.data.gamma.fetch_markets', new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = []

            markets = await strategy._fetch_markets(mock_context)
            assert markets == []

    @pytest.mark.asyncio
    async def test_fetch_markets_handles_malformed_data(self, valid_genome, mock_context, caplog):
        """Test that _fetch_markets handles malformed market data gracefully."""
        strategy = GenomeStrategy(valid_genome)

        # Mock fetch_markets to return malformed data
        malformed_data = [
            {"ticker": "TEST", "slug": "test", "category": "test"},  # Missing outcomePrices
            {"ticker": "TEST2", "outcomePrices": "not_a_list"},  # Invalid outcomePrices
            {"ticker": "TEST3", "outcomePrices": [0.6]},  # Only one price
        ]

        with patch('backend.data.gamma.fetch_markets', new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = malformed_data

            with caplog.at_level("WARNING"):
                markets = await strategy._fetch_markets(mock_context)

            # Should handle all cases gracefully
            assert len(markets) == 3
            for market in markets:
                assert isinstance(market, MarketInfo)
                assert market.yes_price == DEFAULT_CONFIDENCE_BASELINE
                assert market.no_price == DEFAULT_CONFIDENCE_BASELINE

    @pytest.mark.asyncio
    async def test_fetch_markets_logs_exceptions(self, valid_genome, mock_context, caplog):
        """Test that _fetch_markets logs exceptions appropriately."""
        strategy = GenomeStrategy(valid_genome)

        with patch('backend.data.gamma.fetch_markets', new_callable=AsyncMock) as mock_fetch:
            mock_fetch.side_effect = Exception("API Error")

            with caplog.at_level("WARNING"):
                markets = await strategy._fetch_markets(mock_context)

            assert markets == []
            assert "Failed to fetch markets" in caplog.text

    def test_evaluate_market_returns_none_for_missing_cognition(self, valid_genome, mock_context):
        """Test that _evaluate_market returns None when cognition is missing."""
        # Create genome with empty cognition
        genome_no_cognition = StrategyGenome(
            genome_id="test-123",
            strategy_name="test_strategy",
            archetype="test",
            chromosomes={
                "perception": {},
                "cognition": {},  # Empty cognition
                "execution": {},
                "risk": {},
                "meta": {}
            }
        )

        strategy = GenomeStrategy(genome_no_cognition)
        market = MarketInfo(
            ticker="TEST",
            slug="test",
            category="test",
            end_date=None,
            volume=1000.0,
            liquidity=500.0,
            yes_price=0.6,
            no_price=0.4,
            metadata={}
        )

        result = strategy._evaluate_market(market, mock_context)
        assert result is None

    def test_evaluate_market_returns_none_for_low_confidence(self, valid_genome, mock_context):
        """Test that _evaluate_market returns None when confidence is too low."""
        strategy = GenomeStrategy(valid_genome)
        market = MarketInfo(
            ticker="TEST",
            slug="test",
            category="test",
            end_date=None,
            volume=1000.0,
            liquidity=500.0,
            yes_price=0.3,  # Very low probability
            no_price=0.7,
            metadata={}
        )

        result = strategy._evaluate_market(market, mock_context)
        assert result is None  # Confidence too low

    def test_evaluate_market_returns_signal_for_valid_conditions(self, valid_genome, mock_context):
        """Test that _evaluate_market returns a signal for valid market conditions."""
        strategy = GenomeStrategy(valid_genome)
        market = MarketInfo(
            ticker="TEST",
            slug="test",
            category="test",
            end_date=None,
            volume=1000.0,
            liquidity=500.0,
            yes_price=0.7,  # High probability
            no_price=0.3,
            metadata={}
        )

        result = strategy._evaluate_market(market, mock_context)

        assert result is not None
        assert isinstance(result, dict)
        assert result["decision"] == "BUY"
        assert result["market_ticker"] == "TEST"
        assert "confidence" in result
        assert "size" in result

    def test_calculate_confidence_handles_empty_conditions(self, valid_genome):
        """Test that _calculate_confidence handles empty conditions."""
        strategy = GenomeStrategy(valid_genome)
        market = MarketInfo(
            ticker="TEST",
            slug="test",
            category="test",
            end_date=None,
            volume=1000.0,
            liquidity=500.0,
            yes_price=0.5,
            no_price=0.5,
            metadata={}
        )

        confidence = strategy._calculate_confidence(market, [])
        assert confidence == 0.5  # Baseline confidence

    def test_calculate_confidence_with_valid_conditions(self, valid_genome):
        """Test confidence calculation with valid conditions."""
        strategy = GenomeStrategy(valid_genome)
        market = MarketInfo(
            ticker="TEST",
            slug="test",
            category="test",
            end_date=None,
            volume=1000.0,  # > 100000.0 * 0.01 = 1000, so volume condition should match
            liquidity=500.0,
            yes_price=0.7,  # > 0.5, so RSI condition should match
            no_price=0.3,
            metadata={}
        )

        # Conditions from valid_genome: RSI > 0.5 with weight 1.0
        conditions = [{"indicator": "rsi", "operator": ">", "value": 0.5, "weight": 1.0}]
        confidence = strategy._calculate_confidence(market, conditions)

        assert confidence == 1.0  # Perfect match

    def test_compile_genome_creates_valid_strategy_class(self, valid_genome):
        """Test that compile_genome creates a valid strategy class."""
        StrategyClass = compile_genome(valid_genome)

        # Should be a class
        assert isinstance(StrategyClass, type)

        # Should be able to instantiate
        instance = StrategyClass(valid_genome)
        assert isinstance(instance, GenomeStrategy)

        # Should have proper inheritance
        from backend.strategies.base import BaseStrategy
        assert issubclass(StrategyClass, BaseStrategy)

    def test_compile_genome_sets_class_name(self, valid_genome):
        """Test that compile_genome sets the class name correctly."""
        StrategyClass = compile_genome(valid_genome)

        expected_name = f"genome_{valid_genome.genome_id[:8]}"
        assert StrategyClass.__name__ == expected_name
        assert StrategyClass.__qualname__ == expected_name

    @pytest.mark.asyncio
    async def test_run_cycle_handles_empty_markets(self, valid_genome, mock_context):
        """Test that run_cycle handles empty market responses gracefully."""
        strategy = GenomeStrategy(valid_genome)

        # Mock empty market fetch
        with patch.object(strategy, '_fetch_markets', new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = []

            result = await strategy.run_cycle(mock_context)

            assert isinstance(result, CycleResult)
            assert result.decisions_recorded == 0
            assert result.trades_attempted == 0
            assert len(result.errors) == 0

    @pytest.mark.asyncio
    async def test_run_cycle_processes_markets_up_to_limit(self, valid_genome, mock_context):
        """Test that run_cycle processes markets up to TOP_MARKETS_TO_PROCESS limit."""
        strategy = GenomeStrategy(valid_genome)

        # Create more markets than the limit
        markets = [
            MarketInfo(
                ticker=f"TEST{i}",
                slug=f"test{i}",
                category="test",
                end_date=None,
                volume=1000.0,
                liquidity=500.0,
                yes_price=0.7,
                no_price=0.3,
                metadata={}
            )
            for i in range(TOP_MARKETS_TO_PROCESS + 5)  # More than limit
        ]

        with patch.object(strategy, '_fetch_markets', new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = markets

            result = await strategy.run_cycle(mock_context)

            # Should only process up to TOP_MARKETS_TO_PROCESS markets
            assert result.decisions_recorded <= TOP_MARKETS_TO_PROCESS

    def test_constants_have_expected_values(self):
        """Test that all constants have expected values."""
        assert DEFAULT_KELLY_FRACTION == 0.25
        assert DEFAULT_MAX_POSITION_FRACTION == 0.08
        assert DEFAULT_MAX_EXPOSURE_FRACTION == 0.70
        assert DEFAULT_MIN_CONFIDENCE == 0.50
        assert DEFAULT_TRIGGER_TYPE == "threshold_cross"
        assert DEFAULT_BANKROLL == 1000.0
        assert DEFAULT_MAX_TRADE_SIZE == 100.0
        assert DEFAULT_CONFIDENCE_BASELINE == 0.5
        assert MARKET_LIMIT == 50
        assert TOP_MARKETS_TO_PROCESS == 10