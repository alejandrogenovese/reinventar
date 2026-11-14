"""Revisión automática de eventos: cada EVENTOS_AUTO_HORAS, la app de producción mira las fuentes y actualiza
reinvent.evento sola (pensado para la semana de re:Invent, cuando nadie corre scripts).

Fuentes: el calendario Luma "aws-re-invent" (API pública), la tabla de conferenceparties.com (los que llevan a Luma se
completan con su página) y los links sueltos que cargó un admin (app/eventos_link.py).

Cada revisión:
1. Baja las fuentes. Una que falla no toca nada de lo suyo.
2. Compara con la base: nuevos y cambiados se completan con su página de Luma (una por segundo).
3. Resume con el LLM lo que no tiene resumen o cambió, hasta EVENTOS_AUTO_TOPE (lo que sobra, a la próxima).
4. Guarda todo en una transacción. Los nuevos llevan `alta` (dispara el push) salvo en la carga inicial de su fuente.
5. Cancelados: un evento futuro que no aparece queda con `falta_desde`; si sigue sin aparecer en otra revisión (al menos
   MIN_ENTRE_FALTAS después), pasa a `cancelado_desde`. Si una fuente falla o trae menos de la mitad de lo que traía,
   no se cancela nada. Si reaparece, se descancela.
6. Refresca la lista en memoria.
Solo con EVENTOS_AUTO=1 (producción): staging comparte el schema reinvent.
"""
import datetime as dt
import logging
import threading
import time
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass, replace

import httpx
from psycopg import sql
from psycopg.errors import UndefinedColumn, UndefinedTable
from psycopg.rows import tuple_row

from . import config, eventos_link, events, pg, sandbox
from .eventos_carga import fila, resumir_con_llm, sedes_con_coordenadas, upsert
from .eventos_fuentes import (
    Evento,
    completar_con_pagina_luma,
    desde_conferenceparties,
    desde_item_calendario,
    desde_pagina_luma,
    sede_por_texto,
    slug_luma,
)

log = logging.getLogger("reinventar.eventos_auto")

LUMA, CONFERENCEPARTIES, LINKS = "luma", "conferenceparties", "links"
FUENTE_DE_PLATAFORMA = {"luma": LUMA, "conferenceparties": CONFERENCEPARTIES, eventos_link.PLATAFORMA: LINKS}
CALENDARIO_LUMA = "cal-2tkJNe1XeR1VjMh"
URL_CALENDARIO = "https://api.lu.ma/calendar/get-items"
URL_CONFERENCEPARTIES = "https://conferenceparties.com/reinvent2026/"
POR_PAGINA, MAX_PAGINAS = 50, 10
SEGUNDOS_ENTRE_PEDIDOS = 1.0
MIN_PROPORCION = 0.5                        # una fuente que trae menos que esto de lo que traía no cancela nada
MIN_ENTRE_FALTAS = dt.timedelta(hours=1)    # dos faltas tienen que estar al menos así de separadas
ESPERA_INICIAL_S = 120                      # la primera revisión, 2 min después de arrancar
CANDADO = 20261129                          # pg_try_advisory_xact_lock: una revisión a la vez entre réplicas
TIMEOUT_S = 30
USER_AGENT = "ReinventAR/1.0 (agenda personal de re:Invent)"
_CAMPOS_FIRMA = {LUMA: ("nombre", "inicio", "fin", "imagen_url"),
                 CONFERENCEPARTIES: ("nombre", "inicio", "fin", "lugar", "direccion", "descripcion")}

Conectar = Callable[[], AbstractContextManager]


class FuenteRota(ValueError):
    """La fuente respondió algo que no se puede leer."""


@dataclass(frozen=True)
class Lectura:
    fuente: str
    eventos: tuple[Evento, ...] = ()
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


# ---------- fuentes ----------

def leer_luma(http: httpx.Client, pausa: Callable[[], None]) -> list[Evento]:
    eventos, cursor = [], None
    for _ in range(MAX_PAGINAS):
        params = {"calendar_api_id": CALENDARIO_LUMA, "period": "future", "pagination_limit": POR_PAGINA}
        r = http.get(URL_CALENDARIO, params={**params, "pagination_cursor": cursor} if cursor else params)
        r.raise_for_status()
        datos = r.json()
        eventos += [desde_item_calendario(e) for e in datos["entries"]]
        if not datos.get("has_more") or not datos.get("next_cursor"):
            break
        cursor = datos["next_cursor"]
        pausa()
    return eventos


