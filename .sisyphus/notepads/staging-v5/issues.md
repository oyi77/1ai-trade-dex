
## Staging v5 Issues (2026-05-15)

- **cross_market_arb errors=500**: Persistent HTTP 500 from Kalshi API; not Python errors but fills error counter
- **kalshi_arb errors=1**: Same Kalshi connectivity issue
- **Rate-limit blocking**: cex_pm_leadlag had 6 decisions but most blocked by "Rate limit exceeded" and "Duplicate execution blocked"
- **Many strategies 0 trades**: Despite producing decisions (weather_emos=2, market_maker=3, agi_orchestrator=2), no trades execute — likely the BUY filter `d.get("decision") == "BUY"` AND `d.get("market_ticker")` is too strict
