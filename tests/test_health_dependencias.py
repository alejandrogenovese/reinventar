"""/health: además de "el proceso responde", prueba Postgres y escritura en DATA_DIR, rápido y sin filtrar detalles.
La base se simula: estos tests no tocan Postgres (y por eso corren también en el CI sin catálogo)."""
import time
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient

from app import __version__, config, pg
from app import main as app_main
from app.main import app


class _ConexionFalsa:
    def __init__(self, consultas):
        self.consultas = consultas

    def execute(self, sql, *args):
        self.consultas.append(sql)


class _PoolFalso:
    """Imita pool().connection(timeout=...): anota las consultas, y opcionalmente tarda o explota."""

    def __init__(self, error=None, demora=0.0):
        self.error = error
        self.demora = demora
        self.consultas = []
        self.timeouts = []

    @contextmanager
    def connection(self, timeout=None):
        self.timeouts.append(timeout)
        if self.demora:
            time.sleep(self.demora)
        if self.error:
            raise self.error
        yield _ConexionFalsa(self.consultas)


@pytest.fixture
def cliente(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    return TestClient(app)  # sin `with`: no corre el lifespan, no se toca la base


def _con_pool(monkeypatch, pool):
    monkeypatch.setattr(pg, "pool", lambda: pool)
    return pool


def _datos_que_no_es_carpeta(monkeypatch, tmp_path):
    """DATA_DIR apunta a un archivo: no se puede crear ni escribir adentro."""
    archivo = tmp_path / "no-es-carpeta"
    archivo.write_text("x")
    monkeypatch.setattr(config, "DATA_DIR", archivo)


def test_todo_anda_devuelve_200_con_el_formato_de_siempre(cliente, monkeypatch):
    pool = _con_pool(monkeypatch, _PoolFalso())

    r = cliente.get("/health")

    assert r.status_code == 200
    assert r.json() == {"ok": True, "version": __version__, "stt": config.STT_PROVIDER, "llm": config.LLM_PROVIDER}
    assert pool.consultas[-1] == "SELECT 1"
    assert pool.timeouts == [app_main.HEALTH_TIMEOUT_SEGUNDOS]


def test_la_prueba_de_escritura_no_deja_archivos(cliente, monkeypatch, tmp_path):
    _con_pool(monkeypatch, _PoolFalso())

    cliente.get("/health")

    assert list(tmp_path.iterdir()) == []


def test_postgres_caido_devuelve_503_sin_filtrar_el_detalle(cliente, monkeypatch):
    _con_pool(monkeypatch, _PoolFalso(error=RuntimeError("password authentication failed para el usuario secreto")))

    r = cliente.get("/health")

    assert r.status_code == 503
    cuerpo = r.json()
    assert cuerpo["ok"] is False
    assert cuerpo["fallas"] == ["postgres"]
    assert {"version", "stt", "llm"} <= set(cuerpo)
    assert "password" not in r.text and "secreto" not in r.text


def test_disco_sin_escritura_devuelve_503(cliente, monkeypatch, tmp_path):
    _con_pool(monkeypatch, _PoolFalso())
    _datos_que_no_es_carpeta(monkeypatch, tmp_path)

    r = cliente.get("/health")

    assert r.status_code == 503
    assert r.json()["ok"] is False
    assert r.json()["fallas"] == ["disco"]


def test_informa_todas_las_fallas_juntas(cliente, monkeypatch, tmp_path):
    _con_pool(monkeypatch, _PoolFalso(error=RuntimeError("caída")))
    _datos_que_no_es_carpeta(monkeypatch, tmp_path)

    r = cliente.get("/health")

    assert r.status_code == 503
    assert sorted(r.json()["fallas"]) == ["disco", "postgres"]


def test_postgres_colgado_no_cuelga_el_health(cliente, monkeypatch):
    monkeypatch.setattr(app_main, "HEALTH_TIMEOUT_SEGUNDOS", 0.2)
    _con_pool(monkeypatch, _PoolFalso(demora=1.0))

    inicio = time.monotonic()
    r = cliente.get("/health")

    assert time.monotonic() - inicio < 0.9
    assert r.status_code == 503
    assert r.json()["fallas"] == ["postgres"]
