"""Cambia la contraseña de un usuario directo en la base, para cuando nadie puede entrar a Administración.

Sirve si te olvidaste la contraseña y no tenés passkey ni otro admin que te la resetee (por ejemplo, el único admin
durante re:Invent). La contraseña nueva se pide por teclado sin mostrarla y se guarda hasheada como en la app
(PBKDF2, app/passwords.py); nunca pasa por la línea de comandos ni queda en el historial. Cierra las sesiones abiertas
de ese usuario; las passkeys se conservan (olvidarse la contraseña no es una cuenta comprometida: para eso está
«Resetear contraseña» en Administración, que además corta passkeys y notificaciones).

El schema es obligatorio y se escribe a mano: es el valor de DB_SCHEMA del servicio (staging y producción usan
schemas distintos en la misma base), así no se cambia la cuenta equivocada por omisión.

Por defecto corre en modo prueba (ROLLBACK). Con --aplicar confirma. Antes de --aplicar, hacé el backup.

Uso (en tu Terminal; la URL lleva la clave, no la pegues en ningún lado):
  export RAILWAY_DATABASE_URL='postgresql://<usuario>:<clave>@<host del TCP Proxy>:<puerto>/railway'
  python -m scripts.resetear_password --schema <DB_SCHEMA> --usuario <usuario>            # prueba
  python -m scripts.resetear_password --schema <DB_SCHEMA> --usuario <usuario> --aplicar  # de verdad
"""
import argparse
import getpass
import os
import sys

from psycopg import sql

from app import config, passwords

LARGO_MAXIMO = 200  # el mismo tope que el reset de Administración


class ErrorReset(Exception):
    """Algo impide el reset; el mensaje se le muestra tal cual al usuario."""


def validar(password: str, repetida: str) -> str:
    if password != repetida:
        raise ErrorReset("Las dos contraseñas no coinciden.")
    if not config.PASSWORD_MIN_LENGTH <= len(password) <= LARGO_MAXIMO:
        raise ErrorReset(f"La contraseña tiene que tener entre {config.PASSWORD_MIN_LENGTH} y {LARGO_MAXIMO} caracteres.")
    return password


def resetear(conn, schema: str, usuario: str, password: str, forzar_cambio: bool = False) -> int:
    """Guarda la contraseña nueva y cierra las sesiones del usuario, dentro de la transacción de conn (quien llama
    decide COMMIT o ROLLBACK). Devuelve cuántas sesiones cerró."""
    s = sql.Identifier(schema)
    if not conn.execute(sql.SQL("SELECT 1 FROM {}.users WHERE username = %s").format(s), (usuario,)).fetchone():
        raise ErrorReset(f"No existe el usuario «{usuario}» en el schema {schema}.")
    salt, password_hash = passwords.hash_password(password)
    conn.execute(sql.SQL("UPDATE {}.users SET salt = %s, password_hash = %s, must_change_password = %s "
                         "WHERE username = %s").format(s), (salt, password_hash, forzar_cambio, usuario))
    return conn.execute(sql.SQL("DELETE FROM {}.auth_tokens WHERE username = %s").format(s), (usuario,)).rowcount


def pedir_password() -> str:
    return validar(getpass.getpass("Contraseña nueva: "), getpass.getpass("Repetila: "))


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--schema", required=True, help="valor de DB_SCHEMA del servicio (staging y producción difieren)")
    ap.add_argument("--usuario", required=True)
    ap.add_argument("--forzar-cambio", action="store_true", help="que la app pida cambiarla al entrar")
    ap.add_argument("--aplicar", action="store_true", help="confirma; sin esto, ROLLBACK")
    args = ap.parse_args(argv)
    url = os.environ.get("RAILWAY_DATABASE_URL")
    if not url:
        sys.exit("Falta RAILWAY_DATABASE_URL (TCP Proxy del servicio pgvector).")
    import psycopg  # acá y no arriba: los tests de resetear() no necesitan el driver conectado

    try:
        password = pedir_password()
        with psycopg.connect(url) as conn:
            cerradas = resetear(conn, args.schema, args.usuario.strip().lower(), password, args.forzar_cambio)
            if args.aplicar:
                conn.commit()
                print(f"Listo: contraseña cambiada para «{args.usuario}» en {args.schema}; {cerradas} sesiones cerradas.")
            else:
                conn.rollback()
                print(f"Modo prueba: el usuario existe y se cerrarían {cerradas} sesiones. "
                      "No se cambió nada; corré lo mismo con --aplicar.")
    except ErrorReset as e:
        sys.exit(str(e))


if __name__ == "__main__":
    main()
