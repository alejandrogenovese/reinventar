"""Pool de conexiones a Postgres, compartido por el estado de la app (schema app) y el conocimiento (schema reinvent).

Hay un segundo pool para el modo prueba (app/sandbox.py): su search_path pone primero el schema de prueba, donde solo
existen las tablas de datos del usuario. pool() elige según el contexto del pedido en curso.
"""
import re

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from . import config, sandbox

_SCHEMA_NAME = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")
_pools: dict[str, ConnectionPool] = {}


class DatabaseNotConfigured(Exception):
    """Falta DATABASE_URL (en Railway: Variables → referencia al servicio Postgres)."""


def _search_path(en_prueba: bool) -> str:
    # Las tablas del catálogo se nombran siempre como reinvent.<tabla>.
    return f"{sandbox.schema_prueba()}, {config.DB_SCHEMA}, public" if en_prueba else f"{config.DB_SCHEMA}, public"


def _crear(en_prueba: bool) -> ConnectionPool:
    if not config.DATABASE_URL:
        raise DatabaseNotConfigured("DATABASE_URL vacío")
    if not _SCHEMA_NAME.match(config.DB_SCHEMA) or not _SCHEMA_NAME.match(sandbox.schema_prueba()):
        raise DatabaseNotConfigured(f"DB_SCHEMA inválido: {config.DB_SCHEMA!r}")
    path = _search_path(en_prueba)

    def configure(c):
        c.execute(f"SET search_path TO {path}")
        c.commit()

    return ConnectionPool(config.DATABASE_URL, min_size=1, max_size=config.DB_POOL_SIZE,
                          kwargs={"row_factory": dict_row}, configure=configure, open=True)


def pool() -> ConnectionPool:
    """El pool del contexto actual: el de prueba si el pedido es de un usuario en modo prueba."""
    clave = "prueba" if sandbox.actual() else "real"
    if clave not in _pools:
        _pools[clave] = _crear(clave == "prueba")
    return _pools[clave]


def close() -> None:
    for p in _pools.values():
        p.close()
    _pools.clear()
