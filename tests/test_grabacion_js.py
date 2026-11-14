"""Corre las pruebas de JS de la grabación (lógica pura de recorder.js y store.js) con node --test."""
import shutil
import subprocess
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent


@pytest.mark.skipif(shutil.which("node") is None, reason="node no está instalado")
def test_pruebas_js_de_grabacion():
    r = subprocess.run(["node", "--test", "tests/js/"], cwd=RAIZ, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr
