"""Avisos de vuelos y hoteles cargados a mano (app/vuelos.py). Los arma app/push.due junto con el resto y salen por el
mismo hilo de 60 s: cada uno por clave en push_sent, así que ninguno se repite.

- Check-in web: desde que abre la ventana de la aerolínea (vuelos.CHECKIN_WEB) hasta la salida.
- Hotel: el check-in desde 3 h antes; el check-out desde las 19:00 de la noche anterior, nunca antes del check-in. Si la
  ventana cae entera en silencio, el aviso sale a la mañana.
- Estado del vuelo (AeroDataBox, solo con clave): desde 24 h antes (un vuelo sin hora, durante su día) hasta que aterriza
  (llegada_utc; si no se sabe, hasta la salida demorada); el intervalo entre consultas baja de 2 h a 15 min a medida que
  se acerca la salida (intervalo_s) y, con el vuelo en el aire, es de 30 min hasta que faltan 45 para aterrizar. Antes
  de salir avisa si la demora cambia 15 min o más contra la última avisada, si aparece o cambia la puerta, o si se
  cancela; ya en el aire, solo cuando aparece la cinta de equipaje (una vez por cinta). Lo que se compara se guarda
  recién cuando el aviso llegó a algún dispositivo (confirmar / descartar, los llama app/push.py).
- Pendientes del viaje (app/viajes_pendientes.py): cada uno con fecha límite avisa 3 días antes y el mismo día (clave
  pend:<id>:<día del aviso>), y los 3 días previos a la estadía sale a la mañana un resumen «Te faltan N pendientes»
  (pendres:<día>). Las fechas son días de Las Vegas, como el horario de silencio.
Ninguno sale en el horario de silencio (app/recordatorio.py), salvo el check-in web y el estado del vuelo cuando faltan
menos de 6 h para la salida (la cinta, que llega con el vuelo ya en el aire, siempre es urgente).
Cada tipo se apaga desde Ajustes (preferencias_avisos.viajes_*).
"""
import datetime as dt
import time
from collections.abc import Callable

from . import db, estadia, recordatorio, viajes_pendientes, vuelos

CHECKIN_HOTEL_ANTES_H = 3
CHECKOUT_DESDE_HORA = 19        # la noche anterior al check-out
ESTADO_ANTES_H = 24             # desde cuándo se consulta el estado del vuelo
# Cada cuánto se consulta el mismo vuelo según cuánto falta para la salida: lejos alcanza con poco y el cupo diario
# (AERODATABOX_TOPE_DIARIO) rinde para varios vuelos; cerca de la salida se mira más seguido.
INTERVALOS_CONSULTA = ((12, 120 * 60), (6, 60 * 60), (2, 30 * 60))   # (más de N horas faltan, segundos entre consultas)
INTERVALO_CERCA_S = 15 * 60
INTERVALO_EN_VUELO_S = 30 * 60  # con el vuelo en el aire alcanza con esto: solo se espera la cinta
ATERRIZAJE_CERCA_MIN = 45       # a menos de esto de aterrizar se vuelve al intervalo de cerca (la cinta aparece ahí)
VENTANA_EXTRA_SILENCIO_H = 2    # si una ventana cae toda en silencio, se avisa a la mañana hasta 2 h después
URGENTE_H = 6                   # con menos que esto para salir, el estado avisa aunque sea de noche
TTL_SEGUNDOS = 3600
PENDIENTE_AVISO_DIAS = (3, 0)   # días antes de la fecha límite en que se avisa
RESUMEN_DIAS_PREVIOS = 3        # el resumen sale los N días antes de que empiece la estadía
RESUMEN_HASTA_HORA = 12         # «a la mañana»: desde que termina el silencio hasta esta hora
URL_PENDIENTES = "/#/viajes/pendientes"

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
    """De noche solo sale si falta poco para la salida (URGENTE_H); si no, queda para la mañana."""
    de_noche = recordatorio.en_silencio(now)
    out = []
    for v in lista:
        abre, sale = vuelos.abre_checkin(v), vuelos.salida(v)
        if not abre or not abre <= now < sale:
            continue
        if de_noche and sale - now > dt.timedelta(hours=URGENTE_H):
            continue
        local = sale.astimezone(vuelos.zona(v["zona"]))
        out.append((f"vcheckin:{v['id']}",
                    _msg(f"Ya podés hacer el check-in de {v['numero']}",
                         f"Sale el {_cuando(local)}. Tocá para ver el link de la aerolínea.", _url_vuelo(v))))
    return out


