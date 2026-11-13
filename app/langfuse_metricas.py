"""Tablero de LLM del portal de admin: métricas de Langfuse leídas desde el servidor.

Usa la API pública de métricas v2 (GET /api/public/v2/metrics, con un `query` JSON y basic auth con las claves del
proyecto). La v1 (/api/public/metrics y /metrics/daily) está deprecada. Cada fila trae las dimensiones pedidas y las
métricas con nombre `{agregación}_{medida}` (p. ej. `sum_totalCost`, `p95_latency`); el día viene en `time_dimension`.

La tarea de cada llamada es el nombre de la observación (`name`, el `generation_name` que mandan app/llm.py y
app/stt.py vía app/trazas.py), no el de la traza: una grabación es una sola traza "grabacion" con el STT, la traducción y
el resumen adentro. Llamadas, demora, costo y errores cuentan solo observaciones de tipo GENERATION (las llamadas al
modelo, no SPAN ni EVENT).

Lo de los últimos 7 días excluye el tráfico con tag "prueba" (modo prueba), para que no ensucie costo, demora ni scores.
El mes no lo excluye: el costo y las unidades del plan se gastan igual.

Las unidades del plan (trazas + observaciones + scores) no salen de la API pública y la v2 no tiene vista de trazas: las
"trazas" se cuentan como observaciones raíz (`isRootObservation`). Las generaciones que manda LiteLLM no tienen padre,
así que cada una cuenta como raíz y el total es una cota superior (con varias llamadas por traza, las trazas reales son
menos). El tablero lo muestra como "cota superior estimada".

Las claves se quedan en el servidor: al navegador solo llegan números y la URL del
proyecto. Sin claves, o si Langfuse falla o tarda, se devuelve {"disponible": false, "motivo": ...}.
"""
import datetime as dt
import json
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

import httpx

from . import config

log = logging.getLogger(__name__)

TIMEOUT_S = 4.0  # por consulta; van en paralelo, así que el tablero no tarda mucho más que esto
CACHE_S = 300  # 5 minutos: no gastar llamadas cada vez que alguien abre el portal
CACHE_FALLA_S = 60  # si Langfuse falló, se reintenta antes
DIAS = 7
UNIDADES_PLAN = 50_000  # plan Hobby de Langfuse: trazas + observaciones + scores por mes
SCORES = ("lineas_faltantes", "json_valido", "codigos_inventados", "momentos_citados", "util")
FILAS_MAX = 1000  # máximo que acepta la API por consulta
SIN_NOMBRE = "(sin tarea)"

# Solo las llamadas al modelo (la vista observations también trae SPAN y EVENT).
FILTRO_GENERACIONES = {"column": "type", "operator": "=", "value": "GENERATION", "type": "string"}
# Sin el tráfico del modo prueba (tag "prueba", app/trazas.py).
FILTRO_SIN_PRUEBA = {"column": "tags", "operator": "none of", "value": ["prueba"], "type": "arrayOptions"}

_cache: dict = {}
_lock = threading.Lock()


class LangfuseNoDisponible(Exception):
    """Langfuse no respondió bien: el motivo se muestra en el portal (sin claves ni detalles internos)."""


def configurado() -> bool:
    return bool(config.LANGFUSE_PUBLIC_KEY and config.LANGFUSE_SECRET_KEY and config.LANGFUSE_HOST)


def _host() -> str:
    return config.LANGFUSE_HOST.rstrip("/")


def _get(path: str, params: Optional[dict] = None) -> dict:
    try:
        r = httpx.get(f"{_host()}{path}", params=params, auth=(config.LANGFUSE_PUBLIC_KEY, config.LANGFUSE_SECRET_KEY),
                      timeout=TIMEOUT_S)
    except httpx.TimeoutException as e:
        raise LangfuseNoDisponible("Langfuse tardó demasiado en responder") from e
    except httpx.HTTPError as e:
        raise LangfuseNoDisponible("No se pudo conectar con Langfuse") from e
    if r.status_code in (401, 403):
        raise LangfuseNoDisponible("Langfuse rechazó las claves (revisá LANGFUSE_PUBLIC_KEY y LANGFUSE_SECRET_KEY)")
    if r.status_code >= 400:
        raise LangfuseNoDisponible(f"Langfuse respondió con error {r.status_code}")
    try:
        return r.json()
    except ValueError as e:
        raise LangfuseNoDisponible("Langfuse devolvió una respuesta que no es JSON") from e


