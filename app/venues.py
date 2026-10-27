"""Coordenadas de los venues de re:Invent en el Strip de Las Vegas: no vienen en el catálogo, son fijas."""

VENUES = {
    "MGM Grand": {"lat": 36.0994, "lng": -115.1698, "address": "3799 Las Vegas Blvd S"},
    "Wynn/Encore": {"lat": 36.1271, "lng": -115.1655, "address": "3131 Las Vegas Blvd S"},
    "Caesars Forum": {"lat": 36.1225, "lng": -115.1665, "address": "3911 Koval Ln"},
    "Caesars Palace": {"lat": 36.1162, "lng": -115.1745, "address": "3570 Las Vegas Blvd S"},
    "Venetian": {"lat": 36.1211, "lng": -115.1693, "address": "3355 Las Vegas Blvd S"},
    "Allegiant Stadium": {"lat": 36.0909, "lng": -115.1833, "address": "3333 Al Davis Way"},
}


def resolve(venue_path: str) -> dict | None:
    """'MGM Grand|Level 3|Room 350' -> {hotel, detail, lat, lng, address}. lat/lng quedan en None si el hotel no está mapeado."""
    parts = [p.strip() for p in (venue_path or "").split("|") if p.strip()]
    if not parts:
        return None
    hotel = parts[0]
    coords = VENUES.get(hotel)
    return {
        "hotel": hotel,
        "detail": " · ".join(parts[1:]),
        "lat": coords["lat"] if coords else None,
        "lng": coords["lng"] if coords else None,
        "address": coords["address"] if coords else None,
    }
