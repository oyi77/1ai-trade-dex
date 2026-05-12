"""Portfolio optimizer using risk-parity allocation based on Sharpe ratios."""
from dataclasses import dataclass

from loguru import logger
@dataclass
class StrategyMetrics:
    name: str
    total_pnl: float
    trade_count: int
    win_rate: float
    sharpe_ratio: float  # annualized
    max_drawdown: float
    avg_edge: float


@dataclass
class AllocationResult:
    allocations: dict[str, float]  # strategy_name -> weight [0, 1]
    total_exposure: float
    reasoning: list[str]


class PortfolioOptimizer:
    """Risk-parity portfolio optimizer for trading strategies."""

    def __init__(
        self,
        max_total_exposure: float = 0.50,
        max_per_strategy: float = 0.30,
    ) -> None:
        self.max_total_exposure = max_total_exposure
        self.max_per_strategy = max_per_strategy

    def allocate(
        self,
        strategy_metrics: list[StrategyMetrics],
        bankroll: float,
    ) -> AllocationResult:
        """Allocate bankroll across strategies using risk-parity (Sharpe-weighted).

        Steps:
        1. Exclude strategies with non-positive Sharpe ratio.
        2. Compute raw weights proportional to Sharpe.
        3. Normalize so weights sum to max_total_exposure.
        4. Cap each weight at max_per_strategy, then re-normalize.
        """
        allocations: dict[str, float] = {}
        reasoning: list[str] = []

        eligible = []
        for m in strategy_metrics:
            if m.sharpe_ratio <= 0:
                allocations[m.name] = 0.0
                reasoning.append(
                    f"{m.name}: excluded (Sharpe={m.sharpe_ratio:.3f} <= 0)"
                )
                logger.debug("Excluding %s: non-positive Sharpe %.3f", m.name, m.sharpe_ratio)
            else:
                eligible.append(m)

        if not eligible:
            reasoning.append("No eligible strategies; all allocations set to 0.")
            return AllocationResult(
                allocations=allocations,
                total_exposure=0.0,
                reasoning=reasoning,
            )

        sharpe_sum = sum(m.sharpe_ratio for m in eligible)

        # Raw weights normalized to max_total_exposure, capped at max_per_strategy
        raw: dict[str, float] = {
            m.name: (m.sharpe_ratio / sharpe_sum) * self.max_total_exposure
            for m in eligible
        }

        # Apply per-strategy cap and iterate until stable
        MAX_ITERS = 20
        for _ in range(MAX_ITERS):
            capped = {n: min(w, self.max_per_strategy) for n, w in raw.items()}
            capped_sum = sum(capped.values())

            uncapped = {n: w for n, w in raw.items() if w < self.max_per_strategy}
            if not uncapped or abs(capped_sum - self.max_total_exposure) < 1e-9:
                raw = capped
                break

            # Redistribute surplus from capped strategies to uncapped ones
            capped_total = sum(min(w, self.max_per_strategy) for n, w in raw.items() if n not in uncapped)
            uncapped_sum = sum(uncapped.values())
            surplus = self.max_total_exposure - capped_total - uncapped_sum

            if uncapped_sum <= 0 or surplus <= 0:
                # No room to redistribute — cap everything and stop
                raw = capped
                break

            new_raw: dict[str, float] = {}
            for n, w in raw.items():
                if n in uncapped:
                    new_raw[n] = w + surplus * (w / uncapped_sum)
                else:
                    new_raw[n] = min(w, self.max_per_strategy)
            raw = new_raw
        else:
            raw = {n: min(w, self.max_per_strategy) for n, w in raw.items()}

        for m in eligible:
            weight = raw[m.name]
            allocations[m.name] = weight
            dollar_amount = weight * bankroll
            reasoning.append(
                f"{m.name}: weight={weight:.4f} (${dollar_amount:.2f}), "
                f"Sharpe={m.sharpe_ratio:.3f}, "
                f"Sharpe share={m.sharpe_ratio / sharpe_sum:.3f}"
            )
            logger.debug(
                "Allocated %s: weight=%.4f sharpe=%.3f",
                m.name,
                weight,
                m.sharpe_ratio,
            )

        total_exposure = sum(allocations.values())
        reasoning.append(f"Total exposure: {total_exposure:.4f} of bankroll ${bankroll:.2f}")

        return AllocationResult(
            allocations=allocations,
            total_exposure=total_exposure,
            reasoning=reasoning,
        )

    def rebalance_needed(
        self,
        current_allocations: dict[str, float],
        target: AllocationResult,
        drift_tolerance: float = 0.05,
    ) -> bool:
        """Return True if any strategy drifts more than drift_tolerance from target."""
        all_keys = set(current_allocations) | set(target.allocations)
        for key in all_keys:
            current = current_allocations.get(key, 0.0)
            desired = target.allocations.get(key, 0.0)
            if abs(current - desired) > drift_tolerance:
                logger.debug(
                    "Rebalance needed: %s current=%.4f target=%.4f drift=%.4f",
                    key,
                    current,
                    desired,
                    abs(current - desired),
                )
                return True
        return False
