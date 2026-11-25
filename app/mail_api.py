"""Mail de cada persona (obligatorio y verificado con un código) y recuperación de contraseña con un código por mail.

- POST /api/me/email: normaliza y valida el mail, revisa que no lo tenga otra cuenta y manda un código de 6 dígitos
  (vence en CODIGO_MINUTOS, CODIGO_INTENTOS intentos). El mail se guarda en users recién al verificarlo.
- POST /api/me/email/verificar: con el código correcto, el mail queda verificado.
- POST /api/password/olvide: siempre la misma respuesta, exista o no la cuenta. Si existe, está activa y tiene el mail
  verificado, le llega un código de 6 dígitos (vence en RECUPERAR_MINUTOS, RECUPERAR_INTENTOS intentos, una sola vez).
  Todo el trabajo va después de responder (BackgroundTasks): ni el tiempo de respuesta dice si la cuenta existe.
- POST /api/password/restablecer: usuario o mail, código y contraseña nueva. Un código incorrecto, vencido, sin
  intentos o de una cuenta que no existe da siempre el mismo error. Si vale, cambia la contraseña, cierra todas las
  sesiones, borra las passkeys y avisa por mail.
Cada mail lleva el apartado «Seguridad» (app/mail_plantillas.py): la IP y el navegador se toman acá, en el endpoint.
"""
import logging
import re
import secrets
import time

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from . import config, db, limites, mail, mail_db, mail_plantillas, passwords
from .auth import auth
from .auth_api import cambiar_contrasena, ip_cliente
from .mail_plantillas import Origen

router = APIRouter()
log = logging.getLogger("reinventar.mail")

CODIGO_MINUTOS = 15
CODIGO_INTENTOS = 5
CODIGO_DIGITOS = 6
RECUPERAR_MINUTOS = 10
RECUPERAR_INTENTOS = 5
EMAIL_MAX = 254
# Formato razonable (algo@dominio.tld), sin espacios ni saltos de línea: la verificación real es el código.
# Solo caracteres comunes: nada de «,», «<», «"» o «;», que un cliente de mail lee como otro destinatario o un nombre.
_EMAIL = re.compile(r"^[a-z0-9._%+-]{1,64}@[a-z0-9-]+(\.[a-z0-9-]+)*\.[a-z]{2,}$")
_CODIGO = re.compile(rf"^\d{{{CODIGO_DIGITOS}}}$")
# Un código de recuperación recién mandado no se pisa con otro pedido: nadie puede anularle el código a la víctima.
RECUPERAR_ESPERA_SEGUNDOS = 120
CLAVE_LIMITE_MAX = 64
RESPUESTA_OLVIDE = ("Si hay una cuenta con ese usuario o mail y tiene el mail verificado, te mandamos un código de "
                    f"{CODIGO_DIGITOS} dígitos. Revisá tu correo (y el spam). Vence en {RECUPERAR_MINUTOS} minutos.")
# Igual para todo lo que falle al restablecer: no dice si la cuenta existe ni qué parte estuvo mal.
ERROR_RESTABLECER = "El código no es válido o ya venció. Revisalo o pedí uno nuevo."


class EmailNuevo(BaseModel):
    email: str = Field(min_length=3, max_length=EMAIL_MAX)
    # Solo para cambiar un mail ya verificado: con un token robado no alcanza para llevarse la recuperación.
    current_password: str | None = Field(default=None, max_length=200)


class CodigoMail(BaseModel):
    codigo: str = Field(pattern=_CODIGO.pattern)


class Olvide(BaseModel):
    usuario: str = Field(min_length=1, max_length=EMAIL_MAX)


class Restablecer(BaseModel):
    usuario: str = Field(min_length=1, max_length=EMAIL_MAX)
    codigo: str = Field(pattern=_CODIGO.pattern)
    new_password: str = Field(min_length=config.PASSWORD_MIN_LENGTH, max_length=200)


def normalizar_email(valor: str) -> str:
    """Minúsculas y sin espacios alrededor; 422 si no tiene forma de mail."""
    email = valor.strip().lower()
    if len(email) > EMAIL_MAX or not _EMAIL.match(email):
        raise HTTPException(422, "Ese mail no parece válido. Revisalo (ejemplo: nombre@dominio.com).")
    return email


