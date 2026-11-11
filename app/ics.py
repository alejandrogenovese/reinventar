"""El itinerario como calendario .ics (RFC 5545), para importarlo en el calendario del teléfono.

Cada ítem es un VEVENT en UTC (las horas del catálogo son de Las Vegas) con una alarma: 15 min antes del inicio, o
15 min antes de la hora de la cola si la charla no está reservada. Si eligió irse antes, el evento termina a esa hora.
"""
import datetime as dt

from . import config, leave, sandbox
from .guided import COLA_SIN_RESERVA

PRODID = "-//ReinventAR//Itinerario re:Invent//ES"
ALARMA_MIN = 15
DURACION_SIN_FIN_MIN = 60
MAX_OCTETOS = 75


def _escape(texto: str) -> str:
    return texto.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\r\n", "\\n").replace("\n", "\\n")


def _fold(linea: str) -> str:
    """Pliega en líneas de hasta 75 octetos sin cortar un carácter UTF-8; las siguientes empiezan con un espacio."""
    partes, actual = [], b""
    for ch in linea:
        b = ch.encode()
        if len(actual) + len(b) > (MAX_OCTETOS if not partes else MAX_OCTETOS - 1):
            partes.append(actual.decode())
            actual = b""
        actual += b
    partes.append(actual.decode())
    return "\r\n ".join(partes)


def _local(day: str, hhmm: str) -> dt.datetime:
    return dt.datetime.fromisoformat(f"{day}T{hhmm}").replace(tzinfo=sandbox.EVENT_TZ)


def _utc(d: dt.datetime) -> str:
    return d.astimezone(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _rango(c: dict) -> tuple[dt.datetime, dt.datetime]:
    inicio = _local(c["day"], c["start"])
    fin_hhmm = leave.leave_early_at(c) or c.get("end")
    if not fin_hhmm:
        return inicio, inicio + dt.timedelta(minutes=DURACION_SIN_FIN_MIN)
    fin = _local(c["day"], fin_hhmm)
    return inicio, fin if fin > inicio else fin + dt.timedelta(days=1)  # termina pasada la medianoche


def _descripcion(c: dict) -> str:
    base = (config.WEBAUTHN_ORIGIN or "https://reinventar.app").rstrip("/")
    partes = [
        c["code"] if c.get("kind", "talk") == "talk" else None,
        f"Sin reserva: hacé la cola desde las {leave.arrive_by(c)}." if leave.needs_queue(c) else None,
        f"Salís a las {leave.leave_early_at(c)} para llegar a la siguiente." if leave.leave_early_at(c) else None,
        c.get("reason") or None,
        c.get("note") or None,
        f"{base}/#/charla/{c['base']}" if c.get("kind", "talk") == "talk" else f"{base}/#/itinerario",
    ]
    return "\n".join(p for p in partes if p)


def _vevent(c: dict, ahora: dt.datetime) -> list[str]:
    inicio, fin = _rango(c)
    venue = c.get("venue") or {}
    lugar = " · ".join(filter(None, (venue.get("hotel"), venue.get("detail"))))
    antes = ALARMA_MIN + (COLA_SIN_RESERVA if leave.needs_queue(c) else 0)
    return [
        "BEGIN:VEVENT",
        f"UID:{c['code']}-{c['day']}@reinventar",
        f"DTSTAMP:{_utc(ahora)}",
        f"DTSTART:{_utc(inicio)}",
        f"DTEND:{_utc(fin)}",
        f"SUMMARY:{_escape(c['title'])}",
        f"LOCATION:{_escape(lugar)}" if lugar else None,
        f"DESCRIPTION:{_escape(_descripcion(c))}",
        "BEGIN:VALARM", "ACTION:DISPLAY", f"TRIGGER:-PT{antes}M",
        f"DESCRIPTION:{_escape('Hacé la cola: ' + c['title'] if leave.needs_queue(c) else c['title'])}",
        "END:VALARM",
        "END:VEVENT",
    ]


def calendario(cards: list[dict], ahora: dt.datetime | None = None) -> str:
    ahora = ahora or dt.datetime.now(dt.timezone.utc)
    lineas = ["BEGIN:VCALENDAR", "VERSION:2.0", f"PRODID:{PRODID}", "CALSCALE:GREGORIAN", "METHOD:PUBLISH",
              "X-WR-CALNAME:re:Invent · ReinventAR"]
    for c in cards:
        if c.get("start") and c.get("day"):
            lineas += [x for x in _vevent(c, ahora) if x]
    lineas.append("END:VCALENDAR")
    return "\r\n".join(_fold(x) for x in lineas) + "\r\n"
