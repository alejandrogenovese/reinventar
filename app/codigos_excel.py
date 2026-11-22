"""«Mis códigos de sesión»: leer los códigos de un Excel o CSV y cruzarlos con el catálogo y con lo registrado.

Todo son funciones puras: el catálogo y el itinerario entran como datos (ver app/codigos_api.py), así se prueban sin
el schema reinvent. El archivo se lee solo como datos: openpyxl en modo solo lectura y con los valores ya calculados
(`data_only`), sin evaluar fórmulas ni macros.
"""
import csv
import io
import re
import zipfile
from dataclasses import dataclass

from . import itinerary

MAX_BYTES = 1024 * 1024
MAX_DESCOMPRIMIDO = 50 * 1024 * 1024  # un .xlsx es un zip: se corta antes de abrir uno que se infla de más
MAX_FILAS = 5000
MAX_COLUMNAS = 50   # un archivo puede declarar 16384 columnas: openpyxl rellena cada fila hasta ese ancho
MAX_HOJAS = 10
MAX_CELDAS = 250_000  # celdas con algo, entre todas las hojas
MAX_CODIGOS = 500
EXTENSIONES = (".xlsx", ".csv")
_MAGIC_XLSX = b"PK\x03\x04"
_GUIONES = str.maketrans({c: "-" for c in "–—‑−"})
# Igual que el patrón de nl_filters, pero con -R sin número (DAT402-R) y bordes de palabra para no tomar pedazos de otras cosas.
_CODIGO = re.compile(r"(?<![A-Z0-9])([A-Z]{3}\d{3})(?:-(R\d*|S))?(?![A-Z0-9])")


class ArchivoInvalido(ValueError):
    """El archivo no sirve; el mensaje se le muestra tal cual a la persona."""


@dataclass(frozen=True)
class Codigo:
    base: str      # AIM301: lo que identifica a la charla
    completo: str  # AIM301-R1: con el sufijo, para mostrar y para elegir el horario


def _armar(m: re.Match) -> Codigo:
    return Codigo(m.group(1), m.group(1) + (f"-{m.group(2)}" if m.group(2) else ""))


def normalizar(texto: str) -> list[Codigo]:
    """Todos los códigos que aparecen en el texto, en mayúsculas y sin espacios. Un texto que es solo un código
    escrito con espacios ("dat 402 - r") también vale."""
    limpio = texto.translate(_GUIONES).upper()
    codigos = [_armar(m) for m in _CODIGO.finditer(limpio)]
    if codigos:
        return codigos
    junto = _CODIGO.fullmatch(re.sub(r"\s+", "", limpio))
    return [_armar(junto)] if junto else []


# ---------- lectura del archivo ----------

def _sin_vacias_al_final(fila: tuple) -> list:
    """La fila sin las celdas vacías del final (el relleno hasta el ancho declarado no cuenta ni se guarda)."""
    fila = list(fila)
    while fila and fila[-1] is None:
        fila.pop()
    return fila


def _filas_xlsx(datos: bytes) -> list[list[list]]:
    """Por hoja, las filas con los valores de las celdas (las fórmulas sin calcular quedan vacías)."""
    import openpyxl  # diferido: solo hace falta al subir un Excel

    if not datos.startswith(_MAGIC_XLSX):
        raise ArchivoInvalido("El archivo no es un Excel .xlsx válido.")
    try:
        if sum(i.file_size for i in zipfile.ZipFile(io.BytesIO(datos)).infolist()) > MAX_DESCOMPRIMIDO:
            raise ArchivoInvalido("El Excel es demasiado grande por dentro.")
        libro = openpyxl.load_workbook(io.BytesIO(datos), read_only=True, data_only=True)
        try:
            if len(libro.worksheets) > MAX_HOJAS:
                raise ArchivoInvalido(f"El Excel tiene demasiadas hojas (máximo {MAX_HOJAS}).")
            hojas, celdas = [], 0
            for hoja in libro.worksheets:
                filas = []
                for fila in hoja.iter_rows(max_col=MAX_COLUMNAS, values_only=True):
                    if len(filas) >= MAX_FILAS:
                        raise ArchivoInvalido(f"El archivo tiene demasiadas filas (máximo {MAX_FILAS}).")
                    fila = _sin_vacias_al_final(fila)
                    celdas += len(fila)
                    if celdas > MAX_CELDAS:
                        raise ArchivoInvalido("El Excel tiene demasiadas celdas: subí solo la hoja con los códigos.")
                    filas.append(fila)
                hojas.append(filas)
            return hojas
        finally:
            libro.close()
    except ArchivoInvalido:
        raise
    except Exception as e:  # openpyxl/zipfile levantan de todo con un archivo roto o armado a propósito
        raise ArchivoInvalido("No pude leer el archivo como un Excel .xlsx.") from e


