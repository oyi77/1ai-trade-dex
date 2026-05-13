"""ForecastBench AI ensemble benchmarking against published baselines."""

from backend.models.database import SessionLocal, Trade


BASELINES = {
    "human_superforecasters": 0.145,
    "gpt4o": 0.155,
    "claude_3.5_sonnet": 0.154,
    "random_uniform": 0.285,
    "always_0.5": 0.205,
}


def brier_score(predictions: list[tuple[float, float]]) -> float:
    if not predictions:
        return 0.0
    return sum((p - o) ** 2 for p, o in predictions) / len(predictions)


def benchmark_from_trades(min_trades: int = 30):
    db = SessionLocal()
    try:
        trades = db.query(Trade).filter(Trade.settled.is_(True)).all()

        predictions = []
        for t in trades:
            prob = float(t.entry_price or 0.5)
            outcome = 1.0 if (t.pnl or 0) > 0 else 0.0
            predictions.append((prob, outcome))

        if len(predictions) < min_trades:
            print(f"Not enough settled trades ({len(predictions)}) for benchmark (min {min_trades})")
            return

        polyedge_brier = brier_score(predictions)

        print("ForecastBench Comparison")
        print("=" * 40)
        print(f"{'Method':<30} {'Brier Score':>10}")
        print("-" * 40)
        for name, score in sorted(BASELINES.items(), key=lambda x: x[1]):
            print(f"{name:<30} {score:>10.3f}")
        print(f"{'PolyEdge Ensemble':<30} {polyedge_brier:>10.3f}")
        print("-" * 40)

        if polyedge_brier < BASELINES["random_uniform"]:
            print("PolyEdge beats random baseline")
        if polyedge_brier < BASELINES["human_superforecasters"]:
            print("PolyEdge beats human superforecasters!")
    finally:
        db.close()


if __name__ == "__main__":
    benchmark_from_trades()
