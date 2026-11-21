"""Avisos de vuelos y hoteles: check-in web, hoteles, demora y puerta, deduplicación, preferencias, sin clave y
aislamiento por usuario. AeroDataBox y el envío push se simulan: no sale nada a la red."""
import datetime as dt
import time

import pytest
from fastapi.testclient import TestClient

from app import config, db, push, sandbox, vuelos
from app import viajes_avisos as va
from app.main import app
from tests.conftest import TEST_ADMIN, TEST_ADMIN_PASSWORD, TEST_USER, login_headers

BUE = "America/Argentina/Buenos_Aires"
LV = sandbox.EVENT_TZ


def _ahora(texto):
    """Hora de Las Vegas."""
    return dt.datetime.fromisoformat(texto).replace(tzinfo=LV)


def _vuelo(id_="v1", **kw):
    return {"id": id_, "numero": "AR1302", "aerolinea": "", "fecha": "2026-11-28", "hora": "21:05", "zona": BUE,
            "salida_utc": None, "demora_min": None, "puerta": None, "terminal": None, "estado": None,
            "consultado_en": None, **kw}


def _hotel(id_="h1", **kw):
    return {"id": id_, "nombre": "Venetian", "direccion": "3355 S Las Vegas Blvd", "zona": "America/Los_Angeles",
            "checkin": "2026-11-29T15:00", "checkout": "2026-12-04T11:00", **kw}


# Salida del vuelo: sáb 28/11 21:05 de Buenos Aires = 16:05 en Las Vegas (UTC-8 en invierno: 00:05Z del 29 = 16:05 del 28)
SALIDA_LV = "2026-11-28T16:05"


# ---------- check-in web ----------

def test_avisa_que_ya_se_puede_hacer_el_check_in_con_link_a_la_pantalla_del_vuelo():
    [(key, msg)] = va.checkin_web([_vuelo()], _ahora("2026-11-27T17:00"))

    assert key == "vcheckin:v1"
    assert msg["title"] == "Ya podés hacer el check-in de AR1302"
    assert msg["url"] == "/#/viajes/vuelo/v1"
    assert "vie 27/11" not in msg["body"] and "21:05" in msg["body"]


def test_no_avisa_antes_de_abrir_la_ventana_ni_despues_de_la_salida():
    assert va.checkin_web([_vuelo()], _ahora("2026-11-27T15:00")) == []   # abre 16:05 de Las Vegas
    assert va.checkin_web([_vuelo()], _ahora("2026-11-28T17:00")) == []   # ya salió


def test_la_ventana_de_una_aerolinea_de_48_h(monkeypatch):
    monkeypatch.setitem(vuelos.CHECKIN_WEB, "ZZ", {"horas": 48, "url": None})
    v = _vuelo(numero="ZZ9")

    assert va.checkin_web([v], _ahora("2026-11-26T17:00"))
    assert va.checkin_web([v], _ahora("2026-11-26T15:00")) == []


def test_el_vuelo_sin_hora_no_avisa_check_in():
    assert va.checkin_web([_vuelo(hora=None)], _ahora("2026-11-28T10:00")) == []


# ---------- hoteles ----------

def test_check_in_del_hotel_desde_3_horas_antes():
    assert va.hoteles([_hotel()], _ahora("2026-11-29T11:59")) == []
    [(key, msg)] = va.hoteles([_hotel()], _ahora("2026-11-29T12:00"))

    assert key == "hin:h1"
    assert msg["title"] == "Hoy hacés el check-in en Venetian"
    assert "15:00" in msg["body"] and "3355 S Las Vegas Blvd" in msg["body"]
    assert msg["url"] == "/#/viajes/hotel/h1"


def test_check_out_la_noche_anterior_desde_las_19():
    assert va.hoteles([_hotel()], _ahora("2026-12-03T18:59")) == []
    [(key, msg)] = va.hoteles([_hotel()], _ahora("2026-12-03T19:00"))

    assert key == "hout:h1"
    assert msg["title"] == "Mañana es el check-out de Venetian"
    assert "11:00" in msg["body"]


def test_no_avisa_el_check_in_una_vez_pasada_la_hora():
    assert va.hoteles([_hotel()], _ahora("2026-11-29T15:01")) == []


def test_el_check_out_sigue_pendiente_hasta_la_hora_de_salida():
    [(key, _)] = va.hoteles([_hotel()], _ahora("2026-12-04T08:00"))   # lo que se frenó por silencio sale a la mañana

    assert key == "hout:h1"
    assert va.hoteles([_hotel()], _ahora("2026-12-04T11:01")) == []


# ---------- estado: demora y puerta ----------

def _estado(demora=0, puerta=None, estado="Expected", salida_utc=dt.datetime(2026, 11, 29, 0, 5, tzinfo=dt.UTC)):
    return {"salida_utc": salida_utc.timestamp(), "demora_min": demora,
            "puerta": puerta, "terminal": None, "estado": estado}