def _local(texto: str, zona: str) -> dt.datetime:
    return dt.datetime.fromisoformat(texto).replace(tzinfo=vuelos.zona(zona))


def _fin_del_silencio(desde: dt.datetime) -> dt.datetime:
    """El primer momento, desde `desde`, que ya no es de noche (en la zona de `desde`)."""
    momento = desde
    for _ in range(24 * 4):
        if not recordatorio.en_silencio(momento):
            return momento
        momento += dt.timedelta(minutes=15)
    return momento


def _ventana(desde: dt.datetime, hasta: dt.datetime, tz) -> tuple[dt.datetime, dt.datetime]:
    """La ventana de aviso tal cual, salvo que caiga entera en el horario de silencio: entonces se alarga hasta un rato
    después de que termina, así el aviso sale a la mañana en vez de perderse."""
    momento = desde
    while momento < hasta:
        if not recordatorio.en_silencio(momento.astimezone(tz)):
            return desde, hasta
        momento += dt.timedelta(minutes=15)
    return desde, _fin_del_silencio(hasta.astimezone(tz)) + dt.timedelta(hours=VENTANA_EXTRA_SILENCIO_H)


def hoteles(lista: list[dict], now: dt.datetime) -> list[tuple[str, dict]]:
    if recordatorio.en_silencio(now):
        return []
    out = []
    for h in lista:
        entrada, salida = _local(h["checkin"], h["zona"]), _local(h["checkout"], h["zona"])
        donde = f" · {h['direccion']}" if h["direccion"] else ""
        desde, hasta = _ventana(entrada - dt.timedelta(hours=CHECKIN_HOTEL_ANTES_H), entrada, now.tzinfo)
        if desde <= now < hasta:
            out.append((f"hin:{h['id']}", _msg(f"Hoy hacés el check-in en {h['nombre']}",
                                               f"Desde las {entrada:%H:%M}{donde}", _url_hotel(h))))
        noche_anterior = (salida - dt.timedelta(days=1)).replace(hour=CHECKOUT_DESDE_HORA, minute=0)
        desde, hasta = _ventana(max(noche_anterior, entrada), salida, now.tzinfo)   # nunca antes de entrar al hotel
        if desde <= now < hasta:
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


def intervalo_s(falta: dt.timedelta) -> int:
    """Segundos entre consultas del mismo vuelo según cuánto falta para que salga."""
    for horas, segundos in INTERVALOS_CONSULTA:
        if falta > dt.timedelta(hours=horas):
            return segundos
    return INTERVALO_CERCA_S


def _llega(v: dict) -> dt.datetime | None:
    return dt.datetime.fromtimestamp(v["llegada_utc"], dt.UTC) if v.get("llegada_utc") else None


def _sale_demorada(v: dict) -> dt.datetime | None:
    sale = vuelos.salida(v)
    return sale + dt.timedelta(minutes=max(v.get("demora_min") or 0, 0)) if sale else None


def _ventana_estado(v: dict) -> tuple[dt.datetime, dt.datetime] | None:
    """Entre cuándo se consulta el estado: desde 24 h antes hasta que aterriza (la llegada que informó AeroDataBox) o, si
    no se sabe, hasta la salida demorada (la última demora avisada). Un vuelo sin hora se consulta durante todo su día (en
    la zona del vuelo); la respuesta trae la hora real."""
    sale, llega = vuelos.salida(v), _llega(v)
    if sale:
        fin = _sale_demorada(v)
        return sale - dt.timedelta(hours=ESTADO_ANTES_H), max(fin, llega) if llega else fin
    try:
        dia = dt.datetime.fromisoformat(v["fecha"]).replace(tzinfo=vuelos.zona(v["zona"]))
    except (KeyError, ValueError):
        return None
    fin = dia + dt.timedelta(days=1)
    return dia, max(fin, llega) if llega else fin


def _intervalo(v: dict, now: dt.datetime) -> int:
    """Segundos entre consultas: antes de salir, según cuánto falta (intervalo_s); en el aire, 30 min hasta que falta poco
    para aterrizar. Un vuelo sin hora conocida, cada 1 h."""
    sale, llega = vuelos.salida(v), _llega(v)
    if not sale:
        return INTERVALOS_CONSULTA[1][1]
    if llega and now >= _sale_demorada(v):
        cerca = llega - now <= dt.timedelta(minutes=ATERRIZAJE_CERCA_MIN)
        return INTERVALO_CERCA_S if cerca else INTERVALO_EN_VUELO_S
    return intervalo_s(sale - now)


