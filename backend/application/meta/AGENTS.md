<!-- Parent: ../../AGENTS.md -->
<!-- Generated: 2026-05-07 | Updated: 2026-05-10 -->

# meta

## Purpose
Meta-strategy routing and regime detection. Adjusts confidence thresholds based on detected market regime so strategies perform better across different market conditions.

## Key Files

| File | Description |
|------|-------------|
| `__init__.py` | Package marker |
| `regime_router.py` | Regime-aware confidence router — adjusts strategy confidence thresholds based on current market regime (trending, volatile, calm) |

## Subdirectories

None.

## For AI Agents

### Working In This Directory
- Regime types defined in `backend.core.agi_types.MarketRegime`
- Routes are defined per strategy with regime-specific multipliers
- Used by the strategy executor to adjust signal confidence before execution

### Testing Requirements
- Run: `pytest backend/tests/ -v -k regime`

### Common Patterns
- Each strategy has regime-specific multipliers stored in config
- `RegimeConfidenceRouter` takes base confidence and adjusts based on current regime

## Dependencies

### Internal
- `backend.core.agi_types` — MarketRegime enum
- `backend.config` — Settings

### External
- None

<!-- MANUAL: -->