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


@pytest.fixture(scope="session", autouse=True)
def _drop_test_schema():
    yield
    from app import config, pg

    with pg.pool().connection() as c:
        c.execute(f"DROP SCHEMA IF EXISTS {config.DB_SCHEMA} CASCADE")
        c.execute(f"DROP SCHEMA IF EXISTS {config.DB_SCHEMA}_prueba CASCADE")
    pg.close()


def login_headers(client, username=TEST_USER, password=TEST_PASSWORD):
    """Loguea contra /api/login con el TestClient ya abierto (lifespan corrido) y arma el header Authorization."""
    r = client.post("/api/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}
