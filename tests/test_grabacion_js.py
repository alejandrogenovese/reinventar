"""Corre las pruebas de JS de la grabación (lógica pura de recorder.js y store.js) con node --test."""
import shutil
import subprocess
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent


@pytest.mark.skipif(shutil.which("node") is None, reason="node no está instalado")
def test_pruebas_js_de_grabacion():
    # Archivos explícitos: Node 18/20 no aceptan un directorio en `node --test` (solo los más nuevos).
    archivos = [str(a.relative_to(RAIZ)) for a in sorted((RAIZ / "tests" / "js").glob("*.test.mjs"))]
    assert archivos, "no hay pruebas de JS en tests/js"
    r = subprocess.run(["node", "--test", *archivos], cwd=RAIZ, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr
