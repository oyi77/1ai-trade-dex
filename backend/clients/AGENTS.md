<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-04-10 | Updated: 2026-05-09 -->

# clients

## Purpose
External API client wrappers for third-party prediction services and data providers. Currently wraps BigBrain prediction API for enhanced market forecasting.

## Key Files
| File | Description |
|------|-------------|
| bigbrain.py | BigBrain prediction service client; HTTP wrapper with request/response handling |

## Subdirectories
None

## For AI Agents
### Working In This Directory
- Clients are thin HTTP wrappers around external APIs
- Error handling for rate limits, timeouts, authentication failures
- Response parsing and validation
- Retry logic with exponential backoff
- Async-friendly for integration into FastAPI endpoints

### Testing Requirements
- Test API authentication and token refresh
- Verify error handling (4xx, 5xx, timeouts)
- Test request/response serialization
- Validate retry behavior under transient failures
- Mock external API for unit tests

### Common Patterns
- Session-based HTTP clients for connection pooling
- Standardized error types for client-specific failures
- Async/await support for non-blocking I/O
- Configuration via environment variables (API keys, endpoints)

## Dependencies
### Internal
- backend.config (API credentials, endpoint URLs)

### External
- httpx or requests (HTTP client library)

<!-- MANUAL: -->
