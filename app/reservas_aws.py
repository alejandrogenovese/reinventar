"""Importar las reservas del portal de AWS: el calendario .ics que exporta el portal → charlas del itinerario marcadas
como reservadas (sin cola de walk-up).

No hay un formato publicado, así que cada evento se busca en el catálogo de lo más preciso a lo menos:
1. un código de horario que aparezca en el título o la descripción (DAT406-R1);
2. un código de charla (DAT406) y el horario que coincide con el día y la hora del evento;
3. el título de la charla y el día y la hora.
Lo que no se encuentra se informa (por ejemplo, eventos propios que la persona tenía en ese calendario).
"""
import datetime as dt
import re
from dataclasses import dataclass
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from . import catalog, db, itinerary, sandbox

MAX_BYTES = 1024 * 1024
MAX_EVENTOS = 500
RAZON = "Reservada en el portal de AWS."
CODIGO = re.compile(r"\b([A-Z]{2,6}\d{2,4}(?:-[A-Z0-9]{1,4})?)\b")
_ESCAPES = {"\\n": "\n", "\\N": "\n", "\\,": ",", "\\;": ";", "\\\\": "\\"}


class CalendarioInvalido(ValueError):
    pass


@dataclass(frozen=True)
class Evento:
    titulo: str
    descripcion: str
    dia: str | None    # YYYY-MM-DD en hora de Las Vegas
    hora: str | None   # HH:MM


def _unescape(valor: str) -> str:
    return re.sub(r"\\[nN,;\\]", lambda m: _ESCAPES[m.group(0)], valor)


def _hora_local(valor: str, params: dict[str, str]) -> dt.datetime | None:
    """DTSTART en UTC (Z), con TZID o "flotante" (se asume Las Vegas). Las fechas sin hora no sirven para ubicar."""
    valor = valor.strip()
    if "T" not in valor:
        return None
    try:
        if valor.endswith("Z"):
            return dt.datetime.strptime(valor, "%Y%m%dT%H%M%SZ").replace(tzinfo=dt.UTC).astimezone(sandbox.EVENT_TZ)
        tz = sandbox.EVENT_TZ
        if params.get("TZID"):
            try:
                tz = ZoneInfo(params["TZID"].strip('"'))
            except (ZoneInfoNotFoundError, ValueError):
                tz = sandbox.EVENT_TZ
        return dt.datetime.strptime(valor[:15], "%Y%m%dT%H%M%S").replace(tzinfo=tz).astimezone(sandbox.EVENT_TZ)
    except ValueError:
        return None


def _propiedad(linea: str) -> tuple[str, dict[str, str], str]:
    cabeza, _, valor = linea.partition(":")
    nombre, *params = cabeza.split(";")
    return nombre.upper(), dict(p.split("=", 1) for p in params if "=" in p), valor


def leer(texto: str) -> list[Evento]:
    """VEVENTs del calendario (con las líneas plegadas ya unidas, RFC 5545)."""
    if "BEGIN:VCALENDAR" not in texto.upper():
        raise CalendarioInvalido("El archivo no es un calendario .ics")
    lineas = re.sub(r"\r?\n[ \t]", "", texto.replace("\r\n", "\n")).split("\n")
    eventos, actual = [], None
    for linea in lineas:
        nombre, params, valor = _propiedad(linea)
        if nombre == "BEGIN" and valor.upper() == "VEVENT":
            actual = {}
        elif nombre == "END" and valor.upper() == "VEVENT" and actual is not None:
            inicio = actual.get("inicio")
            eventos.append(Evento(actual.get("titulo", ""), actual.get("descripcion", ""),
                                  inicio.strftime("%Y-%m-%d") if inicio else None, inicio.strftime("%H:%M") if inicio else None))
            actual = None
        elif actual is not None and nombre == "SUMMARY":
            actual["titulo"] = _unescape(valor).strip()
        elif actual is not None and nombre == "DESCRIPTION":
            actual["descripcion"] = _unescape(valor).strip()
        elif actual is not None and nombre == "DTSTART":
            actual["inicio"] = _hora_local(valor, params)
        if len(eventos) >= MAX_EVENTOS:
            break
    return eventos


def _en_horario(session: dict, ev: Evento) -> dict | None:
    return next((i for i in session.get("instances") or [] if i["d"] == ev.dia and i["st"] == ev.hora), None)


def buscar(ev: Evento) -> tuple[dict, dict] | None:
    """(sesión, horario) del catálogo que corresponde al evento, o None."""
    for codigo in CODIGO.findall(f"{ev.titulo} {ev.descripcion}"):
        exacto = catalog.get_instance(codigo)
        if exacto:
            return exacto
        session = catalog.get_session(codigo)
        inst = _en_horario(session, ev) if session else None
        if inst:
            return session, inst
    titulo = catalog.fold(ev.titulo)
    if not titulo or not ev.dia:
        return None
    for session in catalog.all_sessions():
        nombre = catalog.fold(session.get("title"))
        if nombre and (nombre in titulo or titulo in nombre):
            inst = _en_horario(session, ev)
            if inst:
                return session, inst
    return None


def importar(username: str, texto: str) -> dict:
    """Agrega (fijadas y reservadas) las charlas del calendario. Si la charla ya estaba en otro horario, la mueve."""
    actuales = {it["base"]: it["code"] for it in db.list_itinerary_items(username) if it.get("kind", "talk") == "talk"}
    out = {"importadas": [], "cambiadas": [], "ya_estaban": [], "sin_encontrar": []}
    for ev in leer(texto):
        encontrado = buscar(ev)
        if not encontrado:
            out["sin_encontrar"].append(ev.titulo or "(sin título)")
            continue
        session, inst = encontrado
        anterior = actuales.get(session["base"])
        if anterior == inst["c"]:
            out["ya_estaban"].append(inst["c"])
        else:
            if anterior:
                db.remove_item(username, anterior)
                out["cambiadas"].append({"de": anterior, "a": inst["c"]})
            else:
                out["importadas"].append(inst["c"])
            itinerary.add_manual(username, inst["c"], RAZON)
            actuales[session["base"]] = inst["c"]
        db.set_item_booked(username, inst["c"], True)
    return out
