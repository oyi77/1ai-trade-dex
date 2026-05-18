import logging

from backend.backtesting.base import (
    BacktestDataSourceManifest,
    BaseBacktestDataSource,
)

logger = logging.getLogger(__name__)


class PolymarketBacktestDataSource(BaseBacktestDataSource):
    def __init__(self) -> None:
        self.manifest = BacktestDataSourceManifest(
            name="polymarket",
            display_name="Polymarket Historical Data",
            version="1.0.0",
            supported_markets=["polymarket", "kalshi"],
            tags=["historical", "prediction-markets"],
        )

    def load_data(self, market_ticker: str, start_date: str, end_date: str) -> object:
        from backend.data.polymarket_data_provider import PolymarketDataProvider

        provider = PolymarketDataProvider()
        data = provider.get_historical_data(
            market_ticker=market_ticker,
            start_date=start_date,
            end_date=end_date,
        )
        return data

    def health_check(self) -> bool:
        try:
            from backend.data.polymarket_data_provider import PolymarketDataProvider

            provider = PolymarketDataProvider()
            return provider.health_check()
        except Exception:
            logger.debug("Polymarket backtest data source health check failed", exc_info=True)
            return False
