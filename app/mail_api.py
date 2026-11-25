"""Mail de cada persona (obligatorio y verificado con un código) y recuperación de contraseña por mail.

- POST /api/me/email: normaliza y valida el mail, revisa que no lo tenga otra cuenta y manda un código de 6 dígitos
  (vence en CODIGO_MINUTOS, CODIGO_INTENTOS intentos). El mail se guarda en users recién al verificarlo.
- POST /api/me/email/verificar: con el código correcto, el mail queda verificado.
- POST /api/password/olvide: siempre la misma respuesta, exista o no la cuenta. Si existe, está activa y tiene el mail
  verificado, le llega un link de un solo uso que vence en TOKEN_MINUTOS. Todo el trabajo va después de responder
  (BackgroundTasks): ni el tiempo de respuesta dice si la cuenta existe.
- POST /api/password/restablecer: con un token vigente, cambia la contraseña, cierra todas las sesiones y borra las
  passkeys.
"""
import logging
import re
import secrets

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from . import config, db, limites, mail, mail_db, passwords
from .auth import auth
from .auth_api import cambiar_contrasena, ip_cliente

router = APIRouter()
log = logging.getLogger("reinventar.mail")

CODIGO_MINUTOS = 15
CODIGO_INTENTOS = 5
CODIGO_DIGITOS = 6
TOKEN_MINUTOS = 30
EMAIL_MAX = 254
# Formato razonable (algo@dominio.tld), sin espacios ni saltos de línea: la verificación real es el código.
# Solo caracteres comunes: nada de «,», «<», «"» o «;», que un cliente de mail lee como otro destinatario o un nombre.
_EMAIL = re.compile(r"^[a-z0-9._%+-]{1,64}@[a-z0-9-]+(\.[a-z0-9-]+)*\.[a-z]{2,}$")
_CODIGO = re.compile(rf"^\d{{{CODIGO_DIGITOS}}}$")
# Un link de recuperación recién mandado no se pisa con otro pedido: nadie puede anularle el link a la víctima.
TOKEN_ESPERA_SEGUNDOS = 120
CLAVE_LIMITE_MAX = 64
RESPUESTA_OLVIDE = ("Si hay una cuenta con ese usuario o mail y tiene el mail verificado, te mandamos un link para "
                    "elegir una contraseña nueva. Revisá tu correo (y el spam). El link vence en "
                    f"{TOKEN_MINUTOS} minutos.")


class EmailNuevo(BaseModel):
    email: str = Field(min_length=3, max_length=EMAIL_MAX)
    # Solo para cambiar un mail ya verificado: con un token robado no alcanza para llevarse la recuperación.
    current_password: str | None = Field(default=None, max_length=200)


class CodigoMail(BaseModel):
    codigo: str = Field(pattern=_CODIGO.pattern)


class Olvide(BaseModel):
    usuario: str = Field(min_length=1, max_length=EMAIL_MAX)


class Restablecer(BaseModel):
    token: str = Field(min_length=20, max_length=200)
    new_password: str = Field(min_length=config.PASSWORD_MIN_LENGTH, max_length=200)


def normalizar_email(valor: str) -> str:
    """Minúsculas y sin espacios alrededor; 422 si no tiene forma de mail."""
    email = valor.strip().lower()
    if len(email) > EMAIL_MAX or not _EMAIL.match(email):
        raise HTTPException(422, "Ese mail no parece válido. Revisalo (ejemplo: nombre@dominio.com).")
    return email


def _exigir_envio_activo() -> None:
    if not mail.activo():
        raise HTTPException(503, "El envío de mails no está configurado en este entorno.")


def _mandar(destino: str, asunto: str, texto: str) -> bool:
    try:
        mail.enviar(destino, asunto, texto)
        return True
    except mail.MailNoEnviado as e:
        log.exception("No se pudo mandar el mail (%s): %s", asunto, e)
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
def pedir_codigo(body: EmailNuevo, username: str = Depends(auth)):
    _exigir_envio_activo()
    email = normalizar_email(body.email)
    # El cupo va antes de revisar si el mail está en uso: así nadie puede probar mails ajenos sin límite.
    limites.exigir_cupo(limites.mails_verificacion, username, "códigos por mail")
    _exigir_contrasena_si_ya_verifico(username, body.current_password)
    otro = mail_db.usuario_por_email(email)
    if otro and otro["username"] != username:
        raise HTTPException(409, "Ese mail ya lo usa otra cuenta. Usá otro o pedile ayuda a un admin.")
    limites.exigir_cupo(limites.mails_destino, email, "códigos por mail")
    codigo = f"{secrets.randbelow(10 ** CODIGO_DIGITOS):0{CODIGO_DIGITOS}d}"
    mail_db.guardar_codigo(username, mail_db.VERIFICAR, mail_db.hash_codigo(username, codigo), email, CODIGO_MINUTOS * 60)
    texto = (f"Hola {username}:\n\nTu código para confirmar este mail en ReinventAR es {codigo}.\n"
             f"Vence en {CODIGO_MINUTOS} minutos. Si no fuiste vos, ignorá este mensaje.\n")
    if not _mandar(email, f"Tu código de ReinventAR: {codigo}", texto):
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

