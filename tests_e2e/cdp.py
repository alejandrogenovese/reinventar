"""Cliente mínimo del protocolo de DevTools (CDP) sobre websockets: enviar un comando y esperar su respuesta por id, y
suscribirse a eventos. Con sesiones «planas» (flatten): una sola conexión al navegador maneja varias pestañas."""
import asyncio
import json
from collections.abc import Callable

from websockets.asyncio.client import connect

TIMEOUT_COMANDO_S = 30


class ErrorCdp(RuntimeError):
    """El navegador contestó un comando con error."""


class Cdp:
    def __init__(self, ws) -> None:
        self._ws = ws
        self._siguiente_id = 0
        self._pendientes: dict[int, asyncio.Future] = {}
        self._oyentes: list[tuple[str, str | None, Callable[[dict], None]]] = []
        self._lector = asyncio.create_task(self._leer())

    @classmethod
    async def conectar(cls, url_ws: str) -> "Cdp":
        # max_size=None: las capturas de pantalla llegan como mensajes grandes.
        return cls(await connect(url_ws, max_size=None, ping_interval=None))

    async def _leer(self) -> None:
        try:
            async for crudo in self._ws:
                self._despachar(json.loads(crudo))
        finally:
            for futuro in self._pendientes.values():
                if not futuro.done():
                    futuro.set_exception(ErrorCdp("Se cerró la conexión con el navegador"))

    def _despachar(self, msg: dict) -> None:
        if "id" in msg:
            futuro = self._pendientes.pop(msg["id"], None)
            if futuro is None or futuro.done():
                return
            if "error" in msg:
                futuro.set_exception(ErrorCdp(f"{msg['error'].get('message')} ({msg['error'].get('code')})"))
            else:
                futuro.set_result(msg.get("result", {}))
            return
        for evento, sesion, callback in self._oyentes:
            if msg.get("method") == evento and (sesion is None or msg.get("sessionId") == sesion):
                callback(msg.get("params", {}))

    async def enviar(self, metodo: str, params: dict | None = None, sesion: str | None = None) -> dict:
        self._siguiente_id += 1
        id_ = self._siguiente_id
        futuro = asyncio.get_running_loop().create_future()
        self._pendientes[id_] = futuro
        msg = {"id": id_, "method": metodo, "params": params or {}, **({"sessionId": sesion} if sesion else {})}
        await self._ws.send(json.dumps(msg))
        async with asyncio.timeout(TIMEOUT_COMANDO_S):
            return await futuro

    def en(self, evento: str, callback: Callable[[dict], None], sesion: str | None = None) -> None:
        """Llama a callback(params) cada vez que llega el evento (de esa sesión, o de cualquiera si es None)."""
        self._oyentes.append((evento, sesion, callback))

    async def esperar(self, evento: str, sesion: str | None = None, plazo_s: float = 15) -> dict:
        """El próximo evento de ese tipo."""
        futuro = asyncio.get_running_loop().create_future()
        self.en(evento, lambda p: futuro.done() or futuro.set_result(p), sesion)
        async with asyncio.timeout(plazo_s):
            return await futuro

    async def cerrar(self) -> None:
        self._lector.cancel()
        await self._ws.close()
