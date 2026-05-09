"""GenomeCompiler - translate StrategyGenome into executable BaseStrategy."""

import logging
from typing import Type, Dict, Any, Optional

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


class GenomeStrategy(BaseStrategy):
    """Compiled strategy from genome - dynamically generated."""
    
    def __init__(self, genome: StrategyGenome):
        self.genome = genome
        
        # Normalize chromosomes to dict to handle both Pydantic models and plain dicts
        raw_chromosomes = genome.chromosomes
        if hasattr(raw_chromosomes, "model_dump"):
            # It's a Pydantic model - convert to dict
            self._chromosomes = raw_chromosomes.model_dump()
        elif isinstance(raw_chromosomes, dict):
            self._chromosomes = raw_chromosomes
        else:
            # Unexpected type, fallback to empty dict
            self._chromosomes = {}
        
        # Normalize each chromosome section (handle Pydantic models nested within)
        self._perception = self._normalize_chromosome_section(self._chromosomes.get("perception"))
        self._cognition = self._normalize_chromosome_section(self._chromosomes.get("cognition"))
        self._execution = self._normalize_chromosome_section(self._chromosomes.get("execution"))
        self._risk = self._normalize_chromosome_section(self._chromosomes.get("risk"))
        self._meta = self._normalize_chromosome_section(self._chromosomes.get("meta"))
        
        self.name = f"genome_{genome.genome_id[:8]}"
        self.description = f"Auto-evolved {genome.archetype} strategy"
        self.category = genome.archetype
        self.default_params = self._build_params()

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
    
    def _build_params(self) -> Dict[str, Any]:
        params = {}
        
        risk = self._risk
        if isinstance(risk, dict):
            params["kelly_fraction"] = risk.get("kelly_fraction", DEFAULT_KELLY_FRACTION)
            params["max_position_fraction"] = risk.get("max_position_fraction", DEFAULT_MAX_POSITION_FRACTION)
            params["max_total_exposure_fraction"] = risk.get("max_total_exposure_fraction", DEFAULT_MAX_EXPOSURE_FRACTION)
        
        cognition = self._cognition
        if isinstance(cognition, dict):
            entry = cognition.get("entry_logic", {})
            if isinstance(entry, dict):
                params["min_confidence"] = entry.get("min_confidence", DEFAULT_MIN_CONFIDENCE)
                params["trigger_type"] = entry.get("trigger_type", DEFAULT_TRIGGER_TYPE)
        
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
        cognition = self._cognition
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
        
        risk = self._risk
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
    Instance attributes (name, description, category) are set in __init__().
    """
    
    class CompiledGenomeStrategy(GenomeStrategy):
        """Compiled strategy instance for this specific genome."""
        pass
    
    # Set strategy metadata for registration
    strategy_name = f"genome_{genome.genome_id[:8]}"
    CompiledGenomeStrategy.__name__ = strategy_name
    CompiledGenomeStrategy.__qualname__ = strategy_name
    
    from backend.strategies.registry import _auto_register
    _auto_register(CompiledGenomeStrategy)
    
    logger.info(f"Compiled genome {genome.genome_id} as {strategy_name}")
    
    return CompiledGenomeStrategy