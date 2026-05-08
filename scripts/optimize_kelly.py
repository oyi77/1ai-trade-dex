"""Optimize Kelly fraction per strategy using historical Trade data."""
import argparse
import sys

from backend.models.database import SessionLocal, Trade, StrategyConfig


def simulate_kelly(trades, kelly_fraction):
    bankroll = 10000.0
    peak = bankroll
    max_drawdown = 0.0

    for trade in trades:
        pnl = float(trade.pnl or 0)
        if pnl > 0:
            bankroll += bankroll * kelly_fraction * (pnl / abs(pnl))
        else:
            bankroll -= bankroll * kelly_fraction * abs(pnl) / max(abs(pnl), 0.01)
        bankroll = max(0.0, bankroll)
        peak = max(peak, bankroll)
        dd = (peak - bankroll) / peak if peak > 0 else 0
        max_drawdown = max(max_drawdown, dd)

    pnl = bankroll - 10000.0
    win_rate = sum(1 for t in trades if (t.pnl or 0) > 0) / len(trades) if trades else 0
    sharpe = pnl / max(1, (len(trades) ** 0.5)) if trades else 0
    return {"pnl": pnl, "sharpe": sharpe, "max_dd": max_drawdown, "win_rate": win_rate}


def optimize(min_trades=10):
    db = SessionLocal()
    try:
        strategies = db.query(StrategyConfig).all()
        fractions = [0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.40, 0.50]

        results = {}
        for strat in strategies:
            name = strat.strategy_name
            trades = (
                db.query(Trade)
                .filter(Trade.strategy == name, Trade.settled.is_(True))
                .all()
            )
            if len(trades) < min_trades:
                print(f"[SKIP] {name}: {len(trades)} trades (min {min_trades})")
                continue

            for kf in fractions:
                sim = simulate_kelly(trades, kf)
                key = f"{name}_k{kf:.2f}"
                results[key] = {"kelly": kf, **sim}

            best_key = max(
                (k for k in results if k.startswith(name)),
                key=lambda k: results[k]["sharpe"],
            )
            best = results[best_key]
            print(
                f"[BEST] {name}: kelly={best['kelly']:.2f} "
                f"sharpe={best['sharpe']:.2f} "
                f"pnl=${best['pnl']:.2f} "
                f"max_dd={best['max_dd']:.1%} "
                f"win_rate={best['win_rate']:.1%}"
            )
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Optimize Kelly fractions")
    parser.add_argument("--min-trades", type=int, default=10)
    args = parser.parse_args()
    optimize(min_trades=args.min_trades)
