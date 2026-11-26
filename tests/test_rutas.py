"""Cómo ir entre sedes (app/rutas.py): atajos fijos, la recomendación corta y Routes API sin red (httpx.post simulado).

Con sedes y tiempos de prueba en memoria: no usa el catálogo y corre en CI."""
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


def test_shuttle_solo_si_es_lejos_y_hay_shuttle_entre_esas_sedes():
    assert rutas.atajo_fijo("MGM Grand", "Venetian", 43) == rutas.TEXTO_SHUTTLE
    assert rutas.atajo_fijo("Caesars Palace", "Wynn/Encore", 22) == rutas.TEXTO_SHUTTLE
    assert rutas.atajo_fijo("Caesars Palace", "Venetian", 13) is None           # cerca: se camina
    assert rutas.atajo_fijo("Caesars Forum", "Venetian", 40) is None            # sin shuttle entre estas dos (2025)
    assert rutas.atajo_fijo("Allegiant Stadium", "MGM Grand", 34) is None       # fuera del campus de charlas
    assert rutas.atajo_fijo("Venetian", "Venetian", 5) is None
    assert rutas.atajo_fijo(None, "Venetian", 30) is None


def test_atajos_tienen_fuente_publica():
    for atajo in rutas.ATAJOS:
        assert atajo.fuente.startswith("https://")
        assert len(atajo.sedes) == 2


def test_transporte_publico_solo_si_ahorra_bastante_y_no_hay_atajo():
    assert rutas.recomendar("Allegiant Stadium", "MGM Grand", 34, 15) == "o transporte público ~15 min"
    assert rutas.recomendar("Allegiant Stadium", "MGM Grand", 34, 28) is None    # ahorra poco
    assert rutas.recomendar("Allegiant Stadium", "MGM Grand", 34, None) is None
    assert rutas.recomendar("MGM Grand", "Venetian", 43, 10) == rutas.TEXTO_SHUTTLE  # el atajo fijo gana


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
    medido = rutas.medir(7, [3, 5, 1, 3])
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
    origen = {"base": "LLENA", "venue": {"hotel": "Venetian", "detail": "Level 2"}}
    out = lleno_alternativas.con_rutas(origen, [_alternativa("WYNN", "Wynn/Encore", 14, estimado=True),
                                                _alternativa("MGM", "MGM Grand", 43),
                                                _alternativa("MISMA", "Venetian", 5, misma_sede=True)])
    assert [(a["code"], a["minutos"], a["estimado"], a["ruta"]) for a in out] == [
        ("WYNN", 12, False, rutas.atajo_fijo("Venetian", "Wynn/Encore", 12)),
        ("MGM", 45, False, rutas.TEXTO_SHUTTLE),
        ("MISMA", 5, False, None)]


def test_con_rutas_sin_google_deja_los_minutos_de_siempre(monkeypatch, maestro):
    monkeypatch.setattr(config, "RUTAS_PROVIDER", "off")
    origen = {"base": "LLENA", "venue": {"hotel": "Venetian"}}
    [a] = lleno_alternativas.con_rutas(origen, [_alternativa("MGM", "MGM Grand", 43, estimado=True)])
    assert (a["minutos"], a["estimado"], a["ruta"]) == (43, True, rutas.TEXTO_SHUTTLE)