def _correr(v, now, res, *, ts=1_000_000.0):
    pedidos = []

    def consulta(numero, fecha):
        pedidos.append((numero, fecha))
        return res

    avisos, updates, diferidos = va.estado([v], now, consulta, ts)
    todo = dict(updates)
    for id_, campos in diferidos.values():   # lo que se guarda cuando el aviso llega
        todo[id_] = {**todo[id_], **campos}
    return avisos, todo, pedidos


def test_no_consulta_antes_de_las_24_h():
    avisos, updates, pedidos = _correr(_vuelo(), _ahora("2026-11-27T10:00"), _estado(60))

    assert (avisos, pedidos) == ([], [])


def test_avisa_la_demora_y_guarda_la_base_para_no_repetirla():
    avisos, updates, pedidos = _correr(_vuelo(), _ahora("2026-11-28T08:00"), _estado(45))

    [(key, msg)] = avisos
    assert pedidos == [("AR1302", "2026-11-28")]
    assert key == "vdemora:v1:0>45"
    assert msg["title"] == "AR1302 sale 45 min más tarde"
    assert "21:50" in msg["body"]
    assert updates["v1"]["demora_min"] == 45 and updates["v1"]["consultado_en"] == 1_000_000.0

    # con la base guardada, la misma demora ya no es un cambio
    de_nuevo, _, _ = _correr(_vuelo(demora_min=45, consultado_en=0), _ahora("2026-11-28T08:30"), _estado(50), ts=1_002_000.0)
    assert de_nuevo == []


def test_avisa_cuando_aparece_la_puerta_y_cuando_cambia():
    [(k1, m1)], u1, _ = _correr(_vuelo(), _ahora("2026-11-28T08:00"), _estado(0, "B12"))
    [(k2, m2)], _, _ = _correr(_vuelo(puerta="B12", consultado_en=0), _ahora("2026-11-28T08:30"), _estado(0, "C3"),
                               ts=1_002_000.0)

    assert k1 == "vpuerta:v1:B12" and m1["title"] == "AR1302: puerta B12"
    assert u1["v1"]["puerta"] == "B12"
    assert k2 == "vpuerta:v1:C3" and m2["title"] == "AR1302 cambió de puerta: ahora C3"


def test_avisa_la_cancelacion():
    [(key, msg)], _, _ = _correr(_vuelo(), _ahora("2026-11-28T08:00"), _estado(0, None, "Canceled"))

    assert key == "vcancel:v1" and "cancel" in msg["title"].lower()


def test_cerca_de_la_salida_no_vuelve_a_consultar_antes_de_15_min():
    ahora = _ahora("2026-11-28T14:30")   # faltan 1 h 35 min
    v = _vuelo(consultado_en=1_000_000.0 - 14 * 60)

    assert _correr(v, ahora, _estado(45))[2] == []
    v = _vuelo(consultado_en=1_000_000.0 - 16 * 60)
    assert _correr(v, ahora, _estado(45))[2] == [("AR1302", "2026-11-28")]


def test_si_la_consulta_falla_no_cambia_nada_pero_se_anota_el_intento():
    avisos, updates, _ = _correr(_vuelo(), _ahora("2026-11-28T08:00"), None)

    assert avisos == [] and updates["v1"] == {"consultado_en": 1_000_000.0}


def test_la_salida_real_corrige_la_hora_cargada():
    _, updates, _ = _correr(_vuelo(), _ahora("2026-11-28T08:00"), _estado(0))

    assert updates["v1"]["salida_utc"] == _estado()["salida_utc"]


def test_de_noche_solo_avisa_lo_urgente():
    lejos = _ahora("2026-11-28T03:00")   # 13 h antes de salir: puede esperar a la mañana
    avisos, updates, _ = _correr(_vuelo(), lejos, _estado(45, "B12"))

    assert avisos == []
    assert "demora_min" not in updates["v1"] and "puerta" not in updates["v1"]   # la base no avanza: queda pendiente

    cerca = _vuelo(hora="08:00")   # sale 03:00 de Las Vegas; a las 23:00 faltan 4 h
    urgente, _, _ = _correr(cerca, _ahora("2026-11-27T23:00"),
                           _estado(45, salida_utc=dt.datetime(2026, 11, 28, 11, 0, tzinfo=dt.UTC)))
    assert [k for k, _ in urgente] == ["vdemora:v1:0>45"]


# ---------- orquestación con base y push (usuarios, preferencias, dedup) ----------

@pytest.fixture
def cli(monkeypatch):
    pub, priv = push.generate_vapid_keys()
    monkeypatch.setattr(config, "VAPID_PUBLIC_KEY", pub)
    monkeypatch.setattr(config, "VAPID_PRIVATE_KEY", priv)
    monkeypatch.setattr(push.itinerary, "get_current", lambda u: {"days": []})
    monkeypatch.setattr(push.changes, "pending", lambda u: [])
    with TestClient(app) as c:
        c.H = login_headers(c)
        c.H2 = login_headers(c, TEST_ADMIN, TEST_ADMIN_PASSWORD)
        _limpiar()
        yield c
        _limpiar()


