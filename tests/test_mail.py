"""Mail obligatorio verificado con código y recuperación de contraseña por mail (MAIL_PROVIDER=fake: no sale nada)."""
import re
import time
import uuid

import pytest
from fastapi.testclient import TestClient

from app import config, db, limites, mail, mail_api, mail_db, passkeys_db, passwords
from app.main import app
from tests.conftest import TEST_ADMIN, TEST_ADMIN_PASSWORD, login_headers

CLAVE = "inicial123"


@pytest.fixture
def c():
    mail.enviados.clear()
    with TestClient(app) as cliente:
        yield cliente


def _usuario():
    username = f"m_{uuid.uuid4().hex[:8]}"
    salt, h = passwords.hash_password(CLAVE)
    db.create_user(username, salt, h, must_change_password=False)
    return username


def _mail_unico():
    return f"Persona.{uuid.uuid4().hex[:8]}@Ejemplo.com"


def _codigo_enviado() -> str:
    return re.search(r"\b(\d{6})\b", mail.enviados[-1]["texto"]).group(1)


def _token_enviado() -> str:
    return re.search(r"#/recuperar/([\w-]+)", mail.enviados[-1]["texto"]).group(1)


def _verificar(c, H, email):
    assert c.post("/api/me/email", headers=H, json={"email": email}).status_code == 200
    return c.post("/api/me/email/verificar", headers=H, json={"codigo": _codigo_enviado()})


# ---------- mail obligatorio ----------

def test_sin_mail_verificado_el_login_y_me_piden_cargarlo(c):
    username = _usuario()

    login = c.post("/api/login", json={"username": username, "password": CLAVE}).json()
    me = c.get("/api/me", headers={"Authorization": f"Bearer {login['token']}"}).json()

    assert (login["debe_cargar_mail"], me["debe_cargar_mail"], me["email_verificado"]) == (True, True, False)


def test_con_el_envio_apagado_no_se_exige_el_mail(c, monkeypatch):
    monkeypatch.setattr(config, "MAIL_PROVIDER", "off")
    H = login_headers(c, _usuario(), CLAVE)

    assert c.get("/api/me", headers=H).json()["debe_cargar_mail"] is False
    assert c.post("/api/me/email", headers=H, json={"email": _mail_unico()}).status_code == 503


def test_el_codigo_correcto_verifica_el_mail_normalizado(c):
    username = _usuario()
    H = login_headers(c, username, CLAVE)
    email = _mail_unico()

    r = _verificar(c, H, f"  {email}  ")

    assert r.status_code == 200, r.text
    assert mail.enviados[-1]["para"] == email.lower()
    me = c.get("/api/me", headers=H).json()
    assert (me["email"], me["email_verificado"], me["debe_cargar_mail"]) == (email.lower(), True, False)


@pytest.mark.parametrize("malo", ["sin-arroba", "a@b", "dos@@ejemplo.com", "con espacio@ejemplo.com", "x@ejemplo.com\nBcc: y"])
def test_rechaza_mails_mal_formados(c, malo):
    H = login_headers(c, _usuario(), CLAVE)

    assert c.post("/api/me/email", headers=H, json={"email": malo}).status_code == 422
    assert not mail.enviados


def test_un_mail_verificado_no_lo_puede_usar_otra_cuenta(c):
    email = _mail_unico()
    _verificar(c, login_headers(c, _usuario(), CLAVE), email)

    r = c.post("/api/me/email", headers=login_headers(c, _usuario(), CLAVE), json={"email": email.upper()})

    assert r.status_code == 409


def test_si_dos_cuentas_verifican_el_mismo_mail_a_la_vez_gana_la_primera(c):
    email = _mail_unico()
    H1, H2 = login_headers(c, _usuario(), CLAVE), login_headers(c, _usuario(), CLAVE)
    c.post("/api/me/email", headers=H1, json={"email": email})
    codigo1 = _codigo_enviado()
    c.post("/api/me/email", headers=H2, json={"email": email})
    codigo2 = _codigo_enviado()

    assert c.post("/api/me/email/verificar", headers=H1, json={"codigo": codigo1}).status_code == 200
    assert c.post("/api/me/email/verificar", headers=H2, json={"codigo": codigo2}).status_code == 409


def test_el_codigo_tiene_intentos_limitados(c):
    H = login_headers(c, _usuario(), CLAVE)
    c.post("/api/me/email", headers=H, json={"email": _mail_unico()})
    bueno = _codigo_enviado()
    malo = f"{(int(bueno) + 1) % 10 ** 6:06d}"

    estados = [c.post("/api/me/email/verificar", headers=H, json={"codigo": malo}).status_code
               for _ in range(mail_api.CODIGO_INTENTOS)]

    assert estados == [400] * (mail_api.CODIGO_INTENTOS - 1) + [410]
    assert c.post("/api/me/email/verificar", headers=H, json={"codigo": bueno}).status_code == 410


def test_el_codigo_vencido_no_sirve(c):
    username = _usuario()
    H = login_headers(c, username, CLAVE)
    c.post("/api/me/email", headers=H, json={"email": _mail_unico()})
    with db.conn() as conn:
        conn.execute("UPDATE mail_codigos SET vence=%s WHERE username=%s", (time.time() - 1, username))

    assert c.post("/api/me/email/verificar", headers=H, json={"codigo": _codigo_enviado()}).status_code == 410


