"""Sedes de re:Invent con sus coordenadas, del maestro reinvent.sede (lo carga catalog.load junto con las sesiones)."""

LOAD_SQL = "SELECT id_sede, nombre, lat, lng, direccion FROM reinvent.sede ORDER BY id_sede"

_venues: dict[str, dict] = {}
_by_id: dict[int, dict] = {}


def _as_float(value) -> float | None:
    return float(value) if value is not None else None


def load(rows) -> None:
    """Reemplaza el maestro en memoria. rows: dicts con nombre, lat, lng y direccion (lat/lng numeric → float)."""
    global _venues, _by_id
    _venues = {r["nombre"]: {"lat": _as_float(r["lat"]), "lng": _as_float(r["lng"]), "address": r["direccion"]}
               for r in rows}
    _by_id = {r["id_sede"]: {"id": r["id_sede"], "name": r["nombre"], **_venues[r["nombre"]]} for r in rows}


def by_id(id_sede: int | None) -> dict | None:
    """{id, name, lat, lng, address} de una sede del maestro (None si no existe)."""
    return _by_id.get(id_sede) if id_sede is not None else None


def all_venues() -> list[dict]:
    return list(_by_id.values())


def resolve(venue_path: str) -> dict | None:
    """'MGM Grand|Level 3|Room 350' -> {hotel, detail, lat, lng, address}. lat/lng quedan en None si la sede no tiene
    coordenadas (Various Locations) o no está en el maestro."""
    parts = [p.strip() for p in (venue_path or "").split("|") if p.strip()]
    if not parts:
        return None
    hotel = parts[0]
    known = _venues.get(hotel, {})
    return {
        "hotel": hotel,
        "detail": " · ".join(parts[1:]),
        "lat": known.get("lat"),
        "lng": known.get("lng"),
        "address": known.get("address"),
    }
