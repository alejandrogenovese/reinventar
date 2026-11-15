"""Los escenarios sin señal (#67, #68, #72) contra la app real en Chromium. Cada uno es una función async que recibe el
contexto y falla con AssertionError diciendo qué no pasó. Van en orden: el 3 sigue lo que dejó el 2."""
import asyncio
import json
import time
from dataclasses import dataclass

from tests_e2e.navegador import Pagina
from tests_e2e.servidor import Servidor

FRANJA = "Sin señal · datos de las"
GRABAR_SEGUNDOS = 12  # más que el TIMESLICE_MS (10 s) de recorder.js: sale al menos un pedazo antes de terminar
TITULO = "Grabación E2E sin señal"
ESPERA_SUBIDA_S = 60  # el uploader reintenta con backoff y se despierta solo cada 30 s


@dataclass(frozen=True)
class Contexto:
    pagina: Pagina
    servidor: Servidor


async def _click(p: Pagina, selector: str, que: str) -> None:
    await p.esperar(f"!!document.querySelector({json.dumps(selector)})", f"aparece {que}")
    await p.tocar(f"document.querySelector({json.dumps(selector)})")


async def _ir_a(p: Pagina, hash_: str) -> None:
    await p.evaluar(f"location.hash = {json.dumps(hash_)}")


async def _sesiones_en_servidor(c: Contexto) -> list[dict]:
    return c.servidor.pedir("/api/sessions")  # type: ignore[return-value]


async def preparar(c: Contexto) -> None:
    """Entra como el usuario de prueba y espera a que el service worker controle la página (hace falta para abrir sin red)."""
    p = c.pagina
    await p.ir(c.servidor.url + "/")
    await p.evaluar(f"localStorage.setItem('reinventar.token', {json.dumps(c.servidor.token)}); localStorage.setItem('reinventar.mustChangePassword', '0'); location.hash = '#/'")
    await p.recargar()
    await p.esperar("!!navigator.serviceWorker?.controller", "el service worker controla la página", 30)
    await p.esperar("document.body.innerText.includes('Tus grabaciones')", "Inicio cargado con red")


async def escenario_1_franja_sin_senal(c: Contexto) -> None:
    p = c.pagina
    await _ir_a(p, "#/itinerario")
    await p.esperar("document.body.innerText.includes('itinerario')", "Itinerario cargado con red")
    assert FRANJA not in await p.texto(), "con red no debería verse la franja «Sin señal»"
    await _ir_a(p, "#/")
    await p.esperar("document.body.innerText.includes('Tus grabaciones')", "Inicio con red")
    await p.offline(True)
    await p.recargar()
    await p.esperar(f"document.body.innerText.includes({json.dumps(FRANJA)})", "la franja «Sin señal» en Inicio tras recargar sin red")
    await _ir_a(p, "#/itinerario")
    await p.esperar(f"document.body.innerText.includes({json.dumps(FRANJA)})", "la franja «Sin señal» en Itinerario sin red")


async def escenario_2_grabar_sin_red(c: Contexto) -> None:
    p = c.pagina
    await p.offline(True)
    await _ir_a(p, "#/nueva")
    await p.esperar("!!document.querySelector('#title')", "formulario Nueva sesión")
    await p.evaluar(f"document.querySelector('#title').value = {json.dumps(TITULO)}")
    await _click(p, "button[type=submit]", "el botón «Preparar grabación»")
    await p.esperar("/^#\\/grabar\\/loc_[0-9a-f]{12}$/.test(location.hash)", "pantalla de grabar con una sesión local (loc_…)")
    # «Listo para grabar» se ve antes de que el micrófono abra: tocar ahí da «Primero abrí el micrófono». Se espera a que
    # el selector tenga micrófonos (los pone openMic cuando el stream ya está).
    await p.esperar("!!document.querySelector('#mic option')", "el micrófono abierto (selector con opciones)")
    await _click(p, "button.ra-rec", "el botón de grabar")
    await p.esperar("document.body.innerText.includes('Grabando')", "estado «Grabando»")
    await asyncio.sleep(GRABAR_SEGUNDOS)
    await p.esperar("[...document.querySelectorAll('button')].some(b => b.textContent.includes('Terminar') && !b.disabled)", "«Terminar» habilitado")
    await p.tocar("[...document.querySelectorAll('button')].find(b => b.textContent.includes('Terminar'))")
    await p.esperar("location.hash === '#/'", "vuelta a Inicio tras Terminar sin señal", 40)
    await p.esperar("document.body.innerText.includes('Grabadas en este celular') && document.body.innerText.includes('Esperando señal')",
                    "«Grabadas en este celular» con «Esperando señal»")
    assert not await _sesiones_en_servidor(c), "sin red no debería haberse creado nada en el servidor"


