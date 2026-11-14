"""Charlas que se bajan o cambian: la app de producción compara reinvent.speech_horario con el buscador público del
catálogo oficial (catalog.awsevents.com/api/search, sin login: no toca la cuenta de nadie). Es la fuente "catalogo" de
la revisión automática (app/eventos_auto.py) y sigue sus mismas reglas.

Cada revisión:
1. Baja el buscador entero (de a 50, uno por segundo). Si falla o viene incompleto, no toca nada.
2. Cruza cada horario oficial con la base: primero por sessionTimeID (aws_time_id), después por código.
   - Mismo sessionTimeID con otro código: AWS lo renombró. Se cambia el código (queda en codigo_renombrado) y, después
     de confirmar, los itinerarios y grabaciones pasan al código nuevo (db.renombrar_codigos).
   - Cambió la fecha, la hora, la sede o la sala: se actualiza. Nada más: títulos, resúmenes traducidos, claves y
     speakers siguen viniendo de la carga manual (scripts/actualizar_catalogo.py).
   - Horario que no está en la base: se inserta. Si la charla tampoco está, entra con lo que trae el oficial (resumen
     en inglés) y con `alta`: es una de las «Charlas nuevas» del admin.
3. Bajas: un horario futuro que no aparece queda con `falta_desde` (la charla muestra un aviso); si sigue sin aparecer
   en otra revisión (al menos MIN_ENTRE_FALTAS después), pasa a `cancelado_desde` («Cancelada» y push a quien la tiene).
   Si el buscador trae menos de la mitad de los horarios futuros de la última revisión OK, no se cancela nada (y ese
   total no se vuelve la referencia). Si reaparece, se limpia.
4. Recarga el catálogo en memoria: los cambios de sala u horario los avisa app/changes.py contra la foto del itinerario.
Cada 3 h en noviembre y cada 30 min durante la semana del evento. Solo con EVENTOS_AUTO=1 (producción).
"""
import datetime as dt
import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field

import httpx
from psycopg.errors import UndefinedColumn, UndefinedTable
from psycopg.rows import tuple_row

from . import catalog, config, db, pg, sandbox
from .catalogo_oficial import BuscadorRoto, Charla, Horario, bajar_buscador, leer_buscador
from .eventos_auto import (
    MIN_ENTRE_FALTAS,
    MIN_PROPORCION,
    TIMEOUT_S,
    USER_AGENT,
    Conectar,
    _guardar_revision,
    _usar_schema,
)

log = logging.getLogger("reinventar.charlas_auto")

FUENTE = "catalogo"
CANDADO = 20261130                          # pg_try_advisory_xact_lock propio: corre en paralelo con la de eventos
SEGUNDOS_ENTRE_PEDIDOS = 1.0
ESPERA_INICIAL_S = 300                      # la primera, 5 min después de arrancar (después de la de eventos)
CADA_EN_NOVIEMBRE = dt.timedelta(hours=3)
CADA_EN_EL_EVENTO = dt.timedelta(minutes=30)
SEMANA_DEL_EVENTO = (dt.date(2026, 11, 29), dt.date(2026, 12, 4))   # hora de Las Vegas
MAX_NUEVAS_EN_ADMIN = 100

_COLUMNAS = ("codigo", "id_speech", "fecha", "hora_inicio", "hora_fin", "id_sede", "sala", "aws_time_id",
             "falta_desde", "cancelado_desde")


class MigracionPendiente(RuntimeError):
    """La base todavía no tiene la migración 008 (speech_horario.falta_desde y compañía)."""


def intervalo(ahora: dt.datetime) -> dt.timedelta:
    desde, hasta = SEMANA_DEL_EVENTO
    return CADA_EN_EL_EVENTO if desde <= ahora.astimezone(sandbox.EVENT_TZ).date() <= hasta else CADA_EN_NOVIEMBRE


def empieza(fecha: dt.date, hora: dt.time) -> dt.datetime:
    return dt.datetime.combine(fecha, hora, tzinfo=sandbox.EVENT_TZ)


# ---------- estado en la base ----------

@dataclass(frozen=True)
class Estado:
    horarios: dict[str, dict]                         # por código
    charlas: set[str]                                 # id_speech que ya están
    alias: dict[str, tuple[int, str | None]]          # texto de AWS → (id_sede, lugar dentro de la sede)
    referencia: int | None                            # horarios futuros de la última revisión OK