def _limpiar():
    with db.conn() as c:
        for t in ("viajes_vuelos", "viajes_hoteles", "push_sent"):
            c.execute(f"DELETE FROM {t} WHERE username IN (%s,%s)", (TEST_USER, TEST_ADMIN))
        c.execute("DELETE FROM preferencias_avisos WHERE username IN (%s,%s)", (TEST_USER, TEST_ADMIN))


def _claves(username, now):
    return [k for k, _ in push.due(username, now)]


def test_el_aviso_sale_por_el_mismo_hilo_de_push_y_una_sola_vez(cli, monkeypatch):
    vuelos.agregar_vuelo(TEST_USER, "AR1302", "", "2026-11-28", "21:05", BUE)
    enviados = []
    monkeypatch.setattr(db, "push_usernames", lambda: [TEST_USER])
    monkeypatch.setattr(push, "notify", lambda u, m: enviados.append((u, m)) or 1)
    monkeypatch.setattr(sandbox, "ahora", lambda tz=LV: _ahora("2026-11-27T17:00"))

    assert push.tick() == 1
    assert push.tick() == 0   # ya avisado: push_sent lo frena
    assert enviados[0][1]["title"] == "Ya podés hacer el check-in de AR1302"


def test_cada_persona_solo_recibe_lo_suyo(cli):
    vuelos.agregar_vuelo(TEST_USER, "AR1302", "", "2026-11-28", "21:05", BUE)
    vuelos.agregar_hotel(TEST_ADMIN, "Wynn", "", "2026-11-29T15:00", "2026-12-04T11:00", "America/Los_Angeles")

    assert _claves(TEST_ADMIN, _ahora("2026-11-27T17:00")) == []
    assert _claves(TEST_USER, _ahora("2026-11-27T17:00")) != []
    assert [k.split(":")[0] for k in _claves(TEST_ADMIN, _ahora("2026-11-29T13:00"))] == ["hin"]


def test_preferencias_apagadas_no_avisan(cli):
    vuelos.agregar_vuelo(TEST_USER, "AR1302", "", "2026-11-28", "21:05", BUE)
    vuelos.agregar_hotel(TEST_USER, "Venetian", "", "2026-11-29T15:00", "2026-12-04T11:00", "America/Los_Angeles")
    assert cli.put("/api/viajes/preferencias", headers=cli.H, json={
        "viajes_checkin": False, "viajes_hoteles": False, "viajes_estado": False}).status_code == 200

    assert _claves(TEST_USER, _ahora("2026-11-27T17:00")) == []
    assert _claves(TEST_USER, _ahora("2026-11-29T13:00")) == []


def test_sin_clave_de_aerodatabox_no_hay_alertas_de_estado_pero_si_el_resto(cli, monkeypatch):
    monkeypatch.setattr(config, "AERODATABOX_API_KEY", "")
    monkeypatch.setattr(vuelos.httpx, "get", lambda *a, **k: pytest.fail("no debe consultar la API sin clave"))
    vuelos.agregar_vuelo(TEST_USER, "AR1302", "", "2026-11-28", "21:05", BUE)

    id_ = vuelos.listar_vuelos(TEST_USER)[0]["id"]
    assert _claves(TEST_USER, _ahora("2026-11-28T08:00")) == [f"vcheckin:{id_}"]   # solo el check-in, sin estado


def test_con_clave_consulta_guarda_la_base_y_no_repite(cli, monkeypatch):
    monkeypatch.setattr(config, "AERODATABOX_API_KEY", "clave-de-prueba")
    vuelos.reiniciar_consultas()
    llamadas = []

    def consultar(numero, fecha, http=None, usuario=None):
        llamadas.append(numero)
        return {"salida_utc": dt.datetime(2026, 11, 29, 0, 5, tzinfo=dt.UTC).timestamp(), "demora_min": 45,
                "puerta": "B12", "terminal": None, "estado": "Expected"}

    monkeypatch.setattr(vuelos, "consultar", consultar)
    v = vuelos.agregar_vuelo(TEST_USER, "AR1302", "", "2026-11-28", "21:05", BUE)

    claves = _claves(TEST_USER, _ahora("2026-11-28T08:00"))
    assert f"vdemora:{v['id']}:0>45" in claves and f"vpuerta:{v['id']}:B12" in claves
    assert vuelos.get_vuelo(TEST_USER, v["id"])["demora_min"] is None   # se guarda recién cuando el aviso llega
    for k in (f"vdemora:{v['id']}:0>45", f"vpuerta:{v['id']}:B12"):
        va.confirmar(TEST_USER, k)
    assert vuelos.get_vuelo(TEST_USER, v["id"])["demora_min"] == 45
    # un minuto después: el intervalo de 20 min frena la consulta, y la base guardada evita repetir el cambio
    assert not any(k.startswith(("vdemora", "vpuerta")) for k in _claves(TEST_USER, _ahora("2026-11-28T08:01")))
    assert llamadas == ["AR1302"]
    assert time.time() - vuelos.get_vuelo(TEST_USER, v["id"])["consultado_en"] < 60