def _url_app(request: Request) -> str | None:
    """Base del link de recuperación. En Railway sale solo de la configuración (APP_URL o WEBAUTHN_ORIGIN): nunca del
    Host del pedido, que lo manda el cliente. Fuera de Railway (dev) se usa la URL del pedido."""
    base = config.APP_URL or config.WEBAUTHN_ORIGIN.rstrip("/")
    if base:
        return base
    return None if config.EN_PRODUCCION else str(request.base_url).rstrip("/")


def _buscar_cuenta(usuario: str) -> dict | None:
    valor = usuario.strip().lower()
    user = mail_db.usuario_por_email(valor) if "@" in valor else db.get_user(valor)
    if not user or not user["is_active"] or not user.get("email") or not user.get("email_verificado_at"):
        return None
    return user


def _mandar_link(usuario: str, base: str | None) -> None:
    """Corre después de responder. Si la cuenta no califica no hace nada (y nada de eso se ve desde afuera)."""
    user = _buscar_cuenta(usuario)
    if user is None:
        return
    if base is None:
        log.error("Falta APP_URL (o WEBAUTHN_ORIGIN): no se puede armar el link de recuperación")
        return
    if mail_db.token_reciente(user["username"], TOKEN_ESPERA_SEGUNDOS):
        return
    token = secrets.token_urlsafe(32)
    mail_db.guardar_codigo(user["username"], mail_db.RECUPERAR, mail_db.hash_token(token), user["email"],
                           TOKEN_MINUTOS * 60)
    texto = (f"Hola {user['username']}:\n\nPediste elegir una contraseña nueva para ReinventAR. Entrá a este link "
             f"(vence en {TOKEN_MINUTOS} minutos y sirve una sola vez):\n\n{base}/#/recuperar/{token}\n\n"
             "Si no fuiste vos, ignorá este mensaje: tu contraseña no cambia.\n")
    if not _mandar(user["email"], "Elegí una contraseña nueva para ReinventAR", texto):
        mail_db.borrar_codigo(user["username"], mail_db.RECUPERAR)


@router.post("/api/password/olvide", responses={429: {"description": "Demasiados pedidos"}})
def olvide(body: Olvide, request: Request, tareas: BackgroundTasks):
    cuenta = body.usuario.strip().lower()[:CLAVE_LIMITE_MAX]  # la clave del tope no crece con lo que mande el cliente
    if not limites.olvide_ip.consumir(ip_cliente(request)) or not limites.olvide_cuenta.consumir(cuenta):
        raise limites.demasiados_intentos()
    if mail.activo():
        tareas.add_task(_mandar_link, cuenta, _url_app(request))
    return {"ok": True, "mensaje": RESPUESTA_OLVIDE}


@router.post("/api/password/restablecer", responses={
    400: {"description": "Link inválido, usado o vencido"}, 429: {"description": "Demasiados pedidos"}})
def restablecer(body: Restablecer, request: Request):
    if not limites.restablecer_ip.consumir(ip_cliente(request)):
        raise limites.demasiados_intentos()
    vigente = mail_db.consumir_token(mail_db.hash_token(body.token.strip()))
    user = db.get_user(vigente["username"]) if vigente else None
    # El link vale solo para el mail al que se mandó: si después cambió, ya no sirve.
    if not user or not user["is_active"] or user.get("email") != vigente["email"]:
        raise HTTPException(400, "El link no es válido, ya se usó o venció. Pedí uno nuevo.")
    cambiar_contrasena(user["username"], body.new_password)
    limites.fallos_usuario.limpiar(user["username"])
    _mandar(user["email"], "Tu contraseña de ReinventAR cambió",
            f"Hola {user['username']}:\n\nSe eligió una contraseña nueva para tu cuenta y se cerraron todas tus "
            "sesiones. Si no fuiste vos, avisale ya a un admin.\n")
    return {"ok": True}
