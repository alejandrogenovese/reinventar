"""«Charlas nuevas» para cada persona: las que la revisión del catálogo oficial (app/charlas_auto.py) encontró en los
últimos DIAS_VISIBLES días (speech.alta) y que todavía tienen algún horario por delante.

- Lista (GET /api/charlas-nuevas, app/charlas_nuevas_api.py): cada charla con sus horarios futuros y, para cada uno,
  con qué se superpone de su itinerario. No aparecen las que agregó o descartó desde ahí (charlas_nuevas_decision) ni
  las que ya tiene en el itinerario por otro camino.
- Push (lo manda app/push.tick, como las ofertas): uno solo por vuelta con todas las que todavía no se avisaron, primero
  las que tocan sus intereses («3 charlas nuevas» · «AIM401 …, DEV302 … y 1 más»). Solo las altas de las últimas
  VENTANA_AVISO, nunca en el horario de silencio (app/recordatorio.py: sale a la mañana) y cada charla una sola vez
  (clave charlanueva:<base> en push_sent). Se apaga desde Ajustes (preferencias_avisos.charlas_nuevas, prendida).
  Las altas se consultan una vez por vuelta para todos; por persona va un camino liviano (sin armar el itinerario) con
  un advisory lock, para que con varios workers la tanda no salga partida. Un dispositivo que falla no hace que se
  desmarque: solo se reintenta si no llegó a ninguno (push.notify_cada_uno).
- Intereses: las claves de la ficha de la entrevista guiada y los intereses del armado rápido, buscados en el texto de
  la charla. Sin LLM ni embeddings: es una comparación de texto. Sin perfil, se avisa igual.
El alta se compara con el reloj real; «todavía no pasó», con el del evento (el simulado en modo prueba).
"""
import datetime as dt
import logging
import time
from collections.abc import Callable

from psycopg.errors import UndefinedColumn, UndefinedTable
from psycopg.rows import tuple_row

from . import catalog, config, db, guided, itinerary, pg, recordatorio, sandbox
from .eventos_auto import Conectar, _usar_schema

log = logging.getLogger("reinventar.charlas_nuevas")

DIAS_VISIBLES = 7
VENTANA_AVISO = dt.timedelta(hours=24)   # una charla que entró hace más que esto ya no se avisa (se ve en la lista)
PREFIJO = "charlanueva:"
URL_LISTA = "/#/itinerario/nuevas"
CODIGOS_EN_AVISO = 2
TTL_SEGUNDOS = 12 * 3600
AGREGADA, DESCARTADA = "agregada", "descartada"
_CAMPOS_TEXTO = ("title", "topic", "aoi", "services", "tech", "concepts", "concepts_en", "focus")


def ahora_real() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def clave(base: str) -> str:
    return f"{PREFIJO}{base}"


# ---------- catálogo ----------

def altas(desde: dt.datetime, conectar: Conectar | None = None, schema: str | None = None) -> dict[str, dt.datetime]:
    """{id_speech: alta} de las charlas que la revisión dio de alta desde `desde`. Sin la migración 008, ninguna."""
    schema = schema or config.CATALOGO_SCHEMA
    conectar = conectar or (lambda: pg.pool().connection())
    try:
        with conectar() as conn, conn.transaction():
            cur = conn.cursor(row_factory=tuple_row)
            _usar_schema(cur, schema)
            filas = cur.execute("SELECT id_speech, alta FROM speech WHERE alta >= %s", (desde,)).fetchall()
    except (UndefinedColumn, UndefinedTable):
        return {}
    return dict(filas)


def _empieza(instancia: dict) -> dt.datetime:
    return dt.datetime.fromisoformat(f"{instancia['d']}T{instancia['st']}").replace(tzinfo=sandbox.EVENT_TZ)


def futuras(session: dict, ahora: dt.datetime) -> list[dict]:
    """Los horarios de la charla que todavía no empezaron y no se cancelaron."""
    return [i for i in session.get("instances") or () if not i.get("cancelada") and i.get("d") and i.get("st")
            and _empieza(i) > ahora]


# ---------- intereses ----------

def claves_de_interes(username: str) -> list[str]:
    """Las claves de la ficha (entrevista guiada) y los intereses del armado rápido. Vacío si no armó perfil."""
    ficha = db.get_interview(username).get("ficha") or {}
    claves = [c for p in ficha.get("prioridades") or () for c in p.get("claves") or ()]
    perfil = db.get_profile(username) or {}
    return [c for c in [*claves, *(perfil.get("interests") or ())] if isinstance(c, str) and c.strip()]


