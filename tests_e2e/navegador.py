"""Chromium con micrófono falso y una pestaña manejable por CDP: navegar, evaluar JS, cortar la red (también la del service
worker), simular un portal cautivo y sacar capturas."""
import asyncio
import base64
import glob
import os
import shutil
import tempfile
import time
from contextlib import asynccontextmanager
from pathlib import Path

from tests_e2e.cdp import Cdp

CACHE_PLAYWRIGHT = Path.home() / "Library" / "Caches" / "ms-playwright"
CANDIDATOS = (
    str(CACHE_PLAYWRIGHT / "chromium-*" / "chrome-mac-arm64" / "*.app" / "Contents" / "MacOS" / "*"),
    str(CACHE_PLAYWRIGHT / "chromium-*" / "chrome-mac-x64" / "*.app" / "Contents" / "MacOS" / "*"),
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
)
ESPERA_ARRANQUE_S = 20
PORTAL_HTML = "<html><body><h1>Portal cautivo de prueba</h1><p>Iniciá sesión en el Wi-Fi</p></body></html>"
PANTALLA = {"width": 390, "height": 844, "deviceScaleFactor": 2, "mobile": True}


class SinNavegador(RuntimeError):
    """No hay Chromium/Chrome: la prueba se saltea."""


def buscar_navegador() -> str:
    """E2E_CHROME, o el Chromium del caché de Playwright (el más nuevo), o el Chrome de la Mac."""
    elegido = os.environ.get("E2E_CHROME")
    if elegido:
        if not os.access(elegido, os.X_OK):
            raise SinNavegador(f"E2E_CHROME={elegido} no existe o no se puede ejecutar.")
        return elegido
    for patron in CANDIDATOS:
        for ruta in sorted(glob.glob(patron), reverse=True):
            if os.access(ruta, os.X_OK) and not os.path.isdir(ruta):
                return ruta
    raise SinNavegador("No encontré Chromium ni Chrome. Instalá Chrome o apuntá E2E_CHROME al ejecutable.")


async def abrir_pestana(cdp: Cdp) -> tuple[str, str]:
    """Una pestaña nueva con los dominios que se usan y el tamaño de un celular: (id del objetivo, id de la sesión CDP)."""
    objetivo = (await cdp.enviar("Target.createTarget", {"url": "about:blank"}))["targetId"]
    sesion = (await cdp.enviar("Target.attachToTarget", {"targetId": objetivo, "flatten": True}))["sessionId"]
    for dominio in ("Page", "Runtime", "Network"):
        await cdp.enviar(f"{dominio}.enable", {}, sesion)
    await cdp.enviar("Emulation.setDeviceMetricsOverride", {**PANTALLA, "screenWidth": 390, "screenHeight": 844}, sesion)
    return objetivo, sesion


