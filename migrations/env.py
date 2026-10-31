"""Alembic environment. The URL comes from pipeline.migrate or from the app settings."""

import sqlalchemy as sa
from alembic import context

from app.config import get_settings

config = context.config


def _database_url() -> str:
    url = config.attributes.get("database_url") or get_settings().database_url
    if not url:
        raise RuntimeError("DATABASE_URL is not set")
    return url


def run_migrations_offline() -> None:
    context.configure(url=_database_url(), literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = sa.create_engine(_database_url(), poolclass=sa.pool.NullPool)
    try:
        with engine.connect() as connection:
            context.configure(connection=connection)
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
