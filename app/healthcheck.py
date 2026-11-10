"""Chequeo funcional para Admin: prueba cada parte de la app sin tocar datos reales y sin gastar en APIs.

Cada chequeo devuelve {name, ok, detail, ms}. Lo que escribe (itinerario de prueba) va al schema de prueba y se borra.
Los chequeos del celular (ubicación, mapa, Routes API, notificaciones) los hace la PWA: ver web/js/account.js.
"""
import datetime as dt
import threading
import time
from collections.abc import Callable

from . import catalog, config, db, events, explore, itinerary, llm, push, sandbox, search, today, venues

CHECK_USER = "__chequeo__"


def _catalogo() -> str:
    sessions = catalog.all_sessions()
    if not sessions:
        raise AssertionError("catálogo vacío")
    con_coords = sum(1 for v in venues.all_venues() if v["lat"] is not None)
    return f"{len(sessions)} charlas · {con_coords}/{len(venues.all_venues())} sedes con coordenadas"


def _resumenes() -> str:
    sessions = catalog.all_sessions()
    traducidas = sum(1 for s in sessions if s.get("abstract_es"))
    con_claves = sum(1 for s in sessions if s.get("concepts"))
    if not traducidas:
        raise AssertionError("ningún resumen traducido (correr traducir_resumenes)")
    return f"{traducidas}/{len(sessions)} traducidos · {con_claves} con claves"


def _eventos() -> str:
    todos = [e for d in events.by_day() for e in d["events"]]
    if not todos:
        raise AssertionError("sin eventos (correr cargar_eventos y el sync)")
    return (f"{len(todos)} eventos · {sum(1 for e in todos if e.get('summary'))} con resumen · "
            f"{sum(1 for e in todos if e['venue'].get('exact'))} con dirección exacta")


def _busqueda() -> str:
    hits = search.hybrid("lakehouse", limit=25)
    if not hits:
        raise AssertionError("'lakehouse' no encontró nada")
    return f"'lakehouse' → {len(hits)} resultados"


def _explorar() -> str:
    facets = explore.explore({}, limit=1)["facets"]
    return f"{len(facets)} facetas"


def _datos_de_prueba() -> str:
    """Escribe y lee un itinerario en el schema de prueba, y lo borra."""
    session = next(s for s in catalog.all_sessions() if s.get("instances"))
    code = session["instances"][0]["c"]
    with sandbox.activar(sandbox.Sandbox(CHECK_USER)):
        itinerary.add_manual(CHECK_USER, code)
        ok = any(c["code"] == code for d in itinerary.get_current(CHECK_USER)["days"] for c in d["sessions"])
        db.remove_item(CHECK_USER, code)
    with sandbox.real():
        en_real = any(it["code"] == code for it in db.list_itinerary_items(CHECK_USER))
    if not ok or en_real:
        raise AssertionError("el itinerario de prueba no quedó aislado del real")
    return f"itinerario escrito y leído en {sandbox.schema_prueba()} (lo real no se tocó)"


def _reloj_simulado() -> str:
    momento = dt.datetime(2026, 12, 1, 13, 40, tzinfo=sandbox.EVENT_TZ)
    with sandbox.activar(sandbox.Sandbox(CHECK_USER, reloj=momento, reloj_fijado=time.time())):
        ahora = sandbox.ahora()
    plan = today.plan([{"day": "2026-12-01", "sessions": [{"code": "X", "title": "X", "start": "13:30", "end": "14:30", "type": ""}]}], ahora)
    if not plan["now"]:
        raise AssertionError("'Hoy' no tomó la hora simulada")
    dia = ("lun", "mar", "mié", "jue", "vie", "sáb", "dom")[ahora.weekday()]
    return f"simulado {dia} {ahora:%d/%m %H:%M} → 'Hoy' muestra la charla en curso"


def _llm() -> str:
    with sandbox.activar(sandbox.Sandbox(CHECK_USER, llm="fake")):
        llm.complete("fake", "Sos un test.", "Pregunta: hola", 50)
    real = config.LLM_PROVIDER
    configurado = real == "fake" or (real == "anthropic" and config.ANTHROPIC_API_KEY) or (real == "openai" and config.LLM_BASE_URL)
    if not configurado:
        raise AssertionError(f"LLM_PROVIDER={real} sin credenciales")
    return f"proveedor {real} configurado (no se llamó a la API paga)"


def _stt() -> str:
    real = config.STT_PROVIDER
    if real == "openai" and not config.STT_API_KEY:
        raise AssertionError("STT_PROVIDER=openai sin STT_API_KEY")
    return f"proveedor {real} configurado"


def _hilos() -> str:
    vivos = {t.name for t in threading.enumerate()}
    faltan = [n for n in ("pipeline",) + (("push",) if push.enabled() else ()) if n not in vivos]
    if faltan:
        raise AssertionError(f"no está corriendo: {', '.join(faltan)}")
    return "pipeline de grabaciones" + (" y avisos Web Push" if push.enabled() else "") + " corriendo"


def _claves_externas() -> str:
    faltan = [n for n, v in (("GOOGLE_MAPS_API_KEY", config.GOOGLE_MAPS_API_KEY), ("VAPID_PUBLIC_KEY", config.VAPID_PUBLIC_KEY),
                             ("VAPID_PRIVATE_KEY", config.VAPID_PRIVATE_KEY)) if not v]
    if faltan:
        raise AssertionError(f"faltan: {', '.join(faltan)}")
    return "Google Maps y Web Push configurados"


CHECKS: list[tuple[str, Callable[[], str]]] = [
    ("Catálogo", _catalogo), ("Resúmenes y claves", _resumenes), ("Eventos", _eventos), ("Búsqueda", _busqueda),
    ("Explorar", _explorar), ("Datos de prueba aislados", _datos_de_prueba), ("Reloj simulado y Hoy", _reloj_simulado),
    ("LLM", _llm), ("Transcripción", _stt), ("Procesos en segundo plano", _hilos), ("Claves externas", _claves_externas),
]


def run_all() -> list[dict]:
    out = []
    for name, check in CHECKS:
        t0 = time.perf_counter()
        try:
            ok, detail = True, check()
        except Exception as e:  # noqa: BLE001 — el chequeo informa el error en lugar de cortar
            ok, detail = False, str(e) or type(e).__name__
        out.append({"name": name, "ok": ok, "detail": detail, "ms": round((time.perf_counter() - t0) * 1000)})
    return out
