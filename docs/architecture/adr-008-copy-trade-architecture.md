# ADR-008: Copy-Trade Architecture

**Status:** Accepted  
**Date:** 2026-05-13

## Context

PolyEdge strategies generate alpha independently. A common and complementary source of edge in prediction markets is mirroring high-performing traders — copying their positions with a size and timing policy.

The system needed a copy-trade subsystem that:
1. Polls or streams signals from external leader sources (on-chain wallet activity, leaderboard APIs, custom feeds)
2. Applies per-source filtering: minimum confidence, maximum order delay, size scaling
3. Routes accepted signals through the existing `RiskManager` + `WalletAllocation` pipeline — no parallel execution path
4. Persists policy configuration in the database so it can be updated without redeployment
5. Is extensible: new signal sources plug in without touching core execution code

## Decision

Introduce a `CopySource` abstract base class and a `CopyPolicy` ORM model.

### CopySource ABC

`backend/core/copy_source.py` defines:

```
CopySource          — abstract base; implementations provide get_name(), fetch_signals(), is_healthy()
CopyPolicyConfig    — dataclass; runtime policy hydrated from CopyPolicy DB row
CopySignalData      — dataclass; one signal from a source (leader address, condition id, side, size, confidence)
```

New sources implement `CopySource` and register with the `CopyEngine` (T6). The engine polls each enabled source on a configurable interval, applies the source's `CopyPolicyConfig`, and emits `Signal` objects into the standard signal queue.

### CopyPolicy Table

| Column | Purpose |
|---|---|
| `source_name` | Unique key matching `CopySource.get_name()` |
| `enabled` | Master on/off switch |
| `max_size_usd` | Hard cap per copied order |
| `confidence_floor` | Minimum confidence score to act on |
| `max_delay_seconds` | Reject signals older than this |
| `size_scale_factor` | Multiply leader size by this before `max_size_usd` cap |
| `cooldown_seconds` | Minimum gap between consecutive copies from same source |

### Signal Flow

```
CopySource.fetch_signals()
  → CopyEngine applies CopyPolicyConfig filters
  → valid CopySignalData → Signal(track_name=source_name)
  → existing RiskManager gate
  → WalletAllocation fan-out
  → order execution
```

The `track_name` is set to `source_name` so trade attribution in the dashboard correctly identifies the copy source, consistent with ADR-003.

## Consequences

**Positive**
- New copy sources require only a `CopySource` subclass — no schema or core changes
- All copied trades pass through `RiskManager` — ADR-004 bounded sizing is preserved
- `CopyPolicy` rows can be updated live via admin API without restarting the bot

**Negative**
- Polling latency is bounded by the scheduler interval; for latency-sensitive sources a push/webhook model would be faster (deferred to v2)
- `confidence` is source-defined; cross-source comparisons are not normalised in v1

## Alternatives Considered

**Hardcoded leader list in config file**: rejected — no per-source policy, requires redeploy to change.

**Separate execution path bypassing RiskManager**: rejected — violates ADR-004; introduces an unguarded capital exposure vector.

**Webhook push per signal**: deferred — operationally more complex; polling is sufficient for current signal volumes.
