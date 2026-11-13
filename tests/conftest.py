"""Variables de entorno por defecto, antes de que cualquier test importe app.main (app.config las lee una sola vez)."""
import os
import tempfile
import uuid

import pytest

TEST_USER = "tester"
TEST_PASSWORD = "testpass123"
TEST_ADMIN = "admin_t"
TEST_ADMIN_PASSWORD = "adminpass123"

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="reinventar-test-"))
os.environ.setdefault("BOOTSTRAP_USERS", f"{TEST_USER}:{TEST_PASSWORD},{TEST_ADMIN}:{TEST_ADMIN_PASSWORD}")
os.environ.setdefault("ADMIN_USERS", TEST_ADMIN)
os.environ.setdefault("STT_PROVIDER", "fake")
os.environ.setdefault("LLM_PROVIDER", "fake")
os.environ.setdefault("EMBED_PROVIDER", "fake")  # vectores por hashing de palabras: sin bajar el modelo en los tests
# Postgres del docker local; cada corrida usa un schema propio que se borra al final.
os.environ.setdefault("DATABASE_URL", "postgresql://reinvent:reinvent2026@localhost:5433/reinvent")
os.environ.setdefault("DB_SCHEMA", f"app_test_{uuid.uuid4().hex[:8]}")
# Que los tests no dependan de la shell (railway run, claves exportadas para scripts/evaluar_modelos.py): sin claves de
# Langfuse no se manda ningún score real, y sin el entorno de Railway las trazas llevan el tag "dev".
for _variable in ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "RAILWAY_ENVIRONMENT_NAME"):
    os.environ[_variable] = ""


@pytest.fixture(scope="session", autouse=True)
def _drop_test_schema():
    yield
    from app import config, pg

    with pg.pool().connection() as c:
        c.execute(f"DROP SCHEMA IF EXISTS {config.DB_SCHEMA} CASCADE")
        c.execute(f"DROP SCHEMA IF EXISTS {config.DB_SCHEMA}_prueba CASCADE")
    pg.close()


def login_headers(client, username=TEST_USER, password=TEST_PASSWORD):
    """Loguea contra /api/login con el TestClient ya abierto (lifespan corrido) y arma el header Authorization.
    Los usuarios de BOOTSTRAP_USERS nacen con contraseña temporal y el servidor exige cambiarla: acá se da por
    cambiada (misma contraseña), salvo en los tests que prueban justamente eso."""
    r = client.post("/api/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    if r.json()["must_change_password"]:
        from app import db, passwords

        salt, password_hash = passwords.hash_password(password)
        db.set_password(username, salt, password_hash, must_change_password=False)
    return {"Authorization": f"Bearer {r.json()['token']}"}


@pytest.fixture(autouse=True)
def _sin_intentos_acumulados():
    """El límite de intentos de login vive en memoria: cada test arranca de cero."""
    from app import limites

    limites.reiniciar_todo()
    yield
