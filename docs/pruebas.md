# Pruebas

## Tests automáticos

`pytest -q` corre la suite completa con STT, LLM y embeddings falsos (no consume APIs) contra un schema `app_test_*`
temporal. Los tests que usan el catálogo de re:Invent necesitan el schema `reinvent` cargado en el Postgres local y
corren solo local; en CI (`.github/workflows/ci-promote.yml`) corren los tests de núcleo contra un Postgres vacío.
Los tests del frontend corren con `node --test tests/js/`.

## Prueba E2E sin señal

Los flujos sin señal (última copia en Inicio e Itinerario, grabar sin red y subir al volver, portal cautivo) tienen una
prueba de punta a punta en un Chromium real. Se corre **a mano antes de publicar**: no corre en CI (no hay navegador ni
catálogo) y `pytest -q` no la levanta (vive en `tests_e2e/`, sin archivos `test_*`).

```bash
docker start reinvent-pg                   # el mismo Postgres local de arriba
export E2E_DATABASE_URL=postgresql://reinvent:<clave del docker>@localhost:5433/reinvent   # o DATABASE_URL
.venv/bin/python -m tests_e2e              # ~50 s; sale con código 1 si algo falla
```

Sin dependencias nuevas: usa `websockets` y lo que ya instala `requirements-dev.lock`, y maneja Chromium por el protocolo
de DevTools (`tests_e2e/cdp.py`). Levanta la app con STT, LLM y embeddings falsos, un `DATA_DIR` temporal, un schema
`app_e2e_*` propio (se borra al terminar) y un usuario de prueba que crea el propio script. Chromium arranca sin cabeza con
micrófono falso y la red se corta con la emulación *offline* de CDP (también para el service worker).

| # | Escenario |
|---|---|
| 1 | Con red se cargan Inicio e Itinerario; sin red y recargando aparece la franja «Sin señal · datos de las HH:MM» |
| 2 | Sin red: Nueva → grabar ~12 s → Terminar → queda en «Grabadas en este celular» como «Esperando señal» (y el servidor no ve nada) |
| 3 | Vuelve la red: la sesión se crea una sola vez, se suben los pedazos, se cierra y desaparece del bloque local |
| 4 | Portal cautivo: `/api/today` y después todo `/api/` contestan un 200 con HTML → se muestra la última copia |
| 5 | Login: el ojo muestra y oculta la contraseña (44 px, sin tapar el lugar del gestor) y al enviar el formulario vuelve a `password` |

Si un escenario falla, deja capturas, el log de consola y el del servidor en `e2e-fallas/<fecha>/` (ignorada por git).
Variables: `E2E_CHROME` (ejecutable de Chrome/Chromium; por defecto el del caché de Playwright o el Chrome instalado en macOS; si no
hay ninguno la prueba se saltea con un aviso), `E2E_PYTHON` (intérprete con las dependencias de la app; por defecto `.venv`)
y `E2E_DATABASE_URL` (obligatoria si no exportás `DATABASE_URL`: el código no trae ninguna clave).
