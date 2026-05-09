<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-05-09 | Updated: 2026-05-09 -->

# backend/repositories

## Purpose
Repository layer — database CRUD abstractions for domain objects. Decouples domain logic from SQLAlchemy query details. Currently contains genome persistence; other domain objects use direct ORM queries in `backend/core/`.

## Key Files

| File | Description |
|------|-------------|
| `genome_repository.py` | `GenomeRepository` — CRUD operations for `GenomeRegistry`, `GenomePerformance`, `GenomeShadowTrade` ORM models |

## For AI Agents

### Working In This Directory
- **New repositories follow the same pattern as `GenomeRepository`** — accept a `Session` in the constructor, expose typed methods (`get`, `create`, `update`, `delete`, `list`), never manage session lifecycle internally.
- **Repositories do not commit** — the caller owns the transaction. Repositories call `db.add()` and `db.flush()` but never `db.commit()`.
- When adding a new repository, register it in `backend/application/` or `backend/core/` where it is used — do not instantiate repositories directly in API routers.

### Testing Requirements
- Use in-memory SQLite with `Base.metadata.create_all(engine)` for isolation
- Test each CRUD method independently
- Verify that repositories do not commit — test that uncommitted changes are visible within the same session but not across sessions

### Common Patterns
```python
class MyRepository:
    def __init__(self, db: Session):
        self.db = db

    def get(self, id: str) -> Optional[MyModel]:
        return self.db.query(MyModel).filter(MyModel.id == id).first()

    def create(self, data: dict) -> MyModel:
        obj = MyModel(**data)
        self.db.add(obj)
        self.db.flush()
        return obj
```

## Dependencies

### Internal
- `backend.models.database` — `SessionLocal`, ORM `Base`
- `backend.models.genome_registry` — `GenomeRegistry`, `GenomePerformance`, `GenomeShadowTrade`

### External
- `sqlalchemy` — ORM queries and session management
