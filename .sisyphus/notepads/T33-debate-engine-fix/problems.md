
### Unresolved Problems from T33: Debate Engine Fix

- **Persistent SQLAlchemy `create_all` Error**: The most significant blocking issue is the `sqlalchemy.exc.InternalError: (sqlite3.InternalError) Cannot add a NOT NULL column with default value NULL` that occurs during `Base.metadata.create_all` in `tests/conftest.py` with an in-memory SQLite database. This error prevents the execution of tests that rely on database setup.
    - **Investigation Summary**: Extensive checks of `nullable=False` columns in all relevant models (`database.py`, `kg_models.py`, `outcome_tables.py`, `historical_data.py`) did not reveal any obvious missing `default` or `server_default` values for non-primary key columns. A `TypeError` related to `create_engine` arguments with SQLite was fixed, but it did not resolve the core `NOT NULL` issue.
    - **Potential Causes**: This likely points to a more subtle interaction issue between SQLAlchemy, SQLite, and potentially complex schema definitions (e.g., `UniqueConstraint`, `Index` combinations), or a specific version-related bug. It might also be related to model loading order or hidden dependencies. This requires a dedicated debugging effort beyond the scope of a single feature fix.
    - **Impact**: Blocks automated testing for any features requiring database interaction.

- **HFT_POSITION_SIZE_PCT Pydantic Validation in Test Environment**: Although temporarily bypassed and reverted, the `ValidationError` for `HFT_POSITION_SIZE_PCT` (value 0.25, expected max 0.20) in the test environment remains. The source of this environment variable setting is unknown and not in `pytest.ini` or `.env.example`. This should be investigated to ensure consistent test environments.

