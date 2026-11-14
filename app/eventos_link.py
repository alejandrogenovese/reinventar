"""Eventos sueltos por link (los que no están en Luma ni en conferenceparties, ej. la recepción de Red Hat).

El admin pega la URL; la app baja la página una vez, el LLM saca fecha, hora y lugar, y se guarda con plataforma
"link". Después app/eventos_auto.py vuelve a mirar la página en cada revisión: si da 404, cuenta como falta.

La descarga la pide un admin pero la hace el servidor, así que se cuida de no servir para llegar a la red interna:
solo https, sin IPs privadas, de loopback ni link-local (se valida cada redirección y la conexión va a la IP
validada, sin volver a resolver), con tope de tamaño y de tiempo total.
"""
import datetime as dt
import hashlib
import ipaddress
import socket
import time
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

import httpx

from . import llm, prompts
from .eventos_fuentes import TZ_VEGAS, Evento, datos_de_pagina
from .llm_router import Tarea

USER_AGENT = "ReinventAR/1.0 (agenda personal de re:Invent)"
MAX_BYTES = 2_000_000
MAX_REDIRECCIONES = 3
TIMEOUT_S = 15
MAX_SEGUNDOS = 30          # tope total de una descarga
MAX_TOKENS = 4000
PLATAFORMA = "link"

Resolver = Callable[[str], list[str]]


class LinkInvalido(ValueError):
    """La URL no se puede bajar desde el servidor (no es https, apunta a la red interna o la página no responde)."""


@dataclass(frozen=True)
class Pagina:
    status: int
    url: str      # la final, después de las redirecciones
    html: str


def resolver_dns(host: str) -> list[str]:
    try:
        return sorted({info[4][0] for info in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)})
    except (socket.gaierror, UnicodeError) as e:
        raise LinkInvalido("No encuentro ese sitio") from e


@dataclass(frozen=True)
class Destino:
    url: str      # la URL normalizada (la que se muestra y se guarda)
    host: str     # el nombre, para el header Host y el certificado (SNI)
    ip: str       # la IP validada: la conexión va a esta, no se vuelve a resolver


def validar_url(url: str, resolver: Resolver = resolver_dns) -> Destino:
    """El destino si se puede bajar; si no, LinkInvalido. Todas las IPs del nombre tienen que ser públicas."""
    try:
        partes = urlsplit((url or "").strip())
        puerto = partes.port
    except ValueError as e:
        raise LinkInvalido("El link no es válido") from e
    if partes.scheme != "https" or not partes.hostname:
        raise LinkInvalido("El link tiene que empezar con https://")
    if partes.username or partes.password or (puerto not in (None, 443)):
        raise LinkInvalido("El link no puede llevar usuario, contraseña ni otro puerto")
    ips = resolver(partes.hostname)
    try:
        direcciones = [ipaddress.ip_address(ip.split("%")[0]) for ip in ips]
    except ValueError as e:
        raise LinkInvalido("No encuentro ese sitio") from e
    if not direcciones:
        raise LinkInvalido("No encuentro ese sitio")
    if not all(d.is_global for d in direcciones):
        raise LinkInvalido("Ese link apunta a una dirección interna")
    return Destino(partes.geturl(), partes.hostname, str(direcciones[0]))


def _url_a_la_ip(d: Destino) -> str:
    """La misma URL pero contra la IP ya validada (así un DNS que cambia entre la validación y la conexión no
    sirve para llegar a la red interna). El certificado se valida contra el nombre por SNI."""
    partes = urlsplit(d.url)
    ip = f"[{d.ip}]" if ":" in d.ip else d.ip
    return partes._replace(netloc=ip).geturl()


def bajar(url: str, http: httpx.Client | None = None, resolver: Resolver = resolver_dns) -> Pagina:
    """Baja la página siguiendo como mucho MAX_REDIRECCIONES, validando cada salto. Corta en MAX_BYTES o a los
    MAX_SEGUNDOS en total (un servidor que manda de a un byte no traba la revisión)."""
    cliente = http or httpx.Client(timeout=httpx.Timeout(TIMEOUT_S, read=5), headers={"User-Agent": USER_AGENT})
    limite = time.monotonic() + MAX_SEGUNDOS
    try:
        for _ in range(MAX_REDIRECCIONES + 1):
            destino = validar_url(url, resolver)
            with cliente.stream("GET", _url_a_la_ip(destino), headers={"Host": destino.host},
                                extensions={"sni_hostname": destino.host}, follow_redirects=False) as r:
                if r.is_redirect and r.headers.get("location"):
                    url = urljoin(destino.url, r.headers["location"])
                    continue
                cuerpo = b""
                for parte in r.iter_bytes():
                    cuerpo += parte
                    if len(cuerpo) >= MAX_BYTES or time.monotonic() > limite:
                        break
                html = cuerpo[:MAX_BYTES].decode(r.encoding or "utf-8", errors="replace")
                return Pagina(r.status_code, destino.url, html)
        raise LinkInvalido("Demasiadas redirecciones")
    except (httpx.HTTPError, httpx.InvalidURL) as e:
        raise LinkInvalido("La página no respondió") from e
    finally:
        if http is None:
            cliente.close()


