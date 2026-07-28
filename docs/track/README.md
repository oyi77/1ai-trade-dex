# Deferred Debt Tracking

Per RULES.md §11, no TODO/FIXME/stub/placeholder should be committed.
When deferral is necessary, create a file here with acceptance criteria.

## Current items

*(None — all known gaps closed as of 2026-07-29 update)*

## Protocol

1. Create `docs/track/<item-slug>.md` with:
   - What is deferred
   - Why it's deferred (not acceptable for critical paths)
   - Acceptance criteria (what proves it's done)
   - Owner and deadline
2. Reference the file in code via comment: `# tracked: docs/track/<item-slug>.md`
3. Revisit by deadline — if still deferred, update with new deadline
4. Close by deleting the file once accepted