# Platform Coverage Matrix — PolyEdge

| Platform | Scanner | Integration | Fee | Notes |
|
|---|---|---|---|---|
| Polymarket | ✅ | ✅ | 0.02 | Live + paper paths. Gamma resolution + CLOB execution. |
| Kalshi | ✅ | ✅ | 0.07 | `kalshi_client` + resolution helpers present. |
| SXBet | ✅ | ✅ | 0.02 | `sxbet_client` + batch orderbook flow in scanner. |
| Myriad | ✅ | partial | 0.02 | Included in `_DEFAULT_FEES`; scanner hookup not confirmed. |
| Predict.fun | ✅ | partial | 0.02 | Included in `_DEFAULT_FEES`; scanner hookup not confirmed. |
| Bookmaker.xyz | ✅ | partial | 0.02 | Included in `_DEFAULT_FEES`; scanner hookup not confirmed. |
| Limitless | 🔒 | 🔒 | — | Blocked: smart wallet not deployed (as of 2026-05-30). |

## Conclusion
Only Polymarket/Kalshi/SXBet are fully confirmed wired end-to-end. Everything else is marked partial until billing route + order placement is exercised.
