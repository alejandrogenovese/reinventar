"""Sede reciente y preferencias del recordatorio "¿la grabás?", y su paso por el hilo de avisos (app/push.py).

Sin catálogo ni push reales: las sedes se cargan a mano, el itinerario y el envío se simulan. Corre en CI."""
import datetime as dt
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import config, db, push, recordatorio, sandbox, venues
from app.main import app
from tests.conftest import TEST_USER, login_headers

SEDES = [{"id_sede": 1, "nombre": "Venetian", "lat": 36.1212, "lng": -115.1697, "direccion": "3355 Las Vegas Blvd S"},
         {"id_sede": 5, "nombre": "MGM Grand", "lat": 36.102219, "lng": -115.169517, "direccion": "3799 Las Vegas Blvd S"}]
SUB = {"endpoint": "https://fcm.googleapis.com/fcm/send/rec", "keys": {"p256dh": "x" * 87, "auth": "y" * 22}}


def _charla(start, locked=True, code="ARC401"):
    return {"kind": "talk", "code": code, "base": code, "title": "Arquitecturas serverless", "day": "2026-12-01",
            "start": start, "end": "15:00", "locked": locked, "venue": {"hotel": "Venetian", "detail": "Room 401"}}


def _ahora(hhmm):
    return dt.datetime.fromisoformat(f"2026-12-01T{hhmm}").replace(tzinfo=sandbox.EVENT_TZ)


def _limpiar():
    db.set_preferencias_avisos(TEST_USER, True, False)
    with db.conn() as c:
        c.execute("DELETE FROM push_sent WHERE username=%s", (TEST_USER,))
        c.execute("DELETE FROM sessions WHERE code='ARC401'")


@pytest.fixture
def cli(monkeypatch):
    pub, priv = push.generate_vapid_keys()
    monkeypatch.setattr(config, "VAPID_PUBLIC_KEY", pub)
    monkeypatch.setattr(config, "VAPID_PRIVATE_KEY", priv)
    with TestClient(app) as c:
        venues.load(SEDES)
        c.H = login_headers(c)
        _limpiar()
        yield c
        _limpiar()
        c.post("/api/push/unsubscribe", headers=c.H, json={"endpoint": SUB["endpoint"]})


@pytest.fixture
def itinerario(monkeypatch):
    """Reemplaza el itinerario del usuario por las charlas que se le pasen."""
    def poner(*cards):
        monkeypatch.setattr(push.itinerary, "get_current", lambda u: {"days": [{"day": "2026-12-01", "sessions": list(cards)}]})
        monkeypatch.setattr(push.changes, "pending", lambda u: [])
    return poner


def _prender_ubicacion(cli):
    assert cli.put("/api/push/preferencias", headers=cli.H, json={"grabar": True, "ubicacion": True}).status_code == 200


# ---------- API ----------

def test_las_preferencias_vienen_con_la_ubicacion_apagada(cli):
    assert cli.get("/api/push/preferencias", headers=cli.H).json() == {"grabar": True, "ubicacion": False,
                                                                       "eventos_nuevos": True}


def test_sin_opt_in_no_se_guarda_la_sede(cli):
    assert cli.post("/api/ubicacion", headers=cli.H, json={"id_sede": 1}).status_code == 403
    assert db.get_ubicacion(TEST_USER, 0) is None


def test_guarda_solo_el_numero_de_sede(cli):
    _prender_ubicacion(cli)

    assert cli.post("/api/ubicacion", headers=cli.H, json={"id_sede": 1}).status_code == 200

    fila = db.get_ubicacion(TEST_USER, time.time() - 60)
    assert fila["id_sede"] == 1 and set(fila) == {"id_sede", "visto_en"}


def test_rechaza_coordenadas(cli):
    _prender_ubicacion(cli)

    r = cli.post("/api/ubicacion", headers=cli.H, json={"id_sede": 1, "lat": 36.12, "lng": -115.17})

    assert r.status_code == 422
    assert db.get_ubicacion(TEST_USER, 0) is None


def test_rechaza_una_sede_desconocida_y_acepta_ninguna(cli):
    _prender_ubicacion(cli)

    assert cli.post("/api/ubicacion", headers=cli.H, json={"id_sede": 999}).status_code == 422
    assert cli.post("/api/ubicacion", headers=cli.H, json={"id_sede": None}).status_code == 200
    assert db.get_ubicacion(TEST_USER, 0)["id_sede"] is None


def test_el_delete_y_apagar_la_preferencia_borran_la_sede(cli):
    _prender_ubicacion(cli)
    cli.post("/api/ubicacion", headers=cli.H, json={"id_sede": 1})

    assert cli.delete("/api/ubicacion", headers=cli.H).status_code == 200
    assert db.get_ubicacion(TEST_USER, 0) is None

    cli.post("/api/ubicacion", headers=cli.H, json={"id_sede": 1})
    cli.put("/api/push/preferencias", headers=cli.H, json={"grabar": True, "ubicacion": False})
    assert db.get_ubicacion(TEST_USER, 0) is None


def test_la_sede_se_borra_a_las_2_horas_y_con_los_datos_de_usuario(cli):
    _prender_ubicacion(cli)
    cli.post("/api/ubicacion", headers=cli.H, json={"id_sede": 1})

    assert db.purgar_ubicaciones(time.time() - recordatorio.UBICACION_BORRADO_MIN * 60) == 0
    assert db.purgar_ubicaciones(time.time() + 1) >= 1
    assert db.get_ubicacion(TEST_USER, 0) is None
    assert {"ubicacion_reciente", "preferencias_avisos"} <= set(db.TABLAS_DATOS_USUARIO)


