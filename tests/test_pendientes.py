"""Pendientes del viaje: siembra idempotente, alta/edición/baja, tildar, aislamiento por usuario (404), sugeridos borrados
que no vuelven, modo prueba, y los avisos de fecha límite y del resumen con dedupe, silencio y preferencia."""
import datetime as dt
import uuid

import pytest
from fastapi.testclient import TestClient

from app import config, db, pg, push, sandbox
from app import viajes_avisos as va
from app import viajes_pendientes as vp
from app.main import app
from tests.conftest import TEST_ADMIN, TEST_ADMIN_PASSWORD, TEST_USER, login_headers

URL = "/api/viajes/pendientes"
LV = sandbox.EVENT_TZ


def _ahora(texto):
    """Hora de Las Vegas."""
    return dt.datetime.fromisoformat(texto).replace(tzinfo=LV)


def _limpiar():
    with db.conn() as c:
        for t in ("viajes_pendientes", "viajes_vuelos", "viajes_hoteles", "push_sent", "preferencias_avisos"):
            c.execute(f"DELETE FROM {t} WHERE username IN (%s,%s)", (TEST_USER, TEST_ADMIN))


@pytest.fixture
def cli(monkeypatch):
    monkeypatch.setattr(push.itinerary, "get_current", lambda u: {"days": []})
    monkeypatch.setattr(push.changes, "pending", lambda u: [])
    with TestClient(app) as c:
        c.H = login_headers(c)
        c.H2 = login_headers(c, TEST_ADMIN, TEST_ADMIN_PASSWORD)
        _limpiar()
        yield c
        _limpiar()


def _lista(cli, headers=None):
    return cli.get(URL, headers=headers or cli.H).json()


# ---------- siembra ----------

def test_el_primer_get_siembra_los_sugeridos_y_el_segundo_no_los_duplica(cli):
    primera = _lista(cli)
    segunda = _lista(cli)

    assert [p["texto"] for p in primera["pendientes"]] == [t for _, t in vp.SUGERIDOS]
    assert {p["origen"] for p in primera["pendientes"]} == {"sugerido"}
    assert segunda["pendientes"] == primera["pendientes"]
    assert segunda["resumen"] == {"hechos": 0, "total": len(vp.SUGERIDOS)}


def test_sembrar_varias_veces_es_idempotente():
    _limpiar()
    for _ in range(3):
        vp.sembrar(TEST_USER)

    assert len(vp.listar_filas(TEST_USER)) == len(vp.SUGERIDOS)
    _limpiar()


def test_un_sugerido_borrado_no_vuelve_a_aparecer(cli):
    esta = _lista(cli)["pendientes"][0]

    assert cli.delete(f"{URL}/{esta['id']}", headers=cli.H).status_code == 200
    lista = _lista(cli)

    assert esta["id"] not in [p["id"] for p in lista["pendientes"]]
    assert esta["texto"] not in [p["texto"] for p in lista["pendientes"]]
    assert lista["resumen"]["total"] == len(vp.SUGERIDOS) - 1
    assert cli.delete(f"{URL}/{esta['id']}", headers=cli.H).status_code == 404


# ---------- alta, edición, tildar, baja ----------

def test_agrega_uno_propio_al_final_con_fecha(cli):
    _lista(cli)

    r = cli.post(URL, headers=cli.H, json={"texto": "  Comprar   adaptador  ", "fecha_limite": "2026-11-27"})

    assert r.status_code == 201
    p = r.json()
    assert (p["texto"], p["fecha_limite"], p["origen"], p["hecho"]) == ("Comprar adaptador", "2026-11-27", "propio", False)
    assert _lista(cli)["pendientes"][-1]["id"] == p["id"]


@pytest.mark.parametrize("body", [{"texto": ""}, {"texto": "   "}, {"texto": "x" * 121}, {"texto": "ok", "fecha_limite": "mañana"},
                                  {}])
def test_rechaza_pendientes_mal_cargados(cli, body):
    assert cli.post(URL, headers=cli.H, json=body).status_code == 422


def test_edita_solo_lo_que_viene_y_null_borra_la_fecha(cli):
    p = cli.post(URL, headers=cli.H, json={"texto": "Adaptador", "fecha_limite": "2026-11-27"}).json()

    r = cli.put(f"{URL}/{p['id']}", headers=cli.H, json={"texto": "Adaptador universal"})
    assert (r.json()["texto"], r.json()["fecha_limite"]) == ("Adaptador universal", "2026-11-27")

    r = cli.put(f"{URL}/{p['id']}", headers=cli.H, json={"fecha_limite": None, "orden": 0})
    assert (r.json()["texto"], r.json()["fecha_limite"], r.json()["orden"]) == ("Adaptador universal", None, 0)


