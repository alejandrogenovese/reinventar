"""Anuncios sin reserva en Inicio: criterio, filtro por hora y día, y el endpoint. Catálogo simulado (corre en CI)."""
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from app import anuncios, catalog, explore, sandbox
from app.main import app
from tests.conftest import login_headers

LUNES, MARTES, MIERCOLES = "2026-11-30", "2026-12-01", "2026-12-02"


def _charla(base, tipo, titulo="Charla", horarios=(), *, newlaunch=False, sponsored=False):
    return {"base": base, "title": titulo, "type": tipo, "newlaunch": newlaunch, "sponsored": sponsored,
            "instances": [{"c": c, "d": d, "st": st, "en": en, "v": "Venetian|Level 2|Venetian Theatre", "seats": 100,
                           "walk": walk} for c, d, st, en, walk in horarios], "people": []}


KEYNOTE = _charla("KEY002", "Keynote", "CEO Keynote", [("KEY002", MARTES, "08:30", "10:30", True)])
MAINSTAGE = _charla("SNR317", "Mainstage", "A leader's guide", [("SNR317", MARTES, "12:00", "13:00", True)])
LANZAMIENTO = _charla("CON346", "Breakout session", "ECR", [("CON346", MARTES, "11:30", "12:30", True)], newlaunch=True)
NOVEDADES = _charla("STG346", "Breakout session", "What's new with Amazon S3", [("STG346", MARTES, "13:00", "14:00", True)])
LIGHTNING = _charla("SVS209", "Lightning talk", "Web apps", [("SVS209", MARTES, "11:30", "11:50", True)], newlaunch=True)
CHALK_LANZAMIENTO = _charla("DAT400", "Chalk talk", "Chalk", [("DAT400", MARTES, "10:00", "11:00", False)], newlaunch=True)
CON_RESERVA = _charla("NET300", "Breakout session", "What's new in networking", [("NET300", MARTES, "15:00", "16:00", False)])
SPONSOREADA = _charla("PEX100", "Breakout session", "[NEW LAUNCH] Sponsor", [("PEX100", MARTES, "15:00", "16:00", True)],
                      sponsored=True)
COMUN = _charla("ARC200", "Breakout session", "Arquitectura", [("ARC200", MARTES, "10:00", "11:00", True)])
DEL_LUNES = _charla("KEY001", "Keynote", "Developer Keynote", [("KEY001", LUNES, "19:30", "20:45", True)])
DEL_MIERCOLES = _charla("SNR321", "Mainstage", "Security", [("SNR321", MIERCOLES, "10:30", "11:30", True)])

CATALOGO = [KEYNOTE, MAINSTAGE, LANZAMIENTO, NOVEDADES, LIGHTNING, CHALK_LANZAMIENTO, CON_RESERVA, SPONSOREADA, COMUN,
            DEL_LUNES, DEL_MIERCOLES]


@pytest.fixture
def catalogo(monkeypatch):
    monkeypatch.setattr(catalog, "_sessions", CATALOGO)
    return CATALOGO


def _nivel(charla):
    return anuncios.nivel(charla, charla["instances"][0])


def _codigos(resultado):
    return [c["code"] for c in resultado["items"]]


# --- criterio ---------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("charla,esperado", [
    (KEYNOTE, anuncios.NIVEL_KEYNOTE), (MAINSTAGE, anuncios.NIVEL_MAINSTAGE),
    (LANZAMIENTO, anuncios.NIVEL_LANZAMIENTO), (LIGHTNING, anuncios.NIVEL_LANZAMIENTO),
    (NOVEDADES, anuncios.NIVEL_NOVEDADES),
], ids=["keynote", "mainstage", "lanzamiento", "lightning", "whats-new"])
def test_los_anuncios_walk_up_entran_con_su_nivel(charla, esperado):
    assert _nivel(charla) == esperado


@pytest.mark.parametrize("charla", [CHALK_LANZAMIENTO, CON_RESERVA, SPONSOREADA, COMUN],
                         ids=["chalk-con-reserva", "breakout-con-reserva", "sponsoreada", "breakout-comun"])
def test_no_entran_las_reservables_las_sponsoreadas_ni_las_comunes(charla):
    assert _nivel(charla) is None


def test_el_titulo_se_compara_sin_importar_mayusculas():
    charla = _charla("X1", "Breakout session", "[New Launch] Coming soon!", [("X1", MARTES, "09:00", "10:00", True)])
    assert _nivel(charla) == anuncios.NIVEL_NOVEDADES


# --- del día ----------------------------------------------------------------------------------------------------

