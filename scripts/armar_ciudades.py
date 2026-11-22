"""Arma app/recursos/ciudades.json.gz con las ciudades de más de 15.000 habitantes de GeoNames (cities15000).

Datos de GeoNames (https://www.geonames.org), licencia CC BY 4.0. El script los baja de URL_GEONAMES. Por ciudad se guarda: nombre, país (ISO 3166-1 alfa-2),
zona horaria IANA, población y los nombres alternativos que sirven para buscar (los de alfabeto latino, que incluyen
los nombres en castellano como «Nueva York» y los códigos de aeropuerto como «HOU»).

Uso: python scripts/armar_ciudades.py (sin argumentos: baja el archivo y escribe siempre en el mismo lugar)
"""
import csv
import gzip
import io
import json
import unicodedata
import zipfile
from pathlib import Path
from zoneinfo import available_timezones

import httpx

DESTINO = Path(__file__).resolve().parent.parent / "app" / "recursos" / "ciudades.json.gz"
URL_GEONAMES = "https://download.geonames.org/export/dump/cities15000.zip"
TIMEOUT_DESCARGA_S = 120
# Los alias se guardan solo en ciudades grandes: son las que alguien busca por su nombre en otro idioma.
POBLACION_CON_ALIAS = 200_000
MAX_ALIAS = 400
LARGO_MAX_ALIAS = 40
# Nombres como se dicen en Argentina que GeoNames no trae (geonameid → alias).
ALIAS_EXTRA = {"3448439": ["San Pablo"]}  # São Paulo


def es_latino(texto: str) -> bool:
    return all(c.isascii() or unicodedata.name(c, "").startswith("LATIN") for c in texto if c.isalpha())


def alias(columna: str, nombre: str, poblacion: int) -> list[str]:
    vistos, salida = {nombre.casefold()}, []
    for a in columna.split(","):
        a = a.strip()
        es_codigo = len(a) == 3 and a.isupper() and a.isalpha()
        if not a or a.casefold() in vistos or len(a) > LARGO_MAX_ALIAS or not es_latino(a):
            continue
        if es_codigo or poblacion >= POBLACION_CON_ALIAS:
            vistos.add(a.casefold())
            salida.append(a)
    return salida[:MAX_ALIAS]


def bajar_geonames() -> str:
    r = httpx.get(URL_GEONAMES, timeout=TIMEOUT_DESCARGA_S, follow_redirects=True)
    r.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        return z.read("cities15000.txt").decode("utf-8")


def main() -> None:
    zonas = available_timezones()
    ciudades = []
    for fila in csv.reader(io.StringIO(bajar_geonames()), delimiter="\t", quoting=csv.QUOTE_NONE):
        nombre, alternativos, pais, poblacion, zona = fila[1], fila[3], fila[8], int(fila[14] or 0), fila[17]
        if zona not in zonas:
            continue
        extra = ALIAS_EXTRA.get(fila[0], [])
        ciudades.append([nombre, pais, zona, poblacion, extra + alias(alternativos, nombre, poblacion)])
    ciudades.sort(key=lambda c: -c[3])
    DESTINO.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(DESTINO, "wt", encoding="utf-8") as f:
        json.dump(ciudades, f, ensure_ascii=False, separators=(",", ":"))
    print(f"{len(ciudades)} ciudades → {DESTINO} ({DESTINO.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
