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
ESPERA_SECCIONES_S = 2  # que las secciones de Inicio que se piden aparte (anuncios) terminen de resolverse antes de leer el texto
TITULO_CIERRE = "Grabación E2E cierre diferido"
ESPERA_CIERRE_S = 45  # tras volver la red y abrir la app: subir lo que falta y cerrar la sesión pedida
ESPERA_SUBIDA_S = 60# el uploader reintenta con backoff y se despierta solo cada 30 s
INICIO_CARGADO = "document.body.innerText.includes('Tus grabaciones')"  # condición JS: Inicio ya dibujó la lista


@dataclass(frozen=True)
class Contexto:
    pagina: Pagina
    servidor: Servidor


async def _click(p: Pagina, selector: str, que: str) -> None:
    await p.esperar(f"!!document.querySelector({json.dumps(selector)})", f"aparece {que}")
    await p.tocar(f"document.querySelector({json.dumps(selector)})")


async def _ir_a(p: Pagina, hash_: str) -> None:
    await p.evaluar(f"location.hash = {json.dumps(hash_)}")


def _sesiones_en_servidor(c: Contexto) -> list[dict]:
    return c.servidor.pedir("/api/sessions")  # type: ignore[return-value]


async def preparar(c: Contexto) -> None:
    """Entra como el usuario de prueba y espera a que el service worker controle la página (hace falta para abrir sin red)."""
    p = c.pagina
    await p.ir(c.servidor.url + "/")
    await p.evaluar(f"localStorage.setItem('reinventar.token', {json.dumps(c.servidor.token)}); localStorage.setItem('reinventar.mustChangePassword', '0'); location.hash = '#/'")
    await p.recargar()
    await p.esperar("!!navigator.serviceWorker?.controller", "el service worker controla la página", 30)
    await p.esperar(INICIO_CARGADO, "Inicio cargado con red")


async def escenario_1_franja_sin_senal(c: Contexto) -> None:
    p = c.pagina
    await _ir_a(p, "#/itinerario")
    await p.esperar("document.body.innerText.includes('itinerario')", "Itinerario cargado con red")
    assert FRANJA not in await p.texto(), "con red no debería verse la franja «Sin señal»"
    await _ir_a(p, "#/")
    await p.esperar(INICIO_CARGADO, "Inicio con red")
    await p.offline(True)
    await p.recargar()
    await p.esperar(f"document.body.innerText.includes({json.dumps(FRANJA)})", "la franja «Sin señal» en Inicio tras recargar sin red")
    # «Anuncios sin reserva» se pide aparte de Hoy y sin franja: sin señal tiene que usar la última copia, no el error.
    await asyncio.sleep(ESPERA_SECCIONES_S)
    texto = await p.texto()
    assert "No se pudieron cargar los anuncios" not in texto, "los anuncios sin reserva no usaron la última copia sin señal"
    # Una lista de grabaciones vacía que es copia puede estar vieja: no se dice «todavía no grabaste».
    assert "Todavía no grabaste" not in texto and "Sin señal: tus grabaciones se muestran cuando vuelva la red" in texto, "el vacío de «Tus grabaciones» sin señal"
    # Ajustes sin señal sigue diciendo quién es (la copia la dejó la consulta de /api/me), no «Sesión no válida».
    await _ir_a(p, "#/ajustes")
    await p.esperar("document.body.innerText.includes('Conectado como e2e.')", "«Conectado como e2e.» en Ajustes sin señal")
    assert "Sesión no válida" not in await p.texto(), "Ajustes sin señal dijo «Sesión no válida»"
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
    # Desde #81 el botón queda deshabilitado («Abriendo el micrófono…») hasta que hay stream: «Listo para grabar» ya es seguro.
    await p.esperar("document.body.innerText.includes('Listo para grabar')", "micrófono listo")
    await _click(p, "button.ra-rec", "el botón de grabar")
    await p.esperar("document.body.innerText.includes('Grabando')", "estado «Grabando»")
    await asyncio.sleep(GRABAR_SEGUNDOS)
    await p.esperar("[...document.querySelectorAll('button')].some(b => b.textContent.includes('Terminar') && !b.disabled)", "«Terminar» habilitado")
    await p.tocar("[...document.querySelectorAll('button')].find(b => b.textContent.includes('Terminar'))")
    # Mientras termina sin señal, la pantalla dice que quedó guardada y deja volver al inicio (cierra sola con señal).
    await p.esperar("document.body.innerText.includes('Terminada · esperando señal')", "el estado «Terminada · esperando señal»", 10)
    await p.esperar("document.body.innerText.includes('Sin señal: la grabación quedó guardada en el celular')", "el aviso de que quedó guardada en el celular", 10)
    await p.esperar("[...document.querySelectorAll('button')].some(b => b.textContent.includes('Volver al inicio') && !b.disabled)", "el botón «Volver al inicio»", 10)
    await p.esperar("location.hash === '#/'", "vuelta a Inicio tras Terminar sin señal", 40)
    await p.esperar("document.body.innerText.includes('Grabadas en este celular') && document.body.innerText.includes('Esperando señal')",
                    "«Grabadas en este celular» con «Esperando señal»")
    assert not _sesiones_en_servidor(c),"sin red no debería haberse creado nada en el servidor"


