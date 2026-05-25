# Data Sources

| Source | Data | Used For | Auth |
|--------|------|----------|------|
| Coinbase | BTC 1-min candles | BTC microstructure | None |
| Kraken | BTC 1-min candles | BTC fallback | None |
| Binance | BTC 1-min candles | BTC fallback | None |
| Open-Meteo | GFS Ensemble (31 members) | Weather probability | None |
| NWS API | Observed temperatures | Weather settlement | None |
| Polymarket | Market prices, orderbook depth, resolutions, trading | Predictions & arbitrage | API key + Wallet proxy |
| Kalshi | Event contract markets, orderbook, resolution | Predictions & weather arbitrage | API key ID + RSA key |
| SX.bet | Sports betting & prediction markets, odds | Sports and prediction trading | EIP-712 wallet signer |
| Limitless | Base L2 prediction markets, prices | General prediction trading | EIP-712 wallet signer |
| Myriad | EVM prediction market contracts, REST odds | General prediction trading | REST API / public endpoints |
| Azuro Protocol | Bookmaker.xyz & Predict.fun prediction pools, odds | Sports and prediction trading | Web3 smart contracts + GraphQL |
| Hyperliquid | L1 perpetuals, orderbook swaps, prediction pools | Perps and prediction trading | EVM wallet signer / L1 SDK |
| Ostium | Arbitrum perps & prediction DEX prices | Perps and DEX prediction trading | EVM wallet signer / CCXT |
| Aster DEX | CCXT swap & perps orderbooks, positions | Swap & perps DEX trading | EVM wallet signer / CCXT |
| Lighter | ZK orderbook perpetuals and DEX prices | Perps and ZK prediction trading | EVM wallet signer + API index / CCXT |

## Supported Cities (Weather)

| City | Station | Tracked |
|------|---------|---------|
| New York | KNYC | Default |
| Chicago | KORD | Default |
| Miami | KMIA | Default |
| Los Angeles | KLAX | Default |
| Denver | KDEN | Default |

Add more cities by editing `WEATHER_CITIES` in config and adding entries to `CITY_CONFIG` in `backend/data/weather.py`.
