"""Alembic environment.

The database URL comes from the environment, never from alembic.ini: a credential in a repository
is a credential that leaks, and a URL in a file is a developer migrating the wrong database because
they forgot to edit it.
"""

from __future__ import annotations

from alembic import context
from sqlalchemy import engine_from_config, pool

from wimsim.storage.schema import METADATA
from wimsim.storage.url import database_url

config = context.config
config.set_main_option("sqlalchemy.url", database_url())

target_metadata = METADATA


def _include(obj, name, type_, reflected, compare_to) -> bool:
    """Only manage our own schemas. TimescaleDB creates a great deal of its own."""
    if type_ == "table":
        return obj.schema in {"wim", "truth"}
    return True


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        include_schemas=True,
        include_object=_include,
        version_table_schema="wim",
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_schemas=True,
            include_object=_include,
            version_table_schema="wim",
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
