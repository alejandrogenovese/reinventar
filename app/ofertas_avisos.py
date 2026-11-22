"""Push de ofertas (los manda app/push.tick junto con el resto de los avisos). Cada oferta sale una sola vez por persona.

- A quién: a quien prendió las alertas, para las categorías que eligió.
- Cuándo: cuando arranca la vigencia (o cuando se la cargó, si ya había arrancado) y hasta OFERTAS_VENTANA_HORAS
  después; nunca de noche (horario de silencio de app/recordatorio.py): lo de la noche sale a la mañana.
- Antispam: como mucho OFERTAS_MAX_POR_DIA push por persona y por día. Si hay más ofertas pendientes que push
  disponibles, van todas juntas en uno solo ("3 ofertas nuevas") que abre la lista.
El push de una oferta abre #/ofertas/<id>; el service worker abre `url` al tocarlo (web/sw.js).
"""
import datetime as dt
import time
from collections.abc import Callable
from dataclasses import dataclass

from . import config, db, ofertas, recordatorio

PREFIJO_OFERTA = "oferta:"
PREFIJO_PUSH = "ofpush:"       # ofpush:<día en Las Vegas>:<n>, una por push mandado: sirve para contar los del día
NOMBRES_EN_AVISO = 2
TTL_SEGUNDOS = 6 * 3600        # una oferta que llega 6 h tarde ya casi no sirve


@dataclass(frozen=True)
class Aviso:
    claves: list[str]          # las ofertas que cubre este push (para no repetirlas)
    mensaje: dict


def clave(id_oferta: str) -> str:
    return f"{PREFIJO_OFERTA}{id_oferta}"


def _arranca(o: ofertas.Oferta) -> dt.datetime:
    """Desde cuándo se puede avisar: la vigencia o, si se cargó después de que empezara, el momento de cargarla."""
    return max(o.desde, dt.datetime.fromtimestamp(o.creado, tz=o.desde.tzinfo))


def elegibles(lista: list[ofertas.Oferta], ahora: dt.datetime, categorias: frozenset[str], ya: set[str]) -> list[ofertas.Oferta]:
    """Las ofertas a avisar ahora: de una categoría suscripta, ya arrancadas y no vencidas, dentro de la ventana y no avisadas.
    Las más viejas primero."""
    ventana = dt.timedelta(hours=config.OFERTAS_VENTANA_HORAS)
    out = [o for o in lista
           if o.categoria in categorias and clave(o.id) not in ya and _arranca(o) <= ahora < _arranca(o) + ventana
           and (o.hasta is None or o.hasta > ahora)]
    return sorted(out, key=_arranca)


def _usd(valor) -> str:
    return f"US$ {valor:.0f}" if valor == valor.to_integral() else f"US$ {valor:.2f}"


def mensaje(o: ofertas.Oferta) -> dict:
    """El push de una oferta."""
    if o.precio_ahora is not None and o.precio_antes is not None:
        titulo = f"{o.titulo} bajó a {_usd(o.precio_ahora)}"
        partes = [f"Antes {_usd(o.precio_antes)}", o.lugar]
    else:
        titulo = o.titulo
        partes = [o.lugar, o.nota]
    return {"title": titulo, "body": " · ".join(p for p in partes if p), "url": f"/#/ofertas/{o.id}", "tag": clave(o.id),
            "ttl": TTL_SEGUNDOS}


def mensaje_grupo(lista: list[ofertas.Oferta]) -> dict:
    nombres = [o.titulo for o in lista]
    visibles = nombres[:NOMBRES_EN_AVISO]
    resto = len(nombres) - len(visibles)
    cuerpo = f"{', '.join(visibles)} y {resto} más" if resto else " y ".join(visibles)
    return {"title": f"{len(lista)} ofertas nuevas", "body": cuerpo, "url": "/#/ofertas", "tag": "ofertas", "ttl": TTL_SEGUNDOS}


def armar(pendientes: list[ofertas.Oferta], quedan: int) -> list[Aviso]:
    """Los push a mandar con `quedan` disponibles hoy: uno por oferta si entran; si no, uno solo con todas."""
    if not pendientes or quedan <= 0:
        return []
    if len(pendientes) <= quedan:
        return [Aviso([clave(o.id)], mensaje(o)) for o in pendientes]
    return [Aviso([clave(o.id) for o in pendientes], mensaje_grupo(pendientes))]


# ---------- con base ----------

def _ya_avisadas(username: str, claves: list[str]) -> set[str]:
    if not claves:
        return set()
    with db.conn() as c:
        return {f["key"] for f in c.execute("SELECT key FROM push_sent WHERE username=%s AND key = ANY(%s)", (username, claves)).fetchall()}


def _push_de_hoy(username: str, ahora: dt.datetime) -> int:
    with db.conn() as c:
        return c.execute("SELECT count(*) AS n FROM push_sent WHERE username=%s AND key LIKE %s",
                         (username, f"{PREFIJO_PUSH}{ahora:%Y-%m-%d}:%")).fetchone()["n"]


def _desmarcar(username: str, claves: tuple[str, ...]) -> None:
    for k in claves:
        db.unmark_push_sent(username, k)


def enviar(username: str, ahora: dt.datetime, notificar: Callable[[str, dict], int]) -> int:
    """Manda a esta persona las ofertas que correspondan. `notificar(usuario, mensaje)` devuelve a cuántos dispositivos
    llegó (en producción, push.notify). Devuelve cuántos push salieron."""
    prefs = ofertas.preferencias(username)
    if not prefs["activas"] or recordatorio.en_silencio(ahora):
        return 0
    vigentes = ofertas.vigentes(ahora)
    pendientes = elegibles(vigentes, ahora, frozenset(prefs["categorias"]), _ya_avisadas(username, [clave(o.id) for o in vigentes]))
    enviados = 0
    for aviso in armar(pendientes, config.OFERTAS_MAX_POR_DIA - _push_de_hoy(username, ahora)):
        nuevas = [k for k in aviso.claves if db.mark_push_sent(username, k)]
        if not nuevas:
            continue  # otra vuelta ya lo mandó
        marca = f"{PREFIJO_PUSH}{ahora:%Y-%m-%d}:{time.time_ns()}"
        db.mark_push_sent(username, marca)
        try:
            llego = notificar(username, aviso.mensaje)
        except Exception:
            _desmarcar(username, (*nuevas, marca))  # un timeout no puede dar la oferta por avisada ni gastar el tope del día
            raise
        if llego:
            enviados += 1
        else:  # no llegó a ningún dispositivo: se reintenta en la próxima vuelta
            _desmarcar(username, (*nuevas, marca))
    return enviados
