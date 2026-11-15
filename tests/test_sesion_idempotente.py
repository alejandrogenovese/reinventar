"""POST /api/sessions con client_id (idempotente por usuario) y recorded_at (la hora real de la grabación), para las
grabaciones que empezaron sin señal y se suben al volver (sesiones locales «loc_…» de la PWA)."""
import datetime as dt
import time
import uuid

import pytest
from fastapi.testclient import TestClient

from app import config, db, pg, sandbox
from app.main import app
from tests.conftest import TEST_ADMIN, TEST_ADMIN_PASSWORD, login_headers

PASSWORD = "idempotente123"
NUEVA = {"title": "Charla sin señal", "kind": "Breakout"}


def _cid() -> str:
    return f"loc_{uuid.uuid4().hex[:12]}"


def _hace(**delta) -> str:
    return (dt.datetime.now(dt.UTC) - dt.timedelta(**delta)).isoformat()


@pytest.fixture
def cli():
    with TestClient(app) as c:
        c.user = login_headers(c)
        yield c


def _cuantas(client_id: str) -> int:
    with sandbox.real(), pg.pool().connection() as conn:
        return conn.execute(f"SELECT count(*) AS n FROM {config.DB_SCHEMA}.sessions WHERE client_id = %s",
                            (client_id,)).fetchone()["n"]


# ---------- client_id ----------

def test_repetir_el_client_id_devuelve_la_misma_sesion_con_200(cli):
    cid = _cid()

    a = cli.post("/api/sessions", headers=cli.user, json={**NUEVA, "client_id": cid})
    b = cli.post("/api/sessions", headers=cli.user, json={**NUEVA, "client_id": cid})

    assert (a.status_code, b.status_code) == (200, 200)
    assert a.json()["id"] == b.json()["id"]
    assert b.json()["client_id"] == cid
    assert _cuantas(cid) == 1


def test_el_reintento_devuelve_lo_que_ya_existe_aunque_cambie_el_cuerpo(cli):
    cid = _cid()
    a = cli.post("/api/sessions", headers=cli.user, json={**NUEVA, "client_id": cid}).json()

    b = cli.post("/api/sessions", headers=cli.user, json={"title": "Otro título", "kind": "Keynote", "client_id": cid})

    assert b.json()["id"] == a["id"]
    assert b.json()["title"] == NUEVA["title"]


def test_sin_client_id_cada_pedido_crea_una_sesion(cli):
    a = cli.post("/api/sessions", headers=cli.user, json=NUEVA).json()
    b = cli.post("/api/sessions", headers=cli.user, json=NUEVA).json()

    assert a["id"] != b["id"]
    assert a["client_id"] is None


def test_el_client_id_es_por_usuario(cli):
    admin = login_headers(cli, TEST_ADMIN, TEST_ADMIN_PASSWORD)
    cid = _cid()

    mia = cli.post("/api/sessions", headers=cli.user, json={**NUEVA, "client_id": cid}).json()
    de_otro = cli.post("/api/sessions", headers=admin, json={**NUEVA, "client_id": cid}).json()

    assert mia["id"] != de_otro["id"]
    assert _cuantas(cid) == 2


@pytest.mark.parametrize("client_id", ["", "corto", "con espacios en el medio", "x" * 65, "ñandú_12345"])
def test_un_client_id_mal_formado_da_422(cli, client_id):
    r = cli.post("/api/sessions", headers=cli.user, json={**NUEVA, "client_id": client_id})

    assert r.status_code == 422


def test_dos_altas_seguidas_con_el_mismo_client_id_en_la_base_crean_una_sola():
    cid = _cid()

    a = db.create_session("T", "Breakout", created_by="tester", client_id=cid)
    b = db.create_session("T", "Breakout", created_by="tester", client_id=cid)

    assert a["id"] == b["id"]
    assert _cuantas(cid) == 1


def test_en_modo_prueba_tambien_es_idempotente_y_va_al_schema_de_prueba():
    with TestClient(app) as c:
        admin = login_headers(c, TEST_ADMIN, TEST_ADMIN_PASSWORD)
        username = f"idem_{uuid.uuid4().hex[:6]}"
        assert c.post("/api/admin/users", headers=admin, json={"username": username, "password": PASSWORD}).status_code == 200
        user = login_headers(c, username, PASSWORD)
        assert c.put(f"/api/admin/users/{username}/sandbox", headers=admin, json={"active": True}).status_code == 200
        cid = _cid()

        a = c.post("/api/sessions", headers=user, json={**NUEVA, "client_id": cid}).json()
        b = c.post("/api/sessions", headers=user, json={**NUEVA, "client_id": cid}).json()

    assert a["id"] == b["id"]
    with sandbox.real(), pg.pool().connection() as conn:
        n = conn.execute(f"SELECT count(*) AS n FROM {sandbox.schema_prueba()}.sessions WHERE client_id = %s",
                         (cid,)).fetchone()["n"]
    assert n == 1


