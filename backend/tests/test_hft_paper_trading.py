"""HFT Paper Trading Validation — simulate HFT strategies over 30 days."""

import random
import logging
from dataclasses import dataclass

logger = logging.getLogger("trading_bot.hft_paper")

SIMULATION_DAYS = 30


@dataclass
class PaperTrade:
    market_id: str
    side: str
    entry_price: float
    size: float
    pnl: float
    win: bool


@dataclass
class SimulationResult:
    starting_bankroll: float
    ending_bankroll: float
    monthly_return: float
    total_trades: int
    winning_trades: int
    losing_trades: int
    max_drawdown: float
    sharpe_ratio: float
    avg_latency_ms: float
    trades: list[PaperTrade]


def simulate_hft_day(bankroll: float, signals: int = 50) -> tuple[float, list[PaperTrade]]:
    """Simulate one day of HFT trading."""
    trades = []
    daily_pnl = 0.0

    for _ in range(signals):
        entry = random.uniform(0.01, 0.99)
        exit_price = entry + random.gauss(0, 0.02)
        size = bankroll * 0.25 * random.uniform(0.5, 1.0)

        pnl = (exit_price - entry) * size if random.random() > 0.4 else -(abs(exit_price - entry) * size * 0.5)
        win = pnl > 0

        trades.append(PaperTrade(
            market_id=f"sim-{random.randint(1, 10000)}",
            side="BUY",
            entry_price=entry,
            size=size,
            pnl=pnl,
            win=win,
        ))
        daily_pnl += pnl

    return bankroll + daily_pnl, trades


def simulate_30_days(starting_bankroll: float = 100.0, daily_target_return: float = 0.023) -> SimulationResult:
    """
    Simulate 30 days of HFT paper trading.

    Target: 100%+ monthly return ($100 → $200+ in 30 days).
    Daily target: ~2.3% compounded = 100% monthly.
    """
    bankroll = starting_bankroll
    all_trades: list[PaperTrade] = []
    peak = bankroll
    daily_returns = []

    for day in range(SIMULATION_DAYS):
        prev = bankroll
        bankroll, trades = simulate_hft_day(bankroll, signals=50)
        all_trades.extend(trades)

        if bankroll > peak:
            peak = bankroll
        daily_returns.append((bankroll - prev) / prev)

    winning = sum(1 for t in all_trades if t.win)
    losing = len(all_trades) - winning
    max_dd = (peak - bankroll) / peak if peak > 0 else 0.0

    mean_ret = sum(daily_returns) / len(daily_returns) if daily_returns else 0.0
    std_ret = (sum((r - mean_ret) ** 2 for r in daily_returns) / len(daily_returns)) ** 0.5 if daily_returns else 1.0
    sharpe = (mean_ret / std_ret * (252 ** 0.5)) if std_ret > 0 else 0.0

    monthly_return = (bankroll - starting_bankroll) / starting_bankroll

    return SimulationResult(
        starting_bankroll=starting_bankroll,
        ending_bankroll=bankroll,
        monthly_return=monthly_return,
        total_trades=len(all_trades),
        winning_trades=winning,
        losing_trades=losing,
        max_drawdown=max_dd,
        sharpe_ratio=sharpe,
        avg_latency_ms=15.0,
        trades=all_trades,
    )


def monte_carlo(n_runs: int = 1000, starting: float = 100.0) -> dict:
    """Run Monte Carlo simulation. Returns percentile outcomes."""
    results = []
    for _ in range(n_runs):
        r = simulate_30_days(starting)
        results.append(r.ending_bankroll)

    results.sort()
    return {
        "p10": results[int(n_runs * 0.1)],
        "p50": results[int(n_runs * 0.5)],
        "p90": results[int(n_runs * 0.9)],
        "p99": results[int(n_runs * 0.99)],
        "mean": sum(results) / len(results),
    }


def tail_risk_analysis(n_scenarios: int = 1000, starting: float = 100.0) -> dict:
    """Analyze worst-case scenarios (tail risk)."""
    outcomes = []
    for _ in range(n_scenarios):
        r = simulate_30_days(starting)
        outcomes.append(r.ending_bankroll)

    worst_1pct = sorted(outcomes)[:int(n_scenarios * 0.01)]
    return {
        "worst_1pct_mean": sum(worst_1pct) / len(worst_1pct) if worst_1pct else 0,
        "worst_case": min(outcomes),
        "best_case": max(outcomes),
        "prob_below_zero": sum(1 for o in outcomes if o <= 0) / len(outcomes),
    }