def _leer_estado(conectar: Conectar, schema: str) -> Estado:
    try:
        with conectar() as conn, conn.transaction():
            cur = conn.cursor(row_factory=tuple_row)
            _usar_schema(cur, schema)
            filas = cur.execute(f"SELECT {', '.join(_COLUMNAS)} FROM speech_horario").fetchall()
            charlas = {r[0] for r in cur.execute("SELECT id_speech FROM speech").fetchall()}
            alias = {a: (i, lugar) for a, i, lugar in cur.execute("SELECT alias, id_sede, lugar FROM sede_alias")}
            # El total se conserva aunque la última haya fallado: es el de la última revisión OK.
            ref = cur.execute("SELECT total FROM evento_revision WHERE fuente = %s", (FUENTE,)).fetchone()
            cur.execute("SELECT alta FROM speech LIMIT 0")
    except (UndefinedColumn, UndefinedTable) as e:
        raise MigracionPendiente(str(e)) from e
    return Estado({f[0]: dict(zip(_COLUMNAS, f, strict=True)) for f in filas}, charlas, alias,
                  (ref[0] or None) if ref else None)


# ---------- comparar ----------

@dataclass
class Plan:
    renombres: list[tuple[str, str, str]] = field(default_factory=list)     # (viejo, nuevo, id_speech nuevo)
    cambios: list[tuple[str, Horario, int, str | None]] = field(default_factory=list)  # (código, oficial, sede, sala)
    nuevos: list[tuple[Horario, int, str | None]] = field(default_factory=list)
    vistos: set[str] = field(default_factory=set)       # códigos de la base (ya renombrados) que aparecieron
    sin_sede: set[str] = field(default_factory=set)     # sedes que AWS escribe distinto y no están en sede_alias
    en_conflicto: list[tuple[str, str]] = field(default_factory=list)


def _sede(h: Horario, alias: dict) -> tuple[int, str | None] | None:
    if h.sede not in alias:
        return None
    id_sede, lugar = alias[h.sede]
    return id_sede, h.sala or lugar


def _renombres_aplicables(pares: list[tuple[str, Horario]], ocupados: set[str]) -> list[tuple[str, Horario]]:
    """Un renombre se aplica si el código nuevo está libre o lo libera otro renombre aplicable (cadenas e
    intercambios). Igual que scripts/actualizar_catalogo.py."""
    aplicables = list(pares)
    while True:
        salen = {viejo for viejo, _ in aplicables}
        siguen = [p for p in aplicables if p[1].codigo not in ocupados or p[1].codigo in salen]
        if len(siguen) == len(aplicables):
            return aplicables
        aplicables = siguen


def _emparejar(oficiales: list[Horario], horarios: dict[str, dict]) -> tuple[list[tuple[str, Horario]], list[Horario]]:
    """([(código en la base, oficial)], oficiales sin pareja): primero por sessionTimeID, después por código."""
    por_time = {a["aws_time_id"]: c for c, a in horarios.items() if a["aws_time_id"]}
    usados: set[str] = set()
    pares, sueltos = [], []
    for h in oficiales:
        c = por_time.get(h.aws_time_id)
        if c is not None and c not in usados:
            usados.add(c)
            pares.append((c, h))
        else:
            sueltos.append(h)
    sin_pareja = []
    for h in sueltos:
        if h.codigo in horarios and h.codigo not in usados:
            usados.add(h.codigo)
            pares.append((h.codigo, h))
        else:
            sin_pareja.append(h)
    return pares, sin_pareja


