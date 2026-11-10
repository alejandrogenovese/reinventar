# Changelog

Todos los cambios relevantes de ReinventAR. El formato sigue [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/)
y la versión, [SemVer](https://semver.org/lang/es/). La versión vive en `app/__init__.py`.

## [Sin publicar]

### Agregado
- Resumen de las charlas en castellano: la ficha y las tarjetas lo muestran traducido y tienen un botón para ver el
  original en inglés. La elección queda recordada en el celular. La búsqueda por texto también busca en la traducción.
- Claves extraídas del resumen de cada charla: servicios de AWS que menciona (completan los que AWS no etiquetó),
  otras tecnologías (Iceberg, MCP, dbt…), conceptos en castellano e inglés y enfoque (novedades, arquitectura, caso
  de cliente, práctica guiada…). Son filtros nuevos en Explorar, aparecen en la ficha de la charla y mejoran la búsqueda.

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

[Sin publicar]: https://github.com/alejandrogenovese/reinventar/compare/v0.19.0...HEAD
[0.19.0]: https://github.com/alejandrogenovese/reinventar/compare/v0.18.0...v0.19.0
[0.18.0]: https://github.com/alejandrogenovese/reinventar/compare/v0.1.0...v0.18.0
[0.1.0]: https://github.com/alejandrogenovese/reinventar/releases/tag/v0.1.0
