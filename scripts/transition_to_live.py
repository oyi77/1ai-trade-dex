#!/usr/bin/env python3
"""Live Trading Transition Script.

Reads paper trading P&L, checks if strategies are profitable,
and prints a go/no-go decision for live trading.

Requirements for GO:
- Paper Sharpe > 1.0 over 7 days
- Win rate > 50%
- Positive P&L
"""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.db.utils import get_db_session
from backend.models.database import Trade, StrategyConfig
from sqlalchemy import func


def calculate_sharpe_ratio(returns: list[float]) -> float:
    """Calculate annualized Sharpe ratio from daily returns."""
    if len(returns) < 2:
        return 0.0
    avg_return = sum(returns) / len(returns)
    variance = sum((r - avg_return) ** 2 for r in returns) / (len(returns) - 1)
    std_dev = variance ** 0.5
    if std_dev == 0:
        return 0.0
    # Annualize (assuming 252 trading days)
    return (avg_return / std_dev) * (252 ** 0.5)


def main():
    """Check paper trading performance and make live transition decision."""
    print("=" * 60)
    print("LIVE TRADING TRANSITION CHECK")
    print("=" * 60)

    cutoff_date = datetime.now(timezone.utc) - timedelta(days=7)

    with get_db_session() as db:
        # Get paper trades from last 7 days
        paper_trades = (
            db.query(Trade)
            .filter(
                Trade.trading_mode == "paper",
                Trade.settled == True,
                Trade.settlement_time >= cutoff_date,
            )
            .all()
        )

        if not paper_trades:
            print("\n[NO GO] No settled paper trades in last 7 days")
            print("Need at least some paper trading history before going live.")
            return

        # Calculate metrics
        wins = sum(1 for t in paper_trades if t.result == "win")
        losses = sum(1 for t in paper_trades if t.result == "loss")
        total = wins + losses
        win_rate = wins / total if total > 0 else 0

        total_pnl = sum(t.pnl or 0 for t in paper_trades)

        # Calculate daily returns for Sharpe
        daily_pnl = {}
        for trade in paper_trades:
            date = trade.settlement_time.date()
            daily_pnl[date] = daily_pnl.get(date, 0) + (trade.pnl or 0)

        # Get initial bankroll for return calculation
        from backend.models.database import BotState
        state = db.query(BotState).filter_by(mode="paper").first()
        initial_bankroll = state.paper_bankroll if state else 1000.0

        daily_returns = [pnl / initial_bankroll for pnl in daily_pnl.values()]
        sharpe = calculate_sharpe_ratio(daily_returns)

        # Get strategy breakdown
        strategy_stats = {}
        for trade in paper_trades:
            strategy = trade.strategy
            if strategy not in strategy_stats:
                strategy_stats[strategy] = {"wins": 0, "losses": 0, "pnl": 0}
            if trade.result == "win":
                strategy_stats[strategy]["wins"] += 1
            elif trade.result == "loss":
                strategy_stats[strategy]["losses"] += 1
            strategy_stats[strategy]["pnl"] += (trade.pnl or 0)

        # Print report
        print(f"\nPeriod: Last 7 days")
        print(f"Total trades: {total}")
        print(f"Win rate: {win_rate:.1%}")
        print(f"Total P&L: ${total_pnl:.2f}")
        print(f"Sharpe ratio: {sharpe:.2f}")

        print("\n--- Strategy Breakdown ---")
        for strategy, stats in strategy_stats.items():
            strat_total = stats["wins"] + stats["losses"]
            strat_wr = stats["wins"] / strat_total if strat_total > 0 else 0
            print(f"  {strategy}: {strat_total} trades, {strat_wr:.1%} WR, ${stats['pnl']:.2f} P&L")

        # Decision
        print("\n" + "=" * 60)
        print("DECISION:")
        print("=" * 60)

        reasons = []
        go = True

        if sharpe <= 1.0:
            go = False
            reasons.append(f"Sharpe ratio {sharpe:.2f} <= 1.0 (required > 1.0)")

        if win_rate <= 0.50:
            go = False
            reasons.append(f"Win rate {win_rate:.1%} <= 50% (required > 50%)")

        if total_pnl <= 0:
            go = False
            reasons.append(f"Total P&L ${total_pnl:.2f} <= 0 (required positive)")

        if go:
            print("\n*** GO - Ready for live trading ***")
            print("All criteria met:")
            print(f"  - Sharpe ratio: {sharpe:.2f} > 1.0")
            print(f"  - Win rate: {win_rate:.1%} > 50%")
            print(f"  - Total P&L: ${total_pnl:.2f} > 0")
        else:
            print("\n*** NO GO - Not ready for live trading ***")
            print("Failed criteria:")
            for reason in reasons:
                print(f"  - {reason}")

        print("=" * 60)
        return go


if __name__ == "__main__":
    result = main()
    sys.exit(0 if result else 1)
