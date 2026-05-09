"""GenomeCompiler - translate StrategyGenome into executable BaseStrategy."""

import logging
import time
from typing import Type

from backend.domain.genome.models import StrategyGenome
from backend.strategies.base import BaseStrategy
from backend.strategies.registry import _auto_register, register_genome_strategy
from backend.application.strategy import genome_strategy as genome_strategy_module

logger = logging.getLogger("trading_bot.genome_compiler")

# Backward-compatible exports for existing imports/tests
GenomeStrategy = genome_strategy_module.GenomeStrategy
DEFAULT_KELLY_FRACTION = genome_strategy_module.DEFAULT_KELLY_FRACTION
DEFAULT_MAX_POSITION_FRACTION = genome_strategy_module.DEFAULT_MAX_POSITION_FRACTION
DEFAULT_MAX_EXPOSURE_FRACTION = genome_strategy_module.DEFAULT_MAX_EXPOSURE_FRACTION
DEFAULT_MIN_CONFIDENCE = genome_strategy_module.DEFAULT_MIN_CONFIDENCE
DEFAULT_TRIGGER_TYPE = genome_strategy_module.DEFAULT_TRIGGER_TYPE
DEFAULT_BANKROLL = genome_strategy_module.DEFAULT_BANKROLL
DEFAULT_MAX_TRADE_SIZE = genome_strategy_module.DEFAULT_MAX_TRADE_SIZE
DEFAULT_CONFIDENCE_BASELINE = genome_strategy_module.DEFAULT_CONFIDENCE_BASELINE
MARKET_LIMIT = genome_strategy_module.MARKET_LIMIT
TOP_MARKETS_TO_PROCESS = genome_strategy_module.TOP_MARKETS_TO_PROCESS


def compile_genome(genome: StrategyGenome) -> Type[BaseStrategy]:
    """Compile a StrategyGenome into a runnable BaseStrategy subclass."""
    start_time = time.time()

    try:
        strategy_name = f"genome_{genome.genome_id[:8]}"

        class CompiledGenomeStrategy(GenomeStrategy):
            name = strategy_name
            description = f"Auto-evolved {genome.archetype} strategy"
            category = genome.archetype
            genome_id = genome.genome_id
            _compiled_genome = genome

            def __init__(self, genome_override: StrategyGenome | None = None):
                super().__init__(genome_override or self._compiled_genome)

        CompiledGenomeStrategy.__name__ = strategy_name
        CompiledGenomeStrategy.__qualname__ = strategy_name

        _auto_register(CompiledGenomeStrategy)
        register_genome_strategy(strategy_name, genome.genome_id)

        compilation_time = time.time() - start_time
        chromosome_count = len(genome.chromosomes) if isinstance(genome.chromosomes, dict) else 0
        logger.info(
            "Genome compilation completed | genome_id=%s | archetype=%s | strategy_name=%s | chromosomes=%s | compilation_time=%.3fs",
            genome.genome_id,
            genome.archetype,
            strategy_name,
            chromosome_count,
            compilation_time,
        )
        return CompiledGenomeStrategy

    except Exception as e:
        compilation_time = time.time() - start_time
        logger.error(
            "Genome compilation failed | genome_id=%s | archetype=%s | error=%s | compilation_time=%.3fs",
            genome.genome_id,
            genome.archetype,
            str(e),
            compilation_time,
        )
        raise
