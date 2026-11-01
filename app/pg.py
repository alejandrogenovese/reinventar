"""Pool de conexiones a Postgres, compartido por el estado de la app (schema app) y el conocimiento (schema reinvent)."""
import re

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from . import config

_SCHEMA_NAME = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")
_pool: ConnectionPool | None = None


class DatabaseNotConfigured(Exception):
    """Falta DATABASE_URL (en Railway: Variables → referencia al servicio Postgres)."""


def _configure(c):
    # search_path apunta al schema de la app; las tablas del catálogo se nombran siempre como reinvent.<tabla>.
    c.execute(f"SET search_path TO {config.DB_SCHEMA}, public")
    c.commit()


def pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        if not config.DATABASE_URL:
            raise DatabaseNotConfigured("DATABASE_URL vacío")
        if not _SCHEMA_NAME.match(config.DB_SCHEMA):
            raise DatabaseNotConfigured(f"DB_SCHEMA inválido: {config.DB_SCHEMA!r}")
        _pool = ConnectionPool(
            config.DATABASE_URL,
            min_size=1,
            max_size=config.DB_POOL_SIZE,
            kwargs={"row_factory": dict_row},
            configure=_configure,
            open=True,
        )
    return _pool


def close() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None