def leer_conferenceparties(http: httpx.Client, _pausa: Callable[[], None]) -> list[Evento]:
    r = http.get(URL_CONFERENCEPARTIES)
    r.raise_for_status()
    eventos = desde_conferenceparties(r.text, URL_CONFERENCEPARTIES)
    if not eventos:
        raise FuenteRota("la tabla vino vacía")
    return eventos


def _leer(fuente: str, leer, http: httpx.Client, pausa) -> Lectura:
    try:
        return Lectura(fuente, tuple(leer(http, pausa)))
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as e:
        log.warning("fuente %s: %s", fuente, e)
        return Lectura(fuente, error=f"{type(e).__name__}: {str(e)[:200]}")


# ---------- estado en la base ----------

_COLUMNAS_ESTADO = ("id_evento", "plataforma", "url", "nombre", "inicio", "fin", "imagen_url", "lugar", "direccion",
                    "descripcion", "resumen_es", "falta_desde", "cancelado_desde")


def _usar_schema(cur, schema: str) -> None:
    cur.execute(sql.SQL("SET LOCAL search_path TO {}, public").format(sql.Identifier(schema)))


def _sedes_con_nombre(cur) -> list[tuple[int, str, float, float]]:
    return [(i, n, float(lat), float(lng)) for i, n, lat, lng in
            cur.execute("SELECT id_sede, nombre, lat, lng FROM sede WHERE lat IS NOT NULL").fetchall()]


def _leer_estado(conectar: Conectar, schema: str) -> tuple[dict, dict, list, list]:
    """(eventos por id, total de la última revisión OK por fuente, sedes con nombre, sedes con coordenadas)."""
    with conectar() as conn, conn.transaction():
        cur = conn.cursor(row_factory=tuple_row)
        _usar_schema(cur, schema)
        filas = cur.execute(sql.SQL("SELECT {} FROM evento").format(
            sql.SQL(", ").join(map(sql.Identifier, _COLUMNAS_ESTADO)))).fetchall()
        # La referencia sobrevive a una revisión fallida (guarda ok = false pero conserva el total de la última buena).
        revisiones = dict(cur.execute("SELECT fuente, total FROM evento_revision WHERE total > 0").fetchall())
        sedes = _sedes_con_nombre(cur)
        coordenadas = sedes_con_coordenadas(cur)
    return {f[0]: dict(zip(_COLUMNAS_ESTADO, f, strict=True)) for f in filas}, revisiones, sedes, coordenadas


# ---------- comparar ----------

def combinar(luma: Lectura, cp: Lectura, actuales: dict) -> dict[str, tuple[str, Evento]]:
    """{id: (fuente, evento)}. Un evento de conferenceparties con link a Luma que ya vino por el calendario (o ya está
    en la base) es el mismo: se usa el id que ya tiene."""
    combinados = {ev.id_evento: (LUMA, ev) for ev in luma.eventos}
    slugs = {slug_luma(ev.url) for ev in luma.eventos}
    por_slug = {slug_luma(a["url"]): i for i, a in actuales.items() if a["plataforma"] == "luma"}
    for ev in cp.eventos:
        slug = slug_luma(ev.url)
        if slug and slug in slugs:
            continue
        if slug and slug in por_slug:
            ev = replace(ev, id_evento=por_slug[slug])
        combinados.setdefault(ev.id_evento, (CONFERENCEPARTIES, ev))
    return combinados


def cambio(fuente: str, ev: Evento, actual: dict | None) -> bool:
    """Si hay que guardarlo: nuevo, o distinto en lo que trae su fuente. Un evento de Luma que vino por
    conferenceparties y ya está en la base no se compara (la tabla trae menos datos que la página)."""
    if actual is None:
        return True
    if fuente == CONFERENCEPARTIES and ev.plataforma == "luma":
        return False
    return any(getattr(ev, c) != actual[c] for c in _CAMPOS_FIRMA[fuente])


