"""Traduce al castellano el resumen oficial de cada charla (speech.resumen → speech.resumen_es) con Claude.

Solo traduce lo que falta: charlas nuevas, o aquellas cuyo resumen cambió (actualizar_catalogo.py vacía resumen_es).
Se puede cortar y volver a correr: cada lote se guarda apenas vuelve.

Sin --aplicar traduce una muestra y la muestra en pantalla, sin escribir nada (sirve para ver la calidad).

Uso (desde la raíz del repo):
  export REINVENT_DATABASE_URL='postgresql://reinvent:<clave>@localhost:5433/reinvent'
  export ANTHROPIC_API_KEY=...            # la misma que usa la app en Railway
  python -m scripts.traducir_resumenes                 # muestra de 3, no escribe
  python -m scripts.traducir_resumenes --codigos AIM405,ANT301   # muestra con esas charlas
  python -m scripts.traducir_resumenes --aplicar       # todo lo pendiente
"""
import argparse
import os
import sys
from collections.abc import Callable
from dataclasses import dataclass

import psycopg
from psycopg import sql

from app import config, llm, llm_router, lotes_llm, prompts
from app.llm_router import Tarea

LOTE = 15  # resúmenes por llamada (~610 caracteres cada uno: entra holgado en la respuesta)
HILOS = 4
MAX_TOKENS = 32000  # Opus piensa antes de responder y el razonamiento cuenta en este tope
MUESTRA = 3

Pendiente = tuple[str, str, str]  # (id_speech, título, resumen en inglés)
Completar = Callable[[str, str, str, int], str]  # misma firma que llm.complete


@dataclass(frozen=True)
class Resultado:
    traducidas: int
    lotes_fallidos: tuple[str, ...]  # mensajes de error, con los ids del lote
    muestra: tuple[tuple[str, str, str], ...] = ()  # (id, original, traducción) en modo prueba


def leer_traducciones(respuesta: str, ids: list[str]) -> dict[str, str]:
    """Valida la respuesta del LLM: todos los ids pedidos, ninguno vacío ni de más."""
    try:
        items = llm.parse_json(respuesta)["traducciones"]
        traducciones = {str(t["id"]): str(t["texto"]).strip() for t in items}
    except (ValueError, KeyError, TypeError) as e:
        raise ValueError(f"respuesta ilegible: {e}") from e
    faltan = [i for i in ids if not traducciones.get(i)]
    sobran = set(traducciones) - set(ids)
    if faltan or sobran:
        raise ValueError(f"faltan {faltan} / sobran {sorted(sobran)}")
    return traducciones


def pendientes(conn: psycopg.Connection, schema: str = "reinvent", limite: int | None = None,
               codigos: list[str] | None = None) -> list[Pendiente]:
    """Charlas con resumen y sin traducción; con codigos, solo esas (aunque ya estén traducidas: sirve para probar)."""
    q = sql.SQL("""SELECT id_speech, titulo, resumen FROM {}.speech
                   WHERE coalesce(btrim(resumen), '') <> ''
                     AND (CASE WHEN %(codigos)s::text[] IS NULL THEN resumen_es IS NULL
                               ELSE id_speech = ANY(%(codigos)s::text[]) END)
                   ORDER BY id_speech""").format(sql.Identifier(schema))
    filas = conn.execute(q, {"codigos": codigos}).fetchall()
    return filas[:limite] if limite else filas


def _traducir_lote(lote: list[Pendiente], completar: Completar) -> dict[str, str]:
    respuesta = completar(Tarea.CATALOGO_TRADUCCION, prompts.ABSTRACT_TRANSLATE_SYSTEM, prompts.abstracts_user(lote),
                          MAX_TOKENS)
    return leer_traducciones(respuesta, [p[0] for p in lote])


def _guardar(conn, schema: str, lote: list[Pendiente], traducciones: dict[str, str]) -> int:
    # Solo si el resumen sigue siendo el que se tradujo (pudo cambiar mientras tanto).
    q = sql.SQL("UPDATE {}.speech SET resumen_es = %s WHERE id_speech = %s AND resumen = %s").format(
        sql.Identifier(schema))
    with conn.cursor() as cur:
        cur.executemany(q, [(traducciones[i], i, original) for i, _, original in lote])
        guardadas = cur.rowcount
    conn.commit()
    return guardadas


def traducir(conn: psycopg.Connection, *, schema: str = "reinvent", aplicar: bool = False, lote: int = LOTE,
             hilos: int = HILOS, limite: int | None = None, codigos: list[str] | None = None,
             completar: Completar = llm.complete,
             avisar: Callable[[str], None] = lambda _: None) -> Resultado:
    """Traduce lo pendiente en lotes paralelos. Sin aplicar, traduce una muestra y no escribe nada."""
    todos = pendientes(conn, schema, limite if aplicar or codigos else (limite or MUESTRA), codigos)
    guardadas, muestra = [0], []

    def al_volver(lt: list[Pendiente], traducciones: dict[str, str]) -> None:
        if aplicar:
            guardadas[0] += _guardar(conn, schema, lt, traducciones)
            avisar(f"  {guardadas[0]}/{len(todos)} traducidas")
        else:
            muestra.extend((i, original, traducciones[i]) for i, _, original in lt)

    fallidos = lotes_llm.procesar(lotes_llm.en_lotes(todos, lote), lambda lt: _traducir_lote(lt, completar), al_volver,
                                  hilos=hilos, describir=lambda lt: str([p[0] for p in lt]), avisar=avisar)
    return Resultado(guardadas[0], fallidos, tuple(muestra))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--aplicar", action="store_true", help="traduce todo lo pendiente y lo guarda")
    ap.add_argument("--limite", type=int, help="traducir como mucho esta cantidad de charlas")
    ap.add_argument("--codigos", type=lambda v: [c.strip().upper() for c in v.split(",") if c.strip()],
                    help="solo estas charlas, separadas por coma (p. ej. para probar la muestra con charlas técnicas)")
    ap.add_argument("--schema", default="reinvent")
    args = ap.parse_args()

    url = os.environ.get("REINVENT_DATABASE_URL")
    if not url:
        sys.exit("Falta REINVENT_DATABASE_URL (Postgres del docker local).")
    if config.LLM_PROVIDER == "anthropic" and not config.ANTHROPIC_API_KEY:
        sys.exit("Falta ANTHROPIC_API_KEY.")

    with psycopg.connect(url) as conn:
        total = len(pendientes(conn, args.schema))
        cuantas = len(args.codigos) if args.codigos else args.limite or MUESTRA
        print(f"> {total} resúmenes sin traducir · modelo {llm_router.modelo(Tarea.CATALOGO_TRADUCCION, config.LLM_PROVIDER)}"
              + ("" if args.aplicar else f" · MODO PRUEBA: muestra de {cuantas}, no se guarda nada"))
        r = traducir(conn, schema=args.schema, aplicar=args.aplicar, limite=args.limite, codigos=args.codigos,
                     avisar=print)

    for i, original, traduccion in r.muestra:
        print(f"\n── {i}\nEN: {original}\nES: {traduccion}")
    if args.aplicar:
        print(f"\nTraducidas y guardadas: {r.traducidas}")
    if r.lotes_fallidos:
        print(f"Lotes fallidos: {len(r.lotes_fallidos)} (volvé a correr el script para reintentarlos)")
        sys.exit(1)


if __name__ == "__main__":
    main()
