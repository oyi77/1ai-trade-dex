
### Learnings from T33: Debate Engine Fix

- The `_parse_agent_response` function in `backend/ai/debate_engine.py` was modified to return `None` on parse failure instead of a fallback `(0.5, 0.0, ...)`. This ensures that invalid or unparseable agent responses result in the signal being dropped, preventing the system from acting on potentially bad data.
- All consuming sites in `run_debate` (`bull_response`, `bear_response`, and rebuttal rounds) were updated to check for `None` from `_parse_agent_response` and skip appending the argument if parsing fails. This propagates the signal drop correctly.
- The judge consensus calculation was updated to check for `None` from `_parse_agent_response` for the judge's response. If the judge's response is unparseable, it falls back to a confidence-weighted average of available bull and bear arguments, with appropriate logging.

### Debugging Learnings:

- **Pydantic Validation Error (HFT_POSITION_SIZE_PCT)**: Encountered a `ValidationError` for `HFT_POSITION_SIZE_PCT` (expected 0.01-0.20, got 0.25). This value is likely set in the test environment outside of `.env.example` or `pytest.ini`. A temporary bypass was implemented and then reverted, as it wasn't the root cause of the main test blocking issue.
- **SQLAlchemy `create_all` failure**: Persistent `sqlalchemy.exc.InternalError: (sqlite3.InternalError) Cannot add a NOT NULL column with default value NULL` during `Base.metadata.create_all` in `tests/conftest.py` with in-memory SQLite. This is highly unusual for a fresh database and suggests a deeper issue with model definitions or SQLAlchemy/SQLite interaction. Extensive investigation into `nullable=False` columns in all imported models (`database.py`, `kg_models.py`, `outcome_tables.py`, `historical_data.py`) did not reveal any obvious misconfigurations.
- **SQLAlchemy `create_engine` TypeError**: Discovered `TypeError: Invalid argument(s) 'max_overflow','pool_timeout'` when using `create_engine` with `StaticPool` for SQLite. This was fixed by conditionally applying pool-related arguments only for non-SQLite databases in `backend/models/database.py`. This fix was necessary but did not resolve the `NOT NULL` column error.

