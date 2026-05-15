# Master Plan: Sequential Execution

## TL;DR

> **Sequential execution**: system-health first (fix trading), then comprehensive-fix (code quality).
> Single entry point — Sisyphus reads this, executes health plan, then fix plan.

## Execution Order

### Phase 1: System Health (MUST complete first)
- **Plan**: `.sisyphus/plans/system-health-comprehensive.md`
- **Why first**: System not trading. Zero trades for 2+ days. Must fix blockers before anything else.
- **Tasks**: T1-T18 + F1-F4 (18 implementation + 4 verification = 22 tasks)
- **Waves**: 6 waves + FINAL
- **Exit condition**: F3 (Real QA) confirms ≥5 paper trades executing within 1 hour

### Phase 2: Comprehensive Fix (starts after Phase 1 FINAL approval)
- **Plan**: `.sisyphus/plans/polyedge-comprehensive-fix.md`
- **Why second**: Code quality, dead code removal, race conditions, test coverage. Only matters after system is trading.
- **Tasks**: 61 tasks across 7 waves
- **Waves**: 7 waves + FINAL
- **Exit condition**: All FINAL checks pass

## Gating Rule

**DO NOT start Phase 2 until Phase 1's FINAL wave (F1-F4) passes.**

Phase 1 makes the system trade. Phase 2 makes the codebase clean. Wrong order = optimizing code that can't trade.

## How To Run

```
/start-work
```

When Sisyphus asks which plan to use, point to this file. It will:
1. Read Phase 1 plan path
2. Execute all 6 waves + FINAL
3. Get user approval after Phase 1 FINAL
4. Read Phase 2 plan path
5. Execute all 7 waves + FINAL
6. Done

## Success Criteria

- [x] Phase 1: System executing trades (paper + live) within 24h of deploy
- [x] Phase 1: NO-bias, HFT pipeline, maker mode all verified
- [x] Phase 1: FINAL wave approved by user
- [x] Phase 2: All 61 tasks completed
- [x] Phase 2: Code quality review passes (no `as any`, no empty catches, no console.log)
- [x] Phase 2: FINAL wave approved by user