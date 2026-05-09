"""GenomeCompiler - translate StrategyGenome into executable BaseStrategy."""

import logging
from typing import Type, Dict, Any

from backend.strategies.base import BaseStrategy, StrategyContext, CycleResult, MarketInfo
from backend.domain.genome.models import StrategyGenome

logger = logging.getLogger("trading_bot.genome_compiler")


class GenomeStrategy(BaseStrategy):
    """Compiled strategy from genome - dynamically generated."""
    
    def __init__(self, genome: StrategyGenome):
        self.genome = genome
        self._chromosomes = genome.chromosomes
        self._perception = self._chromosomes.get("perception", {})
        self._cognition = self._chromosomes.get("cognition", {})
        self._execution = self._chromosomes.get("execution", {})
        self._risk = self._chromosomes.get("risk", {})
        self._meta = self._chromosomes.get("meta", {})
        
        self.name = f"genome_{genome.genome_id[:8]}"
        self.description = f"Auto-evolved {genome.archetype} strategy"
        self.category = genome.archetype
        self.default_params = self._build_params()
    
    def _build_params(self) -> Dict[str, Any]:
        params = {}
        
        risk = self._risk
        if isinstance(risk, dict):
            params["kelly_fraction"] = risk.get("kelly_fraction", 0.25)
            params["max_position_fraction"] = risk.get("max_position_fraction", 0.08)
            params["max_total_exposure_fraction"] = risk.get("max_total_exposure_fraction", 0.70)
        
        cognition = self._cognition
        if isinstance(cognition, dict):
            entry = cognition.get("entry_logic", {})
            if isinstance(entry, dict):
                params["min_confidence"] = entry.get("min_confidence", 0.50)
                params["trigger_type"] = entry.get("trigger_type", "threshold_cross")
        
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
            
            for market in markets[:10]:
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
                            confidence=signal.get("confidence", 0.5),
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
            raw = await fetch_markets(limit=50)
            return [
                MarketInfo(
                    ticker=m.get("ticker", m.get("question", "")[:50]),
                    slug=m.get("slug", ""),
                    category=m.get("category", ""),
                    end_date=m.get("end_date"),
                    volume=float(m.get("volume24hr", 0) or 0),
                    liquidity=float(m.get("liquidity", 0) or 0),
                    yes_price=float(m.get("outcomePrices", [0.5])[0]) if isinstance(m.get("outcomePrices"), list) else 0.5,
                    no_price=float(m.get("outcomePrices", [0.5])[1]) if isinstance(m.get("outcomePrices"), list) and len(m.get("outcomePrices", [])) > 1 else 0.5,
                    metadata=m
                )
                for m in raw
            ]
        except Exception:
            return []
    
    def _evaluate_market(self, market: MarketInfo, ctx: StrategyContext) -> Dict[str, Any]:
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
        min_conf = entry.get("min_confidence", 0.50)
        
        if confidence < min_conf:
            return None
        
        direction = "up" if market.yes_price < 0.5 else "down"
        
        risk = self._risk
        max_frac = 0.08
        if isinstance(risk, dict):
            max_frac = risk.get("max_position_fraction", 0.08)
        
        bankroll = getattr(ctx, 'bankroll', 1000.0) if hasattr(ctx, 'bankroll') else 1000.0
        size = min(bankroll * max_frac, 100.0)
        
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
            "reasoning": f"genome {entry.get('trigger_type', 'threshold')} confidence={confidence:.2f}"
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
    """Compile a StrategyGenome into a BaseStrategy subclass."""
    
    class CompiledGenomeStrategy(GenomeStrategy):
        pass
    
    CompiledGenomeStrategy.__name__ = f"GenomeStrategy_{genome.genome_id[:8]}"
    
    from backend.strategies.registry import _auto_register
    _auto_register(CompiledGenomeStrategy)
    
    logger.info(f"Compiled genome {genome.genome_id} as {CompiledGenomeStrategy.__name__}")
    
    return CompiledGenomeStrategy