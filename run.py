#!/usr/bin/env python3
"""Run the trading bot backend server."""
import uvicorn
from backend.models.database import init_db
from backend.config_extensions import settings

if __name__ == "__main__":
    print("Initializing database...")
    init_db()

    print("Applying Alembic migrations...")
    try:
        from alembic.config import Config
        from alembic import command
        from alembic.runtime.migration import MigrationContext
        from sqlalchemy import create_engine

        alembic_cfg = Config("alembic.ini")
        engine = create_engine(settings.DATABASE_URL)
        with engine.connect() as conn:
            ctx = MigrationContext.configure(conn)
            current_rev = ctx.get_current_revision()

        if current_rev is None:
            command.stamp(alembic_cfg, "head")
            print("Fresh DB — stamped at Alembic head")
        else:
            command.upgrade(alembic_cfg, "head")
            print("Migrations up to date")
    except Exception as exc:
        print(f"Migration warning (non-fatal): {exc}")

    port = settings.PORT
    print(f"Starting server on http://0.0.0.0:{port}")
    print(f"API docs available at http://localhost:{port}/docs")

    uvicorn.run(
        "backend.api.main:app",
        host="0.0.0.0",
        port=port,
        reload=settings.RELOAD_ON_CHANGE
    )
