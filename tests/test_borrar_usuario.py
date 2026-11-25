"""Admin › Borrar usuario: se va todo lo suyo (en el schema real y en el de prueba), queda registro y hay límites."""
import uuid

import pytest
from fastapi.testclient import TestClient

from app import audio, borrar_usuario, db, documentos, passwords, sandbox, tickets_almacen
from app.main import app
from tests.conftest import TEST_ADMIN, TEST_ADMIN_PASSWORD, login_headers


class AlmacenFalso:
    def __init__(self):
        self.borradas = []

    def borrar(self, clave):
        self.borradas.append(clave)


@pytest.fixture
def archivos(monkeypatch):
    """Los buckets de documentos y de fotos, falsos: se anota qué claves se borraron."""
    fotos, docs = AlmacenFalso(), []
    monkeypatch.setattr(tickets_almacen, "obtener", lambda: fotos)
    monkeypatch.setattr(documentos, "borrar_objeto", lambda clave: docs.append(clave) or True)
    return fotos, docs


def _nuevo_usuario():
    username = f"b_{uuid.uuid4().hex[:8]}"
    salt, h = passwords.hash_password("borrame123")
    db.create_user(username, salt, h, must_change_password=False)
    return username


def _cargar_datos(username: str, etiqueta: str) -> str:
    """Una grabación con audio, un documento, un gasto con foto y un ítem del itinerario, en el schema del contexto."""
    sid = db.create_session(f"Charla {etiqueta}", "Breakout", created_by=username)["id"]
    audio.session_dir(sid).mkdir(parents=True, exist_ok=True)
    db.add_item(username, f"AIM{etiqueta}", f"AIM{etiqueta}", "2026-12-01", "10:00")
    with db.conn() as c:
        c.execute("INSERT INTO viajes_documentos (username,id,tipo,titulo,archivo_clave,archivo_tipo,bytes,sha256) "
                  "VALUES (%s,%s,'otro','doc',%s,'application/pdf',1,'x')", (username, uuid.uuid4(), f"doc-{etiqueta}"))
        c.execute("INSERT INTO gastos (username,client_id,fecha,monto,moneda,categoria,cotizacion_oficial,cotizacion_blue,"
                  "cotizacion_tarjeta,monto_usd,foto_clave,updated_at) VALUES (%s,%s,'2026-12-01',10,'USD','comida',1,1,1,10,"
                  "%s,now())", (username, uuid.uuid4(), f"foto-{etiqueta}"))
    return sid


def _filas_del_usuario(username: str) -> int:
    with db.conn() as c:
        return sum(c.execute(f"SELECT COUNT(*) AS n FROM {t} WHERE username=%s", (username,)).fetchone()["n"]
                   for t in ("itinerary_items", "viajes_documentos", "gastos"))


def _admin(c):
    return login_headers(c, TEST_ADMIN, TEST_ADMIN_PASSWORD)


def test_borrar_usuario_se_lleva_todo_lo_suyo_en_real_y_en_prueba(archivos):
    fotos, docs = archivos
    with TestClient(app) as c:
        username = _nuevo_usuario()
        H = login_headers(c, username, "borrame123")
        sid_real = _cargar_datos(username, "1")
        with sandbox.activar(sandbox.Sandbox(username=username)):
            sid_prueba = _cargar_datos(username, "2")
            dir_prueba = audio.session_dir(sid_prueba)

        r = c.delete(f"/api/admin/users/{username}", headers=_admin(c))

        assert r.status_code == 200, r.text
        assert r.json()["borrado"]["grabaciones"] == 2
        assert db.get_user(username) is None
        assert c.get("/api/me", headers=H).status_code == 401
        assert db.get_session(sid_real) is None
        assert not audio.session_dir(sid_real).exists()
        assert not dir_prueba.exists()
        assert _filas_del_usuario(username) == 0
        with sandbox.activar(sandbox.Sandbox(username=username)):
            assert _filas_del_usuario(username) == 0
        assert sorted(docs) == ["doc-1", "doc-2"]
        assert sorted(fotos.borradas) == ["foto-1", "foto-2"]


def test_borrar_usuario_deja_registro_de_quien_lo_borro(archivos):
    with TestClient(app) as c:
        username = _nuevo_usuario()

        c.delete(f"/api/admin/users/{username}", headers=_admin(c))

        registro = db.auditoria(username)[0]
        assert (registro["admin"], registro["accion"]) == (TEST_ADMIN, "borrar_usuario")


def test_un_admin_no_se_puede_borrar_a_si_mismo():
    with TestClient(app) as c:
        r = c.delete(f"/api/admin/users/{TEST_ADMIN}", headers=_admin(c))

        assert r.status_code == 400
        assert db.get_user(TEST_ADMIN) is not None


def test_borrar_usuario_inexistente_da_404():
    with TestClient(app) as c:
        assert c.delete("/api/admin/users/no_existe_xyz", headers=_admin(c)).status_code == 404


def test_solo_un_admin_puede_borrar_usuarios():
    with TestClient(app) as c:
        username = _nuevo_usuario()
        otro = _nuevo_usuario()
        H = login_headers(c, username, "borrame123")

        assert c.delete(f"/api/admin/users/{otro}", headers=H).status_code == 403
        assert db.get_user(otro) is not None


def test_avisa_si_el_usuario_vuelve_a_crearse_al_reiniciar(archivos, monkeypatch):
    username = _nuevo_usuario()
    monkeypatch.setattr(db.config, "BOOTSTRAP_USERS", f"{username}:algo12345")

    with TestClient(app):
        resumen = borrar_usuario.borrar(username, TEST_ADMIN)

    assert resumen["vuelve_al_reiniciar"] is True
