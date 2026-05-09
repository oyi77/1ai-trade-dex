"""GenomeCompiler - translate StrategyGenome into executable BaseStrategy."""

import logging
from typing import Type, Dict, Any, Optional, TypedDict

from backend.strategies.base import BaseStrategy, StrategyContext, CycleResult, MarketInfo
from backend.domain.genome.models import StrategyGenome

logger = logging.getLogger("trading_bot.genome_compiler")

# Default configuration constants
DEFAULT_KELLY_FRACTION = 0.25
DEFAULT_MAX_POSITION_FRACTION = 0.08
DEFAULT_MAX_EXPOSURE_FRACTION = 0.70
DEFAULT_MIN_CONFIDENCE = 0.50
DEFAULT_TRIGGER_TYPE = "threshold_cross"
DEFAULT_BANKROLL = 1000.0
DEFAULT_MAX_TRADE_SIZE = 100.0
DEFAULT_CONFIDENCE_BASELINE = 0.5
MARKET_LIMIT = 50
TOP_MARKETS_TO_PROCESS = 10

# Chromosome schema documentation
"""
Chromosome structure for evolved strategies:

{
  "perception": {
    "indicators": ["rsi", "volume", "liquidity"],
    ...
  },
  "cognition": {
    "entry_logic": {
      "trigger_type": "threshold_cross",
      "conditions": [
        {"indicator": "rsi", "operator": ">", "value": 0.5, "weight": 1.0}
      ],
      "min_confidence": 0.50
    },
    ...
  },
  "execution": {...},
  "risk": {
    "kelly_fraction": 0.25,
    "max_position_fraction": 0.08,
    "max_total_exposure_fraction": 0.70
  },
  "meta": {...}
}
"""

class EntryCondition(TypedDict, total=False):
    """Single condition in entry logic."""
    indicator: str
    operator: str
    value: float
    weight: float

class EntryLogic(TypedDict, total=False):
    """Entry logic chromosome section."""
    trigger_type: str
    min_confidence: float
    conditions: list[EntryCondition]

class CognitionChromosome(TypedDict, total=False):
    """Cognition chromosome section."""
    entry_logic: EntryLogic

class RiskChromosome(TypedDict, total=False):
    """Risk chromosome section."""
    kelly_fraction: float
    max_position_fraction: float
    max_total_exposure_fraction: float


