"""Recomendador de funciones de un show según la agenda del usuario (puro) y su endpoint /api/shows/{id}/cuando."""
import pytest
from fastapi.testclient import TestClient

from app import shows_api
from app.main import app
from app.shows_recomendador import MARGEN_SIN_UBICACION_MIN, recomendar
from tests.conftest import login_headers

# Venetian y MGM están a ~2 km (unos 40 min caminando con rodeo); la otra punta del Venetian, a pocos metros.
VENETIAN = {"lat": 36.1215, "lng": -115.1697}
MGM = {"lat": 36.1029, "lng": -115.1699}
VENETIAN_CERCA = {"lat": 36.1216, "lng": -115.1698}


def funcion(code, day, start, end, venue=None, **extra):
    return {"code": code, "day": day, "start": start, "end": end, "venue": venue or MGM, "cancelled": False,
            "status": "onsale", "price_from": None, **extra}


def charla(title, day, start, end, venue=None):
    return {"code": f"c-{title}", "title": title, "day": day, "start": start, "end": end, "venue": venue or VENETIAN}


def por_codigo(sugerencias):
    return {s["code"]: s for s in sugerencias}


def test_sin_agenda_todas_son_libres_y_sin_nada_ese_dia():
    r = recomendar([funcion("f1", "2026-12-01", "20:00", "22:00")], [])

    assert r[0]["estado"] == "libre"
    assert "nada" in r[0]["razon"].lower()


def test_libre_cuando_llega_con_margen_y_explica_el_traslado():
    agenda = [charla("Keynote", "2026-12-01", "14:00", "16:00")]

    r = recomendar([funcion("f1", "2026-12-01", "20:00", "22:00")], agenda)

    assert r[0]["estado"] == "libre"
    assert "«Keynote»" in r[0]["razon"] and "min caminando" in r[0]["razon"] and "16:00" in r[0]["razon"]


def test_choca_si_se_superpone_con_algo_del_itinerario():
    agenda = [charla("Fiesta", "2026-12-01", "21:00", "23:00")]

    r = recomendar([funcion("f1", "2026-12-01", "20:00", "22:00")], agenda)

    assert r[0]["estado"] == "choca"
    assert "«Fiesta»" in r[0]["razon"]


def test_justo_si_no_se_superpone_pero_el_traslado_no_alcanza():
    agenda = [charla("Workshop", "2026-12-01", "18:00", "19:50")]

    r = recomendar([funcion("f1", "2026-12-01", "20:00", "22:00")], agenda)

    assert r[0]["estado"] == "justo"
    assert "«Workshop»" in r[0]["razon"]


def test_justo_tambien_por_la_vuelta_a_lo_que_viene_despues():
    agenda = [charla("Cena", "2026-12-01", "22:05", "23:30")]

    r = recomendar([funcion("f1", "2026-12-01", "20:00", "22:00")], agenda)

    assert r[0]["estado"] == "justo"
    assert "«Cena»" in r[0]["razon"]


def test_mismo_lugar_alcanza_con_poco_margen():
    agenda = [charla("Charla", "2026-12-01", "18:00", "19:50", venue=VENETIAN_CERCA)]

    r = recomendar([funcion("f1", "2026-12-01", "20:00", "22:00", venue=VENETIAN)], agenda)

    assert r[0]["estado"] == "libre"


def test_orden_libre_justo_choca_y_dentro_de_libre_gana_mas_holgura():
    agenda = [charla("A", "2026-12-02", "18:00", "19:50"), charla("B", "2026-12-03", "21:00", "23:00"),
              charla("C", "2026-12-04", "17:00", "18:40")]
    funciones = [
        funcion("choca", "2026-12-03", "20:00", "22:00"),
        funcion("justo", "2026-12-02", "20:00", "22:00"),
        funcion("libre-ajustada", "2026-12-04", "20:00", "22:00"),   # 80 min de aire, 40 de traslado
        funcion("libre-amplia", "2026-12-01", "20:00", "22:00"),     # sin nada ese día
    ]

    r = recomendar(funciones, agenda)

    assert [s["code"] for s in r] == ["libre-amplia", "libre-ajustada", "justo", "choca"]


def test_empate_se_resuelve_por_fecha_y_hora():
    r = recomendar([funcion("tarde", "2026-12-01", "22:00", "23:30"), funcion("temprano", "2026-12-01", "19:00", "20:30")], [])

    assert [s["code"] for s in r] == ["temprano", "tarde"]


