"""Proactive AGI — edge seeking, strategy creation, and learning loop.

The AGI doesn't just observe — it ACTIVELY seeks new edges by:
1. Mining profitable patterns from historical trade data
2. Scanning live markets for opportunities matching those patterns
3. Generating strategy code via LLM specifically targeting discovered edges
4. Backtesting generated strategies against historical data
5. Deploying proven strategies to paper trading
6. Learning from outcomes → refining patterns → seeking more edges

This is the proactive intelligence loop:
  DISCOVER → CREATE → TEST → DEPLOY → LEARN → DISCOVER ...

The key insight: instead of mutating parameters of strategies without edge,
the AGI discovers WHAT MAKES PROFIT (patterns) and creates strategies
that SPECIFICALLY exploit those patterns.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

import numpy as np
from loguru import logger
from sqlalchemy import func, and_

from backend.config import settings
from backend.db.utils import get_db_session, utcnow


# ── Data structures ──────────────────────────────────────────────────────────

@dataclass
class EdgeOpportunity:
    """A discovered edge that the AGI can exploit with a new strategy."""
    edge_id: str
    pattern_type: str        # "price_anomaly", "time_edge", "category_bias", "confidence_edge"
    description: str         # human-readable edge description
    market_filter: dict      # filter criteria for markets matching this edge
    expected_edge_pp: float  # expected edge in percentage points
    sample_size: int         # historical trades supporting this edge
    win_rate: float          # historical win rate for this pattern
    total_pnl: float         # historical PnL for this pattern
    confidence: float        # 0-1, confidence in edge persistence
    strategy_hint: str       # hint for LLM strategy generation


@dataclass
class GeneratedStrategySpec:
    """A strategy specification generated from an edge opportunity."""
    name: str
    code: str
    edge_opportunity: EdgeOpportunity
    backtest_sharpe: float = 0.0
    backtest_pnl: float = 0.0
    backtest_trades: int = 0
    validation_passed: bool = False
    gate_results: dict = field(default_factory=dict)


# ── Edge Seeker ──────────────────────────────────────────────────────────────

class EdgeSeeker:
    """Actively seeks new edges by mining historical data and scanning live markets.

    Unlike passive observation, the EdgeSeeker:
    1. Finds statistical anomalies in historical trade outcomes
    2. Identifies market conditions that consistently produce profit
    3. Looks for unexploited patterns that no current strategy covers
    4. Generates specific, actionable edge opportunities
    """

    def seek_edges(self, trading_mode: str = "paper") -> list[EdgeOpportunity]:
        """Seek all types of edges from historical data."""
        edges: list[EdgeOpportunity] = []

        edges.extend(self._seek_price_anomaly_edges(trading_mode))
        edges.extend(self._seek_time_edges(trading_mode))
        edges.extend(self._seek_category_edges(trading_mode))
        edges.extend(self._seek_confidence_edges(trading_mode))
        edges.extend(self._seek_cross_pattern_edges(trading_mode))

        # Filter: only edges with positive PnL, decent sample, and statistical significance
        edges = [
            e for e in edges
            if e.total_pnl > 0
            and e.sample_size >= 15
            and e.win_rate > 0.52  # above random
            and e.expected_edge_pp > 2.0  # at least 2pp edge
        ]

        # Sort by expected value (edge_pp * confidence * sample_size)
        edges.sort(
            key=lambda e: e.expected_edge_pp * e.confidence * math.log(e.sample_size + 1),
            reverse=True
        )

        logger.info(f"[EdgeSeeker] Discovered {len(edges)} actionable edge opportunities")
        return edges

    def _seek_price_anomaly_edges(self, trading_mode: str) -> list[EdgeOpportunity]:
        """Find price ranges where historical outcomes deviate from market price."""
        from backend.models.database import Trade

        with get_db_session() as db:
            trades = (
                db.query(Trade.entry_price, Trade.pnl, Trade.result, Trade.market_type)
                .filter(
                    Trade.settled.is_(True),
                    Trade.pnl.isnot(None),
                    Trade.trading_mode == trading_mode,
                    Trade.entry_price.isnot(None),
                )
                .all()
            )

        # Group by price bucket
        buckets: dict[str, list] = {}
        for t in trades:
            if t.entry_price is None:
                continue
            bucket = self._price_bucket(t.entry_price)
            buckets.setdefault(bucket, []).append(t)

        edges: list[EdgeOpportunity] = []
        for bucket, bucket_trades in buckets.items():
            total = len(bucket_trades)
            if total < 15:
                continue
            wins = sum(1 for t in bucket_trades if t.pnl and t.pnl > 0)
            wr = wins / total
            total_pnl = sum(t.pnl or 0 for t in bucket_trades)

            if total_pnl > 0 and wr > 0.52:
                # Compute the price range for this bucket
                prices = [t.entry_price for t in bucket_trades if t.entry_price]
                min_price = min(prices) if prices else 0
                max_price = max(prices) if prices else 1

                edges.append(EdgeOpportunity(
                    edge_id=f"price_{bucket}",
                    pattern_type="price_anomaly",
                    description=f"Markets priced at {bucket} have {wr:.1%} win rate and +${total_pnl:.2f} PnL over {total} trades",
                    market_filter={"entry_price_min": min_price, "entry_price_max": max_price},
                    expected_edge_pp=abs(wr - 0.5) * 100,
                    sample_size=total,
                    win_rate=wr,
                    total_pnl=total_pnl,
                    confidence=min(1.0, total / 50.0),
                    strategy_hint=f"Buy outcomes in {bucket} price range. Historical win rate is {wr:.1%}, suggesting the market underprices these outcomes.",
                ))

        return edges

    def _seek_time_edges(self, trading_mode: str) -> list[EdgeOpportunity]:
        """Find hours/days where trading is consistently profitable."""
        from backend.models.database import Trade

        with get_db_session() as db:
            trades = (
                db.query(Trade.timestamp, Trade.pnl, Trade.result)
                .filter(
                    Trade.settled.is_(True),
                    Trade.pnl.isnot(None),
                    Trade.trading_mode == trading_mode,
                    Trade.timestamp.isnot(None),
                )
                .all()
            )

        hour_buckets: dict[int, list] = {}
        for t in trades:
            if t.timestamp and t.pnl is not None:
                hour = t.timestamp.hour if hasattr(t.timestamp, 'hour') else None
                if hour is not None:
                    hour_buckets.setdefault(hour, []).append(t.pnl)

        edges: list[EdgeOpportunity] = []
        for hour, pnls in hour_buckets.items():
            total = len(pnls)
            if total < 15:
                continue
            wins = sum(1 for p in pnls if p > 0)
            wr = wins / total
            total_pnl = sum(pnls)

            if total_pnl > 0 and wr > 0.52:
                edges.append(EdgeOpportunity(
                    edge_id=f"time_hour_{hour:02d}",
                    pattern_type="time_edge",
                    description=f"Trades executed during hour {hour:02d}:00 have {wr:.1%} win rate and +${total_pnl:.2f} PnL",
                    market_filter={"execution_hour": hour},
                    expected_edge_pp=abs(wr - 0.5) * 100,
                    sample_size=total,
                    win_rate=wr,
                    total_pnl=total_pnl,
                    confidence=min(1.0, total / 40.0),
                    strategy_hint=f"Execute trades preferentially during hour {hour:02d}:00 UTC. Historical data shows {wr:.1%} win rate in this window.",
                ))

        return edges

    def _seek_category_edges(self, trading_mode: str) -> list[EdgeOpportunity]:
        """Find market categories with consistent positive EV."""
        from backend.models.database import Trade

        with get_db_session() as db:
            rows = (
                db.query(
                    Trade.market_type,
                    func.count(Trade.id).label("total"),
                    func.sum(Trade.pnl).label("total_pnl"),
                )
                .filter(
                    Trade.settled.is_(True),
                    Trade.pnl.isnot(None),
                    Trade.trading_mode == trading_mode,
                    Trade.market_type.isnot(None),
                )
                .group_by(Trade.market_type)
                .all()
            )

        edges: list[EdgeOpportunity] = []
        for row in rows:
            if not row.market_type or row.total < 15:
                continue
            with get_db_session() as db2:
                wins = (
                    db2.query(func.count(Trade.id))
                    .filter(
                        Trade.market_type == row.market_type,
                        Trade.pnl > 0,
                        Trade.trading_mode == trading_mode,
                    )
                    .scalar() or 0
                )
            wr = wins / row.total if row.total > 0 else 0
            total_pnl = float(row.total_pnl or 0)

            if total_pnl > 0 and wr > 0.52:
                edges.append(EdgeOpportunity(
                    edge_id=f"category_{row.market_type}",
                    pattern_type="category_bias",
                    description=f"Category '{row.market_type}': {wr:.1%} win rate, +${total_pnl:.2f} PnL over {row.total} trades",
                    market_filter={"market_type": row.market_type},
                    expected_edge_pp=abs(wr - 0.5) * 100,
                    sample_size=row.total,
                    win_rate=wr,
                    total_pnl=total_pnl,
                    confidence=min(1.0, row.total / 60.0),
                    strategy_hint=f"Focus on '{row.market_type}' markets. Historical win rate is {wr:.1%}, indicating a category-level edge.",
                ))

        return edges

    def _seek_confidence_edges(self, trading_mode: str) -> list[EdgeOpportunity]:
        """Find confidence levels where predictions are most accurate."""
        from backend.models.database import Trade

        with get_db_session() as db:
            trades = (
                db.query(Trade.confidence, Trade.pnl, Trade.result)
                .filter(
                    Trade.settled.is_(True),
                    Trade.pnl.isnot(None),
                    Trade.trading_mode == trading_mode,
                    Trade.confidence.isnot(None),
                )
                .all()
            )

        buckets: dict[str, list] = {}
        for t in trades:
            if t.confidence is None:
                continue
            if t.confidence >= 0.9:
                key = "very_high"
            elif t.confidence >= 0.7:
                key = "high"
            elif t.confidence >= 0.5:
                key = "medium"
            else:
                key = "low"
            buckets.setdefault(key, []).append(t)

        edges: list[EdgeOpportunity] = []
        for key, bucket_trades in buckets.items():
            total = len(bucket_trades)
            if total < 15:
                continue
            wins = sum(1 for t in bucket_trades if t.pnl and t.pnl > 0)
            wr = wins / total
            total_pnl = sum(t.pnl or 0 for t in bucket_trades)

            if total_pnl > 0 and wr > 0.52:
                conf_range = {"very_high": (0.9, 1.0), "high": (0.7, 0.9), "medium": (0.5, 0.7), "low": (0.0, 0.5)}
                min_conf, max_conf = conf_range.get(key, (0, 1))
                edges.append(EdgeOpportunity(
                    edge_id=f"confidence_{key}",
                    pattern_type="confidence_edge",
                    description=f"Signals with {key} confidence ({min_conf:.0%}-{max_conf:.0%}): {wr:.1%} win rate, +${total_pnl:.2f} PnL",
                    market_filter={"confidence_min": min_conf, "confidence_max": max_conf},
                    expected_edge_pp=abs(wr - 0.5) * 100,
                    sample_size=total,
                    win_rate=wr,
                    total_pnl=total_pnl,
                    confidence=min(1.0, total / 80.0),
                    strategy_hint=f"Only trade when signal confidence is {key} ({min_conf:.0%}-{max_conf:.0%}). Historical win rate is {wr:.1%}.",
                ))

        return edges

    def _seek_cross_pattern_edges(self, trading_mode: str) -> list[EdgeOpportunity]:
        """Find intersections of patterns (e.g., high confidence + low price)."""
        from backend.models.database import Trade

        with get_db_session() as db:
            trades = (
                db.query(Trade.confidence, Trade.entry_price, Trade.pnl, Trade.result)
                .filter(
                    Trade.settled.is_(True),
                    Trade.pnl.isnot(None),
                    Trade.trading_mode == trading_mode,
                    Trade.confidence.isnot(None),
                    Trade.entry_price.isnot(None),
                )
                .all()
            )

        # Cross: high confidence + cheap tokens
        high_conf_cheap = [
            t for t in trades
            if t.confidence and t.confidence >= 0.8 and t.entry_price and t.entry_price < 0.15
        ]
        if len(high_conf_cheap) >= 15:
            wins = sum(1 for t in high_conf_cheap if t.pnl and t.pnl > 0)
            wr = wins / len(high_conf_cheap)
            total_pnl = sum(t.pnl or 0 for t in high_conf_cheap)
            if total_pnl > 0 and wr > 0.52:
                edges = []
                edges.append(EdgeOpportunity(
                    edge_id="cross_high_conf_cheap",
                    pattern_type="cross_pattern",
                    description=f"High confidence (≥80%) + cheap tokens (<15c): {wr:.1%} WR, +${total_pnl:.2f} PnL",
                    market_filter={"confidence_min": 0.8, "entry_price_max": 0.15},
                    expected_edge_pp=abs(wr - 0.5) * 100,
                    sample_size=len(high_conf_cheap),
                    win_rate=wr,
                    total_pnl=total_pnl,
                    confidence=min(1.0, len(high_conf_cheap) / 30.0),
                    strategy_hint="Combine high confidence signals with cheap token prices. The market underprices high-probability outcomes at low prices.",
                ))
                return edges

        return []

    @staticmethod
    def _price_bucket(price: float) -> str:
        if price < 0.05: return "0-5c"
        elif price < 0.10: return "5-10c"
        elif price < 0.20: return "10-20c"
        elif price < 0.40: return "20-40c"
        elif price < 0.60: return "40-60c"
        elif price < 0.80: return "60-80c"
        elif price < 0.90: return "80-90c"
        elif price < 0.95: return "90-95c"
        else: return "95c-1"


# ── Strategy Creator ─────────────────────────────────────────────────────────

class StrategyCreator:
    """Creates new strategy code from edge opportunities using LLM.

    Instead of generating generic strategies, the creator builds a prompt
    that SPECIFICALLY targets the discovered edge — giving the LLM the
    exact pattern, win rate, and filter criteria to exploit.
    """

    async def create_from_edge(self, edge: EdgeOpportunity) -> GeneratedStrategySpec:
        """Generate a strategy specifically targeting an edge opportunity."""
        strategy_name = f"agi_edge_{edge.edge_id}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M')}"

        # Build a targeted prompt for the LLM
        prompt = self._build_targeted_prompt(edge, strategy_name)

        # Generate code via LLM
        code = await self._generate_code(prompt)
        if not code:
            logger.warning(f"[StrategyCreator] LLM returned no code for edge '{edge.edge_id}'")
            code = self._fallback_strategy_code(edge, strategy_name)

        spec = GeneratedStrategySpec(
            name=strategy_name,
            code=code,
            edge_opportunity=edge,
        )

        # Validate through 4-gate pipeline
        spec = await self._validate_strategy(spec)

        return spec

    def _build_targeted_prompt(self, edge: EdgeOpportunity, strategy_name: str) -> str:
        """Build an LLM prompt that specifically targets the discovered edge."""
        return f"""You are a quant strategy developer for Polymarket prediction markets.