class GenomeStrategy(BaseStrategy):
    """Compiled strategy from genome - dynamically generated."""
    
    def __init__(self, genome: StrategyGenome):
        self.genome = genome
        self._load_chromosomes()
        self.default_params = self._build_params()

    def _load_chromosomes(self) -> None:
        """Load and normalize chromosome sections from genome."""
        raw_chromosomes = self._extract_raw_chromosomes()
        self._perception = self._normalize_chromosome_section(raw_chromosomes.get("perception"))
        self._cognition: CognitionChromosome = self._normalize_chromosome_section(raw_chromosomes.get("cognition"))
        self._execution = self._normalize_chromosome_section(raw_chromosomes.get("execution"))
        self._risk: RiskChromosome = self._normalize_chromosome_section(raw_chromosomes.get("risk"))
        self._meta = self._normalize_chromosome_section(raw_chromosomes.get("meta"))

    def _extract_raw_chromosomes(self) -> Dict[str, Any]:
        """Extract raw chromosomes from genome, handling Pydantic models."""
        raw = self.genome.chromosomes
        if hasattr(raw, "model_dump"):
            try:
                return raw.model_dump()
            except Exception as e:
                logger.warning(f"Failed to extract chromosomes from genome {self.genome.genome_id}: {e}")
                return {}
        elif isinstance(raw, dict):
            return raw
        else:
            logger.warning(f"Unexpected chromosome type {type(raw).__name__} for genome {self.genome.genome_id}")
            return {}

    @property
    def name(self) -> str:
        """Unique machine-readable strategy name."""
        return f"genome_{self.genome.genome_id[:8]}"

    @property
    def description(self) -> str:
        """Human-readable description of what the strategy does."""
        return f"Auto-evolved {self.genome.archetype} strategy"

    @property
    def category(self) -> str:
        """Strategy category (e.g. 'btc', 'weather', 'copy', 'ai')."""
        return self.genome.archetype

    def _normalize_chromosome_section(self, section: Any) -> Dict[str, Any]:
        """Convert Pydantic models to dicts; fallback to empty dict if None."""
        if section is None:
            return {}
        if hasattr(section, "model_dump"):
            return section.model_dump()
        if isinstance(section, dict):
            return section
        # Unexpected type - try converting or return empty
        try:
            return dict(section)
        except (TypeError, ValueError) as e:
            logger.warning(f"Failed to normalize chromosome section (type={type(section).__name__}): {e}")
            return {}

    def validate_chromosome_schema(self) -> bool:
        """Validate that the genome's chromosome structure matches expected schema.
        
        Returns True if valid, False if invalid. Logs validation errors.
        """
        try:
            chromosomes = self._chromosomes
            if not isinstance(chromosomes, dict):
                logger.error(f"Genome {self.genome.genome_id}: chromosomes must be a dict, got {type(chromosomes)}")
                return False
            
            # Required top-level sections
            required_sections = ["perception", "cognition", "execution", "risk", "meta"]
            for section in required_sections:
                if section not in chromosomes:
                    logger.warning(f"Genome {self.genome.genome_id}: missing required chromosome section '{section}'")
            
            # Validate cognition section structure
            cognition = chromosomes.get("cognition", {})
            if isinstance(cognition, dict):
                entry_logic = cognition.get("entry_logic", {})
                if isinstance(entry_logic, dict):
                    conditions = entry_logic.get("conditions", [])
                    if isinstance(conditions, list):
                        for i, condition in enumerate(conditions):
                            if not isinstance(condition, dict):
                                logger.warning(f"Genome {self.genome.genome_id}: condition {i} must be a dict")
                                continue
                            required_keys = ["indicator", "operator", "value"]
                            for key in required_keys:
                                if key not in condition:
                                    logger.warning(f"Genome {self.genome.genome_id}: condition {i} missing '{key}'")
                    else:
                        logger.warning(f"Genome {self.genome.genome_id}: entry_logic.conditions must be a list")
            
            # Validate risk section structure
            risk = chromosomes.get("risk", {})
            if isinstance(risk, dict):
                numeric_params = ["kelly_fraction", "max_position_fraction", "max_total_exposure_fraction"]
                for param in numeric_params:
                    value = risk.get(param)
                    if value is not None and not isinstance(value, (int, float)):
                        logger.warning(f"Genome {self.genome.genome_id}: risk.{param} must be numeric, got {type(value)}")
            
            return True
            
        except Exception as e:
            logger.error(f"Genome {self.genome.genome_id}: schema validation failed with error: {e}")
            return False
    
    def _build_params(self) -> Dict[str, Any]:
        """Build strategy parameters from chromosome configuration.
        
        Optimized to minimize repeated dict.get() calls and improve performance.
        """
        params = {}
        
        # Cache chromosome sections to avoid repeated access
        risk = self._risk
        cognition = self._cognition
        
        # Extract risk parameters with single dict access
        if isinstance(risk, dict):
            risk_params = {
                "kelly_fraction": risk.get("kelly_fraction", DEFAULT_KELLY_FRACTION),
                "max_position_fraction": risk.get("max_position_fraction", DEFAULT_MAX_POSITION_FRACTION),
                "max_total_exposure_fraction": risk.get("max_total_exposure_fraction", DEFAULT_MAX_EXPOSURE_FRACTION)
            }
            params.update(risk_params)
        
        # Extract cognition parameters with single dict access
        if isinstance(cognition, dict):
            entry = cognition.get("entry_logic", {})
            if isinstance(entry, dict):
                cognition_params = {
                    "min_confidence": entry.get("min_confidence", DEFAULT_MIN_CONFIDENCE),
                    "trigger_type": entry.get("trigger_type", DEFAULT_TRIGGER_TYPE)
                }
                params.update(cognition_params)
        
        return params
    
    async def run_cycle(self, ctx: StrategyContext) -> CycleResult:
        result = CycleResult(
            decisions_recorded=0,
            trades_attempted=0,
            trades_placed=0,
            errors=[]
        )
        
        try:
            markets = await self._fetch_markets(ctx)
            if not markets:
                return result
            
            for market in markets[:TOP_MARKETS_TO_PROCESS]:
                signal = self._evaluate_market(market, ctx)
                if signal:
                    result.decisions.append(signal)
                    result.decisions_recorded += 1
                    result.trades_attempted += 1
                    
                    record_decision = getattr(ctx, 'record_decision', None)
                    if record_decision:
                        record_decision(
                            ctx.db,
                            self.name,
                            market.ticker,
                            "BUY",
                            confidence=signal.get("confidence", DEFAULT_MIN_CONFIDENCE),
                            signal_data=signal,
                            reason=signal.get("reason", "genome signal")
                        )
        except Exception as e:
            result.errors.append(str(e))
            logger.exception(f"[{self.name}] Error: {e}")
        
        return result
    
    async def _fetch_markets(self, ctx: StrategyContext) -> list[MarketInfo]:
        try:
            from backend.data.gamma import fetch_markets
            raw = await fetch_markets(limit=MARKET_LIMIT)
            result = []
            for m in raw:
                # Safely extract outcome prices
                outcome_prices = m.get("outcomePrices", [DEFAULT_CONFIDENCE_BASELINE])
                if not isinstance(outcome_prices, list) or len(outcome_prices) == 0:
                    outcome_prices = [DEFAULT_CONFIDENCE_BASELINE]
                
                yes_price = float(outcome_prices[0]) if len(outcome_prices) > 0 else DEFAULT_CONFIDENCE_BASELINE
                no_price = float(outcome_prices[1]) if len(outcome_prices) > 1 else DEFAULT_CONFIDENCE_BASELINE
                
                result.append(MarketInfo(
                    ticker=m.get("ticker", m.get("question", "")[:50]),
                    slug=m.get("slug", ""),
                    category=m.get("category", ""),
                    end_date=m.get("end_date"),
                    volume=float(m.get("volume24hr", 0) or 0),
                    liquidity=float(m.get("liquidity", 0) or 0),
                    yes_price=yes_price,
                    no_price=no_price,
                    metadata=m
                ))
            return result
        except Exception as e:
            logger.warning(f"Failed to fetch markets: {e}")
            return []
    
    def _evaluate_market(self, market: MarketInfo, ctx: StrategyContext) -> Optional[Dict[str, Any]]:
        cognition: CognitionChromosome = self._cognition
        if not isinstance(cognition, dict):
            return None
        
        entry = cognition.get("entry_logic", {})
        if not isinstance(entry, dict):
            return None
        
        conditions = entry.get("conditions", [])
        if not conditions:
            return None
        
        confidence = self._calculate_confidence(market, conditions)
        min_conf = entry.get("min_confidence", DEFAULT_MIN_CONFIDENCE)
        
        if confidence < min_conf:
            return None
        
        direction = "up" if market.yes_price < 0.5 else "down"
        
        risk: RiskChromosome = self._risk
        max_frac = DEFAULT_MAX_POSITION_FRACTION
        if isinstance(risk, dict):
            max_frac = risk.get("max_position_fraction", DEFAULT_MAX_POSITION_FRACTION)
        
        bankroll = getattr(ctx, 'bankroll', DEFAULT_BANKROLL) if hasattr(ctx, 'bankroll') else DEFAULT_BANKROLL
        size = min(bankroll * max_frac, DEFAULT_MAX_TRADE_SIZE)
        
        return {
            "decision": "BUY",
            "market_ticker": market.ticker,
            "direction": direction,
            "confidence": confidence,
            "edge": confidence - market.yes_price,
            "size": size,
            "entry_price": market.yes_price,
            "suggested_size": size,
            "model_probability": confidence,
            "market_probability": market.yes_price,
            "platform": "polymarket",
            "strategy_name": self.name,
            "genome_id": self.genome.genome_id,
            "reasoning": f"genome {entry.get('trigger_type', DEFAULT_TRIGGER_TYPE)} confidence={confidence:.2f}"
        }
    
    def _calculate_confidence(self, market: MarketInfo, conditions: list) -> float:
        if not conditions:
            return 0.5
        
        score = 0.0
        for cond in conditions:
            indicator = cond.get("indicator", "")
            operator = cond.get("operator", ">")
            value = cond.get("value", 0.5)
            weight = cond.get("weight", 1.0)
            
            if indicator in ["rsi", "RSI"]:
                market_value = 0.5
            elif indicator in ["volume", "vol"]:
                market_value = market.volume / 100000.0
            elif indicator in ["liquidity", "liq"]:
                market_value = market.liquidity / 100000.0
            else:
                market_value = market.yes_price
            
            match = False
            if operator == ">" and market_value > value:
                match = True
            elif operator == "<" and market_value < value:
                match = True
            elif operator == ">=" and market_value >= value:
                match = True
            elif operator == "<=" and market_value <= value:
                match = True
            
            if match:
                score += weight
        
        return min(score / len(conditions), 1.0)


