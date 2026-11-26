"""Cómo ir entre sedes (app/rutas.py): atajos fijos, la recomendación corta y Routes API sin red (httpx.post simulado).

Con sedes y tiempos de prueba en memoria: no usa el catálogo y corre en CI."""
import datetime as dt
import logging

import httpx
import pytest

from app import config, lleno_alternativas, rutas, travel, venues

CLAVE = "clave-de-prueba-no-real"
SEDES = [
    {"id_sede": 1, "nombre": "Allegiant Stadium", "lat": 36.0908, "lng": -115.1840, "direccion": None},
    {"id_sede": 2, "nombre": "Caesars Forum", "lat": 36.1179, "lng": -115.1641, "direccion": None},
    {"id_sede": 3, "nombre": "Wynn/Encore", "lat": 36.1265, "lng": -115.1657, "direccion": None},
    {"id_sede": 5, "nombre": "MGM Grand", "lat": 36.1022, "lng": -115.1695, "direccion": None},
    {"id_sede": 6, "nombre": "Various Locations", "lat": None, "lng": None, "direccion": None},
    {"id_sede": 7, "nombre": "Venetian", "lat": 36.1216, "lng": -115.1691, "direccion": None},
]
TIEMPOS = [{"id_origen": 7, "id_destino": 3, "minutos": 14}, {"id_origen": 7, "id_destino": 5, "minutos": 43}]


@pytest.fixture
def maestro():
    venues.load(SEDES)
    travel.load(TIEMPOS)
    rutas.reiniciar()
    yield
    travel.load([])
    rutas.reiniciar()


@pytest.fixture
def google(monkeypatch, maestro):
    """Routes API «de verdad», pero httpx.post devuelve lo que diga cada test y anota los pedidos."""
    monkeypatch.setattr(config, "RUTAS_PROVIDER", "google")
    monkeypatch.setattr(config, "GOOGLE_MAPS_API_KEY", CLAVE)
    monkeypatch.setattr(config, "WEBAUTHN_ORIGIN", "https://reinventar.app")
    pedidos, respuestas = [], []

    def post(url, json, headers, timeout):
        pedidos.append({"url": url, "json": json, "headers": headers})
        r = respuestas.pop(0)
        if isinstance(r, Exception):
            raise r
        return r

    monkeypatch.setattr(rutas.httpx, "post", post)
    return pedidos, respuestas


def _elemento(destino, segundos, metros):
    e = {"originIndex": 0, "condition": "ROUTE_EXISTS", "duration": f"{segundos}s", "distanceMeters": metros}
    return {**e, "destinationIndex": destino} if destino else e  # Google omite los índices en cero


def test_atajos_fijos_entre_sedes():
    assert rutas.atajo_fijo("MGM Grand", "Caesars Forum", 34).startswith("o monorail gratis con badge")
    assert rutas.atajo_fijo("Caesars Forum", "MGM Grand", 34) == rutas.atajo_fijo("MGM Grand", "Caesars Forum", 34)
    assert "puente Wynn–Venetian" in rutas.atajo_fijo("Venetian", "Wynn/Encore", 14)


MARTES_11 = dt.datetime(2026, 12, 1, 11, 0)


def test_shuttle_solo_si_es_lejos_y_hay_shuttle_entre_esas_sedes():
    assert rutas.atajo_fijo("MGM Grand", "Venetian", 43, MARTES_11) == rutas.TEXTO_SHUTTLE
    assert rutas.atajo_fijo("Caesars Palace", "Wynn/Encore", 22, MARTES_11) == rutas.TEXTO_SHUTTLE
    assert rutas.atajo_fijo("Caesars Palace", "Venetian", 13, MARTES_11) is None    # cerca: se camina
    assert rutas.atajo_fijo("Caesars Forum", "Venetian", 40, MARTES_11) is None     # sin shuttle entre estas dos (2025)
    assert rutas.atajo_fijo("Allegiant Stadium", "MGM Grand", 34, MARTES_11) is None  # fuera del campus de charlas
    assert rutas.atajo_fijo("Venetian", "Venetian", 5, MARTES_11) is None
    assert rutas.atajo_fijo(None, "Venetian", 30, MARTES_11) is None
    assert rutas.atajo_fijo("MGM Grand", "Venetian", 43) is None                     # sin hora no se promete shuttle


