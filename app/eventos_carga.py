"""Resumen con el LLM y guardado de eventos en reinvent.evento: lo comparten el cargador manual
(scripts/cargar_eventos.py) y la revisión automática (app/eventos_auto.py).

Las funciones de base usan el search_path de la conexión (el schema del catálogo, o uno efímero en los tests).
"""
from collections.abc import Callable
from dataclasses import asdict

from psycopg import sql

from . import llm, lotes_llm, prompts
from .eventos_fuentes import Evento, sede_mas_cercana
from .llm_router import Tarea

LOTE, HILOS, MAX_TOKENS = 10, 3, 32000
MAX_DESCRIPCION = 4000  # caracteres que van al LLM

COLUMNAS = ("plataforma", "url", "nombre", "inicio", "fin", "imagen_url", "lat", "lng", "lugar", "direccion",
            "direccion_exacta", "google_place_id", "descripcion", "resumen_es", "tipo", "temas", "organizadores",
            "anotados", "lleno", "precio", "requiere_aprobacion", "id_sede_cercana", "metros_a_sede")


def sedes_con_coordenadas(conn) -> list[tuple[int, float, float]]:
    return [(i, float(lat), float(lng)) for i, lat, lng in
            conn.execute("SELECT id_sede, lat, lng FROM sede WHERE lat IS NOT NULL").fetchall()]


def fila(ev: Evento, resumen: dict, sedes: list[tuple[int, float, float]]) -> dict:
    """La fila de reinvent.evento: los datos de la fuente, el resumen del LLM y la sede más cercana."""
    id_sede, metros = sede_mas_cercana(ev, sedes)
    return {**asdict(ev), "resumen_es": resumen.get("resumen_es"), "tipo": resumen.get("tipo"),
            "temas": list(resumen.get("temas") or []), "organizadores": list(resumen.get("organizadores") or []),
            "id_sede_cercana": id_sede, "metros_a_sede": metros}


def leer_resumenes(respuesta: str, ids: list[str]) -> dict[str, dict]:
    try:
        items = {str(e["id"]): e for e in llm.parse_json(respuesta)["eventos"]}
    except (ValueError, KeyError, TypeError) as e:
        raise ValueError(f"respuesta ilegible: {e}") from e
    faltan = [i for i in ids if not (items.get(i) or {}).get("resumen_es")]
    if faltan:
        raise ValueError(f"faltan {faltan}")
    lista = lambda v, n: tuple(str(x).strip() for x in (v or []) if str(x).strip())[:n]  # noqa: E731
    return {i: {"resumen_es": str(items[i]["resumen_es"]).strip(),
                "tipo": items[i].get("tipo") if items[i].get("tipo") in prompts.EVENT_TYPES else None,
                "temas": list(lista(items[i].get("temas"), 4)),
                "organizadores": list(lista(items[i].get("organizadores"), 8))} for i in ids}


def resumir_con_llm(eventos: list[Evento], avisar: Callable[[str], None] = lambda _: None) -> tuple[dict, tuple]:
    """Resúmenes por id, en lotes paralelos; devuelve (resúmenes, errores de lotes)."""
    resultado: dict[str, dict] = {}

    def llamar(lote: list[Evento]) -> dict[str, dict]:
        items = [(e.id_evento, e.nombre, e.lugar or "", (e.descripcion or "")[:MAX_DESCRIPCION]) for e in lote]
        respuesta = llm.complete(Tarea.CATALOGO, prompts.EVENTS_SYSTEM, prompts.events_user(items), MAX_TOKENS)
        return leer_resumenes(respuesta, [e.id_evento for e in lote])

    fallidos = lotes_llm.procesar(lotes_llm.en_lotes(eventos, LOTE), llamar, lambda _l, r: resultado.update(r),
                                  hilos=HILOS, describir=lambda lote: str([e.id_evento for e in lote]), avisar=avisar)
    return resultado, fallidos


def upsert(conn, fila: dict) -> str:
    """'nuevo' | 'actualizado' | 'igual'. Solo escribe (y toca `actualizado`) si algo cambió."""
    columnas = sql.SQL(", ").join(map(sql.Identifier, ("id_evento", *COLUMNAS)))
    marcas = sql.SQL(", ").join(sql.Placeholder(c) for c in ("id_evento", *COLUMNAS))
    asignar = sql.SQL(", ").join(sql.SQL("{c} = EXCLUDED.{c}").format(c=sql.Identifier(c)) for c in COLUMNAS)
    viejas = sql.SQL(", ").join(sql.SQL("evento.{c}").format(c=sql.Identifier(c)) for c in COLUMNAS)
    nuevas = sql.SQL(", ").join(sql.SQL("EXCLUDED.{c}").format(c=sql.Identifier(c)) for c in COLUMNAS)
    r = conn.execute(sql.SQL("""
      INSERT INTO evento ({}) VALUES ({})
      ON CONFLICT (id_evento) DO UPDATE SET {}, actualizado = now() WHERE ({}) IS DISTINCT FROM ({})
      RETURNING (xmax = 0) AS nuevo""").format(columnas, marcas, asignar, viejas, nuevas), fila).fetchone()
    if r is None:
        return "igual"
    return "nuevo" if r[0] else "actualizado"


