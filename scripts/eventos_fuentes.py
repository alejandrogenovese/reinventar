"""Lectura de eventos de networking desde sus fuentes (funciones puras, sin base ni red).

Luma: el export (entries[] con name, start_at, cover_url, coordinate, href, event_api_id) trae lo básico; la página
pública del evento (JSON en <script id="__NEXT_DATA__">) suma fin, dirección, descripción, anotados, precio y aprobación.
Otra fuente se suma con su par de funciones desde_json_<fuente> / completar_con_pagina_<fuente>.
"""
import datetime as dt
import json
import re
from dataclasses import dataclass, replace

from app.travel import metros

_NEXT_DATA = re.compile(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.S)


@dataclass(frozen=True)
class Evento:
    id_evento: str
    plataforma: str
    url: str
    nombre: str
    inicio: dt.datetime
    fin: dt.datetime | None = None
    imagen_url: str | None = None
    lat: float | None = None
    lng: float | None = None
    lugar: str | None = None
    direccion: str | None = None
    direccion_exacta: bool = False
    google_place_id: str | None = None
    descripcion: str | None = None
    anotados: int | None = None
    lleno: bool = False
    precio: str | None = None
    requiere_aprobacion: bool = False


def _fecha(valor: str | None) -> dt.datetime | None:
    return dt.datetime.fromisoformat(valor.replace("Z", "+00:00")) if valor else None


def desde_json_luma(entrada: dict) -> Evento:
    coord = entrada.get("coordinate") or {}
    return Evento(
        id_evento=entrada["event_api_id"], plataforma="luma", url=entrada["href"], nombre=entrada["name"].strip(),
        inicio=_fecha(entrada["start_at"]), imagen_url=entrada.get("cover_url"),
        lat=coord.get("latitude"), lng=coord.get("longitude"))


def texto_de_mirror(nodo: dict | list | None) -> str:
    """Texto plano de una descripción en formato ProseMirror (párrafos separados por línea en blanco)."""
    if not nodo:
        return ""
    if isinstance(nodo, list):
        return "".join(texto_de_mirror(n) for n in nodo)
    tipo = nodo.get("type")
    if tipo == "text":
        return nodo.get("text", "")
    if tipo == "hard_break":
        return "\n"
    interior = texto_de_mirror(nodo.get("content"))
    if tipo == "list_item":
        return f"- {interior.strip()}\n"
    if tipo in ("paragraph", "heading", "bullet_list", "ordered_list", "blockquote"):
        return interior.strip() + "\n\n"
    return interior


def _precio(tickets: list[dict]) -> tuple[str | None, bool]:
    """("Gratis" | "USD 50" | None, requiere aprobación) a partir de los tipos de entrada."""
    if not tickets:
        return None, False
    aprobacion = any(t.get("require_approval") for t in tickets)
    pagos = [t for t in tickets if t.get("type") != "free" and t.get("cents")]
    if not pagos:
        return "Gratis", aprobacion
    barata = min(pagos, key=lambda t: t["cents"])
    return f"{(barata.get('currency') or 'usd').upper()} {barata['cents'] / 100:g}", aprobacion


def completar_con_pagina_luma(ev: Evento, html: str) -> Evento:
    """Suma lo que trae la página pública. Si la página no tiene los datos esperados, devuelve el evento como estaba."""
    m = _NEXT_DATA.search(html or "")
    if not m:
        return ev
    try:
        data = json.loads(m.group(1))["props"]["pageProps"]["initialData"]["data"]
        evento = data["event"]
    except (ValueError, KeyError, TypeError):
        return ev
    geo = evento.get("geo_address_info") or {}
    lugar = geo.get("address")
    exacta = bool(lugar) and lugar != geo.get("city")  # solo la ciudad = la dirección se ve al anotarte
    lugar_coord = geo.get("place_coordinate") or {}
    precio, aprobacion = _precio(data.get("ticket_types") or [])
    return replace(
        ev,
        fin=_fecha(evento.get("end_at")) or ev.fin,
        lugar=lugar if exacta else None,
        direccion=geo.get("full_address") if exacta else None,
        direccion_exacta=exacta,
        google_place_id=geo.get("place_id") if exacta else None,
        lat=lugar_coord.get("latitude", ev.lat) if exacta else ev.lat,
        lng=lugar_coord.get("longitude", ev.lng) if exacta else ev.lng,
        descripcion=texto_de_mirror(data.get("description_mirror")).strip() or None,
        anotados=data.get("guest_count"),
        lleno=bool(data.get("sold_out")),
        precio=precio,
        requiere_aprobacion=aprobacion,
    )


def sede_mas_cercana(ev: Evento, sedes: list[tuple[int, float, float]]) -> tuple[int | None, int | None]:
    """(id_sede, metros) de la sede de re:Invent más cercana; (None, None) sin coordenadas."""
    if ev.lat is None or not sedes:
        return None, None
    id_sede, dist = min(((i, metros((ev.lat, ev.lng), (lat, lng))) for i, lat, lng in sedes), key=lambda t: t[1])
    return id_sede, round(dist)
