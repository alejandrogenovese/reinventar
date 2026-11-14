"""Push de eventos (los arma app/push.due junto con el resto de los avisos; cada uno sale una sola vez por clave).

- Cancelado: a quien tiene el evento en su itinerario, si todavía no empezó. Llega aunque haya apagado los de nuevos.
- Charla cancelada: lo mismo para una charla del itinerario que dejó de aparecer en el catálogo oficial dos revisiones
  seguidas (app/charlas_auto.py): «Se canceló AIM301 (mar 2/12 10:00)».
- Shows de Ticketmaster: cancelado o postergado, igual (los cambios de horario los avisa app/changes.py). No hay aviso
  de shows nuevos.
- Eventos nuevos: uno solo por tanda, con los nombres ("3 eventos nuevos: A, B y 1 más"). Solo los que encontró la
  revisión automática (app/eventos_auto.py; la carga inicial no cuenta) y si la persona no los apagó en su perfil.
Ninguno sale en el horario de silencio (app/recordatorio.py): lo que se junte de noche sale a la mañana.
"""
import datetime as dt
import time

from . import events, recordatorio, sandbox

PREFIJO_NUEVOS = "evnuevos:"
PREFIJO_CANCELADO = "evcancel:"
PREFIJO_CHARLA_CANCELADA = "chcancel:"
PREFIJO_SHOW_CANCELADO = "showcancel:"
PREFIJO_SHOW_POSTERGADO = "showpost:"
VENTANA_PRIMERA_VEZ_H = 24   # sin un aviso anterior, se cuentan los nuevos de las últimas 24 h
NOMBRES_EN_AVISO = 2


def _empieza(card: dict) -> dt.datetime | None:
    if not (card.get("day") and card.get("start")):
        return None
    return dt.datetime.fromisoformat(f"{card['day']}T{card['start']}").replace(tzinfo=sandbox.EVENT_TZ)


def _dia(card: dict) -> str:
    return dt.date.fromisoformat(card["day"]).strftime("%d/%m")


def _aviso_show(c: dict) -> tuple[str, dict] | None:
    url = f"/#/show/{c.get('show')}"
    if c.get("cancelled"):
        return (f"{PREFIJO_SHOW_CANCELADO}{c['code']}",
                {"title": f"Se canceló {c['title']}",
                 "body": f"{_dia(c)} a las {c['start']} · Ticketmaster la marca cancelada. Revisá tu entrada.", "url": url})
    if c.get("postponed"):
        return (f"{PREFIJO_SHOW_POSTERGADO}{c['code']}",
                {"title": f"Se postergó {c['title']}",
                 "body": f"{_dia(c)} a las {c['start']} · Ticketmaster la marca postergada. Revisá tu entrada.",
                 "url": url})
    return None


def _aviso_evento(c: dict) -> tuple[str, dict] | None:
    if not c.get("cancelled"):
        return None
    return (f"{PREFIJO_CANCELADO}{c['code']}",
            {"title": f"Se canceló {c['title']}",
             "body": f"{_dia(c)} a las {c['start']} · ya no aparece en su página. Revisalo antes de ir.",
             "url": "/#/itinerario"})


_AVISO_POR_KIND = {"event": _aviso_evento, "show": _aviso_show}


def cancelados(days: list[dict], now: dt.datetime) -> list[tuple[str, dict]]:
    """Eventos cancelados y shows cancelados o postergados del itinerario que todavía no empezaron."""
    out = []
    for day in days:
        for c in day["sessions"]:
            empieza, armar = _empieza(c), _AVISO_POR_KIND.get(c.get("kind"))
            if not armar or not empieza or empieza <= now:
                continue
            if aviso := armar(c):
                out.append(aviso)
    return out


def cuando(card: dict) -> str:
    """'mar 2/12 10:00' (los días como en app/changes.py)."""
    dia = dt.date.fromisoformat(card["day"])
    return f"{('lun', 'mar', 'mié', 'jue', 'vie', 'sáb', 'dom')[dia.weekday()]} {dia.day}/{dia.month} {card['start']}"


def charlas_canceladas(days: list[dict], now: dt.datetime) -> list[tuple[str, dict]]:
    out = []
    for day in days:
        for c in day["sessions"]:
            empieza = _empieza(c)
            if c.get("kind", "talk") != "talk" or not c.get("cancelled") or not empieza or empieza <= now:
                continue
            out.append((f"{PREFIJO_CHARLA_CANCELADA}{c['code']}",
                        {"title": f"Se canceló {c['code']} ({cuando(c)})",
                         "body": f"«{c['title']}» ya no aparece en el catálogo oficial de AWS. Buscá otra charla.",
                         "url": "/#/itinerario"}))
    return out


def texto_nuevos(nombres: list[str]) -> tuple[str, str]:
    """("3 eventos nuevos", "A, B y 1 más")."""
    n = len(nombres)
    titulo = "1 evento nuevo" if n == 1 else f"{n} eventos nuevos"
    visibles = nombres[:NOMBRES_EN_AVISO]
    resto = n - len(visibles)
    if resto:
        return titulo, f"{', '.join(visibles)} y {resto} más"
    return titulo, " y ".join(visibles)


def nuevos(ultimo: float | None, ahora: float) -> tuple[str, dict] | None:
    """El aviso de los eventos nuevos desde el último aviso de este tipo (o de las últimas 24 h)."""
    desde = max(ultimo or 0, ahora - VENTANA_PRIMERA_VEZ_H * 3600)
    encontrados = events.nuevos_desde(desde)
    if not encontrados:
        return None
    titulo, cuerpo = texto_nuevos([e["title"] for e in encontrados])
    clave = f"{PREFIJO_NUEVOS}{max(e['added'] for e in encontrados):.0f}"
    return clave, {"title": titulo, "body": cuerpo, "url": "/#/eventos"}


def avisos(days: list[dict], now: dt.datetime, *, quiere_nuevos: bool, ultimo_nuevos: float | None) -> list[tuple[str, dict]]:
    if recordatorio.en_silencio(now):
        return []
    out = cancelados(days, now) + charlas_canceladas(days, now)
    if quiere_nuevos and (aviso := nuevos(ultimo_nuevos, time.time())):
        out.append(aviso)
    return out