async def escenario_3_subida_al_volver(c: Contexto) -> None:
    p = c.pagina
    await p.offline(False)
    limite = time.monotonic() + ESPERA_SUBIDA_S
    while time.monotonic() < limite and not (sesiones := await _sesiones_en_servidor(c)):
        await asyncio.sleep(1)
    assert len(sesiones) == 1, f"al volver la red debía crearse una sola sesión y hay {len(sesiones)}: {sesiones}"
    assert sesiones[0]["title"] == TITULO, f"título inesperado: {sesiones[0].get('title')!r}"
    await asyncio.sleep(5)  # que un segundo ciclo del uploader no cree otra
    sesiones = await _sesiones_en_servidor(c)
    assert len(sesiones) == 1, f"la sesión se creó más de una vez: {len(sesiones)}"
    await p.esperar("(async () => { const n = await new Promise((res) => { const r = indexedDB.open('reinventar'); r.onsuccess = () => {"
                    " const q = r.result.transaction('chunks').objectStore('chunks').count(); q.onsuccess = () => res(q.result); }; });"
                    " return n === 0; })()", "la cola de IndexedDB vacía (los pedazos subieron)", ESPERA_SUBIDA_S)
    await _ir_a(p, "#/")
    await p.esperar("!document.body.innerText.includes('Grabadas en este celular') && !document.body.innerText.includes('Esperando señal')",
                    "el bloque «Grabadas en este celular» desapareció (sesión cerrada)", ESPERA_SUBIDA_S)
    final = (await _sesiones_en_servidor(c))[0]
    assert final["status"] != "recording", f"la sesión quedó sin cerrar en el servidor: status={final['status']}"


async def escenario_4_portal_cautivo(c: Contexto) -> None:
    p = c.pagina
    await p.offline(False)
    await _ir_a(p, "#/")
    await p.esperar("document.body.innerText.includes('Tus grabaciones')", "Inicio con red")
    await p.portal("*/api/today*")
    await p.recargar()
    await p.esperar("document.body.innerText.includes('Tus grabaciones')", "Inicio con /api/today devolviendo el portal")
    texto = await p.texto()
    assert "No se pudo cargar Hoy" not in texto, "Hoy debía mostrar la última copia y mostró un error"
    assert "Unexpected token" not in texto and "SyntaxError" not in texto, "se coló el error crudo del navegador"
    await p.portal("*/api/*")
    await p.recargar()
    await p.esperar(f"document.body.innerText.includes({json.dumps(FRANJA)})", "la franja «Sin señal» con todo el /api/ devolviendo el portal")
    await p.portal(None)


ESCENARIOS = (
    ("1 · franja «Sin señal» al recargar sin red", escenario_1_franja_sin_senal),
    ("2 · grabar sin red y terminar", escenario_2_grabar_sin_red),
    ("3 · al volver la red se sube y se cierra", escenario_3_subida_al_volver),
    ("4 · portal cautivo en /api/", escenario_4_portal_cautivo),
)
