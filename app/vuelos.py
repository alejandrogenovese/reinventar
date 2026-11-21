"""Vuelos y hoteles cargados a mano: lógica pura (número de vuelo, ventana de check-in, cambios de estado), consulta del
estado a AeroDataBox (api.market) y las consultas SQL. Los avisos los arma app/viajes_avisos.py.

AeroDataBox: GET {BASE}/flights/number/{número}/{fecha local} con el header x-api-market-key; devuelve una lista de vuelos
con departure.{scheduledTime,revisedTime}.utc, departure.gate/terminal y status (204 = sin datos todavía). Sin
AERODATABOX_API_KEY no se consulta nada y el resto de los avisos anda igual.
"""
import datetime as dt
import logging
import re
import threading
import time
import uuid
from zoneinfo import ZoneInfo

import httpx

from . import config, db

log = logging.getLogger("reinventar.vuelos")

BASE_ADB = "https://prod.api.market/api/v1/aedbx/aerodatabox"
TIMEOUT_S = 8
CACHE_S = 15 * 60          # el mismo vuelo y día no se vuelve a pedir antes de esto
DEMORA_AVISO_MIN = 15      # una demora que cambia en 15 min o más se avisa
HORAS_CHECKIN_DEFECTO = 24
FALLO_CACHE_S = 8 * 60     # un fallo (401, 429, 5xx, red) no se reintenta antes de esto
TOPE_DIARIO_POR_USUARIO = 40  # consultas por persona y por día: una persona con vuelos falsos no agota el cupo de todos

# Cuántas horas antes de la salida abre el check-in web, por código de aerolínea (IATA), y dónde se hace.
# Editable: si una aerolínea cambia su ventana, se corrige acá y listo. Fuentes:
# - AR: 24 h en cabotaje e internacional desde febrero de 2026 (antes 48 h en cabotaje); según Infoviajera (feb 2026) y
#   Promos Aéreas; la web de la aerolínea todavía muestra a veces la regla vieja. VERIFICAR en aerolineas.com.ar.
# - AA, UA, DL: 24 h (reglas publicadas por cada aerolínea; sin re-verificar en 2026).
# - LA (LATAM) e IB (Iberia): 48 h; sin re-verificar. Cualquier otra aerolínea usa HORAS_CHECKIN_DEFECTO.
CHECKIN_WEB = {
    "AR": {"horas": 24, "url": "https://www.aerolineas.com.ar/"},
    "AA": {"horas": 24, "url": "https://www.aa.com/checkin"},
    "UA": {"horas": 24, "url": "https://www.united.com/en/us/checkin"},
    "DL": {"horas": 24, "url": "https://www.delta.com/mytrips/"},
    "LA": {"horas": 48, "url": "https://www.latamairlines.com/ar/es/check-in"},
    "IB": {"horas": 48, "url": "https://www.iberia.com/ar/check-in/"},
}

ZONAS = {"America/Argentina/Buenos_Aires": "Buenos Aires", "America/Los_Angeles": "Las Vegas",
         "America/New_York": "Nueva York", "America/Sao_Paulo": "San Pablo", "America/Santiago": "Santiago",
         "Europe/Madrid": "Madrid"}
ZONA_VUELO_DEFECTO = "America/Argentina/Buenos_Aires"
ZONA_HOTEL_DEFECTO = "America/Los_Angeles"

_NUMERO = re.compile(r"^([A-Z0-9]{2})(\d{1,4}[A-Z]?)$")


def zona(nombre: str) -> ZoneInfo:
    return ZoneInfo(nombre)


def normalizar_numero(texto: str) -> str:
    """'ar 1302' -> 'AR1302'. ValueError si no parece un número de vuelo (código de 2 caracteres y hasta 4 dígitos)."""
    limpio = re.sub(r"\s+", "", texto or "").upper()
    if not _NUMERO.match(limpio) or limpio[:2].isdigit():
        raise ValueError("El número de vuelo es el código de la aerolínea y el número, por ejemplo AR1302")
    return limpio


def codigo_aerolinea(numero: str) -> str:
    return numero[:2].upper()


