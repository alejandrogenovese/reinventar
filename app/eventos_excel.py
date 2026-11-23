"""Cargar eventos propios desde un Excel o CSV: cada fila es un evento privado de «Mis eventos» (app/my_events.py).

Funciones puras: las sedes entran como datos, así se prueba sin base. El archivo lo lee app/planilla.py (sin
fórmulas ni macros, con topes). La cabecera se busca por nombre, en cualquier orden, sin importar mayúsculas, tildes
ni el «*» de obligatoria. No hay columnas nuevas en user_events: Tipo, Dirección, Link, Precio y la aclaración de que
termina al día siguiente se escriben en la nota, que conserva su largo máximo.

Para no duplicar, el id sale de un hash del nombre normalizado, el día y el inicio: subir el mismo archivo otra vez
actualiza los mismos eventos.
"""
import datetime as dt
import hashlib
import re
import unicodedata
from dataclasses import dataclass
from urllib.parse import urlsplit

from pydantic import ValidationError

from . import estadia, planilla
from .my_events import MiEvento
from .planilla import ArchivoInvalido
from .prompts import EVENT_TYPES

MAX_BYTES = 1024 * 1024
MAX_EVENTOS = 100
MAX_NOMBRE, MAX_NOTA, MAX_LUGAR = 120, 500, 200  # los mismos de MiEvento (nombre, nota y direccion)
EXTENSIONES = (".xlsx", ".csv")
TIPOS = (*EVENT_TYPES, "otro")
PREFIJO_ID = "xl"
FILAS_PARA_CABECERA = 20  # la cabecera tiene que estar entre las primeras filas de la hoja
FIN_DEL_DIA = "23:59"     # un evento que termina al día siguiente ocupa hasta el final de su día
_TOPES = planilla.Topes(filas=1000, aviso_celdas="El Excel tiene demasiadas celdas: subí solo la hoja de eventos.")
_EPOCA_EXCEL = dt.date(1899, 12, 30)
_HORA = re.compile(r"^(\d{1,2})(?:[:.](\d{2}))?(?::\d{2})?\s*([ap])?\.?\s*m?\.?$")

# Cabecera normalizada -> campo. Además de los nombres del ejemplo, algunos sinónimos razonables.
_COLUMNAS = {
    "nombre": "nombre", "evento": "nombre",
    "dia": "dia", "fecha": "dia",
    "inicio": "inicio", "hora": "inicio", "desde": "inicio", "hora de inicio": "inicio",
    "fin": "fin", "hasta": "fin", "hora de fin": "fin",
    "tipo": "tipo",
    "lugar": "lugar", "sede": "lugar",
    "direccion": "direccion",
    "link": "link", "url": "link", "enlace": "link",
    "precio": "precio", "costo": "precio",
    "notas": "notas", "nota": "notas",
}
OBLIGATORIAS = ("nombre", "dia", "inicio", "lugar")
_NOMBRES = {"nombre": "Nombre", "dia": "Día", "inicio": "Inicio", "lugar": "Lugar"}


def _plano(texto: str) -> str:
    """Minúsculas, sin tildes y con los espacios colapsados: para comparar cabeceras, sedes, tipos y nombres."""
    sin_tildes = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return " ".join(sin_tildes.casefold().split())


def _campo(celda) -> str | None:
    if not isinstance(celda, str):
        return None
    limpio = re.sub(r"\(.*?\)", "", celda).replace("*", "")
    return _COLUMNAS.get(_plano(limpio))


@dataclass(frozen=True)
class Fila:
    numero: int                  # la fila en la planilla (1 = la primera), para que la persona la encuentre
    id: str | None = None
    evento: MiEvento | None = None
    lugar: str | None = None     # lo que se ve: el nombre de la sede o el texto de Lugar
    sede: bool = False
    error: str | None = None


# ---------- celdas ----------

def _texto(valor) -> str:
    if valor is None:
        return ""
    if isinstance(valor, float) and valor.is_integer():
        valor = int(valor)
    return " ".join(str(valor).split())


