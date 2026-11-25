"""Los mails de la cuenta, en HTML (el diseño aprobado) y con su alternativa de texto.

Tres mails: el código para confirmar el mail, el código para elegir una contraseña nueva y el aviso de contraseña
cambiada. Todos llevan abajo el apartado «Seguridad»: quién lo pidió, cuándo (hora de Las Vegas), desde qué navegador y
la IP enmascarada. El HTML usa solo tablas y estilos inline (Gmail e iOS Mail no leen <style> ni flex/grid de forma
pareja) y todo lo que viene del usuario (usuario, mail, User-Agent) pasa por html.escape.
"""
import datetime as dt
import html
import ipaddress
from dataclasses import dataclass

from . import config
from .mail import Mensaje
from .sandbox import EVENT_TZ

ACENTO = "#fa6400"
FONDO_CODIGO = "#ffe8d9"
TEXTO = "#1f1f1f"
TENUE = "#5f5f5f"
BORDE = "#e3e3e3"
UA_MAX = 512           # lo que se mira del User-Agent (el resto se ignora)
DESDE_MAX = 60         # largo máximo de «Safari en iPhone»
DESCONOCIDO = "navegador desconocido"
_DIAS = ("lun", "mar", "mié", "jue", "vie", "sáb", "dom")
_NUNCA = "ReinventAR nunca te va a pedir este código por WhatsApp, teléfono ni mail."

# El orden importa: Edge y Opera dicen «Chrome» y casi todos dicen «Safari».
_NAVEGADORES = (("Edg", "Edge"), ("OPR/", "Opera"), ("SamsungBrowser", "Samsung Internet"), ("FxiOS", "Firefox"),
                ("Firefox/", "Firefox"), ("CriOS", "Chrome"), ("Chrome/", "Chrome"), ("Safari/", "Safari"))
_SISTEMAS = (("iPhone", "iPhone"), ("iPad", "iPad"), ("Android", "Android"), ("Macintosh", "Mac"),
             ("Windows", "Windows"), ("CrOS", "ChromeOS"), ("Linux", "Linux"))


@dataclass(frozen=True)
class Origen:
    """De dónde salió el pedido: va en el apartado «Seguridad». ip y user_agent se capturan en el endpoint."""
    username: str
    ip: str
    user_agent: str
    momento: float
    buscado_por_mail: bool = False


# ---------- datos del apartado «Seguridad» ----------

def describir_ua(user_agent: str | None) -> str:
    """«Safari en iPhone», «Chrome en Mac», «Chrome en Android»; «navegador desconocido» si no se reconoce."""
    ua = (user_agent or "")[:UA_MAX]
    navegador = next((nombre for marca, nombre in _NAVEGADORES if marca in ua), None)
    sistema = next((nombre for marca, nombre in _SISTEMAS if marca in ua), None)
    if not navegador:
        return DESCONOCIDO
    texto = f"{navegador} en {sistema}" if sistema else navegador
    return texto[:DESDE_MAX]


def enmascarar_ip(ip: str | None) -> str:
    """181.45.xxx.xxx; en IPv6 los dos primeros bloques (2800:810:xxxx:…). «desconocida» si no es una IP."""
    try:
        direccion = ipaddress.ip_address((ip or "").strip())
    except ValueError:
        return "desconocida"
    if direccion.version == 4:
        a, b, *_ = str(direccion).split(".")
        return f"{a}.{b}.xxx.xxx"
    bloques = direccion.exploded.split(":")
    return f"{int(bloques[0], 16):x}:{int(bloques[1], 16):x}:xxxx:…"


def cuando(momento: float) -> str:
    """«mié 25/11/2026, 14:32 (hora de Las Vegas)»."""
    hora = dt.datetime.fromtimestamp(momento, EVENT_TZ)
    return f"{_DIAS[hora.weekday()]} {hora:%d/%m/%Y, %H:%M} (hora de Las Vegas)"


def _filas_seguridad(origen: Origen) -> list[tuple[str, str, str]]:
    """(rótulo, valor en texto, valor en HTML ya escapado), en el orden del diseño."""
    aclaracion = " (buscado por mail)" if origen.buscado_por_mail else ""
    momento, desde = cuando(origen.momento), describir_ua(origen.user_agent)
    ip = enmascarar_ip(origen.ip)
    return [("Pedido por el usuario", origen.username + aclaracion, f"<strong>{_e(origen.username)}</strong>{aclaracion}"),
            ("Cuándo", momento, _e(momento)), ("Desde", desde, _e(desde)),
            ("IP", ip, f'<span style="font-family:Menlo,Consolas,monospace;">{_e(ip)}</span>')]


