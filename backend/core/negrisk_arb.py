"""
Neg-Risk Arbitrage Scanner for PolyEdge.

Groups markets by event and detects opportunities where the sum of YES
prices across mutually exclusive outcomes deviates meaningfully from 1.0.
"""

from dataclasses import dataclass

from loguru import logger

from backend.fee_config import TAKER_FEE_RATE as DEFAULT_FEE_RATE
DEFAULT_MIN_DEVIATION = 0.02  # minimum net deviation to flag as opportunity
DEFAULT_MIN_OUTCOMES = 3  # require at least this many outcomes per event


@dataclass
class NegRiskOpportunity:
    event_id: str
    outcomes: list[dict]  # [{"label": str, "price": float, "token_id": str}]
    sum_of_prices: float
    deviation: float  # abs(sum_of_prices - 1.0)
    profit_after_fees: float


def scan_negrisk_opportunities(
    markets_by_event: dict[str, list[dict]],
    fee_rate: float = DEFAULT_FEE_RATE,
    min_deviation: float = DEFAULT_MIN_DEVIATION,
    min_outcomes: int = DEFAULT_MIN_OUTCOMES,
) -> list[NegRiskOpportunity]:
    """
    Scan events for neg-risk arbitrage opportunities.

    Args:
        markets_by_event: Mapping of event_id -> list of outcome dicts.
            Each outcome dict must contain at minimum:
              - "price"    (float): current YES price
              - "label"    (str):   outcome label, e.g. "Candidate A wins"
              - "token_id" (str):   on-chain token identifier
        fee_rate: Per-leg fee as a fraction (default 2%).
        min_deviation: Minimum net profit after fees to include in results.
        min_outcomes: Minimum number of outcomes required to consider an event.

    Returns:
        List of NegRiskOpportunity, sorted by profit_after_fees descending.
    """
    opportunities: list[NegRiskOpportunity] = []

    for event_id, outcomes in markets_by_event.items():
        if len(outcomes) < min_outcomes:
            continue

        # Validate that each outcome has a numeric price
        valid_outcomes = []
        for o in outcomes:
            try:
                price = float(o.get("price", 0.0))
                valid_outcomes.append(
                    {
                        "label": str(o.get("label", "")),
                        "price": price,
                        "token_id": str(o.get("token_id", "")),
                    }
                )
            except (TypeError, ValueError) as e:
                logger.warning(
                    f"negrisk_arb: skipping malformed outcome in event {event_id}: {e}"
                )

        if len(valid_outcomes) < min_outcomes:
            continue

        price_sum = sum(o["price"] for o in valid_outcomes)
        deviation = abs(price_sum - 1.0)
        total_fees = fee_rate * len(valid_outcomes)
        profit_after_fees = deviation - total_fees

        if profit_after_fees <= min_deviation:
            continue

        opportunities.append(
            NegRiskOpportunity(
                event_id=event_id,
                outcomes=valid_outcomes,
                sum_of_prices=price_sum,
                deviation=deviation,
                profit_after_fees=profit_after_fees,
            )
        )

        logger.info(
            f"negrisk_arb: event={event_id} outcomes={len(valid_outcomes)} "
            f"sum={price_sum:.4f} deviation={deviation:.4f} "
            f"profit_after_fees={profit_after_fees:.4f}"
        )

    # Sort best opportunities first
    opportunities.sort(key=lambda o: o.profit_after_fees, reverse=True)
    return opportunities
