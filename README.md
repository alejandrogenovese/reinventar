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
| `app/main.py` | API, autenticación por token y hosting de la PWA |
| `app/auth.py` | `Depends(auth)` compartido por todas las rutas |
| `app/pipeline.py` | worker: ensamblar → transcribir → traducir → resumir; export a Markdown |
| `app/audio.py` | ffmpeg: une pedazos por parte, normaliza a 16 kHz mono, corta para el STT |
| `app/stt.py`, `app/llm.py` | proveedores intercambiables por variables de entorno |
| `app/prompts.py` | glosario AWS, prompt de traducción, plantillas de resumen por tipo, prompt del itinerario |
| `app/catalog.py` | catálogo de re:Invent (`data/*.json`) en memoria: facets, búsqueda y prefiltro por perfil/prompt |
| `app/venues.py` | coordenadas de los hoteles/venues del Strip para el mapa |
| `app/itinerary.py` | motor de recomendación: prefiltro → LLM elige y justifica → resuelve choques de horario |
| `app/itinerary_api.py` | endpoints de catálogo e itinerario (`/api/catalog/*`, `/api/itinerary/*`) |
| `web/` | la PWA (sin build): grabador, cola offline en IndexedDB, service worker |
| `web/js/itinerary.js` | cuestionario de perfil, vista de itinerario por día, exploración manual del catálogo |
| `web/js/map.js` | mapa interactivo de venues (Leaflet + OpenStreetMap, carga diferida) |
| `tests/test_api.py` | flujo completo de grabación con STT y LLM falsos |
| `tests/test_itinerary.py` | catálogo, generación de itinerario y resolución de choques de horario, con LLM falso |

## Correr local

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt pytest
pytest -q                                  # no consume APIs
DATA_DIR=./data APP_TOKEN=dev STT_PROVIDER=fake LLM_PROVIDER=fake uvicorn app.main:app --reload
# http://localhost:8000 → Ajustes → token "dev"
```

Con micrófono simulado en Chrome: `--use-fake-device-for-media-stream --use-fake-ui-for-media-stream`.

## Deploy en Railway

1. **Repo**: subilo a un repo privado de GitHub. En Railway, *New Project → Deploy from GitHub repo*. Railway detecta el `Dockerfile` solo.
   Sin GitHub: desde la carpeta, `railway init` y después `railway up --detach`.
2. **Volume**: en el servicio, *Attach Volume* con mount path **`/data`**. Sin volumen, cada deploy borra el audio y la base.
3. **Variables** (*Variables → Raw Editor*):
   ```
   APP_TOKEN=<openssl rand -hex 32>
   STT_API_KEY=<API key de Groq>
   ANTHROPIC_API_KEY=<API key de Claude>
   ```
   El resto tiene defaults (ver `.env.example`).
4. **Healthcheck**: *Settings → Deploy → Healthcheck Path* = `/health`.
5. **Dominio**: *Settings → Networking → Generate Domain* (o `railway domain`). Hace falta HTTPS para que el celular habilite el micrófono y el service worker.
6. **Celular**: abrí el dominio en Chrome → Ajustes → pegá el token → *Agregar a pantalla principal*.
   Para que no haga falta pegarlo a mano en cada celular (Mariana, Marcos, Ale, etc.): mandale a cada uno por WhatsApp `https://tu-dominio/?token=<el mismo APP_TOKEN>`. Al abrirlo una vez, la PWA guarda el token en ese celular y no lo vuelve a pedir — después pueden hacer *Agregar a pantalla principal* igual. Cualquiera con ese link tiene acceso completo (graba, consume tu cuota de Anthropic/Groq), así que mandalo sólo por un canal privado, no lo publiques.
7. **Catálogo del itinerario**: `data/reinvent2026-catalogo.json` viaja commiteado en el repo y horneado en la imagen (`COPY data ./data` en el Dockerfile), así que no requiere ningún paso manual — cada deploy lo incluye solo. Si en algún momento falta (por ejemplo corriendo una imagen vieja), la grabación sigue funcionando igual; sólo fallan `/api/catalog` y `/api/itinerary` con un 503 claro.

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
