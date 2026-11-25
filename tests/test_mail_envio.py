"""app/mail.py: el proveedor sale de MAIL_PROVIDER y ninguno real se usa en los tests (SMTP y Resend van simulados)."""
import httpx
import pytest

from app import config, mail


class SmtpFalso:
    enviados: list = []

    def __init__(self, host, port, timeout=None, context=None):
        self.host, self.port, self.tls, self.usuario = host, port, False, None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def starttls(self, context=None):
        self.tls = True

    def login(self, usuario, clave):
        self.usuario = usuario

    def send_message(self, mensaje):
        SmtpFalso.enviados.append((self, mensaje))


@pytest.fixture
def smtp(monkeypatch):
    SmtpFalso.enviados = []
    monkeypatch.setattr(mail.smtplib, "SMTP", SmtpFalso)
    for nombre, valor in {"MAIL_PROVIDER": "smtp", "MAIL_FROM": "App <no-responder@ejemplo.com>", "SMTP_HOST": "smtp.ejemplo",
                          "SMTP_USER": "usuario", "SMTP_SEGURIDAD": "starttls"}.items():
        monkeypatch.setattr(config, nombre, valor)
    return SmtpFalso


def test_proveedor_desconocido_cuenta_como_apagado(monkeypatch):
    monkeypatch.setattr(config, "MAIL_PROVIDER", "carta")

    assert (mail.proveedor(), mail.activo()) == ("off", False)


def test_apagado_no_manda_y_avisa(monkeypatch):
    monkeypatch.setattr(config, "MAIL_PROVIDER", "off")

    with pytest.raises(mail.MailNoEnviado):
        mail.enviar("a@ejemplo.com", "hola", "texto")


def test_smtp_usa_starttls_login_y_el_remitente_configurado(smtp):
    mail.enviar("a@ejemplo.com", "Asunto", "Cuerpo")

    servidor, mensaje = smtp.enviados[-1]
    assert (servidor.host, servidor.tls, servidor.usuario) == ("smtp.ejemplo", True, "usuario")
    assert (mensaje["To"], mensaje["From"], mensaje["Subject"]) == ("a@ejemplo.com", "App <no-responder@ejemplo.com>", "Asunto")


def test_smtp_sin_host_no_intenta_mandar(smtp, monkeypatch):
    monkeypatch.setattr(config, "SMTP_HOST", "")

    with pytest.raises(mail.MailNoEnviado):
        mail.enviar("a@ejemplo.com", "Asunto", "Cuerpo")
    assert not smtp.enviados


def test_resend_manda_por_http_con_la_clave(monkeypatch):
    pedidos = []
    monkeypatch.setattr(config, "MAIL_PROVIDER", "resend")
    monkeypatch.setattr(config, "MAIL_FROM", "no-responder@ejemplo.com")
    monkeypatch.setattr(config, "RESEND_API_KEY", "clave-de-prueba")
    monkeypatch.setattr(mail.httpx, "post", lambda url, **kw: pedidos.append((url, kw)) or httpx.Response(200))

    mail.enviar("a@ejemplo.com", "Asunto", "Cuerpo")

    url, kw = pedidos[-1]
    assert url == mail.RESEND_URL
    assert kw["headers"]["Authorization"] == "Bearer clave-de-prueba"
    assert kw["json"]["to"] == ["a@ejemplo.com"]


def test_resend_que_rechaza_levanta_mail_no_enviado(monkeypatch):
    monkeypatch.setattr(config, "MAIL_PROVIDER", "resend")
    monkeypatch.setattr(config, "MAIL_FROM", "no-responder@ejemplo.com")
    monkeypatch.setattr(config, "RESEND_API_KEY", "clave-de-prueba")
    monkeypatch.setattr(mail.httpx, "post", lambda url, **kw: httpx.Response(422))

    with pytest.raises(mail.MailNoEnviado):
        mail.enviar("a@ejemplo.com", "Asunto", "Cuerpo")
