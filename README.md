# ReinventAR

PWA para grabar charlas de re:Invent con el DJI Mic Mini 2 en el celular. Cuando la sesión termina, el backend la transcribe, la traduce al castellano y la resume.

```
PWA (Chrome Android) ──pedazos webm/opus de 10 s──▶ FastAPI en Railway ──▶ Volume /data
                                                     │ al terminar:
                                                     ├─ ffmpeg (une las partes, corta en pedazos de 10 min)
                                                     ├─ STT  (Groq Whisper / OpenAI / LiteLLM / faster-whisper)
                                                     ├─ traducción EN→ES (Claude Sonnet)
                                                     └─ resumen según el tipo de sesión (Claude Opus)
```

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
| `app/prompts.py` | glosario AWS, prompt de traducción, plantillas de resumen por tipo, prompt del itinerario |
| `app/catalog.py` | catálogo de re:Invent leído de Postgres (schema `reinvent`) a memoria al arrancar: facets y búsqueda, con speakers, empresa y sector |
| `app/search.py`, `app/embeddings.py` | búsqueda híbrida: embeddings multilingües locales (fastembed) + BM25, fusionados con RRF; vectores guardados en `speech_embedding`; prefiltro del itinerario |
| `app/ask.py` | chat de búsqueda (`POST /api/k/ask`): responde citando charlas por código |
| `app/talks.py` | grabación ↔ charla del catálogo: elegirla al grabar (`GET /api/k/talks/pick`), contexto oficial para el resumen y nombres propios para la traducción |
| `app/sectors.py` | mapeo industria → sector (tabla `sector_industria` en el schema de la app; los valores iniciales no pisan ediciones) |
| `app/venues.py` | coordenadas de los hoteles/venues del Strip para el mapa |
| `app/itinerary.py` | motor de recomendación: prefiltro → LLM elige y justifica → resuelve choques de horario |
| `app/itinerary_api.py` | endpoints de catálogo e itinerario (`/api/catalog/*`, `/api/itinerary/*`) |
| `web/` | la PWA (sin build): grabador, cola offline en IndexedDB, service worker |
| `web/js/itinerary.js` | cuestionario de perfil, vista de itinerario por día, exploración manual del catálogo |
| `web/js/map.js` | mapa interactivo de venues (Google Maps JavaScript API, carga diferida) |
| `tests/test_api.py` | flujo completo de grabación con STT y LLM falsos |
| `tests/test_itinerary.py` | catálogo, generación de itinerario y resolución de choques de horario, con LLM falso |

## Correr local

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt pytest
# Postgres local: el docker reinvent-pg (imagen pgvector/pgvector:pg16, puerto 5433) con el schema reinvent cargado.
pytest -q                                  # no consume APIs; usa un schema app_test_* que se borra al final
DATABASE_URL=postgresql://reinvent:reinvent2026@localhost:5433/reinvent \
  DATA_DIR=./data BOOTSTRAP_USERS=dev:dev STT_PROVIDER=fake LLM_PROVIDER=fake uvicorn app.main:app --reload
