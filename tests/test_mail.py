"""Mail obligatorio verificado con código (MAIL_PROVIDER=fake: no sale nada)."""
import time

import pytest

from app import config, db, limites, mail, mail_api
from tests.apoyo_mail import CLAVE, c, codigo_enviado, mail_unico, usuario_nuevo, verificar
from tests.conftest import TEST_ADMIN, TEST_ADMIN_PASSWORD, login_headers

__all__ = ["c"]  # fixture compartida (tests/apoyo_mail.py)


# ---------- mail obligatorio ----------

def test_sin_mail_verificado_el_login_y_me_piden_cargarlo(c):
    username = usuario_nuevo()

    login = c.post("/api/login", json={"username": username, "password": CLAVE}).json()
    me = c.get("/api/me", headers={"Authorization": f"Bearer {login['token']}"}).json()

    assert (login["debe_cargar_mail"], me["debe_cargar_mail"], me["email_verificado"]) == (True, True, False)


def test_con_el_envio_apagado_no_se_exige_el_mail(c, monkeypatch):
    monkeypatch.setattr(config, "MAIL_PROVIDER", "off")
    H = login_headers(c, usuario_nuevo(), CLAVE)

    assert c.get("/api/me", headers=H).json()["debe_cargar_mail"] is False
    assert c.post("/api/me/email", headers=H, json={"email": mail_unico()}).status_code == 503


def test_el_codigo_correcto_verifica_el_mail_normalizado(c):
    username = usuario_nuevo()
    H = login_headers(c, username, CLAVE)
    email = mail_unico()

    r = verificar(c, H, f"  {email}  ")

    assert r.status_code == 200, r.text
    assert mail.enviados[-1]["para"] == email.lower()
    me = c.get("/api/me", headers=H).json()
    assert (me["email"], me["email_verificado"], me["debe_cargar_mail"]) == (email.lower(), True, False)


@pytest.mark.parametrize("malo", ["sin-arroba", "a@b", "dos@@ejemplo.com", "con espacio@ejemplo.com", "x@ejemplo.com\nBcc: y", "a,b@ejemplo.com", "x<y@ejemplo.com>", '"a"@ejemplo.com'])
def test_rechaza_mails_mal_formados(c, malo):
    H = login_headers(c, usuario_nuevo(), CLAVE)

    assert c.post("/api/me/email", headers=H, json={"email": malo}).status_code == 422
    assert not mail.enviados


def test_un_mail_verificado_no_lo_puede_usar_otra_cuenta(c):
    email = mail_unico()
    verificar(c, login_headers(c, usuario_nuevo(), CLAVE), email)

    r = c.post("/api/me/email", headers=login_headers(c, usuario_nuevo(), CLAVE), json={"email": email.upper()})

    assert r.status_code == 409


def test_si_dos_cuentas_verifican_el_mismo_mail_a_la_vez_gana_la_primera(c):
    email = mail_unico()
    H1, H2 = login_headers(c, usuario_nuevo(), CLAVE), login_headers(c, usuario_nuevo(), CLAVE)
    c.post("/api/me/email", headers=H1, json={"email": email})
    codigo1 = codigo_enviado()
    c.post("/api/me/email", headers=H2, json={"email": email})
    codigo2 = codigo_enviado()

    assert c.post("/api/me/email/verificar", headers=H1, json={"codigo": codigo1}).status_code == 200
    assert c.post("/api/me/email/verificar", headers=H2, json={"codigo": codigo2}).status_code == 409


def test_el_codigo_tiene_intentos_limitados(c):
    H = login_headers(c, usuario_nuevo(), CLAVE)
    c.post("/api/me/email", headers=H, json={"email": mail_unico()})
    bueno = codigo_enviado()
    malo = f"{(int(bueno) + 1) % 10 ** 6:06d}"

    estados = [c.post("/api/me/email/verificar", headers=H, json={"codigo": malo}).status_code
               for _ in range(mail_api.CODIGO_INTENTOS)]

    assert estados == [400] * (mail_api.CODIGO_INTENTOS - 1) + [410]
    assert c.post("/api/me/email/verificar", headers=H, json={"codigo": bueno}).status_code == 410


def test_el_codigo_vencido_no_sirve(c):
    username = usuario_nuevo()
    H = login_headers(c, username, CLAVE)
    c.post("/api/me/email", headers=H, json={"email": mail_unico()})
    with db.conn() as conn:
        conn.execute("UPDATE mail_codigos SET vence=%s WHERE username=%s", (time.time() - 1, username))

    assert c.post("/api/me/email/verificar", headers=H, json={"codigo": codigo_enviado()}).status_code == 410


def test_el_codigo_se_guarda_hasheado(c):
    username = usuario_nuevo()
    H = login_headers(c, username, CLAVE)
    c.post("/api/me/email", headers=H, json={"email": mail_unico()})

    with db.conn() as conn:
        guardado = conn.execute("SELECT hash FROM mail_codigos WHERE username=%s", (username,)).fetchone()["hash"]

    assert codigo_enviado() not in guardado


def test_los_envios_de_codigo_tienen_tope_por_usuario(c):
    H = login_headers(c, usuario_nuevo(), CLAVE)

    estados = [c.post("/api/me/email", headers=H, json={"email": mail_unico()}).status_code
               for _ in range(limites.MAILS_VERIFICACION_POR_USUARIO + 1)]

    assert estados[-1] == 429
    assert len(mail.enviados) == limites.MAILS_VERIFICACION_POR_USUARIO


def test_admin_ve_si_cada_usuario_tiene_el_mail_verificado(c):
    username, email = usuario_nuevo(), mail_unico()
    verificar(c, login_headers(c, username, CLAVE), email)

    users = c.get("/api/admin/users", headers=login_headers(c, TEST_ADMIN, TEST_ADMIN_PASSWORD)).json()["users"]

    fila = next(u for u in users if u["username"] == username)
    assert fila["email"] == email.lower()
    assert fila["email_verificado_at"] is not None


def test_cambiar_un_mail_ya_verificado_pide_la_contrasena(c):
    username = usuario_nuevo()
    H = login_headers(c, username, CLAVE)
    verificar(c, H, mail_unico())

    sin = c.post("/api/me/email", headers=H, json={"email": mail_unico()})
    con = c.post("/api/me/email", headers=H, json={"email": mail_unico(), "current_password": CLAVE})

    assert (sin.status_code, con.status_code) == (403, 200)


def test_el_modo_fake_no_se_usa_en_railway(monkeypatch):
    monkeypatch.setattr(config, "MAIL_PROVIDER", "fake")
    monkeypatch.setattr(config, "EN_PRODUCCION", True)

    assert mail.activo() is False
