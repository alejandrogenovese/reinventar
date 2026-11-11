"""Importar las reservas del portal de AWS (.ics): lectura del calendario (pura) y alta en el itinerario como
reservadas, con un catálogo chico en memoria (corre en CI)."""
import pytest
from fastapi.testclient import TestClient

from app import catalog, db, reservas_aws
from app.main import app
from tests.conftest import TEST_ADMIN, TEST_ADMIN_PASSWORD, login_headers

DIA = "2026-12-01"


def _s(base, titulo, *instancias):
    return {"base": base, "title": titulo, "type": "Chalk talk", "level": "400", "topic": "", "aoi": "", "services": "",
            "tech": "", "concepts": "", "concepts_en": "", "focus": "", "speakers": "", "people": [],
            "abstract": "", "abstract_es": None, "newlaunch": False,
            "instances": [{"c": c, "d": d, "st": st, "v": "MGM Grand|Level 3", "seats": 100, "walk": True}
                          for c, d, st in instancias]}


CATALOGO = [
    _s("DAT406", "Build agentic GraphRAG apps with Amazon Neptune", ("DAT406-R", DIA, "10:00"), ("DAT406-R1", DIA, "14:00")),
    _s("SEC301", "Fine-grained access control for data lakes", ("SEC301", DIA, "09:00")),
    _s("ANT201", "Lakehouse governance", ("ANT201-R", DIA, "16:00")),
]


def _vevent(summary, dtstart, description="", extra=""):
    return f"BEGIN:VEVENT\r\nSUMMARY:{summary}\r\nDTSTART{dtstart}\r\nDESCRIPTION:{description}\r\n{extra}END:VEVENT\r\n"


def _ics(*eventos):
    return "BEGIN:VCALENDAR\r\nVERSION:2.0\r\n" + "".join(eventos) + "END:VCALENDAR\r\n"


# ---------- lectura (pura) ----------

def test_lee_eventos_con_hora_utc_o_con_zona_y_lineas_plegadas():
    texto = _ics(
        _vevent("DAT406-R | Build agentic GraphRAG apps", ":20261201T180000Z"),           # 10:00 en Las Vegas
        _vevent("Fine-grained access control for data lakes", ";TZID=America/Los_Angeles:20261201T090000",
                description="Session ID: SEC301\\nRoom: MGM Grand"),
        "BEGIN:VEVENT\r\nSUMMARY:Lakehouse gover\r\n nance\r\nDTSTART:20261202T000000Z\r\nEND:VEVENT\r\n",  # 16:00
    )

    eventos = reservas_aws.leer(texto)

    assert [(e.dia, e.hora) for e in eventos] == [(DIA, "10:00"), (DIA, "09:00"), (DIA, "16:00")]
    assert eventos[1].descripcion == "Session ID: SEC301\nRoom: MGM Grand"
    assert eventos[2].titulo == "Lakehouse governance"


def test_encuentra_por_codigo_de_horario_por_codigo_de_charla_o_por_titulo():
    catalog._sessions = CATALOGO
    try:
        exacto, base, titulo, nada = reservas_aws.leer(_ics(
            _vevent("DAT406-R1 | GraphRAG", ":20261201T220000Z"),                   # el código ya dice el horario
            _vevent("SEC301 - Fine-grained access control", ":20261201T170000Z"),   # código de charla + hora
            _vevent("Lakehouse governance", ":20261202T000000Z"),                   # solo título + hora
            _vevent("Cena con Datadog", ":20261202T030000Z"),
        ))

        assert reservas_aws.buscar(exacto)[1]["c"] == "DAT406-R1"
        assert reservas_aws.buscar(base)[1]["c"] == "SEC301"
        assert reservas_aws.buscar(titulo)[1]["c"] == "ANT201-R"
        assert reservas_aws.buscar(nada) is None
    finally:
        catalog._sessions = None


# ---------- importar (API) ----------

@pytest.fixture
def client(monkeypatch):
    with TestClient(app) as c:
        monkeypatch.setattr(catalog, "_sessions", CATALOGO)
        yield c


@pytest.fixture
def headers(client):
    h = login_headers(client, TEST_ADMIN, TEST_ADMIN_PASSWORD)
    yield {**h, "Content-Type": "text/calendar"}
    for it in db.list_itinerary_items(TEST_ADMIN):
        db.remove_item(TEST_ADMIN, it["code"])


def test_importa_las_reservas_marcadas_y_cambia_de_horario_si_ya_estaba(client, headers):
    client.post("/api/itinerary/items", headers={"Authorization": headers["Authorization"]}, json={"code": "DAT406-R"})
    texto = _ics(_vevent("DAT406-R1 | GraphRAG", ":20261201T220000Z"),
                 _vevent("SEC301 - Fine-grained access control", ":20261201T170000Z"),
                 _vevent("Cena con Datadog", ":20261202T030000Z"))

    r = client.post("/api/itinerary/import-ics", headers=headers, content=texto.encode())
    items = {it["code"]: it for it in db.list_itinerary_items(TEST_ADMIN)}

    assert r.status_code == 200, r.text
    assert r.json()["importadas"] == ["SEC301"]
    assert r.json()["cambiadas"] == [{"de": "DAT406-R", "a": "DAT406-R1"}]
    assert r.json()["sin_encontrar"] == ["Cena con Datadog"]
    assert set(items) == {"DAT406-R1", "SEC301"}
    assert all(it["reservada"] and it["locked"] for it in items.values())


def test_importar_dos_veces_no_duplica(client, headers):
    texto = _ics(_vevent("SEC301", ":20261201T170000Z")).encode()

    client.post("/api/itinerary/import-ics", headers=headers, content=texto)
    r = client.post("/api/itinerary/import-ics", headers=headers, content=texto)

    assert (r.json()["importadas"], r.json()["ya_estaban"]) == ([], ["SEC301"])
    assert len(db.list_itinerary_items(TEST_ADMIN)) == 1


def test_un_archivo_que_no_es_un_calendario_se_rechaza(client, headers):
    assert client.post("/api/itinerary/import-ics", headers=headers, content=b"hola").status_code == 422
    grande = b"BEGIN:VCALENDAR\r\n" + b"x" * (reservas_aws.MAX_BYTES + 1)
    assert client.post("/api/itinerary/import-ics", headers=headers, content=grande).status_code == 413