@pytest.mark.parametrize("body", [{"texto": None}, {"orden": None}, {"orden": -1}, {"texto": "x" * 121}])
def test_la_edicion_valida_los_limites(cli, body):
    p = cli.post(URL, headers=cli.H, json={"texto": "Adaptador"}).json()

    assert cli.put(f"{URL}/{p['id']}", headers=cli.H, json=body).status_code == 422


def test_tildar_y_destildar_actualiza_el_resumen(cli):
    ids = [p["id"] for p in _lista(cli)["pendientes"]]

    assert cli.post(f"{URL}/{ids[0]}/hecho", headers=cli.H).json()["hecho"] is True
    cli.post(f"{URL}/{ids[1]}/hecho", headers=cli.H)
    assert _lista(cli)["resumen"] == {"hechos": 2, "total": len(ids)}

    assert cli.delete(f"{URL}/{ids[0]}/hecho", headers=cli.H).json()["hecho"] is False
    assert _lista(cli)["resumen"]["hechos"] == 1


def test_un_propio_borrado_desaparece_de_verdad(cli):
    p = cli.post(URL, headers=cli.H, json={"texto": "Adaptador"}).json()

    assert cli.delete(f"{URL}/{p['id']}", headers=cli.H).status_code == 200
    with db.conn() as c:
        assert c.execute("SELECT COUNT(*) AS n FROM viajes_pendientes WHERE id=%s", (p["id"],)).fetchone()["n"] == 0


def test_hay_un_tope_por_persona(cli, monkeypatch):
    monkeypatch.setattr(vp, "TOPE_POR_PERSONA", 1)
    assert cli.post(URL, headers=cli.H, json={"texto": "Uno"}).status_code == 201

    assert cli.post(URL, headers=cli.H, json={"texto": "Dos"}).status_code == 409


# ---------- aislamiento ----------

def test_el_pendiente_de_otro_da_404_en_todo(cli):
    p = cli.post(URL, headers=cli.H, json={"texto": "Mío"}).json()
    otro = cli.H2

    assert cli.put(f"{URL}/{p['id']}", headers=otro, json={"texto": "Robado"}).status_code == 404
    assert cli.post(f"{URL}/{p['id']}/hecho", headers=otro).status_code == 404
    assert cli.delete(f"{URL}/{p['id']}/hecho", headers=otro).status_code == 404
    assert cli.delete(f"{URL}/{p['id']}", headers=otro).status_code == 404
    assert p["id"] not in [x["id"] for x in _lista(cli, otro)["pendientes"]]
    assert vp.get(TEST_USER, p["id"])["texto"] == "Mío"


def test_un_id_con_caracteres_raros_se_rechaza(cli):
    assert cli.delete(f"{URL}/abc%25", headers=cli.H).status_code == 422


def test_sin_sesion_no_entra(cli):
    assert cli.get(URL).status_code == 401
    assert cli.post(URL, json={"texto": "x"}).status_code == 401


# ---------- modo prueba ----------

def test_en_modo_prueba_los_pendientes_van_al_schema_de_prueba(cli):
    username = f"sb_{uuid.uuid4().hex[:6]}"
    assert cli.post("/api/admin/users", headers=cli.H2, json={"username": username, "password": "sandboxpass123"}).status_code == 200
    user = login_headers(cli, username, "sandboxpass123")
    assert cli.put(f"/api/admin/users/{username}/sandbox", headers=cli.H2, json={"active": True}).status_code == 200

    pid = cli.post(URL, headers=user, json={"texto": "De prueba"}).json()["id"]

    with sandbox.real(), pg.pool().connection() as c:
        contar = "SELECT count(*) AS n FROM {}.viajes_pendientes WHERE id = %s"
        assert c.execute(contar.format(sandbox.schema_prueba()), (pid,)).fetchone()["n"] == 1
        assert c.execute(contar.format(config.DB_SCHEMA), (pid,)).fetchone()["n"] == 0


# ---------- avisos ----------

def _p(id_="p1", texto="Seguro", fecha=None):
    return {"id": id_, "texto": texto, "fecha_limite": dt.date.fromisoformat(fecha) if fecha else None, "hecho_en": None}