def _origen(request: Request, username: str, buscado_por_mail: bool = False) -> Origen:
    """IP y navegador del pedido, tomados en el endpoint (la tarea en segundo plano ya no tiene el request)."""
    return Origen(username=username, ip=ip_cliente(request), user_agent=request.headers.get("user-agent", ""),
                  momento=time.time(), buscado_por_mail=buscado_por_mail)


def _nuevo_codigo() -> str:
    return f"{secrets.randbelow(10 ** CODIGO_DIGITOS):0{CODIGO_DIGITOS}d}"


def _exigir_envio_activo() -> None:
    if not mail.activo():
        raise HTTPException(503, "El envío de mails no está configurado en este entorno.")


def _mandar(destino: str, mensaje: mail.Mensaje) -> bool:
    try:
        mail.enviar(destino, mensaje)
        return True
    except mail.MailNoEnviado:
        log.exception("No se pudo mandar un mail de la cuenta")
        return False


# ---------- mail obligatorio ----------

def _exigir_contrasena_si_ya_verifico(username: str, contrasena: str | None) -> None:
    user = db.get_user(username)
    if not user.get("email_verificado_at"):
        return
    if not contrasena or not passwords.verify_password(contrasena, user["salt"], user["password_hash"]):
        raise HTTPException(403, "Para cambiar un mail ya confirmado hace falta tu contraseña actual.")


@router.post("/api/me/email", responses={
    403: {"description": "Cambiar un mail ya verificado pide la contraseña actual"},
    409: {"description": "Otra cuenta ya tiene ese mail"}, 422: {"description": "Mail inválido"},
    429: {"description": "Demasiados envíos"}, 502: {"description": "No se pudo mandar el mail"},
    503: {"description": "Envío de mails no configurado"}})
def pedir_codigo(body: EmailNuevo, request: Request, username: str = Depends(auth)):
    _exigir_envio_activo()
    email = normalizar_email(body.email)
    # El cupo va antes de revisar si el mail está en uso: así nadie puede probar mails ajenos sin límite.
    limites.exigir_cupo(limites.mails_verificacion, username, "códigos por mail")
    _exigir_contrasena_si_ya_verifico(username, body.current_password)
    otro = mail_db.usuario_por_email(email)
    if otro and otro["username"] != username:
        raise HTTPException(409, "Ese mail ya lo usa otra cuenta. Usá otro o pedile ayuda a un admin.")
    limites.exigir_cupo(limites.mails_destino, email, "códigos por mail")
    codigo = _nuevo_codigo()
    mail_db.guardar_codigo(username, mail_db.VERIFICAR, mail_db.hash_codigo(username, codigo), email, CODIGO_MINUTOS * 60)
    mensaje = mail_plantillas.confirmar_mail(_origen(request, username), email, codigo, CODIGO_MINUTOS)
    if not _mandar(email, mensaje):
        mail_db.borrar_codigo(username, mail_db.VERIFICAR)
        raise HTTPException(502, "No pudimos mandar el mail. Probá de nuevo en un rato.")
    return {"ok": True, "enviado_a": email, "vence_minutos": CODIGO_MINUTOS}


@router.post("/api/me/email/verificar", responses={
    400: {"description": "Código incorrecto"}, 409: {"description": "Otra cuenta verificó ese mail"},
    410: {"description": "Código vencido o sin intentos"}})
def verificar_codigo(body: CodigoMail, username: str = Depends(auth)):
    codigo = body.codigo
    vigente = mail_db.sumar_intento(username, mail_db.VERIFICAR, CODIGO_INTENTOS)
    if vigente is None:
        raise HTTPException(410, "El código venció o se usaron todos los intentos. Pedí uno nuevo.")
    if not secrets.compare_digest(vigente["hash"], mail_db.hash_codigo(username, codigo)):
        quedan = CODIGO_INTENTOS - vigente["intentos"]
        if quedan <= 0:
            mail_db.borrar_codigo(username, mail_db.VERIFICAR)
            raise HTTPException(410, "Código incorrecto y no quedan intentos. Pedí uno nuevo.")
        raise HTTPException(400, f"Código incorrecto. Te quedan {quedan} intentos.")
    try:
        mail_db.fijar_email(username, vigente["email"])
    except mail_db.MailEnUso as e:
        raise HTTPException(409, "Ese mail ya lo verificó otra cuenta.") from e
    finally:
        mail_db.borrar_codigo(username, mail_db.VERIFICAR)
    return {"ok": True, "email": vigente["email"]}


