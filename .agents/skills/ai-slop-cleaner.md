# Skill: /ai-slop-cleaner

Clean AI-generated code slop with a regression-safe, deletion-first workflow and optional reviewer-only mode.

## Usage:
* `/ai-slop-cleaner <target>`: Audit and clean up the specified target directory or file.
* `/ai-slop-cleaner <file-a> <file-b>`: Audit and clean up the specified list of files.
* `/ai-slop-cleaner <target> --review`: Run a reviewer-only pass to evaluate a drafted cleanup.

## Workflow:

1. **Protect current behavior first**
   - Identify what must stay the same.
   - Add or run the narrowest regression tests needed before editing.
   - If tests cannot come first, record the verification plan explicitly before touching code.

2. **Write a cleanup plan before code**
   - Bound the pass to the requested files or feature area.
   - List the concrete smells to remove.
   - Order the work from safest deletion to riskier consolidation.

3. **Classify the slop before editing**
   - **Duplication** — repeated logic, copy-paste branches, redundant helpers
   - **Dead code** — unused code, unreachable branches, stale flags, debug leftovers
   - **Needless abstraction** — pass-through wrappers, speculative indirection, single-use helper layers
   - **Boundary violations** — hidden coupling, misplaced responsibilities, wrong-layer imports or side effects
   - **Missing tests** — behavior not locked, weak regression coverage, edge-case gaps

4. **Run one smell-focused pass at a time**
   - **Pass 1: Dead code deletion**
   - **Pass 2: Duplicate removal**
   - **Pass 3: Naming and error-handling cleanup**
   - **Pass 4: Test reinforcement**
   - Re-run targeted verification after each pass.
   - Do not bundle unrelated refactors into the same edit set.

5. **Run the quality gates**
   - Keep regression tests green.
   - Run the relevant lint, typecheck, and unit/integration tests for the touched area.
   - If a gate fails, fix the issue or back out the risky cleanup instead of forcing it through.

6. **Close with an evidence-dense report**
   Always report:
   - **Changed files**
   - **Simplifications**
   - **Behavior lock / verification run**
   - **Remaining risks**