def _aviso_cinta(v: dict, nuevo: dict) -> tuple[str, dict]:
    cinta, destino = nuevo["llegada_cinta"], nuevo.get("destino_nombre") or nuevo.get("destino_iata")
    donde = f"Llegás a {destino}" if destino else "Ya estás llegando"
    terminal = f" · terminal {nuevo['llegada_terminal']}" if nuevo.get("llegada_terminal") else ""
    return f"vcinta:{v['id']}:{cinta}", _msg(f"{v['numero']}: el equipaje sale por la cinta {cinta}",
                                             f"{donde}{terminal}.", _url_vuelo(v))


def _es_cancelado(texto: str | None) -> bool:
    return (texto or "").lower().startswith("cancel")


def estado(lista: list[dict], now: dt.datetime, consulta: Callable[[str, str], dict | None], ahora_ts: float,
           ) -> tuple[list[tuple[str, dict]], list[tuple[str, dict]], dict[str, tuple[str, dict]]]:
    """(avisos, [(id del vuelo, campos a guardar ya)], {clave del aviso: (id del vuelo, campos a guardar si el aviso llega)}).
    consulta(número, fecha) devuelve el estado o None. Lo que se compara para avisar (demora, puerta, cancelación) se guarda
    recién cuando el aviso llegó a algún dispositivo: si no, la próxima vuelta no vería diferencia y se perdería.
    De noche solo avisa lo urgente; lo demás queda pendiente (no se guarda como avisado)."""
    de_noche = recordatorio.en_silencio(now)
    avisos, guardar, diferidos = [], [], {}
    for v in lista:
        ventana = _ventana_estado(v)
        if not ventana or not ventana[0] <= now < ventana[1]:
            continue
        if v.get("consultado_en") and ahora_ts - v["consultado_en"] < _intervalo(v, now):
            continue
        nuevo = consulta(v["numero"], v["fecha"])
        campos: dict = {"consultado_en": ahora_ts}
        guardar.append((v["id"], campos))
        if not nuevo:
            continue
        campos.update(salida_utc=nuevo["salida_utc"], terminal=nuevo.get("terminal"),
                      **{k: nuevo.get(k) for k in vuelos.CAMPOS_LLEGADA})   # informativos: se guardan ya
        sale_real = dt.datetime.fromtimestamp(nuevo["salida_utc"], dt.UTC)
        if de_noche and sale_real - now > dt.timedelta(hours=URGENTE_H):
            continue   # sin avisar no se avanza la base: sale a la mañana
        if now >= sale_real + dt.timedelta(minutes=max(nuevo["demora_min"], 0)):
            # Ya salió: la demora o la puerta no sirven de nada. Solo la cinta, una vez por cinta (la clave de push_sent
            # no se libera porque no pasa por confirmar). Es urgente por definición: de noche también sale.
            if nuevo.get("llegada_cinta"):
                avisos.append(_aviso_cinta(v, nuevo))
            continue
        if not _es_cancelado(nuevo.get("estado")):
            campos["estado"] = nuevo.get("estado")
        sale_local = (sale_real + dt.timedelta(minutes=nuevo["demora_min"])).astimezone(vuelos.zona(v["zona"]))
        for tipo, valor in vuelos.cambios(v, nuevo):
            clave, mensaje = _aviso_cambio(v, tipo, valor, sale_local)
            avisos.append((clave, mensaje))
            campo, nuevo_valor = (("demora_min", nuevo["demora_min"]) if tipo == "demora"
                                  else ("puerta", valor) if tipo == "puerta" else ("estado", nuevo["estado"]))
            diferidos[clave] = (v["id"], {campo: nuevo_valor})
    return avisos, guardar, diferidos


def _aviso_fecha_limite(p: dict, hoy: dt.date) -> tuple[str, dict] | None:
    faltan = (p["fecha_limite"] - hoy).days
    if faltan not in PENDIENTE_AVISO_DIAS:
        return None
    titulo = "Hoy vence un pendiente del viaje" if faltan == 0 else f"En {faltan} días vence un pendiente del viaje"
    return f"pend:{p['id']}:{hoy.isoformat()}", _msg(titulo, p["texto"], URL_PENDIENTES)