def test_a_media_manana_muestra_lo_que_queda_hoy_en_orden_de_hora(catalogo):
    r = anuncios.del_dia(datetime(2026, 12, 1, 11, 10), set())

    assert r["day"] == MARTES and r["is_today"]
    # KEY002 sigue en curso pero empezó hace 2 h 40 min: ya no se muestra.
    assert _codigos(r) == ["CON346", "SVS209", "SNR317", "STG346"]
    assert r["total"] == 4


def test_la_que_empezo_hace_5_min_sigue_y_la_de_hace_15_no(catalogo):
    a_los_5 = anuncios.del_dia(datetime(2026, 12, 1, 11, 35), set())
    a_los_15 = anuncios.del_dia(datetime(2026, 12, 1, 11, 45), set())

    assert "CON346" in _codigos(a_los_5)
    assert "CON346" not in _codigos(a_los_15)


def test_grabar_solo_si_esta_en_curso(catalogo):
    r = anuncios.del_dia(datetime(2026, 12, 1, 11, 35), set())
    por_codigo = {c["code"]: c for c in r["items"]}

    assert por_codigo["CON346"]["en_curso"] is True
    assert por_codigo["SNR317"]["en_curso"] is False


def test_la_tarjeta_trae_fin_cola_y_tipo_de_grabacion(catalogo):
    keynote = anuncios.del_dia(datetime(2026, 12, 1, 7, 0), set())["items"][0]

    assert keynote["code"] == "KEY002" and keynote["nivel"] == anuncios.NIVEL_KEYNOTE
    assert keynote["end"] == "10:30"
    assert keynote["cola_desde"] == "08:00"
    assert keynote["recording_kind"] == "Keynote"
    assert keynote["walk_in"] is True


def test_sin_fin_en_el_catalogo_se_estima_por_tipo(monkeypatch):
    sin_fin = _charla("SVS1", "Lightning talk", "x", [("SVS1", MARTES, "11:30", None, True)], newlaunch=True)
    monkeypatch.setattr(catalog, "_sessions", [sin_fin])

    assert anuncios.del_dia(datetime(2026, 12, 1, 9, 0), set())["items"][0]["end"] == "11:50"


def test_respeta_el_limite_y_devuelve_el_total(catalogo):
    r = anuncios.del_dia(datetime(2026, 12, 1, 7, 0), set(), limite=2)

    assert _codigos(r) == ["KEY002", "CON346"]
    assert r["total"] == 5


def test_no_repite_lo_que_ya_esta_en_el_itinerario(catalogo):
    r = anuncios.del_dia(datetime(2026, 12, 1, 11, 10), {"SNR317", "CON346"})

    assert _codigos(r) == ["SVS209", "STG346"]
    assert r["total"] == 2


def test_antes_del_evento_muestra_el_primer_dia_con_anuncios(catalogo):
    r = anuncios.del_dia(datetime(2026, 11, 13, 10, 0), set())

    assert r["day"] == LUNES and not r["is_today"]
    assert _codigos(r) == ["KEY001"]
    assert r["items"][0]["en_curso"] is False


def test_de_noche_muestra_los_del_dia_siguiente(catalogo):
    r = anuncios.del_dia(datetime(2026, 12, 1, 20, 0), set())

    assert r["day"] == MIERCOLES and not r["is_today"]
    assert _codigos(r) == ["SNR321"]


def test_despues_del_ultimo_dia_no_hay_nada(catalogo):
    assert anuncios.del_dia(datetime(2026, 12, 5, 9, 0), set()) == {"day": None, "is_today": False, "items": [], "total": 0}


# --- filtro de Buscar -------------------------------------------------------------------------------------------

def test_buscar_tiene_el_filtro_anuncios(catalogo):
    r = explore.explore({"anuncio": {anuncios.FILTRO_BUSCAR}, "dia": {MARTES}}, limit=50)

    assert {c["code"] for c in r["results"]} == {"KEY002", "SNR317", "CON346", "STG346", "SVS209"}
    assert {"value": anuncios.FILTRO_BUSCAR, "count": 5} in r["facets"]["anuncio"]


# --- endpoint ---------------------------------------------------------------------------------------------------

def test_el_endpoint_pide_login_y_respeta_el_reloj_simulado(monkeypatch):
    with TestClient(app) as c:
        assert c.get("/api/anuncios").status_code == 401
        headers = login_headers(c)
        monkeypatch.setattr(catalog, "_sessions", CATALOGO)  # después del arranque, que carga el catálogo real si está
        monkeypatch.setattr(sandbox, "ahora", lambda tz=None: datetime(2026, 12, 1, 11, 10, tzinfo=tz))

        r = c.get("/api/anuncios", headers=headers)

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["day"] == MARTES and body["is_today"] is True
    assert [i["code"] for i in body["items"]] == ["CON346", "SVS209", "SNR317", "STG346"]
    assert {"nivel", "end", "cola_desde", "en_curso", "venue"} <= set(body["items"][0])
