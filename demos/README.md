# Demos de reinventar

Libretos para grabar videos demo de cada funcionalidad.

| Archivo | Qué es |
|---|---|
| `features.yml` | Relevamiento de las funcionalidades (52: 46 de usuario y 6 de admin), con ruta, pasos, selectores y fuentes. |
| `libretos/<feature>.yml` | Un libreto por funcionalidad: `titulo` y `beneficio` para la placa, y escenas con `accion`, `narracion`, `subtitulo` y `duracion_s`. Las `notas:` dicen qué preparar antes de grabar. |
| `diseno/placa-y-subtitulos.html` | Diseño aprobado de la placa de título y de los subtítulos (1920×1080, tokens de `web/css/tokens.css`). |

Todavía no hay specs de Playwright (`specs/`): las genera el agente `director` a partir de los libretos.

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
