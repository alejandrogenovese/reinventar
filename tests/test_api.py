"""Test end-to-end del backend con STT y LLM falsos (no consume APIs)."""
import os
import subprocess
import tempfile
import time
from pathlib import Path

DATA = tempfile.mkdtemp(prefix="reinventar-test-")
os.environ.update(DATA_DIR=DATA, STT_PROVIDER="fake", LLM_PROVIDER="fake", STT_SEGMENT_SECONDS="8")

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from tests.conftest import login_headers  # noqa: E402


def _webm(seconds: int, freq: int) -> bytes:
    out = Path(DATA) / f"tone-{freq}.webm"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"sine=frequency={freq}:duration={seconds}",
                    "-c:a", "libopus", "-b:a", "32k", str(out)], check=True)
    return out.read_bytes()


def _split(data: bytes, n: int) -> list[bytes]:
    size = len(data) // n + 1
    return [data[i:i + size] for i in range(0, len(data), size)]


def test_flujo_completo():
    with TestClient(app) as c:
        assert c.get("/health").json()["ok"]
        assert c.get("/api/sessions").status_code == 401
        H = login_headers(c)

        s = c.post("/api/sessions", headers=H, json={"title": "Lakehouse con Iceberg", "kind": "Chalk talk", "code": "ANT301"}).json()
        sid = s["id"]

        # Dos partes (simula una recarga de la PWA a mitad de la grabación).
        p0, p1 = _split(_webm(12, 440), 5), _split(_webm(6, 660), 3)
        for seq, chunk in enumerate(p0):
            assert c.put(f"/api/sessions/{sid}/chunks/0/{seq}", headers=H, content=chunk).status_code == 200
        # reintento idempotente
        assert c.put(f"/api/sessions/{sid}/chunks/0/0", headers=H, content=p0[0]).status_code == 200
        for seq, chunk in enumerate(p1[:-1]):
            c.put(f"/api/sessions/{sid}/chunks/1/{seq}", headers=H, content=chunk)

        r = c.post(f"/api/sessions/{sid}/finish", headers=H, json={"parts": {"0": len(p0), "1": len(p1)}})
        assert r.status_code == 409 and r.json()["detail"]["missing"] == {"1": [len(p1) - 1]}

        c.put(f"/api/sessions/{sid}/chunks/1/{len(p1) - 1}", headers=H, content=p1[-1])
        assert c.post(f"/api/sessions/{sid}/finish", headers=H, json={"parts": {"0": len(p0), "1": len(p1)}}).status_code == 200

        for _ in range(120):
            s = c.get(f"/api/sessions/{sid}", headers=H).json()
            if s["status"] in ("ready", "error"):
                break
            time.sleep(0.25)
        assert s["status"] == "ready", s.get("error")
        assert 17 <= s["duration_s"] <= 19
        assert s["blocks"] and all(b["es"] for b in s["blocks"])
        assert s["summary"]["tldr"]

        md = c.get(f"/api/sessions/{sid}/export.md", headers=H).text
        assert "# Lakehouse con Iceberg" in md and "## Para llevar a Galicia" in md

        assert c.put(f"/api/sessions/{sid}/chunks/0/99", headers=H, content=b"x").status_code == 409
        assert c.delete(f"/api/sessions/{sid}", headers=H).status_code == 200
        assert c.get(f"/api/sessions/{sid}", headers=H).status_code == 404


def test_pwa_se_sirve():
    with TestClient(app) as c:
        assert c.get("/").status_code == 200
        assert c.get("/sw.js").status_code == 200
        assert c.get("/manifest.webmanifest").status_code == 200