@pytest.mark.parametrize("cuando, hay", [
    (dt.datetime(2026, 11, 29, 9, 29), False),    # domingo: desde las 9:30
    (dt.datetime(2026, 11, 29, 12, 0), True),     # domingo, MGM ↔ Venetian está en el servicio limitado
    (dt.datetime(2026, 11, 29, 20, 31), False),
    (dt.datetime(2026, 11, 30, 5, 59), False),    # lunes 6:00 a 21:15
    (dt.datetime(2026, 11, 30, 6, 0), True),
    (dt.datetime(2026, 11, 30, 21, 15), True),
    (dt.datetime(2026, 11, 30, 21, 16), False),
    (dt.datetime(2026, 12, 1, 20, 30), True),     # martes 6:00 a 20:30
    (dt.datetime(2026, 12, 1, 20, 45), False),
    (dt.datetime(2026, 12, 2, 7, 0), True),       # miércoles 6:00 a 20:30
    (dt.datetime(2026, 12, 2, 21, 0), False),
    (dt.datetime(2026, 12, 3, 17, 45), True),     # jueves hasta las 17:45
    (dt.datetime(2026, 12, 3, 18, 30), False),    # el de re:Play va a la fiesta, no entre sedes
    (dt.datetime(2026, 12, 4, 9, 0), False),      # viernes: solo Venetian y Wynn/Encore
    (dt.datetime(2026, 12, 5, 10, 0), False),     # el sábado ya no hay
    (dt.datetime(2026, 11, 28, 10, 0), False),
])
def test_shuttle_mgm_venetian_segun_dia_y_hora(cuando, hay):
    esperado = rutas.TEXTO_SHUTTLE if hay else None
    assert rutas.atajo_fijo("MGM Grand", "Venetian", 43, cuando) == esperado


def test_servicio_limitado_del_domingo_y_del_viernes():
    domingo = dt.datetime(2026, 11, 29, 12, 0)
    assert rutas.atajo_fijo("MGM Grand", "Caesars Forum", 34, domingo).startswith("o monorail")  # el atajo no depende
    assert rutas.atajo_fijo("Caesars Palace", "Wynn/Encore", 22, domingo) is None   # no están en el domingo
    viernes = dt.datetime(2026, 12, 4, 10, 0)
    assert rutas.hay_shuttle(frozenset({"Caesars Palace", "Wynn/Encore"}), viernes) is False
    assert "puente" in rutas.atajo_fijo("Venetian", "Wynn/Encore", 25, viernes)      # entre esas dos, el puente


def test_horarios_shuttle_tienen_fuente_oficial():
    assert rutas.FUENTE_AGENDA_2026.startswith("https://aws.amazon.com/events/reinvent/agenda")
    assert all(h.desde < h.hasta and h.sedes <= rutas.CAMPUS for h in rutas.HORARIOS_SHUTTLE.values())


def test_momento_arma_la_hora_de_las_vegas():
    assert rutas.momento("2026-12-01", "14:30") == dt.datetime(2026, 12, 1, 14, 30)
    assert rutas.momento("2026-12-01", "14:30:00") == dt.datetime(2026, 12, 1, 14, 30)
    assert rutas.momento(None, "14:30") is None
    assert rutas.momento("mañana", "14:30") is None


def test_atajos_tienen_fuente_publica():
    for atajo in rutas.ATAJOS:
        assert atajo.fuente.startswith("https://")
        assert len(atajo.sedes) == 2


def test_transporte_publico_solo_si_ahorra_bastante_y_no_hay_atajo():
    assert rutas.recomendar("Allegiant Stadium", "MGM Grand", 34, 15) == "o transporte público ~15 min"
    assert rutas.recomendar("Allegiant Stadium", "MGM Grand", 34, 28) is None    # ahorra poco
    assert rutas.recomendar("Allegiant Stadium", "MGM Grand", 34, None) is None
    assert rutas.recomendar("MGM Grand", "Venetian", 43, 10, MARTES_11) == rutas.TEXTO_SHUTTLE  # el atajo fijo gana
    assert rutas.recomendar("MGM Grand", "Venetian", 43, 10, dt.datetime(2026, 12, 3, 19, 0)) == "o transporte público ~10 min"


