"""Arma (o rehace) la copia del catálogo para staging: reinvent → reinvent_staging, en la misma base de Railway.

Staging usa esa copia (CATALOGO_SCHEMA=reinvent_staging) para probar la revisión automática de eventos, charlas y shows
sin tocar lo que ve producción. Copia todas las tablas de reinvent con sus datos, índices y restricciones (sin las claves
foráneas entre tablas, que en una copia de prueba no hacen falta) y después corre todas las migraciones sobre la copia
(así queda con la 007, 008, 009… aunque producción todavía no las tenga). reinvent no se modifica.

Por defecto corre en modo prueba (todo en una transacción con ROLLBACK). Con --aplicar confirma.
Si reinvent_staging ya existe, se borra y se vuelve a copiar (se pierde lo que haya cargado la revisión en staging).

Uso (en tu Terminal; la URL lleva la clave, no la pegues en ningún lado):
  export RAILWAY_DATABASE_URL='postgresql://<usuario>:<clave>@<host del TCP Proxy>:<puerto>/<base>'
  python -m scripts.preparar_catalogo_staging            # prueba
  python -m scripts.preparar_catalogo_staging --aplicar  # de verdad
"""
import argparse
import os
import sys

import psycopg
from psycopg import sql

from scripts.actualizar_catalogo import aplicar_migraciones

ORIGEN = "reinvent"
DESTINO = "reinvent_staging"


def tablas(conn, schema: str) -> list[str]:
    return [r[0] for r in conn.execute(
        "SELECT tablename FROM pg_tables WHERE schemaname = %s ORDER BY tablename", (schema,)).fetchall()]


def copiar(conn, origen: str = ORIGEN, destino: str = DESTINO) -> dict[str, int]:
    """Copia cada tabla de origen a destino (estructura + datos). Devuelve filas por tabla. Dentro de la transacción
    de conn: quien llama decide COMMIT o ROLLBACK."""
    if destino == origen:
        raise ValueError("el destino no puede ser el mismo schema")
    o, d = sql.Identifier(origen), sql.Identifier(destino)
    conn.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(d))
    conn.execute(sql.SQL("CREATE SCHEMA {}").format(d))
    filas = {}
    for t in tablas(conn, origen):
        ti = sql.Identifier(t)
        conn.execute(sql.SQL("CREATE TABLE {}.{} (LIKE {}.{} INCLUDING ALL)").format(d, ti, o, ti))
        filas[t] = conn.execute(sql.SQL("INSERT INTO {}.{} SELECT * FROM {}.{}").format(d, ti, o, ti)).rowcount
    return filas


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--aplicar", action="store_true", help="confirma; sin esto, ROLLBACK")
    args = ap.parse_args()
    url = os.environ.get("RAILWAY_DATABASE_URL")
    if not url:
        sys.exit("Falta RAILWAY_DATABASE_URL (TCP Proxy del servicio pgvector).")
    with psycopg.connect(url) as conn:
        if not tablas(conn, ORIGEN):
            sys.exit(f"No encuentro el schema {ORIGEN} en esa base.")
        filas = copiar(conn)
        aplicar_migraciones(conn, DESTINO)
        print(f"> {len(filas)} tablas copiadas a {DESTINO}:")
        for t, n in filas.items():
            print(f"    {t}: {n}")
        if args.aplicar:
            conn.commit()
            print(f"\nListo: {DESTINO} creado. En reinventar-staging: CATALOGO_SCHEMA={DESTINO}.")
        else:
            conn.rollback()
            print("\nModo prueba: no se cambió nada. Si está bien, corré lo mismo con --aplicar.")


if __name__ == "__main__":
    main()