def test_la_migracion_es_idempotente_y_deja_el_indice_en_el_schema_real_y_el_de_prueba():
    with TestClient(app), sandbox.real(), db.conn() as c:  # TestClient: corre el init de la base
        c.execute(db.DATOS_USUARIO)  # correrla de nuevo no rompe
        indices = {(r["schemaname"], r["indexname"]) for r in c.execute(
            "SELECT schemaname, indexname FROM pg_indexes WHERE indexname = 'sessions_client_id_unico'").fetchall()}

    assert (config.DB_SCHEMA, "sessions_client_id_unico") in indices
    assert (sandbox.schema_prueba(), "sessions_client_id_unico") in indices


# ---------- recorded_at ----------

def test_recorded_at_es_la_hora_de_la_sesion_y_con_ella_se_ordena_la_lista(cli):
    ahora = cli.post("/api/sessions", headers=cli.user, json={**NUEVA, "title": "ahora"}).json()
    vieja = cli.post("/api/sessions", headers=cli.user, json={**NUEVA, "title": "vieja", "recorded_at": _hace(hours=5)}).json()
    media = cli.post("/api/sessions", headers=cli.user, json={**NUEVA, "title": "media", "recorded_at": _hace(hours=1)}).json()

    ids = [s["id"] for s in cli.get("/api/sessions", headers=cli.user).json()]

    assert ids.index(ahora["id"]) < ids.index(media["id"]) < ids.index(vieja["id"])
    assert vieja["created_at"] == pytest.approx(time.time() - 5 * 3600, abs=30)


def test_sin_recorded_at_la_hora_es_la_del_pedido(cli):
    s = cli.post("/api/sessions", headers=cli.user, json=NUEVA).json()

    assert s["created_at"] == pytest.approx(time.time(), abs=30)


def test_recorded_at_acepta_una_hora_levemente_en_el_futuro_por_desfase_del_reloj(cli):
    adelante = (dt.datetime.now(dt.UTC) + dt.timedelta(minutes=2)).isoformat()

    r = cli.post("/api/sessions", headers=cli.user, json={**NUEVA, "recorded_at": adelante})

    assert r.status_code == 200


def test_recorded_at_acepta_el_formato_z_y_los_offsets(cli):
    hace3h = dt.datetime.now(dt.UTC) - dt.timedelta(hours=3)
    z = hace3h.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    buenos_aires = hace3h.astimezone(dt.timezone(dt.timedelta(hours=-3))).isoformat()

    for valor in (z, buenos_aires):
        r = cli.post("/api/sessions", headers=cli.user, json={**NUEVA, "recorded_at": valor})
        assert r.status_code == 200, valor
        assert r.json()["created_at"] == pytest.approx(time.time() - 3 * 3600, abs=30)


@pytest.mark.parametrize("valor", [
    (dt.datetime.now(dt.UTC) + dt.timedelta(minutes=30)).isoformat(),        # en el futuro
    (dt.datetime.now(dt.UTC) - dt.timedelta(days=2, hours=1)).isoformat(),   # más de 2 días
    "2026-12-01T10:00:00",   # sin zona horaria
    "ayer a la tarde",
    "",
])
def test_recorded_at_fuera_de_rango_o_mal_formado_da_422(cli, valor):
    r = cli.post("/api/sessions", headers=cli.user, json={**NUEVA, "recorded_at": valor})

    assert r.status_code == 422


def test_un_reintento_con_client_id_no_cambia_la_hora_de_la_sesion(cli):
    cid = _cid()
    a = cli.post("/api/sessions", headers=cli.user, json={**NUEVA, "client_id": cid, "recorded_at": _hace(hours=2)}).json()

    b = cli.post("/api/sessions", headers=cli.user, json={**NUEVA, "client_id": cid, "recorded_at": _hace(hours=1)}).json()

    assert b["created_at"] == a["created_at"]
