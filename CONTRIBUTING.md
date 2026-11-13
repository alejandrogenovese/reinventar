# Cómo contribuir a ReinventAR

Gracias por darte una vuelta. Esta guía junta las reglas para trabajar en el repo: ramas, commits, tests, lint,
dependencias y cómo se publica una versión. Para levantar la app local mirá [README → Correr local](README.md#correr-local)
y para entender las piezas, [docs/arquitectura.md](docs/arquitectura.md).

Al participar aceptás el [Código de conducta](CODE_OF_CONDUCT.md). Si encontrás una vulnerabilidad, no abras un issue:
seguí [SECURITY.md](SECURITY.md).

## Ramas y PRs

- `main` es producción: cada push despliega en Railway. **No se toca a mano** ni se abren PRs contra `main`.
- Se trabaja en `dev`. Para cada cambio, una rama `feat/...`, `fix/...`, `docs/...` o `chore/...` desde `dev` y un PR
  contra `dev`. Al completar el PR, el template te pide qué cambia, cómo lo probaste y un checklist.
- Cuando `dev` pasa los tests, `.github/workflows/ci-promote.yml` adelanta `main` a `dev` (fast-forward) y Railway
  deploya solo.
- Si la promoción falla porque `main` tiene commits que `dev` no tiene: `git checkout dev && git merge origin/main && git push`.

## Idioma y commits

- Todo en castellano rioplatense: código, comentarios, commits y descripciones de PR.
- Commits con [Conventional Commits](https://www.conventionalcommits.org/es/v1.0.0/) en castellano: `feat:`, `fix:`,
  `docs:`, `refactor:`, `test:`, `chore:`, `perf:`, `ci:`. Ejemplo: `fix: no cortar la grabación al bloquear la pantalla`.

## Tests

- Las funcionalidades nuevas van con su test en `tests/`. STT, LLM y embeddings corren en modo `fake`: los tests no
  consumen APIs.
- Local, con el Postgres `reinvent-pg` (pgvector, puerto 5433) y el schema `reinvent` cargado, corre todo:
  ```bash
  pytest -q   # usa un schema app_test_* que se borra al final
  ```
- En CI no está el catálogo de re:Invent, así que corren solo los tests de núcleo. Para reproducir CI, usá el mismo
  comando de `.github/workflows/ci-promote.yml` (los `--ignore` y `--deselect` de ese paso).

## Lint

El repo usa [ruff](https://docs.astral.sh/ruff/) con la configuración de `pyproject.toml` (reglas `E`, `F`, `W`, `I`,
`B`, `UP`, `SIM`). CI corre `ruff check .` antes de los tests.

```bash
ruff check .          # revisar
ruff check --fix .    # aplicar los arreglos seguros
```

**No corras `ruff format`**: el código tiene un estilo compacto deliberado y un reformateo masivo ensucia el historial.
Si una regla no aplica en un caso puntual, ignorala en esa línea con `# noqa: <regla>` y el motivo.

Opcional, para que se revise solo en cada commit: [pre-commit](https://pre-commit.com/) con `.pre-commit-config.yaml`
(ruff, espacios al final, fin de archivo, YAML, archivos grandes y claves privadas).

```bash
pip install pre-commit && pre-commit install
```

## Secretos

El repo es público: nunca agregues secretos, tokens ni URLs con credenciales. Van en `.env` local (ignorado por git) o
en las variables de Railway. `.env.example` tiene los nombres de las variables, sin valores reales.

## CHANGELOG

Todo lo que cambie para el usuario va en `CHANGELOG.md`, sección *Sin publicar*
([Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/)).

## Dependencias

Las dependencias directas se declaran en `requirements.txt` (producción) y `requirements-dev.txt` (más pytest y ruff).
CI y Docker instalan desde los locks (`requirements.lock`, `requirements-dev.lock`): todas las versiones fijas,
transitivas incluidas, con hashes y solo wheels (`--require-hashes --only-binary :all:`). Después de cambiar un
`requirements*.txt`, regenerá los dos:

```bash
OPTS="--generate-hashes --only-binary :all: --python-version 3.12 --python-platform x86_64-manylinux_2_28 --no-header"
uv pip compile requirements.txt $OPTS -o requirements.lock
uv pip compile requirements-dev.txt $OPTS -o requirements-dev.lock
```

Las acciones de GitHub en `.github/workflows` van fijadas por SHA de commit, con la versión en un comentario
(`uses: owner/accion@<sha> # vX.Y.Z`). Dependabot (`.github/dependabot.yml`) abre PRs semanales contra `dev` para pip,
Actions y Docker.

## Publicar una versión

La versión sigue [SemVer](https://semver.org/lang/es/): `MAJOR.MINOR.PATCH` (`fix` sube PATCH, `feat` sube MINOR).

1. Subí `__version__` en `app/__init__.py`.
2. Subí `VERSION` en `web/sw.js` al mismo número, para que los celulares descarguen la PWA nueva.
3. En `CHANGELOG.md`, pasá lo de *Sin publicar* a una sección `## [X.Y.Z] - AAAA-MM-DD` y actualizá los links del final.
4. `pytest -q` (`tests/test_version.py` verifica que los tres coincidan).
5. Commit `chore: versión X.Y.Z`, tag y push:
   ```bash
   git tag -a vX.Y.Z -m "vX.Y.Z" && git push && git push --tags
   ```

## Claude Code en issues y PRs

Mencioná `@claude` en un issue, un PR o una revisión y Claude Code responde, implementa o abre un PR contra `dev`
(`.github/workflows/claude.yml`). Solo responde a usuarios con permiso de escritura y sigue las reglas de `CLAUDE.md`.