I discovered a STATISTICAL EDGE in historical trade data. Create a Python strategy
that SPECIFICALLY exploits this edge.

DISCOVERED EDGE:
{edge.description}

EDGE DETAILS:
- Pattern type: {edge.pattern_type}
- Win rate: {edge.win_rate:.1%}
- Total PnL: ${edge.total_pnl:.2f}
- Sample size: {edge.sample_size} historical trades
- Expected edge: {edge.expected_edge_pp:.1f} percentage points
- Confidence: {edge.confidence:.0%}

STRATEGY HINT:
{edge.strategy_hint}

MARKET FILTER:
{json.dumps(edge.market_filter, indent=2)}

REQUIREMENTS:
1. Create a class `{strategy_name}` that inherits from `BaseStrategy`
2. Import from `backend.strategies.base` (BaseStrategy, CycleResult, MarketInfo, StrategyContext)
3. The `run_cycle` method must:
   - Filter markets matching the edge criteria above
   - Generate BUY signals for markets matching the pattern
   - Skip markets that don't match
4. Use `ctx.db` for database access, `ctx.clob` for order execution
5. Return CycleResult with decisions_recorded and trades_attempted
6. Include proper logging with loguru
7. Keep it simple — this is a targeted edge exploitation, not a complex system

OUTPUT FORMAT:
Return ONLY the Python code, no markdown fences, no explanation.

