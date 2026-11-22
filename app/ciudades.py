"""Ciudades del mundo con su zona horaria, para elegir de dónde sale un vuelo escribiendo («hou» → Houston).

Los datos son de GeoNames (https://www.geonames.org, CC BY 4.0): todas las ciudades de más de 15.000 habitantes, con
sus nombres alternativos (los de alfabeto latino, que incluyen «Nueva York», «San Pablo» y códigos como «HOU»). El
archivo lo arma scripts/armar_ciudades.py y se carga una sola vez, la primera vez que alguien busca.
"""
import gzip
import json
import unicodedata
from functools import cache
from pathlib import Path

ARCHIVO = Path(__file__).parent / "recursos" / "ciudades.json.gz"
LIMITE = 10
LARGO_MAX_CONSULTA = 60


def normalizar(texto: str) -> str:
    """Sin tildes ni mayúsculas: «São Paulo» y «sao paulo» se encuentran igual."""
    sin_tildes = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return " ".join(sin_tildes.casefold().split())


@cache
def _indice() -> list[tuple[str, str, str, tuple[str, ...]]]:
    """(nombre, país, zona, claves de búsqueda normalizadas), de la más poblada a la menos."""
    with gzip.open(ARCHIVO, "rt", encoding="utf-8") as f:
        crudo = json.load(f)
    return [(nombre, pais, zona, tuple(dict.fromkeys(normalizar(x) for x in [nombre, *alias])))
            for nombre, pais, zona, _poblacion, alias in crudo]


def _puntaje(q: str, claves: tuple[str, ...]) -> int | None:
    """Menor es mejor: un nombre tal cual (el propio, uno en otro idioma como «Nueva York» o un código como «HOU»),
    después uno que empieza así y al final una palabra del medio («york» → New York City). Dentro de cada nivel
    desempata la población."""
    if q in claves:
        return 0
    if any(c.startswith(q) for c in claves):
        return 1
    if any(p.startswith(q) for c in claves for p in c.split()[1:]):
        return 2
    return None


def buscar(consulta: str, limite: int = LIMITE) -> list[dict]:
    """Las ciudades que coinciden con lo escrito, las más pobladas primero dentro de cada nivel de coincidencia."""
    q = normalizar(consulta[:LARGO_MAX_CONSULTA])
    if not q:
        return []
    candidatas = []
    for orden, (nombre, pais, zona, claves) in enumerate(_indice()):
        puntaje = _puntaje(q, claves)
        if puntaje is not None:
            candidatas.append((puntaje, orden, {"nombre": nombre, "pais": pais, "zona": zona}))
    candidatas.sort(key=lambda c: (c[0], c[1]))
    return [c[2] for c in candidatas[:limite]]


def nombre_de_zona(zona: str) -> str:
    """Para vuelos cargados sin ciudad: «America/Argentina/Buenos_Aires» → «Buenos Aires»."""
    return zona.rsplit("/", 1)[-1].replace("_", " ")
