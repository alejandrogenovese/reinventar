"""Extrae claves de búsqueda del resumen de cada charla con un LLM: servicios de AWS mencionados, otras tecnologías,
conceptos (castellano e inglés) y enfoque. Las usa la app para buscar y filtrar mejor que con las etiquetas de AWS.

Solo procesa lo que falta (conceptos IS NULL): charlas nuevas o cuyo resumen cambió (actualizar_catalogo.py las vacía).
Se puede cortar y volver a correr: cada lote se guarda apenas vuelve.
Sin --aplicar procesa una muestra y la muestra en pantalla, sin escribir nada.

Uso (desde la raíz del repo):
  export REINVENT_DATABASE_URL='postgresql://reinvent:<clave>@localhost:5433/reinvent'
  export ANTHROPIC_API_KEY=...
  python -m scripts.extraer_claves                              # muestra de 3, no escribe
  python -m scripts.extraer_claves --codigos AIM405,ANT301      # muestra con esas charlas
  python -m scripts.extraer_claves --aplicar                    # todo lo pendiente
"""
import argparse
import os
import sys
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass

import psycopg
from psycopg import sql

from app import config, llm, llm_router, prompts
from app.llm_router import Tarea
from scripts import lotes_llm, unificar_conceptos

LOTE = 15
HILOS = 4
MAX_TOKENS = 32000  # con Opus el razonamiento cuenta en este tope
MUESTRA = 3
MAX_CONCEPTOS = 8
MAX_NOMBRES = 15  # servicios y tecnologías por charla

Pendiente = tuple[str, str, str, str]  # (id_speech, título, tipo, resumen en inglés)
Completar = Callable[[str, str, str, int], str]  # misma firma que llm.complete


@dataclass(frozen=True)
class Claves:
    servicios_mencionados: tuple[str, ...]
    tecnologias: tuple[str, ...]
    conceptos: tuple[str, ...]
    conceptos_en: tuple[str, ...]
    enfoque: tuple[str, ...]


@dataclass(frozen=True)
class Resultado:
    procesadas: int
    lotes_fallidos: tuple[str, ...]
    muestra: tuple[tuple[str, Claves], ...] = ()


def _limpia(valores: object, maximo: int, canonico: Callable[[str], str] = lambda v: v) -> tuple[str, ...]:
    """Lista de strings sin vacíos ni repetidos (sin distinguir mayúsculas), en el orden en que vinieron."""
    if not isinstance(valores, list):
        raise ValueError(f"se esperaba una lista y vino {type(valores).__name__}")
    vistos, salida = set(), []
    for v in valores:
        texto = canonico(str(v).strip())
        if texto and texto.casefold() not in vistos:
            vistos.add(texto.casefold())
            salida.append(texto)
    return tuple(salida[:maximo])


def leer_claves(respuesta: str, ids: list[str], servicios_oficiales: Iterable[str] = ()) -> dict[str, Claves]:
    """Valida la respuesta del LLM: todos los ids, listas de strings, enfoque solo de los valores permitidos.
    Los servicios se llevan a la grafía oficial del catálogo cuando coinciden sin distinguir mayúsculas."""
    oficiales = {s.casefold(): s for s in servicios_oficiales}
    canonico = lambda s: oficiales.get(s.casefold(), s)  # noqa: E731
    try:
        charlas = {str(c["id"]): c for c in llm.parse_json(respuesta)["charlas"]}
        claves = {i: Claves(
            servicios_mencionados=_limpia(c.get("servicios", []), MAX_NOMBRES, canonico),
            tecnologias=_limpia(c.get("tecnologias", []), MAX_NOMBRES),
            conceptos=_limpia(c.get("conceptos", []), MAX_CONCEPTOS),
            conceptos_en=_limpia(c.get("conceptos_en", []), MAX_CONCEPTOS),
            enfoque=tuple(e for e in _limpia(c.get("enfoque", []), 3, str.lower) if e in prompts.ENFOQUES),
        ) for i, c in charlas.items()}
    except (ValueError, KeyError, TypeError, AttributeError) as e:
        raise ValueError(f"respuesta ilegible: {e}") from e
    faltan, sobran = [i for i in ids if i not in claves], set(claves) - set(ids)
    if faltan or sobran:
        raise ValueError(f"faltan {faltan} / sobran {sorted(sobran)}")
    return claves


