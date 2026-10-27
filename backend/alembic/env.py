"""Alembic's run: the app's own engine (DB_CONNECTION_STRING through dbUtils) and the tables in models.py."""
from logging.config import fileConfig

from alembic import context

from src.db.database import MODEL_METADATA, engine

if context.config.config_file_name is not None:
    fileConfig(context.config.config_file_name)


def run_migrations_offline() -> None:
    context.configure(url=engine.url.render_as_string(hide_password=False), target_metadata=MODEL_METADATA,
                      literal_binds=True, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=MODEL_METADATA, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
