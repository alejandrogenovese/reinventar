"""Grabaciones entre varios: permisos de reintentar y borrar, aviso de grabación duplicada, resumen para compartir y el
link público que vence (/c/<token>). Corre en CI: Postgres local, sin APIs."""
import time
import uuid

import pytest
from fastapi.testclient import TestClient

from app import db, gastos_links, grabaciones_links, pipeline
from app.main import app
from tests.conftest import TEST_ADMIN, TEST_ADMIN_PASSWORD, TEST_USER, login_headers

PASSWORD = "otrapass1234"
XSS = '<script>alert("x")</script><img src=x onerror=alert(1)>'
RESUMEN = {
    "tldr": "Iceberg en S3 Tables " + XSS,
    "key_points": ["Punto uno", "Punto <b>dos</b>"],
    "services": ["S3 Tables", "Athena"],
    "announcements": [{"service": "S3", "text": "Tablas nuevas"}],
    "quotes": [{"time": "00:12:03", "text": "Una frase"}],
    "vs_abstract": "SECRETO-VS-ABSTRACT",
    "takeaways": ["SECRETO-TAKEAWAY"],
}


@pytest.fixture
def cli():
    with TestClient(app) as c:
        c.admin = login_headers(c, TEST_ADMIN, TEST_ADMIN_PASSWORD)
        c.user = login_headers(c)
        c.otro_nombre = f"otro_{uuid.uuid4().hex[:6]}"
        assert c.post("/api/admin/users", headers=c.admin,
                      json={"username": c.otro_nombre, "password": PASSWORD}).status_code == 200
        c.otro = login_headers(c, c.otro_nombre, PASSWORD)
        c.creadas = []
        yield c
        for sid in c.creadas:
            db.delete_session(sid)


def _grabacion(c, created_by=TEST_USER, code=None, listo=True, **extra):
    sid = db.create_session("Lakehouse con Iceberg", "Chalk talk", code or f"T{uuid.uuid4().hex[:6].upper()}",
                            speaker="Ana Speaker", created_by=created_by)["id"]
    if listo:
        db.update_session(sid, status="ready", summary=RESUMEN, **extra)
    c.creadas.append(sid)
    return sid


# --- permisos: reintentar y borrar ------------------------------------------------------------------

@pytest.mark.parametrize("quien,esperado", [("user", 200), ("otro", 403), ("admin", 200)])
def test_borrar_solo_el_dueno_o_un_admin(cli, quien, esperado):
    sid = _grabacion(cli)
    r = cli.delete(f"/api/sessions/{sid}", headers=getattr(cli, quien))
    assert r.status_code == esperado, r.text
    if esperado == 403:
        assert "Solo quien grabó" in r.json()["detail"]
        assert db.get_session(sid) is not None


@pytest.mark.parametrize("quien,esperado", [("user", 200), ("otro", 403), ("admin", 200)])
def test_reintentar_solo_el_dueno_o_un_admin(cli, monkeypatch, quien, esperado):
    monkeypatch.setattr(pipeline, "enqueue", lambda sid: None)
    sid = _grabacion(cli)
    assert cli.post(f"/api/sessions/{sid}/retry", headers=getattr(cli, quien)).status_code == esperado


@pytest.mark.parametrize("quien,esperado", [("user", 403), ("otro", 403), ("admin", 200)])
def test_las_viejas_sin_dueno_solo_las_toca_un_admin(cli, monkeypatch, quien, esperado):
    monkeypatch.setattr(pipeline, "enqueue", lambda sid: None)
    sid = _grabacion(cli, created_by=None)
    assert cli.post(f"/api/sessions/{sid}/retry", headers=getattr(cli, quien)).status_code == esperado
    assert cli.delete(f"/api/sessions/{sid}", headers=getattr(cli, quien)).status_code == esperado


def test_ver_y_exportar_sigue_para_todos_y_el_get_dice_si_es_mia(cli):
    sid = _grabacion(cli)
    mia = cli.get(f"/api/sessions/{sid}", headers=cli.user).json()
    ajena = cli.get(f"/api/sessions/{sid}", headers=cli.otro).json()
    assert (mia["es_mia"], mia["puede_borrar"]) == (True, True)
    assert (ajena["es_mia"], ajena["puede_borrar"]) == (False, False)
    assert cli.get(f"/api/sessions/{sid}", headers=cli.admin).json()["puede_borrar"] is True
    assert cli.get(f"/api/sessions/{sid}/export.md", headers=cli.otro).status_code == 200


# --- aviso de grabación duplicada -------------------------------------------------------------------

