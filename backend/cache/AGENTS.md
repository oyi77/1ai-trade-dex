<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-04-10 | Updated: 2026-05-09 -->

# cache

## Purpose
Redis-based caching layer for market data, session state, and computed results. Provides TTL-managed key-value storage with type-safe wrappers around raw Redis operations.

## Key Files
| File | Description |
|------|-------------|
| redis_cache.py | RedisCache class wrapping redis-py client with get/set/delete/expire operations and TTL management |

## Subdirectories
None

## For AI Agents
### Working In This Directory
- Single Redis client instance per process
- TTL management with configurable expiration (market data: minutes, session: hours)
- Key naming convention: `module:entity:id` (e.g., `market:btc_5m:latest_price`)
- Type conversion: serialize to JSON for complex objects, store as strings
- Fallback: missing keys return None; expired keys auto-delete

### Testing Requirements
- Test get/set/delete operations with various value types
- Verify TTL expiration behavior
- Test connection failures and retries
- Verify key naming consistency across modules

### Common Patterns
- Lazy initialization of Redis connection
- JSON serialization for non-primitive types
- Consistent key naming conventions
- TTL defaults per data type
- Context managers for connection cleanup

## Dependencies
### Internal
- backend.config (Redis connection settings)

### External
- redis (Redis client library)

<!-- MANUAL: -->
