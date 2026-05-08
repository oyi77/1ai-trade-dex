<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-05-09 | Updated: 2026-05-09 -->

# backend/data/providers

## Purpose

Data provider implementations for external market data exchanges. Implements the DataProvider abstract interface for Polymarket and Kalshi platforms, providing unified market discovery, position retrieval, and balance information access.

## Key Files

| File | Description |
|------|-------------|
| `__init__.py` | Package marker for data provider implementations |
| `kalshi.py` | Kalshi Provider implementation - market discovery, position tracking, balance info, and health checks using KalshiClient and kalshi_markets |
| `polymarket.py` | Polymarket Provider implementation - market metadata fetching, portfolio management, balance information, and connectivity health checks |

## For AI Agents

### Working In This Directory
- Both providers implement the DataProvider abstract base class interface
- Unified market discovery across platforms using common MarketEntry format
- Health check methods for connectivity validation
- Position and balance retrieval for portfolio management
- Platform-specific optimizations for exchange-specific data formats

### Testing Requirements
- Mock exchange API responses for provider testing
- Test health check timeout and error handling
- Validate market data transformation to common format
- Test position and balance retrieval logic
- Verify error handling for API rate limits and connectivity issues

### Common Patterns
- Implement `platform_name` property for provider identification
- Use `async def health_check()` for connectivity validation
- Return `List[MarketEntry]` from `get_markets()` with optional category filtering
- Provide `get_positions()` and `get_balance()` for portfolio information
- Handle platform-specific rate limiting and error responses gracefully

## Dependencies

### Internal
- `backend.data.provider` - DataProvider abstract base class interface
- `backend.data.kalshi_client` - Kalshi API client for kalshi.py
- `backend.data.gamma` - Gamma API client for market data in polymarket.py
- `backend.data.polymarket_clob` - Polymarket CLOB client for position tracking

### External
- `httpx` - Async HTTP client for API requests
- `typing` - Type hints for method signatures
- `datetime` - Timestamp handling for market data