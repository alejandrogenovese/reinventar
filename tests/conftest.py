"""Variables de entorno por defecto, antes de que cualquier test importe app.main (app.config las lee una sola vez)."""
import os
import tempfile

TEST_USER = "tester"
TEST_PASSWORD = "testpass123"

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="reinventar-test-"))
os.environ.setdefault("BOOTSTRAP_USERS", f"{TEST_USER}:{TEST_PASSWORD}")
os.environ.setdefault("STT_PROVIDER", "fake")
os.environ.setdefault("LLM_PROVIDER", "fake")


def login_headers(client, username=TEST_USER, password=TEST_PASSWORD):
    """Loguea contra /api/login con el TestClient ya abierto (lifespan corrido) y arma el header Authorization."""
    r = client.post("/api/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}