async def escenario_3_subida_al_volver(c: Contexto) -> None:
    p = c.pagina
    await p.offline(False)
    limite = time.monotonic() + ESPERA_SUBIDA_S
    while time.monotonic() < limite and not (sesiones := _sesiones_en_servidor(c)):
        await asyncio.sleep(1)
    assert len(sesiones) == 1, f"al volver la red debía crearse una sola sesión y hay {len(sesiones)}: {sesiones}"
    assert sesiones[0]["title"] == TITULO, f"título inesperado: {sesiones[0].get('title')!r}"
    await asyncio.sleep(5)  # que un segundo ciclo del uploader no cree otra
    sesiones = _sesiones_en_servidor(c)
    assert len(sesiones) == 1, f"la sesión se creó más de una vez: {len(sesiones)}"
    await p.esperar("(async () => { const n = await new Promise((res) => { const r = indexedDB.open('reinventar'); r.onsuccess = () => {"
                    " const q = r.result.transaction('chunks').objectStore('chunks').count(); q.onsuccess = () => res(q.result); }; });"
                    " return n === 0; })()", "la cola de IndexedDB vacía (los pedazos subieron)", ESPERA_SUBIDA_S)
    await _ir_a(p, "#/")
    await p.esperar("!document.body.innerText.includes('Grabadas en este celular') && !document.body.innerText.includes('Esperando señal')",
                    "el bloque «Grabadas en este celular» desapareció (sesión cerrada)", ESPERA_SUBIDA_S)
    final = _sesiones_en_servidor(c)[0]
    assert final["status"] != "recording", f"la sesión quedó sin cerrar en el servidor: status={final['status']}"


async def escenario_4_portal_cautivo(c: Contexto) -> None:
    p = c.pagina
    await p.offline(False)
    await _ir_a(p, "#/")
    await p.esperar(INICIO_CARGADO, "Inicio con red")
    await p.portal("*/api/today*")
    await p.recargar()
    await p.esperar(INICIO_CARGADO, "Inicio con /api/today devolviendo el portal")
    # Hoy es la copia y la lista de grabaciones vino fresca: la franja tiene que estar en Hoy, una sola vez.
    await p.esperar(f"document.body.innerText.includes({json.dumps(FRANJA)})", "la franja «Sin señal» en Hoy (copia de /api/today)")
    texto = await p.texto()
    assert texto.count(FRANJA) == 1, f"la franja debía verse una vez y se ve {texto.count(FRANJA)}"
    assert "No se pudo cargar Hoy" not in texto, "Hoy debía mostrar la última copia y mostró un error"
    assert "Unexpected token" not in texto and "SyntaxError" not in texto, "se coló el error crudo del navegador"
    await p.portal("*/api/*")
    await p.recargar()
    await p.esperar(f"document.body.innerText.includes({json.dumps(FRANJA)})", "la franja «Sin señal» con todo el /api/ devolviendo el portal")
    await p.esperar("!document.querySelector('.ra-skel')", "Hoy terminó de cargar")
    texto = await p.texto()
    assert texto.count(FRANJA) == 1, f"con Hoy y la lista en copia la franja no se repite: se ve {texto.count(FRANJA)} veces"
    await p.portal(None)


