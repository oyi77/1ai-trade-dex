from backend.backtesting.base import (
    BacktestStrategyRunnerManifest,
    BaseBacktestStrategyRunner,
)


class DefaultStrategyRunner(BaseBacktestStrategyRunner):
    def __init__(self) -> None:
        self.manifest = BacktestStrategyRunnerManifest(
            name="default",
            display_name="Default Strategy Runner",
            version="1.0.0",
            description="Standard backtest mode strategy execution",
            tags=["backtest", "standard"],
        )

    def run_strategy(
        self,
        strategy_cls: type,
        data: object,
        params: dict,
    ) -> list[dict]:
        strategy = strategy_cls(backtest_mode=True, **params)

        trades = []
        for _, row in data.iterrows():
            signal = strategy.generate_signal(row)
            if signal:
                trade = strategy.execute_trade(signal, row)
                if trade:
                    trades.append(trade)

        return trades

    def health_check(self) -> bool:
        return True