def test_leer_matriz_omite_sin_ruta_y_redondea_para_arriba():
    elementos = [_elemento(0, 601, 900), _elemento(1, 30, 0), {"destinationIndex": 2, "condition": "ROUTE_NOT_FOUND"}]
    assert rutas.leer_matriz(elementos) == {0: (11, 900), 1: (1, 0)}


def test_sin_clave_no_llama_a_google(monkeypatch, maestro):
    monkeypatch.setattr(config, "RUTAS_PROVIDER", "google")
    monkeypatch.setattr(config, "GOOGLE_MAPS_API_KEY", None)
    monkeypatch.setattr(rutas.httpx, "post", lambda *a, **k: pytest.fail("no debería llamar"))
    assert rutas.medir(7, [3, 5]) == {}


def test_off_y_sedes_sin_coordenadas(monkeypatch, maestro):
    assert rutas.medir(6, [3]) == {}           # Various Locations: no hay desde dónde medir
    assert rutas.medir(7, [7, 6]) == {}        # la misma sede y una sin coordenadas no se piden
    monkeypatch.setattr(config, "RUTAS_PROVIDER", "off")
    assert rutas.medir(7, [3]) == {}


def test_fake_usa_lo_medido_sin_red(maestro):
    medido = rutas.medir(7, [3, 2])
    assert medido[3] == rutas.Medicion(14, medido[3].caminando_m, None)
    assert medido[2].caminando_min is None     # par estimado por línea recta: no cuenta como medido


def test_google_camina_y_pide_transporte_solo_donde_no_hay_atajo(google):
    pedidos, respuestas = google
    respuestas += [httpx.Response(200, json=[_elemento(0, 14 * 60, 954), _elemento(1, 43 * 60, 3012),
                                             _elemento(2, 70 * 60, 4690)]),
                   httpx.Response(200, json=[_elemento(0, 20 * 60, 5000)])]
    medido = rutas.medir(7, [3, 5, 1, 3], MARTES_11)
    assert medido == {3: rutas.Medicion(14, 954, None), 5: rutas.Medicion(43, 3012, None),
                      1: rutas.Medicion(70, 4690, 20)}
    caminando, transporte = pedidos
    assert caminando["json"]["travelMode"] == "WALK" and len(caminando["json"]["destinations"]) == 3
    assert transporte["json"]["travelMode"] == "TRANSIT" and len(transporte["json"]["destinations"]) == 1  # solo Allegiant
    assert caminando["headers"]["X-Goog-Api-Key"] == CLAVE                     # la clave va en el header, no en la URL
    assert CLAVE not in caminando["url"]
    assert caminando["headers"]["Referer"] == "https://reinventar.app/"


def test_google_falla_cae_a_lo_de_siempre_sin_loguear_la_clave(google, caplog):
    _, respuestas = google
    respuestas += [httpx.Response(403, json={"error": {"message": f"API key {CLAVE} not valid"}})]
    with caplog.at_level(logging.WARNING, logger="reinventar.rutas"):
        assert rutas.medir(7, [5]) == {}
    assert "403" in caplog.text and CLAVE not in caplog.text
    assert rutas.medir(7, [5]) == {}           # durante la pausa no se insiste (no quedan respuestas para dar)


LEJOS = [_elemento(0, 70 * 60, 4690)]   # Venetian → Allegiant: lejos y sin atajo, pide transporte público


def test_si_falla_transporte_publico_a_pie_sigue_andando(google):
    pedidos, respuestas = google
    respuestas += [httpx.Response(200, json=LEJOS), httpx.Response(500, json={}), httpx.Response(200, json=LEJOS)]
    assert rutas.medir(7, [1]) == {1: rutas.Medicion(70, 4690, None)}
    assert rutas.medir(7, [1]) == {1: rutas.Medicion(70, 4690, None)}     # a pie sigue; transporte, en pausa
    assert [p["json"]["travelMode"] for p in pedidos] == ["WALK", "TRANSIT", "WALK"]


@pytest.mark.parametrize("respuesta", [httpx.Response(200, json={"error": "no es una lista"}),
                                       httpx.Response(200, content=b"<html>no es JSON</html>"),
                                       httpx.Response(200, json=["no es un elemento"])])