def completar(pendientes: list[tuple[str, Evento]], http: httpx.Client, pausa) -> list[tuple[str, Evento]]:
    """Los de Luma, con su página. Uno de conferenceparties que lleva a Luma se arma entero desde la página (con su id
    real); si la página falla, se deja para la próxima revisión."""
    completos = []
    for fuente, ev in pendientes:
        if ev.plataforma != "luma":
            completos.append((fuente, ev))
            continue
        try:
            r = http.get(ev.url)
            r.raise_for_status()
            html = r.text
        except httpx.HTTPError as e:
            log.info("sin página de Luma para %s: %s", ev.id_evento, e)
            html = None
        pausa()
        if fuente == LUMA:
            completos.append((fuente, completar_con_pagina_luma(ev, html) if html else ev))
        elif html and (desde_pagina := desde_pagina_luma(html)):
            completos.append((fuente, desde_pagina))
    return completos


def _evento_de_fila(a: dict) -> Evento:
    return Evento(id_evento=a["id_evento"], plataforma=a["plataforma"], url=a["url"], nombre=a["nombre"],
                  inicio=a["inicio"], lugar=a["lugar"], descripcion=a["descripcion"])


def para_resumir(guardar: list[tuple[str, Evento]], actuales: dict, tope: int) -> list[Evento]:
    """Primero lo nuevo o lo que cambió de nombre o descripción; después lo que quedó sin resumen de antes."""
    ids = {ev.id_evento for _f, ev in guardar}
    cambiados = [ev for _f, ev in guardar if not (a := actuales.get(ev.id_evento)) or not a["resumen_es"]
                 or (a["nombre"], a["descripcion"]) != (ev.nombre, ev.descripcion)]
    atrasados = [_evento_de_fila(a) for i, a in actuales.items()
                 if i not in ids and not a["resumen_es"] and not a["cancelado_desde"]]
    return (cambiados + atrasados)[:max(tope, 0)]


# ---------- cancelados ----------

def _marcar(cur, id_evento: str, *, falta, cancelado) -> None:
    cur.execute("UPDATE evento SET falta_desde = %s, cancelado_desde = %s, actualizado = now() WHERE id_evento = %s",
                (falta, cancelado, id_evento))


def aplicar_faltas(cur, actuales: dict, vistos: set[str], faltan: set[str], ahora: dt.datetime) -> list[str]:
    """vistos: aparecieron (se descancelan); faltan: no aparecieron en una fuente que anduvo bien. Devuelve los ids
    que se cancelaron en esta revisión."""
    cancelados = []
    for i in vistos & actuales.keys():
        if actuales[i]["falta_desde"] or actuales[i]["cancelado_desde"]:
            _marcar(cur, i, falta=None, cancelado=None)
    for i in faltan - vistos:
        a = actuales[i]
        if a["cancelado_desde"] or a["inicio"] <= ahora:
            continue
        if a["falta_desde"] is None:
            _marcar(cur, i, falta=ahora, cancelado=None)
        elif ahora - a["falta_desde"] >= MIN_ENTRE_FALTAS:
            _marcar(cur, i, falta=a["falta_desde"], cancelado=ahora)
            cancelados.append(i)
    return cancelados


def revisar_links(actuales: dict, http: httpx.Client, resolver, ahora: dt.datetime, pausa) -> tuple[set, set]:
    """(vistos, faltan) de los eventos cargados por link: 404/410 cuenta como falta; un error de red, como nada."""
    vistos, faltan = set(), set()
    for i, a in actuales.items():
        if a["plataforma"] != eventos_link.PLATAFORMA or a["inicio"] <= ahora:
            continue
        try:
            status = eventos_link.bajar(a["url"], http, resolver).status
        except eventos_link.LinkInvalido:
            continue
        except Exception:  # noqa: BLE001 — un link raro no frena la revisión de los demás ni de las fuentes
            log.warning("no pude revisar el link de %s", i, exc_info=True)
            continue
        finally:
            pausa()
        if status in (404, 410):
            faltan.add(i)
        elif status < 400:
            vistos.add(i)
    return vistos, faltan


# ---------- revisión ----------

def futuros(lectura: Lectura, ahora: dt.datetime) -> int:
    """Cuántos eventos que todavía no empezaron trajo la fuente: es lo que se compara entre revisiones (los que ya
    pasaron salen solos del calendario durante la semana y no son una falla)."""
    return sum(ev.inicio > ahora for ev in lectura.eventos)