def pendientes(conn: psycopg.Connection, schema: str = "reinvent", limite: int | None = None,
               codigos: list[str] | None = None) -> list[Pendiente]:
    """Charlas con resumen y sin claves; con codigos, solo esas (aunque ya tengan claves: sirve para probar)."""
    q = sql.SQL("""SELECT id_speech, titulo, tipo, resumen FROM {}.speech
                   WHERE coalesce(btrim(resumen), '') <> ''
                     AND (CASE WHEN %(codigos)s::text[] IS NULL THEN conceptos IS NULL
                               ELSE id_speech = ANY(%(codigos)s::text[]) END)
                   ORDER BY id_speech""").format(sql.Identifier(schema))
    filas = conn.execute(q, {"codigos": codigos}).fetchall()
    return filas[:limite] if limite else filas


def servicios_oficiales(conn: psycopg.Connection, schema: str = "reinvent") -> list[str]:
    q = sql.SQL("SELECT DISTINCT unnest(servicios) FROM {}.speech").format(sql.Identifier(schema))
    return [r[0] for r in conn.execute(q).fetchall()]


def _guardar(conn, schema: str, lote: list[Pendiente], claves: dict[str, Claves]) -> int:
    # Solo si el resumen sigue siendo el que se procesó (pudo cambiar mientras tanto).
    q = sql.SQL("""UPDATE {}.speech SET servicios_mencionados = %s, tecnologias = %s, conceptos = %s,
                   conceptos_en = %s, enfoque = %s WHERE id_speech = %s AND resumen = %s""").format(
        sql.Identifier(schema))
    filas = [(*(list(v) for v in asdict(claves[i]).values()), i, resumen) for i, _, _, resumen in lote]
    with conn.cursor() as cur:
        cur.executemany(q, filas)
        guardadas = cur.rowcount
    conn.commit()
    return guardadas


def extraer(conn: psycopg.Connection, *, schema: str = "reinvent", aplicar: bool = False, lote: int = LOTE,
            hilos: int = HILOS, limite: int | None = None, codigos: list[str] | None = None,
            completar: Completar = llm.complete, avisar: Callable[[str], None] = lambda _: None) -> Resultado:
    """Extrae las claves de lo pendiente en lotes paralelos. Sin aplicar, procesa una muestra y no escribe nada."""
    todos = pendientes(conn, schema, limite if aplicar or codigos else (limite or MUESTRA), codigos)
    oficiales = servicios_oficiales(conn, schema)
    guardadas, muestra = [0], []

    def llamar(lt: list[Pendiente]) -> dict[str, Claves]:
        respuesta = completar(Tarea.CATALOGO, prompts.KEYS_EXTRACT_SYSTEM, prompts.keys_user(lt), MAX_TOKENS)
        return leer_claves(respuesta, [p[0] for p in lt], oficiales)

    def al_volver(lt: list[Pendiente], claves: dict[str, Claves]) -> None:
        if aplicar:
            guardadas[0] += _guardar(conn, schema, lt, claves)
            avisar(f"  {guardadas[0]}/{len(todos)} procesadas")
        else:
            muestra.extend((p[0], claves[p[0]]) for p in lt)

    fallidos = lotes_llm.procesar(lotes_llm.en_lotes(todos, lote), llamar, al_volver, hilos=hilos,
                                  describir=lambda lt: str([p[0] for p in lt]), avisar=avisar)
    return Resultado(guardadas[0], fallidos, tuple(sorted(muestra)))


def _imprimir_muestra(muestra: tuple[tuple[str, Claves], ...]) -> None:
    for i, c in muestra:
        print(f"\n── {i}")
        for campo, valores in asdict(c).items():
            print(f"  {campo:<22}{', '.join(valores) or '—'}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--aplicar", action="store_true", help="procesa todo lo pendiente y lo guarda")
    ap.add_argument("--limite", type=int, help="procesar como mucho esta cantidad de charlas")
    ap.add_argument("--codigos", type=lambda v: [c.strip().upper() for c in v.split(",") if c.strip()],
                    help="solo estas charlas, separadas por coma")
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
        print(f"> {total} charlas sin claves · modelo {llm_router.modelo(Tarea.CATALOGO, config.LLM_PROVIDER)}"
              + ("" if args.aplicar else f" · MODO PRUEBA: muestra de {cuantas}, no se guarda nada"))
        r = extraer(conn, schema=args.schema, aplicar=args.aplicar, limite=args.limite, codigos=args.codigos,
                    avisar=print)
        if args.aplicar:  # los sinónimos se unifican sobre todo el catálogo, también con lo recién extraído
            unificadas = unificar_conceptos.unificar(conn, args.schema)
            conn.commit()
            print(f"Conceptos unificados (sinónimos) en {len(unificadas)} charlas")

    _imprimir_muestra(r.muestra)
    if args.aplicar:
        print(f"\nProcesadas y guardadas: {r.procesadas}")
    if r.lotes_fallidos:
        print(f"Lotes fallidos: {len(r.lotes_fallidos)} (volvé a correr el script para reintentarlos)")
        sys.exit(1)


if __name__ == "__main__":
    main()