def horas_checkin(numero: str) -> int:
    return CHECKIN_WEB.get(codigo_aerolinea(numero), {}).get("horas", HORAS_CHECKIN_DEFECTO)


def url_checkin(numero: str) -> str | None:
    return CHECKIN_WEB.get(codigo_aerolinea(numero), {}).get("url")


def salida(v: dict) -> dt.datetime | None:
    """Cuándo sale: la hora que informó AeroDataBox si la hay, si no la que cargó la persona (en la zona del vuelo)."""
    if v.get("salida_utc"):
        return dt.datetime.fromtimestamp(v["salida_utc"], dt.UTC)
    if not v.get("hora"):
        return None
    return dt.datetime.fromisoformat(f"{v['fecha']}T{v['hora']}").replace(tzinfo=zona(v["zona"]))


def abre_checkin(v: dict) -> dt.datetime | None:
    sale = salida(v)
    return sale - dt.timedelta(hours=horas_checkin(v["numero"])) if sale else None


# ---------- estado (AeroDataBox) ----------

def _hora(movimiento: dict, campo: str) -> dt.datetime | None:
    """La hora UTC de un movimiento. Una fecha sin zona se toma como UTC: restarla contra una con zona tiraría TypeError."""
    texto = ((movimiento or {}).get(campo) or {}).get("utc")
    if not texto or not isinstance(texto, str):
        return None
    try:
        hora = dt.datetime.fromisoformat(texto.replace("Z", "+00:00"))
    except ValueError:
        return None
    return hora if hora.tzinfo else hora.replace(tzinfo=dt.UTC)


def _es_del_dia(vuelo: dict, fecha: str) -> bool:
    local = (((vuelo.get("departure") or {}).get("scheduledTime") or {}).get("local")) or ""
    return isinstance(local, str) and local.startswith(fecha)


def leer_estado(respuesta, fecha: str) -> dict | None:
    """De la lista que devuelve AeroDataBox, el vuelo de esa fecha: salida (epoch UTC), demora, puerta, terminal, estado.
    None si no hay ninguno de ese día (tomar el de otro día daría una demora falsa de 24 h) o si la respuesta viene rara."""
    try:
        return _leer_estado(respuesta, fecha)
    except (KeyError, TypeError, AttributeError, ValueError):
        log.warning("AeroDataBox: respuesta con formato inesperado para %s", fecha)
        return None


def _leer_estado(respuesta, fecha: str) -> dict | None:
    if not isinstance(respuesta, list):
        return None
    candidatos = [f for f in respuesta if isinstance(f, dict) and isinstance(f.get("departure"), dict)
                  and _hora(f["departure"], "scheduledTime")]
    vuelo = next((f for f in candidatos if _es_del_dia(f, fecha)), None)
    if not vuelo:
        return None
    dep = vuelo["departure"]
    programada, revisada = _hora(dep, "scheduledTime"), _hora(dep, "revisedTime")
    demora = round((revisada - programada).total_seconds() / 60) if revisada else 0
    return {"salida_utc": programada.timestamp(), "demora_min": demora, "puerta": dep.get("gate") or None,
            "terminal": dep.get("terminal") or None, "estado": vuelo.get("status")}


def cambios(v: dict, nuevo: dict) -> list[tuple[str, int | str | None]]:
    """Qué hay para avisar comparando con lo último avisado: [('demora', min)], [('puerta', 'B12')], [('cancelado', None)]."""
    out: list[tuple[str, int | str | None]] = []
    if abs(nuevo["demora_min"] - (v.get("demora_min") or 0)) >= DEMORA_AVISO_MIN:
        out.append(("demora", nuevo["demora_min"]))
    if nuevo.get("puerta") and nuevo["puerta"] != v.get("puerta"):
        out.append(("puerta", nuevo["puerta"]))
    if (nuevo.get("estado") or "").lower().startswith("cancel") and not (v.get("estado") or "").lower().startswith("cancel"):
        out.append(("cancelado", None))
    return out


_lock = threading.Lock()
_cache: dict[tuple[str, str], tuple[float, dict | None, float]] = {}   # (momento, resultado, cuánto vale)
_dia = {"fecha": None, "n": 0}
_por_usuario: dict[str, int] = {}


