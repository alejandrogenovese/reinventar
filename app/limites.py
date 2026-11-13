"""Límite de intentos para las rutas públicas de login (contraseña y passkey): frena la fuerza bruta y que una ráfaga de
pedidos deje sin CPU al único worker (cada login con contraseña corre PBKDF2).

En memoria: la app corre con un solo worker de uvicorn (Dockerfile), así que alcanza y no suma tablas. Un reinicio
borra los contadores, lo que es aceptable para este caso.
"""
import threading
import time
from collections import deque

from fastapi import HTTPException

VENTANA_SEGUNDOS = 15 * 60
FALLOS_POR_USUARIO = 5        # intentos fallidos contra la misma cuenta en la ventana
FALLOS_POR_IP = 20            # intentos fallidos desde la misma IP (varias cuentas) en la ventana
PEDIDOS_PASSKEY_POR_IP = 30   # pedidos de challenge de passkey por IP en la ventana (cada uno escribe en la base)


class Limite:
    """Cuenta eventos por clave en una ventana deslizante. Seguro entre threads."""

    def __init__(self, maximo: int, ventana: float = VENTANA_SEGUNDOS):
        self.maximo = maximo
        self.ventana = ventana
        self._eventos: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def _vigentes(self, clave: str, ahora: float) -> deque[float]:
        eventos = self._eventos.setdefault(clave, deque())
        while eventos and eventos[0] <= ahora - self.ventana:
            eventos.popleft()
        return eventos

    def excedido(self, clave: str, ahora: float | None = None) -> bool:
        with self._lock:
            return len(self._vigentes(clave, ahora or time.monotonic())) >= self.maximo

    def sumar(self, clave: str, ahora: float | None = None) -> None:
        with self._lock:
            self._vigentes(clave, ahora or time.monotonic()).append(ahora or time.monotonic())

    def limpiar(self, clave: str) -> None:
        with self._lock:
            self._eventos.pop(clave, None)

    def reiniciar(self) -> None:
        with self._lock:
            self._eventos.clear()


fallos_usuario = Limite(FALLOS_POR_USUARIO)
fallos_ip = Limite(FALLOS_POR_IP)
pedidos_passkey = Limite(PEDIDOS_PASSKEY_POR_IP)


def demasiados_intentos() -> HTTPException:
    return HTTPException(429, "Demasiados intentos. Esperá unos minutos y probá de nuevo.")


def reiniciar_todo() -> None:
    """Para los tests: cada test arranca sin intentos acumulados."""
    for limite in (fallos_usuario, fallos_ip, pedidos_passkey):
        limite.reiniciar()