def test_avisa_quien_ya_esta_grabando_esa_charla(cli):
    code = f"DUP{uuid.uuid4().hex[:5].upper()}"
    sid = _grabacion(cli, code=code, listo=False)
    r = cli.get("/api/sessions/activa", params={"code": code.lower()}, headers=cli.otro)
    assert r.status_code == 200
    assert r.json() == {"activa": {"id": sid, "quien": TEST_USER, "status": "recording"}}


def test_la_propia_no_cuenta_y_sin_grabaciones_no_hay_aviso(cli):
    code = f"DUP{uuid.uuid4().hex[:5].upper()}"
    _grabacion(cli, code=code, listo=False)
    assert cli.get("/api/sessions/activa", params={"code": code}, headers=cli.user).json() == {"activa": None}
    assert cli.get("/api/sessions/activa", params={"code": "NADA999"}, headers=cli.otro).json() == {"activa": None}


def test_una_sin_dueno_tambien_avisa_sin_nombre(cli):
    code = f"DUP{uuid.uuid4().hex[:5].upper()}"
    sid = _grabacion(cli, created_by=None, code=code, listo=False)
    assert cli.get("/api/sessions/activa", params={"code": code}, headers=cli.otro).json() == {
        "activa": {"id": sid, "quien": None, "status": "recording"}}


def test_una_grabacion_vieja_y_cerrada_no_avisa(cli):
    code = f"DUP{uuid.uuid4().hex[:5].upper()}"
    sid = _grabacion(cli, code=code)
    db.update_session(sid, created_at=time.time() - 3600)  # hace una hora, ya procesada
    assert cli.get("/api/sessions/activa", params={"code": code}, headers=cli.otro).json() == {"activa": None}


def test_el_aviso_pide_sesion(cli):
    assert cli.get("/api/sessions/activa", params={"code": "ANT301"}).status_code == 401


# --- resumen para compartir --------------------------------------------------------------------------

def test_el_markdown_publico_no_lleva_lo_personal(cli):
    sid = _grabacion(cli)
    r = cli.get(f"/api/sessions/{sid}/resumen.md", headers=cli.otro)
    assert r.status_code == 200
    md = r.text
    assert "Iceberg en S3 Tables" in md and "Punto uno" in md and "Una frase" in md and "Ana Speaker" in md
    assert "SECRETO" not in md and "Transcripción" not in md
    completo = cli.get(f"/api/sessions/{sid}/export.md", headers=cli.user).text
    assert "SECRETO-TAKEAWAY" in completo  # el export sigue completo


def test_sin_resumen_no_hay_markdown_publico(cli):
    sid = _grabacion(cli, listo=False)
    assert cli.get(f"/api/sessions/{sid}/resumen.md", headers=cli.user).status_code == 409


# --- link público --------------------------------------------------------------------------------------

def _token(url: str) -> str:
    return url.rsplit("/c/", 1)[1]


def test_compartir_da_un_link_que_abre_la_pagina_publica(cli):
    sid = _grabacion(cli)
    r = cli.post(f"/api/sessions/{sid}/compartir", headers=cli.user)
    assert r.status_code == 200, r.text
    assert "/c/" in r.json()["url"] and r.json()["vence"]
    p = cli.get(f"/c/{_token(r.json()['url'])}")
    assert p.status_code == 200
    assert p.headers["content-type"].startswith("text/html")
    assert p.headers["referrer-policy"] == "no-referrer"
    assert "noindex" in p.headers["x-robots-tag"] and '<meta name="robots" content="noindex' in p.text
    csp = p.headers["content-security-policy"]
    assert "default-src 'none'" in csp and "'unsafe-inline'" not in csp
    assert "max-age=" in p.headers["cache-control"]
    assert "Lakehouse con Iceberg" in p.text and "Punto uno" in p.text and "Athena" in p.text and "Ana Speaker" in p.text


def test_la_pagina_publica_no_muestra_lo_personal_ni_datos_internos(cli):
    sid = _grabacion(cli)
    db.set_voto_resumen(sid, TEST_USER, True)
    token, _ = grabaciones_links.firmar(sid)
    html = cli.get(f"/c/{token}").text
    assert "SECRETO" not in html
    assert TEST_USER not in html and sid not in html
    assert "sirvió" not in html


def test_la_pagina_publica_escapa_el_html_del_resumen(cli):
    sid = _grabacion(cli)
    token, _ = grabaciones_links.firmar(sid)
    html = cli.get(f"/c/{token}").text
    assert "<script>alert" not in html and "<img src=x" not in html and "<b>dos</b>" not in html
    assert "&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt;" in html and "&lt;b&gt;dos&lt;/b&gt;" in html
    assert '<script src="/js/imprimir.js" defer></script>' in html  # el único script: propio, sin inline