def coincide(session: dict, claves: list[str]) -> bool:
    texto = catalog.fold(" ".join(str(session.get(k) or "") for k in _CAMPOS_TEXTO))
    return any(guided.contiene(texto, c) for c in claves)


# ---------- decisiones de la persona ----------

def decisiones(username: str) -> set[str]:
    with db.conn() as c:
        return {f["base"] for f in c.execute("SELECT base FROM charlas_nuevas_decision WHERE username=%s",
                                             (username,)).fetchall()}


def decidir(username: str, base: str, decision: str) -> None:
    if decision not in (AGREGADA, DESCARTADA):
        raise ValueError(f"decisión desconocida: {decision}")
    with db.conn() as c:
        c.execute("INSERT INTO charlas_nuevas_decision (username, base, decision, creado) VALUES (%s,%s,%s,%s) "
                  "ON CONFLICT (username, base) DO UPDATE SET decision=EXCLUDED.decision, creado=EXCLUDED.creado",
                  (username, base, decision, time.time()))


def quiere_aviso(username: str) -> bool:
    with db.conn() as c:
        r = c.execute("SELECT charlas_nuevas FROM preferencias_avisos WHERE username=%s", (username,)).fetchone()
    return r["charlas_nuevas"] if r else True


def set_quiere_aviso(username: str, avisar: bool) -> bool:
    with db.conn() as c:
        c.execute("INSERT INTO preferencias_avisos (username,grabar,ubicacion,updated_at) VALUES (%s,TRUE,FALSE,%s) "
                  "ON CONFLICT DO NOTHING", (username, time.time()))
        c.execute("UPDATE preferencias_avisos SET charlas_nuevas=%s, updated_at=%s WHERE username=%s",
                  (avisar, time.time(), username))
    return quiere_aviso(username)


# ---------- la lista ----------

def choques(card: dict, dias: list[dict]) -> list[str]:
    """Títulos de lo que tiene en el itinerario ese día y se superpone con este horario."""
    del_dia = next((d["sessions"] for d in dias if d["day"] == card["day"]), [])
    inicio, fin = itinerary._span({**card, "end": itinerary._end(card)})
    spans = [(o["title"], itinerary._span(o)) for o in del_dia if o.get("start")]
    return [titulo for titulo, (s, e) in spans if s < fin and inicio < e]


def _horario(session: dict, instancia: dict, dias: list[dict]) -> dict:
    card = catalog.card(session, instancia)
    return {"code": card["code"], "day": card["day"], "start": card["start"], "end": itinerary._end(card),
            "venue": card["venue"], "choques": choques(card, dias)}


def _candidatas(username: str, recientes: dict[str, dt.datetime], ahora: dt.datetime,
                en_agenda: set[str]) -> list[tuple[str, dt.datetime, dict, list[dict]]]:
    """(base, alta, sesión, horarios futuros) de las altas que la persona no agregó, no descartó, no tiene en el
    itinerario y todavía no pasaron."""
    ya = decisiones(username)
    out = []
    for base, alta in recientes.items():
        session = None if base in ya or base in en_agenda else catalog.get_session(base)
        proximas = futuras(session, ahora) if session else []
        if proximas:
            out.append((base, alta, session, proximas))
    return out


def _ordenar(charlas: list[dict]) -> list[dict]:
    """Primero las de sus intereses; después de la más reciente a la más vieja."""
    return sorted(charlas, key=lambda c: (not c["interes"], -dt.datetime.fromisoformat(c["alta"]).timestamp(), c["base"]))


def pendientes(username: str, ahora: dt.datetime, real: dt.datetime | None = None) -> list[dict]:
    """Las charlas nuevas que le quedan por ver (la pantalla). Cada una es la tarjeta de su próximo horario más
    `horarios` (con sus choques), `interes` y `alta`."""
    real = real or ahora_real()
    recientes = altas(real - dt.timedelta(days=DIAS_VISIBLES))
    if not recientes:
        return []
    dias = itinerary.get_current(username)["days"]
    candidatas = _candidatas(username, recientes, ahora, {c.get("base") for d in dias for c in d["sessions"]})
    claves = claves_de_interes(username) if candidatas else []
    return _ordenar([{**catalog.card(session, proximas[0]), "alta": alta.isoformat(), "interes": coincide(session, claves),
                      "horarios": [_horario(session, i, dias) for i in proximas]}
                     for _base, alta, session, proximas in candidatas])


# ---------- push ----------

