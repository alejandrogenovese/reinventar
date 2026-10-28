"""Hash y verificación de contraseñas: PBKDF2-HMAC-SHA256 con salt random, sin dependencias nuevas."""
import hashlib
import hmac
import secrets

_ITERATIONS = 310_000  # recomendación OWASP 2023 para PBKDF2-SHA256


def hash_password(password: str) -> tuple[str, str]:
    """Devuelve (salt, hash), ambos en hex."""
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), _ITERATIONS)
    return salt, digest.hex()


def verify_password(password: str, salt: str, expected_hash: str) -> bool:
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), _ITERATIONS)
    return hmac.compare_digest(digest.hex(), expected_hash)
