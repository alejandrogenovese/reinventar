"""Avisos de vuelos y hoteles cargados a mano (app/vuelos.py). Los arma app/push.due junto con el resto y salen por el
mismo hilo de 60 s: cada uno por clave en push_sent, así que ninguno se repite.

- Check-in web: desde que abre la ventana de la aerolínea (vuelos.CHECKIN_WEB) hasta la salida.
- Hotel: el check-in desde 3 h antes; el check-out desde las 19:00 de la noche anterior (si cae de noche, sale a la mañana).
- Estado del vuelo (AeroDataBox, solo con clave): desde 24 h antes, una consulta cada 20 min como mucho; avisa si la demora
  cambia 15 min o más contra la última avisada, si aparece o cambia la puerta, o si se cancela.
Ninguno sale en el horario de silencio (app/recordatorio.py), salvo el estado del vuelo cuando faltan menos de 6 h.
Cada tipo se apaga desde Ajustes (preferencias_avisos.viajes_*).
"""
import datetime as dt
import time
from collections.abc import Callable

from . import recordatorio, vuelos

CHECKIN_HOTEL_ANTES_H = 3
CHECKOUT_DESDE_HORA = 19        # la noche anterior al check-out
ESTADO_ANTES_H = 24             # desde cuándo se consulta el estado del vuelo
INTERVALO_CONSULTA_S = 20 * 60  # entre consultas del mismo vuelo
URGENTE_H = 6                   # con menos que esto para salir, el estado avisa aunque sea de noche
TTL_SEGUNDOS = 3600

_DIAS = ("lun", "mar", "mié", "jue", "vie", "sáb", "dom")


def _cuando(momento: dt.datetime) -> str:
    return f"{_DIAS[momento.weekday()]} {momento.day}/{momento.month} {momento:%H:%M}"


def _url_vuelo(v: dict) -> str:
    return f"/#/viajes/vuelo/{v['id']}"


def _url_hotel(h: dict) -> str:
    return f"/#/viajes/hotel/{h['id']}"


def _msg(title: str, body: str, url: str) -> dict:
    return {"title": title, "body": body, "url": url, "ttl": TTL_SEGUNDOS}


def checkin_web(lista: list[dict], now: dt.datetime) -> list[tuple[str, dict]]:
    out = []
    for v in lista:
        abre, sale = vuelos.abre_checkin(v), vuelos.salida(v)
        if not abre or not abre <= now < sale:
            continue
        local = sale.astimezone(vuelos.zona(v["zona"]))
        out.append((f"vcheckin:{v['id']}",
                    _msg(f"Ya podés hacer el check-in de {v['numero']}",
                         f"Sale el {_cuando(local)}. Tocá para ver el link de la aerolínea.", _url_vuelo(v))))
    return out


def _local(texto: str, zona: str) -> dt.datetime:
    return dt.datetime.fromisoformat(texto).replace(tzinfo=vuelos.zona(zona))


def hoteles(lista: list[dict], now: dt.datetime) -> list[tuple[str, dict]]:
    out = []
    for h in lista:
        entrada, salida = _local(h["checkin"], h["zona"]), _local(h["checkout"], h["zona"])
        donde = f" · {h['direccion']}" if h["direccion"] else ""
        if entrada - dt.timedelta(hours=CHECKIN_HOTEL_ANTES_H) <= now < entrada:
            out.append((f"hin:{h['id']}", _msg(f"Hoy hacés el check-in en {h['nombre']}",
                                               f"Desde las {entrada:%H:%M}{donde}", _url_hotel(h))))
        noche_anterior = (salida - dt.timedelta(days=1)).replace(hour=CHECKOUT_DESDE_HORA, minute=0)
        if noche_anterior <= now < salida:
            out.append((f"hout:{h['id']}", _msg(f"Mañana es el check-out de {h['nombre']}",
                                                f"Hasta las {salida:%H:%M}{donde}", _url_hotel(h))))
    return out


