# Despliegue y operación

Cómo se instala ReinventAR en Railway, cómo se promueve de staging a producción, qué proveedores de STT, LLM y
embeddings se pueden configurar y cómo se administran los usuarios. Para levantar la app en una máquina local, ver
[README → Correr local](../README.md#correr-local).

## Railway

1. **Repo**: en Railway, *New Project → Deploy from GitHub repo*. Railway detecta el `Dockerfile` solo.
   Sin GitHub: desde la carpeta, `railway init` y después `railway up --detach`.
2. **Volume**: en el servicio, *Attach Volume* con mount path **`/data`**. Ahí quedan los audios; sin volumen, cada deploy los borra.
   **Postgres**: *New → Template → pgvector* (Postgres con la extensión `vector`). En la app, `DATABASE_URL=${{<servicio postgres>.DATABASE_URL}}` (red privada).
   Para conectarte desde afuera, activá *Settings → Networking → TCP Proxy* (puerto `5432`); la URL pública es `postgresql://<PGUSER>:<PGPASSWORD>@<RAILWAY_TCP_PROXY_DOMAIN>:<RAILWAY_TCP_PROXY_PORT>/<PGDATABASE>` (variables del servicio pgvector; el dominio HTTP no sirve para Postgres). Los colaboradores entran con el rol de solo lectura `colaborador`, que ve el schema `reinvent` y no el `app`.
   Cargá el catálogo desde una máquina local con `scripts/sync_to_railway.sh` (te pide los datos del TCP Proxy, o exportá `RAILWAY_DATABASE_URL`): sin flags corre en **modo prueba** (todo en una transacción con ROLLBACK, muestra la verificación) y con `--aplicar` hace backup de Railway y confirma. Repetilo cada vez que corrijas la base local (solo pisa el schema `reinvent`) y después reiniciá la app. Los eventos (`reinvent.evento`) no se pisan: los mantiene la app (ver *Eventos automáticos*); para reemplazarlos con los locales, `REEMPLAZAR_EVENTOS=1`.
   Si el volumen tenía el SQLite anterior (`/data/reinventar.db`), el primer arranque lo importa solo a Postgres y lo renombra a `reinventar.db.migrated`.
3. **Variables** (*Variables → Raw Editor*):
   ```
   BOOTSTRAP_USERS=<admin>:<contraseña>
   ADMIN_USERS=<admin>
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
6. **Celular**: abrí el dominio en Chrome, ingresá con tu usuario y contraseña → *Agregar a pantalla principal*. Cada usuario tiene su propio login e itinerario; las grabaciones se comparten dentro de la instalación.
7. **Catálogo del itinerario**: se lee del schema `reinvent` de Postgres al arrancar. Después de correr `scripts/sync_to_railway.sh`, el admin puede recargarlo sin reiniciar (`POST /api/admin/catalog/reload`, botón en Administración). Si el schema no está cargado, la grabación sigue funcionando igual; sólo fallan `/api/catalog` y `/api/itinerary` con un 503 claro.
8. **Eventos automáticos** (`app/eventos_auto.py`): con `EVENTOS_AUTO=1` (en producción; staging con su propia copia del catálogo, ver abajo), cada `EVENTOS_AUTO_HORAS` (3) la app revisa el calendario Luma de re:Invent, conferenceparties.com y los eventos cargados por link: suma nuevos, actualiza cambios, resume con el LLM hasta `EVENTOS_AUTO_TOPE` (50) por revisión y marca cancelados los que faltan dos revisiones seguidas. Necesita la migración `scripts/migraciones/007_eventos_automaticos.sql`. Staging usa su propia copia del catálogo para probarlo: `python -m scripts.preparar_catalogo_staging --aplicar` (copia `reinvent` a `reinvent_staging` y le corre las migraciones) y en `reinventar-staging` `CATALOGO_SCHEMA=reinvent_staging` y `EVENTOS_AUTO=1`. Estado, «Revisar ahora» y «Agregar evento por link» en Administración.
   Con `TICKETMASTER_API_KEY` (Discovery API de Ticketmaster), la misma revisión suma los shows de Las Vegas de la semana (`app/ticketmaster.py`, tabla `reinvent.show_funcion` de la migración `scripts/migraciones/009_shows.sql`) y aparece la pestaña **Shows** en Eventos. Sin la key, ni la pestaña ni los pedidos. La key va en la URL: nunca se loguea.
   Con `VIATOR_API_KEY` (Partner API de Viator, acceso Basic de afiliado) aparece la pestaña **Excursiones** en Actividades (`app/viator.py`). La búsqueda se cachea solo en memoria y por 1 h (lo que permiten los términos); nada va a la base. Sin la clave, ni la pestaña ni los pedidos. Va en el header `exp-api-key`: nunca se loguea.
   Los minutos caminando entre sedes (`reinvent.sede_tiempo`) se calculan una sola vez en local con `python -m scripts.calcular_tiempos_sedes` (Routes API, modo prueba; `--aplicar` para confirmar) y suben con el mismo sync. Si la tabla falta, la app los estima por línea recta.

9. **Búsqueda por significado**: al arrancar se baja el modelo de embeddings (~220 MB) a `/data/models` (una sola vez, queda en el volumen) y se calculan los vectores de las charlas en segundo plano (~30 s la primera vez; después solo las charlas nuevas o cambiadas). Mientras tanto la búsqueda y el itinerario funcionan solo por palabras. Suma ~400 MB de RAM.

## CI/CD con GitHub Actions y Claude Code

- **Flujo**: `feat/...` o `fix/...` → PR a `dev` → merge → `ci-promote.yml` corre los tests de núcleo y el servicio `reinventar-staging` de Railway (branch `dev`) deploya en `staging.reinventar.app`. **Producción se publica a mano**: Actions → *CI y publicación en producción* → *Run workflow* sobre `dev`; si los tests pasan, hace fast-forward de `main` a `dev` y Railway deploya producción con ese push a `main`. El servicio de producción tiene que seguir conectado al repo (*Settings → Source*, branch `main`), sin *Wait for CI*: el push que hace Actions no dispara otro workflow en `main`.
- **Staging**: mismo repo y misma base, pero `DB_SCHEMA=app_staging` (usuarios, grabaciones e itinerarios aparte; el catálogo `reinvent` es el mismo), `ENTORNO=staging` (tag propio en Langfuse) y `WEBAUTHN_RP_ID`/`WEBAUTHN_ORIGIN` de su dominio.
- **Si la promoción falla** porque `main` tiene commits que `dev` no tiene: `git checkout dev && git merge origin/main && git push`.
- **`claude.yml`**: mencioná `@claude` en un issue, un PR o una revisión y Claude Code responde, implementa o abre un PR contra `dev`. Solo responde a usuarios con permiso de escritura. Necesita la GitHub App de Claude y el secret `CLAUDE_CODE_OAUTH_TOKEN` (`claude setup-token`). Sigue las reglas de `CLAUDE.md`.

No hay `railway.toml` a propósito: Railway marcó Config as Code como deprecado y los archivos legacy dejan de funcionar el 1-dic-2026, en plena re:Invent. Configurá todo desde el dashboard.

## Proveedores

| Variable | Default | Alternativas |
|---|---|---|
| `STT_PROVIDER` | `openai` (endpoint compatible) | `litellm`: por el gateway, con `LLM_BASE_URL` y `LLM_API_KEY` y un alias por uso (`stt-charlas`, `stt-voz`); `local` (faster-whisper, instalalo y subí la RAM), `fake` |
| `STT_BASE_URL` | `https://api.groq.com/openai/v1` | `https://api.openai.com/v1` con `STT_MODEL=whisper-1` (no se usa con `STT_PROVIDER=litellm`) |
| `STT_MODEL` | `whisper-large-v3-turbo` | `whisper-large-v3` (más preciso, más lento) |
| `LLM_PROVIDER` | `anthropic` | `litellm` + `LLM_BASE_URL` + `LLM_API_KEY`: cada tarea va a su alias del gateway (ver *Gateway de LLM*); `openai` para otro endpoint compatible |
| `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` | — (sin claves no se mandan scores) | las claves del proyecto de Langfuse: para mandar los scores automáticos de calidad y para el tablero de LLM de Cuenta → Admin. Van en el servicio **de la app** en Railway (no solo en `litellm`) y las carga quien administra el entorno |
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

## Gateway de LLM (LiteLLM + Langfuse)

Cada parte de la app pide una **tarea** (`app/llm_router.py`: resumen, traducción, entrevista, razones, chat, filtros…) y el gateway decide el modelo: `infra/litellm/config.yaml` tiene un alias `rx-<tarea>` por tarea, y uno `stt-<uso>` por uso del STT (`stt-charlas` y `stt-voz`: Whisper large-v3 completo, con un vocabulario por uso en `app/stt.py`). Cambiar el modelo de una parte es editar ese alias y reiniciar el servicio `litellm`, sin deployar la app. Cada llamada va con la tarea como tag y el usuario, así el gasto de cada parte se ve en el panel de LiteLLM y las trazas en Langfuse.

1. **Base**: en el Postgres de Railway, `CREATE DATABASE litellm;` (aparte de la de la app; ahí guarda el gasto por tag, las claves virtuales y el panel).
2. **Servicio** `litellm`: *New → GitHub repo* (este), *Settings → Root Directory* = `infra/litellm` (usa su `Dockerfile`). *Networking*: dominio público con puerto `4000` (el panel queda en `/ui`).
3. **Variables del servicio** (las keys van solo acá): `LITELLM_MASTER_KEY` (empieza con `sk-`), `ANTHROPIC_API_KEY`, `DATABASE_URL=postgresql://${{pgvector.PGUSER}}:${{pgvector.PGPASSWORD}}@${{pgvector.RAILWAY_PRIVATE_DOMAIN}}:5432/litellm` (variables de referencia de Railway: la base `litellm` por la red privada, sin copiar la clave; el `PGHOST` de pgvector es el proxy público), `GROQ_API_KEY` (STT), `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_HOST=https://us.cloud.langfuse.com` (plan Hobby gratis de Langfuse Cloud).
4. **Claves virtuales**: en el panel, una para la app y otra para los scripts locales (nunca la master).
5. **App**: `LLM_PROVIDER=litellm`, `LLM_BASE_URL=http://litellm.railway.internal:4000` (red privada), `LLM_API_KEY=<clave virtual de la app>`. Admin › Chequeo funcional confirma que el gateway responde.
6. **Scripts locales**: en el `.env` local, `LLM_PROVIDER=litellm`, `LLM_BASE_URL=https://<dominio público del gateway>` y `LLM_API_KEY=<clave virtual de scripts>`.
7. **STT por el gateway**: con `GROQ_API_KEY` en el servicio `litellm`, en la app `STT_PROVIDER=litellm` (usa el mismo `LLM_BASE_URL` y `LLM_API_KEY`). Las grabaciones quedan a nombre de quien grabó.
8. **Volver atrás**: `LLM_PROVIDER=anthropic` y `STT_PROVIDER=openai` en la app: vuelve a llamar directo con los `*_MODEL` y `STT_*` de siempre.

## Usuarios

- **Alta**: un admin entra a *Ajustes → Administración* (`#/admin`) y crea el usuario con una contraseña temporal (mínimo 8 caracteres). Al primer ingreso la app obliga a cambiarla.
- Desde la misma pantalla se resetean contraseñas, se activan o desactivan usuarios y se cierran sus sesiones.
- **Admins**: los usuarios listados en `ADMIN_USERS` (separados por coma). Se cambia en las variables de Railway; no hay botón en la app.
- **Un admin que se olvidó la contraseña** y no tiene passkey ni otro admin que se la resetee (`BOOTSTRAP_USERS` no pisa usuarios existentes): `python -m scripts.resetear_password --schema <DB_SCHEMA> --usuario <usuario>` desde una máquina local, con `RAILWAY_DATABASE_URL` exportada. Pide la contraseña nueva sin mostrarla, cierra las sesiones y conserva las passkeys. Sin `--aplicar` corre en modo prueba; antes de `--aplicar`, backup. El schema es el `DB_SCHEMA` del servicio: staging y producción usan schemas distintos.
