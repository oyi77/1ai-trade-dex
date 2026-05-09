<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-05-07 | Updated: 2026-05-10 -->

# scanners

## Purpose
Market scanning and weather infrastructure modules. These scan for opportunities and process weather forecast data but are not alpha strategies themselves.

## Key Files

| File | Description |
|------|-------------|
| `__init__.py` | Package marker |
| `weather_emos.py` | 31-member GFS ensemble temperature forecasting (Open-Meteo + NWS) for weather prediction markets |

## For AI Agents

### Working In This Directory
- These are scanner modules, NOT alpha strategies
- Imported by `backend.strategies.registry` as functional strategy entries
- `weather_emos` follows the standard `Strategy` interface

### Testing Requirements
- Integration tests in `tests/` at project root

### Common Patterns
- Implements `Strategy` interface from `backend.strategies.base`
- Uses `@register_strategy("weather_emos")` decorator
- Configurable via `WEATHER_*` environment variables

## Dependencies

### Internal
- `backend.data.weather` — Weather API integration
- `backend.data.weather_markets` — Weather market discovery
- `backend.config` — Settings (WEATHER_*, EMOS_* thresholds)

### External
- `httpx` — Async HTTP for weather API calls
- `numpy` — Ensemble statistical computations

<!-- MANUAL: -->