def _metricas(query: dict) -> list[dict]:
    datos = _get("/api/public/v2/metrics", {"query": json.dumps(query)}).get("data")
    if not isinstance(datos, list):
        raise LangfuseNoDisponible("Langfuse devolvió métricas en un formato inesperado")
    return [fila for fila in datos if isinstance(fila, dict)]


def _num(valor) -> float:
    """La API puede devolver números como texto (los conteos de ClickHouse) o null."""
    try:
        return float(valor or 0)
    except (TypeError, ValueError):
        return 0.0


def _iso(momento: dt.datetime) -> str:
    return momento.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _query(view: str, desde: dt.datetime, hasta: dt.datetime, metricas: list[tuple[str, str]],
           dimensiones: tuple[str, ...] = (), filtros: tuple[dict, ...] = (), por_dia: bool = False) -> dict:
    q = {
        "view": view,
        "dimensions": [{"field": d} for d in dimensiones],
        "metrics": [{"measure": m, "aggregation": a} for m, a in metricas],
        "filters": list(filtros),
        "fromTimestamp": _iso(desde),
        "toTimestamp": _iso(hasta),
        "config": {"row_limit": FILAS_MAX},
    }
    if por_dia:
        q["timeDimension"] = {"granularity": "day"}
    return q


def consultas(ahora: dt.datetime) -> dict[str, dict]:
    """Las consultas del tablero: últimos 7 días por tarea y por día, y el mes en curso para costo y unidades."""
    semana = ahora - dt.timedelta(days=DIAS)
    mes = ahora.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    raiz = {"column": "isRootObservation", "operator": "=", "value": True, "type": "boolean"}
    llamadas = (FILTRO_GENERACIONES, FILTRO_SIN_PRUEBA)
    return {
        "por_tarea": _query("observations", semana, ahora,
                            [("totalCost", "sum"), ("count", "count"), ("latency", "p50"), ("latency", "p95")],
                            ("name",), llamadas),
        "niveles": _query("observations", semana, ahora, [("count", "count")], ("name", "level"), llamadas),
        "por_dia": _query("observations", semana, ahora, [("totalCost", "sum")], ("name",), llamadas, por_dia=True),
        "scores": _query("scores-numeric", semana, ahora, [("value", "avg"), ("count", "count")], ("name",),
                         (FILTRO_SIN_PRUEBA,)),
        "mes": _query("observations", mes, ahora, [("totalCost", "sum"), ("count", "count")]),
        "mes_trazas": _query("observations", mes, ahora, [("count", "count")], filtros=(raiz,)),
        "mes_scores": _query("scores-numeric", mes, ahora, [("count", "count")]),
    }


def _tarea(fila: dict) -> str:
    return fila.get("name") or SIN_NOMBRE


def _tareas(por_tarea: list[dict], niveles: list[dict]) -> list[dict]:
    errores: dict[str, int] = {}
    for fila in niveles:
        if str(fila.get("level") or "").upper() == "ERROR":
            errores[_tarea(fila)] = errores.get(_tarea(fila), 0) + int(_num(fila.get("count_count")))
    tareas = [{
        "tarea": _tarea(f),
        "costo": round(_num(f.get("sum_totalCost")), 4),
        "llamadas": int(_num(f.get("count_count"))),
        "p50_ms": round(_num(f.get("p50_latency"))),
        "p95_ms": round(_num(f.get("p95_latency"))),
        "errores": errores.get(_tarea(f), 0),
    } for f in por_tarea]
    return sorted(tareas, key=lambda t: (-t["costo"], -t["llamadas"], t["tarea"]))


def _por_dia(filas: list[dict], ahora: dt.datetime) -> list[dict]:
    """Un renglón por cada uno de los últimos 7 días (UTC), también los que no tuvieron llamadas."""
    dias = [(ahora - dt.timedelta(days=i)).date().isoformat() for i in range(DIAS - 1, -1, -1)]
    por_tarea: dict[str, dict[str, float]] = {d: {} for d in dias}
    for fila in filas:
        dia = str(fila.get("time_dimension") or "")[:10]
        if dia not in por_tarea:
            continue
        tarea = _tarea(fila)
        por_tarea[dia] = {**por_tarea[dia], tarea: por_tarea[dia].get(tarea, 0.0) + _num(fila.get("sum_totalCost"))}
    return [{"dia": d, "costo": round(sum(por_tarea[d].values()), 4),
             "por_tarea": {t: round(c, 4) for t, c in por_tarea[d].items()}} for d in dias]


