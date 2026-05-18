"""
Negative-Risk Multi-Outcome Portfolio Strategy for PolyEdge.

Discovers neg-risk events where mutually exclusive outcomes sum > 1.0,
calculates fair probabilities via normalization, detects mispricings,
and places multi-leg orders with Kelly sizing.

Neg-risk markets (e.g. "Who will win?") have N outcomes that must sum to 1.0.
When market prices deviate, a portfolio of all outcomes guarantees profit.
"""

import json
import time
from dataclasses import dataclass
from typing import Optional

from backend.strategies.base import (
    BaseStrategy,
    CycleResult,
    StrategyContext,
)
from backend.config import settings

from loguru import logger


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------


def _cfg(name: str, default=None):
    return getattr(settings, name, default) if hasattr(settings, name) else default


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class NegRiskEvent:
    """A multi-outcome event with neg-risk properties."""

    event_id: str
    slug: str
    question: str
    outcomes: list[dict]  # [{"label", "token_id", "yes_price", "no_price"}]
    sum_of_prices: float = 0.0
    deviation: float = 0.0
    num_outcomes: int = 0


@dataclass
class FairProbResult:
    """Result of fair probability calculation for a neg-risk event."""

    event_id: str
    fair_probs: list[float]  # normalized fair probabilities per outcome
    market_probs: list[float]  # current market probabilities
    mispricings: list[float]  # fair - market per outcome (positive = underpriced)
    sum_deviation: float  # |sum(market_probs) - 1.0|
    kelly_bets: list[float]  # Kelly-optimal bet sizes in USD per outcome


@dataclass
class NegRiskOrder:
    """A multi-leg neg-risk order to place."""

    event_id: str
    outcome_label: str
    token_id: str
    side: str  # "BUY"
    price: float
    size_usd: float
    edge: float
    kelly_fraction: float


# ---------------------------------------------------------------------------
# Fair probability calculation
# ---------------------------------------------------------------------------


def calculate_fair_probabilities(outcome_prices: list[float]) -> list[float]:
    """
    Calculate fair (normalized) probabilities from market prices.

    In a correctly priced neg-risk market all YES prices sum to 1.0.
    When they don't we normalize to get fair probabilities::

        fair_prob_i = price_i / sum(prices)
    """
    total = sum(outcome_prices)
    if total <= 0:
        n = len(outcome_prices)
        return [1.0 / n] * n
    return [p / total for p in outcome_prices]


def calculate_kelly_bets(
    fair_probs: list[float],
    market_probs: list[float],
    bankroll: float,
    kelly_fraction: float = 0.25,
    max_bet_frac: float = 0.10,
) -> list[float]:
    """
    Calculate Kelly-optimal bet sizes for each outcome.

    Kelly criterion for multi-outcome markets::

        f_i = max(0, (p_i * b_i - q_i) / b_i)

    where *p_i* = fair probability, *b_i* = payout odds, *q_i* = 1 - p_i.

    The result is fractionally adjusted by *kelly_fraction* and capped at
    *max_bet_frac* of the bankroll.
    """
    bets: list[float] = []
    for fair_p, market_p in zip(fair_probs, market_probs):
        if market_p <= 0.01 or market_p >= 0.99:
            bets.append(0.0)
            continue

        # Payout odds: buy YES at market_p -> receive 1.0 on win
        b = (1.0 / market_p) - 1.0
        q = 1.0 - fair_p

        if b <= 0:
            bets.append(0.0)
            continue

        kelly_f = (fair_p * b - q) / b
        kelly_f = max(0.0, kelly_f)

        bet_size = kelly_f * kelly_fraction * bankroll
        bet_size = min(bet_size, max_bet_frac * bankroll)
        bets.append(round(bet_size, 2))

    return bets


# ---------------------------------------------------------------------------
# Event detection
# ---------------------------------------------------------------------------