def planear(oficiales: list[Horario], estado: Estado) -> Plan:
    plan = Plan()
    pares, sin_pareja = _emparejar(oficiales, estado.horarios)
    candidatos = [(c, h) for c, h in pares if c != h.codigo]
    aplicables = _renombres_aplicables(candidatos, set(estado.horarios))
    plan.en_conflicto = [(c, h.codigo) for c, h in candidatos if (c, h) not in aplicables]
    plan.renombres = [(c, h.codigo, h.id_speech) for c, h in aplicables]
    renombrado = {c: h.codigo for c, h in aplicables}

    for c, h in pares:
        if c != h.codigo and c not in renombrado:  # renombre en conflicto: queda como está, pero apareció
            plan.vistos.add(c)
            continue
        final = renombrado.get(c, c)
        plan.vistos.add(final)
        lugar = _sede(h, estado.alias)
        if lugar is None:
            plan.sin_sede.add(h.sede)
            continue
        a = estado.horarios[c]
        if (a["fecha"], a["hora_inicio"], a["hora_fin"], a["id_sede"], a["sala"]) != (h.fecha, h.hora_inicio,
                                                                                     h.hora_fin, *lugar):
            plan.cambios.append((final, h, *lugar))

    ocupados = (set(estado.horarios) - set(renombrado)) | set(renombrado.values())
    for h in sin_pareja:
        if h.codigo in ocupados:  # el mismo código con dos horarios (pasa): se queda el que ya está
            continue
        lugar = _sede(h, estado.alias)
        if lugar is None:
            plan.sin_sede.add(h.sede)
            continue
        ocupados.add(h.codigo)
        plan.nuevos.append((h, *lugar))
    return plan


# ---------- guardar ----------

_INSERTAR_CHARLA = """
INSERT INTO speech (id_speech, titulo, tipo, nivel, topicos, servicios, area_interes, formato, roles, industria,
                    es_lanzamiento, es_sponsoreada, speakers_ocultos, duracion_min, resumen, speakers_original,
                    modificado, alta)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT DO NOTHING"""

_INSERTAR_HORARIO = """
INSERT INTO speech_horario (codigo, id_speech, fecha, hora_inicio, hora_fin, id_sede, sala, cupo, walk_up,
                            aws_session_id, aws_time_id)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT DO NOTHING"""


def _insertar_charla(cur, c: Charla, alta: dt.datetime | None) -> None:
    cur.execute(_INSERTAR_CHARLA, (c.id_speech, c.titulo, c.tipo, c.nivel, list(c.topicos), list(c.servicios),
                                   c.area_interes, c.formato, list(c.roles), list(c.industria), c.es_lanzamiento,
                                   c.es_sponsoreada, c.speakers_ocultos, c.duracion_min, c.resumen,
                                   c.speakers_original, c.modificado, alta))


def _asegurar_charla(cur, id_speech: str, estado: Estado, charlas: dict[str, Charla], alta) -> bool:
    """Que la charla exista antes de colgarle un horario. alta: la marca de «charla nueva» (None para un renombre)."""
    if id_speech in estado.charlas:
        return True
    if id_speech not in charlas:
        return False
    _insertar_charla(cur, charlas[id_speech], alta)
    estado.charlas.add(id_speech)
    return True


def _renombrar(cur, plan: Plan, estado: Estado, charlas: dict[str, Charla]) -> list[tuple[str, str, str]]:
    hechos = [r for r in plan.renombres if _asegurar_charla(cur, r[2], estado, charlas, None)]
    # Dos pasos (pasando por un código temporal) para que cadenas e intercambios no choquen con la PK.
    cur.executemany("UPDATE speech_horario SET codigo = '~' || codigo WHERE codigo = %s", [(v,) for v, _n, _b in hechos])
    cur.executemany("UPDATE speech_horario SET codigo = %s, id_speech = %s WHERE codigo = '~' || %s",
                    [(n, b, v) for v, n, b in hechos])
    cur.executemany("""
      INSERT INTO codigo_renombrado (codigo_viejo, codigo_nuevo, aws_time_id)
      SELECT %s, %s, aws_time_id FROM speech_horario WHERE codigo = %s AND aws_time_id IS NOT NULL
      ON CONFLICT (codigo_viejo) DO UPDATE SET codigo_nuevo = EXCLUDED.codigo_nuevo, detectado = now()""",
                    [(v, n, n) for v, n, _b in hechos])
    return hechos


def _nuevos(cur, plan: Plan, estado: Estado, charlas: dict[str, Charla], ahora) -> int:
    n = 0
    for h, id_sede, sala in plan.nuevos:
        if not _asegurar_charla(cur, h.id_speech, estado, charlas, ahora):
            continue
        n += cur.execute(_INSERTAR_HORARIO, (h.codigo, h.id_speech, h.fecha, h.hora_inicio, h.hora_fin, id_sede, sala,
                                             h.cupo, h.walk_up, h.aws_session_id, h.aws_time_id)).rowcount
    return n