async def escenario_5_ver_contrasena_en_el_login(c: Contexto) -> None:
    p = c.pagina
    await p.offline(False)
    await p.evaluar("localStorage.removeItem('reinventar.token'); location.hash = '#/login'")  # el 6 se vuelve a loguear
    await p.esperar("!!document.querySelector('#password')", "el login")
    tipo = "document.querySelector('#password').type"
    assert await p.evaluar(tipo) == "password", "el campo debía arrancar oculto"
    await p.tocar("document.querySelector('.ra-pass-eye')")
    assert await p.evaluar(tipo) == "text", "tocar el ojo debía mostrar la contraseña"
    assert await p.evaluar("document.querySelector('.ra-pass-eye').getAttribute('aria-pressed')") == "true"
    # Táctil (44 px) y sin tapar el lugar del ícono del gestor de contraseñas, que va pegado al borde derecho del campo.
    m = await p.evaluar("(() => { const i = document.querySelector('#password').getBoundingClientRect(), b = document.querySelector('.ra-pass-eye').getBoundingClientRect();"
                        " return { ancho: b.width, alto: b.height, libre: i.right - b.right }; })()")
    assert m["ancho"] >= 44 and m["alto"] >= 44, f"el ojo debía tener 44 px de toque y tiene {m}"
    assert m["libre"] >= 40, f"el ojo tapa el borde derecho del campo (el ícono del gestor): libre={m['libre']}"
    await p.tocar("document.querySelector('.ra-pass-eye')")
    assert await p.evaluar(tipo) == "password", "tocar de nuevo debía ocultarla"
    # Al enviar el formulario vuelve a password aunque el login falle (credenciales de prueba inválidas).
    await p.tocar("document.querySelector('.ra-pass-eye')")
    await p.evaluar("document.querySelector('#username').value = 'nadie'; document.querySelector('#password').value = 'clave-que-no-existe'")
    await p.tocar("document.querySelector('button[type=submit]')")
    await p.esperar("document.body.innerText.includes('Usuario o contraseña inválidos')", "el aviso de login inválido")
    assert await p.evaluar(tipo) == "password", "al enviar el formulario la contraseña debía volver a ocultarse"
    # Se vuelve a entrar como el usuario de prueba para los escenarios que siguen.
    await p.evaluar(f"localStorage.setItem('reinventar.token', {json.dumps(c.servidor.token)}); location.hash = '#/'")
    await p.esperar(INICIO_CARGADO, "Inicio de nuevo con la sesión de prueba")


