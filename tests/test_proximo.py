"""«Próximo» del banner de estado: ventanas de vuelo, hotel y charla, desempates, husos, cancelado y el endpoint (que
solo lee la base y usa la hora de la app). Sin red: AeroDataBox nunca se consulta."""
import datetime as dt

import pytest
from fastapi.testclient import TestClient

from app import db, proximo, sandbox, vuelos
from app import viajes_api as api
from app.main import app
from tests.conftest import TEST_ADMIN, TEST_ADMIN_PASSWORD, TEST_USER, login_headers

LV = sandbox.EVENT_TZ
BUE = "America/Argentina/Buenos_Aires"


def _lv(texto):
    return dt.datetime.fromisoformat(texto).replace(tzinfo=LV)


def _vuelo(id_="v1", **kw):
    # sale martes 1/12 13:05 de Las Vegas
    return {"id": id_, "numero": "UA1355", "fecha": "2026-12-01", "hora": "13:05", "zona": "America/Los_Angeles",
            "salida_utc": None, "demora_min": None, "puerta": None, "estado": None, "destino_nombre": None,
            "destino_iata": None, **kw}


def _hotel(id_="h1", **kw):
    return {"id": id_, "nombre": "Venetian", "direccion": "3355 S Las Vegas Blvd", "zona": "America/Los_Angeles",
            "checkin": "2026-11-29T15:00", "checkout": "2026-12-04T11:00", **kw}


def _plan(start="14:30", date="2026-12-01", **kw):
    nxt = {"start": start, "title": "Agentes en producción", "code": "ARC407", "base": "ARC407", "kind": "talk",
           "venue": {"hotel": "Venetian", "detail": "Sala Lido 3"}, **kw}
    return {"date": date, "next": nxt}


# ---------- vuelo ----------

def test_el_vuelo_se_ve_desde_12_h_antes_hasta_que_sale():
    v = _vuelo(destino_nombre="Houston", puerta="D12")

    assert proximo.elegir([v], [], None, _lv("2026-12-01T01:04")) is None
    p = proximo.elegir([v], [], None, _lv("2026-12-01T01:05"))
    assert p["tipo"] == "vuelo" and p["titulo"] == "UA1355 a Houston" and p["hora"] == "13:05"
    assert p["detalle"] == "puerta D12" and p["url"] == "#/viajes/vuelo/v1" and p["tono"] == "info"
    assert proximo.elegir([v], [], None, _lv("2026-12-01T13:05")) is None


def test_el_vuelo_demorado_usa_la_salida_revisada():
    salida = dt.datetime(2026, 12, 1, 21, 5, tzinfo=dt.UTC).timestamp()   # 13:05 de Las Vegas
    v = _vuelo(salida_utc=salida, demora_min=20, destino_iata="IAH")

    p = proximo.elegir([v], [], None, _lv("2026-12-01T13:10"))
    assert p["hora"] == "13:25" and p["demora_min"] == 20 and p["titulo"] == "UA1355 a IAH"
    assert proximo.elegir([v], [], None, _lv("2026-12-01T13:25")) is None


def test_el_vuelo_cancelado_se_muestra_con_tono_de_error():
    p = proximo.elegir([_vuelo(estado="Canceled")], [], None, _lv("2026-12-01T10:00"))

    assert p["cancelado"] is True and p["tono"] == "error"


def test_la_hora_del_vuelo_es_la_de_su_zona_y_se_compara_en_utc():
    # sale 18:00 de Buenos Aires = 13:00 de Las Vegas: le gana a la charla de las 13:30 de Las Vegas
    v = _vuelo(numero="AR1302", fecha="2026-12-01", hora="18:00", zona=BUE)

    p = proximo.elegir([v], [], _plan("13:30"), _lv("2026-12-01T12:00"))
    assert p["tipo"] == "vuelo" and p["hora"] == "18:00"
    assert p["inicio"] == "2026-12-01T21:00:00+00:00"
    assert proximo.elegir([v], [], _plan("12:50"), _lv("2026-12-01T12:00"))["tipo"] == "charla"


def test_un_vuelo_sin_hora_no_aparece():
    assert proximo.elegir([_vuelo(hora=None)], [], None, _lv("2026-12-01T10:00")) is None


# ---------- hotel ----------

def test_check_in_desde_3_h_antes_y_check_out_desde_2_h_antes():
    h = _hotel()

    assert proximo.elegir([], [h], None, _lv("2026-11-29T11:59")) is None
    p = proximo.elegir([], [h], None, _lv("2026-11-29T12:00"))
    assert p["titulo"] == "Check-in en Venetian" and p["hora"] == "15:00" and p["url"] == "#/viajes/hotel/h1"
    assert p["detalle"] == "3355 S Las Vegas Blvd"
    assert proximo.elegir([], [h], None, _lv("2026-12-04T08:59")) is None
    assert proximo.elegir([], [h], None, _lv("2026-12-04T09:00"))["titulo"] == "Check-out de Venetian"
    assert proximo.elegir([], [h], None, _lv("2026-12-04T11:00")) is None


def test_la_ventana_del_check_in_es_la_de_su_aviso():
    assert proximo.CHECKIN_HOTEL_ANTES_H == proximo.viajes_avisos.CHECKIN_HOTEL_ANTES_H == 3


# ---------- charla ----------