def _marcar(cur, codigo: str, *, falta, cancelado) -> None:
    cur.execute("UPDATE speech_horario SET falta_desde = %s, cancelado_desde = %s WHERE codigo = %s",
                (falta, cancelado, codigo))


def aplicar_faltas(cur, horarios: dict[str, dict], vistos: set[str], faltan: set[str], ahora: dt.datetime) -> list[str]:
    """Como eventos_auto.aplicar_faltas, por horario. horarios: por código, ya con los códigos renombrados."""
    cancelados = []
    for c in vistos & horarios.keys():
        if horarios[c]["falta_desde"] or horarios[c]["cancelado_desde"]:
            _marcar(cur, c, falta=None, cancelado=None)
    for c in faltan - vistos:
        a = horarios[c]
        if a["cancelado_desde"] or empieza(a["fecha"], a["hora_inicio"]) <= ahora:
            continue
        if a["falta_desde"] is None:
            _marcar(cur, c, falta=ahora, cancelado=None)
        elif ahora - a["falta_desde"] >= MIN_ENTRE_FALTAS:
            _marcar(cur, c, falta=a["falta_desde"], cancelado=ahora)
            cancelados.append(c)
    return cancelados


def _con_renombres(horarios: dict[str, dict], renombres: list[tuple[str, str, str]]) -> dict[str, dict]:
    nuevos_codigos = {v: n for v, n, _b in renombres}
    return {nuevos_codigos.get(c, c): a for c, a in horarios.items()}


def _detalle(plan: Plan, reducida: bool, en_duda: int) -> str | None:
    partes = [
        "no se canceló nada: el catálogo vino a la mitad" if reducida else None,
        f"{en_duda} horarios no aparecieron (se cancelan si siguen sin aparecer)" if en_duda else None,
        f"sedes sin mapear en sede_alias: {', '.join(sorted(plan.sin_sede))}" if plan.sin_sede else None,
        "renombres en conflicto: " + ", ".join(f"{v} → {n}" for v, n in plan.en_conflicto) if plan.en_conflicto else None,
    ]
    return "; ".join(filter(None, partes)) or None


# ---------- revisión ----------

def revisar(*, conectar: Conectar | None = None, http: httpx.Client | None = None, schema: str = "reinvent",
            ahora: dt.datetime | None = None, pausa: Callable[[], None] | None = None) -> dict:
    """Una revisión completa. Devuelve el resumen (lo que se guarda en evento_revision) y los renombres aplicados."""
    conectar = conectar or (lambda: pg.pool().connection())
    ahora = ahora or dt.datetime.now(dt.UTC)
    pausa = pausa or (lambda: time.sleep(SEGUNDOS_ENTRE_PEDIDOS))
    cliente = http or httpx.Client(timeout=TIMEOUT_S, follow_redirects=True, headers={"User-Agent": USER_AGENT})
    try:
        estado = _leer_estado(conectar, schema)
        try:
            oficiales, charlas = leer_buscador(bajar_buscador(cliente, pausa))
            error = None
        except (httpx.HTTPError, BuscadorRoto, ValueError, KeyError, TypeError) as e:
            log.warning("catálogo oficial: %s", e)
            oficiales, charlas, error = [], {}, f"{type(e).__name__}: {str(e)[:200]}"
    finally:
        if http is None:
            cliente.close()
    return _guardar(conectar, schema, estado, oficiales, charlas, error, ahora)