# ---------- recuperación de contraseña ----------

def _clave_cuenta(usuario: str) -> str:
    """Cómo se busca la cuenta (y la clave de su tope): minúsculas, sin espacios y con largo máximo."""
    return usuario.strip().lower()[:CLAVE_LIMITE_MAX]


def _buscar_cuenta(cuenta: str) -> dict | None:
    """La cuenta que puede recuperar: existe, está activa y tiene el mail verificado. None si no."""
    user = mail_db.usuario_por_email(cuenta) if "@" in cuenta else db.get_user(cuenta)
    if not user or not user["is_active"] or not user.get("email") or not user.get("email_verificado_at"):
        return None
    return user


def _mandar_codigo_recuperacion(cuenta: str, origen: Origen) -> None:
    """Corre después de responder. Si la cuenta no califica no hace nada (y nada de eso se ve desde afuera)."""
    user = _buscar_cuenta(cuenta)
    if user is None or mail_db.codigo_reciente(user["username"], mail_db.RECUPERAR, RECUPERAR_ESPERA_SEGUNDOS):
        return
    codigo = _nuevo_codigo()
    mail_db.guardar_codigo(user["username"], mail_db.RECUPERAR, mail_db.hash_codigo(user["username"], codigo),
                           user["email"], RECUPERAR_MINUTOS * 60)
    origen = Origen(user["username"], origen.ip, origen.user_agent, origen.momento, buscado_por_mail="@" in cuenta)
    mensaje = mail_plantillas.recuperar_contrasena(origen, codigo, RECUPERAR_MINUTOS, RECUPERAR_INTENTOS)
    if not _mandar(user["email"], mensaje):
        mail_db.borrar_codigo(user["username"], mail_db.RECUPERAR)


@router.post("/api/password/olvide", responses={429: {"description": "Demasiados pedidos"}})
def olvide(body: Olvide, request: Request, tareas: BackgroundTasks):
    cuenta = _clave_cuenta(body.usuario)
    if not limites.olvide_ip.consumir(ip_cliente(request)) or not limites.olvide_cuenta.consumir(cuenta):
        raise limites.demasiados_intentos()
    if mail.activo():
        tareas.add_task(_mandar_codigo_recuperacion, cuenta, _origen(request, ""))
    return {"ok": True, "mensaje": RESPUESTA_OLVIDE}


def _validar_codigo_recuperacion(user: dict | None, codigo: str) -> bool:
    """Gasta un intento y consume el código si coincide (una sola vez). Solo vale para el mail al que se mandó."""
    if user is None:
        return False
    username = user["username"]
    vigente = mail_db.sumar_intento(username, mail_db.RECUPERAR, RECUPERAR_INTENTOS)
    hash_ = mail_db.hash_codigo(username, codigo)
    if vigente is None or not secrets.compare_digest(vigente["hash"], hash_):
        return False
    return mail_db.consumir_codigo(username, mail_db.RECUPERAR, hash_) == user["email"]


@router.post("/api/password/restablecer", responses={
    400: {"description": "Código inválido, vencido o sin intentos (el mismo error exista o no la cuenta)"},
    429: {"description": "Demasiados pedidos"}})
def restablecer(body: Restablecer, request: Request):
    if not limites.restablecer_ip.consumir(ip_cliente(request)):
        raise limites.demasiados_intentos()
    user = _buscar_cuenta(_clave_cuenta(body.usuario))
    if not _validar_codigo_recuperacion(user, body.codigo):
        raise HTTPException(400, ERROR_RESTABLECER)
    cambiar_contrasena(user["username"], body.new_password)
    limites.fallos_usuario.limpiar(user["username"])
    _mandar(user["email"], mail_plantillas.contrasena_cambiada(_origen(request, user["username"])))
    return {"ok": True}
