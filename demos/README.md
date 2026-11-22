# Demos de reinventar

Libretos para grabar videos demo de cada funcionalidad.

| Archivo | Qué es |
|---|---|
| `features.yml` | Relevamiento de las funcionalidades (52: 46 de usuario y 6 de admin), con ruta, pasos, selectores y fuentes. |
| `libretos/<feature>.yml` | Un libreto por funcionalidad: `titulo` y `beneficio` para la placa, y escenas con `accion`, `narracion`, `subtitulo` y `duracion_s`. Las `notas:` dicen qué preparar antes de grabar. |
| `diseno/placa-y-subtitulos.html` | Diseño aprobado de la placa de título y de los subtítulos (1920×1080, tokens de `web/css/tokens.css`). |

## Grabar

`specs/<feature>.spec.ts` graba cada libreto con Playwright (celular 430×932, cursor visible, sin la franja de modo prueba) y deja en `out/` el video `.webm` y el `<feature>.timeline.json` con el inicio real de cada escena y su subtítulo. Playwright se instala fuera del repo (no hay `package.json`):

```sh
npm i --prefix ~/.cache/rx-pw @playwright/test && ~/.cache/rx-pw/node_modules/.bin/playwright install chromium
TESTER_PASSWORD=… NODE_PATH=~/.cache/rx-pw/node_modules ~/.cache/rx-pw/node_modules/.bin/playwright test -c demos/playwright.config.ts demos/specs/viaje-hub.spec.ts
```

Para el video final (1920×1080: placa de 3 s, el celular al centro y los subtítulos de cada escena, según el diseño aprobado) hace falta además `ffmpeg`:

```sh
NODE_PATH=~/.cache/rx-pw/node_modules node demos/componer.cjs [feature ...]
```

Deja `demos/out/final/<feature>.mp4`; sin argumentos compone todas las que tengan un timeline completo.

Si cambia un libreto, regenerá las specs con `demos/specs/_generar.js` (el uso está en su encabezado).

Cada demo necesita el reloj de `tester` en un momento distinto (se fija por `PUT /api/admin/users/tester/sandbox`):

| Reloj (Las Vegas) | Demos |
|---|---|
| mar 1/12 07:00 | `anuncios-sin-reserva` (antes de la keynote) |
| lun 30/11 10:05 | `me-la-perdi` (terminó IND374-R y se repite el martes 13:00) |
| mar 1/12 13:50, con IND302-R fijada y reservada | `franja-cuenta-regresiva` (después se desfija y se desmarca) |
| mar 1/12 11:40 | todas las demás |

`shows` necesita `DEMO_SHOW_ID` (en staging: `e3db62330fd2`, «WOW - The Vegas Spectacular», con funciones todos los días).
Al final van `itinerario-armar-dia`, `itinerario-armado-rapido` y `cerrar-sesion`, que cambian el itinerario o la sesión.
Después de `avisos-lleno-cola` hay que retirar el aviso (`DELETE /api/lleno/DAT307-R1`): no va al schema de prueba.

### Grabadas (37 de 40)

No se pudieron grabar:

- `notificaciones-push`: el navegador de Playwright no se puede suscribir al push (ni con Google Chrome, con o sin ventana), así que nunca aparece «Probar una notificación». Hay que grabarla a mano en un celular.
- `ofertas`: staging no tiene ofertas cargadas; la lista dice «No hay ofertas vigentes».
- `cambio-de-contrasena`: necesita una cuenta descartable (`DEMO_USUARIO`, `DEMO_PASSWORD_ACTUAL`, `DEMO_PASSWORD_NUEVA`); con `tester` se saltea.

## Estado de staging para grabar

Las demos usan el usuario `tester` de `staging.reinventar.app` (la contraseña no va en el repo: en los libretos es `{{TESTER_PASSWORD}}`).
`tester` es admin y está en **modo prueba**, así que todo lo que se crea queda en el schema de prueba y no toca datos reales.

- **Reloj simulado:** martes 1/12/2026 a las 11:40 (Las Vegas). El reloj sigue corriendo desde que se fija, así que antes de grabar hay que volver a fijarlo (Admin › Usuarios › Modo prueba).
  A esa hora Inicio muestra «Ahora» (DAT307-R1, Wynn/Encore) y «Después» (14:30).
- **Ubicación simulada:** Venetian (sede 7). La charla de «Ahora» queda a 620 m, así que se ve Llevame.
- **STT:** fake. **LLM:** real (para que la ficha, el itinerario y las opciones de «Armá tu día» tengan contenido de verdad).
- **Ficha:** creada a partir de una entrevista ficticia (arquitecto de soluciones cloud en banca).
- **Itinerario:** armado rápido, con 18 charlas del 30/11 al 4/12. El viernes 4/12 tiene una sola charla, para «Armá tu día».
- **Viajes:** 4 vuelos de United (EZE–IAH–LAS, ida y vuelta) y 2 hoteles (Trump International y The LINQ).
  La app no tiene la zona horaria de Houston: los vuelos que salen de ahí están cargados en hora de Buenos Aires.

Para volver a empezar desde cero: Admin › Modo prueba › borrar datos de prueba (borra los de todos los usuarios en modo prueba).

## Funcionalidades sin libreto

| Feature | Por qué |
|---|---|
| `ficha-de-charla` | No hay selector para el link a la ficha ni un código de charla de prueba. |
| `itinerario-entrevista` | Los campos de las preguntas no tienen selector y la variante por voz necesita micrófono. |
| `mi-evento` | Faltan selectores en el formulario (nombre, día, desde, lugar). |
| `importar-reservas-aws` | Hay que subir un `.ics`, y los libretos no tienen acción para subir archivos. |
| `cruzar-con-excel` | Hay que subir un `.xlsx` o `.csv`, igual que el anterior. |
| `franja-cambios-itinerario` | El aviso aparece solo cuando AWS cambia una charla; no se puede provocar desde la app. |

## `data-testid` para agregar

El front no tiene ninguno. Estos destrabarían o harían más firmes varias demos:
`entrevista-rol`, `entrevista-industria`, `entrevista-opcion`, `mievento-*`, link a la ficha de charla,
`show-card`, `evento-agregar`, `gastos-presupuesto-guardar` y los campos del formulario de vuelo.
