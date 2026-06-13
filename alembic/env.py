import sys
import os
from logging.config import fileConfig

from sqlalchemy import engine_from_config
from sqlalchemy import pool

from alembic import context

# Add project root to sys.path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from backend.models.database import Base
from backend.config import settings

raise RuntimeError(
    "This root alembic/ directory is LEGACY and its revision graph is "
    "disconnected from backend/alembic/ (the canonical one — see "
    "docs/alembic-dirs.md). Running migrations from here against the "
    "shared DATABASE_URL desyncs alembic_version from the canonical graph "
    "(this happened once already: revision 'arb_exec_status_001', fixed by "
    "stamping to 'add_arb_bundle_tracking' + "
    "backend/alembic/versions/20260613_add_decision_execution_status.py). "
    "Run `cd backend && alembic upgrade head` instead."
)

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    retries = 5
    delay = 1  # delay in seconds between retries

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
