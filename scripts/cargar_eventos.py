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
from dataclasses import dataclass, field
from pathlib import Path

import httpx
import psycopg

from app import config
from app.eventos_carga import fila as armar_fila
from app.eventos_carga import resumir_con_llm, sedes_con_coordenadas, upsert
from app.eventos_fuentes import Evento, completar_con_pagina_luma, desde_json_luma
from scripts.actualizar_catalogo import _HOSTS_LOCALES, _backup, aplicar_migraciones

CACHE_DIR = Path(os.environ.get("LUMA_CACHE_DIR", "~/Documents/Proyectos/Scripts/reinventar/out/luma")).expanduser()
SEGUNDOS_ENTRE_PAGINAS = 1.0
USER_AGENT = "ReinventAR/1.0 (agenda personal de re:Invent)"
MUESTRA = 3

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


# ---------- base ----------

def _actuales(conn) -> dict[str, dict]:
    filas = conn.execute("SELECT id_evento, plataforma, nombre, descripcion, resumen_es, tipo, temas, organizadores "
                         "FROM evento").fetchall()
    return {f[0]: dict(zip(("id_evento", "plataforma", "nombre", "descripcion", "resumen_es", "tipo", "temas",
                            "organizadores"), f, strict=False)) for f in filas}


def cargar(conn, eventos: list[Evento], *, schema: str = "reinvent", resumir: Callable | None = None,
           limite_llm: int | None = None, borrar_bajas: bool = False) -> Reporte:
    """Aplica los eventos dentro de la transacción de conn; quien llama decide COMMIT o ROLLBACK.
    resumir(eventos) → (resúmenes por id, lotes fallidos); None = sin LLM (se conserva lo que ya había)."""
    aplicar_migraciones(conn, schema)
    actuales = _actuales(conn)
    sedes = sedes_con_coordenadas(conn)

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
        fila = armar_fila(ev, res, sedes)
        cuenta[upsert(conn, fila)] += 1
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
