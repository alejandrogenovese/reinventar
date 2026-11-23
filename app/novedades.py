"""Novedades por versión, leídas de CHANGELOG.md (formato Keep a Changelog), para la hoja «Novedades» de la PWA.

Cada ítem del CHANGELOG arranca con un título en negrita (**…**) y sigue con el detalle: se devuelve el título sin
asteriscos y el resto en una sola línea, sin markdown (los links quedan como su texto). «Sin publicar» se ignora.
El parseo se hace una vez por proceso: el archivo viene con la imagen y no cambia mientras corre.
"""
import functools
import re
from pathlib import Path

# En el contenedor: /srv/CHANGELOG.md (WORKDIR /srv, ver Dockerfile); en local y en los tests, la raíz del repo.
CHANGELOG = Path(__file__).resolve().parent.parent / "CHANGELOG.md"
MAX_ITEMS_POR_SECCION = 5
# Las secciones que muestra la PWA; «Arreglado» es el nombre viejo de «Corregido».
SECCIONES = {"Agregado": "Agregado", "Cambiado": "Cambiado", "Corregido": "Corregido", "Arreglado": "Corregido"}

_VERSION = re.compile(r"^## \[(\d+\.\d+\.\d+)\](?:\s*-\s*(\d{4}-\d{2}-\d{2}))?")
_SEMVER = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
_TITULO = re.compile(r"^\*\*(.+?)\*\*\s*(.*)$")
_LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")


def semver(texto: str) -> tuple[int, int, int] | None:
    m = _SEMVER.match(texto)
    return (int(m[1]), int(m[2]), int(m[3])) if m else None


def _limpiar(texto: str) -> str:
    """Una línea, sin negritas, código ni links de markdown."""
    sin_links = _LINK.sub(r"\1", texto)
    return " ".join(sin_links.replace("**", "").replace("`", "").split())


def _item(lineas: list[str]) -> dict:
    texto = " ".join(linea.strip().removeprefix("- ") for linea in lineas)
    m = _TITULO.match(texto)
    if not m:
        return {"titulo": "", "texto": _limpiar(texto)}
    return {"titulo": _limpiar(m[1]), "texto": _limpiar(m[2])}


def _cerrar_item(version: dict | None, seccion: str | None, lineas: list[str]) -> None:
    if version is not None and seccion and lineas:
        version["secciones"].setdefault(seccion, []).append(_item(lineas))


def parsear(texto: str) -> list[dict]:
    """[{version, fecha, secciones: {Agregado|Cambiado|Corregido: [{titulo, texto}]}}], de la más nueva a la más vieja."""
    versiones: list[dict] = []
    actual, seccion, lineas = None, None, []
    for linea in texto.splitlines():
        if linea.startswith("## "):
            _cerrar_item(actual, seccion, lineas)
            m = _VERSION.match(linea)
            actual = {"version": m[1], "fecha": m[2], "secciones": {}} if m else None  # None: «Sin publicar»
            if actual:
                versiones.append(actual)
            seccion, lineas = None, []
        elif linea.startswith("### "):
            _cerrar_item(actual, seccion, lineas)
            seccion, lineas = SECCIONES.get(linea[4:].strip()), []
        elif linea.startswith("- "):
            _cerrar_item(actual, seccion, lineas)
            lineas = [linea]
        elif linea.startswith(" ") and linea.strip():
            if lineas:
                lineas.append(linea)  # continuación (o sub-ítem) del ítem en curso
        else:  # línea en blanco o párrafo suelto: cierra el ítem
            _cerrar_item(actual, seccion, lineas)
            lineas = []
    _cerrar_item(actual, seccion, lineas)
    return [{**v, "secciones": {s: items[:MAX_ITEMS_POR_SECCION] for s, items in v["secciones"].items()}}
            for v in versiones]


@functools.cache
def todas(ruta: Path = CHANGELOG) -> tuple[dict, ...]:
    return tuple(parsear(ruta.read_text(encoding="utf-8")))


def posteriores(desde: tuple[int, int, int], ruta: Path = CHANGELOG) -> list[dict]:
    return [v for v in todas(ruta) if semver(v["version"]) > desde]
