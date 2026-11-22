"""El Excel de ejemplo de «Cruzar con mi Excel» (app/codigos_ejemplo.py y GET /api/codigos/ejemplo.xlsx): se baja, se
completa y se sube. Lo que importa es la ida y vuelta: el propio ejemplo, subido tal cual, lo lee app/codigos_excel.py."""
import io

import openpyxl
import pytest
from fastapi.testclient import TestClient

from app import codigos_ejemplo, codigos_excel
from app.main import app
from tests.conftest import login_headers

MIME_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _libro(datos: bytes):
    return openpyxl.load_workbook(io.BytesIO(datos))


def _con_codigos(codigos: list[str]) -> bytes:
    """El ejemplo con la columna Código reemplazada, como lo completaría la persona."""
    libro = _libro(codigos_ejemplo.generar())
    hoja = libro[codigos_ejemplo.HOJA_CODIGOS]
    hoja.delete_rows(2, hoja.max_row)
    for codigo in codigos:
        hoja.append([codigo])
    salida = io.BytesIO()
    libro.save(salida)
    return salida.getvalue()


def test_el_ejemplo_tiene_la_hoja_de_codigos_primero_y_las_instrucciones_aparte():
    libro = _libro(codigos_ejemplo.generar())
    assert libro.sheetnames == [codigos_ejemplo.HOJA_CODIGOS, codigos_ejemplo.HOJA_INSTRUCCIONES]
    assert libro.active.title == codigos_ejemplo.HOJA_CODIGOS
    cabecera = [c.value for c in libro[codigos_ejemplo.HOJA_CODIGOS][1]]
    assert cabecera == list(codigos_ejemplo.CABECERA)


def test_el_ejemplo_subido_tal_cual_devuelve_sus_codigos_sin_descartes():
    lectura = codigos_excel.leer_codigos(codigos_ejemplo.generar(), codigos_ejemplo.NOMBRE)
    assert [c.completo for c in lectura.codigos] == [fila[0] for fila in codigos_ejemplo.FILAS]
    assert lectura.descartados == []


def test_las_instrucciones_y_los_titulos_no_aportan_codigos_cuando_la_persona_pone_los_suyos():
    lectura = codigos_excel.leer_codigos(_con_codigos(["SEC201", "ARC407-R1"]), "mis-charlas.xlsx")
    assert [c.completo for c in lectura.codigos] == ["SEC201", "ARC407-R1"]
    assert lectura.descartados == []  # ni la hoja de instrucciones ni las otras columnas meten códigos de ejemplo


def test_los_codigos_de_ejemplo_tienen_formato_real():
    for codigo, *_ in codigos_ejemplo.FILAS:
        assert [c.completo for c in codigos_excel.normalizar(codigo)] == [codigo]


# ---------- API ----------

@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def test_el_ejemplo_pide_sesion(client):
    assert client.get("/api/codigos/ejemplo.xlsx").status_code == 401


def test_el_ejemplo_se_baja_como_xlsx_adjunto_y_se_puede_volver_a_subir(client):
    r = client.get("/api/codigos/ejemplo.xlsx", headers=login_headers(client))
    assert r.status_code == 200
    assert r.headers["content-type"] == MIME_XLSX
    assert r.headers["content-disposition"] == f'attachment; filename="{codigos_ejemplo.NOMBRE}"'
    lectura = codigos_excel.leer_codigos(r.content, codigos_ejemplo.NOMBRE)
    assert [c.completo for c in lectura.codigos] == [fila[0] for fila in codigos_ejemplo.FILAS]