def _reducida(lectura: Lectura, previas: dict, ahora: dt.datetime) -> bool:
    previo = previas.get(lectura.fuente)
    return bool(previo) and futuros(lectura, ahora) < MIN_PROPORCION * previo


def _guardar_revision(cur, fuente: str, ahora, lectura_ok: bool, conteo: dict, detalle: str | None) -> None:
    if lectura_ok:
        cur.execute("""
          INSERT INTO evento_revision (fuente, revisado, ok, total, nuevos, cambiados, cancelados, pendientes, detalle)
          VALUES (%(fuente)s, %(ahora)s, true, %(total)s, %(nuevos)s, %(cambiados)s, %(cancelados)s, %(pendientes)s,
                  %(detalle)s)
          ON CONFLICT (fuente) DO UPDATE SET revisado = EXCLUDED.revisado, ok = true, total = EXCLUDED.total,
            nuevos = EXCLUDED.nuevos, cambiados = EXCLUDED.cambiados, cancelados = EXCLUDED.cancelados,
            pendientes = EXCLUDED.pendientes, detalle = EXCLUDED.detalle""",
                    {"fuente": fuente, "ahora": ahora, "detalle": detalle, **conteo})
    else:  # se conserva el total de la última vez que anduvo (sirve para detectar una fuente "a la mitad")
        cur.execute("""
          INSERT INTO evento_revision (fuente, revisado, ok, detalle) VALUES (%s, %s, false, %s)
          ON CONFLICT (fuente) DO UPDATE SET revisado = EXCLUDED.revisado, ok = false, detalle = EXCLUDED.detalle""",
                    (fuente, ahora, detalle))


def _pendientes_por_fuente(cur) -> dict[str, int]:
    filas = cur.execute("SELECT plataforma, count(*) FROM evento WHERE resumen_es IS NULL AND cancelado_desde IS NULL "
                        "GROUP BY plataforma").fetchall()
    cuenta: dict[str, int] = {}
    for plataforma, n in filas:
        fuente = FUENTE_DE_PLATAFORMA.get(plataforma)
        if fuente:
            cuenta[fuente] = cuenta.get(fuente, 0) + n
    return cuenta


def revisar(*, conectar: Conectar | None = None, http: httpx.Client | None = None, schema: str = "reinvent",
            resumir=None, tope: int | None = None, ahora: dt.datetime | None = None,
            pausa: Callable[[], None] | None = None, resolver=None) -> dict:
    """Una revisión completa. Devuelve el resumen por fuente (lo que se guarda en evento_revision)."""
    conectar = conectar or (lambda: pg.pool().connection())
    ahora = ahora or dt.datetime.now(dt.UTC)
    pausa = pausa or (lambda: time.sleep(SEGUNDOS_ENTRE_PEDIDOS))
    resumir = resumir or resumir_con_llm
    tope = config.EVENTOS_AUTO_TOPE if tope is None else tope
    cliente = http or httpx.Client(timeout=TIMEOUT_S, follow_redirects=True, headers={"User-Agent": USER_AGENT})
    try:
        return _revisar(conectar, cliente, schema, resumir, tope, ahora, pausa,
                        resolver or eventos_link.resolver_dns)
    finally:
        if http is None:
            cliente.close()