def id_de_link(url: str) -> str:
    return "link-" + hashlib.sha256(url.encode()).hexdigest()[:12]


# ---------- vista previa ----------

def _hora(valor) -> str | None:
    try:
        return dt.time.fromisoformat(str(valor)).strftime("%H:%M") if valor else None
    except ValueError:
        return None


def _fecha(valor) -> str | None:
    try:
        return dt.date.fromisoformat(str(valor)).isoformat() if valor else None
    except ValueError:
        return None


def _texto(valor, largo: int) -> str | None:
    texto = str(valor).strip() if valor is not None else ""
    return texto[:largo] or None


def leer_extraccion(respuesta: str) -> dict:
    """La respuesta del LLM, validada: lo que no tiene el formato esperado queda en None."""
    try:
        d = llm.parse_json(respuesta)
    except ValueError as e:
        raise LinkInvalido("No pude leer los datos del evento") from e
    if not isinstance(d, dict):
        raise LinkInvalido("No pude leer los datos del evento")
    lista = lambda v, n: [str(x).strip()[:80] for x in (v or []) if str(x).strip()][:n]  # noqa: E731
    return {
        "nombre": _texto(d.get("nombre"), 200), "fecha": _fecha(d.get("fecha")),
        "inicio": _hora(d.get("inicio")), "fin": _hora(d.get("fin")),
        "lugar": _texto(d.get("lugar"), 120), "direccion": _texto(d.get("direccion"), 200),
        "resumen_es": _texto(d.get("resumen_es"), 1200),
        "tipo": d.get("tipo") if d.get("tipo") in prompts.EVENT_TYPES else None,
        "temas": lista(d.get("temas"), 4), "organizadores": lista(d.get("organizadores"), 8),
    }


def vista_previa(url: str, http: httpx.Client | None = None, resolver: Resolver = resolver_dns,
                 extraer: Callable[[str, dict], str] | None = None) -> dict:
    """Los datos del evento para revisarlos antes de guardar. extraer(url, datos) → respuesta del LLM (tests)."""
    pagina = bajar(url, http, resolver)
    if pagina.status >= 400:
        raise LinkInvalido(f"La página respondió {pagina.status}")
    datos = datos_de_pagina(pagina.html)
    llamar = extraer or (lambda u, d: llm.complete(Tarea.CATALOGO, prompts.EVENT_LINK_SYSTEM,
                                                   prompts.event_link_user(u, d), MAX_TOKENS))
    return {**leer_extraccion(llamar(pagina.url, datos)), "url": pagina.url, "imagen": datos["imagen"],
            "descripcion": _texto(datos.get("descripcion"), 4000)}


def evento(datos: dict) -> Evento:
    """El Evento a guardar a partir de la vista previa (corregida por el admin). Exige nombre, fecha e inicio."""
    if not (datos.get("nombre") and datos.get("fecha") and datos.get("inicio")):
        raise LinkInvalido("Faltan el nombre, la fecha o la hora de inicio")
    dia = dt.date.fromisoformat(datos["fecha"])
    inicio = dt.datetime.combine(dia, dt.time.fromisoformat(datos["inicio"]), TZ_VEGAS)
    fin = dt.datetime.combine(dia, dt.time.fromisoformat(datos["fin"]), TZ_VEGAS) if datos.get("fin") else None
    if fin and fin <= inicio:
        fin += dt.timedelta(days=1)  # "21:00–01:00": termina al otro día
    imagen = datos.get("imagen")
    return Evento(id_evento=id_de_link(datos["url"]), plataforma=PLATAFORMA, url=datos["url"], nombre=datos["nombre"],
                  inicio=inicio, fin=fin, imagen_url=imagen if imagen and imagen.startswith("https://") else None,
                  lugar=datos.get("lugar"), direccion=datos.get("direccion"), descripcion=datos.get("descripcion"))