def test_avisa_3_dias_antes_y_el_mismo_dia_de_la_fecha_limite():
    p = _p(fecha="2026-11-20")

    assert [k for k, _ in va.pendientes([p], _ahora("2026-11-17T09:00"))] == ["pend:p1:2026-11-17"]
    assert [k for k, _ in va.pendientes([p], _ahora("2026-11-20T09:00"))] == ["pend:p1:2026-11-20"]
    assert va.pendientes([p], _ahora("2026-11-18T09:00")) == []
    [(_, msg)] = va.pendientes([p], _ahora("2026-11-20T09:00"))
    assert msg["title"] == "Hoy vence un pendiente del viaje" and msg["body"] == "Seguro"
    assert msg["url"] == "/#/viajes/pendientes"


def test_nada_sale_de_noche():
    assert va.pendientes([_p(fecha="2026-11-20")], _ahora("2026-11-20T23:00")) == []
    assert va.pendientes([_p()], _ahora("2026-11-28T06:00")) == []


def test_el_resumen_sale_a_la_manana_los_3_dias_previos():
    lista = [_p("a"), _p("b")]

    [(clave, msg)] = va.pendientes(lista, _ahora("2026-11-26T08:00"))
    assert clave == "pendres:2026-11-26" and msg["title"] == "Te faltan 2 pendientes del viaje"
    assert "En 3 días" in msg["body"]
    assert va.pendientes(lista, _ahora("2026-11-28T09:00"))[0][1]["body"].startswith("Mañana")
    assert va.pendientes(lista, _ahora("2026-11-28T15:00")) == []   # ya no es la mañana
    assert va.pendientes(lista, _ahora("2026-11-25T08:00")) == []   # faltan 4 días
    assert va.pendientes(lista, _ahora("2026-11-29T08:00")) == []   # ya arrancó
    assert va.pendientes([], _ahora("2026-11-27T08:00")) == []      # no falta nada


def test_por_push_due_cada_aviso_sale_una_sola_vez(cli, monkeypatch):
    cli.post(URL, headers=cli.H, json={"texto": "Seguro", "fecha_limite": "2026-11-27"})
    enviados = []
    monkeypatch.setattr(db, "push_usernames", lambda: [TEST_USER])
    monkeypatch.setattr(push, "notify", lambda u, m: enviados.append(m["title"]) or 1)
    monkeypatch.setattr(sandbox, "ahora", lambda tz=LV: _ahora("2026-11-27T08:00"))

    push.tick()
    push.tick()

    assert sorted(enviados) == ["Hoy vence un pendiente del viaje", "Te falta 1 pendiente del viaje"]


def test_los_hechos_no_avisan(cli):
    p = cli.post(URL, headers=cli.H, json={"texto": "Seguro", "fecha_limite": "2026-11-27"}).json()
    cli.post(f"{URL}/{p['id']}/hecho", headers=cli.H)

    assert [k for k, _ in push.due(TEST_USER, _ahora("2026-11-27T08:00")) if k.startswith("pend")] == []


def test_la_preferencia_apagada_no_avisa_y_la_app_vieja_no_la_pisa(cli):
    cli.post(URL, headers=cli.H, json={"texto": "Seguro", "fecha_limite": "2026-11-27"})
    prefs = {"viajes_checkin": True, "viajes_hoteles": True, "viajes_estado": True}
    assert cli.put("/api/viajes/preferencias", headers=cli.H, json={**prefs, "viajes_pendientes": False}).status_code == 200

    cli.put("/api/viajes/preferencias", headers=cli.H, json=prefs)   # una app que no conoce la preferencia nueva

    assert cli.get("/api/viajes/preferencias", headers=cli.H).json()["viajes_pendientes"] is False
    assert [k for k, _ in push.due(TEST_USER, _ahora("2026-11-27T08:00")) if k.startswith("pend")] == []


def test_los_sugeridos_tienen_clave_unica_y_entran_en_el_largo_maximo():
    claves = [k for k, _ in vp.SUGERIDOS]
    assert len(claves) == len(set(claves))
    assert all(len(t) <= vp.LARGO_MAX_TEXTO for _, t in vp.SUGERIDOS)


def test_los_sugeridos_incluyen_enchufe_foto_aduana_tarjeta_y_swag():
    textos = dict(vp.SUGERIDOS)
    assert "tipo A" in textos["enchufe"]
    assert "portal de registro" in textos["foto_reinvent"]
    assert "OM-121" in textos["om121"]
    assert "dólares propios" in textos["tarjeta_dolares"]
    assert "swag" in textos["swag"]
