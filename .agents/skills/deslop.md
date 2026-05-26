# Skill: /deslop

Clean up low-quality AI-generated code, boilerplates, and redundant elements to enforce premium, clean human-engineering standards while guaranteeing behavior locks.

## Usage:
* `/deslop <filename>`: Audit and clean up the specified file.
* `/deslop`: Audit and clean up the active file or staged changes.

## Cleanup Instructions:

1. **Obvious & Redundant Comments**:
   - Delete comments that merely restate what the adjacent line of code does (e.g. `# import json` or `// set x to 10`).
   - Retain only high-value architectural comments, docstrings, or complex business logic explanations.

2. **Defensive Programming Overkill**:
   - Streamline excessive, nested try-catch blocks that simply catch exceptions and log them without re-raising or recovering.
   - Replace complex defensive assertions with clean, logical checks or modern language features.

3. **Abstractions & Wrapper Bloat**:
   - Eliminate redundant wrappers, one-line functions that merely call another function, and unnecessarily complex abstractions.
   - Refactor repetitive logic blocks into single, focused reusable routines.

4. **Dead Code & Placeholders**:
   - Remove unused imports, variables, arguments, and dead code branches.
   - Replace dummy or placeholder implementations with correct live code.

5. **Behavior Locking**:
   - After cleaning, verify that the file's functionality remains perfectly intact.
   - Proactively run relevant unit tests (e.g., `pytest tests/` or target tests) to confirm zero functional regressions.