def _filas_csv(datos: bytes) -> list[list[list]]:
    if b"\x00" in datos:
        raise ArchivoInvalido("El archivo no es un CSV de texto.")
    try:
        texto = datos.decode("utf-8-sig")
    except UnicodeDecodeError:
        texto = datos.decode("latin-1")
    try:
        delimitador = csv.Sniffer().sniff(texto[:4096], delimiters=",;\t|").delimiter
    except csv.Error:
        delimitador = ","
    filas = []
    try:
        for fila in csv.reader(io.StringIO(texto), delimiter=delimitador):
            if len(filas) >= MAX_FILAS:
                raise ArchivoInvalido(f"El archivo tiene demasiadas filas (máximo {MAX_FILAS}).")
            filas.append(fila[:MAX_COLUMNAS])
    except csv.Error as e:  # p. ej. un campo de más de 128 KB
        raise ArchivoInvalido("No pude leer el archivo como un CSV: tiene un campo demasiado largo o está mal armado.") from e
    return [filas]


@dataclass(frozen=True)
class Lectura:
    codigos: list[Codigo]      # los de la columna elegida, sin repetir
    descartados: list[Codigo]  # los que están en otras columnas u hojas y no entraron (sin repetir)


def _columnas(hojas: list[list[list]]) -> list[list[list[Codigo]]]:
    """Por cada columna de cada hoja que trae algún código, los códigos de cada celda, en el orden del archivo."""
    columnas = []
    for filas in hojas:
        por_columna: dict[int, list[list[Codigo]]] = {}
        for fila in filas:
            for i, celda in enumerate(fila):
                if isinstance(celda, str) and (codigos := normalizar(celda)):
                    por_columna.setdefault(i, []).append(codigos)
        columnas.extend(por_columna.values())
    return columnas


def _sin_repetir_por_base(codigos: list[Codigo]) -> list[Codigo]:
    """Un código por charla (aunque cambie el sufijo): queda el primero que aparece, en el orden del archivo."""
    vistos: dict[str, Codigo] = {}
    for c in codigos:
        vistos.setdefault(c.base, c)
    return list(vistos.values())


def _elegir(hojas: list[list[list]]) -> Lectura:
    """La columna (de cualquier hoja) con más celdas con código; si empatan, la primera. Lo de las demás se informa."""
    columnas = _columnas(hojas)
    if not columnas:
        return Lectura([], [])
    mejor = max(range(len(columnas)), key=lambda i: (len(columnas[i]), -i))  # más celdas; en empate, la primera
    planas = [[c for celda in col for c in celda] for col in columnas]
    elegidos = _sin_repetir_por_base(planas[mejor])
    bases = {c.base for c in elegidos}
    otros = [c for i, col in enumerate(planas) if i != mejor for c in col if c.base not in bases]
    return Lectura(elegidos, _sin_repetir_por_base(otros))


def leer_codigos(datos: bytes, nombre: str) -> Lectura:
    """Los códigos del archivo, sin repetir, en el orden en que aparecen, y los que quedaron afuera. ArchivoInvalido si no sirve."""
    if not datos:
        raise ArchivoInvalido("El archivo está vacío.")
    if len(datos) > MAX_BYTES:
        raise ArchivoInvalido(f"El archivo es demasiado grande (máximo {MAX_BYTES // 1024 // 1024} MB).")
    extension = ("." + nombre.rsplit(".", 1)[-1]).lower() if "." in nombre else ""
    if extension not in EXTENSIONES:
        raise ArchivoInvalido("Subí un archivo .xlsx o .csv.")
    hojas = _filas_xlsx(datos) if extension == ".xlsx" else _filas_csv(datos)
    lectura = _elegir(hojas)
    if not lectura.codigos:
        raise ArchivoInvalido("No encontré códigos de sesión en el archivo. Tienen que verse como AIM301 o DAT402-R.")
    if len(lectura.codigos) > MAX_CODIGOS:
        raise ArchivoInvalido(f"Hay más de {MAX_CODIGOS} códigos distintos: subí una lista más corta.")
    return lectura


def extraer_codigos(datos: bytes, nombre: str) -> list[Codigo]:
    """Solo los códigos de la columna elegida (ver leer_codigos)."""
    return leer_codigos(datos, nombre).codigos


# ---------- cruce ----------

def _duracion(inst: dict, tipo: str | None) -> int:
    inicio, fin = inst.get("st"), inst.get("en")
    if inicio and fin:
        minutos = itinerary._minutes(fin) - itinerary._minutes(inicio)
        if minutos > 0:
            return minutos
    return itinerary._duration(tipo or "")


