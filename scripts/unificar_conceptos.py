"""Unifica sinónimos en speech.conceptos para que el filtro "Concepto" de Explorar no se fragmente.

Señal: los conceptos vienen de a pares (castellano, inglés). Si varias formas en castellano comparten la misma forma en
inglés ("cumplimiento normativo" y "cumplimiento regulatorio" → "regulatory compliance"), todas pasan a la más usada.
Sin LLM, determinístico e idempotente: extraer_claves.py lo corre al final de cada --aplicar.

Uso: python -m scripts.unificar_conceptos [--aplicar]   (sin --aplicar muestra los cambios y no escribe)
"""
import argparse
import os
import sys
from collections import Counter, defaultdict
from collections.abc import Iterable

import psycopg
from psycopg import sql

Fila = tuple[str, list[str], list[str]]  # (id_speech, conceptos, conceptos_en)


def _mas_usada(formas: Counter) -> str:
    """La forma más usada; si empatan, la más corta y después la primera en orden alfabético."""
    return min(formas.items(), key=lambda kv: (-kv[1], len(kv[0]), kv[0]))[0]


def canonicos(filas: Iterable[Fila]) -> dict[str, tuple[str, str]]:
    """Por clave inglesa (sin mayúsculas): (forma en castellano, forma en inglés) que gana."""
    es_por_en, en_por_en = defaultdict(Counter), defaultdict(Counter)
    for _, conceptos, conceptos_en in filas:
        for es, en in zip(conceptos, conceptos_en, strict=False):
            es_por_en[en.casefold()][es] += 1
            en_por_en[en.casefold()][en] += 1
    return {k: (_mas_usada(es_por_en[k]), _mas_usada(en_por_en[k])) for k in es_por_en}


def plan(filas: list[Fila]) -> dict[str, tuple[list[str], list[str]]]:
    """Charlas cuyos conceptos cambian → (conceptos, conceptos_en) nuevos, sin repetidos y en el mismo orden."""
    canon = canonicos(filas)
    cambios = {}
    for id_speech, conceptos, conceptos_en in filas:
        if len(conceptos) != len(conceptos_en):  # sin pares alineados no hay señal: se deja como está
            continue
        nuevos_es, nuevos_en, vistos = [], [], set()
        for en in conceptos_en:
            es2, en2 = canon[en.casefold()]
            if es2.casefold() not in vistos:
                vistos.add(es2.casefold())
                nuevos_es.append(es2)
                nuevos_en.append(en2)
        if (nuevos_es, nuevos_en) != (conceptos, conceptos_en):
            cambios[id_speech] = (nuevos_es, nuevos_en)
    return cambios


def unificar(conn: psycopg.Connection, schema: str = "reinvent", *, aplicar: bool = True) -> dict:
    """Aplica el plan dentro de la transacción de conn (quien llama hace commit). Devuelve el plan."""
    esquema = sql.Identifier(schema)
    filas = conn.execute(sql.SQL("SELECT id_speech, conceptos, conceptos_en FROM {}.speech "
                                 "WHERE conceptos IS NOT NULL ORDER BY id_speech").format(esquema)).fetchall()
    cambios = plan(filas)
    if aplicar and cambios:
        with conn.cursor() as cur:
            cur.executemany(sql.SQL("UPDATE {}.speech SET conceptos = %s, conceptos_en = %s WHERE id_speech = %s")
                            .format(esquema), [(es, en, i) for i, (es, en) in cambios.items()])
    return cambios


def _distintos(conn, schema: str) -> int:
    q = sql.SQL("SELECT count(DISTINCT c) FROM {}.speech, unnest(conceptos) c").format(sql.Identifier(schema))
    return conn.execute(q).fetchone()[0]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--aplicar", action="store_true")
    ap.add_argument("--schema", default="reinvent")
    args = ap.parse_args()
    url = os.environ.get("REINVENT_DATABASE_URL")
    if not url:
        sys.exit("Falta REINVENT_DATABASE_URL (Postgres del docker local).")
    with psycopg.connect(url) as conn:
        antes = _distintos(conn, args.schema)
        cambios = unificar(conn, args.schema)
        despues = _distintos(conn, args.schema)
        if args.aplicar:
            conn.commit()
        else:
            conn.rollback()
    print(f"Charlas con conceptos unificados: {len(cambios)} · conceptos distintos: {antes} → {despues}"
          + ("" if args.aplicar else " (modo prueba, no se guardó)"))


if __name__ == "__main__":
    main()
