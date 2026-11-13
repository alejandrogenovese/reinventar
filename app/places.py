"""Google Places (API New) desde el servidor, para ubicar "Mis eventos": autocompletar y detalle de un lugar.

Se llama desde el servidor para no depender de la librería de Places en el navegador. El detalle se pide una sola vez,
al dar de alta el evento: después las coordenadas salen de la base. El sessionToken (lo genera la PWA) agrupa el
autocompletar y el detalle en una sola sesión de facturación.
"""
import re

import httpx

from . import config

AUTOCOMPLETE_URL = "https://places.googleapis.com/v1/places:autocomplete"
DETAIL_URL = "https://places.googleapis.com/v1/places/{}"
DETAIL_FIELDS = "id,displayName,formattedAddress,location"
TIMEOUT_S = 10
MAX_SUGERENCIAS = 5
# Sesgo hacia Las Vegas (el Strip): los eventos de proveedores son ahí.
CENTRO = {"latitude": 36.1147, "longitude": -115.1728}
RADIO_M = 20000.0

PLACE_ID = re.compile(r"^[A-Za-z0-9_-]{10,300}$")
SESION = re.compile(r"^[A-Za-z0-9-]{8,64}$")


class PlacesNoDisponible(RuntimeError):
    """Sin key, o Google respondió con error (API no habilitada, sitio no permitido, cuota)."""


def _headers(campos: str | None = None) -> dict:
    if config.GOOGLE_PLACES_SERVER_KEY:  # la buena: key propia del servidor, sin Referer
        h = {"X-Goog-Api-Key": config.GOOGLE_PLACES_SERVER_KEY}
    elif config.GOOGLE_MAPS_API_KEY:
        h = {"X-Goog-Api-Key": config.GOOGLE_MAPS_API_KEY}
        if config.WEBAUTHN_ORIGIN:  # la key del navegador está restringida por sitio web: Google mira el Referer
            h["Referer"] = config.WEBAUTHN_ORIGIN.rstrip("/") + "/"
    else:
        raise PlacesNoDisponible("Falta GOOGLE_PLACES_SERVER_KEY (o GOOGLE_MAPS_API_KEY)")
    if campos:
        h["X-Goog-FieldMask"] = campos
    return h


def _respuesta(r: httpx.Response) -> dict:
    if r.status_code != 200:
        raise PlacesNoDisponible(f"Places respondió {r.status_code}: {r.text[:300]}")
    return r.json()


def leer_sugerencias(data: dict) -> list[dict]:
    """Solo lugares (placePrediction); las búsquedas sugeridas (queryPrediction) se descartan."""
    out = []
    for s in data.get("suggestions") or []:
        p = s.get("placePrediction")
        if not p or not p.get("placeId"):
            continue
        formato = p.get("structuredFormat") or {}
        out.append({"place_id": p["placeId"],
                    "nombre": (formato.get("mainText") or p.get("text") or {}).get("text", ""),
                    "direccion": (formato.get("secondaryText") or {}).get("text", "")})
    return out[:MAX_SUGERENCIAS]


def leer_lugar(data: dict) -> dict:
    loc = data.get("location") or {}
    return {"place_id": data.get("id"), "nombre": (data.get("displayName") or {}).get("text", ""),
            "direccion": data.get("formattedAddress", ""), "lat": loc.get("latitude"), "lng": loc.get("longitude")}


def autocomplete(q: str, sesion: str | None = None) -> list[dict]:
    body = {"input": q, "languageCode": "es", "includedRegionCodes": ["us"],
            "locationBias": {"circle": {"center": CENTRO, "radius": RADIO_M}}}
    if sesion and SESION.match(sesion):
        body["sessionToken"] = sesion
    try:
        r = httpx.post(AUTOCOMPLETE_URL, json=body, headers=_headers(), timeout=TIMEOUT_S)
    except httpx.HTTPError as e:
        raise PlacesNoDisponible(f"Sin conexión con Places: {e}") from e
    return leer_sugerencias(_respuesta(r))


def details(place_id: str, sesion: str | None = None) -> dict:
    if not PLACE_ID.match(place_id):
        raise ValueError("place_id inválido")
    params = {"languageCode": "es"}
    if sesion and SESION.match(sesion):
        params["sessionToken"] = sesion
    try:
        r = httpx.get(DETAIL_URL.format(place_id), params=params, headers=_headers(DETAIL_FIELDS), timeout=TIMEOUT_S)
    except httpx.HTTPError as e:
        raise PlacesNoDisponible(f"Sin conexión con Places: {e}") from e
    return leer_lugar(_respuesta(r))
