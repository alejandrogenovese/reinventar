"""Lectura segura de planillas (.xlsx y .csv) que sube la persona: la usan «Mis códigos de Excel»
(app/codigos_excel.py) y la carga de eventos propios (app/eventos_excel.py).

El archivo se lee solo como datos: openpyxl en modo solo lectura y con los valores ya calculados (`data_only`), sin
evaluar fórmulas ni macros. Los topes (filas, columnas, hojas, celdas y tamaño descomprimido) cortan antes de que un
archivo armado a propósito se coma la memoria: un .xlsx es un zip y puede declarar 16384 columnas.
"""
import csv
import io
import zipfile
from dataclasses import dataclass

_MAGIC_XLSX = b"PK\x03\x04"


class ArchivoInvalido(ValueError):
    """El archivo no sirve; el mensaje se le muestra tal cual a la persona."""


@dataclass(frozen=True)
class Topes:
    filas: int = 5000
    columnas: int = 50     # openpyxl rellena cada fila hasta el ancho declarado: se corta acá
    hojas: int = 10
    celdas: int = 250_000  # celdas con algo, entre todas las hojas
    descomprimido: int = 50 * 1024 * 1024
    aviso_celdas: str = "El Excel tiene demasiadas celdas."


def extension(nombre: str) -> str:
    """«.xlsx» de «Mis Eventos.XLSX»; vacío si no tiene."""
    return ("." + nombre.rsplit(".", 1)[-1]).lower() if "." in nombre else ""


def _sin_vacias_al_final(fila: tuple) -> list:
    """La fila sin las celdas vacías del final (el relleno hasta el ancho declarado no cuenta ni se guarda)."""
    fila = list(fila)
    while fila and fila[-1] is None:
        fila.pop()
    return fila


def filas_xlsx(datos: bytes, topes: Topes) -> list[list[list]]:
    """Por hoja, las filas con los valores de las celdas (las fórmulas sin calcular quedan vacías)."""
    import openpyxl  # diferido: solo hace falta al subir un Excel

    if not datos.startswith(_MAGIC_XLSX):
        raise ArchivoInvalido("El archivo no es un Excel .xlsx válido.")
    try:
        if sum(i.file_size for i in zipfile.ZipFile(io.BytesIO(datos)).infolist()) > topes.descomprimido:
            raise ArchivoInvalido("El Excel es demasiado grande por dentro.")
        libro = openpyxl.load_workbook(io.BytesIO(datos), read_only=True, data_only=True)
        try:
            if len(libro.worksheets) > topes.hojas:
                raise ArchivoInvalido(f"El Excel tiene demasiadas hojas (máximo {topes.hojas}).")
            hojas, celdas = [], 0
            for hoja in libro.worksheets:
                filas = []
                for fila in hoja.iter_rows(max_col=topes.columnas, values_only=True):
                    if len(filas) >= topes.filas:
                        raise ArchivoInvalido(f"El archivo tiene demasiadas filas (máximo {topes.filas}).")
                    fila = _sin_vacias_al_final(fila)
                    celdas += len(fila)
                    if celdas > topes.celdas:
                        raise ArchivoInvalido(topes.aviso_celdas)
                    filas.append(fila)
                hojas.append(filas)
            return hojas
        finally:
            libro.close()
    except ArchivoInvalido:
        raise
    except Exception as e:  # openpyxl/zipfile levantan de todo con un archivo roto o armado a propósito
        raise ArchivoInvalido("No pude leer el archivo como un Excel .xlsx.") from e


def filas_csv(datos: bytes, topes: Topes) -> list[list[list]]:
    """Una sola «hoja» con las filas del CSV (UTF-8 con o sin BOM, o latin-1; separador , ; tab o |)."""
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
            if len(filas) >= topes.filas:
                raise ArchivoInvalido(f"El archivo tiene demasiadas filas (máximo {topes.filas}).")
            filas.append(fila[:topes.columnas])
    except csv.Error as e:  # p. ej. un campo de más de 128 KB
        raise ArchivoInvalido("No pude leer el archivo como un CSV: tiene un campo demasiado largo o está mal armado.") from e
    return [filas]
