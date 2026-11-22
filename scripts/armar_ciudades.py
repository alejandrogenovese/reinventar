"""Arma app/datos/ciudades.json.gz desde cities15000.txt de GeoNames (ciudades de más de 15.000 habitantes).

Datos de GeoNames (https://www.geonames.org), licencia CC BY 4.0. Se bajan de
https://download.geonames.org/export/dump/cities15000.zip. Por ciudad se guarda: nombre, país (ISO 3166-1 alfa-2),
zona horaria IANA, población y los nombres alternativos que sirven para buscar (los de alfabeto latino, que incluyen
los nombres en castellano como «Nueva York» y los códigos de aeropuerto como «HOU»).

Uso: python scripts/armar_ciudades.py <cities15000.txt>
"""
import csv
import gzip
import json
import sys
import unicodedata
from pathlib import Path
from zoneinfo import available_timezones

DESTINO = Path(__file__).resolve().parent.parent / "app" / "datos" / "ciudades.json.gz"
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


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    zonas = available_timezones()
    ciudades = []
    with open(sys.argv[1], encoding="utf-8", newline="") as f:
        for fila in csv.reader(f, delimiter="\t", quoting=csv.QUOTE_NONE):
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