def test_200_con_cuerpo_invalido_cae_a_lo_de_siempre_y_pausa(google, respuesta):
    pedidos, respuestas = google
    respuestas.append(respuesta)
    assert rutas.medir(7, [5]) == {}
    assert rutas.medir(7, [5]) == {}           # en pausa: no se vuelve a pedir
    assert len(pedidos) == 1


def test_timeout_chico_por_fase():
    assert rutas.TIMEOUT.connect <= 1.5 and rutas.TIMEOUT.read <= 2.5


def test_a_pie_lento_saltea_transporte_publico_y_pausa(google, monkeypatch):
    pedidos, respuestas = google
    reloj = [1000.0]
    monkeypatch.setattr(rutas.time, "monotonic", lambda: reloj[0])
    post = rutas.httpx.post

    def lento(*a, **k):
        reloj[0] += rutas.PRESUPUESTO_S + 1
        return post(*a, **k)

    monkeypatch.setattr(rutas.httpx, "post", lento)
    respuestas.append(httpx.Response(200, json=LEJOS))
    assert rutas.medir(7, [1]) == {1: rutas.Medicion(70, 4690, None)}     # se usa, pero sin transporte público
    assert [p["json"]["travelMode"] for p in pedidos] == ["WALK"]
    assert rutas.medir(7, [1]) == {}                                      # y a pie queda en pausa un minuto
    assert len(pedidos) == 1


def test_google_sin_conexion(google):
    _, respuestas = google
    respuestas += [httpx.ConnectTimeout("timeout")]
    assert rutas.medir(7, [5]) == {}


def _alternativa(code, sede, minutos, misma_sede=False, estimado=False):
    return {"code": code, "base": code, "title": code, "start": "14:30", "minutos": minutos, "estimado": estimado,
            "misma_sede": misma_sede, "en_curso": False, "venue": {"hotel": sede, "detail": "Level 2"}}


def test_con_rutas_agrega_la_recomendacion_y_el_tiempo_real(google):
    _, respuestas = google
    respuestas += [httpx.Response(200, json=[_elemento(0, 12 * 60, 900), _elemento(1, 45 * 60, 3000)])]
    origen = {"base": "LLENA", "day": "2026-12-01", "venue": {"hotel": "Venetian", "detail": "Level 2"}}
    out = lleno_alternativas.con_rutas(origen, [_alternativa("WYNN", "Wynn/Encore", 14, estimado=True),
                                                _alternativa("MGM", "MGM Grand", 43),
                                                _alternativa("MISMA", "Venetian", 5, misma_sede=True)])
    assert [(a["code"], a["minutos"], a["estimado"], a["ruta"]) for a in out] == [
        ("WYNN", 12, False, rutas.atajo_fijo("Venetian", "Wynn/Encore", 12)),
        ("MGM", 45, False, rutas.TEXTO_SHUTTLE),
        ("MISMA", 5, False, None)]


def test_con_rutas_sin_google_deja_los_minutos_de_siempre(monkeypatch, maestro):
    monkeypatch.setattr(config, "RUTAS_PROVIDER", "off")
    origen = {"base": "LLENA", "day": "2026-12-01", "venue": {"hotel": "Venetian"}}
    [a] = lleno_alternativas.con_rutas(origen, [_alternativa("MGM", "MGM Grand", 43, estimado=True)])
    assert (a["minutos"], a["estimado"], a["ruta"]) == (43, True, rutas.TEXTO_SHUTTLE)


@pytest.mark.parametrize("dia, inicio", [("2026-12-03", "18:30"),   # jueves: el shuttle termina a las 17:45
                                         ("2026-12-04", "10:00"),   # viernes: solo Venetian y Wynn/Encore
                                         ("2026-12-01", "22:00")])  # martes de noche
def test_con_rutas_sin_shuttle_a_esa_hora_no_lo_ofrece(monkeypatch, maestro, dia, inicio):
    monkeypatch.setattr(config, "RUTAS_PROVIDER", "off")
    origen = {"base": "LLENA", "day": dia, "venue": {"hotel": "Venetian"}}
    [a] = lleno_alternativas.con_rutas(origen, [{**_alternativa("MGM", "MGM Grand", 43), "start": inicio}])
    assert a["ruta"] is None

