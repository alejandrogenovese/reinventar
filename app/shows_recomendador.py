"""¿Cuándo nos conviene ir a un show? Rankea sus funciones según el itinerario del usuario (puro, sin base ni red).

Cada función se compara con lo que el usuario tiene ese mismo día: si se superpone ("choca"), si no se superpone pero
el traslado caminando no alcanza ("justo") o si llega con margen ("libre"). La razón sale del mismo cálculo, así el
ranking se puede explicar. Del lado de Ticketmaster solo se informa lo que trae (precio mínimo y si no está en venta).
"""
from .travel import estimar_minutos

MARGEN_SIN_UBICACION_MIN = 20   # traslado que se asume si falta la ubicación de alguna de las dos puntas
DURACION_DEFAULT_MIN = 90       # ítems sin hora de fin
HOLGURA_MAX_MIN = 180           # a partir de acá más aire no suma
FIN_DEL_DIA_MIN = 24 * 60

_ORDEN_ESTADO = {"libre": 0, "justo": 1, "choca": 2}


def _minutos(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def _hhmm(minutos: int) -> str:
    return f"{minutos // 60:02d}:{minutos % 60:02d}"


def _tramo(card: dict) -> tuple[int, int]:
    """(inicio, fin) en minutos del día; lo que termina pasada la medianoche cuenta hasta el final del día."""
    inicio = _minutos(card["start"])
    fin = _minutos(card["end"]) if card.get("end") else inicio + DURACION_DEFAULT_MIN
    return inicio, fin if fin > inicio else FIN_DEL_DIA_MIN


def _coordenadas(card: dict) -> tuple[float, float] | None:
    venue = card.get("venue") or {}
    return (venue["lat"], venue["lng"]) if venue.get("lat") is not None and venue.get("lng") is not None else None


def _traslado(a: dict, b: dict) -> tuple[int, bool]:
    """(minutos caminando entre dos tarjetas, True si es un margen asumido por falta de ubicación)."""
    ca, cb = _coordenadas(a), _coordenadas(b)
    if ca is None or cb is None:
        return MARGEN_SIN_UBICACION_MIN, True
    return estimar_minutos(ca, cb), False


def _aviso(funcion: dict) -> str | None:
    return "Sin venta por ahora." if funcion.get("status") == "offsale" else None


def _lado_previo(funcion: dict, inicio: int, previo: dict | None) -> tuple[int | None, str]:
    """(holgura en minutos, frase) respecto de lo último que termina antes de la función."""
    if previo is None:
        return None, ""
    _, fin = _tramo(previo)
    minutos, asumido = _traslado(previo, funcion)
    nota = " (tiempo estimado)" if asumido else ""
    return inicio - fin - minutos, f"{minutos} min caminando desde «{previo['title']}» (termina {_hhmm(fin)}){nota}"


def _lado_siguiente(funcion: dict, fin: int, siguiente: dict | None) -> tuple[int | None, str]:
    """(holgura en minutos, frase) respecto de lo primero que empieza después de la función."""
    if siguiente is None:
        return None, ""
    inicio, _ = _tramo(siguiente)
    minutos, asumido = _traslado(funcion, siguiente)
    nota = " (tiempo estimado)" if asumido else ""
    return inicio - fin - minutos, f"{minutos} min para llegar a «{siguiente['title']}» ({_hhmm(inicio)}){nota}"


def _ventana(previo: dict | None, siguiente: dict | None) -> str:
    desde = _hhmm(_tramo(previo)[1]) if previo else None
    hasta = _hhmm(_tramo(siguiente)[0]) if siguiente else None
    if desde and hasta:
        return f"Libre de {desde} a {hasta}"
    if desde:
        return f"Libre desde las {desde}"
    if hasta:
        return f"Libre hasta las {hasta}"
    return "Sin nada más ese día en tu itinerario"


def _evaluar(funcion: dict, agenda_del_dia: list[dict]) -> dict:
    inicio, fin = _tramo(funcion)
    choque = next((c for c in agenda_del_dia if _tramo(c)[0] < fin and inicio < _tramo(c)[1]), None)
    if choque:
        return {"estado": "choca", "holgura_min": 0,
                "razon": f"Se superpone con «{choque['title']}» ({_hhmm(_tramo(choque)[0])})."}
    previo = max((c for c in agenda_del_dia if _tramo(c)[1] <= inicio), key=lambda c: _tramo(c)[1], default=None)
    siguiente = min((c for c in agenda_del_dia if _tramo(c)[0] >= fin), key=lambda c: _tramo(c)[0], default=None)
    holgura_previa, frase_previa = _lado_previo(funcion, inicio, previo)
    holgura_siguiente, frase_siguiente = _lado_siguiente(funcion, fin, siguiente)
    holguras = [h for h in (holgura_previa, holgura_siguiente) if h is not None]
    holgura = min(holguras + [HOLGURA_MAX_MIN]) if holguras else HOLGURA_MAX_MIN
    frases = [f for f in (frase_previa, frase_siguiente) if f]
    if holgura < 0:
        problema = frase_previa if holgura_previa is not None and holgura_previa < 0 else frase_siguiente
        return {"estado": "justo", "holgura_min": holgura, "razon": f"Justo: {problema}; no llegás con ese margen."}
    return {"estado": "libre", "holgura_min": holgura,
            "razon": " · ".join([_ventana(previo, siguiente), *frases]) + ("." if not frases else "")}


def recomendar(funciones: list[dict], agenda: list[dict]) -> list[dict]:
    """Funciones sugeridas, de la que más conviene a la que menos. No toca las entradas.

    `funciones`: tarjetas de las funciones del show (day, start, end, venue, cancelled, status, price_from).
    `agenda`: tarjetas del itinerario del usuario (day, start, end, title, venue).
    """
    codigos_propios = {f["code"] for f in funciones}
    en_itinerario = {c["code"] for c in agenda} & codigos_propios
    ajena = [c for c in agenda if c.get("start") and c["code"] not in codigos_propios]
    sugeridas = []
    for f in funciones:
        if f.get("cancelled"):
            continue
        del_dia = [c for c in ajena if c["day"] == f["day"]]
        sugeridas.append({
            "code": f["code"], "day": f["day"], "start": f["start"], "end": f.get("end"),
            **_evaluar(f, del_dia),
            "price_from": f.get("price_from"), "aviso": _aviso(f), "in_itinerary": f["code"] in en_itinerario,
        })
    return sorted(sugeridas, key=lambda s: (_ORDEN_ESTADO[s["estado"]], s["aviso"] is not None, -s["holgura_min"],
                                            s["day"], s["start"]))
