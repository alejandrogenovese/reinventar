# Arquitectura

Resumen de las piezas de ReinventAR y de cómo viaja una grabación. El detalle de cada módulo está en
[Estructura del código](#estructura-del-código); el deploy, en [Despliegue y operación](despliegue.md).

## Componentes

```
 Celular (PWA)                       Railway
┌────────────────────┐  HTTPS   ┌───────────────────────────────┐   red privada   ┌──────────────────┐
│ web/  JS sin build │ ───────▶ │ app/  FastAPI (1 worker)      │ ──────────────▶ │ litellm          │
│ IndexedDB (cola)   │          │  · API + hosting de la PWA    │                 │ infra/litellm    │
│ service worker     │          │  · pipeline en un thread      │                 │ alias rx-*/stt-* │
└────────────────────┘          │  · ffmpeg                     │                 └────────┬─────────┘
                                │  · Volume /data (audio)       │                          │
                                └──────────────┬────────────────┘                          ▼
                                               │                          Anthropic · Groq (Whisper)
                                               ▼                          Langfuse (trazas y scores)
                                ┌───────────────────────────────┐
                                │ Postgres + pgvector           │
                                │  schema app: estado de la app │
                                │  schema reinvent: catálogo    │
                                └───────────────────────────────┘
```

| Pieza | Dónde | Qué hace |
|---|---|---|
| **App FastAPI** | `app/`, `Dockerfile` | API (`/api/*`), login por usuario/contraseña o passkey, hosting de la PWA y `/health`. Al arrancar (`lifespan` en `app/main.py`) inicializa la base, carga el catálogo y los eventos a memoria, calcula embeddings en segundo plano y arranca los workers del pipeline y de las notificaciones push. Corre con un solo worker de uvicorn: el pipeline vive en un thread del mismo proceso. |
| **PWA** | `web/` | JavaScript sin build. Graba con MediaRecorder, guarda cada pedazo en IndexedDB (`web/js/store.js`) y lo sube en orden con reintentos (`web/js/recorder.js`); el service worker (`web/sw.js`) cachea la app para que abra sin señal. |
| **Postgres + pgvector** | `app/pg.py`, `app/db.py`, `scripts/migraciones/` | Un pool de conexiones compartido. El schema `app` (`DB_SCHEMA`) guarda grabaciones, usuarios, sesiones, itinerarios y los fragmentos de lo grabado con sus vectores; el schema `reinvent` tiene el catálogo de re:Invent (charlas, speakers, empresas, sedes), cargado desde una máquina local con `scripts/sync_to_railway.sh`. El modo prueba (`app/sandbox.py`) usa un schema aparte para los datos del usuario. |
| **LLM y STT** | `app/llm.py`, `app/stt.py`, `app/llm_router.py` | Cada parte de la app pide una *tarea* (resumen, traducción, chat…) y el router elige el modelo según el proveedor: Claude directo (`LLM_PROVIDER=anthropic`) o el gateway (`litellm`). El STT va a un endpoint compatible con OpenAI (Groq Whisper) o por el gateway. En tests todo corre en modo `fake`. |
| **LiteLLM** | `infra/litellm/` | Gateway en un servicio aparte de Railway: un alias `rx-<tarea>` por tarea y `stt-<uso>` por uso del STT (`config.yaml`). Cambiar el modelo de una parte es editar el alias y reiniciar el servicio, sin deployar la app. Registra el gasto por tarea y por usuario. |
| **Langfuse** | `app/trazas.py`, `app/langfuse_scores.py`, `app/langfuse_metricas.py` | LiteLLM manda cada llamada como traza a Langfuse Cloud. La app agrega la metadata (una traza por grabación o por pedido, versión del prompt y de la app, tags `prod`/`dev`/`prueba`, enmascarado de lo personal), manda scores de calidad en segundo plano y lee métricas para el tablero de Admin. |
| **Búsqueda** | `app/search.py`, `app/embeddings.py`, `app/fragmentos.py` | Embeddings locales (fastembed, el modelo queda en `/data/models`) más BM25 o `tsvector`, fusionados con RRF; sirve para el catálogo y para buscar dentro de lo grabado. |
| **Railway** | dashboard (sin `railway.toml`) | Deploya la app desde `main` con el `Dockerfile`; el Volume `/data` guarda audio y modelos. Postgres (pgvector) y LiteLLM son servicios del mismo proyecto. |
| **GitHub Actions** | `.github/workflows/` | `ci-promote.yml`: ruff y tests de núcleo en cada push y PR a `dev`; si pasan en `dev`, adelanta `main` y Railway deploya. `claude.yml`: Claude Code responde a `@claude` en issues y PRs. |

## Flujo de una grabación

1. **Crear la sesión.** La PWA hace `POST /api/sessions` (título, tipo de sesión y, opcional, la charla del catálogo).
2. **Grabar y subir.** MediaRecorder graba en `audio/webm;codecs=opus` y genera un pedazo cada ~10 s. Cada pedazo se
   guarda primero en IndexedDB y se sube con `PUT /api/sessions/{sid}/chunks/{part}/{seq}`; el servidor lo escribe de
   forma atómica en el Volume (`/data`) y lo registra en la base. El pedazo local se borra recién cuando el servidor
   confirma, así que sin señal se acumulan y suben solos al volver la red. Si la página se recarga, arranca una
   **parte** nueva.
3. **Terminar.** `POST /api/sessions/{sid}/finish` manda cuántos pedazos tiene cada parte. Si falta alguno, responde
   409 con la lista y no procesa; si están todos, la sesión entra a la cola del pipeline (`queued`).
4. **Procesar** (`app/pipeline.py`, un thread; todo queda en una sola traza de Langfuse):
   1. *Ensamblar* (`app/audio.py`): ffmpeg decodifica cada parte por separado, las une a 16 kHz mono y corta el audio
      en pedazos de 10 minutos (`STT_SEGMENT_SECONDS`) para respetar el límite de las APIs de STT.
   2. *Transcribir* (`app/stt.py`): Whisper con un vocabulario de nombres propios de AWS; los segmentos se agrupan en
      bloques de lectura de ~15 s. Si no hubo voz, la grabación termina con un error claro.
   3. *Traducir* al castellano por lotes (`TRANSLATE_BATCH`), con los nombres propios de la charla; las líneas que el
      modelo se saltea se reintentan una por una y se cuentan como score.
   4. *Resumir* sobre el original en inglés con timestamps, según el tipo de sesión (`app/prompts.py`) y el contexto
      oficial de la charla si se eligió una.
   5. *Indexar* la transcripción en fragmentos de ~40 s con vectores y `tsvector` para buscar en lo grabado.
5. **Lista.** La sesión pasa a `ready` y la PWA muestra resumen y transcripción; se puede exportar a Markdown
   (`GET /api/sessions/{sid}/export.md`). Si algo falla, queda en `error` y se reintenta con `POST .../retry`
   (reusa la transcripción salvo que se pida empezar de cero). Al reiniciar el contenedor, lo que quedó a medio procesar
   vuelve a la cola.

## Cómo se comporta la grabación

- MediaRecorder en `audio/webm;codecs=opus` a 32 kbps mono: una hora ≈ 14 MB. Se desactivan el echo cancellation, el noise suppression y el AGC del navegador.
- Cada pedazo se guarda primero en IndexedDB y se borra recién cuando el servidor confirma. Sin señal se acumulan y suben solos al volver la red.
- Si la página se recarga a mitad de la grabación, al volver a grabar arranca una **parte** nueva. El backend decodifica cada parte por separado y después las une.
- *Terminar y procesar* espera a que no quede nada por subir y le pasa al servidor cuántos pedazos tiene cada parte. Si falta alguno, responde 409 con la lista y no procesa.
- Mientras se graba, Screen Wake Lock mantiene la pantalla encendida. *Modo sala* pone la pantalla negra para usar en salas oscuras.

## Estructura del código

| Ruta | Qué es |
|---|---|
| `app/main.py` | API, login por usuario/contraseña y hosting de la PWA |
| `app/auth.py` | `Depends(auth)` compartido: resuelve el token de sesión a un `username` |
| `app/auth_api.py` | `POST /api/login`, `POST /api/logout` |
| `app/passwords.py` | hash/verificación de contraseñas (PBKDF2, sin dependencias nuevas) |
| `app/pipeline.py` | worker: ensamblar → transcribir → traducir → resumir; export a Markdown |
| `app/audio.py` | ffmpeg: une pedazos por parte, normaliza a 16 kHz mono, corta para el STT |
| `app/stt.py`, `app/llm.py` | proveedores intercambiables por variables de entorno |
| `app/trazas.py` | metadata de Langfuse de cada llamada por el gateway: una traza por grabación o por pedido, sesión, versión del prompt y de la app, tags `prod`/`dev`/`prueba`, entrevista enmascarada |
| `app/langfuse_scores.py` | scores automáticos sobre las trazas (`json_valido`, `lineas_faltantes`, `codigos_inventados`, `momentos_citados`), en segundo plano |
| `app/prompts.py` | glosario AWS, prompt de traducción, plantillas de resumen por tipo, prompt del itinerario |
| `app/catalog.py` | catálogo de re:Invent leído de Postgres (schema `reinvent`) a memoria al arrancar: facets y búsqueda, con speakers, empresa y sector |
| `app/search.py`, `app/embeddings.py` | búsqueda híbrida: embeddings multilingües locales (fastembed) + BM25, fusionados con RRF; vectores guardados en `speech_embedding`; prefiltro del itinerario |
| `app/fragmentos.py` | buscar en lo grabado: transcripciones en fragmentos de ~40 s con pgvector (coseno) + `tsvector`, fusionados con RRF; se indexa al terminar cada grabación |
| `scripts/evaluar_busqueda.py` | mide la búsqueda del catálogo contra `scripts/eval/busqueda_catalogo.json` (acierto, recall y MRR en los primeros 10) |
| `scripts/evaluar_modelos.py` | compara el modelo de cada tarea contra uno más barato, con los prompts de la app y un juez a ciegas (`--estimar` muestra el costo sin llamar a la API) |
| `app/ask.py` | chat de búsqueda (`POST /api/k/ask`): responde citando charlas por código |
| `app/briefing.py` | "Preparar conversación" (`POST /api/k/briefing`): ficha de un speaker o empresa cruzada con el perfil del usuario y sus grabaciones; caché por usuario en `briefings` |
| `app/nl_filters.py` | filtros en lenguaje natural (`POST /api/k/explore/parse`): el LLM propone, se valida contra los valores reales de cada faceta |
| `app/clusters.py` | temas emergentes: k-means sobre los embeddings, nombrados por el LLM; faceta `tema` del explorador, guardados en `speech_cluster` |
| `app/talks.py` | grabación ↔ charla del catálogo: elegirla al grabar (`GET /api/k/talks/pick`), contexto oficial para el resumen y nombres propios para la traducción |
| `app/sectors.py` | mapeo industria → sector (tabla `sector_industria` en el schema de la app; los valores iniciales no pisan ediciones) |
| `app/venues.py` | coordenadas de los hoteles/venues del Strip para el mapa |
| `app/itinerary.py` | motor de recomendación: prefiltro → LLM elige y justifica → resuelve choques de horario |
| `app/itinerary_api.py` | endpoints de catálogo e itinerario (`/api/catalog/*`, `/api/itinerary/*`, `/api/today`) |
| `app/today.py` | pantalla Hoy: charla actual y próxima del itinerario, en hora de Las Vegas |
| `app/knowledge.py`, `app/knowledge_api.py` | fichas de charla, speaker y empresa (`/api/k/*`) |
| `app/admin_api.py` | administración de usuarios y uso (`/api/admin/*`, solo `ADMIN_USERS`) |
| `app/passkey_api.py`, `app/passkeys_db.py` | ingreso con passkeys (WebAuthn) |
| `app/__init__.py` | `__version__`: la versión única de la app |
| `web/` | la PWA (sin build): grabador, cola offline en IndexedDB, service worker (`web/sw.js`) |
| `web/css/tokens.css` | tokens de diseño (colores, tipografía, espaciado) sobre Brick v2 |
| `web/js/app.js` | router, inicio y grabador |
| `web/js/today.js`, `web/js/search.js` | pantalla Hoy; Buscar con los modos Filtrar (`explore.js`) y Preguntar (`ask.js`) |
| `web/js/itinerary.js` | cuestionario de perfil y vista de itinerario por día |
| `web/js/knowledge.js`, `web/js/briefing.js` | fichas navegables y "Para conversar" |
| `web/js/ui.js`, `web/js/dialog.js` | componentes compartidos: botones, toasts con deshacer, diálogos |
| `web/js/map.js` | mapa interactivo de venues (Google Maps JavaScript API, carga diferida) |
| `tests/` | pytest con STT, LLM y embeddings falsos; un test por módulo |