def test_el_codigo_se_guarda_hasheado(c):
    username = _usuario()
    H = login_headers(c, username, CLAVE)
    c.post("/api/me/email", headers=H, json={"email": _mail_unico()})

    with db.conn() as conn:
        guardado = conn.execute("SELECT hash FROM mail_codigos WHERE username=%s", (username,)).fetchone()["hash"]

    assert _codigo_enviado() not in guardado


def test_los_envios_de_codigo_tienen_tope_por_usuario(c):
    H = login_headers(c, _usuario(), CLAVE)

    estados = [c.post("/api/me/email", headers=H, json={"email": _mail_unico()}).status_code
               for _ in range(limites.MAILS_VERIFICACION_POR_USUARIO + 1)]

    assert estados[-1] == 429
    assert len(mail.enviados) == limites.MAILS_VERIFICACION_POR_USUARIO


def test_admin_ve_si_cada_usuario_tiene_el_mail_verificado(c):
    username, email = _usuario(), _mail_unico()
    _verificar(c, login_headers(c, username, CLAVE), email)

    users = c.get("/api/admin/users", headers=login_headers(c, TEST_ADMIN, TEST_ADMIN_PASSWORD)).json()["users"]

    fila = next(u for u in users if u["username"] == username)
    assert fila["email"] == email.lower()
    assert fila["email_verificado_at"] is not None


# ---------- recuperación de contraseña ----------

def _con_mail_verificado(c):
    username, email = _usuario(), _mail_unico()
    _verificar(c, login_headers(c, username, CLAVE), email)
    mail.enviados.clear()
    return username, email.lower()


def test_olvide_responde_igual_exista_o_no_la_cuenta(c):
    username, _ = _con_mail_verificado(c)

    existe = c.post("/api/password/olvide", json={"usuario": username})
    no_existe = c.post("/api/password/olvide", json={"usuario": "nadie_por_aca"})

    assert existe.status_code == no_existe.status_code == 200
    assert existe.json() == no_existe.json()
    assert len(mail.enviados) == 1


def test_olvide_no_manda_nada_si_el_mail_no_esta_verificado(c):
    username = _usuario()

    c.post("/api/password/olvide", json={"usuario": username})

    assert not mail.enviados


def test_el_link_cambia_la_contrasena_cierra_sesiones_y_sirve_una_vez(c, monkeypatch):
    monkeypatch.setattr(config, "APP_URL", "https://staging.ejemplo")
    username, email = _con_mail_verificado(c)
    H = login_headers(c, username, CLAVE)
    passkeys_db.add_passkey(f"pk-{username}", username, b"clave", 0, "celu")
    c.post("/api/password/olvide", json={"usuario": email.upper()})
    assert mail.enviados[-1]["para"] == email
    assert "https://staging.ejemplo/#/recuperar/" in mail.enviados[-1]["texto"]
    token = _token_enviado()

    r = c.post("/api/password/restablecer", json={"token": token, "new_password": "nueva-clave-123"})
    otra_vez = c.post("/api/password/restablecer", json={"token": token, "new_password": "otra-clave-456"})

    assert r.status_code == 200, r.text
    assert otra_vez.status_code == 400
    assert c.get("/api/me", headers=H).status_code == 401
    assert c.post("/api/login", json={"username": username, "password": "nueva-clave-123"}).status_code == 200
    assert passkeys_db.list_passkeys(username) == []


def test_el_token_se_guarda_hasheado_y_vence(c):
    username, _ = _con_mail_verificado(c)
    c.post("/api/password/olvide", json={"usuario": username})
    token = _token_enviado()
    with db.conn() as conn:
        guardado = conn.execute("SELECT hash FROM mail_codigos WHERE username=%s AND tipo='recuperar'",
                                (username,)).fetchone()["hash"]
        conn.execute("UPDATE mail_codigos SET vence=%s WHERE username=%s", (time.time() - 1, username))

    assert guardado == mail_db.hash_token(token)
    assert c.post("/api/password/restablecer", json={"token": token, "new_password": "nueva-clave-123"}).status_code == 400


def test_pedir_otro_link_invalida_el_anterior(c):
    username, _ = _con_mail_verificado(c)
    c.post("/api/password/olvide", json={"usuario": username})
    viejo = _token_enviado()
    c.post("/api/password/olvide", json={"usuario": username})

    assert c.post("/api/password/restablecer", json={"token": viejo, "new_password": "nueva-clave-123"}).status_code == 400
    assert c.post("/api/password/restablecer", json={"token": _token_enviado(), "new_password": "nueva-clave-123"}).status_code == 200


def test_restablecer_aplica_el_largo_minimo_de_contrasena(c):
    username, _ = _con_mail_verificado(c)
    c.post("/api/password/olvide", json={"usuario": username})

    r = c.post("/api/password/restablecer", json={"token": _token_enviado(), "new_password": "corta"})

    assert r.status_code == 422


def test_olvide_tiene_tope_por_cuenta_exista_o_no(c):
    estados = [c.post("/api/password/olvide", json={"usuario": "cuenta_x"}).status_code
               for _ in range(limites.OLVIDE_POR_CUENTA + 1)]

    assert estados == [200] * limites.OLVIDE_POR_CUENTA + [429]


def test_en_railway_sin_url_configurada_no_arma_el_link_con_el_host_del_pedido(c, monkeypatch):
    monkeypatch.setattr(config, "EN_PRODUCCION", True)
    monkeypatch.setattr(config, "APP_URL", "")
    monkeypatch.setattr(config, "WEBAUTHN_ORIGIN", "")
    username, _ = _con_mail_verificado(c)

    c.post("/api/password/olvide", json={"usuario": username}, headers={"Host": "malo.example"})

    assert not mail.enviados
