import os
import sys
from logging.config import fileConfig
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import engine_from_config, pool

from alembic import context

# So `alembic` (run from backend/, or anywhere via -c backend/alembic.ini)
# can import `app.*` the same way the application itself does.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Loads backend/.env for local development — same convention as
# app/main.py's own load_dotenv() call. No-op if the file doesn't exist;
# production sets DATABASE_URL directly as a real environment variable.
load_dotenv()

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# See BRAGI_INTEROP_PLAN.md / docs/database/MIGRATIONS.md for the full
# migration architecture. target_metadata is ALWAYS the current, real
# app.models.Base.metadata — the one-time exception (temporarily pointing
# this at a frozen copy of the pre-interop commit's models, to autogenerate
# the 0001 baseline revision from an empty database) was a scripted,
# throwaway env.py edit reverted immediately after, never committed. Every
# migration file under versions/ is static, reviewed Python — nothing here
# re-imports historical model state at migration-run time.
from app import models  # noqa: E402

target_metadata = models.Base.metadata


def _database_url() -> str:
    """Same URL resolution/normalization as app/db.py, so Alembic always
    targets the exact same database the application would."""
    raw = os.getenv(
        "DATABASE_URL",
        "postgresql+psycopg://postgres:dreams@localhost:5432/mvp1_phase1",
    )
    if raw.startswith("postgresql://"):
        return raw.replace("postgresql://", "postgresql+psycopg://", 1)
    return raw


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = _database_url()
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
    configuration = config.get_section(config.config_ini_section, {})
    # Only fall back to the real DATABASE_URL when the Config wasn't
    # already given a real one — e.g. by tests/test_migrations.py's
    # `cfg.set_main_option("sqlalchemy.url", scratch_db_url)`, which must
    # be respected. Without this check, every alembic command (including
    # a destructive downgrade) silently targeted the real dev database
    # instead of the caller's intended scratch database — reproduced for
    # real and fixed before this file shipped (see
    # docs/database/MIGRATIONS.md's testing notes).
    configured_url = config.get_main_option("sqlalchemy.url")
    if not configured_url or configured_url == "driver://user:pass@localhost/dbname":
        configuration["sqlalchemy.url"] = _database_url()
    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
