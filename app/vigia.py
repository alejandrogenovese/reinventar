"""Vigía de los procesos de fondo: si el hilo del pipeline o el de los avisos push se mueren o se traban, reinicia el
contenedor.

Durante el evento nadie toca el código y UptimeRobot solo avisa: un hilo muerto deja las grabaciones en cola o los
avisos sin salir hasta que alguien reinicie a mano. Acá un hilo daemon mira cada INTERVALO_S lo mismo que /health
(salud.push_al_dia y pipeline.vivo); si algo da false FALLAS_SEGUIDAS veces seguidas, lo deja en el log y sale con
código 1, y Railway levanta el contenedor de nuevo (restart policy «on failure»). Al reiniciar, el pipeline re-encola
lo pendiente. Se apaga con VIGIA=0 (los tests lo apagan).
"""
import logging
import os
import threading
import time
from collections.abc import Callable

from . import config, pipeline, salud

log = logging.getLogger("reinventar.vigia")

INTERVALO_S = 60
FALLAS_SEGUIDAS = 3
# Al arrancar, el hilo de avisos todavía no latió y el pipeline puede estar re-encolando: no se mira nada antes de esto.
GRACIA_S = 5 * 60
CODIGO_SALIDA = 1
NOMBRE_HILO = "vigia"

_started = False


def motivos() -> tuple[str, ...]:
    """Los procesos de fondo que no andan ahora (vacío si todo bien)."""
    chequeos = {"pipeline": pipeline.vivo, "push": salud.push_al_dia}
    return tuple(nombre for nombre, anda in chequeos.items() if not anda())


def siguiente(seguidas: int, fallando: tuple[str, ...]) -> tuple[int, bool]:
    """Decisión pura: (fallas seguidas actualizadas, si hay que reiniciar). Un chequeo sano vuelve la cuenta a cero."""
    nuevas = seguidas + 1 if fallando else 0
    return nuevas, nuevas >= FALLAS_SEGUIDAS


def vuelta(seguidas: int, mirar: Callable[[], tuple[str, ...]] = motivos,
           salir: Callable[[int], None] = os._exit) -> int:
    """Un chequeo: mira, decide y, si toca, sale. Devuelve la cuenta de fallas seguidas."""
    try:
        fallando = mirar()
    except Exception:  # noqa: BLE001 - un chequeo que explota no es motivo para reiniciar; queda en el log
        log.exception("Vigía: no se pudo chequear")
        return seguidas
    nuevas, reiniciar = siguiente(seguidas, fallando)
    if fallando:
        log.warning("Vigía: no anda %s (%d de %d seguidas)", ", ".join(fallando), nuevas, FALLAS_SEGUIDAS)
    if reiniciar:
        log.critical("Vigía: %s sin andar %d chequeos seguidos; reinicio el contenedor", ", ".join(fallando), nuevas)
        logging.shutdown()  # que el motivo llegue al log antes de salir
        salir(CODIGO_SALIDA)
    return nuevas


def _loop() -> None:
    time.sleep(GRACIA_S)
    seguidas = 0
    while True:
        seguidas = vuelta(seguidas)
        time.sleep(INTERVALO_S)


def start_worker() -> None:
    global _started
    if not config.VIGIA or _started:
        return
    _started = True
    threading.Thread(target=_loop, name=NOMBRE_HILO, daemon=True).start()
