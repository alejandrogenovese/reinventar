"""Carga los eventos de networking (desayunos, happy hours, fiestas, meetups) en reinvent.evento.

1. Lee el export de la fuente (por ahora Luma: datos/eventos_recreacion.json).
2. Baja la página pública de cada evento (caché local en LUMA_CACHE_DIR, fuera del repo) y suma fin, dirección,
   descripción, anotados, precio y aprobación.
3. Con el LLM (EXTRACT_MODEL) arma resumen en castellano, tipo, temas y organizadores. Solo para los eventos nuevos o
   cuya descripción cambió.
4. Calcula la sede de re:Invent más cercana y hace upsert. Lo que ya no está en el export se reporta (--borrar-bajas).

Por defecto corre en modo prueba: todo en una transacción con ROLLBACK, y el LLM solo para una muestra de 3.
Con --aplicar hace backup del schema (docker local) y confirma.

Uso (desde la raíz del repo):
  export REINVENT_DATABASE_URL='postgresql://reinvent:<clave>@localhost:5433/reinvent'
  export ANTHROPIC_API_KEY=...
  python -m scripts.cargar_eventos datos/eventos_recreacion.json             # prueba
  python -m scripts.cargar_eventos datos/eventos_recreacion.json --aplicar   # de verdad
"""
import argparse
import json
import os
import sys
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path

import httpx
import psycopg
from psycopg import sql

from app import config, llm, prompts
from scripts import lotes_llm
from scripts.actualizar_catalogo import _HOSTS_LOCALES, _backup, aplicar_migraciones
from scripts.eventos_fuentes import Evento, completar_con_pagina_luma, desde_json_luma, sede_mas_cercana
from app.llm_router import Tarea

CACHE_DIR = Path(os.environ.get("LUMA_CACHE_DIR", "~/Documents/Proyectos/Scripts/reinventar/out/luma")).expanduser()
SEGUNDOS_ENTRE_PAGINAS = 1.0
LOTE, HILOS, MAX_TOKENS = 10, 3, 32000
MAX_DESCRIPCION = 4000  # caracteres que van al LLM
USER_AGENT = "ReinventAR/1.0 (agenda personal de re:Invent)"
MUESTRA = 3

_COLUMNAS = ("plataforma", "url", "nombre", "inicio", "fin", "imagen_url", "lat", "lng", "lugar", "direccion",
             "direccion_exacta", "google_place_id", "descripcion", "resumen_es", "tipo", "temas", "organizadores",
             "anotados", "lleno", "precio", "requiere_aprobacion", "id_sede_cercana", "metros_a_sede")

Resumir = Callable[[list[Evento]], dict[str, dict]]


@dataclass(frozen=True)
class Reporte:
    nuevos: int = 0
    actualizados: int = 0
    sin_cambios: int = 0
    resumidos: int = 0
    sin_direccion_exacta: tuple[str, ...] = ()
    bajas: tuple[str, ...] = ()
    lotes_fallidos: tuple[str, ...] = ()
    muestra: tuple[dict, ...] = field(default_factory=tuple)


# ---------- fuente ----------

def leer_export(crudo: dict) -> list[Evento]:
    """Eventos del export de Luma, sin repetidos."""
    eventos = {}
    for entrada in crudo.get("entries") or []:
        if entrada.get("platform", "luma") == "luma":
            ev = desde_json_luma(entrada)
            eventos[ev.id_evento] = ev
    return list(eventos.values())