def _aviso_cambio(v: dict, tipo: str, valor, sale_local: dt.datetime) -> tuple[str, dict]:
    num, url = v["numero"], _url_vuelo(v)
    if tipo == "demora":
        previa = v.get("demora_min") or 0
        clave = f"vdemora:{v['id']}:{previa}>{valor}"
        if valor <= 0:
            return clave, _msg(f"{num} ya no tiene demora", f"Sale a las {sale_local:%H:%M}", url)
        return clave, _msg(f"{num} sale {valor} min más tarde", f"Nueva hora de salida: {sale_local:%H:%M}", url)
    if tipo == "puerta":
        titulo = f"{num} cambió de puerta: ahora {valor}" if v.get("puerta") else f"{num}: puerta {valor}"
        return f"vpuerta:{v['id']}:{valor}", _msg(titulo, f"Sale a las {sale_local:%H:%M}", url)
    return f"vcancel:{v['id']}", _msg(f"Se canceló {num}", "Revisá con la aerolínea cómo seguís.", url)


def estado(lista: list[dict], now: dt.datetime, consulta: Callable[[str, str], dict | None], ahora_ts: float,
           ) -> tuple[list[tuple[str, dict]], list[tuple[str, dict]]]:
    """(avisos, [(id del vuelo, campos a guardar)]). consulta(número, fecha) devuelve el estado o None.
    De noche solo avisa lo urgente; lo demás queda pendiente (no se guarda como avisado)."""
    de_noche = recordatorio.en_silencio(now)
    avisos, guardar = [], []
    for v in lista:
        sale = vuelos.salida(v)
        if not sale or not sale - dt.timedelta(hours=ESTADO_ANTES_H) <= now < sale:
            continue
        if v.get("consultado_en") and ahora_ts - v["consultado_en"] < INTERVALO_CONSULTA_S:
            continue
        nuevo = consulta(v["numero"], v["fecha"])
        campos: dict = {"consultado_en": ahora_ts}
        guardar.append((v["id"], campos))
        if not nuevo:
            continue
        campos.update(salida_utc=nuevo["salida_utc"], terminal=nuevo.get("terminal"), estado=nuevo.get("estado"))
        sale_real = dt.datetime.fromtimestamp(nuevo["salida_utc"], dt.UTC)
        if de_noche and sale_real - now > dt.timedelta(hours=URGENTE_H):
            campos.pop("estado")   # sin avisar no se avanza la base: sale a la mañana
            continue
        sale_local = (sale_real + dt.timedelta(minutes=nuevo["demora_min"])).astimezone(vuelos.zona(v["zona"]))
        for tipo, valor in vuelos.cambios(v, nuevo):
            avisos.append(_aviso_cambio(v, tipo, valor, sale_local))
            campos["demora_min" if tipo == "demora" else "puerta" if tipo == "puerta" else "estado"] = (
                nuevo["demora_min"] if tipo == "demora" else valor if tipo == "puerta" else nuevo["estado"])
    return avisos, guardar


def avisos(username: str, now: dt.datetime) -> list[tuple[str, dict]]:
    """Lo que corresponde avisar ahora a este usuario sobre sus vuelos y hoteles."""
    prefs = vuelos.get_prefs(username)
    lista_vuelos = vuelos.listar_vuelos(username)
    out: list[tuple[str, dict]] = []
    if not recordatorio.en_silencio(now):
        if prefs["viajes_checkin"]:
            out += checkin_web(lista_vuelos, now)
        if prefs["viajes_hoteles"]:
            out += hoteles(vuelos.listar_hoteles(username), now)
    if prefs["viajes_estado"] and lista_vuelos and vuelos.estado_disponible():
        nuevos, guardar = estado(lista_vuelos, now, lambda n, f: vuelos.consultar(n, f), time.time())
        for id_, campos in guardar:
            vuelos.guardar_estado(username, id_, campos)
        out += nuevos
    return out