# ---------- HTML ----------

def _e(valor) -> str:
    return html.escape(str(valor), quote=True)


def _p(contenido_html: str, tamano: int = 16, color: str = TEXTO, abajo: int = 18) -> str:
    return (f'<p style="margin:0 0 {abajo}px;font-size:{tamano}px;line-height:1.5;color:{color};">'
            f"{contenido_html}</p>")


def _caja_codigo(codigo: str, nota: str) -> str:
    return (f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin:0 0 18px;">'
            f'<tr><td align="center" style="background:{FONDO_CODIGO};border-radius:10px;padding:22px;">'
            f'<div style="font-family:Menlo,Consolas,monospace;font-size:40px;font-weight:700;letter-spacing:10px;'
            f'color:{TEXTO};">{_e(codigo)}</div>'
            f'<div style="font-size:13px;color:{TENUE};padding-top:6px;">{_e(nota)}</div></td></tr></table>')


def _seguridad_html(origen: Origen, aviso: str) -> str:
    filas = "".join(
        f'<tr><td style="padding:3px 12px 3px 0;color:{TENUE};width:150px;vertical-align:top;">{_e(rotulo)}</td>'
        f'<td style="padding:3px 0;">{valor_html}</td></tr>'
        for rotulo, _, valor_html in _filas_seguridad(origen))
    return (f'<tr><td style="border-top:1px solid {BORDE};background:#f9f9f9;padding:20px 28px 24px;">'
            f'<div style="font-size:13px;font-weight:700;text-transform:uppercase;letter-spacing:0.6px;'
            f'padding-bottom:10px;color:{TEXTO};">&#128737; Seguridad</div>'
            f'<table role="presentation" cellpadding="0" cellspacing="0" style="font-size:13px;line-height:1.4;'
            f'color:{TEXTO};">{filas}</table>'
            f'<p style="margin:12px 0 0;font-size:13px;line-height:1.5;color:{TENUE};">{_e(aviso)}</p></td></tr>')


def _documento(titulo: str, cuerpo: str, seguridad: str, pie: str) -> str:
    return (
        '<!doctype html><html lang="es"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{_e(titulo)}</title></head>"
        f'<body style="margin:0;padding:0;background:#f4f4f4;">'
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f4f4f4;">'
        f'<tr><td align="center" style="padding:24px 12px;">'
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:600px;'
        f"background:#ffffff;border:1px solid {BORDE};border-radius:12px;overflow:hidden;"
        f'font-family:Helvetica,Arial,sans-serif;color:{TEXTO};">'
        f'<tr><td style="background:#1a1a1a;padding:20px 28px;">'
        f'<span style="display:inline-block;width:10px;height:10px;border-radius:50%;background:{ACENTO};'
        f'vertical-align:middle;"></span>'
        f'<span style="color:#f4f4f4;font-size:20px;font-weight:700;letter-spacing:-0.2px;vertical-align:middle;'
        f'padding-left:10px;">ReinventAR</span></td></tr>'
        f'<tr><td style="padding:32px 28px 10px;">'
        f'<h1 style="margin:0 0 18px;font-size:24px;line-height:1.25;color:{TEXTO};">{_e(titulo)}</h1>'
        f"{cuerpo}</td></tr>{seguridad}</table>"
        f'<p style="max-width:600px;margin:14px auto 0;font-family:Helvetica,Arial,sans-serif;font-size:12px;'
        f'color:{TENUE};line-height:1.5;">{_e(pie)}</p>'
        "</td></tr></table></body></html>")


# ---------- texto plano ----------

def _seguridad_texto(origen: Origen, aviso: str) -> str:
    filas = "\n".join(f"{rotulo}: {valor}" for rotulo, valor, _ in _filas_seguridad(origen))
    return f"\n\n— SEGURIDAD —\n{filas}\n\n{aviso}"


# ---------- los tres mails ----------