def bajar_paginas(eventos: list[Evento], *, refrescar: bool = False, http: httpx.Client | None = None,
                  avisar: Callable[[str], None] = lambda _: None) -> list[Evento]:
    """Completa cada evento con su página pública (caché local; una página por segundo para no castigar a Luma)."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    http = http or httpx.Client(timeout=30, follow_redirects=True, headers={"User-Agent": USER_AGENT})
    completos = []
    for ev in eventos:
        archivo = CACHE_DIR / f"{ev.id_evento}.html"
        if refrescar or not archivo.exists():
            try:
                r = http.get(ev.url)
                r.raise_for_status()
                archivo.write_text(r.text, encoding="utf-8")
            except httpx.HTTPError as e:
                avisar(f"  sin página para {ev.id_evento} ({ev.nombre[:50]}): {e}")
                completos.append(ev)
                continue
            time.sleep(SEGUNDOS_ENTRE_PAGINAS)
        completos.append(completar_con_pagina_luma(ev, archivo.read_text(encoding="utf-8")))
    return completos


# ---------- LLM ----------

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


# ---------- base ----------

def _actuales(conn) -> dict[str, dict]:
    filas = conn.execute("SELECT id_evento, plataforma, nombre, descripcion, resumen_es, tipo, temas, organizadores "
                         "FROM evento").fetchall()
    return {f[0]: dict(zip(("id_evento", "plataforma", "nombre", "descripcion", "resumen_es", "tipo", "temas",
                            "organizadores"), f)) for f in filas}


def _upsert(conn, fila: dict) -> str:
    """'nuevo' | 'actualizado' | 'igual'. Solo escribe (y toca `actualizado`) si algo cambió."""
    columnas = sql.SQL(", ").join(map(sql.Identifier, ("id_evento", *_COLUMNAS)))
    marcas = sql.SQL(", ").join(sql.Placeholder(c) for c in ("id_evento", *_COLUMNAS))
    asignar = sql.SQL(", ").join(sql.SQL("{c} = EXCLUDED.{c}").format(c=sql.Identifier(c)) for c in _COLUMNAS)
    viejas = sql.SQL(", ").join(sql.SQL("evento.{c}").format(c=sql.Identifier(c)) for c in _COLUMNAS)
    nuevas = sql.SQL(", ").join(sql.SQL("EXCLUDED.{c}").format(c=sql.Identifier(c)) for c in _COLUMNAS)
    r = conn.execute(sql.SQL("""
      INSERT INTO evento ({}) VALUES ({})
      ON CONFLICT (id_evento) DO UPDATE SET {}, actualizado = now() WHERE ({}) IS DISTINCT FROM ({})
      RETURNING (xmax = 0) AS nuevo""").format(columnas, marcas, asignar, viejas, nuevas), fila).fetchone()
    if r is None:
        return "igual"
    return "nuevo" if r[0] else "actualizado"


def cargar(conn, eventos: list[Evento], *, schema: str = "reinvent", resumir: Callable | None = None,
           limite_llm: int | None = None, borrar_bajas: bool = False) -> Reporte:
    """Aplica los eventos dentro de la transacción de conn; quien llama decide COMMIT o ROLLBACK.
    resumir(eventos) → (resúmenes por id, lotes fallidos); None = sin LLM (se conserva lo que ya había)."""
    aplicar_migraciones(conn, schema)
    actuales = _actuales(conn)
    sedes = [(i, float(lat), float(lng)) for i, lat, lng in
             conn.execute("SELECT id_sede, lat, lng FROM sede WHERE lat IS NOT NULL").fetchall()]

    # Al LLM solo lo nuevo o lo que cambió de nombre o descripción.
    pendientes = [e for e in eventos if not (a := actuales.get(e.id_evento)) or not a["resumen_es"]
                  or (a["descripcion"], a["nombre"]) != (e.descripcion, e.nombre)]
    pendientes = pendientes[:limite_llm] if limite_llm is not None else pendientes
    resumenes, fallidos = resumir(pendientes) if resumir and pendientes else ({}, ())

    cuenta = {"nuevo": 0, "actualizado": 0, "igual": 0}
    muestra = []
    for ev in eventos:
        previo = actuales.get(ev.id_evento) or {}
        res = resumenes.get(ev.id_evento) or {k: previo.get(k) for k in ("resumen_es", "tipo", "temas", "organizadores")}
        id_sede, metros = sede_mas_cercana(ev, sedes)
        fila = {**asdict(ev), "resumen_es": res.get("resumen_es"), "tipo": res.get("tipo"),
                "temas": list(res.get("temas") or []), "organizadores": list(res.get("organizadores") or []),
                "id_sede_cercana": id_sede, "metros_a_sede": metros}
        cuenta[_upsert(conn, fila)] += 1
        if ev.id_evento in resumenes:
            muestra.append(fila)

    vigentes = {e.id_evento for e in eventos}
    plataformas = {e.plataforma for e in eventos}
    bajas = tuple(sorted(i for i, a in actuales.items() if i not in vigentes and a["plataforma"] in plataformas))
    if borrar_bajas and bajas:
        conn.execute("DELETE FROM evento WHERE id_evento = ANY(%s)", (list(bajas),))
    return Reporte(cuenta["nuevo"], cuenta["actualizado"], cuenta["igual"], len(resumenes),
                   tuple(e.nombre for e in eventos if not e.direccion_exacta), bajas, tuple(fallidos), tuple(muestra))


# ---------- CLI ----------

def _imprimir(r: Reporte) -> None:
    print(f"Eventos nuevos: {r.nuevos} · actualizados: {r.actualizados} · sin cambios: {r.sin_cambios}")
    print(f"Resumidos con el LLM: {r.resumidos}" + (f" · lotes fallidos: {len(r.lotes_fallidos)}" if r.lotes_fallidos else ""))
    if r.sin_direccion_exacta:
        print(f"Sin dirección exacta (Luma la muestra al anotarte): {len(r.sin_direccion_exacta)}")
    if r.bajas:
        print(f"Ya no están en el export (se borran con --borrar-bajas): {', '.join(r.bajas)}")
    for f in r.muestra[:MUESTRA]:
        print(f"\n── {f['nombre']}\n   {f['tipo']} · {f['lugar'] or 'Las Vegas'} · {f['precio'] or '—'}"
              f" · {f['anotados'] or 0} anotados · organizan: {', '.join(f['organizadores']) or '—'}"
              f"\n   {f['resumen_es']}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("json", type=Path, help="export de Luma (entries[])")
    ap.add_argument("--aplicar", action="store_true", help="confirma (con backup previo); sin esto, ROLLBACK")
    ap.add_argument("--sin-llm", action="store_true", help="no resume con el LLM (conserva lo que ya había)")
    ap.add_argument("--refrescar", action="store_true", help="vuelve a bajar las páginas aunque estén en caché")
    ap.add_argument("--borrar-bajas", action="store_true")
    ap.add_argument("--schema", default="reinvent")
    args = ap.parse_args()

    url = os.environ.get("REINVENT_DATABASE_URL")
    if not url:
        sys.exit("Falta REINVENT_DATABASE_URL (Postgres del docker local).")
    if args.aplicar and not any(h in url for h in _HOSTS_LOCALES):
        sys.exit("--aplicar solo contra el docker local (localhost). A Railway se sube con scripts/sync_to_railway.sh.")
    if not args.sin_llm and config.LLM_PROVIDER == "anthropic" and not config.ANTHROPIC_API_KEY:
        sys.exit("Falta ANTHROPIC_API_KEY (o corré con --sin-llm).")
    try:
        eventos = leer_export(json.loads(args.json.read_text(encoding="utf-8")))
    except (OSError, ValueError, KeyError) as e:
        sys.exit(f"No pude leer {args.json}: {e}")

    print(f"> {len(eventos)} eventos en el export · bajando páginas (caché: {CACHE_DIR})")
    eventos = bajar_paginas(eventos, refrescar=args.refrescar, avisar=print)
    backup = _backup(args.schema) if args.aplicar else None
    print("> " + ("APLICANDO cambios" if args.aplicar else "MODO PRUEBA (todo se deshace; LLM solo para 3)") + "\n")
    with psycopg.connect(url) as conn:
        r = cargar(conn, eventos, schema=args.schema, resumir=None if args.sin_llm else resumir_con_llm,
                   limite_llm=None if args.aplicar else MUESTRA, borrar_bajas=args.borrar_bajas)
        _imprimir(r)
        if args.aplicar:
            conn.commit()
            print(f"\nListo. Backup previo: {backup}")
        else:
            conn.rollback()
            print("\nNo se cambió nada. Si está bien, corré lo mismo con --aplicar.")


if __name__ == "__main__":
    main()
