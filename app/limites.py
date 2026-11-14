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

    def consumir(self, clave: str) -> bool:
        """Anota un uso si todavía hay cupo y devuelve True; si ya se llegó al máximo, devuelve False sin anotar.
        Revisa y anota bajo el mismo lock: dos pedidos simultáneos no se cuelan los dos por el último lugar."""
        with self._lock:
            ahora = time.monotonic()
            eventos = self._vigentes(clave, ahora)
            if len(eventos) >= self.maximo:
                return False
            eventos.append(ahora)
            return True

    def limpiar(self, clave: str) -> None:
        with self._lock:
            self._eventos.pop(clave, None)

    def reiniciar(self) -> None:
        with self._lock:
            self._eventos.clear()


fallos_usuario = Limite(FALLOS_POR_USUARIO)
fallos_ip = Limite(FALLOS_POR_IP)
pedidos_passkey = Limite(PEDIDOS_PASSKEY_POR_IP)

# Endpoints que gastan LLM/STT, por usuario. Los topes son holgados para uso real en el evento (alguien que prueba
# varias búsquedas seguidas no los toca) y frenan a un script o una cuenta comprometida que queme crédito.
# Ventana de 10 minutos para lo que se usa en ráfagas (buscar, preguntar) y de 1 hora para lo pesado.
VENTANA_CORTA = 10 * 60
VENTANA_LARGA = 60 * 60
BUSQUEDAS_NL_POR_USUARIO = 30      # /api/k/explore/parse: un LLM chico por búsqueda en lenguaje natural
PREGUNTAS_POR_USUARIO = 20         # /api/k/ask
FICHAS_POR_USUARIO = 40            # /api/k/briefing (en caché por usuario; solo cuenta cuando se pide de nuevo)
ENTREVISTA_POR_USUARIO = 60        # repreguntas, ficha y audio de la entrevista: ~12 audios + ajustes
ITINERARIOS_POR_USUARIO = 10       # /api/itinerary/generate: cada uno es una llamada grande al LLM
ADMIN_LINKS_POR_USUARIO = 30       # vista previa y guardado de eventos por link (admin)

busquedas_nl = Limite(BUSQUEDAS_NL_POR_USUARIO, VENTANA_CORTA)
preguntas = Limite(PREGUNTAS_POR_USUARIO, VENTANA_CORTA)
briefings = Limite(FICHAS_POR_USUARIO, VENTANA_LARGA)
entrevista = Limite(ENTREVISTA_POR_USUARIO, VENTANA_LARGA)
itinerarios = Limite(ITINERARIOS_POR_USUARIO, VENTANA_LARGA)
admin_links = Limite(ADMIN_LINKS_POR_USUARIO, VENTANA_LARGA)


def demasiados_intentos() -> HTTPException:
    return HTTPException(429, "Demasiados intentos. Esperá unos minutos y probá de nuevo.")


def exigir_cupo(limite: Limite, usuario: str, accion: str) -> None:
    """Gasta un uso del usuario o corta con 429 y un mensaje claro. Se llama antes de usar el LLM o el STT."""
    if not limite.consumir(usuario):
        minutos = max(1, round(limite.ventana / 60))
        raise HTTPException(429, f"Hiciste muchos pedidos de {accion} en poco tiempo. "
                                 f"Esperá unos minutos (el límite se renueva cada {minutos} min) y probá de nuevo.")


TODOS = (fallos_usuario, fallos_ip, pedidos_passkey, busquedas_nl, preguntas, briefings, entrevista, itinerarios,
         admin_links)


def reiniciar_todo() -> None:
    """Para los tests: cada test arranca sin intentos acumulados."""
    for limite in TODOS:
        limite.reiniciar()