def confirmar_mail(origen: Origen, email: str, codigo: str, minutos: int) -> Mensaje:
    titulo = "Confirmá tu mail"
    nota = f"Vence en {minutos} minutos · se puede usar una sola vez"
    cierre = ("Escribilo en la pantalla «Confirmá tu mail» de la app. Si no lo pediste vos, ignorá este mensaje: "
              "nadie puede usar tu mail sin este código.")
    aviso = f"¿No fuiste vos? No compartas el código con nadie y avisale a un admin. {_NUNCA}"
    pie = "Este mail lo manda ReinventAR porque alguien cargó esta dirección en la app. No respondas: la casilla no se lee."
    cuerpo = (_p(f"Hola <strong>{_e(origen.username)}</strong>: este es tu código para confirmar "
                 f"<strong>{_e(email)}</strong> en ReinventAR.")
              + _caja_codigo(codigo, nota) + _p(_e(cierre), 15, TENUE))
    texto = (f"{titulo}\n\nHola {origen.username}: este es tu código para confirmar {email} en ReinventAR.\n\n"
             f"    {codigo}\n\n{nota}.\n\n{cierre}" + _seguridad_texto(origen, aviso) + f"\n\n{pie}\n")
    return Mensaje(f"Tu código de ReinventAR: {codigo}", texto, _documento(titulo, cuerpo, _seguridad_html(origen, aviso), pie))


def recuperar_contrasena(origen: Origen, codigo: str, minutos: int, intentos: int) -> Mensaje:
    titulo = "Elegí una contraseña nueva"
    nota = f"Vence en {minutos} minutos · {intentos} intentos · una sola vez"
    pasos = ("Volvé a la app, a la pantalla «Recuperar contraseña».",
             f"Escribí el código y tu contraseña nueva ({config.PASSWORD_MIN_LENGTH} caracteres o más).",
             "Se cierran tus sesiones en los otros dispositivos y entrás con la nueva.")
    tranquilidad = "Tu contraseña actual sigue andando hasta que uses el código. Si no lo pediste vos, no hagas nada."
    aviso = ("¿No fuiste vos? Alguien sabe tu usuario o tu mail, pero sin este código no puede entrar. No se lo pases "
             f"a nadie y avisale a un admin. {_NUNCA}")
    pie = "Este mail lo manda ReinventAR a la dirección verificada de tu cuenta. No respondas: la casilla no se lee."
    lista = "".join(f'<li style="margin:0 0 4px;">{_e(p)}</li>' for p in pasos)
    cuerpo = (_p(f"Hola <strong>{_e(origen.username)}</strong>: alguien tocó «¿Olvidaste tu contraseña?» con tu "
                 "usuario. Si fuiste vos, usá este código en la app:")
              + _caja_codigo(codigo, nota)
              + f'<ol style="margin:0 0 18px;padding-left:20px;font-size:15px;line-height:1.6;color:{TEXTO};">{lista}</ol>'
              + f'<div style="background:#fdf1d8;border-radius:8px;padding:12px 14px;font-size:14px;line-height:1.5;'
                f'color:#3d2a00;margin:0 0 18px;">{_e(tranquilidad)}</div>')
    texto = (f"{titulo}\n\nHola {origen.username}: alguien tocó «¿Olvidaste tu contraseña?» con tu usuario. Si fuiste "
             f"vos, usá este código en la app:\n\n    {codigo}\n\n{nota}.\n\n"
             + "\n".join(f"{i}. {p}" for i, p in enumerate(pasos, 1))
             + f"\n\n{tranquilidad}" + _seguridad_texto(origen, aviso) + f"\n\n{pie}\n")
    asunto = f"Código para elegir una contraseña nueva: {codigo[:3]} {codigo[3:]}"
    return Mensaje(asunto, texto, _documento(titulo, cuerpo, _seguridad_html(origen, aviso), pie))


def contrasena_cambiada(origen: Origen) -> Mensaje:
    titulo = "Tu contraseña cambió"
    detalle = ("Se eligió una contraseña nueva para tu cuenta con un código de recuperación. Se cerraron tus sesiones "
               "en todos los dispositivos y se borraron tus passkeys.")
    aviso = ("¿No fuiste vos? Avisale ya a un admin para que bloquee la cuenta. ReinventAR nunca te va a pedir un "
             "código ni tu contraseña por WhatsApp, teléfono ni mail.")
    pie = "Este mail lo manda ReinventAR a la dirección verificada de tu cuenta. No respondas: la casilla no se lee."
    cuerpo = _p(f"Hola <strong>{_e(origen.username)}</strong>: {_e(detalle)}")
    texto = f"{titulo}\n\nHola {origen.username}: {detalle}" + _seguridad_texto(origen, aviso) + f"\n\n{pie}\n"
    return Mensaje("Tu contraseña de ReinventAR cambió", texto, _documento(titulo, cuerpo, _seguridad_html(origen, aviso), pie))
