# ReinventAR

[![CI](https://github.com/alejandrogenovese/reinventar/actions/workflows/ci-promote.yml/badge.svg?branch=dev)](https://github.com/alejandrogenovese/reinventar/actions/workflows/ci-promote.yml)
[![Quality Gate](https://sonarcloud.io/api/project_badges/measure?project=alejandrogenovese_reinventar&metric=alert_status)](https://sonarcloud.io/summary/new_code?id=alejandrogenovese_reinventar)
[![Licencia: MIT](https://img.shields.io/badge/licencia-MIT-blue.svg)](LICENSE)

Aplicación web progresiva (PWA) para equipos que asisten a AWS re:Invent. Centraliza la agenda, la grabación de
charlas y la preparación de reuniones en el celular, y funciona sin señal en los salones.

## Funcionalidades

| Área | Qué resuelve |
|---|---|
| **Grabación y resúmenes** | Graba las charlas con el micrófono del celular o uno externo. Al terminar, transcribe, traduce al castellano y genera un resumen según el tipo de sesión, con los puntos aplicables a la organización. |
| **Catálogo y agenda** | Búsqueda por filtros, por código de charla o en lenguaje natural sobre el catálogo oficial, e itinerario recomendado según el perfil de cada persona, con tiempos de traslado entre sedes. |
| **Preparación de reuniones** | Fichas de charlas, speakers y empresas, y un resumen previo para llegar con contexto a cada conversación. |
| **Eventos** | Eventos de networking y shows de la semana, actualizados automáticamente, con avisos de cambios y cancelaciones. |
| **Uso sin señal** | La grabación, el itinerario y la pantalla de inicio funcionan sin conexión; el audio se guarda en el dispositivo y se sube solo cuando vuelve la red. |

## Arquitectura

```
PWA (Chrome Android / Safari iOS) ──audio en pedazos de 10 s──▶ FastAPI ──▶ almacenamiento de audio
                                                                 │ al terminar:
                                                                 ├─ ffmpeg (une y normaliza el audio)
                                                                 ├─ transcripción (STT)
                                                                 ├─ traducción EN→ES (LLM)
                                                                 └─ resumen por tipo de sesión (LLM)
                                              Postgres + pgvector: estado de la app y catálogo
```

- **Frontend:** PWA sin build (JavaScript nativo), service worker y cola de audio en IndexedDB.
- **Backend:** Python 3.12 + FastAPI, con un worker de procesamiento y ffmpeg.
- **Datos:** PostgreSQL con pgvector para la búsqueda híbrida (embeddings + BM25).
- **IA:** proveedores de STT y LLM intercambiables por configuración, con un gateway LiteLLM opcional y trazas en Langfuse.
- **Infraestructura:** Railway, con entornos de staging y producción.

El detalle está en [docs/arquitectura.md](docs/arquitectura.md).

## Correr local

Requisitos: Python 3.12, ffmpeg y un PostgreSQL con la extensión pgvector.

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.lock
pytest -q                     # no consume APIs; usa un schema temporal que se borra al final
DATABASE_URL=postgresql://<usuario>:<clave>@localhost:5433/<base> DB_SCHEMA=app_dev \
  DATA_DIR=./data BOOTSTRAP_USERS=dev:<contraseña> ADMIN_USERS=dev \
  STT_PROVIDER=fake LLM_PROVIDER=fake EMBED_PROVIDER=off uvicorn app.main:app --reload
# http://localhost:8000 → usuario "dev" con la contraseña elegida
```

Con `STT_PROVIDER=fake` y `LLM_PROVIDER=fake` la app funciona completa sin claves de API. Las variables disponibles
están en [`.env.example`](.env.example).

## Documentación

| Documento | Contenido |
|---|---|
| [Arquitectura](docs/arquitectura.md) | Componentes, flujo de una grabación y estructura del código |
| [Despliegue y operación](docs/despliegue.md) | Railway, CI/CD, proveedores de IA, gateway LiteLLM y usuarios |
| [Pruebas](docs/pruebas.md) | Tests automáticos, prueba E2E sin señal y pruebas en dispositivo |
| [CHANGELOG](CHANGELOG.md) | Cambios de cada versión |
| [Cómo contribuir](CONTRIBUTING.md) | Ramas, commits, tests y publicación de versiones |
| [Seguridad](SECURITY.md) | Cómo reportar una vulnerabilidad |
| [Código de conducta](CODE_OF_CONDUCT.md) | Normas de participación |

## Cómo trabajar en el repo

Las reglas (ramas, commits, tests, lint, dependencias con locks y hashes, cómo publicar una versión) están en
[CONTRIBUTING.md](CONTRIBUTING.md). Lo esencial: se trabaja en ramas desde `dev` con PR contra `dev` (nunca contra
`main`), commits con Conventional Commits en castellano, cada funcionalidad nueva con su test y nada de secretos en el
repo. `dev` se publica en staging automáticamente; producción se publica a mano desde GitHub Actions.

## Licencia

[MIT](LICENSE) © 2026 Alejandro Genovese.