async def escenario_6_cierre_diferido(c: Contexto) -> None:
    """Sesión creada con señal: se corta la red, Terminar deja el cierre pedido y lo hace el uploader al volver, con la pestaña cerrada de por medio."""
    p = c.pagina
    await p.offline(False)
    await _ir_a(p, "#/nueva")
    await p.esperar("!!document.querySelector('#title')", "formulario Nueva sesión")
    await p.evaluar(f"document.querySelector('#title').value = {json.dumps(TITULO_CIERRE)}")
    await _click(p, "button[type=submit]", "el botón «Preparar grabación»")
    await p.esperar("/^#\\/grabar\\/(?!loc_)[\\w-]+$/.test(location.hash)", "pantalla de grabar con una sesión del servidor (no loc_…)")
    await p.esperar("document.body.innerText.includes('Listo para grabar')", "micrófono listo")
    await _click(p, "button.ra-rec", "el botón de grabar")
    await p.esperar("document.body.innerText.includes('Grabando')", "estado «Grabando»")
    await asyncio.sleep(GRABAR_SEGUNDOS)  # con red: el primer pedazo (10 s) sube solo; el resto queda en el celular
    await p.offline(True)
    await p.esperar("[...document.querySelectorAll('button')].some(b => b.textContent.includes('Terminar') && !b.disabled)", "«Terminar» habilitado")
    await p.tocar("[...document.querySelectorAll('button')].find(b => b.textContent.includes('Terminar'))")
    await p.esperar("document.body.innerText.includes('Terminada · esperando señal')", "el estado «Terminada · esperando señal»", 15)
    await p.esperar("[...document.querySelectorAll('button')].some(b => b.textContent.includes('Volver al inicio') && !b.disabled)", "el botón «Volver al inicio»", 10)
    await p.tocar("[...document.querySelectorAll('button')].find(b => b.textContent.includes('Volver al inicio'))")
    await p.esperar("location.hash === '#/' && document.body.innerText.includes('Grabadas en este celular') && document.body.innerText.includes('Esperando señal')",
                    "la tarjeta «Esperando señal» en «Grabadas en este celular»", 15)
    propias = [s for s in _sesiones_en_servidor(c) if s["title"] == TITULO_CIERRE]
    assert len(propias) == 1 and propias[0]["status"] == "recording", f"antes de volver la red la sesión debía seguir abierta: {propias}"
    # Se cierra la pestaña (la app deja de correr) y vuelve la red: nada se cierra solo sin la app abierta.
    await p.reabrir()
    await p.offline(False)
    await asyncio.sleep(3)
    propias = [s for s in _sesiones_en_servidor(c) if s["title"] == TITULO_CIERRE]
    assert propias[0]["status"] == "recording", f"con la app cerrada no debería haberse cerrado la sesión: status={propias[0]['status']}"
    # Se abre la app de nuevo: el uploader sube lo que falta y cierra la sesión pedida.
    await p.ir(c.servidor.url + "/#/")
    limite = time.monotonic() + ESPERA_CIERRE_S
    while time.monotonic() < limite:
        propias = [s for s in _sesiones_en_servidor(c) if s["title"] == TITULO_CIERRE]
        if propias and propias[0]["status"] != "recording":
            break
        await asyncio.sleep(1)
    assert len(propias) == 1, f"debía haber una sola sesión «{TITULO_CIERRE}» en el servidor y hay {len(propias)}"
    assert propias[0]["status"] != "recording", f"la sesión no se cerró tras volver la red ({ESPERA_CIERRE_S} s): status={propias[0]['status']}"
    await p.esperar("!document.body.innerText.includes('Grabadas en este celular')", "la tarjeta local desapareció", 20)


# La API de gastos (PR del backend) no está en esta rama: el escenario 7 la simula en la página (fetch) con la forma real
# de sus respuestas (app/gastos.py: aplicados, cambios con el gasto completo y ahora) y solo comprueba lo que hace el front.
STUB_GASTOS = """(() => {
  window.__sync = [];
  const original = window.fetch.bind(window);
  const json = (cuerpo) => new Response(JSON.stringify(cuerpo), { status: 200, headers: { "content-type": "application/json" } });
  const delServidor = (c) => ({ ...c, cotizacion_oficial: 1000, cotizacion_blue: 1200, cotizacion_tarjeta: 1300,
    monto_usd: c.moneda === 'USD' ? c.monto : Math.round(c.monto / 13) / 100, foto_url: null });
  window.fetch = async (url, init = {}) => {
    const ruta = String(url);
    if (!ruta.startsWith('/api/gastos')) return original(url, init);
    if (!navigator.onLine) throw new TypeError('Failed to fetch');
    if (ruta.startsWith('/api/gastos/cotizacion')) return json({ oficial: 1000, blue: 1200, tarjeta: 1300, at: new Date().toISOString() });
    if (ruta.startsWith('/api/gastos/sync')) {
      const cuerpo = JSON.parse(init.body);
      const ahora = new Date().toISOString();
      window.__sync.push({ ...cuerpo, ahora });
      return json({ aplicados: cuerpo.cambios.map((c) => c.client_id), cambios: cuerpo.cambios.map(delServidor), ahora });
    }
    return json({ gastos: [], totales: { usd: 0, por_categoria: {}, por_dia: {} }, presupuesto: { total_usd: 1000, diario_usd: 100, por_categoria: {} } });
  };
})()"""
BOTON_POR_TEXTO = "[...document.querySelectorAll('button')].find(b => b.textContent.trim() === {texto})"
ESPERA_SYNC_GASTOS_S = 30
ESPERA_ANIMACION_HOJA_S = 1


