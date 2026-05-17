<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-05-17 -->

# core/copy_sources

## Purpose
Copy trading signal sources. Provides implementations that feed copy-trading signals into the execution pipeline — one mirrors internal strategy trades, the other scrapes external leaderboards.

## Key Files
| File | Description |
|------|-------------|
| `__init__.py` | Empty package init |
| `internal_mirror_source.py` | `InternalMirrorSource` — mirrors trades from followed internal strategies; reads from `CopyTraderEntry` and `Trade` DB tables |
| `leaderboard_source.py` | `LeaderboardCopySource` — scrapes external leaderboard for top trader positions via HTTP |

## For AI Agents

### Working In This Directory
- Both sources subclass `CopySource` from `backend.core.copy_source`
- `InternalMirrorSource` requires a `db_session` and optional `followed_strategies` list
- `LeaderboardCopySource` requires a `db_session` and makes HTTP calls to external leaderboards
- Both respect `CopyPolicyConfig` for risk limits and position sizing

## Dependencies

### Internal
- `backend.core.copy_source` — `CopySource`, `CopyPolicyConfig`, `CopySignalData` ABCs
- `backend.models.database` — `CopyTraderEntry`, `Trade`, `TradeContext`, `WalletConfig`
- `backend.config` — `settings` for leaderboard URL

### External
- `httpx` — HTTP client for leaderboard scraping
- `sqlalchemy` — DB access