def leer_dia(valor) -> str:
    """«aaaa-mm-dd» de una celda de fecha de Excel, un número de serie o un texto dd/mm/aaaa o aaaa-mm-dd."""
    if isinstance(valor, dt.datetime):
        fecha = valor.date()
    elif isinstance(valor, dt.date):
        fecha = valor
    elif isinstance(valor, int | float) and not isinstance(valor, bool):
        fecha = _EPOCA_EXCEL + dt.timedelta(days=int(valor))
    else:
        fecha = _dia_de_texto(_texto(valor))
    primero, ultimo = estadia.INICIO_DE_LA_ESTADIA.date(), estadia.FIN_DE_LA_ESTADIA.date()
    if not primero <= fecha <= ultimo:
        raise ValueError(f"El día tiene que estar entre el {primero:%d/%m/%Y} y el {ultimo:%d/%m/%Y}")
    return fecha.isoformat()


def _dia_de_texto(texto: str) -> dt.date:
    try:
        if m := re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", texto):
            return dt.date(int(m[1]), int(m[2]), int(m[3]))
        if m := re.fullmatch(r"(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})", texto):
            return dt.date(int(m[3]), int(m[2]), int(m[1]))
    except ValueError:
        pass
    raise ValueError(f"No entiendo el día «{texto}»: usá dd/mm/aaaa")


