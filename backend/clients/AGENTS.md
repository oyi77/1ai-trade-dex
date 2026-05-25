<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-04-10 | Updated: 2026-05-25 -->

# clients

## Purpose
External API client wrappers for third-party prediction services, decentralized betting protocols, orderbook DEXes, and data providers.

## Key Files
| File | Description |
|------|-------------|
| `aster_client.py` | Aster DEX client using CCXT for swaps and perpetuals |
| `azuro_client.py` | Azuro Protocol smart contract and GraphQL subgraph client for Bookmaker.xyz & Predict.fun |
| `bigbrain.py` | BigBrain prediction service client; HTTP wrapper with request/response handling |
| `hyperliquid_client.py` | Hyperliquid DEX client for perpetuals and predictions using `hyperliquid-python-sdk` |
| `lighter_client.py` | Lighter orderbook swap/perps DEX client |
| `limitless_client.py` | Limitless Exchange prediction market API client (EIP-712 signing) |
| `myriad_client.py` | Myriad prediction market REST API client |
| `ostium_client.py` | Ostium DEX client using `ostium-python-sdk` |
| `polymarket_sdk_client.py` | Polymarket SDK and CLOB API wrapper client |
| `sxbet_client.py` | SX.bet API client with EIP-712 order placement |
| `websearch.py` | WebSearchClient wrapping Tavily, Exa, Serper, and DuckDuckGo search queries |

## Subdirectories
None

## For AI Agents
### Working In This Directory
- Clients are thin wrappers (HTTP, Web3, SDK, or CCXT) around external APIs.
- Error handling for rate limits, timeouts, authentication failures.
- Response parsing, model serialization/validation.
- Retry logic with exponential backoff.
- Async-friendly for integration into FastAPI endpoints.

### Testing Requirements
- Test API authentication, token refresh, and key decryption.
- Verify error handling (4xx, 5xx, timeouts, connection issues).
- Test request/response serialization.
- Validate retry behavior under transient failures.
- Mock external APIs/contracts for unit tests.

### Common Patterns
- Session-based HTTP clients for connection pooling.
- Standardized error types for client-specific failures.
- Async/await support for non-blocking I/O.
- Configuration via environment variables (keys, endpoints, RPC URLs).

## Dependencies
### Internal
- `backend.config` (API credentials, endpoint URLs, and settings)
- `backend.core.eip712_signer` (shared signing for EVM venues)

### External
- `httpx` or `requests` (HTTP client library)
- `ccxt` (Aster, Lighter, and CCXT DEXes)
- `hyperliquid-python-sdk` (Hyperliquid integration)
- `ostium-python-sdk` (Ostium integration)
- `lighter-sdk` (Lighter integration)
- `web3` (EVM transaction signing and RPC interactions)

<!-- MANUAL: -->