def _revisar(conectar, http, schema, resumir, tope, ahora, pausa, resolver) -> dict:
    actuales, previas, sedes, coordenadas = _leer_estado(conectar, schema)
    luma = _leer(LUMA, leer_luma, http, pausa)
    cp = _leer(CONFERENCEPARTIES, leer_conferenceparties, http, pausa)
    combinados = combinar(luma, cp, actuales)
    guardar = completar([(f, ev) for f, ev in combinados.values() if cambio(f, ev, actuales.get(ev.id_evento))],
                        http, pausa)
    guardar = [(f, sede_por_texto(ev, sedes)) for f, ev in guardar]
    a_resumir = para_resumir(guardar, actuales, tope)
    resumenes, fallidos = resumir(a_resumir) if a_resumir else ({}, ())
    links_vistos, links_faltan = revisar_links(actuales, http, resolver, ahora, pausa)

    reducidas = {lec.fuente for lec in (luma, cp) if _reducida(lec, previas, ahora)}
    lecturas_ok = luma.ok and cp.ok and not reducidas
    vistos = set(combinados) | {ev.id_evento for _f, ev in guardar} | links_vistos
    de_fuentes = {i for i, a in actuales.items() if a["plataforma"] in ("luma", "conferenceparties")}
    faltan = (de_fuentes if lecturas_ok else set()) | links_faltan

    with conectar() as conn, conn.transaction():
        cur = conn.cursor(row_factory=tuple_row)
        _usar_schema(cur, schema)
        if not cur.execute("SELECT pg_try_advisory_xact_lock(%s)", (CANDADO,)).fetchone()[0]:
            return {"estado": "ocupado"}
        conteo = {f: {"total": 0, "nuevos": 0, "cambiados": 0, "cancelados": 0, "pendientes": 0}
                  for f in (LUMA, CONFERENCEPARTIES, LINKS)}
        for lectura in (luma, cp):  # una fuente "a la mitad" no se vuelve la nueva referencia: queda la anterior
            conteo[lectura.fuente]["total"] = previas[lectura.fuente] if lectura.fuente in reducidas \
                else futuros(lectura, ahora)
        conteo[LINKS]["total"] = sum(a["plataforma"] == eventos_link.PLATAFORMA for a in actuales.values())
        for fuente, ev in guardar:
            previo = actuales.get(ev.id_evento) or {}
            res = resumenes.get(ev.id_evento) or {k: previo.get(k) for k in ("resumen_es", "tipo", "temas",
                                                                               "organizadores")}
            resultado = upsert(cur, fila(ev, res, coordenadas))
            if resultado == "nuevo":
                conteo[fuente]["nuevos"] += 1
                if fuente in previas:  # la carga inicial de una fuente no dispara el push de "eventos nuevos"
                    cur.execute("UPDATE evento SET alta = %s WHERE id_evento = %s", (ahora, ev.id_evento))
            elif resultado == "actualizado":
                conteo[fuente]["cambiados"] += 1
        guardados = {ev.id_evento for _f, ev in guardar}
        for i, res in resumenes.items():
            if i not in guardados:
                cur.execute("UPDATE evento SET resumen_es = %s, tipo = %s, temas = %s, organizadores = %s, "
                            "actualizado = now() WHERE id_evento = %s",
                            (res["resumen_es"], res["tipo"], list(res["temas"]), list(res["organizadores"]), i))
        for i in aplicar_faltas(cur, actuales, vistos, faltan, ahora):
            conteo[FUENTE_DE_PLATAFORMA.get(actuales[i]["plataforma"], LUMA)]["cancelados"] += 1
        for fuente, n in _pendientes_por_fuente(cur).items():
            conteo[fuente]["pendientes"] = n
        aviso = None if lecturas_ok else "no se canceló nada: una fuente falló o vino a la mitad"
        lote = f"{len(fallidos)} lotes del LLM fallaron" if fallidos else None
        for lectura in (luma, cp):
            detalle = lectura.error or "; ".join(filter(None, (aviso, lote))) or None
            _guardar_revision(cur, lectura.fuente, ahora, lectura.ok, conteo[lectura.fuente], detalle)
        _guardar_revision(cur, LINKS, ahora, True, conteo[LINKS], None)
    log.info("eventos: %s", {f: c for f, c in conteo.items() if any(c.values())})
    return {"estado": "ok", "fuentes": conteo, "errores": {lec.fuente: lec.error for lec in (luma, cp) if lec.error}}


# ---------- en segundo plano ----------

_en_curso = threading.Lock()


def ocupado() -> bool:
    return _en_curso.locked()


def revisar_ahora(**kw) -> dict:
    """Una revisión con el reloj y la base reales (aunque la pida un admin en modo prueba), y refresca la lista."""
    if not _en_curso.acquire(blocking=False):
        return {"estado": "ocupado"}
    try:
        with sandbox.real():
            resultado = revisar(**kw)
            events.load()
        return resultado
    finally:
        _en_curso.release()


