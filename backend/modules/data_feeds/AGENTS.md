<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-05-07 | Updated: 2026-05-10 -->

# data_feeds

## Purpose
Whale tracking and signal feed modules. These modules track large trader activity (whale PnL, whale frontrun) and provide data signals but do not directly generate alpha.

## Key Files

| File | Description |
|------|-------------|
| `__init__.py` | Package marker |
| `whale_pnl_tracker.py` | Tracks top trader realized PnL on Polymarket leaderboard for signal generation |
| `whale_frontrun.py` | Detects large whale orders and generates frontrun signals before execution completes |

## For AI Agents

### Working In This Directory
- These are data feed modules, NOT alpha strategies
- Imported by `backend.strategies.registry` as functional strategy entries
- Each module follows the standard `Strategy` interface for compatibility

### Testing Requirements
- Integration tests in `tests/` at project root

### Common Patterns
- Implement `Strategy` interface from `backend.strategies.base`
- Use `@register_strategy()` decorator for registry discovery
- Snapshot DB-backed wallet/config rows before awaited HTTP calls; never keep a SQLAlchemy session open while polling external feeds

## Dependencies

### Internal
- `backend.data.polymarket_scraper` — Leaderboard data
- `backend.config` — Settings and thresholds
- `backend.models.database` — Trade and signal models

### External
- `httpx` — Async HTTP for API calls

<!-- MANUAL: -->
