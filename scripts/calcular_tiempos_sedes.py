"""Calcula una sola vez los minutos caminando entre las sedes de re:Invent y los guarda en reinvent.sede_tiempo.

Usa la Routes API de Google (computeRouteMatrix, a pie): una sola llamada con todas las sedes con coordenadas como
origen y destino (6 sedes = 30 pares, centavos). La app lee la tabla al cargar el catálogo (app/travel.py) y estima
por línea recta lo que falte. A Railway sube con el sync del catálogo (scripts/sync_to_railway.sh).

Por defecto corre en modo prueba: llama a la API, muestra la matriz y deshace todo (ROLLBACK).
Con --aplicar hace backup del schema (docker local) y confirma.

Uso (desde la raíz del repo):
  export REINVENT_DATABASE_URL='postgresql://reinvent:<clave>@localhost:5433/reinvent'
  export GOOGLE_MAPS_API_KEY=...        # la misma de la app, con la Routes API habilitada
  python -m scripts.calcular_tiempos_sedes             # prueba
  python -m scripts.calcular_tiempos_sedes --aplicar   # de verdad
"""
import argparse
import math
import os
import sys
from collections.abc import Callable
from dataclasses import dataclass

import httpx
import psycopg
from psycopg.rows import dict_row

from app import config
from scripts.actualizar_catalogo import _HOSTS_LOCALES, _backup, _schema, aplicar_migraciones

ROUTES_URL = "https://routes.googleapis.com/distanceMatrix/v2:computeRouteMatrix"
CAMPOS = "originIndex,destinationIndex,duration,distanceMeters,condition"
# Si la key está restringida por sitio web, Google mira el Referer: se manda el dominio de la app.
REFERER = os.environ.get("ROUTES_REFERER", "https://reinventar.app/")
TIMEOUT_S = 30


@dataclass(frozen=True)
class Sede:
    id_sede: int
    nombre: str
    lat: float
    lng: float


@dataclass(frozen=True)
class Tiempo:
    id_origen: int
    id_destino: int
    minutos: int
    metros: int


PedirMatriz = Callable[[dict], list[dict]]


def leer_sedes(conn: psycopg.Connection, schema: str = "reinvent") -> list[Sede]:
    """Sedes con coordenadas (Various Locations queda afuera). Corre las migraciones: deja la tabla destino creada."""
    aplicar_migraciones(conn, schema)
    filas = conn.execute("SELECT id_sede, nombre, lat, lng FROM sede WHERE lat IS NOT NULL ORDER BY id_sede").fetchall()
    return [Sede(f["id_sede"], f["nombre"], float(f["lat"]), float(f["lng"])) for f in filas]


def _punto(s: Sede) -> dict:
    return {"waypoint": {"location": {"latLng": {"latitude": s.lat, "longitude": s.lng}}}}


def armar_pedido(sedes: list[Sede]) -> dict:
    puntos = [_punto(s) for s in sedes]
    return {"origins": puntos, "destinations": puntos, "travelMode": "WALK"}


def _segundos(duracion: str) -> int:
    return int(duracion.removesuffix("s"))


def leer_matriz(elementos: list[dict], sedes: list[Sede]) -> list[Tiempo]:
    """Pares distintos con ruta, ordenados. La API omite los campos en cero (originIndex 0, por ejemplo)."""
    tiempos = []
    for e in elementos:
        o, d = e.get("originIndex", 0), e.get("destinationIndex", 0)
        if o == d or e.get("condition") != "ROUTE_EXISTS" or "duration" not in e:
            continue
        minutos = max(1, math.ceil(_segundos(e["duration"]) / 60))
        tiempos.append(Tiempo(sedes[o].id_sede, sedes[d].id_sede, minutos, int(e.get("distanceMeters", 1))))
    return sorted(tiempos, key=lambda t: (t.id_origen, t.id_destino))


def pedir_con_google(pedido: dict) -> list[dict]:
    r = httpx.post(ROUTES_URL, json=pedido, timeout=TIMEOUT_S, headers={
        "X-Goog-Api-Key": config.GOOGLE_MAPS_API_KEY, "X-Goog-FieldMask": CAMPOS, "Referer": REFERER})
    if r.status_code != 200:
        # El cuerpo del error de Google no incluye la key: se muestra para saber si falta habilitar la API o el sitio.
        sys.exit(f"La Routes API respondió {r.status_code}: {r.text[:500]}")
    return r.json()


def guardar(conn: psycopg.Connection, tiempos: list[Tiempo], schema: str = "reinvent") -> int:
    """Upsert de los pares medidos dentro de la transacción de conn; quien llama decide COMMIT o ROLLBACK."""
    aplicar_migraciones(conn, schema)
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO sede_tiempo (id_origen, id_destino, minutos, metros) VALUES (%s, %s, %s, %s) "
            "ON CONFLICT (id_origen, id_destino) DO UPDATE "
            "SET minutos = EXCLUDED.minutos, metros = EXCLUDED.metros, calculado = now()",
            [(t.id_origen, t.id_destino, t.minutos, t.metros) for t in tiempos])
    return len(tiempos)


def calcular(conn: psycopg.Connection, pedir: PedirMatriz, schema: str = "reinvent") -> tuple[list[Sede], list[Tiempo]]:
    sedes = leer_sedes(conn, schema)
    if len(sedes) < 2:
        sys.exit("Hacen falta al menos 2 sedes con coordenadas en reinvent.sede.")
    tiempos = leer_matriz(pedir(armar_pedido(sedes)), sedes)
    guardar(conn, tiempos, schema)
    return sedes, tiempos


def _imprimir(sedes: list[Sede], tiempos: list[Tiempo]) -> None:
    nombre = {s.id_sede: s.nombre for s in sedes}
    esperados = len(sedes) * (len(sedes) - 1)
    print(f"Pares medidos: {len(tiempos)} de {esperados}\n")
    for t in tiempos:
        print(f"  {nombre[t.id_origen]:<18} → {nombre[t.id_destino]:<18} {t.minutos:>3} min  {t.metros:>5} m")
    if len(tiempos) < esperados:
        print("\nLos pares que faltan se estiman en la app por línea recta.")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--aplicar", action="store_true", help="confirma (con backup previo); sin esto, ROLLBACK")
    ap.add_argument("--schema", default="reinvent")
    args = ap.parse_args()
    _schema(args.schema)  # valida el nombre antes de tocar nada

    url = os.environ.get("REINVENT_DATABASE_URL")
    if not url:
        sys.exit("Falta REINVENT_DATABASE_URL (Postgres del docker local).")
    if args.aplicar and not any(h in url for h in _HOSTS_LOCALES):
        sys.exit("--aplicar solo contra el docker local (localhost). A Railway se sube con scripts/sync_to_railway.sh.")
    if not config.GOOGLE_MAPS_API_KEY:
        sys.exit("Falta GOOGLE_MAPS_API_KEY (la misma de la app, con la Routes API habilitada).")

    backup = _backup(args.schema) if args.aplicar else None
    print("> " + ("APLICANDO cambios" if args.aplicar else "MODO PRUEBA (todo se deshace al final)") + "\n")
    with psycopg.connect(url, row_factory=dict_row) as conn:
        sedes, tiempos = calcular(conn, pedir_con_google, schema=args.schema)
        _imprimir(sedes, tiempos)
        if args.aplicar:
            conn.commit()
            print(f"\nListo. Backup previo: {backup}")
        else:
            conn.rollback()
            print("\nNo se cambió nada. Si está bien, corré lo mismo con --aplicar.")


if __name__ == "__main__":
    main()