def leer_hora(valor) -> str:
    """«HH:MM» de una celda de hora de Excel (o la fracción del día) o de un texto «19:30», «7:30 PM», «7 pm»."""
    if isinstance(valor, dt.datetime):
        valor = valor.time()
    if isinstance(valor, dt.time):
        return f"{valor.hour:02d}:{valor.minute:02d}"
    if isinstance(valor, dt.timedelta):
        minutos = round(valor.total_seconds() / 60)
        return _hhmm(minutos // 60, minutos % 60, valor)
    if isinstance(valor, float) and 0 <= valor < 1:  # una hora sin formato en Excel es la fracción del día
        minutos = round(valor * 24 * 60)
        return _hhmm(minutos // 60, minutos % 60, valor)
    texto = _texto(valor)
    m = _HORA.fullmatch(texto.casefold())
    if not m:
        raise ValueError(f"No entiendo la hora «{texto}»: usá 19:30 o 7:30 PM")
    hora, minutos, ampm = int(m[1]), int(m[2] or 0), m[3]
    if ampm:
        if not 1 <= hora <= 12:
            raise ValueError(f"No entiendo la hora «{texto}»: usá 19:30 o 7:30 PM")
        hora = hora % 12 + (12 if ampm == "p" else 0)
    return _hhmm(hora, minutos, texto)


def _hhmm(hora: int, minutos: int, original) -> str:
    if not (0 <= hora <= 23 and 0 <= minutos <= 59):
        raise ValueError(f"No entiendo la hora «{original}»: usá 19:30 o 7:30 PM")
    return f"{hora:02d}:{minutos:02d}"


def leer_link(valor) -> str:
    texto = _texto(valor)
    partes = urlsplit(texto)
    if partes.scheme != "https" or not partes.netloc or " " in texto:
        raise ValueError("El link tiene que empezar con https://")
    return texto


def leer_tipo(valor) -> str:
    """El tipo tal como está en la lista (con su tilde), aunque lo hayan escrito en mayúsculas o sin tildes."""
    plano = _plano(_texto(valor))
    tipo = next((t for t in TIPOS if _plano(t) == plano), None)
    if tipo is None:
        raise ValueError(f"Tipo «{_texto(valor)}» desconocido: elegí uno de {', '.join(TIPOS)}")
    return tipo


def id_de(nombre: str, dia: str, inicio: str) -> str:
    """Id determinístico: el mismo nombre (sin importar mayúsculas ni tildes), día e inicio dan el mismo evento."""
    clave = f"{_plano(nombre)}|{dia}|{inicio}"
    return PREFIJO_ID + hashlib.sha256(clave.encode()).hexdigest()[:10]


# ---------- filas ----------

def _nombres_de_sede(nombre: str) -> set[str]:
    """«Wynn/Encore» se reconoce entero o por cada una de sus partes."""
    return {_plano(nombre), *(_plano(parte) for parte in nombre.split("/") if parte.strip())}


def _sede(lugar: str, sedes: list[dict]) -> dict | None:
    plano = _plano(lugar)
    return next((s for s in sedes if plano in _nombres_de_sede(s["name"])), None)


def _nota(valores: dict, tipo: str | None, link: str | None, fin_real: str | None) -> str:
    """La nota legible: primero los datos que no tienen columna propia y después las Notas de la persona."""
    lineas = [
        f"Tipo: {tipo}" if tipo else None,
        f"Termina al día siguiente, a las {fin_real}." if fin_real else None,
        f"Precio: {valores['precio']}" if valores.get("precio") else None,
        f"Dirección: {valores['direccion']}" if valores.get("direccion") else None,
        f"Link: {link}" if link else None,
        valores.get("notas") or None,
    ]
    nota = "\n".join(linea for linea in lineas if linea)
    if len(nota) > MAX_NOTA:
        raise ValueError(f"Entre Notas, Link, Precio y Dirección pasa de {MAX_NOTA} caracteres: acortá las Notas")
    return nota


def _evento(celdas: dict, sedes: list[dict]) -> tuple[MiEvento, dict | None]:
    """El evento de una fila (celdas por campo, con los valores crudos). ValueError con el motivo si no sirve."""
    textos = {k: _texto(v) for k, v in celdas.items()}
    faltan = [_NOMBRES[k] for k in OBLIGATORIAS if not textos.get(k)]
    if faltan:
        raise ValueError("Falta " + ", ".join(faltan))
    if len(textos["nombre"]) > MAX_NOMBRE:
        raise ValueError(f"El nombre pasa de {MAX_NOMBRE} caracteres")
    if len(textos["lugar"]) > MAX_LUGAR:
        raise ValueError(f"El lugar pasa de {MAX_LUGAR} caracteres")
    dia, inicio = leer_dia(celdas["dia"]), leer_hora(celdas["inicio"])
    fin = leer_hora(celdas["fin"]) if textos.get("fin") else None
    if fin == inicio:
        raise ValueError("El fin es igual al inicio")
    fin_real = fin if fin and fin < inicio else None
    tipo = leer_tipo(celdas["tipo"]) if textos.get("tipo") else None
    link = leer_link(celdas["link"]) if textos.get("link") else None
    nota = _nota(textos, tipo, link, fin_real)
    sede = _sede(textos["lugar"], sedes)
    lugar = {"id_sede": sede["id"]} if sede else {"direccion": textos["lugar"]}
    evento = MiEvento(nombre=textos["nombre"], dia=dia, inicio=inicio, fin=FIN_DEL_DIA if fin_real else fin,
                      nota=nota, **lugar)
    return evento, sede


def _cabecera(filas: list[list]) -> tuple[int, dict[str, int]] | None:
    """(índice de la fila de cabecera, campo -> columna) si alguna de las primeras filas trae las obligatorias."""
    for i, fila in enumerate(filas[:FILAS_PARA_CABECERA]):
        columnas: dict[str, int] = {}
        for j, celda in enumerate(fila):
            campo = _campo(celda)
            if campo and campo not in columnas:
                columnas[campo] = j
        if all(k in columnas for k in OBLIGATORIAS):
            return i, columnas
    return None


def _hoja_de_eventos(hojas: list[list[list]]) -> tuple[list[list], int, dict[str, int]]:
    for filas in hojas:
        if encontrada := _cabecera(filas):
            return filas, *encontrada
    raise ArchivoInvalido("No encontré la cabecera: la hoja tiene que tener las columnas Nombre, Día, Inicio y Lugar. "
                          "Bajá el Excel de ejemplo para ver cómo armarla.")


def _vacia(fila: list) -> bool:
    return all(_texto(c) == "" for c in fila)


def _filas(hojas: list[list[list]], sedes: list[dict]) -> list[Fila]:
    filas, cabecera, columnas = _hoja_de_eventos(hojas)
    salida: list[Fila] = []
    vistos: dict[str, int] = {}
    for i in range(cabecera + 1, len(filas)):
        fila = filas[i]
        if _vacia(fila):
            continue
        if len(salida) >= MAX_EVENTOS:
            raise ArchivoInvalido(f"Hay más de {MAX_EVENTOS} eventos: subí una lista más corta.")
        celdas = {campo: fila[j] if j < len(fila) else None for campo, j in columnas.items()}
        salida.append(_fila(i + 1, celdas, sedes, vistos))
    if not salida:
        raise ArchivoInvalido("La planilla no tiene eventos debajo de la cabecera.")
    return salida


def _fila(numero: int, celdas: dict, sedes: list[dict], vistos: dict[str, int]) -> Fila:
    try:
        evento, sede = _evento(celdas, sedes)
    except ValidationError as e:
        return Fila(numero, error=e.errors()[0]["msg"])
    except ValueError as e:
        return Fila(numero, error=str(e))
    id_ = id_de(evento.nombre, evento.dia, evento.inicio)
    if id_ in vistos:
        return Fila(numero, error=f"Repite el evento de la fila {vistos[id_]} (mismo nombre, día e inicio)")
    vistos[id_] = numero
    return Fila(numero, id_, evento, sede["name"] if sede else evento.direccion, sede is not None)


def leer_eventos(datos: bytes, nombre: str, sedes: list[dict]) -> list[Fila]:
    """Las filas con su evento o el motivo del error. ArchivoInvalido si el archivo entero no sirve.

    sedes: las de app/venues.py ({"id", "name", ...}); un Lugar que coincide con una toma sus coordenadas."""
    if not datos:
        raise ArchivoInvalido("El archivo está vacío.")
    if len(datos) > MAX_BYTES:
        raise ArchivoInvalido(f"El archivo es demasiado grande (máximo {MAX_BYTES // 1024 // 1024} MB).")
    extension = planilla.extension(nombre)
    if extension not in EXTENSIONES:
        raise ArchivoInvalido("Subí un archivo .xlsx o .csv.")
    hojas = planilla.filas_xlsx(datos, _TOPES) if extension == ".xlsx" else planilla.filas_csv(datos, _TOPES)
    return _filas(hojas, sedes)


# ---------- comparación con lo guardado ----------

NUEVA, ACTUALIZA, SIN_CAMBIOS, ERROR = "nueva", "actualiza", "sin_cambios", "error"
_COMPARABLES = ("nombre", "dia", "inicio", "fin", "nota", "id_sede", "lugar")


def estado(fila: Fila, anterior: dict | None) -> str:
    """nueva, actualiza o sin_cambios contra lo que ya está en user_events (error si la fila no sirve)."""
    if fila.error:
        return ERROR
    if anterior is None:
        return NUEVA
    ev = fila.evento
    nuevo = {"nombre": ev.nombre, "dia": ev.dia, "inicio": ev.inicio, "fin": ev.fin, "nota": ev.nota,
             "id_sede": ev.id_sede, "lugar": fila.lugar}
    return SIN_CAMBIOS if all(anterior.get(k) == nuevo[k] for k in _COMPARABLES) else ACTUALIZA


def vista(fila: Fila, estado_: str) -> dict:
    """Lo que se muestra de una fila en la vista previa."""
    ev = fila.evento
    if ev is None:
        return {"fila": fila.numero, "estado": estado_, "error": fila.error}
    return {"fila": fila.numero, "estado": estado_, "error": None, "id": fila.id, "nombre": ev.nombre, "dia": ev.dia,
            "inicio": ev.inicio, "fin": ev.fin, "lugar": fila.lugar, "sede": fila.sede, "nota": ev.nota}
