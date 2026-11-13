"""Correcciones de seguridad: sesiones, login, passkeys, subidas, cabeceras, push, Places y el mapa."""
import re
import time
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import auth, cabeceras, config, db, limites, passkeys_db, passwords, places, push_api
from app.main import app
from tests.conftest import TEST_ADMIN, TEST_ADMIN_PASSWORD, login_headers


@pytest.fixture(scope="module")
def c():
    with TestClient(app) as cliente:
        yield cliente


def _usuario(must_change=False, password="inicial123"):
    username = f"s_{uuid.uuid4().hex[:8]}"
    salt, h = passwords.hash_password(password)
    db.create_user(username, salt, h, must_change_password=must_change)
    return username, password


def _login(c, username, password):
    r = c.post("/api/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["token"], {"Authorization": f"Bearer {r.json()['token']}"}


# --- sesiones -----------------------------------------------------------------------------
def test_el_token_se_guarda_hasheado_y_no_en_claro(c):
    username, password = _usuario()
    token, _ = _login(c, username, password)

    with db.conn() as cx:
        guardados = [r["token"] for r in cx.execute("SELECT token FROM auth_tokens WHERE username=%s", (username,))]

    assert token not in guardados and db.hash_token(token) in guardados
    assert db.resolve_auth_token(token) == username


def test_una_sesion_sin_usar_por_mas_de_30_dias_vence(c):
    username, password = _usuario()
    token, headers = _login(c, username, password)
    viejo = time.time() - db.SESION_INACTIVA_SEGUNDOS - 60
    with db.conn() as cx:
        cx.execute("UPDATE auth_tokens SET created_at=%s, usado_at=%s WHERE token=%s", (viejo, viejo, db.hash_token(token)))

    assert c.get("/api/me", headers=headers).status_code == 401


def test_usar_la_app_mantiene_viva_la_sesion(c):
    username, password = _usuario()
    token, _ = _login(c, username, password)
    hace_dos_dias = time.time() - 2 * 24 * 3600
    with db.conn() as cx:
        cx.execute("UPDATE auth_tokens SET usado_at=%s WHERE token=%s", (hace_dos_dias, db.hash_token(token)))

    db.resolve_session(token)

    with db.conn() as cx:
        usado = cx.execute("SELECT usado_at FROM auth_tokens WHERE token=%s", (db.hash_token(token),)).fetchone()["usado_at"]
    assert usado > hace_dos_dias + 24 * 3600


def test_los_tokens_viejos_en_claro_se_migran_y_siguen_valiendo(c):
    username, _ = _usuario()
    token_viejo = uuid.uuid4().hex * 2
    with db.conn() as cx:
        cx.execute("INSERT INTO auth_tokens (token, username, created_at, hasheado) VALUES (%s,%s,%s,FALSE)",
                   (token_viejo, username, time.time()))
        db._hashear_tokens_viejos(cx)
        db._hashear_tokens_viejos(cx)  # idempotente: la segunda vez no toca nada

    assert db.resolve_auth_token(token_viejo) == username


# --- contraseña temporal ----------------------------------------------------------------
def test_con_la_contrasena_temporal_solo_se_puede_cambiarla(c):
    username, password = _usuario(must_change=True)
    _, headers = _login(c, username, password)

    r = c.get("/api/sessions", headers=headers)
    assert r.status_code == 403 and r.json()["detail"] == auth.DEBE_CAMBIAR_CONTRASENA
    assert c.get("/api/me", headers=headers).status_code == 200

    c.post("/api/password", headers=headers, json={"current_password": password, "new_password": "definitiva99"})
    assert c.get("/api/sessions", headers=headers).status_code == 200


# --- login ------------------------------------------------------------------------------
def test_despues_de_5_fallos_el_login_se_bloquea_aunque_la_clave_sea_buena(c):
    username, password = _usuario()
    for _ in range(limites.FALLOS_POR_USUARIO):
        assert c.post("/api/login", json={"username": username, "password": "mala"}).status_code == 401

    assert c.post("/api/login", json={"username": username, "password": password}).status_code == 429


def test_un_login_bueno_limpia_los_fallos_de_la_cuenta(c):
    username, password = _usuario()
    for _ in range(limites.FALLOS_POR_USUARIO - 1):
        c.post("/api/login", json={"username": username, "password": "mala"})
    _login(c, username, password)

    assert c.post("/api/login", json={"username": username, "password": "mala"}).status_code == 401  # no 429


def test_muchos_fallos_desde_la_misma_ip_contra_distintas_cuentas_tambien_se_frenan(c):
    for i in range(limites.FALLOS_POR_IP):
        c.post("/api/login", json={"username": f"nadie{i}", "password": "mala"})

    username, password = _usuario()
    assert c.post("/api/login", json={"username": username, "password": password}).status_code == 429


def test_si_el_usuario_no_existe_igual_se_verifica_una_contrasena(c, monkeypatch):
    llamadas = []
    original = passwords.verify_password
    monkeypatch.setattr(passwords, "verify_password", lambda *a: llamadas.append(1) or original(*a))

    assert c.post("/api/login", json={"username": "no_existe_x", "password": "algo"}).status_code == 401
    assert llamadas == [1]  # mismo trabajo que con un usuario real: el tiempo no delata qué usuarios existen


def test_la_ventana_del_limite_se_vacia_con_el_tiempo():
    limite = limites.Limite(2, ventana=60)
    limite.sumar("x", ahora=100)
    limite.sumar("x", ahora=110)

    assert limite.excedido("x", ahora=120)
    assert not limite.excedido("x", ahora=171)


# --- passkeys ---------------------------------------------------------------------------
def _passkey_de(username):
    passkeys_db.add_passkey(f"cred-{uuid.uuid4().hex}", username, b"clave", 0, "iPhone")


def test_cambiar_la_contrasena_borra_las_passkeys(c):
    username, password = _usuario()
    _, headers = _login(c, username, password)
    _passkey_de(username)

    c.post("/api/password", headers=headers, json={"current_password": password, "new_password": "otraclave99"})

    assert passkeys_db.list_passkeys(username) == []


@pytest.mark.parametrize("accion", ["reset", "revocar", "desactivar"])
def test_recuperar_la_cuenta_desde_admin_corta_passkeys_sesiones_y_avisos(c, accion):
    username, password = _usuario()
    _, headers = _login(c, username, password)
    _passkey_de(username)
    db.save_push_subscription(username, f"https://fcm.googleapis.com/fcm/send/{uuid.uuid4().hex}", "p" * 87, "a" * 22)
    admin = login_headers(c, TEST_ADMIN, TEST_ADMIN_PASSWORD)

    if accion == "reset":
        c.post(f"/api/admin/users/{username}/reset-password", headers=admin, json={"password": "temporal123"})
    elif accion == "revocar":
        c.delete(f"/api/admin/users/{username}/sessions", headers=admin)
    else:
        c.post(f"/api/admin/users/{username}/active", headers=admin, json={"active": False})

    assert passkeys_db.list_passkeys(username) == []
    assert db.push_subscriptions(username) == []
    assert c.get("/api/me", headers=headers).status_code == 401


def test_para_registrar_una_passkey_hace_falta_un_login_reciente(c):
    username, password = _usuario()
    token, headers = _login(c, username, password)
    assert c.post("/api/passkey/register/options", headers=headers).status_code == 200

    hace_una_hora = time.time() - 3600
    with db.conn() as cx:
        cx.execute("UPDATE auth_tokens SET created_at=%s WHERE token=%s", (hace_una_hora, db.hash_token(token)))

    assert c.post("/api/passkey/register/options", headers=headers).status_code == 403


def test_pedir_challenges_de_passkey_sin_parar_se_frena(c):
    for _ in range(limites.PEDIDOS_PASSKEY_POR_IP):
        assert c.post("/api/passkey/login/options").status_code == 200

    assert c.post("/api/passkey/login/options").status_code == 429


# --- subidas ----------------------------------------------------------------------------
def _grabacion(c, headers):
    return c.post("/api/sessions", headers=headers, json={"title": "Prueba", "kind": "Breakout"}).json()["id"]


@pytest.mark.parametrize("parts", [{"a": 1}, {"0": 10_000_000}, {"0": -1}, {str(i): 1 for i in range(201)}])
def test_terminar_rechaza_partes_invalidas_o_gigantes(c, parts):
    headers = login_headers(c)

    assert c.post(f"/api/sessions/{_grabacion(c, headers)}/finish", headers=headers, json={"parts": parts}).status_code == 422


def test_terminar_informa_los_pedazos_que_faltan(c):
    headers = login_headers(c)
    sid = _grabacion(c, headers)
    c.put(f"/api/sessions/{sid}/chunks/0/0", headers=headers, content=b"audio")

    r = c.post(f"/api/sessions/{sid}/finish", headers=headers, json={"parts": {"0": 3}})

    assert r.status_code == 409 and r.json()["detail"]["missing"] == {"0": [1, 2]}


def test_un_pedazo_que_declara_un_tamano_enorme_se_rechaza_sin_leerlo(c):
    headers = login_headers(c)
    sid = _grabacion(c, headers)

    r = c.put(f"/api/sessions/{sid}/chunks/0/0", content=b"x" * (config.MAX_CHUNK_BYTES + 1),
              headers={**headers, "Content-Type": "application/octet-stream"})

    assert r.status_code == 413


def test_los_intereses_del_perfil_tienen_tope(c):
    headers = login_headers(c)
    perfil = {"profile": {"interests": ["x" * 81]}, "prompt": ""}
    muchos = {"profile": {"interests": ["data"] * 31}, "prompt": ""}

    assert c.post("/api/itinerary/generate", headers=headers, json=perfil).status_code == 422
    assert c.post("/api/itinerary/generate", headers=headers, json=muchos).status_code == 422


# --- cabeceras ----------------------------------------------------------------------------
def test_todas_las_respuestas_llevan_cabeceras_de_seguridad(c):
    for ruta in ("/", "/health", "/api/me"):
        h = c.get(ruta).headers
        assert h["x-content-type-options"] == "nosniff"
        assert h["x-frame-options"] == "DENY"
        assert "frame-ancestors 'none'" in h["content-security-policy"]


def test_la_csp_permite_el_script_inline_de_index_por_su_hash():
    politica = cabeceras.politica()

    assert re.search(r"script-src 'self' 'sha256-[A-Za-z0-9+/=]{44}'", politica)
    assert "'unsafe-inline'" not in politica.split("script-src")[1].split(";")[0]


def test_csp_en_modo_report_no_bloquea(monkeypatch):
    monkeypatch.setattr(config, "CSP_MODO", "report")

    nombres = [k for k, _ in cabeceras.cabeceras()]

    assert b"content-security-policy-report-only" in nombres and b"content-security-policy" not in nombres


# --- push ---------------------------------------------------------------------------------
@pytest.mark.parametrize("endpoint,valido", [
    ("https://fcm.googleapis.com/fcm/send/abc", True),
    ("https://web.push.apple.com/QWx", True),
    ("https://updates.push.services.mozilla.com/wpush/v2/x", True),
    ("https://wns2-bl2p.notify.windows.com/w/?token=x", True),
    ("https://internal.railway.internal/admin", False),
    ("https://fcm.googleapis.com.evil.com/x", False),
    ("https://fcm.googleapis.com:8443/x", False),
    ("http://fcm.googleapis.com/x", False),
])
def test_solo_se_aceptan_servicios_de_push_conocidos(endpoint, valido):
    assert push_api.es_servicio_push(endpoint) is valido


def test_a_un_usuario_desactivado_no_le_llegan_avisos(c):
    username, _ = _usuario()
    db.save_push_subscription(username, f"https://fcm.googleapis.com/fcm/send/{uuid.uuid4().hex}", "p" * 87, "a" * 22)
    assert username in db.push_usernames()

    db.set_user_active(username, False)

    assert username not in db.push_usernames()


# --- Places y mapa ------------------------------------------------------------------------
def test_places_usa_la_key_del_servidor_sin_fingir_el_referer(monkeypatch):
    monkeypatch.setattr(config, "GOOGLE_PLACES_SERVER_KEY", "server-key")
    monkeypatch.setattr(config, "GOOGLE_MAPS_API_KEY", "browser-key")

    h = places._headers()

    assert h["X-Goog-Api-Key"] == "server-key" and "Referer" not in h


def test_el_mapa_no_arma_html_con_datos_externos():
    js = (Path(__file__).parents[1] / "web" / "js" / "map.js").read_text(encoding="utf-8")

    assert "setContent(`" not in js and "innerHTML" not in js
