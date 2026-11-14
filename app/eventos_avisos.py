"""Push de eventos (los arma app/push.due junto con el resto de los avisos; cada uno sale una sola vez por clave).

- Cancelado: a quien tiene el evento en su itinerario, si todavía no empezó. Llega aunque haya apagado los de nuevos.
- Eventos nuevos: uno solo por tanda, con los nombres ("3 eventos nuevos: A, B y 1 más"). Solo los que encontró la
  revisión automática (app/eventos_auto.py; la carga inicial no cuenta) y si la persona no los apagó en su perfil.
Ninguno sale en el horario de silencio (app/recordatorio.py): lo que se junte de noche sale a la mañana.
"""
import datetime as dt
import time

from . import events, recordatorio, sandbox

PREFIJO_NUEVOS = "evnuevos:"
PREFIJO_CANCELADO = "evcancel:"
VENTANA_PRIMERA_VEZ_H = 24   # sin un aviso anterior, se cuentan los nuevos de las últimas 24 h
NOMBRES_EN_AVISO = 2


def _empieza(card: dict) -> dt.datetime | None:
    if not (card.get("day") and card.get("start")):
        return None
    return dt.datetime.fromisoformat(f"{card['day']}T{card['start']}").replace(tzinfo=sandbox.EVENT_TZ)


def _dia(card: dict) -> str:
    return dt.date.fromisoformat(card["day"]).strftime("%d/%m")


def cancelados(days: list[dict], now: dt.datetime) -> list[tuple[str, dict]]:
    out = []
    for day in days:
        for c in day["sessions"]:
            empieza = _empieza(c)
            if c.get("kind") != "event" or not c.get("cancelled") or not empieza or empieza <= now:
                continue
            out.append((f"{PREFIJO_CANCELADO}{c['code']}",
                        {"title": f"Se canceló {c['title']}",
                         "body": f"{_dia(c)} a las {c['start']} · ya no aparece en su página. Revisalo antes de ir.",
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
    out = cancelados(days, now)
    if quiere_nuevos and (aviso := nuevos(ultimo_nuevos, time.time())):
        out.append(aviso)
    return out
