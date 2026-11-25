"""Envío de mails (verificación de mail y recuperación de contraseña), configurable por variables de entorno.

MAIL_PROVIDER:
  off    → no se manda nada y el mail no es obligatorio (default: un entorno sin configurar no deja a nadie afuera)
  fake   → para tests y desarrollo: los mails quedan en `enviados` (memoria), no salen. En Railway cuenta como off
  smtp   → cualquier servidor SMTP (SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, SMTP_SEGURIDAD)
  resend → API HTTP de Resend (RESEND_API_KEY)
En todos los reales, MAIL_FROM es el remitente («ReinventAR <no-responder@dominio>»).
"""
import logging
import smtplib
import ssl
from email.message import EmailMessage

import httpx

from . import config

log = logging.getLogger("reinventar.mail")

PROVEEDORES = ("off", "fake", "smtp", "resend")
RESEND_URL = "https://api.resend.com/emails"
TIMEOUT_SEGUNDOS = 15
ENVIADOS_MAXIMO = 50  # los de modo fake que se guardan en memoria (los tests leen el último)

# Modo fake: los últimos mails «enviados», para los tests y para verlos en desarrollo.
enviados: list[dict] = []


class MailNoEnviado(Exception):
    """El proveedor rechazó el mail o no se pudo hablar con él."""


def proveedor() -> str:
    """El proveedor configurado. fake en Railway cuenta como off: ahí nadie debe poder leer códigos en los logs."""
    valor = config.MAIL_PROVIDER.lower()
    if valor not in PROVEEDORES or (valor == "fake" and config.EN_PRODUCCION):
        return "off"
    return valor


def activo() -> bool:
    """¿Se pueden mandar mails? Si no, el mail no se exige y la recuperación de contraseña no manda nada."""
    return proveedor() != "off"


def estado_de(user: dict) -> dict:
    """Lo que ve la PWA en /api/me y en el login: su mail verificado y si tiene que cargarlo antes de seguir."""
    verificado = bool(user.get("email") and user.get("email_verificado_at"))
    return {"email": user.get("email") if verificado else None, "email_verificado": verificado,
            "debe_cargar_mail": activo() and not verificado}


def enviar(destino: str, asunto: str, texto: str) -> None:
    """Manda un mail de texto plano. Levanta MailNoEnviado si falla (quien llama decide qué hacer)."""
    tipo = proveedor()
    if tipo == "off":
        raise MailNoEnviado("MAIL_PROVIDER=off: no hay envío de mails configurado")
    if tipo == "fake":
        _fake(destino, asunto, texto)
    elif tipo == "smtp":
        _smtp(destino, asunto, texto)
    else:
        _resend(destino, asunto, texto)


def _fake(destino: str, asunto: str, texto: str) -> None:
    enviados.append({"para": destino, "asunto": asunto, "texto": texto})
    del enviados[:-ENVIADOS_MAXIMO]
    log.info("Mail (fake) a %s: %s", destino, asunto)  # sin el texto: lleva códigos y links de un solo uso


def _mensaje(destino: str, asunto: str, texto: str) -> EmailMessage:
    m = EmailMessage()
    m["From"], m["To"], m["Subject"] = config.MAIL_FROM, destino, asunto
    m.set_content(texto)
    return m


def _smtp(destino: str, asunto: str, texto: str) -> None:
    if not config.SMTP_HOST or not config.MAIL_FROM:
        raise MailNoEnviado("Faltan SMTP_HOST o MAIL_FROM")
    contexto = ssl.create_default_context()
    try:
        if config.SMTP_SEGURIDAD == "ssl":
            servidor = smtplib.SMTP_SSL(config.SMTP_HOST, config.SMTP_PORT, timeout=TIMEOUT_SEGUNDOS, context=contexto)
        else:
            servidor = smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=TIMEOUT_SEGUNDOS)
        with servidor:
            if config.SMTP_SEGURIDAD == "starttls":
                servidor.starttls(context=contexto)
            if config.SMTP_USER:
                servidor.login(config.SMTP_USER, config.SMTP_PASSWORD)
            servidor.send_message(_mensaje(destino, asunto, texto))
    except (smtplib.SMTPException, OSError) as e:
        raise MailNoEnviado(f"SMTP: {type(e).__name__}") from e


def _resend(destino: str, asunto: str, texto: str) -> None:
    if not config.RESEND_API_KEY or not config.MAIL_FROM:
        raise MailNoEnviado("Faltan RESEND_API_KEY o MAIL_FROM")
    try:
        r = httpx.post(RESEND_URL, timeout=TIMEOUT_SEGUNDOS,
                       headers={"Authorization": f"Bearer {config.RESEND_API_KEY}"},
                       json={"from": config.MAIL_FROM, "to": [destino], "subject": asunto, "text": texto})
    except httpx.HTTPError as e:
        raise MailNoEnviado(f"Resend: {type(e).__name__}") from e
    if r.status_code >= 300:
        raise MailNoEnviado(f"Resend contestó {r.status_code}")
