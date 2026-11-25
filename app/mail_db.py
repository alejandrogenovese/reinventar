"""Persistencia del mail de cada usuario y de sus códigos de un solo uso (tabla mail_codigos, columnas users.email*).

Los códigos se guardan hasheados (sha256): quien lea la base o un backup no puede usarlos. Hay uno vigente por
usuario y tipo: pedir otro reemplaza (e invalida) el anterior. Siempre en el schema real (son de la cuenta).
"""
import hashlib
import time

import psycopg

from . import sandbox
from .db import conn

VERIFICAR = "verificar"
RECUPERAR = "recuperar"


class MailEnUso(Exception):
    """Otro usuario ya tiene ese mail verificado."""


def hash_codigo(username: str, codigo: str) -> str:
    """Los códigos (6 dígitos, de verificación y de recuperación) se hashean junto con el usuario: dos personas con el
    mismo código no comparten hash."""
    return hashlib.sha256(f"{username}:{codigo}".encode()).hexdigest()


def usuario_por_email(email: str) -> dict | None:
    with sandbox.real(), conn() as c:
        r = c.execute("SELECT * FROM users WHERE email=%s", (email,)).fetchone()
    return dict(r) if r else None


def guardar_codigo(username: str, tipo: str, hash_: str, email: str, vigencia: float) -> None:
    ahora = time.time()
    with sandbox.real(), conn() as c:
        c.execute("INSERT INTO mail_codigos (username,tipo,hash,email,creado,vence,intentos) VALUES (%s,%s,%s,%s,%s,%s,0) "
                  "ON CONFLICT (username, tipo) DO UPDATE SET hash=EXCLUDED.hash, email=EXCLUDED.email, "
                  "creado=EXCLUDED.creado, vence=EXCLUDED.vence, intentos=0",
                  (username, tipo, hash_, email, ahora, ahora + vigencia))


def sumar_intento(username: str, tipo: str, maximo: int) -> dict | None:
    """Anota un intento y devuelve el código vigente ({hash, email, vence, intentos}); None si no hay, venció o ya
    se gastaron los intentos. Revisa y anota en una sola sentencia: dos pedidos a la vez no se cuelan por el último
    intento. Solo borra el vencido: uno sin intentos queda hasta que vence, así el anti-pisado lo sigue viendo y quien
    gaste los intentos a propósito no puede pedir otro código en seguida para la víctima."""
    ahora = time.time()
    with sandbox.real(), conn() as c:
        r = c.execute("UPDATE mail_codigos SET intentos = intentos + 1 WHERE username=%s AND tipo=%s AND intentos < %s "
                      "AND vence >= %s RETURNING hash, email, vence, intentos",
                      (username, tipo, maximo, ahora)).fetchone()
        if r is None:
            c.execute("DELETE FROM mail_codigos WHERE username=%s AND tipo=%s AND vence < %s", (username, tipo, ahora))
    return dict(r) if r else None


def borrar_codigo(username: str, tipo: str) -> None:
    with sandbox.real(), conn() as c:
        c.execute("DELETE FROM mail_codigos WHERE username=%s AND tipo=%s", (username, tipo))


def consumir_codigo(username: str, tipo: str, hash_: str) -> str | None:
    """Usa el código (una sola vez: lo borra al leerlo, en la misma sentencia que lo compara). Devuelve el mail al que
    se mandó, o None si no coincide o ya no está: de dos pedidos a la vez con el mismo código, solo uno lo consume."""
    with sandbox.real(), conn() as c:
        r = c.execute("DELETE FROM mail_codigos WHERE username=%s AND tipo=%s AND hash=%s AND vence >= %s RETURNING email",
                      (username, tipo, hash_, time.time())).fetchone()
    return r["email"] if r else None


def codigo_reciente(username: str, tipo: str, segundos: float) -> bool:
    """¿Hay un código vigente de ese tipo creado hace menos de `segundos`?"""
    ahora = time.time()
    with sandbox.real(), conn() as c:
        return c.execute("SELECT 1 FROM mail_codigos WHERE username=%s AND tipo=%s AND creado > %s AND vence >= %s",
                         (username, tipo, ahora - segundos, ahora)).fetchone() is not None


def fijar_email(username: str, email: str) -> None:
    """Guarda el mail ya verificado. MailEnUso si otro usuario lo verificó antes (índice único)."""
    try:
        with sandbox.real(), conn() as c:
            c.execute("UPDATE users SET email=%s, email_verificado_at=%s WHERE username=%s",
                      (email, time.time(), username))
    except psycopg.errors.UniqueViolation as e:
        raise MailEnUso(email) from e