async def escenario_7_gasto_sin_red(c: Contexto) -> None:
    """Un gasto cargado sin señal queda en el celular como «Sin sincronizar» y viaja una sola vez al volver la red."""
    p = c.pagina
    await p.offline(False)
    await _ir_a(p, "#/ajustes")
    await p.esperar("document.body.innerText.includes('Conectado como')", "Ajustes cargado")
    await p.evaluar(STUB_GASTOS)
    await _ir_a(p, "#/gastos")
    await p.esperar("document.body.innerText.includes('Todavía no cargaste gastos')", "la pantalla de Gastos vacía")
    await p.offline(True)
    await p.tocar(BOTON_POR_TEXTO.format(texto=json.dumps("Cargar gasto")))
    await p.esperar("!!document.querySelector('dialog[open] #g-monto')", "la hoja de carga")
    await asyncio.sleep(ESPERA_ANIMACION_HOJA_S)  # la hoja sube con animación: el toque real calcula el centro del botón antes
    await p.evaluar("(() => { const m = document.querySelector('#g-monto'); m.value = '14,10'; m.dispatchEvent(new Event('input')); document.querySelector('#g-nota').value = 'Café E2E'; })()")
    await p.tocar(BOTON_POR_TEXTO.format(texto=json.dumps("Guardar gasto")))
    await p.esperar("!document.querySelector('dialog[open]')", "la hoja cerrada tras guardar")
    await p.esperar("document.body.innerText.includes('Café E2E') && document.body.innerText.includes('Sin sincronizar')",
                    "el gasto en la lista, marcado «Sin sincronizar»")
    enviados = "window.__sync.flatMap((s) => s.cambios).length"  # el sync al abrir la pantalla (con red) iba con la lista vacía
    assert await p.evaluar(enviados) == 0, "sin señal no debía haber salido ningún gasto"
    await p.offline(False)
    await p.esperar(f"{enviados} > 0", "el gasto sale al volver la red", ESPERA_SYNC_GASTOS_S)
    await p.esperar("!document.body.innerText.includes('Sin sincronizar')", "el gasto ya sin la marca «Sin sincronizar»", ESPERA_SYNC_GASTOS_S)
    cambios = await p.evaluar("window.__sync.flatMap((s) => s.cambios)")
    assert len(cambios) == 1, f"el gasto debía viajar una sola vez y viajó {len(cambios)}: {cambios}"
    assert cambios[0]["monto"] == 14.1 and cambios[0]["moneda"] == "USD" and cambios[0]["nota"] == "Café E2E", cambios[0]
    assert len(cambios[0]["client_id"]) == 36, f"el client_id debía ser un UUID: {cambios[0]['client_id']}"
    # El cursor del próximo sync es el `ahora` que devolvió el servidor, no el reloj del teléfono.
    await p.evaluar("document.dispatchEvent(new Event('visibilitychange'))")
    await p.esperar("window.__sync.length >= 2", "otro sync al volver a primer plano", ESPERA_SYNC_GASTOS_S)
    syncs = await p.evaluar("window.__sync")
    assert syncs[-1]["desde"] == syncs[-2]["ahora"], f"el desde debía ser el ahora del servidor: {syncs[-2:]}"


ESCENARIOS = (
    ("1 · franja «Sin señal» al recargar sin red", escenario_1_franja_sin_senal),
    ("2 · grabar sin red y terminar", escenario_2_grabar_sin_red),
    ("3 · al volver la red se sube y se cierra", escenario_3_subida_al_volver),
    ("4 · portal cautivo en /api/", escenario_4_portal_cautivo),
    ("5 · ver y ocultar la contraseña en el login", escenario_5_ver_contrasena_en_el_login),
    ("6 · terminar sin red una sesión ya creada y cerrarla al volver", escenario_6_cierre_diferido),
    ("7 · cargar un gasto sin red y sincronizarlo al volver", escenario_7_gasto_sin_red),
)