@pytest.mark.parametrize("quien,esperado", [("otro", 403), ("admin", 200)])
def test_compartir_por_link_solo_el_dueno_o_un_admin(cli, quien, esperado):
    sid = _grabacion(cli)
    assert cli.post(f"/api/sessions/{sid}/compartir", headers=getattr(cli, quien)).status_code == esperado


def test_compartir_una_vieja_sin_dueno_solo_admin(cli):
    sid = _grabacion(cli, created_by=None)
    assert cli.post(f"/api/sessions/{sid}/compartir", headers=cli.user).status_code == 403
    assert cli.post(f"/api/sessions/{sid}/compartir", headers=cli.admin).status_code == 200


def test_compartir_sin_resumen_es_409(cli):
    sid = _grabacion(cli, listo=False)
    assert cli.post(f"/api/sessions/{sid}/compartir", headers=cli.user).status_code == 409


def _mismo_404(cli, token):
    r = cli.get(f"/c/{token}")
    assert r.status_code == 404
    assert "Este link no existe o ya venció." in r.text
    assert r.headers["referrer-policy"] == "no-referrer"
    return r.text


def test_token_adulterado_vencido_ajeno_o_sin_grabacion_dan_el_mismo_404(cli, monkeypatch):
    sid = _grabacion(cli)
    token, _ = grabaciones_links.firmar(sid)
    cuerpo, firma = token.split(".")
    otro_cuerpo = grabaciones_links._b64(f"{_grabacion(cli)}\n{int(time.time()) + 999}".encode())
    respuestas = {
        _mismo_404(cli, f"{otro_cuerpo}.{firma}"),            # sid cambiado: la firma no coincide
        _mismo_404(cli, f"{cuerpo}.{firma[:-2]}AA"),           # firma tocada
        _mismo_404(cli, "basura"),
        _mismo_404(cli, "a" * 500),
        _mismo_404(cli, gastos_links.firmar(TEST_USER, uuid.uuid4())),  # token de foto de ticket
    }
    inexistente, _ = grabaciones_links.firmar("noexiste123")
    respuestas.add(_mismo_404(cli, inexistente))
    sin_listo, _ = grabaciones_links.firmar(_grabacion(cli, listo=False))
    respuestas.add(_mismo_404(cli, sin_listo))
    monkeypatch.setattr(grabaciones_links, "_ahora", lambda: int(time.time()) + 15 * 86400)  # pasaron 15 días
    respuestas.add(_mismo_404(cli, token))
    assert len(respuestas) == 1  # todas idénticas: no dan pistas de qué falló


def test_un_token_de_foto_no_verifica_como_de_grabacion_ni_al_reves():
    foto = gastos_links.firmar("ana", uuid.uuid4())
    grabacion, _ = grabaciones_links.firmar("abc123")
    assert grabaciones_links.verificar(foto) is None
    assert gastos_links.verificar(grabacion) is None
    assert grabaciones_links.verificar(grabacion) == "abc123"


def test_el_link_vence_a_los_dias_configurados(monkeypatch):
    monkeypatch.setattr(grabaciones_links.config, "GRABACION_LINK_DIAS", 14)
    ahora = int(time.time())
    _, vence = grabaciones_links.firmar("abc123")
    assert 14 * 86400 - 5 <= vence - ahora <= 14 * 86400 + 5


def test_si_se_borra_la_grabacion_el_link_deja_de_andar(cli):
    sid = _grabacion(cli)
    token, _ = grabaciones_links.firmar(sid)
    assert cli.get(f"/c/{token}").status_code == 200
    db.delete_session(sid)
    _mismo_404(cli, token)


def test_la_pagina_publica_tiene_limite_por_ip(cli, monkeypatch):
    from app import limites

    monkeypatch.setattr(limites.links_grabacion, "maximo", 2)
    assert cli.get("/c/basura").status_code == 404
    assert cli.get("/c/basura").status_code == 404
    assert cli.get("/c/basura").status_code == 429


# --- modo prueba -----------------------------------------------------------------------------------------

def test_en_modo_prueba_compartir_por_link_es_409(cli):
    assert cli.put(f"/api/admin/users/{cli.otro_nombre}/sandbox", headers=cli.admin,
                   json={"active": True}).status_code == 200
    sid = cli.post("/api/sessions", headers=cli.otro, json={"title": "Prueba", "kind": "Breakout"}).json()["id"]
    r = cli.post(f"/api/sessions/{sid}/compartir", headers=cli.otro)
    assert r.status_code == 409 and "modo prueba" in r.json()["detail"]
    cli.put(f"/api/admin/users/{cli.otro_nombre}/sandbox", headers=cli.admin, json={"active": False})