def detect_neg_risk_events(
    markets: list[dict],
    min_outcomes: int = 3,
    min_sum_deviation: float = 0.01,
) -> list[NegRiskEvent]:
    """
    Detect neg-risk events from a flat list of markets.

    Groups markets by *slug* (Polymarket groups multi-outcome markets under
    a single event).  An event is neg-risk when it has >= *min_outcomes*
    mutually exclusive outcomes whose YES prices deviate from 1.0.
    """
    events: dict[str, list[dict]] = {}
    for m in markets:
        slug = m.get("slug", "")
        if not slug:
            continue
        events.setdefault(slug, []).append(m)

    neg_risk_events: list[NegRiskEvent] = []
    for slug, outcomes in events.items():
        if len(outcomes) < min_outcomes:
            continue

        prices: list[float] = []
        parsed: list[dict] = []
        for o in outcomes:
            yes_p = float(o.get("yes_price", 0.5))
            no_p = float(o.get("no_price", 0.5))
            token_id = o.get("token_id", o.get("market_id", ""))
            prices.append(yes_p)
            parsed.append(
                {
                    "label": o.get("question", o.get("slug", "")),
                    "token_id": str(token_id),
                    "yes_price": yes_p,
                    "no_price": no_p,
                }
            )

        price_sum = sum(prices)
        deviation = abs(price_sum - 1.0)

        if deviation < min_sum_deviation:
            continue

        neg_risk_events.append(
            NegRiskEvent(
                event_id=slug,
                slug=slug,
                question=outcomes[0].get("question", ""),
                outcomes=parsed,
                sum_of_prices=price_sum,
                deviation=deviation,
                num_outcomes=len(parsed),
            )
        )

    neg_risk_events.sort(key=lambda e: e.deviation, reverse=True)
    return neg_risk_events


# ---------------------------------------------------------------------------
# Order construction
# ---------------------------------------------------------------------------


def construct_orders(
    event: NegRiskEvent,
    fair_result: FairProbResult,
    min_edge: float = 0.02,
    max_position_usd: float = 50.0,
) -> list[NegRiskOrder]:
    """
    Construct multi-leg orders for a neg-risk event.

    For each outcome where mispricing exceeds *min_edge*:
      - underpriced (mispricing > 0) -> BUY YES
      - overpriced  (mispricing < -min_edge) -> BUY NO (= BUY at no_price)

    Sizes are Kelly-optimal capped at *max_position_usd* per leg.
    """
    orders: list[NegRiskOrder] = []
    min_order = float(_cfg("MIN_ORDER_USDC", 5.0))

    for i, outcome in enumerate(event.outcomes):
        edge = fair_result.mispricings[i]
        kelly_usd = fair_result.kelly_bets[i]

        if abs(edge) < min_edge:
            continue
        if kelly_usd <= 0:
            continue

        size = min(kelly_usd, max_position_usd)
        if size < min_order:
            continue

        if edge > 0:
            # Underpriced -> BUY YES
            orders.append(
                NegRiskOrder(
                    event_id=event.event_id,
                    outcome_label=outcome["label"],
                    token_id=outcome["token_id"],
                    side="BUY",
                    price=outcome["yes_price"],
                    size_usd=round(size, 2),
                    edge=round(edge, 4),
                    kelly_fraction=kelly_usd / max(1.0, max_position_usd),
                )
            )
        else:
            # Overpriced -> BUY NO (= SELL YES)
            orders.append(
                NegRiskOrder(
                    event_id=event.event_id,
                    outcome_label=outcome["label"],
                    token_id=outcome["token_id"],
                    side="BUY",
                    price=outcome["no_price"],
                    size_usd=round(size, 2),
                    edge=round(abs(edge), 4),
                    kelly_fraction=kelly_usd / max(1.0, max_position_usd),
                )
            )

    return orders


# ---------------------------------------------------------------------------
# Strategy
# ---------------------------------------------------------------------------


