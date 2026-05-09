<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-05-09 | Updated: 2026-05-09 -->

# frontend/src/types

## Purpose
TypeScript type definitions and interfaces. Extends the core types in `src/types.ts` with feature-specific types.

## Key Files

| File | Description |
|------|-------------|
| `features.ts` | Feature-specific types: `FeatureFlag`, `FeatureToggle`, `FeatureConfig`. Used by the admin dashboard for feature management. |

## For AI Agents

### Working In This Directory
- Types are additive — never modify `src/types.ts` directly for feature-specific types
- Export all types from `features.ts` for use in components
- Use `interface` for object shapes, `type` for unions/aliases

### Common Patterns
- Feature flags use `FeatureFlag = { name: string; enabled: boolean; description: string }`

## Dependencies

### Internal
- `src/types.ts` — Core type definitions

### External
- `typescript` — Type system

<!-- MANUAL: -->
