# ReinventAR — instrucciones para Claude

Las reglas completas están en `README.md` (sección *Cómo trabajar en el repo*). Lo esencial:

- Escribí en castellano rioplatense: código, comentarios, commits y descripciones de PR.
- Commits con [Conventional Commits](https://www.conventionalcommits.org/es/v1.0.0/) en castellano (`feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:`, `perf:`).
- `main` es producción: Railway deploya cada push a `main`. Nunca pushees ni abras PRs contra `main`.
- Se trabaja en `dev`: creá una rama `feat/...` o `fix/...` desde `dev` y abrí el PR contra `dev`. Lo que entra a `dev` se ve en staging (`staging.reinventar.app`); producción se publica a mano (Actions → `ci-promote.yml` → *Run workflow* sobre `dev`), y lo hace el usuario.
- Las funcionalidades nuevas van con su test en `tests/`. STT, LLM y embeddings se usan en modo `fake`; los tests no consumen APIs.
- En CI y en las Actions no está cargado el catálogo de re:Invent (schema `reinvent`). Corré los tests de núcleo con el mismo comando que `.github/workflows/ci-promote.yml`; los que usan el catálogo quedan para correr local.
- El repo es público: nunca agregues secretos, tokens ni URLs con credenciales. Van en `.env` (ignorado) o en las variables de Railway.
- Si cambiás la versión, se sube en tres lugares a la vez: `app/__init__.py`, `VERSION` en `web/sw.js` y `CHANGELOG.md` (`tests/test_version.py` lo verifica).
- Lo que cambie para el usuario va en `CHANGELOG.md`, sección *Sin publicar*.