class NegRiskStrategy(BaseStrategy):
    """
    Negative-risk multi-outcome portfolio strategy.

    Pipeline:
      1. Discover neg-risk events (group by slug, outcomes >= N)
      2. Calculate fair probabilities by normalizing market prices
      3. Detect mispricings (|fair - market| > min_edge)
      4. Construct multi-leg orders with Kelly sizing
      5. Execute via CLOB (with neg_risk-aware settlement)
    """

    name = "negrisk_strategy"
    description = (
        "Neg-risk multi-outcome portfolio: discovers events, calculates fair "
        "probabilities, detects mispricings, places multi-leg Kelly-sized orders"
    )
    category = "arb"
    default_params = {
        "min_outcomes": 3,
        "min_sum_deviation": 0.01,
        "min_edge": 0.02,
        "max_position_usd": 50.0,
        "kelly_fraction": 0.25,
        "bankroll_fraction": 0.08,
        "enabled": True,
    }

    async def run_cycle(self, ctx: StrategyContext) -> CycleResult:
        """Execute one neg-risk strategy cycle."""
        start = time.monotonic()
        errors: list[str] = []
        decisions_recorded = 0
        trades_attempted = 0
        trades_placed = 0

        # Merge DB params with defaults
        p = {**self.default_params, **(ctx.params or {})}
        min_outcomes = int(p.get("min_outcomes", 3))
        min_sum_deviation = float(p.get("min_sum_deviation", 0.01))
        min_edge = float(p.get("min_edge", 0.02))
        max_position_usd = float(p.get("max_position_usd", 50.0))
        kelly_fraction = float(p.get("kelly_fraction", 0.25))

        try:
            # 1. Fetch markets
            markets = await self._fetch_markets(ctx)
            if not markets:
                ctx.logger.info("[negrisk] No markets fetched")
                return CycleResult(0, 0, 0, errors=errors)

            # 2. Detect neg-risk events
            events = detect_neg_risk_events(
                markets,
                min_outcomes=min_outcomes,
                min_sum_deviation=min_sum_deviation,
            )
            ctx.logger.info("[negrisk] Found %d neg-risk events", len(events))

            # 3. Bankroll for Kelly sizing
            bankroll = await self._get_bankroll(ctx)

            # 4. Process each event
            for event in events:
                try:
                    outcome_prices = [o["yes_price"] for o in event.outcomes]

                    fair_probs = calculate_fair_probabilities(outcome_prices)
                    market_probs = outcome_prices
                    mispricings = [f - m for f, m in zip(fair_probs, market_probs)]

                    kelly_bets = calculate_kelly_bets(
                        fair_probs=fair_probs,
                        market_probs=market_probs,
                        bankroll=bankroll,
                        kelly_fraction=kelly_fraction,
                        max_bet_frac=float(p.get("bankroll_fraction", 0.08)),
                    )

                    fair_result = FairProbResult(
                        event_id=event.event_id,
                        fair_probs=fair_probs,
                        market_probs=market_probs,
                        mispricings=mispricings,
                        sum_deviation=event.deviation,
                        kelly_bets=kelly_bets,
                    )

                    orders = construct_orders(
                        event=event,
                        fair_result=fair_result,
                        min_edge=min_edge,
                        max_position_usd=max_position_usd,
                    )

                    if not orders:
                        continue

                    decisions_recorded += len(orders)

                    # 5. Execute
                    for order in orders:
                        trades_attempted += 1
                        result = await self._execute_order(ctx, order)
                        if result and result.get("success"):
                            trades_placed += 1
                        elif result:
                            errors.append(result.get("error", "unknown"))

                except Exception as exc:
                    ctx.logger.warning(
                        "[negrisk] Error processing event %s: %s",
                        event.event_id,
                        exc,
                    )
                    errors.append(str(exc))

            elapsed_ms = (time.monotonic() - start) * 1000
            return CycleResult(
                decisions_recorded=decisions_recorded,
                trades_attempted=trades_attempted,
                trades_placed=trades_placed,
                errors=errors,
                cycle_duration_ms=elapsed_ms,
            )

        except Exception as exc:
            ctx.logger.exception("[negrisk] Cycle failed: %s", exc)
            return CycleResult(0, 0, 0, errors=[str(exc)])

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _fetch_markets(self, ctx: StrategyContext) -> list[dict]:
        """Fetch markets via Gamma API, falling back to MarketUniverseScanner."""
        try:
            from backend.data.gamma import fetch_markets

            return await fetch_markets(limit=2000)
        except Exception as exc:
            ctx.logger.warning("[negrisk] Gamma fetch failed, trying scanner: %s", exc)

        try:
            from backend.data.market_universe import MarketUniverseScanner

            scanner = MarketUniverseScanner()
            return await scanner.get_active_markets(limit=2000)
        except Exception as exc:
            ctx.logger.error("[negrisk] Market fetch failed: %s", exc)
            return []

    async def _get_bankroll(self, ctx: StrategyContext) -> float:
        """Get current bankroll for Kelly sizing."""
        try:
            if ctx.clob and hasattr(ctx.clob, "get_wallet_balance"):
                bal = await ctx.clob.get_wallet_balance()
                return float(bal.get("usdc_balance", 100.0))
        except Exception:
            pass
        return float(_cfg("NEGRISK_DEFAULT_BANKROLL", 100.0))

    async def _execute_order(
        self, ctx: StrategyContext, order: NegRiskOrder
    ) -> Optional[dict]:
        """Execute a single neg-risk order via CLOB."""
        if ctx.clob is None:
            ctx.logger.debug(
                "[negrisk] Paper mode -- skipping order for %s",
                order.outcome_label,
            )
            return {"success": True, "paper": True}

        try:
            result = await ctx.clob.place_limit_order(
                token_id=order.token_id,
                side=order.side,
                price=order.price,
                size=order.size_usd,
            )
            if result.success:
                ctx.logger.info(
                    "[negrisk] %s %.2f @ %.3f for %s (edge=%.4f)",
                    order.side,
                    order.size_usd,
                    order.price,
                    order.outcome_label,
                    order.edge,
                )
                return {"success": True, "order_id": result.order_id}
            else:
                return {"success": False, "error": result.error or "order failed"}
        except Exception as exc:
            ctx.logger.error("[negrisk] Order execution failed: %s", exc)
            return {"success": False, "error": str(exc)}
