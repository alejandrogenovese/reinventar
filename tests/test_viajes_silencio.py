"""Vuelos y hoteles: vuelo sin hora, ventana de consulta hasta la salida demorada, intervalo adaptativo, contador diario
que sobrevive a un reinicio, y las ventanas frente al horario de silencio (22 a 7 de Las Vegas). Sin red."""
import datetime as dt

import pytest
from fastapi.testclient import TestClient

from app import config, db, sandbox, vuelos
from app import viajes_avisos as va
from app.main import app
from tests.test_viajes_avisos import _ahora, _estado, _hotel, _vuelo

SALIDA_UTC = dt.datetime(2026, 11, 29, 0, 5, tzinfo=dt.UTC)   # 21:05 de Buenos Aires = 16:05 de Las Vegas del 28/11


def _estado_de(v, now, res, ts=1_000_000.0):
    pedidos = []

    def consulta(numero, fecha):
        pedidos.append(numero)
        return res

    avisos, guardar, diferidos = va.estado([v], now, consulta, ts)
    return avisos, dict(guardar), pedidos


# ---------- vuelo sin hora ----------

def test_un_vuelo_sin_hora_se_consulta_durante_su_dia():
    v = _vuelo(hora=None)

    _, guardar, pedidos = _estado_de(v, _ahora("2026-11-28T10:00"), _estado(0))

    assert pedidos == ["AR1302"]
    assert guardar["v1"]["salida_utc"] == _estado()["salida_utc"]   # con la hora real ya se calcula todo lo demás


def test_un_vuelo_sin_hora_no_se_consulta_otro_dia():
    v = _vuelo(hora=None)

    assert _estado_de(v, _ahora("2026-11-26T10:00"), _estado(0))[2] == []
    assert _estado_de(v, _ahora("2026-11-30T10:00"), _estado(0))[2] == []


# ---------- hasta la salida demorada ----------

def test_se_sigue_consultando_hasta_la_salida_demorada_no_la_programada():
    v = _vuelo(salida_utc=SALIDA_UTC.timestamp(), demora_min=90, consultado_en=0)

    # 16:05 programada; 16:50 con 90 min de demora sale a las 17:35: sigue en ventana
    assert _estado_de(v, _ahora("2026-11-28T16:50"), _estado(90))[2] == ["AR1302"]
    assert _estado_de(v, _ahora("2026-11-28T17:40"), _estado(90))[2] == []


def test_sin_demora_corta_en_la_hora_programada():
    v = _vuelo(salida_utc=SALIDA_UTC.timestamp(), demora_min=0, consultado_en=0)

    assert _estado_de(v, _ahora("2026-11-28T16:10"), _estado(0))[2] == []


# ---------- intervalo adaptativo ----------

@pytest.mark.parametrize("falta_h, minutos", [(20, 120), (8, 60), (4, 30), (1, 15)])
def test_cuanto_mas_cerca_la_salida_mas_seguido_se_consulta(falta_h, minutos):
    assert va.intervalo_s(dt.timedelta(hours=falta_h)) == minutos * 60


def test_lejos_de_la_salida_no_se_consulta_cada_20_minutos():
    v = _vuelo(consultado_en=1_000_000.0 - 30 * 60)   # hace 30 min; faltan ~20 h

    assert _estado_de(v, _ahora("2026-11-27T20:00"), _estado(0))[2] == []


# ---------- contador diario que sobrevive al reinicio ----------

@pytest.fixture
def _contador_limpio(monkeypatch):
    monkeypatch.setattr(config, "AERODATABOX_TOPE_DIARIO", 3)
    with TestClient(app):   # al arrancar crea las tablas
        with sandbox.real(), db.conn() as c:
            c.execute("DELETE FROM push_sent WHERE username=%s", (vuelos.USUARIO_CONTADOR,))
        vuelos.reiniciar_consultas()
        yield
        with sandbox.real(), db.conn() as c:
            c.execute("DELETE FROM push_sent WHERE username=%s", (vuelos.USUARIO_CONTADOR,))
        vuelos.reiniciar_consultas()


def test_un_reinicio_no_pone_en_cero_el_contador_del_dia(_contador_limpio, monkeypatch):
    monkeypatch.setattr(vuelos, "_persistir_contador", True)
    assert [vuelos._reservar_cupo(None) for _ in range(2)] == [True, True]

    vuelos._dia.update(fecha=None, n=0)   # lo que pasa en un redeploy: la memoria vuelve a cero

    assert vuelos._reservar_cupo(None) is True
    assert vuelos._reservar_cupo(None) is False   # ya se habían gastado 3 de 3


# ---------- silencio ----------

def test_el_check_in_web_de_madrugada_se_demora_si_falta_mucho():
    v = _vuelo(salida_utc=SALIDA_UTC.timestamp())   # sale 16:05 LV: 23:00 del día anterior son 17 h antes

    assert va.checkin_web([v], _ahora("2026-11-27T23:00")) == []


def test_el_check_in_web_sale_de_noche_si_falta_poco_para_la_salida():
    v = _vuelo(salida_utc=dt.datetime(2026, 11, 28, 9, 0, tzinfo=dt.UTC).timestamp())   # sale 01:00 LV

    [(key, _)] = va.checkin_web([v], _ahora("2026-11-27T22:30"))   # faltan 2 h 30 min

    assert key == "vcheckin:v1"


def test_una_ventana_de_check_in_de_hotel_entera_en_silencio_avisa_a_la_manana():
    h = _hotel(checkin="2026-11-29T06:00")   # la ventana (3 a 6) cae toda en silencio

    assert va.hoteles([h], _ahora("2026-11-29T04:00")) == []
    assert [k for k, _ in va.hoteles([h], _ahora("2026-11-29T07:30"))] == ["hin:h1"]
    assert va.hoteles([h], _ahora("2026-11-29T11:00")) == []


def test_el_check_out_no_sale_antes_del_check_in_en_una_estadia_de_una_noche():
    h = _hotel(checkin="2026-11-29T21:00", checkout="2026-11-30T08:00")

    antes = va.hoteles([h], _ahora("2026-11-29T19:30"))

    assert [k for k, _ in antes] == ["hin:h1"]   # ya pasaron las 19 pero todavía no entró al hotel


def test_hoteles_no_avisa_dentro_del_silencio_si_hay_horas_habiles_en_la_ventana():
    h = _hotel(checkin="2026-11-29T23:30")   # ventana 20:30 a 23:30: hay un tramo hábil

    assert [k for k, _ in va.hoteles([h], _ahora("2026-11-29T21:00"))] == ["hin:h1"]
    assert va.hoteles([h], _ahora("2026-11-29T22:30")) == []   # ya es de noche: no se avisa
