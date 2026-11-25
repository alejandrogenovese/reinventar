"""Borrado completo de un usuario (Admin › Usuarios › Borrar usuario).

Se borra todo lo que es de la persona, en el schema real y en el de prueba (app/sandbox.py):
- sus grabaciones (las que creó: created_by) con su audio en disco, pedazos, bloques, fragmentos y votos;
- sus documentos de viaje (filas y archivos cifrados del bucket) y las fotos de sus gastos;
- cada tabla de datos del usuario (itinerario, eventos, viajes, gastos, avisos, fichas, etc.);
- su cuenta: sesiones, passkeys, suscripciones push, challenges de WebAuthn y la fila de users;
- sus contadores de límites en memoria.
Primero se desactiva y se cortan los accesos, así no escribe nada mientras se borra. Los archivos van antes que las filas:
después de borrarlas ya no se sabría cuáles eran. Si un archivo del bucket no se puede borrar, se cuenta y se loguea.
"""
import logging
import shutil

from . import audio, db, documentos, limites, passkeys_db, sandbox, tickets_almacen

log = logging.getLogger("reinventar.admin")

# Tablas de datos que cuelgan de una grabación (sin columna username): se borran con db.delete_session.
_DE_GRABACIONES = ("sessions", "chunks", "blocks", "fragmentos")
# Cachés por usuario que se crean a demanda (pueden no existir todavía en un schema).
_A_DEMANDA = ("briefings",)
# Tablas de la cuenta: solo existen en el schema real.
_CUENTA = ("auth_tokens", "passkeys", "push_subscriptions", "webauthn_challenges")


def _tablas_con_username() -> tuple[str, ...]:
    return tuple(t for t in db.tablas_datos_usuario() if t not in _DE_GRABACIONES) + _A_DEMANDA


def _borrar_grabaciones(username: str) -> int:
    with db.conn() as c:
        ids = [r["id"] for r in c.execute("SELECT id FROM sessions WHERE created_by=%s", (username,)).fetchall()]
    for sid in ids:
        db.delete_session(sid)
        shutil.rmtree(audio.session_dir(sid), ignore_errors=True)
    return len(ids)


def _borrar_fotos_gastos(username: str) -> tuple[int, int]:
    """(borradas, fallidas): las fotos de ticket de sus gastos, antes de borrar las filas que dicen cuáles son."""
    with db.conn() as c:
        claves = [r["foto_clave"] for r in c.execute(
            "SELECT foto_clave FROM gastos WHERE username=%s AND foto_clave IS NOT NULL", (username,)).fetchall()]
    fallidas = 0
    almacen = tickets_almacen.obtener() if claves else None
    for clave in claves:
        try:
            almacen.borrar(clave)
        except Exception:  # un bucket caído no frena el borrado: se cuenta y se avisa
            log.exception("No se pudo borrar una foto de gasto del usuario borrado")
            fallidas += 1
    return len(claves) - fallidas, fallidas


def _borrar_filas(username: str) -> int:
    total = 0
    with db.conn() as c:
        for tabla in _tablas_con_username():
            if c.execute("SELECT to_regclass(%s) AS t", (tabla,)).fetchone()["t"] is None:
                continue  # caché a demanda que todavía no se creó en este schema
            total += c.execute(f"DELETE FROM {tabla} WHERE username=%s", (username,)).rowcount  # nombres del código
    return total


def _borrar_datos(username: str) -> dict:
    """Lo del usuario en el schema del contexto actual (real o prueba)."""
    grabaciones = _borrar_grabaciones(username)
    docs = documentos.borrar_todos(username)
    fotos, fotos_fallidas = _borrar_fotos_gastos(username)
    return {"grabaciones": grabaciones, "documentos": docs, "fotos": fotos, "fotos_fallidas": fotos_fallidas,
            "filas": _borrar_filas(username)}


def _sumar(a: dict, b: dict) -> dict:
    return {k: a.get(k, 0) + b.get(k, 0) for k in a.keys() | b.keys()}


def _borrar_cuenta(username: str) -> None:
    with sandbox.real(), db.conn() as c:
        for tabla in _CUENTA:
            c.execute(f"DELETE FROM {tabla} WHERE username=%s", (username,))  # nombres del código
        c.execute("DELETE FROM users WHERE username=%s", (username,))


def borrar(username: str, admin: str) -> dict:
    """Borra al usuario y todo lo suyo; deja registro en auditoria_admin. Devuelve un resumen de lo borrado."""
    with sandbox.real():
        db.set_user_active(username, False)
        db.revoke_tokens(username)
        passkeys_db.delete_all(username)
        resumen = _borrar_datos(username)
    with sandbox.activar(sandbox.Sandbox(username=username)):
        resumen = _sumar(resumen, _borrar_datos(username))
    _borrar_cuenta(username)
    for limite in limites.TODOS:
        limite.limpiar(username)
    resumen["vuelve_al_reiniciar"] = db.en_bootstrap(username)
    db.registrar_auditoria(admin, "borrar_usuario", username, resumen)
    log.warning("El admin %s borró al usuario %s: %s", admin, username, resumen)
    return resumen
