"""«Próximo» del banner de estado: lo que viene enseguida entre los vuelos, los hoteles y el itinerario del día.

Puro: recibe las listas ya leídas de la base (app/vuelos.py), el plan del día (app/today.plan) y `now` con zona, y elige
uno. Nunca consulta AeroDataBox: lo usa GET /api/viajes/proximo (app/viajes_api.py), que solo lee lo guardado.

Ventanas (desde cuándo se muestra, hasta que empieza):
- Salir al aeropuerto (solo el vuelo que sale de Las Vegas, app/vuelta.py): desde 3 h antes de la hora de salir del
  hotel hasta esa hora; después queda el vuelo.
- Vuelo: desde 12 h antes de la salida (la demorada, si AeroDataBox informó demora) hasta que sale. Uno cancelado se
  muestra igual, con tono de error.
- Hotel: el check-in desde 3 h antes (como su aviso, viajes_avisos.CHECKIN_HOTEL_ANTES_H); el check-out desde 2 h antes.
- Charla o evento del itinerario: la que sigue hoy (plan["next"]), desde 2 h antes.
Gana el que empieza antes; si empiezan a la vez, aeropuerto > vuelo > hotel > charla. Todo se compara en UTC: cada hora se arma en
su zona (la del vuelo, la del hotel o la del evento).
"""
import datetime as dt
from urllib.parse import quote

from . import sandbox, viajes_avisos, vuelos, vuelta

VUELO_ANTES_H = 12
AEROPUERTO_ANTES_H = 3
CHECKIN_HOTEL_ANTES_H = viajes_avisos.CHECKIN_HOTEL_ANTES_H
CHECKOUT_HOTEL_ANTES_H = 2
CHARLA_ANTES_H = 2
ORDEN = {"aeropuerto": 0, "vuelo": 1, "hotel": 2, "charla": 3}   # desempate a igual hora de inicio
ZONA_EVENTO = sandbox.EVENT_TZ                  # el itinerario está en hora de Las Vegas

Candidato = tuple[dt.timedelta, int, dict]


def _candidato(tipo: str, inicio: dt.datetime, antes_h: float, now: dt.datetime, datos: dict) -> Candidato | None:
    if not inicio - dt.timedelta(hours=antes_h) <= now < inicio:
        return None
    return inicio - now, ORDEN[tipo], {"tipo": tipo, **datos, "inicio": inicio.astimezone(dt.UTC).isoformat()}


def _es_cancelado(v: dict) -> bool:
    return (v.get("estado") or "").lower().startswith("cancel")


def _vuelo(v: dict, now: dt.datetime) -> Candidato | None:
    sale = vuelos.salida(v)
    if not sale:
        return None
    demora = v.get("demora_min") or 0
    inicio = sale + dt.timedelta(minutes=demora)
    destino = v.get("destino_nombre") or v.get("destino_iata")
    cancelado = _es_cancelado(v)
    return _candidato("vuelo", inicio, VUELO_ANTES_H, now, {
        "titulo": f"{v['numero']} a {destino}" if destino else v["numero"],
        "hora": inicio.astimezone(vuelos.zona(v["zona"])).strftime("%H:%M"),
        "detalle": f"puerta {v['puerta']}" if v.get("puerta") else None,
        "url": f"#/viajes/vuelo/{v['id']}", "demora_min": demora, "cancelado": cancelado,
        "tono": "error" if cancelado else "info"})


def _aeropuerto(v: dict, now: dt.datetime) -> Candidato | None:
    """«Salí al aeropuerto» a la hora que calcula app/vuelta.py (solo vuelos que salen de Las Vegas)."""
    salir = vuelta.salir_al_aeropuerto(v)
    if not salir:
        return None
    sale = vuelos.salida(v).astimezone(vuelos.zona(v["zona"]))
    return _candidato("aeropuerto", salir, AEROPUERTO_ANTES_H, now, {
        "titulo": "Salí al aeropuerto", "hora": salir.astimezone(vuelos.zona(v["zona"])).strftime("%H:%M"),
        "detalle": f"{v['numero']} sale {sale:%H:%M}", "url": f"#/viajes/vuelo/{v['id']}", "tono": "info"})


def _local(texto: str, zona: str) -> dt.datetime:
    return dt.datetime.fromisoformat(texto).replace(tzinfo=vuelos.zona(zona))


def _hotel(h: dict, now: dt.datetime) -> list[Candidato]:
    comun = {"detalle": h.get("direccion") or None, "url": f"#/viajes/hotel/{h['id']}", "tono": "info"}
    entrada, salida = _local(h["checkin"], h["zona"]), _local(h["checkout"], h["zona"])
    return [c for c in (
        _candidato("hotel", entrada, CHECKIN_HOTEL_ANTES_H, now,
                   {**comun, "titulo": f"Check-in en {h['nombre']}", "hora": f"{entrada:%H:%M}"}),
        _candidato("hotel", salida, CHECKOUT_HOTEL_ANTES_H, now,
                   {**comun, "titulo": f"Check-out de {h['nombre']}", "hora": f"{salida:%H:%M}"}),
    ) if c]


def _url_item(s: dict) -> str:
    """A dónde lleva tocar el ítem: igual que en Hoy (web/js/today.js, itemHref)."""
    if s.get("kind") == "event" and s.get("code"):
        return f"#/evento/{quote(str(s['code']), safe='')}"
    if s.get("kind") == "show" and s.get("show"):
        return f"#/show/{quote(str(s['show']), safe='')}"
    if s.get("kind") == "mine" or not s.get("base"):
        return "#/itinerario"
    return f"#/charla/{s['base']}"


def _charla(plan_hoy: dict | None, now: dt.datetime) -> Candidato | None:
    s = (plan_hoy or {}).get("next")
    if not s or not s.get("start") or not plan_hoy.get("date"):
        return None
    try:
        inicio = dt.datetime.fromisoformat(f"{plan_hoy['date']}T{s['start']}").replace(tzinfo=ZONA_EVENTO)
    except ValueError:
        return None
    venue = s.get("venue") if isinstance(s.get("venue"), dict) else {}
    # En el banner alcanza con el hotel y la primera parte de la sala: el detalle completo
    # («Upper Convention Promenade · Cristal 2 · Content Hub · Red Theater») ocupa media pantalla y está en la ficha.
    sala_corta = (venue.get("detail") or "").split(" · ")[0]
    sala = " · ".join(filter(None, (venue.get("hotel"), sala_corta))) or None
    return _candidato("charla", inicio, CHARLA_ANTES_H, now, {
        "titulo": s.get("title") or "Lo que sigue", "hora": s["start"], "detalle": sala, "url": _url_item(s),
        "tono": "info"})


def elegir(lista_vuelos: list[dict], lista_hoteles: list[dict], plan_hoy: dict | None, now: dt.datetime) -> dict | None:
    """{tipo, titulo, hora, detalle, url, tono, inicio, …} de lo próximo, o None si no hay nada dentro de su ventana."""
    candidatos = [c for v in lista_vuelos if (c := _vuelo(v, now))]
    candidatos += [c for v in lista_vuelos if (c := _aeropuerto(v, now))]
    candidatos += [c for h in lista_hoteles for c in _hotel(h, now)]
    candidatos += [c for c in (_charla(plan_hoy, now),) if c]
    if not candidatos:
        return None
    return min(candidatos, key=lambda c: (c[0], c[1]))[2]