def test_ignora_lo_que_pasa_otro_dia():
    agenda = [charla("Otro día", "2026-12-02", "19:00", "22:00")]

    r = recomendar([funcion("f1", "2026-12-01", "20:00", "22:00")], agenda)

    assert r[0]["estado"] == "libre"


def test_no_se_choca_con_su_propia_funcion_si_ya_esta_en_el_itinerario():
    propia = {**funcion("f1", "2026-12-01", "20:00", "22:00"), "title": "El show"}

    r = recomendar([funcion("f1", "2026-12-01", "20:00", "22:00")], [propia])

    assert r[0]["estado"] == "libre"
    assert r[0]["in_itinerary"] is True


def test_sin_ubicacion_usa_margen_fijo_y_lo_dice():
    sin_lugar = {"code": "c1", "title": "Charla", "day": "2026-12-01", "start": "18:00", "end": "19:50", "venue": {}}

    r = recomendar([funcion("f1", "2026-12-01", "20:00", "22:00")], [sin_lugar])

    assert MARGEN_SIN_UBICACION_MIN > 10
    assert r[0]["estado"] == "justo"
    assert "estimado" in r[0]["razon"]


def test_las_canceladas_no_se_sugieren():
    r = recomendar([funcion("f1", "2026-12-01", "20:00", "22:00", cancelled=True, status="canceled")], [])

    assert r == []


def test_sin_venta_va_al_final_de_su_grupo_y_avisa():
    r = recomendar([funcion("off", "2026-12-01", "19:00", "21:00", status="offsale"),
                    funcion("on", "2026-12-01", "21:00", "23:00")], [])

    assert [s["code"] for s in r] == ["on", "off"]
    assert por_codigo(r)["off"]["aviso"] == "Sin venta por ahora."
    assert por_codigo(r)["on"]["aviso"] is None


def test_precio_solo_si_ticketmaster_lo_trae_y_sin_inventar_disponibilidad():
    r = por_codigo(recomendar([funcion("con", "2026-12-01", "20:00", "22:00", price_from=99.0),
                               funcion("sin", "2026-12-02", "20:00", "22:00")], []))

    assert r["con"]["price_from"] == 99.0 and r["sin"]["price_from"] is None
    assert "pocas" not in str(r).lower()


def test_no_muta_las_entradas():
    funciones = [funcion("f1", "2026-12-01", "20:00", "22:00")]
    agenda = [charla("Keynote", "2026-12-01", "14:00", "16:00")]
    antes = (repr(funciones), repr(agenda))

    recomendar(funciones, agenda)

    assert (repr(funciones), repr(agenda)) == antes


# --- endpoint -----------------------------------------------------------------------------------
@pytest.fixture
def cli():
    with TestClient(app) as c:
        c.H = login_headers(c)
        yield c


@pytest.fixture
def show_falso(monkeypatch):
    s = {"id": "s1", "functions": [funcion("tm-A1", "2026-12-01", "20:00", "22:00"),
                                   funcion("tm-A2", "2026-12-02", "20:00", "22:00")]}
    monkeypatch.setattr(shows_api.shows, "habilitado", lambda: True)
    monkeypatch.setattr(shows_api.shows, "show", lambda id_show: s if id_show == "s1" else None)
    agenda = {"days": [{"day": "2026-12-01", "sessions": [charla("Fiesta", "2026-12-01", "21:00", "23:00")]}]}
    monkeypatch.setattr(shows_api.itinerary, "get_current", lambda username: agenda)


def test_endpoint_cuando_devuelve_las_sugerencias_ordenadas(cli, show_falso):
    r = cli.get("/api/shows/s1/cuando", headers=cli.H)

    assert r.status_code == 200
    cuerpo = r.json()
    assert cuerpo["id"] == "s1"
    assert [(s["code"], s["estado"]) for s in cuerpo["sugerencias"]] == [("tm-A2", "libre"), ("tm-A1", "choca")]


def test_endpoint_cuando_404_si_no_existe_y_401_sin_login(cli, show_falso):
    assert cli.get("/api/shows/nada/cuando", headers=cli.H).status_code == 404
    assert cli.get("/api/shows/s1/cuando").status_code == 401


def test_endpoint_cuando_404_con_shows_apagados(cli, show_falso, monkeypatch):
    monkeypatch.setattr(shows_api.shows, "habilitado", lambda: False)

    assert cli.get("/api/shows/s1/cuando", headers=cli.H).status_code == 404