class Pagina:
    """Una pestaña: un Cdp, la sesión de esa pestaña y lo que el navegador contó en consola."""

    def __init__(self, cdp: Cdp, objetivo: str, sesion: str, origen: str) -> None:
        self.cdp, self.objetivo, self.sesion, self.origen = cdp, objetivo, sesion, origen
        self.consola: list[str] = []
        self._sw_emulados: list[str] = []
        self._escuchar()

    def _escuchar(self) -> None:
        sesion = self.sesion
        self.cdp.en("Runtime.consoleAPICalled", lambda p: self._anotar(p), sesion)
        self.cdp.en("Runtime.exceptionThrown", lambda p: self.consola.append("EXCEPCIÓN " + p["exceptionDetails"].get("text", "")
                                                                              + " " + str(p["exceptionDetails"].get("exception", {}).get("description", ""))), sesion)
        self.cdp.en("Fetch.requestPaused", lambda p: asyncio.ensure_future(self._servir_portal(p)), sesion)

    async def reabrir(self) -> None:
        """Cierra la pestaña de verdad (la app deja de correr: ni timers ni uploader) y abre otra, sin emulación de red.
        Navegar a about:blank no sirve para esto: la emulación se pierde y el uploader de la página vieja alcanza a salir."""
        await self.cdp.enviar("Target.closeTarget", {"targetId": self.objetivo})
        self.objetivo, self.sesion = await abrir_pestana(self.cdp)
        self._sw_emulados = []
        self._escuchar()

    def _anotar(self, p: dict) -> None:
        if p["type"] in ("error", "warning"):
            self.consola.append(f"{p['type']}: " + " ".join(str(a.get("value", a.get("description", ""))) for a in p["args"]))

    async def _enviar(self, metodo: str, params: dict | None = None) -> dict:
        return await self.cdp.enviar(metodo, params, self.sesion)

    async def ir(self, url: str) -> None:
        cargada = asyncio.ensure_future(self.cdp.esperar("Page.loadEventFired", self.sesion, 30))
        await self._enviar("Page.navigate", {"url": url})
        await cargada

    async def recargar(self) -> None:
        cargada = asyncio.ensure_future(self.cdp.esperar("Page.loadEventFired", self.sesion, 30))
        await self._enviar("Page.reload")
        await cargada

    async def evaluar(self, js: str):
        r = await self._enviar("Runtime.evaluate", {"expression": js, "awaitPromise": True, "returnByValue": True})
        if "exceptionDetails" in r:
            raise RuntimeError("Falló el JS de la página: " + str(r["exceptionDetails"].get("exception", {}).get("description")))
        return r["result"].get("value")

    async def esperar(self, js_condicion: str, que: str, plazo_s: float = 20):
        """Reintenta la condición hasta que dé algo verdadero; si no, falla diciendo qué se esperaba."""
        limite, ultimo = time.monotonic() + plazo_s, None
        while time.monotonic() < limite:
            try:
                ultimo = await self.evaluar(js_condicion)
            except RuntimeError as e:  # la página se está recargando: se reintenta
                ultimo = str(e)
            if ultimo:
                return ultimo
            await asyncio.sleep(0.25)
        raise AssertionError(f"Timeout esperando: {que} (último valor: {ultimo!r})")

    async def tocar(self, js_elemento: str) -> None:
        """Toque real (mouse del navegador, con gesto de usuario) en el centro del elemento que devuelve la expresión JS."""
        centro = await self.evaluar(f"(() => {{ const e = ({js_elemento}); if (!e) return null; e.scrollIntoView({{block: 'center'}});"
                                    " const r = e.getBoundingClientRect(); return [r.x + r.width / 2, r.y + r.height / 2]; })()")
        assert centro, f"no encontré el elemento a tocar: {js_elemento}"
        for tipo in ("mousePressed", "mouseReleased"):
            await self._enviar("Input.dispatchMouseEvent", {"type": tipo, "x": centro[0], "y": centro[1], "button": "left", "clickCount": 1})

    async def texto(self) -> str:
        return await self.evaluar("document.body.innerText")

    async def offline(self, cortada: bool) -> None:
        """Corta (o devuelve) la red de la pestaña y de su service worker, para que el shell tampoco salga a la red."""
        condiciones = {"offline": cortada, "latency": 0, "downloadThroughput": -1, "uploadThroughput": -1}
        await self._enviar("Network.emulateNetworkConditions", condiciones)
        for objetivo in (await self.cdp.enviar("Target.getTargets"))["targetInfos"]:
            if objetivo["type"] == "service_worker" and objetivo["url"].startswith(self.origen):
                sw = (await self.cdp.enviar("Target.attachToTarget", {"targetId": objetivo["targetId"], "flatten": True}))["sessionId"]
                await self.cdp.enviar("Network.enable", {}, sw)
                await self.cdp.enviar("Network.emulateNetworkConditions", condiciones, sw)

    async def portal(self, patron_url: str | None) -> None:
        """Con patrón: lo que pida la página a esa URL recibe un 200 con HTML (portal cautivo). Sin patrón: se desactiva."""
        if patron_url is None:
            await self._enviar("Fetch.disable")
        else:
            await self._enviar("Fetch.enable", {"patterns": [{"urlPattern": patron_url, "requestStage": "Request"}]})

    async def _servir_portal(self, p: dict) -> None:
        cuerpo = base64.b64encode(PORTAL_HTML.encode()).decode()
        await self._enviar("Fetch.fulfillRequest", {"requestId": p["requestId"], "responseCode": 200, "body": cuerpo,
                                                    "responseHeaders": [{"name": "Content-Type", "value": "text/html; charset=utf-8"}]})

    async def captura(self, ruta: Path) -> None:
        ruta.parent.mkdir(parents=True, exist_ok=True)
        ruta.write_bytes(base64.b64decode((await self._enviar("Page.captureScreenshot", {"format": "png"}))["data"]))


@asynccontextmanager
async def navegador(origen: str, perfil_base: Path | None = None):
    """Lanza Chromium sin cabeza, con micrófono falso, y entrega una Pagina vacía con el permiso de micrófono ya dado."""
    ejecutable = buscar_navegador()
    perfil = tempfile.mkdtemp(prefix="reinventar-e2e-chrome-", dir=perfil_base)
    proceso = await asyncio.create_subprocess_exec(
        ejecutable, "--headless=new", "--remote-debugging-port=0", f"--user-data-dir={perfil}", "--no-first-run",
        "--no-default-browser-check", "--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream",
        "--autoplay-policy=no-user-gesture-required", "--disable-gpu", "about:blank",
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
    cdp = None
    try:
        archivo = Path(perfil) / "DevToolsActivePort"
        limite = time.monotonic() + ESPERA_ARRANQUE_S
        while not archivo.exists() or len(archivo.read_text().splitlines()) < 2:
            if proceso.returncode is not None or time.monotonic() > limite:
                raise RuntimeError("Chromium no abrió el puerto de depuración.")
            await asyncio.sleep(0.2)
        puerto, ruta_ws = archivo.read_text().splitlines()[:2]
        cdp = await Cdp.conectar(f"ws://127.0.0.1:{puerto}{ruta_ws}")
        await cdp.enviar("Browser.grantPermissions", {"origin": origen, "permissions": ["audioCapture"]})
        objetivo, sesion = await abrir_pestana(cdp)
        yield Pagina(cdp, objetivo, sesion, origen)
    finally:
        if cdp:
            await cdp.cerrar()
        if proceso.returncode is None:
            proceso.terminate()
            try:
                async with asyncio.timeout(10):
                    await proceso.wait()
            except TimeoutError:
                proceso.kill()
                await proceso.wait()
        shutil.rmtree(perfil, ignore_errors=True)
