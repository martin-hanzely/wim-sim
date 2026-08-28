"""Where the database is.

One place, so that the writer, the migrations and the CLI cannot disagree about which database they
are talking to -- and so that the default points at the compose stack's 5433 rather than at whatever
PostgreSQL happens to be listening on 5432.
"""

from __future__ import annotations

import os

__all__ = ["DEFAULT_URL", "database_url"]

#: Port 5433 matches docker-compose. A local PostgreSQL on 5432 is the common case, and silently
#: migrating *that* would be a memorable afternoon.
DEFAULT_URL = "postgresql+psycopg://wimsim:wimsim@localhost:5433/wimsim"


def database_url(override: str | None = None) -> str:
    return override or os.environ.get("WIMSIM_DATABASE_URL") or DEFAULT_URL