def reiniciar_consultas() -> None:
    with _lock:
        _cache.clear()
        _dia.update(fecha=None, n=0)
        _por_usuario.clear()


def estado_disponible() -> bool:
    return bool(config.AERODATABOX_API_KEY)


def _reservar_cupo(usuario: str | None) -> bool:
    """Gasta una consulta del día (global y de la persona). Con el cupo de una persona agotado no toca el de todos."""
    hoy = dt.datetime.now(dt.UTC).strftime("%Y-%m-%d")
    with _lock:
        if _dia["fecha"] != hoy:
            _dia.update(fecha=hoy, n=0)
            _por_usuario.clear()
        if _dia["n"] >= config.AERODATABOX_TOPE_DIARIO:
            return False
        if usuario is not None and _por_usuario.get(usuario, 0) >= TOPE_DIARIO_POR_USUARIO:
            return False
        _dia["n"] += 1
        if usuario is not None:
            _por_usuario[usuario] = _por_usuario.get(usuario, 0) + 1
        return True


def _devolver_cupo(usuario: str | None) -> None:
    with _lock:
        _dia["n"] = max(0, _dia["n"] - 1)
        if usuario is not None:
            _por_usuario[usuario] = max(0, _por_usuario.get(usuario, 0) - 1)


def _guardar_en_cache(clave: tuple[str, str], resultado: dict | None, vale_s: float) -> None:
    with _lock:
        _cache[clave] = (time.time(), resultado, vale_s)


def consultar(numero: str, fecha: str, http=None, usuario: str | None = None) -> dict | None:
    """Estado del vuelo, o None (sin clave, sin datos, tope alcanzado o error: nunca tira). Los fallos se cachean unos
    minutos para no reintentar cada vuelta; una clave mala (401/403) no gasta cupo. `usuario` pone un tope por persona."""
    if not estado_disponible():
        return None
    clave = (numero, fecha)
    with _lock:
        hit = _cache.get(clave)
    if hit and time.time() - hit[0] < hit[2]:
        return hit[1]
    if not _reservar_cupo(usuario):
        log.warning("tope diario de consultas de vuelos alcanzado (%s, %s)", config.AERODATABOX_TOPE_DIARIO,
                    usuario or "global")
        return None
    try:
        r = (http or httpx).get(f"{BASE_ADB}/flights/number/{numero}/{fecha}",
                                headers={"x-api-market-key": config.AERODATABOX_API_KEY}, timeout=TIMEOUT_S)
    except httpx.HTTPError as e:  # nunca se loguea la URL con la clave: va en el header
        log.warning("AeroDataBox %s %s falló: %s", numero, fecha, type(e).__name__)
        _guardar_en_cache(clave, None, FALLO_CACHE_S)
        return None
    if r.status_code in (401, 403):
        _devolver_cupo(usuario)
        log.error("AeroDataBox rechazó la clave (HTTP %s): revisar AERODATABOX_API_KEY", r.status_code)
        _guardar_en_cache(clave, None, FALLO_CACHE_S)
        return None
    if r.status_code == 429 or r.status_code >= 400:
        log.warning("AeroDataBox %s %s respondió HTTP %s%s", numero, fecha, r.status_code,
                    " (cuota agotada)" if r.status_code == 429 else "")
        _guardar_en_cache(clave, None, FALLO_CACHE_S)
        return None
    resultado = None
    if r.status_code != 204:
        try:
            resultado = leer_estado(r.json(), fecha)
        except ValueError:
            log.warning("AeroDataBox %s %s devolvió algo que no es JSON", numero, fecha)
            _guardar_en_cache(clave, None, FALLO_CACHE_S)
            return None
    _guardar_en_cache(clave, resultado, CACHE_S)
    return resultado


# ---------- base de datos ----------

PREFS_VIAJES = ("viajes_checkin", "viajes_hoteles", "viajes_estado")
TOPE_POR_PERSONA = 40


def _nuevo_id() -> str:
    return uuid.uuid4().hex[:12]


def get_prefs(username: str) -> dict:
    with db.conn() as c:
        r = c.execute(f"SELECT {', '.join(PREFS_VIAJES)} FROM preferencias_avisos WHERE username=%s", (username,)).fetchone()
    return dict(r) if r else dict.fromkeys(PREFS_VIAJES, True)


