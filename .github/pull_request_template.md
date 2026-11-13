<!-- El PR va contra dev, nunca contra main. Escribilo en castellano. -->

## Qué cambia

<!-- Qué hace este PR y por qué. Si cierra un issue: "Cierra #123". -->

## Cómo se probó

<!-- Tests nuevos o actualizados, pytest local (con o sin catálogo), prueba a mano en el celular, capturas. -->

## Checklist

- [ ] El PR va contra `dev`.
- [ ] Los tests pasan (`pytest -q`) y lo nuevo tiene su test en `tests/`.
- [ ] `ruff check .` pasa.
- [ ] Si cambia algo para el usuario, está en `CHANGELOG.md` → *Sin publicar*.
- [ ] Si se sube la versión, cambió en los tres lugares: `app/__init__.py`, `VERSION` en `web/sw.js` y `CHANGELOG.md`.
- [ ] No hay secretos, tokens ni URLs con credenciales en el diff.
