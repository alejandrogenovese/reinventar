"""Conversor › «Leer con la cámara»: el LLM (con visión) lee la foto de una carta, un cartel o una etiqueta, traduce lo
que dice y marca los números con unidad. Nada más: las conversiones las hace el celular (web/js/unidades.js), así no
dependen del modelo y andan igual que el conversor manual.

La foto vive solo en memoria durante el pedido: no va a disco ni a un bucket, no se loguea y en Langfuse no se guarda
ni la entrada ni la salida (app/trazas.py: tarea privada "foto").
"""
import json
import logging
import math
import re

from . import config, llm
from .llm_router import Tarea

log = logging.getLogger("reinventar.conversor")

MAX_TEXTOS = 30
MAX_UNIDADES = 10
LARGO_TEXTO = 300
LARGO_UNIDAD = 20
MAX_TOKENS = 2000
LIMITE_VALOR = 1e9  # un valor más grande no es una medida de una carta o un cartel: se descarta
# Mismo criterio que parsearNumero de web/js/unidades.js. Miles: 1 a 3 cifras (sin 0 adelante) y grupos de 3 con el
# mismo separador, punto o coma («1,234», «1.234»), con decimales opcionales detrás del otro («1,234.5»).
_MILES = re.compile(r"(-?)([1-9]\d{0,2}(?:([.,])\d{3})(?:\3\d{3})*)(?:([.,])(\d+))?")
# Decimal simple: un solo separador («72,5», «72.5», «,5», «0,750»). Nada de «1_000», «1e3» ni «inf».
_DECIMAL = re.compile(r"-?(?:\d+(?:[.,]\d*)?|[.,]\d+)")

SYSTEM = f"""Leés fotos que saca una persona argentina de viaje en Estados Unidos: cartas de restaurante, carteles, etiquetas, pronósticos, máquinas del gym. Transcribís el texto legible y lo traducís a {config.TARGET_LANGUAGE}, con voseo.

Para cada renglón o ítem con sentido propio (un plato con su precio, un cartel, una indicación) devolvés:
- "original": el texto tal como se lee en la foto.
- "traduccion": la traducción, breve y natural. Los nombres propios y de marcas quedan igual.
- "unidades": los números con unidad estadounidense que aparecen en ese texto, sin convertirlos: [{{"valor": 16, "unidad": "oz"}}]. "valor" va siempre como número JSON (16, 2.5, 1250), nunca como texto ni con separador de miles. Unidades posibles: °F, oz, lb, fl oz, cup, pint, gallon, in, ft, yd, mi, mph, $. Precios en dólares con unidad "$". Si no hay, [].

No conviertas nada ni agregues texto que no esté en la foto. Si no hay texto legible, devolvé {{"textos": []}}.
Respondé solo con JSON, sin comentarios: {{"textos": [{{"original": "...", "traduccion": "...", "unidades": [...]}}]}}"""

USER = "Foto para leer: transcribí, traducí y marcá las unidades."


def leer(imagen: llm.Imagen) -> dict:
    """Lee la foto con el LLM y devuelve {textos: [...]} ya limpio (ver parsear)."""
    return parsear(llm.complete(Tarea.FOTO, SYSTEM, USER, MAX_TOKENS, imagen=imagen))


def parsear(texto: str) -> dict:
    """La respuesta del LLM como {textos: [{original, traduccion, unidades: [{valor, unidad}]}]}. Tolera JSON incompleto
    (respuesta cortada): se queda con los ítems que llegaron enteros. Lo que no tiene la forma esperada se descarta."""
    try:
        datos = llm.parse_json(texto)
        crudos = datos.get("textos") if isinstance(datos, dict) else None
    except ValueError:
        crudos = _rescatar(texto)
    lista = crudos if isinstance(crudos, list) else []
    return {"textos": [t for t in map(_texto, lista) if t][:MAX_TEXTOS]}


def _rescatar(texto: str) -> list:
    """Los objetos completos del arreglo "textos" de un JSON cortado a la mitad."""
    inicio = texto.find('"textos"')
    corchete = texto.find("[", inicio) if inicio >= 0 else -1
    if corchete < 0:
        return []
    decodificador, pos, items = json.JSONDecoder(), corchete + 1, []
    while pos < len(texto):
        while pos < len(texto) and texto[pos] in " \t\r\n,":
            pos += 1
        if pos >= len(texto) or texto[pos] == "]":
            break
        try:
            item, pos = decodificador.raw_decode(texto, pos)
        except ValueError:
            break
        items.append(item)
    return items


def _cadena(valor, largo: int) -> str:
    return valor.strip()[:largo] if isinstance(valor, str) else ""


def _numero(valor) -> float | None:
    """El valor como número finito; si el LLM lo mandó como texto, se lee con _MILES o _DECIMAL. Si no, None."""
    if isinstance(valor, bool):
        return None
    if isinstance(valor, int | float):
        numero = float(valor)
    elif isinstance(valor, str):
        numero = _numero_de_texto(valor.strip())
    else:
        return None
    return numero if numero is not None and math.isfinite(numero) else None


def _numero_de_texto(texto: str) -> float | None:
    miles = _MILES.fullmatch(texto)
    if miles and miles[4] != miles[3]:
        return float(f"{miles[1]}{re.sub(r'[.,]', '', miles[2])}" + (f".{miles[5]}" if miles[5] else ""))
    if _DECIMAL.fullmatch(texto):
        return float(texto.replace(",", "."))
    return None


def _unidad(u) -> dict | None:
    if not isinstance(u, dict):
        return None
    valor, unidad = _numero(u.get("valor")), _cadena(u.get("unidad"), LARGO_UNIDAD)
    if valor is None or not unidad or not abs(valor) < LIMITE_VALOR:
        return None
    return {"valor": int(valor) if valor.is_integer() else valor, "unidad": unidad}


def _texto(t) -> dict | None:
    if not isinstance(t, dict):
        return None
    original, traduccion = _cadena(t.get("original"), LARGO_TEXTO), _cadena(t.get("traduccion"), LARGO_TEXTO)
    if not original and not traduccion:
        return None
    crudas = t.get("unidades") if isinstance(t.get("unidades"), list) else []
    unidades = [u for u in map(_unidad, crudas) if u][:MAX_UNIDADES]
    return {"original": original, "traduccion": traduccion, "unidades": unidades}