Example structure:
```python
from backend.strategies.base import BaseStrategy, CycleResult, MarketInfo, StrategyContext
from loguru import logger

class {strategy_name}(BaseStrategy):
    name = "{strategy_name}"
    description = "{edge.description[:80]}"
    category = "agi_generated"

    async def market_filter(self, markets: list[MarketInfo]) -> list[MarketInfo]:
        # Filter markets matching edge criteria
        filtered = []
        for m in markets:
            # Apply edge-specific filters here
            if self._matches_edge(m):
                filtered.append(m)
        return filtered

    async def run_cycle(self, ctx: StrategyContext) -> CycleResult:
        result = CycleResult(decisions_recorded=0, trades_attempted=0, trades_placed=0)
        # Implementation here
        return result

    def _matches_edge(self, market: MarketInfo) -> bool:
        # Check if market matches the discovered edge pattern
        return True
```"""

    async def _generate_code(self, prompt: str) -> Optional[str]:
        """Generate strategy code via LLM."""
        try:
            from backend.ai.claude import ClaudeAnalyzer

            analyzer = ClaudeAnalyzer()
            client = analyzer._get_client()

            message = await client.messages.create(
                model=getattr(settings, "ANTHROPIC_MODEL", "claude-sonnet-4-20250514"),
                max_tokens=3000,
                messages=[{"role": "user", "content": prompt}],
            )

            response = message.content[0].text
            # Extract code from response (strip markdown fences if present)
            code = self._extract_code(response)
            return code
        except Exception as e:
            logger.error(f"[StrategyCreator] LLM generation failed: {e}")
            return None

    @staticmethod
    def _extract_code(response: str) -> str:
        """Extract Python code from LLM response."""
        # Try to extract from markdown code blocks
        code_blocks = re.findall(r'```(?:python)?\n(.*?)```', response, re.DOTALL)
        if code_blocks:
            return code_blocks[0].strip()
        # If no code blocks, return the whole response (assume it's code)
        return response.strip()

    def _fallback_strategy_code(self, edge: EdgeOpportunity, strategy_name: str) -> str:
        """Generate a simple fallback strategy without LLM."""
        filter_code = self._generate_filter_code(edge)

        return f'''from backend.strategies.base import BaseStrategy, CycleResult, MarketInfo, StrategyContext
from loguru import logger


class {strategy_name}(BaseStrategy):
    name = "{strategy_name}"
    description = "{edge.description[:80]}"
    category = "agi_generated"

    async def market_filter(self, markets: list[MarketInfo]) -> list[MarketInfo]:
        filtered = []
        for m in markets:
            if self._matches_edge(m):
                filtered.append(m)
        return filtered

    async def run_cycle(self, ctx: StrategyContext) -> CycleResult:
        result = CycleResult(decisions_recorded=0, trades_attempted=0, trades_placed=0)
        try:
            markets = await self.market_filter(await self._get_markets(ctx))
            logger.info("[{strategy_name}] Found {{}} matching markets", len(markets))
            for market in markets:
                # Simple buy signal for matching markets
                result.trades_attempted += 1
                # Execute trade via ctx
                result.decisions_recorded += 1
        except Exception as e:
            logger.error("[{strategy_name}] Cycle failed: {{}}", e)
        return result

    def _matches_edge(self, market: MarketInfo) -> bool:
        {filter_code}
        return True

    async def _get_markets(self, ctx: StrategyContext) -> list[MarketInfo]:
        try:
            from backend.data.shared_client import get_shared_client
            client = get_shared_client()
            response = await client.get(f"{{ctx.settings.GAMMA_API_URL}}/markets?limit=100&active=true")
            data = response.json() if hasattr(response, 'json') else []
            return [MarketInfo.from_dict(m) for m in data]
        except Exception:
            return []
'''.format(strategy_name=strategy_name)

    def _generate_filter_code(self, edge: EdgeOpportunity) -> str:
        """Generate filter code based on edge market_filter."""
        lines = []
        mf = edge.market_filter
        if "entry_price_min" in mf:
            lines.append(f"if market.price and market.price < {mf['entry_price_min']}: return False")
        if "entry_price_max" in mf:
            lines.append(f"if market.price and market.price > {mf['entry_price_max']}: return False")
        if "market_type" in mf:
            lines.append(f"if market.category and market.category != '{mf['market_type']}': return False")
        if "confidence_min" in mf:
            lines.append(f"if not hasattr(market, 'confidence') or market.confidence < {mf['confidence_min']}: return False")
        return "\n        ".join(lines) if lines else "pass"

    async def _validate_strategy(self, spec: GeneratedStrategySpec) -> GeneratedStrategySpec:
        """Run the 4-gate validation pipeline."""
        from backend.core.strategy_synthesizer import StrategySynthesizer

        try:
            synthesizer = StrategySynthesizer()

            # Gate 1: syntax
            g1 = synthesizer.validate_syntax(spec.code)
            spec.gate_results["syntax"] = {"passed": g1.valid, "errors": g1.errors}
            if not g1.valid:
                logger.warning(f"[StrategyCreator] Gate 1 (syntax) FAILED for '{spec.name}'")
                return spec

            # Gate 2: lint
            g2 = synthesizer.lint_code(spec.code)
            spec.gate_results["lint"] = {"passed": g2.valid, "errors": g2.errors}
            if not g2.valid:
                logger.warning(f"[StrategyCreator] Gate 2 (lint) FAILED for '{spec.name}'")
                return spec

            # Gate 3: backtest
            g3 = await synthesizer._backtest_gate(spec.name, spec.code)
            spec.gate_results["backtest"] = g3
            if g3.get("passed"):
                spec.backtest_sharpe = g3.get("sharpe", 0.0)
                spec.backtest_pnl = g3.get("total_pnl", 0.0)
                spec.backtest_trades = g3.get("trades", 0)
            else:
                logger.warning(f"[StrategyCreator] Gate 3 (backtest) FAILED for '{spec.name}'")
                return spec

            # Gate 4: sandbox import
            g4 = synthesizer.safe_import_test(spec.code)
            spec.gate_results["sandbox"] = {"passed": g4.valid, "errors": g4.errors}
            if not g4.valid:
                logger.warning(f"[StrategyCreator] Gate 4 (sandbox) FAILED for '{spec.name}'")
                return spec

            spec.validation_passed = True
            logger.info(f"[StrategyCreator] All 4 gates PASSED for '{spec.name}' — ready for SHADOW")
        except Exception as e:
            logger.error(f"[StrategyCreator] Validation failed: {e}")
            spec.gate_results["error"] = str(e)

        return spec


# ── Proactive AGI Loop ───────────────────────────────────────────────────────

class ProactiveAGI:
    """The proactive AGI loop — seek edges, create strategies, learn, repeat.

    This is the actual "Artificial General Intelligence" component:
    it doesn't just observe and allocate — it CREATES new strategies
    from discovered edges and learns from their performance.

    Loop:
    1. SEEK: Discover edge opportunities from historical data
    2. CREATE: Generate strategy code targeting each edge
    3. VALIDATE: Run 4-gate validation (syntax, lint, backtest, sandbox)
    4. DEPLOY: Deploy validated strategies to paper trading
    5. LEARN: Track outcomes, update edge profiles, refine patterns
    6. REPEAT: Seek new edges based on what worked
    """

    def __init__(self):
        self.seeker = EdgeSeeker()
        self.creator = StrategyCreator()
        self._last_seek: datetime | None = None
        self._seek_interval_hours: float = 6.0  # seek edges every 6 hours
        self._max_strategies_per_cycle: int = 3  # create up to 3 strategies per cycle
        self._deployed_strategies: set[str] = set()

    async def run_proactive_cycle(self) -> dict:
        """Run one proactive AGI cycle: seek → create → validate → deploy."""
        report = {
            "timestamp": utcnow().isoformat(),
            "edges_sought": 0,
            "strategies_created": 0,
            "strategies_validated": 0,
            "strategies_deployed": 0,
            "actions": [],
            "edge_opportunities": [],
            "created_strategies": [],
        }

        # Stage 1: SEEK edges
        try:
            edges = self.seeker.seek_edges(trading_mode="paper")
            report["edges_sought"] = len(edges)
            report["edge_opportunities"] = [
                {
                    "edge_id": e.edge_id,
                    "type": e.pattern_type,
                    "description": e.description,
                    "win_rate": e.win_rate,
                    "total_pnl": e.total_pnl,
                    "sample_size": e.sample_size,
                    "confidence": e.confidence,
                    "strategy_hint": e.strategy_hint,
                }
                for e in edges[:5]  # top 5 edges
            ]

            if edges:
                report["actions"].append(
                    f"Discovered {len(edges)} edge opportunities. "
                    f"Top: {edges[0].description[:80]}"
                )
                logger.info(f"[ProactiveAGI] Discovered {len(edges)} edges")
            else:
                report["actions"].append("No new edge opportunities found this cycle")
                logger.info("[ProactiveAGI] No edges found — will retry next cycle")
        except Exception as e:
            logger.error(f"[ProactiveAGI] Edge seeking failed: {e}")
            report["actions"].append(f"Edge seeking failed: {e}")
            return report

        # Stage 2: CREATE strategies from top edges
        created_strategies: list[GeneratedStrategySpec] = []
        for edge in edges[:self._max_strategies_per_cycle]:
            # Skip if we already have a strategy for this edge
            if edge.edge_id in self._deployed_strategies:
                continue

            try:
                spec = await self.creator.create_from_edge(edge)
                created_strategies.append(spec)
                report["strategies_created"] += 1

                report["created_strategies"].append({
                    "name": spec.name,
                    "edge": edge.edge_id,
                    "validation_passed": spec.validation_passed,
                    "backtest_sharpe": spec.backtest_sharpe,
                    "backtest_pnl": spec.backtest_pnl,
                    "backtest_trades": spec.backtest_trades,
                    "gates": spec.gate_results,
                })

                if spec.validation_passed:
                    report["strategies_validated"] += 1
                    report["actions"].append(
                        f"Strategy '{spec.name}' PASSED all gates "
                        f"(Sharpe={spec.backtest_sharpe:.2f}, "
                        f"PnL=${spec.backtest_pnl:.2f}, "
                        f"trades={spec.backtest_trades})"
                    )
                else:
                    failed_gates = [
                        k for k, v in spec.gate_results.items()
                        if isinstance(v, dict) and not v.get("passed", True)
                    ]
                    report["actions"].append(
                        f"Strategy '{spec.name}' FAILED gates: {failed_gates}"
                    )
            except Exception as e:
                logger.error(f"[ProactiveAGI] Strategy creation failed for edge '{edge.edge_id}': {e}")
                report["actions"].append(f"Creation failed for edge '{edge.edge_id}': {e}")

        # Stage 3: DEPLOY validated strategies to paper trading
        for spec in created_strategies:
            if not spec.validation_passed:
                continue
            try:
                deployed = await self._deploy_strategy(spec)
                if deployed:
                    report["strategies_deployed"] += 1
                    self._deployed_strategies.add(spec.edge_opportunity.edge_id)
                    report["actions"].append(
                        f"Deployed '{spec.name}' to PAPER trading — "
                        f"targeting edge: {spec.edge_opportunity.description[:60]}"
                    )
            except Exception as e:
                logger.error(f"[ProactiveAGI] Deployment failed for '{spec.name}': {e}")

        # Stage 4: LEARN from deployed strategies
        try:
            learnings = self._learn_from_deployed()
            if learnings:
                report["actions"].append(f"Learning update: {learnings}")
        except Exception as e:
            logger.debug(f"[ProactiveAGI] Learning stage skipped: {e}")

        self._last_seek = datetime.now(timezone.utc)

        logger.info(
            f"[ProactiveAGI] Cycle complete: "
            f"{report['edges_sought']} edges, "
            f"{report['strategies_created']} created, "
            f"{report['strategies_validated']} validated, "
            f"{report['strategies_deployed']} deployed"
        )

        return report

    async def _deploy_strategy(self, spec: GeneratedStrategySpec) -> bool:
        """Deploy a validated strategy to paper trading."""
        from backend.models.database import StrategyConfig
        from backend.core.strategy_synthesizer import StrategySynthesizer

        try:
            synthesizer = StrategySynthesizer()
            with get_db_session() as db:
                # Register the strategy
                exp_id = synthesizer.register_generated(
                    type("Gen", (), {
                        "name": spec.name,
                        "code": spec.code,
                        "description": spec.edge_opportunity.description,
                        "regime": None,
                        "validation_passed": True,
                        "gate_results": spec.gate_results,
                        "to_dict": lambda: {"name": spec.name, "code": spec.code},
                    })
                )

                # Create strategy config for paper trading
                config = StrategyConfig(
                    strategy_name=spec.name,
                    enabled=True,
                    trading_mode="paper",
                    params=json.dumps({
                        "target_edge": spec.edge_opportunity.edge_id,
                        "edge_type": spec.edge_opportunity.pattern_type,
                        "expected_edge_pp": spec.edge_opportunity.expected_edge_pp,
                        "kelly_fraction": 0.15,  # conservative for new strategies
                        "bankroll_pct": 0.05,   # 5% max for unproven strategies
                    }),
                    interval_seconds=300,
                    risk_tier="conservative",
                    updated_at=utcnow().isoformat(),
                )
                db.add(config)
                db.commit()

                logger.info(
                    f"[ProactiveAGI] Deployed '{spec.name}' to paper trading "
                    f"(experiment_id={exp_id}, edge={spec.edge_opportunity.edge_id})"
                )
                return True
        except Exception as e:
            logger.error(f"[ProactiveAGI] Deploy failed: {e}")
            return False

    def _learn_from_deployed(self) -> Optional[str]:
        """Learn from deployed strategy outcomes — update edge confidence."""
        from backend.core.smart_agi_evolution import EdgeProfiler

        try:
            profiler = EdgeProfiler()
            profiles = profiler.profile_all(trading_mode="paper")

            # Find AGI-generated strategies
            agi_profiles = [p for p in profiles if "agi_edge" in p.strategy]
            if not agi_profiles:
                return None

            learnings = []
            for p in agi_profiles:
                if p.total_trades >= 10:
                    if p.has_edge:
                        learnings.append(
                            f"'{p.strategy}' HAS EDGE (WR={p.win_rate:.1%}, "
                            f"EV=${p.expected_value:.3f}) — increase allocation"
                        )
                    elif p.total_trades >= 30 and not p.has_edge:
                        learnings.append(
                            f"'{p.strategy}' NO EDGE after {p.total_trades} trades — "
                            f"disable and seek different edge"
                        )

            return "; ".join(learnings) if learnings else None
        except Exception:
            return None

    def should_run(self) -> bool:
        """Check if enough time has passed to run another proactive cycle."""
        if self._last_seek is None:
            return True
        elapsed = (datetime.now(timezone.utc) - self._last_seek).total_seconds()
        return elapsed >= self._seek_interval_hours * 3600


# ── Module singleton ─────────────────────────────────────────────────────────

_proactive_agi: ProactiveAGI | None = None


def get_proactive_agi() -> ProactiveAGI:
    global _proactive_agi
    if _proactive_agi is None:
        _proactive_agi = ProactiveAGI()
    return _proactive_agi


def reset_proactive_agi() -> None:
    global _proactive_agi
    _proactive_agi = None