def set_prefs(username: str, prefs: dict) -> dict:
    """Guarda solo las columnas de viajes; crea la fila con los valores por defecto del resto si no existía."""
    with db.conn() as c:
        c.execute("INSERT INTO preferencias_avisos (username,grabar,ubicacion,updated_at) VALUES (%s,TRUE,FALSE,%s) "
                  "ON CONFLICT DO NOTHING", (username, time.time()))
        c.execute("UPDATE preferencias_avisos SET viajes_checkin=%s, viajes_hoteles=%s, viajes_estado=%s, updated_at=%s "
                  "WHERE username=%s", (*(prefs[k] for k in PREFS_VIAJES), time.time(), username))
    return get_prefs(username)


def listar_vuelos(username: str) -> list[dict]:
    with db.conn() as c:
        return [dict(r) for r in c.execute("SELECT * FROM viajes_vuelos WHERE username=%s ORDER BY fecha, hora, creado",
                                           (username,)).fetchall()]


def get_vuelo(username: str, id_: str) -> dict | None:
    with db.conn() as c:
        r = c.execute("SELECT * FROM viajes_vuelos WHERE username=%s AND id=%s", (username, id_)).fetchone()
    return dict(r) if r else None


def agregar_vuelo(username: str, numero: str, aerolinea: str, fecha: str, hora: str | None, zona_: str) -> dict | None:
    """None si ya tiene demasiados cargados."""
    id_ = _nuevo_id()
    with db.conn() as c:
        if c.execute("SELECT COUNT(*) AS n FROM viajes_vuelos WHERE username=%s", (username,)).fetchone()["n"] >= TOPE_POR_PERSONA:
            return None
        c.execute("INSERT INTO viajes_vuelos (username,id,numero,aerolinea,fecha,hora,zona,creado) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                  (username, id_, numero, aerolinea, fecha, hora, zona_, time.time()))
    return get_vuelo(username, id_)


def quitar_vuelo(username: str, id_: str) -> bool:
    with db.conn() as c:
        return c.execute("DELETE FROM viajes_vuelos WHERE username=%s AND id=%s", (username, id_)).rowcount == 1


CAMPOS_ESTADO = ("salida_utc", "demora_min", "puerta", "terminal", "estado", "consultado_en")


def guardar_estado(username: str, id_: str, campos: dict) -> None:
    columnas = [k for k in campos if k in CAMPOS_ESTADO]
    if not columnas:
        return
    with db.conn() as c:
        c.execute(f"UPDATE viajes_vuelos SET {', '.join(f'{k}=%s' for k in columnas)} WHERE username=%s AND id=%s",
                  (*(campos[k] for k in columnas), username, id_))


def listar_hoteles(username: str) -> list[dict]:
    with db.conn() as c:
        return [dict(r) for r in c.execute("SELECT * FROM viajes_hoteles WHERE username=%s ORDER BY checkin, creado",
                                           (username,)).fetchall()]


def get_hotel(username: str, id_: str) -> dict | None:
    with db.conn() as c:
        r = c.execute("SELECT * FROM viajes_hoteles WHERE username=%s AND id=%s", (username, id_)).fetchone()
    return dict(r) if r else None


def agregar_hotel(username: str, nombre: str, direccion: str, checkin: str, checkout: str, zona_: str) -> dict | None:
    id_ = _nuevo_id()
    with db.conn() as c:
        if c.execute("SELECT COUNT(*) AS n FROM viajes_hoteles WHERE username=%s", (username,)).fetchone()["n"] >= TOPE_POR_PERSONA:
            return None
        c.execute("INSERT INTO viajes_hoteles (username,id,nombre,direccion,checkin,checkout,zona,creado) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                  (username, id_, nombre, direccion, checkin, checkout, zona_, time.time()))
    return get_hotel(username, id_)


def quitar_hotel(username: str, id_: str) -> bool:
    with db.conn() as c:
        return c.execute("DELETE FROM viajes_hoteles WHERE username=%s AND id=%s", (username, id_)).rowcount == 1
