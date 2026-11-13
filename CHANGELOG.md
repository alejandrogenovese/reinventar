# Changelog

Todos los cambios relevantes de ReinventAR. El formato sigue [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/)
y la versión, [SemVer](https://semver.org/lang/es/). La versión vive en `app/__init__.py`.

## [Sin publicar]

### Agregado
- **Buscar en lo que grabaste**: en Inicio, arriba de tus grabaciones, un buscador que encuentra el momento de cada
  charla donde se habló de algo ("¿qué dijeron de Neptune?", "migrar Teradata"), por significado y por palabras, en
  castellano o en inglés. Cada resultado abre la transcripción en ese minuto. Las grabaciones viejas se indexan solas.
- **El chat de Buscar también responde con lo que grabaste**: además de las charlas del catálogo, usa lo que realmente
  se dijo en tus grabaciones y lo cita con un link al minuto (▶ 01:30). Debajo de la respuesta aparecen esos momentos.
- **Set para medir la búsqueda del catálogo** (`python -m scripts.evaluar_busqueda`): 30 preguntas con sus charlas
  relevantes, para comparar cambios en la búsqueda con números (acierto, recall y MRR en los primeros 10).

### Cambiado
- **Nueva cara, misma identidad** (naranja, Inter y JetBrains Mono): escala tipográfica de 6 pasos (los títulos de
  sección se separan de los de tarjeta), texto secundario con más contraste, un tinte suave por estado, radios más
  amables y, en oscuro, sin sombras (superficie y borde). Los emojis que hacían de íconos (🟠 🕒 📍 🎉 📌 ⚠ y el
  semáforo del armado guiado) pasan a íconos que siguen el color del tema.
- **Inicio**: «Ahora» se marca con borde naranja y un estado con punto; los avisos (cola, salí antes, superposición)
  son una fila tintada con ícono en vez de una tarjeta dentro de otra; el resto del día va en una lista agrupada.
- **Buscar**: una sola píldora de filtro, de 44 px, con el estado activo en tinta llena y ✕ para quitarlo; las charlas
  de Filtrar se ven compactas (hora, código, título, sede, hasta 3 tags y un botón + para agregar), así entran el doble
  por pantalla. En Preguntar, la pregunta va como burbuja, las citas son pastillas (el código en gris y el momento ▶ en
  naranja, ya no en rojo) y los momentos grabados van en una lista agrupada.
- **Detalle de grabación**: el título baja a 24 px. La barra inferior pasa a fondo sólido.
- **La búsqueda entiende mejor lo que pedís**: nuevo modelo de embeddings (embeddinggemma, multilingüe y con textos
  largos) y plurales que encuentran el singular ("mainframes" → "mainframe"). En el set de 30 preguntas, de las charlas
  que tienen que aparecer entre las 10 primeras se encuentran el 81 % (antes 74 %). Mejora Buscar, el chat, el armado
  guiado y la búsqueda en lo grabado.
- **El servidor usa mucha menos memoria para la búsqueda**: el modelo de embeddings pasa a su versión de 4 bits y corre
  con 2 hilos fijos. Misma calidad en el set de 30 preguntas (81 % → 80 %) y en la búsqueda por nombre de speaker, con
  ~0,4 GB de RAM en vez de más de 3 GB en Railway. Además, al terminar el cálculo del catálogo le devuelve al sistema la
  memoria que quedó libre.
- **Responder con la voz, más claro**: un botón compacto con el micrófono y, mientras graba, una barra con punto rojo,
  tiempo y nivel del micrófono (como al grabar una charla), para terminar o cancelar. Al terminar muestra "Pasando a
  texto…".
- **Chips de intereses y filtros más prolijos**: forma de píldora, tilde al elegirlos y el mismo estilo en el armado
  rápido, la entrevista y Buscar.
- **"Convertir en filtros" responde más rápido y cuesta mucho menos**: usa Claude Haiku 5.5 y reaprovecha (prompt
  caching) la lista de facetas, que es la mayor parte del pedido. Los filtros se siguen validando contra los valores
  reales del catálogo.
- **Transcripción de charlas más precisa** (cuando el STT pasa por el gateway): usa Whisper large-v3 completo en vez del
  turbo, que se equivoca menos con acentos y ruido de sala.
- **Menos errores con nombres técnicos al transcribir**: el STT recibe un vocabulario de AWS y datos (lakehouse,
  Neptune, Trainium, Redshift…), en las charlas y en las respuestas por voz de la entrevista, que además pasan a
  Whisper large-v3 completo.

### Arreglado
- Las pestañas del detalle (y los días del itinerario) quedaban tapadas al bajar porque se pegaban a 68 px fijos: ahora
  se pegan justo debajo del encabezado, sea cual sea su alto (notch, cuenta regresiva, modo prueba).
- La franja de arriba y la barra con el logo eran dos bloques pegados arriba que se pisaban: ahora son uno solo.
- Contraste: «Deshacer» del aviso en oscuro (2,8:1) y la píldora «Listo» (3,8:1) pasan AA; los horarios y códigos que
  debían ir en mono ahora lo están.

## [0.20.0] - 2026-11-10

### Agregado
- **Armado guiado del itinerario** (la opción recomendada; el cuestionario de siempre queda como "Armado rápido"):
  - **Te conocemos**: una entrevista de una pregunta por pantalla (rol, día a día, equipo, desafío, trayectoria,
    nivel, qué usan, qué te querés llevar, qué evitar y ritmo del día). Las respuestas largas se pueden dictar con 🎤.
    La IA hace hasta dos repreguntas y arma tu ficha, que podés corregir.
  - **Armá tu día**: elegís con qué arrancás y te propone lo que sigue según tu ficha y la distancia, con un estado
    por opción: 🟢 a tiempo, 🟡 justo, 🟠 salí N min antes (y a qué hora), 🔴 se superpone (con cuántos minutos). Si la
    charla no está reservada, cuenta 30 min de cola. "☆ Para otro día" guarda una charla en pendientes y vuelve primera
    cuando se repite. También: pausa, arrancar más tarde y "Completá el resto del día por mí".
  - En el itinerario, cada charla muestra si salís antes y se puede marcar como **✓ Reservada**.
- **Avisos de cola y de "salí antes"**: si una charla no está reservada, el aviso push, el banner y "Hoy" cuentan
  30 min de cola ("hacé la cola desde las 09:30"). Si elegiste irte antes de una charla para llegar a la siguiente, te
  avisa a esa hora ("Salí a las 09:26 para llegar a…").
- **Pasar a mi calendario**: desde el itinerario, un `.ics` con todo (charlas, eventos y Mis eventos) para el calendario
  del teléfono, con alarma a la hora de la cola si no está reservada.
- Al terminar un día en el armado guiado: resumen, lo que quedó afuera, **personas para conocer** (speakers de tus
  charlas de ese día, primero los de clientes, con link a su ficha para charlar) y eventos para la noche que no se pisan.
- **Importar reservas de AWS**: subí el calendario (.ics) que exportás desde tu agenda del portal de re:Invent y esas
  charlas quedan en tu itinerario como "✓ Reservada" (sin cola). Si ya tenías la charla en otro horario, la pasa al
  reservado.
- La ficha de la entrevista también se usa en el **chat de búsqueda** (prioriza lo que te sirve), en la **ficha para
  charlar con un speaker o empresa** y en el **armado rápido**.
- **Mis eventos**: cargá los eventos que te dan los proveedores (Eventos › "＋ Mi evento"), con sede, lugar de Google
  o dirección. Quedan fijados en tu itinerario, ocupan su horario, aparecen en "Hoy" y avisan cuándo salir.
- Resumen de las charlas en castellano: la ficha y las tarjetas lo muestran traducido y tienen un botón para ver el
  original en inglés. La elección queda recordada en el celular. La búsqueda por texto también busca en la traducción.
- Claves extraídas del resumen de cada charla: servicios de AWS que menciona (completan los que AWS no etiquetó),
  otras tecnologías (Iceberg, MCP, dbt…), conceptos en castellano e inglés y enfoque (novedades, arquitectura, caso
  de cliente, práctica guiada…). Son filtros nuevos en Explorar, aparecen en la ficha de la charla y mejoran la búsqueda.

- Modo prueba por usuario, que se prende desde Admin › Usuarios. Lo que hace ese usuario queda aparte y sus datos reales
  no se tocan. El admin elige si la transcripción y el LLM son de prueba (gratis) o reales, puede simular la hora y la
  ubicación (una sede) para probar "Hoy" antes del evento, y adelantar el reloj. Arriba de la app se ve una franja
  "MODO PRUEBA". Los datos de prueba se borran con un botón.

- Ubicación y "Llevame":
  - En "Hoy", la charla de ahora y la próxima muestran a cuánto quedan, cuánto se tarda caminando (Routes API de
    Google) y a qué hora salir.
  - Cada horario de una charla muestra la distancia.
  - "Llevame" abre Google Maps con la navegación a pie.
  - El mapa marca dónde estás.
  - La ubicación se usa solo en el celular; se puede apagar en Ajustes.

- Pestaña **Eventos**: desayunos, happy hours, fiestas y meetups alrededor de re:Invent, con imagen, resumen en
  castellano, tipo, organizadores, anotados, precio, si piden aprobación y si están llenos. Filtros por día y tipo, y
  orden por cercanía. Se agregan al itinerario (quedan fijados), aparecen en "Hoy" y avisan si se superponen con una charla.

- Countdown de lo fijado: una franja arriba cuenta cuánto falta para la próxima charla o evento fijado, dice a qué hora
  salir y cambia de color cuando hay que salir ya. Avisa "Salí ahora" y "Empieza en 5 min" (ajustables en Ajustes ›
  Alertas). "Hoy" y la ficha de los eventos muestran el countdown.
- Avisos de cambios: si AWS cambia el horario o la sala de algo de tu itinerario, lo da de baja, o un evento se llena,
  aparece un aviso hasta que tocás "Entendido".
- Notificaciones en el celular (Web Push), que se activan en Ajustes. Llegan con la app cerrada: cuándo salir, cuándo
  empieza y los cambios. En iPhone funcionan con la app instalada en la pantalla de inicio.
- Charlas repetidas: la ficha muestra los otros horarios, cuál tenés, con qué chocaría cada uno, y "Cambiar a este"
  (conserva el 📌). "Me la perdí" ofrece los otros horarios y charlas parecidas que empiezan pronto. Después de una charla
  fijada, la app pregunta si llegaste.
- Admin › Chequeo funcional: prueba cada parte de la app (catálogo, búsqueda, datos de prueba aislados, reloj simulado,
  proveedores, procesos, claves) y, en el celular, ubicación, mapa, Routes API y notificaciones.

### Cambiado
- En el itinerario, "Bloquear" pasa a llamarse "📌 Fijar". Las charlas y eventos que se superponen se marcan.
- Las sedes y sus coordenadas salen de un maestro en la base (`reinvent.sede`) en lugar de estar fijas en el código.
  Los bares y restaurantes dentro de un hotel (Canonita, Tableau…) se muestran como sala de ese hotel.
- Perfil profesional de los speakers: los perfiles que resultaron ser de otra persona con el mismo nombre ya no se
  muestran (ni el cargo en la charla ni la trayectoria en la ficha). Los que no se pudieron confirmar llevan el aviso
  "Puede no ser esta persona". Se revisaron a mano y con un LLM unos 600 perfiles dudosos.
- La app vive en `reinventar.app`. Entrar por `www.reinventar.app` redirige al dominio sin www, que es donde funcionan
  las passkeys y los avisos. Las passkeys creadas en el dominio anterior hay que volver a registrarlas.

## [0.19.0] - 2026-11-06

### Agregado
- CI en GitHub Actions: tests de núcleo contra Postgres en cada PR y en cada push a `dev`.
- Promoción automática `dev` → `main` (fast-forward) cuando pasan los tests; Railway deploya con el push a `main`.
- Claude Code en GitHub: `@claude` en issues y PRs, con PRs contra `dev` y `CLAUDE.md` como guía del repo.

### Seguridad
- Dependencias instaladas desde locks con hashes y solo wheels (`requirements.lock`, `requirements-dev.lock`) en CI y en Docker.
- Acciones de GitHub fijadas por SHA de commit.
- Hashes de caché (embeddings, temas, briefings) con SHA-256 en lugar de SHA-1/MD5. Al desplegar se recalculan una vez.
- Los logs no incluyen el texto que escribe el usuario, y los rechazos de passkeys se loguean en una sola línea (sin inyección de líneas falsas).

### Arreglado
- Errores que se perdían en silencio en la PWA: reintentar el procesamiento, fijar una charla, quitar una passkey,
  cambiar de pestaña y leer el audio pendiente ahora avisan con un mensaje. La subida en segundo plano muestra el error.
- El service worker avisa en consola si no puede guardar en caché, en vez de fallar en silencio.
- Test de filtros en lenguaje natural que fallaba según el orden (carrera con el nombrado de temas en segundo plano).

## [0.18.0] - 2026-11-05

### Agregado
- Pantalla **Hoy** en el inicio: la charla de ahora, la próxima y el resto del día, con "Grabar esta charla" (`GET /api/today`).
- **Buscar** unificado, con dos modos: Filtrar (facetas en un panel inferior) y Preguntar (chat con RAG).
- Diálogos propios para confirmar y para pedir datos, "Deshacer" en las acciones destructivas, tags, skeletons y tarjetas con riel de tiempo.
- Fichas de charla, speaker y empresa con jerarquía nueva y la sección "Para conversar".
- Medidor de nivel por segmentos y estado de la grabación visible.
- Versión única de la app, informada en `/health` y verificada por tests.
- `CHANGELOG.md`, `.editorconfig`, `.gitattributes` y `requirements-dev.txt`.

### Cambiado
- Rediseño completo sobre los tokens de Brick v2: logo de onda de voz, navegación con íconos y fuentes Inter y JetBrains Mono.
- La navegación queda en tres secciones: Inicio, Buscar e Itinerario. `#/explorar` y `#/preguntar` redirigen a Buscar.
- Las URLs de los íconos llevan versión para que el navegador tome el logo nuevo.

### Arreglado
- Accesibilidad: foco al título de cada pantalla, salto al contenido, orden de encabezados y foco devuelto al cerrar diálogos.
- Menos saltos de diseño al cargar (fuentes de reemplazo con métricas ajustadas y placeholders).

## [0.1.0] - 2026-10-17

Primera versión. Las versiones entre 0.1.0 y 0.18.0 no se publicaron por separado; el detalle está en el historial de git.
Lo que se sumó en ese período:
- Grabación con cola offline, transcripción, traducción y resumen por tipo de sesión.
- Login por usuario y contraseña, passkeys (Face ID / huella) y módulo de administración.
- Itinerario recomendado con resolución de choques y mapa de venues.
- Catálogo de re:Invent en Postgres, con fichas navegables de charla, speaker y empresa.
- Búsqueda híbrida (embeddings + BM25), chat Preguntar, explorador por facetas, filtros en lenguaje natural y temas emergentes.
- Briefing para preparar una conversación y bloques de transcripción de 15 s.

[Sin publicar]: https://github.com/alejandrogenovese/reinventar/compare/v0.20.0...HEAD
[0.20.0]: https://github.com/alejandrogenovese/reinventar/compare/v0.19.0...v0.20.0
[0.19.0]: https://github.com/alejandrogenovese/reinventar/compare/v0.18.0...v0.19.0
[0.18.0]: https://github.com/alejandrogenovese/reinventar/compare/v0.1.0...v0.18.0
[0.1.0]: https://github.com/alejandrogenovese/reinventar/releases/tag/v0.1.0