def _candidatos(codigo: Codigo, sesion: dict, registrado: str | None) -> list[dict]:
    """Los horarios en los que podría estar: el que ya registré; si no, el que pidió el sufijo; si no, todos los vigentes."""
    todos = sesion.get("instances") or []
    vigentes = [i for i in todos if not i.get("cancelada")] or list(todos)
    if registrado:
        elegido = [i for i in todos if i.get("c") == registrado]
        if elegido:
            return elegido
    if codigo.completo != codigo.base:
        pedido = [i for i in vigentes if i.get("c") == codigo.completo]
        if pedido:
            return pedido
    return vigentes


def _se_pisan(a: dict, tipo_a: str | None, b: dict, tipo_b: str | None) -> bool:
    if not (a.get("d") and a.get("st") and b.get("d") and b.get("st")):
        return False
    tomado = (b["d"], itinerary._minutes(b["st"]), _duracion(b, tipo_b), b.get("c"))
    return itinerary._conflict(a["d"], a["st"], _duracion(a, tipo_a), [tomado]) is not None


def _chocan(a: tuple[list[dict], str | None], b: tuple[list[dict], str | None]) -> bool:
    """Chocan solo si no hay forma de ir a los dos: todas las combinaciones de horarios se pisan."""
    return bool(a[0]) and bool(b[0]) and all(_se_pisan(ia, a[1], ib, b[1]) for ia in a[0] for ib in b[0])


def _sala(inst: dict) -> str | None:
    return (inst.get("v") or "").replace("|", " · ") or None


def _entrada(codigo: Codigo, sesion: dict | None, candidatos: list[dict], registrado: str | None) -> dict:
    base = {"codigo": codigo.completo, "base": codigo.base}
    if sesion is None:
        return {**base, "estado": "inexistente", "titulo": None, "tipo": None, "dia": None, "inicio": None, "fin": None,
                "sala": None, "instancia": None}
    inst = min(candidatos, key=lambda i: (i.get("d") or "", i.get("st") or "")) if candidatos else {}
    return {**base, "estado": "registrado" if registrado else "falta", "titulo": sesion.get("title"),
            "tipo": sesion.get("type"), "dia": inst.get("d"), "inicio": inst.get("st"), "fin": inst.get("en"),
            "sala": _sala(inst), "instancia": inst.get("c")}


def _de_mas(registrados: list[dict], bases_pedidas: set[str], sesiones: dict[str, dict]) -> list[dict]:
    salida = []
    for reg in registrados:
        if reg["base"] in bases_pedidas:
            continue
        sesion = sesiones.get(reg["base"]) or {}
        inst = next((i for i in sesion.get("instances") or [] if i.get("c") == reg["code"]), {})
        salida.append({"codigo": reg["code"], "base": reg["base"], "titulo": sesion.get("title"), "dia": inst.get("d"),
                       "inicio": inst.get("st"), "fin": inst.get("en"), "sala": _sala(inst)})
    return sorted(salida, key=lambda d: (d["dia"] or "", d["inicio"] or ""))


def _choques(entradas: list[dict], horarios: list[tuple[list[dict], str | None]]) -> list[list[str]]:
    """Por entrada, los códigos (de la lista) con los que se pisa."""
    pisa = [[] for _ in entradas]
    for i in range(len(entradas)):
        for j in range(i + 1, len(entradas)):
            if _chocan(horarios[i], horarios[j]):
                pisa[i].append(entradas[j]["codigo"])
                pisa[j].append(entradas[i]["codigo"])
    return pisa


def cruzar(deseados: list[Codigo], sesiones: dict[str, dict], registrados: list[dict]) -> dict:
    """Cruza lo que quiero con el catálogo (sesiones por base) y con lo que ya registré ([{"code", "base"}]).

    Por código: registrado, falta o inexistente (más `choca_con`: otros que quiero y se pisan con él). Aparte, lo
    registrado que no está en la lista (`de_mas`)."""
    registrado_por_base = {r["base"]: r["code"] for r in registrados}
    entradas, horarios = [], []
    for cod in deseados:
        sesion = sesiones.get(cod.base)
        reg = registrado_por_base.get(cod.base)
        cands = _candidatos(cod, sesion, reg) if sesion else []
        entradas.append(_entrada(cod, sesion, cands, reg))
        horarios.append((cands, sesion.get("type") if sesion else None))
    codigos = [{**e, "choca_con": pisa} for e, pisa in zip(entradas, _choques(entradas, horarios), strict=True)]
    de_mas = _de_mas(registrados, {c.base for c in deseados}, sesiones)
    return {"codigos": codigos, "de_mas": de_mas, "resumen": {
        "total": len(codigos), "registrados": sum(e["estado"] == "registrado" for e in codigos),
        "faltan": sum(e["estado"] == "falta" for e in codigos), "choques": sum(bool(e["choca_con"]) for e in codigos),
        "de_mas": len(de_mas), "inexistentes": sum(e["estado"] == "inexistente" for e in codigos)}}
