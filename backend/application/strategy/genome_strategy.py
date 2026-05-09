"""Genome-backed strategy template used by compiled genome classes."""

import logging
from typing import Dict, Any, Optional, TypedDict

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


class EntryCondition(TypedDict, total=False):
    indicator: str
    operator: str
    value: float
    weight: float


class EntryLogic(TypedDict, total=False):
    trigger_type: str
    min_confidence: float
    conditions: list[EntryCondition]


class CognitionChromosome(TypedDict, total=False):
    entry_logic: EntryLogic
    exit_logic: Dict[str, Any]


class RiskChromosome(TypedDict, total=False):
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
        raw_chromosomes = self._extract_raw_chromosomes()
        self._chromosomes = raw_chromosomes
        self._perception = self._normalize_chromosome_section(raw_chromosomes.get("perception"))
        self._cognition: CognitionChromosome = self._normalize_chromosome_section(raw_chromosomes.get("cognition"))
        self._execution = self._normalize_chromosome_section(raw_chromosomes.get("execution"))
        self._risk: RiskChromosome = self._normalize_chromosome_section(raw_chromosomes.get("risk"))
        self._meta = self._normalize_chromosome_section(raw_chromosomes.get("meta"))

    def _extract_raw_chromosomes(self) -> Dict[str, Any]:
        raw = self.genome.chromosomes
        if hasattr(raw, "model_dump"):
            try:
                return raw.model_dump()
            except Exception as e:
                logger.warning(f"Failed to extract chromosomes from genome {self.genome.genome_id}: {e}")
                return {}
        if isinstance(raw, dict):
            return raw
        logger.warning(f"Unexpected chromosome type {type(raw).__name__} for genome {self.genome.genome_id}")
        return {}

    @property
    def name(self) -> str:
        return f"genome_{self.genome.genome_id[:8]}"

    @property
    def description(self) -> str:
        return f"Auto-evolved {self.genome.archetype} strategy"

    @property
    def category(self) -> str:
        return self.genome.archetype

    def _normalize_chromosome_section(self, section: Any) -> Dict[str, Any]:
        if section is None:
            return {}
        if hasattr(section, "model_dump"):
            return section.model_dump()
        if isinstance(section, dict):
            return section
        try:
            return dict(section)
        except (TypeError, ValueError) as e:
            logger.warning(f"Failed to normalize chromosome section (type={type(section).__name__}): {e}")
            return {}

    def validate_chromosome_schema(self) -> bool:
        try:
            chromosomes = self._chromosomes
            if not isinstance(chromosomes, dict):
                logger.error(f"Genome {self.genome.genome_id}: chromosomes must be a dict, got {type(chromosomes)}")
                return False

            required_sections = ["perception", "cognition", "execution", "risk", "meta"]
            for section in required_sections:
                if section not in chromosomes:
                    logger.warning(f"Genome {self.genome.genome_id}: missing required chromosome section '{section}'")

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
        params = {}
        risk = self._risk
        cognition = self._cognition
        execution = self._execution
        perception = self._perception

        if isinstance(risk, dict):
            params.update(
                {
                    "kelly_fraction": risk.get("kelly_fraction", DEFAULT_KELLY_FRACTION),
                    "max_position_fraction": risk.get("max_position_fraction", DEFAULT_MAX_POSITION_FRACTION),
                    "max_total_exposure_fraction": risk.get("max_total_exposure_fraction", DEFAULT_MAX_EXPOSURE_FRACTION),
                }
            )

        if isinstance(cognition, dict):
            entry = cognition.get("entry_logic", {})
            if isinstance(entry, dict):
                params.update(
                    {
                        "min_confidence": entry.get("min_confidence", DEFAULT_MIN_CONFIDENCE),
                        "trigger_type": entry.get("trigger_type", DEFAULT_TRIGGER_TYPE),
                    }
                )
            exit_logic = cognition.get("exit_logic", {})
            if isinstance(exit_logic, dict):
                params["exit_logic"] = exit_logic

        if isinstance(execution, dict):
            params["execution"] = {
                "order_type": execution.get("order_type", "limit"),
                "slippage_tolerance": execution.get("slippage_tolerance", 0.02),
                "retry_logic": execution.get("retry_logic", "exponential_backoff"),
            }

        if isinstance(perception, dict):
            params["perception"] = {
                "data_sources": perception.get("data_sources", []),
                "timeframes": perception.get("timeframes", []),
            }

        return params

    async def run_cycle(self, ctx: StrategyContext) -> CycleResult:
        result = CycleResult(decisions_recorded=0, trades_attempted=0, trades_placed=0, errors=[])
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

                    record_decision = getattr(ctx, "record_decision", None)
                    if record_decision:
                        record_decision(
                            ctx.db,
                            self.name,
                            market.ticker,
                            "BUY",
                            confidence=signal.get("confidence", DEFAULT_MIN_CONFIDENCE),
                            signal_data=signal,
                            reason=signal.get("reason", "genome signal"),
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
                outcome_prices = m.get("outcomePrices", [DEFAULT_CONFIDENCE_BASELINE])
                if not isinstance(outcome_prices, list) or len(outcome_prices) == 0:
                    outcome_prices = [DEFAULT_CONFIDENCE_BASELINE]

                yes_price = float(outcome_prices[0]) if len(outcome_prices) > 0 else DEFAULT_CONFIDENCE_BASELINE
                no_price = float(outcome_prices[1]) if len(outcome_prices) > 1 else DEFAULT_CONFIDENCE_BASELINE

                result.append(
                    MarketInfo(
                        ticker=m.get("ticker", m.get("question", "")[:50]),
                        slug=m.get("slug", ""),
                        category=m.get("category", ""),
                        end_date=m.get("end_date"),
                        volume=float(m.get("volume24hr", 0) or 0),
                        liquidity=float(m.get("liquidity", 0) or 0),
                        yes_price=yes_price,
                        no_price=no_price,
                        metadata=m,
                    )
                )
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
        kelly_fraction = DEFAULT_KELLY_FRACTION
        if isinstance(risk, dict):
            max_frac = risk.get("max_position_fraction", DEFAULT_MAX_POSITION_FRACTION)
            kelly_fraction = risk.get("kelly_fraction", DEFAULT_KELLY_FRACTION)

        bankroll = getattr(ctx, "bankroll", DEFAULT_BANKROLL) if hasattr(ctx, "bankroll") else DEFAULT_BANKROLL
        size = min(bankroll * min(max_frac, kelly_fraction), DEFAULT_MAX_TRADE_SIZE)

        execution = self.default_params.get("execution", {})
        exit_logic = self.default_params.get("exit_logic", {})

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
            "order_type": execution.get("order_type", "limit"),
            "slippage_tolerance": execution.get("slippage_tolerance", 0.02),
            "retry_logic": execution.get("retry_logic", "exponential_backoff"),
            "exit_logic": exit_logic,
            "reasoning": f"genome {entry.get('trigger_type', DEFAULT_TRIGGER_TYPE)} confidence={confidence:.2f}",
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