def _guardar(conectar, schema, estado: Estado, oficiales, charlas, error, ahora) -> dict:
    futuros = sum(empieza(h.fecha, h.hora_inicio) > ahora for h in oficiales)
    reducida = error is None and bool(estado.referencia) and futuros < MIN_PROPORCION * estado.referencia
    plan = planear(oficiales, estado) if error is None else Plan()
    with conectar() as conn, conn.transaction():
        cur = conn.cursor(row_factory=tuple_row)
        _usar_schema(cur, schema)
        if not cur.execute("SELECT pg_try_advisory_xact_lock(%s)", (CANDADO,)).fetchone()[0]:
            return {"estado": "ocupado"}
        if error:
            _guardar_revision(cur, FUENTE, ahora, False, {}, error)
            return {"estado": "ok", "error": error, "renombres": []}
        renombres = _renombrar(cur, plan, estado, charlas)
        for codigo, h, id_sede, sala in plan.cambios:
            cur.execute("UPDATE speech_horario SET fecha = %s, hora_inicio = %s, hora_fin = %s, id_sede = %s, sala = %s "
                        "WHERE codigo = %s", (h.fecha, h.hora_inicio, h.hora_fin, id_sede, sala, codigo))
        nuevos = _nuevos(cur, plan, estado, charlas, ahora)
        horarios = _con_renombres(estado.horarios, renombres)
        faltan = set() if reducida else set(horarios)
        cancelados = aplicar_faltas(cur, horarios, plan.vistos, faltan, ahora)
        en_duda = cur.execute("SELECT count(*) FROM speech_horario WHERE falta_desde IS NOT NULL "
                              "AND cancelado_desde IS NULL").fetchone()[0]
        conteo = {"total": estado.referencia if reducida else futuros, "nuevos": nuevos,
                  "cambiados": len(plan.cambios) + len(renombres), "cancelados": len(cancelados), "pendientes": 0}
        _guardar_revision(cur, FUENTE, ahora, True, conteo, _detalle(plan, reducida, en_duda))
    log.info("catálogo oficial: %s, %d renombres", conteo, len(renombres))
    return {"estado": "ok", "error": None, "conteo": conteo, "cancelados": cancelados,
            "renombres": [(v, n) for v, n, _b in renombres], "renombres_base": renombres}


# ---------- en segundo plano ----------

_en_curso = threading.Lock()


def ocupado() -> bool:
    return _en_curso.locked()


def revisar_ahora(**kw) -> dict:
    """Una revisión con el reloj y la base reales: pasa los itinerarios a los códigos renombrados y recarga el
    catálogo en memoria (con eso app/changes.py avisa los cambios de sala u horario)."""
    if not _en_curso.acquire(blocking=False):
        return {"estado": "ocupado"}
    try:
        with sandbox.real():
            resultado = revisar(**kw)
            if resultado.get("renombres_base"):
                db.renombrar_codigos(resultado["renombres_base"])
            if resultado.get("estado") == "ok" and not resultado.get("error"):
                catalog.load()
        return resultado
    finally:
        _en_curso.release()


def en_segundo_plano() -> bool:
    """Arranca una revisión sin esperarla (botón del admin). False si ya hay una en curso."""
    if ocupado():
        return False
    threading.Thread(target=_una_vuelta, name="charlas-auto-ya", daemon=True).start()
    return True


def _una_vuelta() -> None:
    try:
        revisar_ahora()
    except MigracionPendiente:
        log.warning("revisión de charlas: falta la migración 008 en la base")
    except Exception:  # noqa: BLE001 — un error de una revisión no corta las siguientes
        log.exception("revisión de charlas falló")


def _loop() -> None:
    time.sleep(ESPERA_INICIAL_S)
    while True:
        _una_vuelta()
        time.sleep(intervalo(dt.datetime.now(dt.UTC)).total_seconds())


def start_worker() -> None:
    if config.EVENTOS_AUTO:
        threading.Thread(target=_loop, name="charlas-auto", daemon=True).start()
    else:
        log.info("Revisión de charlas apagada (EVENTOS_AUTO no es 1)")


# ---------- admin ----------

def nuevas(conectar: Conectar | None = None, schema: str = "reinvent") -> list[dict]:
    """Las «Charlas nuevas» que encontró la revisión (para que el admin las revise), de la más reciente a la más vieja.
    Sin la migración 008, ninguna."""
    conectar = conectar or (lambda: pg.pool().connection())
    try:
        with conectar() as conn, conn.transaction():
            cur = conn.cursor(row_factory=tuple_row)
            _usar_schema(cur, schema)
            filas = cur.execute("""
              SELECT s.id_speech, s.titulo, s.alta, min(h.fecha + h.hora_inicio) AS primero, count(h.codigo)
              FROM speech s LEFT JOIN speech_horario h ON h.id_speech = s.id_speech
              WHERE s.alta IS NOT NULL GROUP BY s.id_speech, s.titulo, s.alta
              ORDER BY s.alta DESC, s.id_speech LIMIT %s""", (MAX_NUEVAS_EN_ADMIN,)).fetchall()
    except (UndefinedColumn, UndefinedTable):
        return []
    return [{"base": b, "titulo": t, "alta": a, "primero": p, "horarios": n} for b, t, a, p, n in filas]