def test_la_lista_de_sedes_trae_coordenadas_para_calcular_en_el_celular(cli):
    sedes = cli.get("/api/my-events/sedes", headers=cli.H).json()["sedes"]

    assert {"id": 1, "nombre": "Venetian", "lat": 36.1212, "lng": -115.1697} in sedes


# ---------- avisos ----------

def test_el_aviso_de_empieza_de_una_charla_fijada_pregunta_si_la_grabas(cli, itinerario):
    itinerario(_charla("14:00"))

    [(key, msg)] = push.due(TEST_USER, _ahora("13:57"))

    assert key == "start:ARC401:2026-12-01"
    assert msg["body"] == "Venetian · Room 401 · ¿La grabás?"
    assert msg["url"] == "/#/grabar-charla/ARC401"
    assert msg["actions"] == [{"action": "grabar", "title": "Grabar"}]


def test_con_recordar_grabar_apagado_el_aviso_de_empieza_queda_como_antes(cli, itinerario):
    itinerario(_charla("14:00"))
    db.set_preferencias_avisos(TEST_USER, False, False)

    [(_, msg)] = push.due(TEST_USER, _ahora("13:57"))

    assert "¿La grabás?" not in msg["body"] and "actions" not in msg
    assert push.due(TEST_USER, _ahora("14:03")) == []


def test_avisa_una_sola_vez_si_nadie_la_graba(cli, itinerario, monkeypatch):
    itinerario(_charla("14:00"))
    enviados = []
    monkeypatch.setattr(push, "send", lambda sub, msg, http=None, ttl=push.TTL_SECONDS: enviados.append((msg, ttl)) or 201)
    monkeypatch.setattr(push.sandbox, "ahora", lambda tz=None: _ahora("14:03"))
    assert cli.post("/api/push/subscribe", headers=cli.H, json=SUB).status_code == 200

    push.tick()
    push.tick()

    assert [m["title"] for m, _ in enviados] == ["Empezó Arquitecturas serverless en Venetian"]
    assert enviados[0][1] == recordatorio.TTL_SEGUNDOS
    assert "ttl" not in enviados[0][0]  # el TTL va en la cabecera, no al celular


def test_no_avisa_si_ya_hay_una_grabacion_de_esa_charla(cli, itinerario):
    itinerario(_charla("14:00"))
    db.create_session("Arquitecturas serverless", "Breakout", "ARC401")

    assert push.due(TEST_USER, _ahora("14:03")) == []


def test_enfriamiento_entre_recordatorios(cli, itinerario):
    itinerario(_charla("14:00"), _charla("14:30", code="DEV302"))
    db.mark_push_sent(TEST_USER, "rec:ARC401:2026-12-01")

    assert push.due(TEST_USER, _ahora("14:33")) == []


def test_la_sede_reciente_cambia_el_texto_y_vence_a_los_45_min(cli, itinerario):
    itinerario(_charla("14:00", locked=False))
    _prender_ubicacion(cli)
    cli.post("/api/ubicacion", headers=cli.H, json={"id_sede": 1})

    [(_, msg)] = push.due(TEST_USER, _ahora("14:03"))
    assert msg["title"] == "Estás en Venetian: ¿grabás Arquitecturas serverless?"

    with db.conn() as c:
        c.execute("UPDATE ubicacion_reciente SET visto_en = %s WHERE username = %s",
                  (time.time() - (recordatorio.UBICACION_VIGENCIA_MIN + 1) * 60, TEST_USER))
    assert push.due(TEST_USER, _ahora("14:03")) == []  # vencida = sin dato, y sin dato no avisa lo no fijado


def test_con_la_consulta_de_ubicacion_apagada_se_ignora_la_sede(cli, itinerario):
    itinerario(_charla("14:00", locked=False))
    db.set_ubicacion(TEST_USER, 1)  # quedó una fila, pero la preferencia está apagada

    assert push.due(TEST_USER, _ahora("14:03")) == []


def test_en_modo_prueba_usa_la_sede_simulada(cli, itinerario):
    itinerario(_charla("14:00", locked=False))
    sb = sandbox.Sandbox(username=TEST_USER, id_sede=1)

    with sandbox.activar(sb):
        [(_, msg)] = push.due(TEST_USER, _ahora("14:03"))

    assert msg["title"].startswith("Estás en Venetian")


# ---------- PWA (texto, sin navegador) ----------

WEB = Path(__file__).resolve().parent.parent / "web"


def test_el_service_worker_maneja_la_accion_grabar_y_el_tag_propio():
    sw = (WEB / "sw.js").read_text()

    assert 'e.action === "grabar"' in sw
    assert "msg.tag || msg.title" in sw
    assert "msg.actions" in sw


def test_existe_la_ruta_para_grabar_desde_el_aviso():
    app_js = (WEB / "js" / "app.js").read_text()

    assert "#\\/grabar-charla\\/" in app_js
    assert "Empezar a grabar" in (WEB / "js" / "grabarCharla.js").read_text()


def test_la_ubicacion_solo_sale_como_numero_de_sede():
    location_js = (WEB / "js" / "location.js").read_text()

    assert "Ubicacion.set(nearestVenue(" in location_js
    assert 'permissions.query({ name: "geolocation" })' in location_js
