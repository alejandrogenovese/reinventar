# ReinventAR

[![CI](https://github.com/alejandrogenovese/reinventar/actions/workflows/ci-promote.yml/badge.svg?branch=dev)](https://github.com/alejandrogenovese/reinventar/actions/workflows/ci-promote.yml)
[![Quality Gate](https://sonarcloud.io/api/project_badges/measure?project=alejandrogenovese_reinventar&metric=alert_status)](https://sonarcloud.io/summary/new_code?id=alejandrogenovese_reinventar)
[![Licencia: MIT](https://img.shields.io/badge/licencia-MIT-blue.svg)](LICENSE)

PWA para aprovechar AWS re:Invent desde el celular. Tiene tres enfoques:

1. **Grabar charlas**: graba con el micrófono (pensado para el DJI Mic Mini 2) y, al terminar, el backend transcribe, traduce al castellano y resume según el tipo de sesión.
2. **Encontrar sesiones**: búsqueda híbrida y chat con RAG sobre el catálogo en Postgres, más un itinerario recomendado según el perfil de cada persona.
3. **Preparar conversaciones**: fichas navegables de charla → speaker → empresa y un briefing para llegar con contexto a cada charla.

Versión actual: ver [`CHANGELOG.md`](CHANGELOG.md). Producción: Railway, se despliega solo con cada push a `main`. Se trabaja en `dev`: cuando pasa los tests en GitHub Actions, `main` se adelanta a `dev` solo.

```
PWA (Chrome Android / Safari iOS) ──pedazos webm/opus de 10 s──▶ FastAPI en Railway ──▶ Volume /data
                                                                 │ al terminar:
                                                                 ├─ ffmpeg (une las partes, corta en pedazos de 10 min)
                                                                 ├─ STT  (Groq Whisper / OpenAI / LiteLLM / faster-whisper)
                                                                 ├─ traducción EN→ES (Claude Sonnet)
                                                                 └─ resumen según el tipo de sesión (Claude Opus)
                                                       Postgres + pgvector: estado de la app y catálogo de re:Invent
```

**Contenido:** [Estructura](#estructura) · [Correr local](#correr-local) · [Deploy en Railway](#deploy-en-railway) ·
[Usuarios](#usuarios) · [Cómo se comporta la grabación](#cómo-se-comporta-la-grabación) ·
[Cómo trabajar en el repo](#cómo-trabajar-en-el-repo) · [Licencia](#licencia)

**Documentación:** [Arquitectura](docs/arquitectura.md) · [Cómo contribuir](CONTRIBUTING.md) ·
[Seguridad](SECURITY.md) · [Código de conducta](CODE_OF_CONDUCT.md) · [CHANGELOG](CHANGELOG.md)

## Estructura

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

## Correr local

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.lock
# Postgres local: el docker reinvent-pg (imagen pgvector/pgvector:pg16, puerto 5433) con el schema reinvent cargado.
pytest -q                                  # no consume APIs; usa un schema app_test_* que se borra al final
DATABASE_URL=postgresql://reinvent:reinvent2026@localhost:5433/reinvent DB_SCHEMA=app_dev \
  DATA_DIR=./data BOOTSTRAP_USERS=dev:devpass123 ADMIN_USERS=dev \
  STT_PROVIDER=fake LLM_PROVIDER=fake EMBED_PROVIDER=off uvicorn app.main:app --reload
# http://localhost:8000 → usuario "dev", contraseña "devpass123"
```

Los tests que usan el catálogo de re:Invent (charlas reales como ARC407) necesitan el schema `reinvent` cargado en el Postgres local, por eso corren solo local. En CI (`.github/workflows/ci-promote.yml`) corren los tests de núcleo (auth, API, base, LLM, passkeys, versión) contra un Postgres vacío.

Con micrófono simulado en Chrome: `--use-fake-device-for-media-stream --use-fake-ui-for-media-stream`.

## Deploy en Railway

1. **Repo**: en Railway, *New Project → Deploy from GitHub repo*. Railway detecta el `Dockerfile` solo.
   Sin GitHub: desde la carpeta, `railway init` y después `railway up --detach`.
2. **Volume**: en el servicio, *Attach Volume* con mount path **`/data`**. Ahí quedan los audios; sin volumen, cada deploy los borra.
   **Postgres**: *New → Template → pgvector* (Postgres con la extensión `vector`). En la app, `DATABASE_URL=${{<servicio postgres>.DATABASE_URL}}` (red privada).
   Para conectarte desde afuera, activá *Settings → Networking → TCP Proxy* (puerto `5432`); la URL pública es `postgresql://<PGUSER>:<PGPASSWORD>@<RAILWAY_TCP_PROXY_DOMAIN>:<RAILWAY_TCP_PROXY_PORT>/<PGDATABASE>` (variables del servicio pgvector; el dominio HTTP no sirve para Postgres). Los colaboradores entran con el rol de solo lectura `colaborador`, que ve el schema `reinvent` y no el `app`.
   Cargá el catálogo desde la Mac con `scripts/sync_to_railway.sh` (te pide los datos del TCP Proxy, o exportá `RAILWAY_DATABASE_URL`): sin flags corre en **modo prueba** (todo en una transacción con ROLLBACK, muestra la verificación) y con `--aplicar` hace backup de Railway y confirma. Repetilo cada vez que corrijas la base local (solo pisa el schema `reinvent`) y después reiniciá la app.
   Si el volumen tenía el SQLite anterior (`/data/reinventar.db`), el primer arranque lo importa solo a Postgres y lo renombra a `reinventar.db.migrated`.
3. **Variables** (*Variables → Raw Editor*):
   ```
   BOOTSTRAP_USERS=ale:<contraseña>
   ADMIN_USERS=ale
   STT_API_KEY=<API key de Groq>
   ANTHROPIC_API_KEY=<API key de Claude>
   GOOGLE_MAPS_API_KEY=<API key de Google Maps>
   ```
   `BOOTSTRAP_USERS` crea al arrancar los usuarios que todavía no existen (no pisa contraseñas); usalo solo para el primer admin. El resto de los usuarios se da de alta desde la app (ver [Usuarios](#usuarios)). Las demás variables tienen defaults (ver `.env.example`).

   Para `GOOGLE_MAPS_API_KEY`: en [Google Cloud Console](https://console.cloud.google.com/google/maps-apis) activá la *Maps JavaScript API*, creá una API key y restringila por *HTTP referrer* a tu dominio de Railway (p. ej. `https://tu-dominio.up.railway.app/*`) para que nadie más la pueda usar aunque la vea en el código del navegador. Sin esta variable el itinerario funciona igual, pero sin mapa.

   **Key aparte para el servidor (`GOOGLE_PLACES_SERVER_KEY`):** el autocompletado de lugares (Places API New) corre en el servidor. Creá una segunda API key **restringida solo a Places API (New)**, sin restricción por sitio, y cargala en esa variable. La de `GOOGLE_MAPS_API_KEY` se ve en el navegador: si también tuviera Places habilitado, cualquiera que la viera podría usar Places a tu costo. Mientras no exista la key del servidor, la app sigue usando la del navegador (como antes).

   Opcionales, para el tablero de LLM de Cuenta → Admin: `LANGFUSE_PUBLIC_KEY` y `LANGFUSE_SECRET_KEY` (las del proyecto de Langfuse) y `LANGFUSE_HOST` (por defecto `https://us.cloud.langfuse.com`). El servidor lee las métricas con esas claves y al navegador solo llegan los números. Sin ellas, el tablero dice que no está disponible y el resto anda igual.
4. **Healthcheck**: *Settings → Deploy → Healthcheck Path* = `/health`.
5. **Dominio**: *Settings → Networking → Generate Domain* (o `railway domain`). Hace falta HTTPS para que el celular habilite el micrófono y el service worker.
6. **Celular**: abrí el dominio en Chrome, ingresá con tu usuario y contraseña → *Agregar a pantalla principal*. Cada persona (Mariana, Marcos, Ale) tiene su propio login y su propio itinerario; las grabaciones de audio se comparten entre todos.
7. **Catálogo del itinerario**: se lee del schema `reinvent` de Postgres al arrancar. Después de correr `scripts/sync_to_railway.sh`, el admin puede recargarlo sin reiniciar (`POST /api/admin/catalog/reload`, botón en Administración). Si el schema no está cargado, la grabación sigue funcionando igual; sólo fallan `/api/catalog` y `/api/itinerary` con un 503 claro.
   Los minutos caminando entre sedes (`reinvent.sede_tiempo`) se calculan una sola vez en local con `python -m scripts.calcular_tiempos_sedes` (Routes API, modo prueba; `--aplicar` para confirmar) y suben con el mismo sync. Si la tabla falta, la app los estima por línea recta.

8. **Búsqueda por significado**: al arrancar se baja el modelo de embeddings (~220 MB) a `/data/models` (una sola vez, queda en el volumen) y se calculan los vectores de las charlas en segundo plano (~30 s la primera vez; después solo las charlas nuevas o cambiadas). Mientras tanto la búsqueda y el itinerario funcionan solo por palabras. Suma ~400 MB de RAM.

### CI/CD con GitHub Actions y Claude Code

- **Flujo**: `feat/...` o `fix/...` → PR a `dev` → merge → `ci-promote.yml` corre los tests de núcleo y el servicio `reinventar-staging` de Railway (branch `dev`) deploya en `staging.reinventar.app`. **Producción se publica a mano**: Actions → *CI y publicación en producción* → *Run workflow* sobre `dev`; si los tests pasan, hace fast-forward de `main` a `dev` y Railway deploya producción con ese push a `main`. El servicio de producción tiene que seguir conectado al repo (*Settings → Source*, branch `main`), sin *Wait for CI*: el push que hace Actions no dispara otro workflow en `main`.
- **Staging**: mismo repo y misma base, pero `DB_SCHEMA=app_staging` (usuarios, grabaciones e itinerarios aparte; el catálogo `reinvent` es el mismo), `ENTORNO=staging` (tag propio en Langfuse) y `WEBAUTHN_RP_ID`/`WEBAUTHN_ORIGIN` de su dominio.
- **Si la promoción falla** porque `main` tiene commits que `dev` no tiene: `git checkout dev && git merge origin/main && git push`.
- **`claude.yml`**: mencioná `@claude` en un issue, un PR o una revisión y Claude Code responde, implementa o abre un PR contra `dev`. Solo responde a usuarios con permiso de escritura. Necesita la GitHub App de Claude y el secret `CLAUDE_CODE_OAUTH_TOKEN` (`claude setup-token`). Sigue las reglas de `CLAUDE.md`.

No hay `railway.toml` a propósito: Railway marcó Config as Code como deprecado y los archivos legacy dejan de funcionar el 1-dic-2026, en plena re:Invent. Configurá todo desde el dashboard.

### Proveedores

| Variable | Default | Alternativas |
|---|---|---|
| `STT_PROVIDER` | `openai` (endpoint compatible) | `litellm`: por el gateway, con `LLM_BASE_URL` y `LLM_API_KEY` y un alias por uso (`stt-charlas`, `stt-voz`); `local` (faster-whisper, instalalo y subí la RAM), `fake` |
| `STT_BASE_URL` | `https://api.groq.com/openai/v1` | `https://api.openai.com/v1` con `STT_MODEL=whisper-1` (no se usa con `STT_PROVIDER=litellm`) |
| `STT_MODEL` | `whisper-large-v3-turbo` | `whisper-large-v3` (más preciso, más lento) |
| `LLM_PROVIDER` | `anthropic` | `litellm` + `LLM_BASE_URL` + `LLM_API_KEY`: cada tarea va a su alias del gateway (ver *Gateway de LLM*); `openai` para otro endpoint compatible |
| `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` | — (sin claves no se mandan scores) | las claves del proyecto de Langfuse: para mandar los scores automáticos de calidad y para el tablero de LLM de Cuenta → Admin. Van en el servicio **de la app** en Railway (no solo en `litellm`) y las cargás vos |
| `LANGFUSE_HOST` | `https://us.cloud.langfuse.com` | el host de tu proyecto de Langfuse (en el servicio de la app, junto a las claves) |
| `RAILWAY_ENVIRONMENT_NAME` | la pone Railway | con `production`, las trazas llevan el tag `prod`; si no, `dev` |
| `LLM_RUTA_<TAREA>` | — | fuerza el modelo de una tarea (ej. `LLM_RUTA_RAZONES=rx-razones-haiku`); tareas en `app/llm_router.py` |
| `TRANSLATE_MODEL` | `claude-sonnet-5-5` | `claude-haiku-5-5` para abaratar |
| `SUMMARY_MODEL` | `claude-opus-5-5` | `claude-sonnet-5-5` |
| `BRIEFING_MODEL` | `claude-sonnet-5-5` | modelo de la ficha para conversar |
| `ASK_MODEL` | `claude-sonnet-5-5` | `claude-haiku-5-5` para abaratar el chat de búsqueda |
| `EMBED_PROVIDER` | `local` (modelo dentro del contenedor, sin API key) | `off` (solo búsqueda por palabras), `fake` |
| `EMBED_MODEL` | `google/embeddinggemma-300m-q4` (versión de 4 bits: ~0,4 GB de RAM) | `google/embeddinggemma-300m` (el original: casi igual, el triple de RAM) u otro modelo de fastembed (se recalculan todos los vectores; los prefijos de consulta y documento van en `PREFIJOS` de `app/embeddings.py`). Volver a `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` es instantáneo: sus vectores quedan guardados |
| `CSP_MODO` | `enforce` | `report` (la política de seguridad de contenido solo avisa, no bloquea: para destrabar sin deploy si algo de Google Maps se rompe), `off` |
| `EMBED_THREADS` / `EMBED_BATCH` | `2` / `8` | más hilos o lotes más grandes: algo más rápido el primer cálculo, bastante más RAM |

### Gateway de LLM (LiteLLM + Langfuse)

Cada parte de la app pide una **tarea** (`app/llm_router.py`: resumen, traducción, entrevista, razones, chat, filtros…) y el gateway decide el modelo: `infra/litellm/config.yaml` tiene un alias `rx-<tarea>` por tarea, y uno `stt-<uso>` por uso del STT (`stt-charlas` y `stt-voz`: Whisper large-v3 completo, con un vocabulario por uso en `app/stt.py`). Cambiar el modelo de una parte es editar ese alias y reiniciar el servicio `litellm`, sin deployar la app. Cada llamada va con la tarea como tag y el usuario, así el gasto de cada parte se ve en el panel de LiteLLM y las trazas en Langfuse.

1. **Base**: en el Postgres de Railway, `CREATE DATABASE litellm;` (aparte de la de la app; ahí guarda el gasto por tag, las claves virtuales y el panel).
2. **Servicio** `litellm`: *New → GitHub repo* (este), *Settings → Root Directory* = `infra/litellm` (usa su `Dockerfile`). *Networking*: dominio público con puerto `4000` (el panel queda en `/ui`).
3. **Variables del servicio** (las keys van solo acá): `LITELLM_MASTER_KEY` (empieza con `sk-`), `ANTHROPIC_API_KEY`, `DATABASE_URL=postgresql://${{pgvector.PGUSER}}:${{pgvector.PGPASSWORD}}@${{pgvector.RAILWAY_PRIVATE_DOMAIN}}:5432/litellm` (variables de referencia de Railway: la base `litellm` por la red privada, sin copiar la clave; el `PGHOST` de pgvector es el proxy público), `GROQ_API_KEY` (STT), `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_HOST=https://us.cloud.langfuse.com` (plan Hobby gratis de Langfuse Cloud).
4. **Claves virtuales**: en el panel, una para la app y otra para los scripts de la Mac (nunca la master).
5. **App**: `LLM_PROVIDER=litellm`, `LLM_BASE_URL=http://litellm.railway.internal:4000` (red privada), `LLM_API_KEY=<clave virtual de la app>`. Admin › Chequeo funcional confirma que el gateway responde.
6. **Scripts locales**: en el `.env` de la Mac, `LLM_PROVIDER=litellm`, `LLM_BASE_URL=https://<dominio público del gateway>` y `LLM_API_KEY=<clave virtual de scripts>`.
7. **STT por el gateway**: con `GROQ_API_KEY` en el servicio `litellm`, en la app `STT_PROVIDER=litellm` (usa el mismo `LLM_BASE_URL` y `LLM_API_KEY`). Las grabaciones quedan a nombre de quien grabó.
8. **Volver atrás**: `LLM_PROVIDER=anthropic` y `STT_PROVIDER=openai` en la app: vuelve a llamar directo con los `*_MODEL` y `STT_*` de siempre.

## Usuarios

- **Alta**: un admin entra a *Ajustes → Administración* (`#/admin`) y crea el usuario con una contraseña temporal (mínimo 8 caracteres). Al primer ingreso la app obliga a cambiarla.
- Desde la misma pantalla se resetean contraseñas, se activan o desactivan usuarios y se cierran sus sesiones.
- **Admins**: los usuarios listados en `ADMIN_USERS` (separados por coma). Se cambia en las variables de Railway; no hay botón en la app.

## Cómo se comporta la grabación

- MediaRecorder en `audio/webm;codecs=opus` a 32 kbps mono: una hora ≈ 14 MB. Se desactivan el echo cancellation, el noise suppression y el AGC del navegador.
- Cada pedazo se guarda primero en IndexedDB y se borra recién cuando el servidor confirma. Sin señal se acumulan y suben solos al volver la red.
- Si la página se recarga a mitad de la grabación, al volver a grabar arranca una **parte** nueva. El backend decodifica cada parte por separado y después las une.
- *Terminar y procesar* espera a que no quede nada por subir y le pasa al servidor cuántos pedazos tiene cada parte. Si falta alguno, responde 409 con la lista y no procesa.
- Mientras se graba, Screen Wake Lock mantiene la pantalla encendida. *Modo sala* pone la pantalla negra para usar en salas oscuras.

## Pruebas pendientes en el S24 Ultra (antes de viajar)

1. Que el receptor USB-C del DJI aparezca en el selector y la PWA lo elija sola.
2. 60 min con *Modo sala*: confirmar que no se corta. Probar también con la pantalla bloqueada (no está garantizado en Chrome Android).
3. Activar el modo avión a mitad de la sesión y desactivarlo: la cola tiene que vaciarse sola.
4. Cuánto tarda y cuánto cuesta procesar una keynote de 2 h.

## Cómo trabajar en el repo

Las reglas (ramas, commits, tests, lint, dependencias con locks y hashes, cómo publicar una versión) están en
[CONTRIBUTING.md](CONTRIBUTING.md). Lo esencial: se trabaja en ramas desde `dev` con PR contra `dev` (nunca contra
`main`), commits con Conventional Commits en castellano, cada funcionalidad nueva con su test y nada de secretos en el
repo. Para reportar una vulnerabilidad, [SECURITY.md](SECURITY.md).

## Licencia

[MIT](LICENSE) © 2026 Alejandro Genovese.
