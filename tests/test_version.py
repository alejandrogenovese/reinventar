"""Una sola versión: app/__init__.py manda; /health, el service worker y el CHANGELOG la repiten."""
import re
from pathlib import Path

from fastapi.testclient import TestClient

from app import __version__
from app.main import app

ROOT = Path(__file__).resolve().parent.parent


def test_version_sigue_semver():
    assert re.fullmatch(r"\d+\.\d+\.\d+", __version__)


def test_health_informa_la_version():
    with TestClient(app) as c:
        body = c.get("/health").json()

    assert body["version"] == __version__


def test_service_worker_usa_la_misma_version():
    # Si no coincide, el celular sigue sirviendo la PWA vieja desde la caché.
    sw = (ROOT / "web" / "sw.js").read_text()

    assert f'const VERSION = "reinventar-v{__version__}";' in sw


def test_changelog_documenta_la_version_actual():
    changelog = (ROOT / "CHANGELOG.md").read_text()

    assert re.search(rf"^## \[{re.escape(__version__)}\] - \d{{4}}-\d{{2}}-\d{{2}}$", changelog, re.M)
