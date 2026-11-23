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


# ---- Búsqueda cercana (dónde comer): una llamada por celda, la cachea app/comer_api.py ----
NEARBY_URL = "https://places.googleapis.com/v1/places:searchNearby"
# Mínimo para listar: id, nombre, puntaje, cantidad de reseñas, precio, ubicación, dirección, si está abierto, link y
# reseñas (estas últimas cuestan más: se piden porque la lista muestra una o dos).
NEARBY_FIELDS = ",".join(f"places.{c}" for c in (
    "id", "displayName", "rating", "userRatingCount", "priceLevel", "location", "formattedAddress",
    "currentOpeningHours.openNow", "googleMapsUri", "reviews", "primaryTypeDisplayName"))
TIPOS_COMER = ["restaurant", "cafe", "fast_food_restaurant", "sandwich_shop", "pizza_restaurant", "bakery"]
# «Dónde comer» por tipo de lugar: (tipos que se piden, tipos principales que se dejan afuera). Son de la Tabla A de
# Places (New): uno que no exista hace fallar toda la búsqueda.
_COMIDA_RAPIDA = ["fast_food_restaurant", "hamburger_restaurant", "pizza_restaurant", "sandwich_shop",
                  "chicken_restaurant", "taco_restaurant", "hot_dog_restaurant", "food_court"]
TIPOS_POR_CATEGORIA = {
    "rapida": (_COMIDA_RAPIDA, []),
    "dulces": (["dessert_shop", "dessert_restaurant", "ice_cream_shop", "candy_store", "chocolate_shop",
                "confectionery", "donut_shop"], []),
    "cafe": (["cafe", "coffee_shop", "bakery", "bagel_shop", "tea_house", "juice_shop"], []),
    "restaurantes": (["restaurant", "buffet_restaurant", "deli"], _COMIDA_RAPIDA),
}
MAX_RESULTADOS = 20  # tope de searchNearby
# priceLevel de Places (New) → 1 = $, 2 = $$, 3 = $$$, 4 = $$$$; gratis cuenta como $. Sin dato o sin especificar → None.
NIVELES_PRECIO = {"PRICE_LEVEL_FREE": 1, "PRICE_LEVEL_INEXPENSIVE": 1, "PRICE_LEVEL_MODERATE": 2,
                  "PRICE_LEVEL_EXPENSIVE": 3, "PRICE_LEVEL_VERY_EXPENSIVE": 4}
MAX_RESENAS = 2
MAX_CARACTERES_RESENA = 160


def _resena_corta(r: dict) -> str | None:
    texto = ((r.get("text") or r.get("originalText") or {}).get("text") or "").strip()
    if not texto:
        return None
    return texto if len(texto) <= MAX_CARACTERES_RESENA else texto[:MAX_CARACTERES_RESENA].rstrip() + "…"


def leer_cercanos(data: dict) -> list[dict]:
    """Lugares sin coordenadas o sin id se descartan; las reseñas quedan en {texto, puntaje} y recortadas."""
    out = []
    for p in data.get("places") or []:
        loc = p.get("location") or {}
        if not p.get("id") or loc.get("latitude") is None or loc.get("longitude") is None:
            continue
        resenas = [{"texto": t, "puntaje": r.get("rating")} for r in (p.get("reviews") or [])
                   if (t := _resena_corta(r))][:MAX_RESENAS]
        out.append({"place_id": p["id"], "nombre": (p.get("displayName") or {}).get("text", ""),
                    "direccion": p.get("formattedAddress", ""), "lat": loc["latitude"], "lng": loc["longitude"],
                    "rating": p.get("rating"), "resenas": p.get("userRatingCount") or 0,
                    "precio": NIVELES_PRECIO.get(p.get("priceLevel")),
                    "abierto": (p.get("currentOpeningHours") or {}).get("openNow"),
                    "url": p.get("googleMapsUri"), "extracto": resenas,
                    "tipo": (p.get("primaryTypeDisplayName") or {}).get("text")})
    return out


def nearby(lat: float, lng: float, radio_m: float, tipos: list[str] | None = None,
           campos: str = NEARBY_FIELDS, excluir: list[str] | None = None) -> list[dict]:
    """`campos` es la field mask: define el SKU que cobra Google (las reseñas son el más caro). `excluir`: tipos
    principales que no entran (un restaurante cuyo tipo principal es comida rápida, por ejemplo)."""
    body = {"includedTypes": tipos or TIPOS_COMER, "maxResultCount": MAX_RESULTADOS, "languageCode": "es",
            "rankPreference": "POPULARITY",
            "locationRestriction": {"circle": {"center": {"latitude": lat, "longitude": lng}, "radius": float(radio_m)}}}
    if excluir:
        body["excludedPrimaryTypes"] = excluir
    try:
        r = httpx.post(NEARBY_URL, json=body, headers=_headers(campos), timeout=TIMEOUT_S)
    except httpx.HTTPError as e:
        raise PlacesNoDisponible(f"Sin conexión con Places: {e}") from e
    return leer_cercanos(_respuesta(r))
