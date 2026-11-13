"""Persistencia de passkeys y de los challenges de WebAuthn (tablas passkeys y webauthn_challenges)."""
import secrets
import time

from .db import conn

CHALLENGE_TTL_SECONDS = 300


def save_challenge(kind: str, challenge: bytes, username: str | None = None) -> str:
    challenge_id = secrets.token_urlsafe(16)
    with conn() as c:
        c.execute("DELETE FROM webauthn_challenges WHERE created_at < %s", (time.time() - CHALLENGE_TTL_SECONDS,))
        c.execute(
            "INSERT INTO webauthn_challenges (id,kind,username,challenge,created_at) VALUES (%s,%s,%s,%s,%s)",
            (challenge_id, kind, username, challenge, time.time()),
        )
    return challenge_id


def pop_challenge(challenge_id: str, kind: str, username: str | None = None) -> bytes | None:
    """Devuelve el challenge y lo borra (sirve una sola vez); None si no existe, venció o es de otro usuario/tipo."""
    with conn() as c:
        r = c.execute(
            "DELETE FROM webauthn_challenges WHERE id=%s RETURNING kind, username, challenge, created_at", (challenge_id,)
        ).fetchone()
    if not r or r["kind"] != kind or r["username"] != username:
        return None
    if r["created_at"] < time.time() - CHALLENGE_TTL_SECONDS:
        return None
    return bytes(r["challenge"])


def add_passkey(credential_id: str, username: str, public_key: bytes, sign_count: int, device: str | None) -> None:
    with conn() as c:
        c.execute(
            "INSERT INTO passkeys (id,username,public_key,sign_count,device,created_at) VALUES (%s,%s,%s,%s,%s,%s)",
            (credential_id, username, public_key, sign_count, device, time.time()),
        )


def get_passkey(credential_id: str) -> dict | None:
    with conn() as c:
        r = c.execute("SELECT * FROM passkeys WHERE id=%s", (credential_id,)).fetchone()
    return dict(r) if r else None


def list_passkeys(username: str) -> list[dict]:
    with conn() as c:
        rows = c.execute(
            "SELECT id, device, created_at, last_used_at FROM passkeys WHERE username=%s ORDER BY created_at",
            (username,),
        ).fetchall()
    return [dict(r) for r in rows]


def touch_passkey(credential_id: str, sign_count: int) -> None:
    with conn() as c:
        c.execute(
            "UPDATE passkeys SET sign_count=%s, last_used_at=%s WHERE id=%s", (sign_count, time.time(), credential_id)
        )


def delete_passkey(username: str, credential_id: str) -> bool:
    with conn() as c:
        cur = c.execute("DELETE FROM passkeys WHERE id=%s AND username=%s", (credential_id, username))
    return cur.rowcount > 0


def delete_all(username: str) -> int:
    """Borra todas las passkeys del usuario: al cambiar o resetear la contraseña y al revocar sus sesiones, para que
    una passkey registrada con un token robado no sobreviva a la recuperación de la cuenta."""
    with conn() as c:
        return c.execute("DELETE FROM passkeys WHERE username=%s", (username,)).rowcount