def test_la_charla_que_sigue_desde_2_h_antes():
    assert proximo.elegir([], [], _plan(), _lv("2026-12-01T12:29")) is None
    p = proximo.elegir([], [], _plan(), _lv("2026-12-01T12:30"))
    assert p == {"tipo": "charla", "titulo": "Agentes en producción", "hora": "14:30", "detalle": "Venetian · Sala Lido 3",
                 "url": "#/charla/ARC407", "tono": "info", "inicio": "2026-12-01T22:30:00+00:00"}


@pytest.mark.parametrize(("extra", "url"), [
    ({"kind": "event", "code": "ev 1"}, "#/evento/ev%201"),
    ({"kind": "show", "show": "o-show"}, "#/show/o-show"),
    ({"kind": "mine"}, "#/itinerario"),
])
def test_eventos_shows_y_eventos_propios_llevan_a_su_pantalla(extra, url):
    assert proximo.elegir([], [], _plan(**extra), _lv("2026-12-01T13:00"))["url"] == url


def test_sin_plan_o_con_datos_raros_no_rompe():
    ahora = _lv("2026-12-01T13:00")
    assert proximo.elegir([], [], {"date": "2026-12-01", "next": None}, ahora) is None
    assert proximo.elegir([], [], _plan(start="25:99"), ahora) is None
    assert proximo.elegir([], [], _plan(venue=None), ahora)["detalle"] is None


# ---------- desempates ----------

def test_gana_el_que_empieza_antes():
    ahora = _lv("2026-12-01T12:00")
    assert proximo.elegir([_vuelo()], [], _plan("13:00"), ahora)["tipo"] == "charla"
    assert proximo.elegir([_vuelo()], [], _plan("13:30"), ahora)["tipo"] == "vuelo"


def test_a_igual_hora_vuelo_le_gana_a_hotel_y_hotel_a_charla():
    ahora = _lv("2026-12-01T12:00")
    hotel = _hotel(checkin="2026-12-01T13:05", checkout="2026-12-02T11:00")

    assert proximo.elegir([_vuelo()], [hotel], _plan("13:05"), ahora)["tipo"] == "vuelo"
    assert proximo.elegir([], [hotel], _plan("13:05"), ahora)["tipo"] == "hotel"


# ---------- endpoint ----------

@pytest.fixture
def cli(monkeypatch):
    monkeypatch.setattr(api.itinerary, "get_current", lambda u: {"days": [
        {"day": "2026-12-01", "sessions": [{"start": "14:30", "title": "Agentes en producción", "code": "ARC407",
                                            "base": "ARC407", "type": "Breakout session"}]}]})
    monkeypatch.setattr(vuelos.httpx, "get", lambda *a, **k: pytest.fail("«Próximo» no consulta AeroDataBox"))
    with TestClient(app) as c:
        c.H = login_headers(c)
        c.H2 = login_headers(c, TEST_ADMIN, TEST_ADMIN_PASSWORD)
        _limpiar()
        yield c
        _limpiar()


def _limpiar():
    with db.conn() as c:
        for t in ("viajes_vuelos", "viajes_hoteles"):
            c.execute(f"DELETE FROM {t} WHERE username IN (%s,%s)", (TEST_USER, TEST_ADMIN))


def _a_las(monkeypatch, texto):
    monkeypatch.setattr(sandbox, "ahora", lambda tz=LV: _lv(texto).astimezone(tz))


def test_el_endpoint_devuelve_lo_proximo_de_cada_persona(cli, monkeypatch):
    _a_las(monkeypatch, "2026-12-01T12:40")
    vuelos.agregar_vuelo(TEST_USER, "UA1355", "United", "2026-12-01", "13:05", "America/Los_Angeles")

    mio = cli.get("/api/viajes/proximo", headers=cli.H)
    otro = cli.get("/api/viajes/proximo", headers=cli.H2)

    assert mio.status_code == 200
    assert mio.json()["tipo"] == "vuelo" and mio.json()["titulo"] == "UA1355"
    assert otro.json()["tipo"] == "charla"   # el itinerario simulado es el mismo; el vuelo, solo de TEST_USER


def test_el_endpoint_usa_la_hora_de_la_app_y_devuelve_null_si_no_hay_nada(cli, monkeypatch):
    _a_las(monkeypatch, "2026-12-01T05:00")
    assert cli.get("/api/viajes/proximo", headers=cli.H).json() is None
    _a_las(monkeypatch, "2026-12-01T13:00")   # p. ej. el reloj simulado del modo prueba
    assert cli.get("/api/viajes/proximo", headers=cli.H).json()["url"] == "#/charla/ARC407"


def test_sin_itinerario_sigue_con_vuelos_y_hoteles(cli, monkeypatch):
    def falla(u):
        raise RuntimeError("sin catálogo")

    monkeypatch.setattr(api.itinerary, "get_current", falla)
    _a_las(monkeypatch, "2026-11-29T13:00")
    vuelos.agregar_hotel(TEST_USER, "Wynn", "", "2026-11-29T15:00", "2026-12-04T11:00", "America/Los_Angeles")

    assert cli.get("/api/viajes/proximo", headers=cli.H).json()["titulo"] == "Check-in en Wynn"


def test_el_endpoint_pide_sesion(cli):
    assert cli.get("/api/viajes/proximo").status_code == 401


def test_la_sala_de_la_charla_va_corta_en_el_banner():
    plan = _plan(venue={"hotel": "Wynn/Encore", "detail": "Upper Convention Promenade · Cristal 2 · Content Hub"})

    p = proximo.elegir([], [], plan, _lv("2026-12-01T14:00"))

    assert p["detalle"] == "Wynn/Encore · Upper Convention Promenade"