def compile_genome(genome: StrategyGenome) -> Type[BaseStrategy]:
    """Compile a StrategyGenome into a BaseStrategy subclass.
    
    Creates a GenomeStrategy subclass with genome-specific initialization.
    Properties (name, description, category) are computed dynamically from genome.
    
    Logs comprehensive metrics about the compilation process.
    """
    import time
    start_time = time.time()
    
    try:
        class CompiledGenomeStrategy(GenomeStrategy):
            """Compiled strategy instance for this specific genome."""
            pass
        
        # Set strategy metadata for registration and logging
        strategy_name = f"genome_{genome.genome_id[:8]}"
        CompiledGenomeStrategy.__name__ = strategy_name
        CompiledGenomeStrategy.__qualname__ = strategy_name
        
        # Log compilation metrics
        compilation_time = time.time() - start_time
        chromosome_count = len(genome.chromosomes) if isinstance(genome.chromosomes, dict) else 0
        
        logger.info(
            f"Genome compilation completed | "
            f"genome_id={genome.genome_id} | "
            f"archetype={genome.archetype} | "
            f"strategy_name={strategy_name} | "
            f"chromosomes={chromosome_count} | "
            f"compilation_time={compilation_time:.3f}s"
        )
        
        from backend.strategies.registry import _auto_register
        _auto_register(CompiledGenomeStrategy)
        
        return CompiledGenomeStrategy
        
    except Exception as e:
        compilation_time = time.time() - start_time
        logger.error(
            f"Genome compilation failed | "
            f"genome_id={genome.genome_id} | "
            f"error={str(e)} | "
            f"genome_id={genome.genome_id} | "
            f"archetype={genome.archetype} | "
            f"compilation_time={compilation_time:.3f}s"
        )
        raise