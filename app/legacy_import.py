"""Importación única del SQLite anterior (/data/reinventar.db) a Postgres al primer arranque."""
import logging
import sqlite3
from pathlib import Path

log = logging.getLogger("reinventar.legacy_import")

# Orden sin importancia (no hay FKs entre estas tablas); se copian solo las columnas que existen en ambos lados.
TABLES = ("users", "auth_tokens", "sessions", "chunks", "blocks", "itinerary_profile", "itinerary_items")


def _pg_columns(c, table: str) -> list[str]:
    rows = c.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = current_schema() AND table_name = %s",
        (table,),
    ).fetchall()
    return [r["column_name"] for r in rows]


def _copy_table(src: sqlite3.Connection, c, table: str) -> int:
    exists = src.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
    if not exists:
        return 0
    src_cols = {r[1] for r in src.execute(f"PRAGMA table_info({table})")}
    cols = [col for col in _pg_columns(c, table) if col in src_cols]
    if not cols:
        return 0
    rows = src.execute(f"SELECT {', '.join(cols)} FROM {table}").fetchall()
    if rows:
        placeholders = ", ".join(["%s"] * len(cols))
        c.cursor().executemany(
            f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({placeholders}) ON CONFLICT DO NOTHING", rows
        )
    return len(rows)


def run_once(c, sqlite_path: Path) -> None:
    """Si existe el SQLite viejo y Postgres todavía no tiene usuarios, copia todo y renombra el archivo a .migrated."""
    if not sqlite_path.exists():
        return
    if c.execute("SELECT EXISTS (SELECT 1 FROM users)").fetchone()["exists"]:
        log.warning("Hay %s pero Postgres ya tiene usuarios: no se importa (borralo o renombralo a mano)", sqlite_path)
        return
    src = sqlite3.connect(sqlite_path)
    try:
        counts = {t: _copy_table(src, c, t) for t in TABLES}
    finally:
        src.close()
    c.commit()
    sqlite_path.rename(sqlite_path.with_suffix(".db.migrated"))
    log.info("SQLite importado a Postgres: %s", counts)