def _scores(filas: list[dict]) -> list[dict]:
    por_nombre = {f.get("name"): f for f in filas}
    return [{"nombre": n, "promedio": round(_num(por_nombre[n].get("avg_value")), 3),
             "cantidad": int(_num(por_nombre[n].get("count_count")))} for n in SCORES if n in por_nombre]


def _total(filas: list[dict], campo: str) -> float:
    return sum(_num(f.get(campo)) for f in filas)


def _mes(r: dict[str, list[dict]]) -> dict:
    """Las unidades del plan no salen de la API pública: se estiman como trazas + observaciones + scores del mes, con las
    trazas contadas como observaciones raíz. Es una cota superior (ver el docstring del módulo)."""
    observaciones = int(_total(r["mes"], "count_count"))
    trazas = int(_total(r["mes_trazas"], "count_count"))
    scores = int(_total(r["mes_scores"], "count_count"))
    return {
        "costo": round(_total(r["mes"], "sum_totalCost"), 4),
        "unidades": observaciones + trazas + scores,
        "limite_unidades": UNIDADES_PLAN,
        "unidades_estimadas": True,
        "unidades_cota_superior": True,
        "detalle": {"trazas": trazas, "observaciones": observaciones, "scores": scores},
    }


def _url_proyecto() -> str:
    """La URL del proyecto en Langfuse (sin claves). Si no se puede averiguar, la del host."""
    try:
        proyectos = _get("/api/public/projects").get("data") or []
        pid = proyectos[0].get("id") if proyectos and isinstance(proyectos[0], dict) else None
    except LangfuseNoDisponible:
        pid = None
    return f"{_host()}/project/{pid}" if pid else _host()


def armar(ahora: Optional[dt.datetime] = None) -> dict:
    """Consulta Langfuse (en paralelo) y arma el tablero. Levanta LangfuseNoDisponible si alguna consulta falla."""
    ahora = ahora or dt.datetime.now(dt.timezone.utc)
    qs = consultas(ahora)
    with ThreadPoolExecutor(max_workers=len(qs) + 1) as pool:
        url = pool.submit(_url_proyecto)
        futuros = {nombre: pool.submit(_metricas, q) for nombre, q in qs.items()}
        r = {nombre: f.result() for nombre, f in futuros.items()}
        url_proyecto = url.result()
    tareas = _tareas(r["por_tarea"], r["niveles"])
    return {
        "disponible": True,
        "actualizado": _iso(ahora),
        "dias": DIAS,
        "tareas": tareas,
        "costo_por_dia": _por_dia(r["por_dia"], ahora),
        "costo_semana": round(sum(t["costo"] for t in tareas), 4),
        "errores_semana": sum(t["errores"] for t in tareas),
        "scores": _scores(r["scores"]),
        "mes": _mes(r),
        "url": url_proyecto,
    }


def _no_disponible(motivo: str) -> dict:
    return {"disponible": False, "motivo": motivo, "url": _host() if config.LANGFUSE_HOST else None}


def tablero() -> dict:
    """El tablero con cache en memoria: 5 minutos si salió bien, 1 minuto si Langfuse falló."""
    if not configurado():
        return _no_disponible("Faltan las claves de Langfuse (LANGFUSE_PUBLIC_KEY y LANGFUSE_SECRET_KEY) en el servidor")
    with _lock:
        guardado = _cache.get("tablero")
        if guardado and time.monotonic() < guardado["vence"]:
            return guardado["valor"]
        try:
            valor, dura = armar(), CACHE_S
        except LangfuseNoDisponible as e:
            log.warning("Tablero de LLM: %s", e)
            valor, dura = _no_disponible(str(e)), CACHE_FALLA_S
        except Exception:  # un formato raro de Langfuse no puede romper el portal
            log.exception("Tablero de LLM: error inesperado armando las métricas")
            valor, dura = _no_disponible("Error inesperado leyendo las métricas de Langfuse"), CACHE_FALLA_S
        _cache["tablero"] = {"valor": valor, "vence": time.monotonic() + dura}
        return valor


def limpiar_cache() -> None:
    with _lock:
        _cache.clear()
