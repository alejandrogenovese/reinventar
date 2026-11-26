"""Cotización del dólar para el control de gastos: oficial y blue de Bluelytics, y la de tarjeta derivada.

Se actualiza al arrancar y cada COTIZACION_MINUTOS en segundo plano, y se guarda el historial (tabla cotizaciones): solo se agrega una
fila cuando alguna de las tres se movió más de MOVIMIENTO_MINIMO. Si la API falla se queda con la última guardada; si
nunca hubo ninguna, usa RESPALDO. Un gasto congela la cotización vigente a su fecha (app/gastos.py); si era la de
respaldo o tenía más de 48 h, queda marcado como estimada.
"""
import logging
import threading
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import httpx

from . import config, db, sandbox

log = logging.getLogger("reinventar.cotizacion")

URL = "https://api.bluelytics.com.ar/v2/latest"
TIMEOUT_SEGUNDOS = 10
MOVIMIENTO_MINIMO = Decimal("0.001")   # 0,1 %: por debajo no vale la pena sumar una fila al historial
DECIMALES = Decimal("0.0001")
EDAD_MAXIMA = timedelta(hours=48)      # más vieja que esto (o el respaldo), el gasto queda marcado como estimado
ZONA = ZoneInfo("America/Argentina/Buenos_Aires")   # el día del gasto es el de Argentina
# Respaldo si la API nunca respondió y la base está vacía (primer arranque sin red). Valores de venta de Bluelytics (la
# misma API) consultados el 25/11/2026: oficial 1630 y blue 1710; tarjeta = oficial × TARJETA_FACTOR (1,30) = 2119.
RESPALDO = {"oficial": Decimal("1630"), "blue": Decimal("1710"), "tarjeta": Decimal("2119")}


_ultima_consulta_ok: datetime | None = None   # última vez que la API respondió bien, haya o no movimiento


def _dec(valor) -> Decimal:
    return Decimal(str(valor)).quantize(DECIMALES)


def tarjeta_desde_oficial(oficial: Decimal) -> Decimal:
    return (oficial * Decimal(str(config.TARJETA_FACTOR))).quantize(DECIMALES)


def _venta(datos: dict, clave: str) -> Decimal:
    """El valor de venta (lo que se paga por un dólar) de una cotización de Bluelytics; lanza si no es un número > 0."""
    valor = _dec(datos[clave]["value_sell"])
    if valor <= 0:
        raise ValueError(f"{clave}: cotización no positiva")
    return valor


def parsear(datos: dict) -> dict[str, Decimal]:
    oficial = _venta(datos, "oficial")
    return {"oficial": oficial, "blue": _venta(datos, "blue"), "tarjeta": tarjeta_desde_oficial(oficial)}


def _se_movio(nueva: dict[str, Decimal], ultima: dict | None) -> bool:
    if ultima is None:
        return True
    return any(abs(nueva[k] - ultima[k]) / ultima[k] > MOVIMIENTO_MINIMO for k in ("oficial", "blue", "tarjeta"))


def ultima() -> dict | None:
    """La última fila del historial ({at, oficial, blue, tarjeta}) o None si está vacío."""
    with sandbox.real(), db.conn() as c:
        return c.execute("SELECT at, oficial, blue, tarjeta FROM cotizaciones ORDER BY at DESC, id DESC LIMIT 1"
                         ).fetchone()


def actual() -> dict:
    """La cotización vigente: {oficial, blue, tarjeta, at} (at en ISO). La última guardada o, sin ninguna, el respaldo."""
    fila = ultima()
    if fila is None:
        return {**RESPALDO, "at": None}
    return {"oficial": fila["oficial"], "blue": fila["blue"], "tarjeta": fila["tarjeta"], "at": fila["at"].isoformat()}


def edad_min(c: dict) -> int | None:
    """Minutos desde que la cotización es confiable: lo más reciente entre su fila y la última consulta exitosa a la
    API (una cotización que no se movió sigue siendo fresca). None si es el respaldo."""
    if c["at"] is None:
        return None
    desde = datetime.fromisoformat(c["at"])
    if _ultima_consulta_ok and _ultima_consulta_ok > desde:
        desde = _ultima_consulta_ok
    return max(0, int((datetime.now(UTC) - desde).total_seconds() // 60))


def vigente_en(fecha: date, ahora: datetime | None = None) -> dict:
    """La cotización que regía al terminar el día `fecha` (la última guardada hasta entonces; si el historial arranca
    después, la más antigua). {oficial, blue, tarjeta, at, respaldo, estimada}: `estimada` si es el respaldo o si dista
    más de 48 h del momento del gasto (el fin de su día, o ahora si es de hoy o futuro)."""
    ahora = ahora or datetime.now(UTC)
    fin = datetime.combine(fecha + timedelta(days=1), time.min, tzinfo=ZONA)
    with sandbox.real(), db.conn() as c:
        fila = c.execute("SELECT at, oficial, blue, tarjeta FROM cotizaciones WHERE at < %s "
                         "ORDER BY at DESC, id DESC LIMIT 1", (fin,)).fetchone()
        if fila is None:
            fila = c.execute("SELECT at, oficial, blue, tarjeta FROM cotizaciones ORDER BY at, id LIMIT 1").fetchone()
    if fila is None:
        return {**RESPALDO, "at": None, "respaldo": True, "estimada": True}
    # Para un gasto de hoy vale también la última consulta exitosa: una cotización que no se movió no está vieja.
    fresca = max(fila["at"], _ultima_consulta_ok) if _ultima_consulta_ok and fin > ahora else fila["at"]
    estimada = abs(min(ahora, fin) - fresca) > EDAD_MAXIMA
    return {"oficial": fila["oficial"], "blue": fila["blue"], "tarjeta": fila["tarjeta"],
            "at": fila["at"].isoformat(), "respaldo": False, "estimada": estimada}


def refrescar(cliente: httpx.Client | None = None) -> bool:
    """Pide la cotización y la guarda si se movió. Devuelve False si la API falló o devolvió algo inservible (en ese
    caso no toca nada: se sigue con la última guardada)."""
    global _ultima_consulta_ok
    propio = cliente is None
    cliente = cliente or httpx.Client(timeout=TIMEOUT_SEGUNDOS)
    try:
        r = cliente.get(URL)
        r.raise_for_status()
        nueva = parsear(r.json())
    except (httpx.HTTPError, ValueError, KeyError, TypeError, ArithmeticError) as e:
        log.warning("No se pudo actualizar la cotización (%s): sigo con la última guardada", e)
        return False
    finally:
        if propio:
            cliente.close()
    _ultima_consulta_ok = datetime.now(UTC)
    if _se_movio(nueva, ultima()):
        with sandbox.real(), db.conn() as c:
            c.execute("INSERT INTO cotizaciones (at, oficial, blue, tarjeta) VALUES (%s, %s, %s, %s)",
                      (datetime.now(UTC), nueva["oficial"], nueva["blue"], nueva["tarjeta"]))
    return True


def _loop() -> None:
    parar = threading.Event()
    while not parar.is_set():
        try:
            refrescar()
        except Exception:  # el hilo no puede morir: un error de base o de red no corta las próximas vueltas
            log.exception("Falló la actualización de la cotización")
        parar.wait(config.COTIZACION_MINUTOS * 60)


def start_worker() -> None:
    if config.COTIZACION_AUTO:
        threading.Thread(target=_loop, name="cotizacion", daemon=True).start()
    else:
        log.info("Cotización automática apagada (COTIZACION_AUTO)")