def en_segundo_plano() -> bool:
    """Arranca una revisión sin esperarla (botón del admin). False si ya hay una en curso."""
    if ocupado():
        return False
    threading.Thread(target=_una_vuelta, name="eventos-auto-ya", daemon=True).start()
    return True


def _una_vuelta() -> None:
    try:
        revisar_ahora()
    except Exception:  # noqa: BLE001 — un error de una revisión no corta las siguientes
        log.exception("revisión de eventos falló")


def _loop() -> None:
    time.sleep(ESPERA_INICIAL_S)
    while True:
        _una_vuelta()
        time.sleep(config.EVENTOS_AUTO_HORAS * 3600)


def start_worker() -> None:
    if config.EVENTOS_AUTO:
        threading.Thread(target=_loop, name="eventos-auto", daemon=True).start()
    else:
        log.info("Eventos automáticos apagados (EVENTOS_AUTO no es 1)")


# ---------- admin ----------

def estado(conectar: Conectar | None = None, schema: str = "reinvent") -> dict:
    """Lo que muestra el admin: si está prendido, si hay una revisión en curso, la última de cada fuente y los
    eventos cargados por link. migracion_pendiente: la base todavía no tiene la migración 007."""
    conectar = conectar or (lambda: pg.pool().connection())
    base = {"activo": config.EVENTOS_AUTO, "horas": config.EVENTOS_AUTO_HORAS, "ocupado": ocupado()}
    try:
        with conectar() as conn, conn.transaction():
            cur = conn.cursor(row_factory=tuple_row)
            _usar_schema(cur, schema)
            columnas = ("fuente", "revisado", "ok", "total", "nuevos", "cambiados", "cancelados", "pendientes",
                        "detalle")
            revisiones = [dict(zip(columnas, f, strict=True)) for f in cur.execute(
                "SELECT fuente, revisado, ok, total, nuevos, cambiados, cancelados, pendientes, detalle "
                "FROM evento_revision ORDER BY fuente").fetchall()]
            links = [{"id": i, "nombre": n, "url": u, "inicio": ini, "cancelado": c is not None}
                     for i, n, u, ini, c in cur.execute(
                         "SELECT id_evento, nombre, url, inicio, cancelado_desde FROM evento WHERE plataforma = %s "
                         "ORDER BY inicio", (eventos_link.PLATAFORMA,)).fetchall()]
    except (UndefinedTable, UndefinedColumn):
        return {**base, "migracion_pendiente": True, "revisiones": [], "links": []}
    return {**base, "migracion_pendiente": False, "revisiones": revisiones, "links": links}


class LinkRepetido(ValueError):
    """Ese link ya está cargado (por Luma, conferenceparties o a mano)."""


def ya_cargado(url: str, conectar: Conectar | None = None, schema: str = "reinvent") -> str | None:
    """El nombre del evento que ya tiene ese link (o el mismo evento de Luma), o None."""
    conectar = conectar or (lambda: pg.pool().connection())
    slug = slug_luma(url)
    with conectar() as conn, conn.transaction():
        cur = conn.cursor(row_factory=tuple_row)
        _usar_schema(cur, schema)
        filas = cur.execute("SELECT nombre, url FROM evento").fetchall()
    return next((n for n, u in filas if u == url or (slug and slug_luma(u) == slug)), None)


def guardar_link(datos: dict, *, resumen: dict, conectar: Conectar | None = None, schema: str = "reinvent",
                 ahora: dt.datetime | None = None) -> str:
    """Guarda un evento cargado por link (con alta: dispara el push de "eventos nuevos"). Devuelve su id."""
    conectar = conectar or (lambda: pg.pool().connection())
    if nombre := ya_cargado(datos["url"], conectar, schema):
        raise LinkRepetido(f"Ya está cargado: {nombre}")
    ev = eventos_link.evento(datos)
    with conectar() as conn, conn.transaction():
        cur = conn.cursor(row_factory=tuple_row)
        _usar_schema(cur, schema)
        ev = sede_por_texto(ev, _sedes_con_nombre(cur))
        upsert(cur, fila(ev, resumen, sedes_con_coordenadas(cur)))
        cur.execute("UPDATE evento SET alta = %s WHERE id_evento = %s", (ahora or dt.datetime.now(dt.UTC), ev.id_evento))
    return ev.id_evento