def _resumen(lista: list[dict], now: dt.datetime) -> list[tuple[str, dict]]:
    hoy = now.date()
    faltan_dias = (estadia.INICIO_DE_LA_ESTADIA.date() - hoy).days
    if not lista or not 1 <= faltan_dias <= RESUMEN_DIAS_PREVIOS or now.hour >= RESUMEN_HASTA_HORA:
        return []
    n = len(lista)
    titulo = "Te falta 1 pendiente del viaje" if n == 1 else f"Te faltan {n} pendientes del viaje"
    cuando = "Mañana" if faltan_dias == 1 else f"En {faltan_dias} días"
    return [(f"pendres:{hoy.isoformat()}", _msg(titulo, f"{cuando} arranca el viaje. Tocá para ver la lista.",
                                                URL_PENDIENTES))]


def pendientes(lista: list[dict], now: dt.datetime) -> list[tuple[str, dict]]:
    """`lista`: los pendientes sin hacer. `now` en hora de Las Vegas. Nada sale de noche: el día del aviso sigue vigente
    a la mañana (la clave lleva el día, así que tampoco se repite)."""
    if recordatorio.en_silencio(now):
        return []
    hoy = now.date()
    out = [a for p in lista if p.get("fecha_limite") and (a := _aviso_fecha_limite(p, hoy))]
    return out + _resumen(lista, now)


# Estados a guardar cuando llegue el aviso, por (usuario, clave). Los usa push.tick después de notify.
_pendientes: dict[tuple[str, str], tuple[str, dict]] = {}


def confirmar(username: str, clave: str) -> None:
    """El aviso llegó a algún dispositivo: ahora sí se guarda el estado contra el que se compara. La clave de dedupe se
    libera: de ahí en más la que decide es el estado guardado, y así una demora o puerta que vuelve a un valor anterior
    (0 > 30 > 0 > 30, A > B > A) se vuelve a avisar."""
    pendiente = _pendientes.pop((username, clave), None)
    if not pendiente:
        return
    id_, campos = pendiente
    try:
        vuelos.guardar_estado(username, id_, campos)
    finally:
        db.unmark_push_sent(username, clave)


def olvidar_vuelo(username: str, id_: str) -> None:
    """El vuelo se editó y su salida cambió: los avisos de estado que esperaban confirmación eran del vuelo viejo. Si
    llegaran después, confirmar guardaría demora/puerta viejas sobre el vuelo nuevo."""
    for clave in [k for (u, k), (vid, _) in _pendientes.items() if u == username and vid == id_]:
        del _pendientes[(username, clave)]


def descartar(username: str, clave: str) -> None:
    """El aviso no llegó: el estado no se guarda y la próxima vuelta vuelve a consultar sin esperar el intervalo."""
    pendiente = _pendientes.pop((username, clave), None)
    if pendiente:
        vuelos.guardar_estado(username, pendiente[0], {"consultado_en": None})


def avisos(username: str, now: dt.datetime) -> list[tuple[str, dict]]:
    """Lo que corresponde avisar ahora a este usuario sobre sus vuelos, hoteles y pendientes del viaje."""
    prefs = vuelos.get_prefs(username)
    lista_vuelos = vuelos.listar_vuelos(username)
    out: list[tuple[str, dict]] = []
    if prefs["viajes_checkin"]:
        out += checkin_web(lista_vuelos, now)   # de noche solo sale lo urgente
    if prefs["viajes_hoteles"]:
        out += hoteles(vuelos.listar_hoteles(username), now)
    if prefs["viajes_pendientes"]:
        out += pendientes(viajes_pendientes.sin_hacer(username), now)
    if prefs["viajes_estado"] and lista_vuelos and vuelos.estado_disponible():
        nuevos, guardar, diferidos = estado(
            lista_vuelos, now, lambda n, f: vuelos.consultar(n, f, usuario=username), time.time())
        for id_, campos in guardar:
            vuelos.guardar_estado(username, id_, campos)
        for clave in [k for (u, k) in _pendientes if u == username]:
            del _pendientes[(username, clave)]
        _pendientes.update({(username, clave): pendiente for clave, pendiente in diferidos.items()})
        out += nuevos
    return out
