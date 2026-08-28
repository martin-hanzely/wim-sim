"""Storage: TimescaleDB schema, migrations and the idempotent writer.

Alembic owns the schema. The writer never creates a table -- a writer that did would work on an
empty database and diverge from the migration for the rest of the project's life.
"""

from wimsim.storage.schema import METADATA
from wimsim.storage.url import DEFAULT_URL, database_url
from wimsim.storage.writer import EventWriter

__all__ = ["DEFAULT_URL", "METADATA", "EventWriter", "database_url"]