CANDADO = 20261123   # advisory lock (CANDADO, hashtext(usuario)): con varios workers, la tanda sale entera de uno solo


def altas_para_aviso(real: dt.datetime | None = None) -> dict[str, dt.datetime]:
    """Las altas que todavía se avisan (las de las últimas VENTANA_AVISO). Se consulta una vez por vuelta de
    app/push.tick y se comparte entre todos los usuarios."""
    return altas((real or ahora_real()) - VENTANA_AVISO)


def mensaje(charlas: list[dict]) -> dict:
    """Un solo push para todas: «Charla nueva: AIM401» o «3 charlas nuevas», con las primeras en el cuerpo."""
    base = {"url": URL_LISTA, "tag": "charlas-nuevas", "ttl": TTL_SEGUNDOS}
    para_vos = "Para vos: " if charlas[0].get("interes") else ""
    if len(charlas) == 1:
        c = charlas[0]
        return {**base, "title": f"Charla nueva: {c['base']}", "body": f"{para_vos}{c['title']}"}
    visibles = [f"{c['base']} {c['title']}" for c in charlas[:CODIGOS_EN_AVISO]]
    resto = len(charlas) - len(visibles)
    cuerpo = f"{', '.join(visibles)} y {resto} más" if resto else " y ".join(visibles)
    return {**base, "title": f"{len(charlas)} charlas nuevas", "body": f"{para_vos}{cuerpo}"}


def _ya_avisadas(username: str, claves: list[str]) -> set[str]:
    with db.conn() as c:
        return {f["key"] for f in c.execute("SELECT key FROM push_sent WHERE username=%s AND key = ANY(%s)",
                                            (username, claves)).fetchall()}


def a_avisar(username: str, ahora: dt.datetime, recientes: dict[str, dt.datetime]) -> list[dict]:
    """Las altas de `recientes` que le quedan por ver y todavía no se le avisaron, ya ordenadas. Camino liviano: sin
    armar el itinerario, ni horarios ni choques (corre para cada persona en cada vuelta)."""
    sin_avisar = set(recientes) - _ya_avisadas(username, [clave(b) for b in recientes])
    if not sin_avisar:
        return []
    en_agenda = {i["base"] for i in db.list_itinerary_items(username)}
    candidatas = _candidatas(username, {b: recientes[b] for b in sin_avisar}, ahora, en_agenda)
    claves = claves_de_interes(username) if candidatas else []
    return _ordenar([{"base": base, "title": session["title"], "alta": alta.isoformat(),
                      "interes": coincide(session, claves)} for base, alta, session, _p in candidatas])


def enviar(username: str, ahora: dt.datetime, notificar: Callable[[str, dict], int],
           recientes: dict[str, dt.datetime] | None = None) -> int:
    """Manda el aviso agrupado si corresponde. `notificar(usuario, mensaje)` devuelve a cuántos dispositivos llegó (en
    producción, push.notify_cada_uno: un dispositivo que falla no corta a los demás). `recientes`: lo de
    altas_para_aviso (si no viene, se consulta). Devuelve cuántos push salieron (0 o 1)."""
    ahora = ahora.astimezone(sandbox.EVENT_TZ)  # el silencio es en hora de Las Vegas
    if recordatorio.en_silencio(ahora):
        return 0
    recientes = altas_para_aviso() if recientes is None else recientes
    if not recientes or not quiere_aviso(username):
        return 0
    with db.conn() as c, c.transaction():
        libre = c.execute("SELECT pg_try_advisory_xact_lock(%s, hashtext(%s)) AS libre", (CANDADO, username)).fetchone()
        if not libre["libre"]:
            return 0  # otro worker está mandando la tanda de esta persona
        return _mandar(username, a_avisar(username, ahora, recientes), notificar)


def _mandar(username: str, charlas: list[dict], notificar: Callable[[str, dict], int]) -> int:
    marcadas = [c for c in charlas if db.mark_push_sent(username, clave(c["base"]))]
    if not marcadas:
        return 0
    try:
        llego = notificar(username, mensaje(marcadas))
    except Exception:
        _desmarcar(username, marcadas)  # no se sabe si llegó a alguno: se reintenta en la próxima vuelta
        raise
    if not llego:  # no llegó a ningún dispositivo: se reintenta en la próxima vuelta
        _desmarcar(username, marcadas)
        return 0
    return 1


def _desmarcar(username: str, charlas: list[dict]) -> None:
    for c in charlas:
        db.unmark_push_sent(username, clave(c["base"]))
