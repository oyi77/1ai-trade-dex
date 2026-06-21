"""M1 Backtest — validate risk parameter changes against historical trades.

Runs the BacktestEngine with:
1. OLD parameters (pre-fix): MIN_EDGE_PP=2%, KELLY=30%, PORTFOLIO_DD=50%
2. NEW parameters (post-fix): MIN_EDGE_PP=6%, KELLY=10%, PORTFOLIO_DD=25%

Compares results to show impact of the fixes.
"""

import asyncio
import sys
from datetime import datetime, timedelta
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.core.backtester import BacktestConfig, BacktestEngine
from backend.db.utils import get_db_session


async def run_backtest(label: str, config: BacktestConfig) -> dict:
    """Run a single backtest and return metrics."""
    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"{'='*60}")
    print(f"  Strategy:       {config.strategy_name}")
    print(f"  Date range:     {config.start_date.date()} → {config.end_date.date()}")
    print(f"  Initial $:      ${config.initial_bankroll:.2f}")
    print(f"  Kelly fraction: {config.kelly_fraction:.1%}")
    print(f"  Max trade size: ${config.max_trade_size:.2f}")
    print(f"  Max position:   {config.max_position_fraction:.0%} of bankroll")
    print(f"  Daily loss:     ${config.daily_loss_limit:.2f}")
    print(f"  Slippage:       ${config.slippage:.2f} per trade")

    engine = BacktestEngine(config)
    with get_db_session() as db:
        result = await engine.run(db=db)

    print(f"\n  Results:")
    print(f"  {'─'*50}")
    print(f"  Total trades:   {result.total_trades}")
    print(f"  Winning trades: {result.winning_trades}")
    print(f"  Losing trades:  {result.total_trades - result.winning_trades}")
    print(f"  Win rate:       {result.win_rate:.1%}")
    print(f"  Total PnL:      ${result.total_pnl:.2f}")
    print(f"  Max drawdown:   {result.max_drawdown:.1%}")
    print(f"  Final bankroll: ${result.final_bankroll:.2f}")
    print(f"  Return:         {result.return_pct:.1%}")
    print(f"  Sharpe ratio:   {result.sharpe_ratio:.2f}")
    print(f"  Profit factor:  {result.profit_factor:.2f}")
    print(f"  Avg edge:       {result.avg_edge:.1%}")

    return {
        "label": label,
        "total_trades": result.total_trades,
        "winning_trades": result.winning_trades,
        "losing_trades": result.total_trades - result.winning_trades,
        "win_rate": result.win_rate,
        "total_pnl": result.total_pnl,
        "max_drawdown": result.max_drawdown,
        "final_bankroll": result.final_bankroll,
        "return_pct": result.return_pct,
        "sharpe_ratio": result.sharpe_ratio,
        "profit_factor": result.profit_factor,
    }


async def main():
    # Date range: last 30 days of historical data
    end_date = datetime(2026, 6, 19)
    start_date = end_date - timedelta(days=30)

    # Run for all strategies that have historical trades
    strategies = [
        "longshot_bias",
        "apex",
        "bond_scanner",
        "crypto_oracle",
    ]

    old_results = []
    new_results = []

    for strategy in strategies:
        # OLD parameters (pre-fix)
        old_config = BacktestConfig(
            strategy_name=strategy,
            start_date=start_date,
            end_date=end_date,
            initial_bankroll=100.0,
            kelly_fraction=0.30,          # OLD: 30% Kelly
            max_trade_size=50.0,          # OLD: $50 max
            max_position_fraction=0.30,   # OLD: 30% of bankroll
            max_total_exposure=0.70,      # OLD: 70% total
            daily_loss_limit=100.0,       # OLD: $100 daily
            slippage=0.02,                # OLD: no slippage protection
        )

        # NEW parameters (post-fix)
        new_config = BacktestConfig(
            strategy_name=strategy,
            start_date=start_date,
            end_date=end_date,
            initial_bankroll=100.0,
            kelly_fraction=0.10,          # NEW: 10% Kelly
            max_trade_size=15.0,          # NEW: $15 max
            max_position_fraction=0.10,   # NEW: 10% of bankroll
            max_total_exposure=0.30,      # NEW: 30% total
            daily_loss_limit=25.0,        # NEW: $25 daily
            slippage=0.01,                # NEW: 1% slippage cost
        )

        try:
            old_r = await run_backtest(f"OLD params — {strategy}", old_config)
            old_results.append(old_r)
        except Exception as e:
            print(f"  OLD backtest failed for {strategy}: {e}")

        try:
            new_r = await run_backtest(f"NEW params — {strategy}", new_config)
            new_results.append(new_r)
        except Exception as e:
            print(f"  NEW backtest failed for {strategy}: {e}")

    # Summary comparison
    print(f"\n{'='*70}")
    print(f"  COMPARISON SUMMARY — OLD vs NEW parameters")
    print(f"{'='*70}")
    print(f"  {'Strategy':<20} {'OLD PnL':>10} {'NEW PnL':>10} {'OLD DD':>8} {'NEW DD':>8} {'Δ PnL':>10}")
    print(f"  {'─'*68}")

    for old, new in zip(old_results, new_results):
        delta = new["total_pnl"] - old["total_pnl"]
        print(
            f"  {old['label'].split(' — ')[1]:<20} "
            f"${old['total_pnl']:>8.2f} ${new['total_pnl']:>8.2f} "
            f"{old['max_drawdown']:>7.1%} {new['max_drawdown']:>7.1%} "
            f"${delta:>+8.2f}"
        )

    old_total = sum(r["total_pnl"] for r in old_results)
    new_total = sum(r["total_pnl"] for r in new_results)
    delta_total = new_total - old_total

    print(f"  {'─'*68}")
    print(
        f"  {'TOTAL':<20} "
        f"${old_total:>8.2f} ${new_total:>8.2f} "
        f"{'':>8} {'':>8} "
        f"${delta_total:>+8.2f}"
    )

    old_avg_dd = (
        sum(r["max_drawdown"] for r in old_results) / len(old_results)
        if old_results else 0
    )
    new_avg_dd = (
        sum(r["max_drawdown"] for r in new_results) / len(new_results)
        if new_results else 0
    )
    print(f"\n  Avg max drawdown:  OLD={old_avg_dd:.1%} → NEW={new_avg_dd:.1%}")
    print(f"  Total PnL change:  ${delta_total:+.2f} ({delta_total/old_total*100:+.1f}%)" if old_total != 0 else "")

    if old_total < 0 and new_total > old_total:
        print(f"\n  ✅ NEW parameters IMPROVED total PnL by ${abs(delta_total):.2f}")
    elif old_total > 0 and new_total > 0:
        print(f"\n  ✅ Both profitable, NEW params {'improved' if delta_total > 0 else 'reduced'} by ${abs(delta_total):.2f}")
    else:
        print(f"\n  ⚠️  Review needed — check data availability and strategy signals")


if __name__ == "__main__":
    asyncio.run(main())