# http://localhost:8000 → usuario "dev", contraseña "dev"
```

Con micrófono simulado en Chrome: `--use-fake-device-for-media-stream --use-fake-ui-for-media-stream`.

## Deploy en Railway

1. **Repo**: subilo a un repo privado de GitHub. En Railway, *New Project → Deploy from GitHub repo*. Railway detecta el `Dockerfile` solo.
   Sin GitHub: desde la carpeta, `railway init` y después `railway up --detach`.
2. **Volume**: en el servicio, *Attach Volume* con mount path **`/data`**. Ahí quedan los audios; sin volumen, cada deploy los borra.
   **Postgres**: *New → Template → pgvector* (Postgres con la extensión `vector`). En la app, `DATABASE_URL=${{<servicio postgres>.DATABASE_URL}}` (red privada).
   Cargá el catálogo desde la Mac con `RAILWAY_DATABASE_URL='<DATABASE_PUBLIC_URL>' scripts/sync_to_railway.sh`; repetilo cada vez que corrijas la base local (solo pisa el schema `reinvent`).
   Si el volumen tenía el SQLite anterior (`/data/reinventar.db`), el primer arranque lo importa solo a Postgres y lo renombra a `reinventar.db.migrated`.
3. **Variables** (*Variables → Raw Editor*):
   ```
   BOOTSTRAP_USERS=ale:<contraseña>,mariana:<contraseña>,marcos:<contraseña>
   STT_API_KEY=<API key de Groq>
   ANTHROPIC_API_KEY=<API key de Claude>
   GOOGLE_MAPS_API_KEY=<API key de Google Maps>
   ```
   Cada usuario de la lista se crea al arrancar si todavía no existe (no pisa contraseñas de usuarios ya creados). Para sumar a alguien después, agregalo a la variable y redeployá. El resto tiene defaults (ver `.env.example`).

   Para `GOOGLE_MAPS_API_KEY`: en [Google Cloud Console](https://console.cloud.google.com/google/maps-apis) activá la *Maps JavaScript API*, creá una API key y restringila por *HTTP referrer* a tu dominio de Railway (p. ej. `https://tu-dominio.up.railway.app/*`) para que nadie más la pueda usar aunque la vea en el código del navegador. Sin esta variable el itinerario funciona igual, pero sin mapa.
4. **Healthcheck**: *Settings → Deploy → Healthcheck Path* = `/health`.
5. **Dominio**: *Settings → Networking → Generate Domain* (o `railway domain`). Hace falta HTTPS para que el celular habilite el micrófono y el service worker.
6. **Celular**: abrí el dominio en Chrome, ingresá con tu usuario y contraseña → *Agregar a pantalla principal*. Cada persona (Mariana, Marcos, Ale) tiene su propio login y su propio itinerario; las grabaciones de audio se comparten entre todos.
7. **Catálogo del itinerario**: se lee del schema `reinvent` de Postgres al arrancar. Después de correr `scripts/sync_to_railway.sh`, el admin puede recargarlo sin reiniciar (`POST /api/admin/catalog/reload`, botón en Administración). Si el schema no está cargado, la grabación sigue funcionando igual; sólo fallan `/api/catalog` y `/api/itinerary` con un 503 claro.

8. **Búsqueda por significado**: al arrancar se baja el modelo de embeddings (~220 MB) a `/data/models` (una sola vez, queda en el volumen) y se calculan los vectores de las charlas en segundo plano (~30 s la primera vez; después solo las charlas nuevas o cambiadas). Mientras tanto la búsqueda y el itinerario funcionan solo por palabras. Suma ~400 MB de RAM.

No hay `railway.toml` a propósito: Railway marcó Config as Code como deprecado y los archivos legacy dejan de funcionar el 1-dic-2026, en plena re:Invent. Configurá todo desde el dashboard.

### Proveedores

| Variable | Default | Alternativas |
|---|---|---|
| `STT_PROVIDER` | `openai` (endpoint compatible) | `local` (faster-whisper, instalalo y subí la RAM), `fake` |
| `STT_BASE_URL` | `https://api.groq.com/openai/v1` | `https://api.openai.com/v1` con `STT_MODEL=whisper-1`; tu LiteLLM |
| `STT_MODEL` | `whisper-large-v3-turbo` | `whisper-large-v3` (más preciso, más lento) |
| `LLM_PROVIDER` | `anthropic` | `openai` + `LLM_BASE_URL` para pasar por LiteLLM |
| `TRANSLATE_MODEL` | `claude-sonnet-5-5` | `claude-haiku-5-5` para abaratar |
| `SUMMARY_MODEL` | `claude-opus-5-5` | `claude-sonnet-5-5` |
| `ASK_MODEL` | `claude-sonnet-5-5` | `claude-haiku-5-5` para abaratar el chat de búsqueda |
| `EMBED_PROVIDER` | `local` (modelo dentro del contenedor, sin API key) | `off` (solo búsqueda por palabras), `fake` |
| `EMBED_MODEL` | `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` | otro modelo de fastembed (se recalculan todos los vectores) |

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
