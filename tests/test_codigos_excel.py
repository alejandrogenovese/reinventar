"""Cruce de «mis códigos de sesión» con un Excel o CSV: lectura del archivo, cruce con el catálogo y el itinerario, y la API.
Usa un catálogo chico en memoria (no el schema reinvent): corre en CI. Los archivos se generan acá, no hay binarios."""
import io
import threading
import time
import tracemalloc
import zipfile

import openpyxl
import pytest
from fastapi.testclient import TestClient

from app import catalog, codigos_api, codigos_excel, db
from app.codigos_excel import ArchivoInvalido, Codigo, cruzar, extraer_codigos, normalizar
from app.main import app
from tests.conftest import TEST_ADMIN, TEST_ADMIN_PASSWORD, TEST_USER, login_headers

LUN, MAR, MIE = "2026-11-30", "2026-12-01", "2026-12-02"


def _s(base, titulo, tipo, *instancias):
    """instancias: (código, día, inicio, fin[, cancelada])"""
    return {"base": base, "title": titulo, "type": tipo,
            "instances": [{"c": c, "d": d, "st": st, "en": en, "v": "Venetian|Hall A", "cancelada": bool(rest and rest[0])}
                          for c, d, st, en, *rest in instancias]}


CATALOGO = [
    _s("KEY001", "Keynote con el CEO", "Keynote", ("KEY001", MAR, "08:00", "09:30")),
    _s("AIM301", "Agentes con Bedrock", "Breakout session", ("AIM301", MAR, "10:00", "11:00")),
    _s("SEC201", "Seguridad para agentes", "Chalk talk", ("SEC201", MAR, "10:30", "11:30")),
    _s("DAT402", "Aurora DSQL a fondo", "Breakout session",
       ("DAT402", MAR, "10:30", "11:30"), ("DAT402-R", MIE, "10:30", "11:30")),
    _s("ARC407", "Arquitecturas resilientes", "Chalk talk", ("ARC407", MIE, "14:00", "15:00")),
    _s("NET305", "Redes en la nube", "Workshop",
       ("NET305", MAR, "13:00", "15:00", True), ("NET305-R", MIE, "13:00", "15:00")),
]
POR_BASE = {s["base"]: s for s in CATALOGO}


def _xlsx(*hojas):
    """hojas: lista de (nombre, filas); devuelve los bytes de un .xlsx."""
    libro = openpyxl.Workbook()
    libro.remove(libro.active)
    for nombre, filas in hojas:
        hoja = libro.create_sheet(nombre)
        for fila in filas:
            hoja.append(list(fila))
    salida = io.BytesIO()
    libro.save(salida)
    return salida.getvalue()


def _bases(codigos):
    return [c.base for c in codigos]


# ---------- normalizar ----------

def test_normaliza_mayusculas_espacios_y_guiones_raros():
    assert normalizar("aim301") == [Codigo("AIM301", "AIM301")]
    assert normalizar("dat 402–r") == [Codigo("DAT402", "DAT402-R")]
    assert normalizar("  KEY001  ") == [Codigo("KEY001", "KEY001")]


def test_las_repeticiones_r_y_r1_son_el_mismo_codigo_base_y_conservan_el_sufijo():
    codigos = normalizar("AIM301-R, aim301-r1 y AIM301")
    assert [c.base for c in codigos] == ["AIM301"] * 3
    assert [c.completo for c in codigos] == ["AIM301-R", "AIM301-R1", "AIM301"]


@pytest.mark.parametrize(("texto", "base"), [("AIM121-S", "AIM121-S"), ("svc003-d0", "SVC003-D0"),
                                             ("AIM2205-SC2", "AIM2205-SC2")])
def test_los_otros_sufijos_son_parte_del_codigo_de_la_charla(texto, base):
    # En el catálogo, -S (sponsoreada), -D0 o -SC2 nombran otra charla: solo -R y -R<n> son repeticiones.
    assert normalizar(texto) == [Codigo(base, base)]


@pytest.mark.parametrize(("texto", "esperado"), [("IND3313", Codigo("IND3313", "IND3313")),
                                                 ("ind 3343", Codigo("IND3343", "IND3343")),
                                                 ("AIM2201-S", Codigo("AIM2201-S", "AIM2201-S")),
                                                 ("SEC4290-R1", Codigo("SEC4290", "SEC4290-R1"))])
def test_reconoce_codigos_de_cuatro_digitos(texto, esperado):
    assert normalizar(texto) == [esperado]


def test_encuentra_codigos_sueltos_dentro_de_un_texto():
    assert _bases(normalizar("Quiero ir a (AIM301), después SEC201-R; y nada de XX12")) == ["AIM301", "SEC201"]


def test_no_toma_pedazos_de_palabras_ni_numeros_largos():
    assert normalizar("ABCD1234 y 12345 y AIM30123 y xAIM301x") == []


# ---------- extraer_codigos ----------

def test_detecta_la_columna_de_codigos_con_encabezados_raros_y_celdas_vacias():
    datos = _xlsx(("Hoja 1", [
        ("N°", "Qué quiero ver (¡ojo!)", "Notas"),
        (1, "AIM301", "AIM sin número"),
        (2, None, "ver después"),
        (3, "dat402-r", None),
        (4, "", "KEY"),
        (5, "KEY001", "importante"),
    ]))
    assert _bases(extraer_codigos(datos, "lista.xlsx")) == ["AIM301", "DAT402", "KEY001"]


def test_elige_la_columna_con_mas_codigos_en_cualquier_hoja():
    datos = _xlsx(
        ("Resumen", [("Código",), ("AIM301",)]),
        ("Todo", [("Cod", "Otra"), ("KEY001", "AIM301"), ("SEC201", None), ("ARC407", None)]))
    assert _bases(extraer_codigos(datos, "lista.xlsx")) == ["KEY001", "SEC201", "ARC407"]


def test_no_duplica_el_mismo_codigo_base_aunque_cambie_el_sufijo():
    datos = _xlsx(("H", [("AIM301",), ("aim301",), ("DAT402",), ("DAT402-R",)]))
    assert [c.completo for c in extraer_codigos(datos, "x.xlsx")] == ["AIM301", "DAT402"]


def test_no_evalua_formulas():
    libro = openpyxl.Workbook()
    hoja = libro.active
    hoja.append(["KEY001"])
    hoja.append(['="AIM"&"301"'])
    salida = io.BytesIO()
    libro.save(salida)
    assert _bases(extraer_codigos(salida.getvalue(), "f.xlsx")) == ["KEY001"]


def test_lee_csv_con_coma_punto_y_coma_y_bom():
    assert _bases(extraer_codigos("Código,Nota\nAIM301,uno\nKEY001,dos\n".encode(), "a.csv")) == ["AIM301", "KEY001"]
    assert _bases(extraer_codigos("Nota;Código\nuno;aim301\ndos;ARC407\n".encode("utf-8-sig"), "a.csv")) == ["AIM301", "ARC407"]


def test_csv_en_latin1_no_rompe():
    assert _bases(extraer_codigos("Código;Título\nAIM301;Sesión\n".encode("latin-1"), "a.csv")) == ["AIM301"]


@pytest.mark.parametrize("datos, nombre", [
    (b"", "vacio.xlsx"),
    (b"", "vacio.csv"),
    (b"esto no es un excel", "falso.xlsx"),
    (b"PK\x03\x04basura que no es un zip valido", "roto.xlsx"),
    (b"AIM301\n", "lista.txt"),
    (b"AIM301\n", "lista"),
    (b"PK\x03\x04" + b"\x00" * 50, "binario.csv"),
    (b"nombre,nota\nuno,dos\n", "sin_codigos.csv"),
    (_xlsx(("H", [("sin", "codigos"), ("nada", "aca")])), "sin_codigos.xlsx"),
], ids=["xlsx vacío", "csv vacío", "no es Excel", "zip roto", "extensión .txt", "sin extensión", "csv binario",
        "csv sin códigos", "xlsx sin códigos"])
def test_rechaza_archivos_que_no_sirven(datos, nombre):
    with pytest.raises(ArchivoInvalido):
        extraer_codigos(datos, nombre)


def test_rechaza_xlsm_porque_puede_traer_macros():
    with pytest.raises(ArchivoInvalido):
        extraer_codigos(_xlsx(("H", [("AIM301",)])), "macros.xlsm")


def test_rechaza_lo_que_pasa_del_tope_de_bytes():
    with pytest.raises(ArchivoInvalido, match="grande"):
        extraer_codigos(b"AIM301\n" * (codigos_excel.MAX_BYTES // 7 + 10), "grande.csv")


def test_rechaza_demasiadas_filas_y_demasiados_codigos(monkeypatch):
    monkeypatch.setattr(codigos_excel, "MAX_FILAS", 5)
    with pytest.raises(ArchivoInvalido, match="filas"):
        extraer_codigos(b"AIM301\n" * 6, "filas.csv")
    monkeypatch.setattr(codigos_excel, "MAX_FILAS", 5000)
    monkeypatch.setattr(codigos_excel, "MAX_CODIGOS", 2)
    with pytest.raises(ArchivoInvalido, match="códigos"):
        extraer_codigos(b"AIM301\nSEC201\nKEY001\n", "codigos.csv")


# ---------- cruzar ----------

def _cruce(deseados, registrados=()):
    return cruzar([Codigo(c[:6], c) for c in deseados], POR_BASE,
                  [{"code": c, "base": c[:6]} for c in registrados])


def _por_base(resultado):
    return {e["base"]: e for e in resultado["codigos"]}


def test_registrado_cuando_esta_en_el_itinerario_reservado():
    r = _cruce(["KEY001"], registrados=["KEY001"])
    e = _por_base(r)["KEY001"]
    assert e["estado"] == "registrado"
    assert (e["titulo"], e["dia"], e["inicio"]) == ("Keynote con el CEO", MAR, "08:00")
    assert r["resumen"]["registrados"] == 1


def test_falta_cuando_lo_quiero_y_no_lo_registre():
    r = _cruce(["ARC407"])
    assert _por_base(r)["ARC407"]["estado"] == "falta"
    assert r["resumen"]["faltan"] == 1


def test_inexistente_cuando_el_codigo_no_esta_en_el_catalogo():
    r = _cruce(["ZZZ999"])
    e = _por_base(r)["ZZZ999"]
    assert e["estado"] == "inexistente"
    assert e["titulo"] is None
    assert r["resumen"]["inexistentes"] == 1


def test_de_mas_es_lo_registrado_que_no_esta_en_el_excel():
    r = _cruce(["KEY001"], registrados=["KEY001", "ARC407"])
    assert [d["base"] for d in r["de_mas"]] == ["ARC407"]
    assert r["de_mas"][0]["titulo"] == "Arquitecturas resilientes"
    assert r["resumen"]["de_mas"] == 1


def test_choque_entre_dos_que_quiero_se_marca_en_los_dos():
    r = _cruce(["AIM301", "SEC201"])
    por = _por_base(r)
    assert por["AIM301"]["choca_con"] == ["SEC201"]
    assert por["SEC201"]["choca_con"] == ["AIM301"]
    assert r["resumen"]["choques"] == 2
    assert por["AIM301"]["estado"] == "falta"  # el choque no reemplaza el estado


def test_horarios_pegados_no_chocan():
    catalogo = {"AAA111": _s("AAA111", "a", "Chalk talk", ("AAA111", MAR, "10:00", "11:00")),
                "BBB222": _s("BBB222", "b", "Chalk talk", ("BBB222", MAR, "11:00", "12:00"))}
    r = cruzar([Codigo("AAA111", "AAA111"), Codigo("BBB222", "BBB222")], catalogo, [])
    assert r["resumen"]["choques"] == 0


def test_no_hay_choque_si_alguna_repeticion_lo_evita():
    # DAT402 también tiene una repetición el miércoles, que no pisa a AIM301
    r = _cruce(["AIM301", "DAT402"])
    assert r["resumen"]["choques"] == 0


def test_si_ya_registre_un_horario_el_choque_se_calcula_con_ese():
    r = _cruce(["AIM301", "DAT402"], registrados=["DAT402"])  # registrado el del martes 10:30: pisa a AIM301
    por = _por_base(r)
    assert por["AIM301"]["choca_con"] == ["DAT402"]
    assert por["DAT402"]["estado"] == "registrado"


def test_el_sufijo_cuenta_como_el_mismo_codigo_pero_se_conserva_para_mostrar():
    r = cruzar([Codigo("DAT402", "DAT402-R")], POR_BASE, [{"code": "DAT402", "base": "DAT402"}])
    e = r["codigos"][0]
    assert (e["codigo"], e["estado"]) == ("DAT402-R", "registrado")
    sin = cruzar([Codigo("DAT402", "DAT402-R")], POR_BASE, [])
    assert (sin["codigos"][0]["dia"], sin["codigos"][0]["inicio"]) == (MIE, "10:30")  # el horario de la repetición pedida


def test_ignora_los_horarios_cancelados_al_elegir_cual_mostrar():
    r = _cruce(["NET305"])
    assert r["codigos"][0]["dia"] == MIE


def test_el_resultado_no_cambia_lo_que_recibe():
    deseados = [Codigo("AIM301", "AIM301")]
    registrados = [{"code": "KEY001", "base": "KEY001"}]
    cruzar(deseados, POR_BASE, registrados)
    assert deseados == [Codigo("AIM301", "AIM301")] and registrados == [{"code": "KEY001", "base": "KEY001"}]


# ---------- API ----------

@pytest.fixture
def client(monkeypatch):
    with TestClient(app) as c:
        monkeypatch.setattr(catalog, "_sessions", CATALOGO)
        with db.conn() as con:  # la base se comparte entre tests: cada uno arranca sin lista ni itinerario
            for tabla in ("codigos_deseados", "itinerary_items"):
                con.execute(f"DELETE FROM {tabla} WHERE username = ANY(%s)", ([TEST_USER, TEST_ADMIN],))
        yield c


@pytest.fixture
def H(client):
    return login_headers(client)


def _subir(client, H, contenido, nombre="lista.csv"):
    return client.post("/api/codigos", params={"nombre": nombre}, headers=H, content=contenido)


def _filas_guardadas(username):
    with db.conn() as c:
        return c.execute("SELECT codigo FROM codigos_deseados WHERE username=%s ORDER BY orden", (username,)).fetchall()


def test_la_api_pide_sesion(client):
    assert client.get("/api/codigos").status_code == 401
    assert client.post("/api/codigos", content=b"AIM301").status_code == 401
    assert client.delete("/api/codigos").status_code == 401


def test_sin_lista_el_get_lo_dice(client, H):
    client.delete("/api/codigos", headers=H)
    assert client.get("/api/codigos", headers=H).json() == {"lista": False}


def test_subir_cruza_y_el_get_devuelve_lo_mismo(client, H):
    db.add_item("tester", "KEY001", "KEY001", MAR, "08:00")
    db.set_item_booked("tester", "KEY001", True)
    r = _subir(client, H, b"Codigo\nKEY001\nARC407\nZZZ999\n")
    assert r.status_code == 200, r.text
    estados = {e["base"]: e["estado"] for e in r.json()["codigos"]}
    assert estados == {"KEY001": "registrado", "ARC407": "falta", "ZZZ999": "inexistente"}
    subida = {k: v for k, v in r.json().items() if k != "codigos_descartados"}  # el aviso de descartados es solo de la subida
    assert client.get("/api/codigos", headers=H).json() == subida
    assert r.json()["codigos_descartados"] == []


def test_volver_a_subir_reemplaza_la_lista_sin_duplicar(client, H):
    _subir(client, H, b"AIM301\nSEC201\nKEY001\n")
    r = _subir(client, H, b"ARC407\nKEY001\n")
    assert [e["base"] for e in r.json()["codigos"]] == ["ARC407", "KEY001"]
    assert [f["codigo"] for f in _filas_guardadas("tester")] == ["ARC407", "KEY001"]
    _subir(client, H, b"ARC407\nKEY001\n")
    assert len(_filas_guardadas("tester")) == 2


def test_borrar_deja_al_usuario_sin_lista(client, H):
    _subir(client, H, b"AIM301\n")
    assert client.delete("/api/codigos", headers=H).status_code == 200
    assert client.get("/api/codigos", headers=H).json() == {"lista": False}
    assert _filas_guardadas("tester") == []


def test_la_lista_de_cada_usuario_es_aislada(client, H):
    otro = login_headers(client, TEST_ADMIN, TEST_ADMIN_PASSWORD)
    _subir(client, H, b"AIM301\nKEY001\n")
    assert client.get("/api/codigos", headers=otro).json() == {"lista": False}
    _subir(client, otro, b"ARC407\n")
    assert [e["base"] for e in client.get("/api/codigos", headers=H).json()["codigos"]] == ["AIM301", "KEY001"]
    client.delete("/api/codigos", headers=otro)
    assert [e["base"] for e in client.get("/api/codigos", headers=H).json()["codigos"]] == ["AIM301", "KEY001"]


def test_el_registrado_de_uno_no_aparece_en_la_lista_de_otro(client, H):
    otro = login_headers(client, TEST_ADMIN, TEST_ADMIN_PASSWORD)
    db.add_item(TEST_ADMIN, "ARC407", "ARC407", MIE, "14:00")
    db.set_item_booked(TEST_ADMIN, "ARC407", True)
    r = _subir(client, H, b"ARC407\n")
    assert r.json()["codigos"][0]["estado"] == "falta"
    assert r.json()["de_mas"] == []
    assert client.get("/api/codigos", headers=otro).json() == {"lista": False}


def test_lo_que_esta_en_el_itinerario_sin_reservar_no_cuenta_como_registrado(client, H):
    db.add_item("tester", "SEC201", "SEC201", MAR, "10:30")
    r = _subir(client, H, b"SEC201\n")
    assert r.json()["codigos"][0]["estado"] == "falta"
    assert r.json()["de_mas"] == []


@pytest.mark.parametrize("contenido, nombre, status", [
    (b"", "vacio.csv", 422),
    (b"esto no es un excel", "falso.xlsx", 422),
    (b"AIM301\n", "lista.pdf", 422),
    (b"hola,mundo\n", "sin_codigos.csv", 422),
    (b"A" * (codigos_excel.MAX_BYTES + 1), "grande.csv", 413),
])
def test_archivos_invalidos_devuelven_error_claro_y_no_pisan_la_lista(client, H, contenido, nombre, status):
    _subir(client, H, b"AIM301\n")
    r = _subir(client, H, contenido, nombre)
    assert r.status_code == status
    assert isinstance(r.json()["detail"], str) and r.json()["detail"]
    assert [f["codigo"] for f in _filas_guardadas("tester")] == ["AIM301"]


def test_subir_un_xlsx_de_verdad(client, H):
    r = _subir(client, H, _xlsx(("Hoja", [("Código", "Nota"), ("aim301", "x"), (None, None), ("ARC407-R", "y")])), "lista.xlsx")
    assert r.status_code == 200, r.text
    assert [(e["codigo"], e["base"]) for e in r.json()["codigos"]] == [("AIM301", "AIM301"), ("ARC407-R", "ARC407")]


# ---------- archivos armados a propósito ----------

def _xlsx_ancho_declarado(filas=5000):
    """Un .xlsx chico que declara A1:XFD<filas> y trae una sola celda por fila: openpyxl (solo lectura) rellena cada fila
    hasta el ancho declarado, así que sin tope ocupa cientos de MB."""
    ns = "http://schemas.openxmlformats.org/"
    celdas = "".join(f'<row r="{i}"><c r="A{i}" t="inlineStr"><is><t>x</t></is></c></row>' for i in range(1, filas + 1))
    hoja = (f'<?xml version="1.0"?><worksheet xmlns="{ns}spreadsheetml/2006/main"><dimension ref="A1:XFD{filas}"/>'
            f"<sheetData>{celdas}</sheetData></worksheet>")
    libro = (f'<?xml version="1.0"?><workbook xmlns="{ns}spreadsheetml/2006/main" xmlns:r="{ns}officeDocument/2006/relationships">'
             '<sheets><sheet name="a" sheetId="1" r:id="rId1"/></sheets></workbook>')
    rel_libro = (f'<?xml version="1.0"?><Relationships xmlns="{ns}package/2006/relationships"><Relationship Id="rId1" '
                 f'Type="{ns}officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>')
    tipos = (f'<?xml version="1.0"?><Types xmlns="{ns}package/2006/content-types"><Default Extension="xml" ContentType="application/xml"/>'
             '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
             '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
             '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>')
    rel_raiz = (f'<?xml version="1.0"?><Relationships xmlns="{ns}package/2006/relationships"><Relationship Id="rId1" '
                f'Type="{ns}officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
    salida = io.BytesIO()
    with zipfile.ZipFile(salida, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", tipos)
        z.writestr("_rels/.rels", rel_raiz)
        z.writestr("xl/workbook.xml", libro)
        z.writestr("xl/_rels/workbook.xml.rels", rel_libro)
        z.writestr("xl/worksheets/sheet1.xml", hoja)
    return salida.getvalue()


def test_un_xlsx_que_declara_un_ancho_enorme_se_corta_rapido_y_con_poca_memoria():
    datos = _xlsx_ancho_declarado()
    assert len(datos) < 100 * 1024
    tracemalloc.start()
    inicio = time.monotonic()
    try:
        with pytest.raises(ArchivoInvalido):
            extraer_codigos(datos, "malicioso.xlsx")  # no tiene códigos: lo que importa es que no explote
        _, pico = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert pico < 60 * 1024 * 1024, f"pico de {pico / 1e6:.0f} MB"
    assert time.monotonic() - inicio < 10


def test_rechaza_un_libro_con_demasiadas_hojas():
    hojas = [(f"h{i}", [("AIM301",)]) for i in range(codigos_excel.MAX_HOJAS + 1)]
    with pytest.raises(ArchivoInvalido, match="hojas"):
        extraer_codigos(_xlsx(*hojas), "hojas.xlsx")


def test_rechaza_un_libro_con_demasiadas_celdas(monkeypatch):
    monkeypatch.setattr(codigos_excel, "MAX_CELDAS", 20)
    with pytest.raises(ArchivoInvalido, match="celdas"):
        extraer_codigos(_xlsx(("H", [("AIM301", "a", "b", "c")] * 6)), "celdas.xlsx")


def test_las_columnas_de_mas_de_50_no_se_leen():
    fila = [None] * codigos_excel.MAX_COLUMNAS + ["AIM301"]
    with pytest.raises(ArchivoInvalido, match="códigos"):
        extraer_codigos(_xlsx(("H", [fila])), "ancho.xlsx")


def test_un_csv_con_un_campo_enorme_es_un_archivo_invalido():
    with pytest.raises(ArchivoInvalido, match="CSV"):
        extraer_codigos(b"AIM301," + b"a" * 200_000 + b"\n", "campo.csv")


# ---------- códigos que se descartan ----------

def test_informa_los_codigos_de_las_columnas_que_no_se_eligieron():
    filas = [("AIM301", "SEC201"), ("DAT402", "KEY001"), ("ARC407", None)]
    lectura = codigos_excel.leer_codigos(_xlsx(("H", filas)), "dos.xlsx")
    assert _bases(lectura.codigos) == ["AIM301", "DAT402", "ARC407"]
    assert _bases(lectura.descartados) == ["SEC201", "KEY001"]


def test_informa_los_codigos_de_otra_hoja_y_no_repite_los_que_si_entraron():
    hojas = [("A", [("AIM301",), ("DAT402",)]), ("B", [("DAT402",), ("SEC201",)])]
    lectura = codigos_excel.leer_codigos(_xlsx(*hojas), "hojas.xlsx")
    assert _bases(lectura.codigos) == ["AIM301", "DAT402"]
    assert _bases(lectura.descartados) == ["SEC201"]


def test_sin_columnas_de_mas_no_hay_descartados():
    assert codigos_excel.leer_codigos(b"AIM301\nSEC201\n", "l.csv").descartados == []


# ---------- API: límites y concurrencia ----------

@pytest.fixture(autouse=True)
def _cupo_de_subidas_limpio():
    codigos_api._subidas.reiniciar()
    yield


def test_la_api_devuelve_los_descartados_al_subir(client, H):
    r = _subir(client, H, b"AIM301;SEC201\nDAT402;KEY001\n", "dos.csv")
    assert r.status_code == 200, r.text
    assert r.json()["codigos_descartados"] == ["SEC201", "KEY001"]


def test_un_csv_con_un_campo_enorme_da_422_y_no_500(client, H):
    r = _subir(client, H, b"AIM301," + b"a" * 200_000 + b"\n", "campo.csv")
    assert r.status_code == 422


def test_solo_se_pueden_subir_diez_listas_por_hora(client, H):
    for _ in range(codigos_api.SUBIDAS_POR_HORA):
        assert _subir(client, H, b"AIM301\n").status_code == 200
    r = _subir(client, H, b"AIM301\n")
    assert r.status_code == 429
    assert "muchos pedidos" in r.json()["detail"]


def test_el_cupo_de_subidas_es_por_usuario(client, H):
    for _ in range(codigos_api.SUBIDAS_POR_HORA):
        _subir(client, H, b"AIM301\n")
    otro = login_headers(client, TEST_ADMIN, TEST_ADMIN_PASSWORD)
    assert _subir(client, otro, b"AIM301\n").status_code == 200


def test_dos_subidas_simultaneas_no_chocan_por_la_clave_primaria(client):
    codigos = [Codigo("AIM301", "AIM301"), Codigo("SEC201", "SEC201"), Codigo("KEY001", "KEY001")]
    errores, arranque = [], threading.Barrier(6)

    def subir():
        try:
            arranque.wait()
            codigos_api._guardar(TEST_USER, codigos, "x.csv")
        except Exception as e:  # noqa: BLE001 - se junta para verificar abajo
            errores.append(e)

    hilos = [threading.Thread(target=subir) for _ in range(6)]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join()
    assert errores == []
    assert [f["codigo"] for f in _filas_guardadas(TEST_USER)] == ["AIM301", "SEC201", "KEY001"]


# ---------- agregar al itinerario ----------

def _bases_en_itinerario(username):
    return {it["base"]: it for it in db.list_itinerary_items(username)}


def test_agregar_al_itinerario_suma_las_que_faltan_y_no_toca_las_que_ya_estaban(client, H):
    db.add_item("tester", "KEY001", "KEY001", MAR, "08:00")
    db.set_item_booked("tester", "KEY001", True)
    _subir(client, H, b"KEY001\nARC407\nDAT402-R\nZZZ999\n")

    r = client.post("/api/codigos/al-itinerario", headers=H)

    assert r.status_code == 200, r.text
    assert r.json()["agregadas"] == 2
    items = _bases_en_itinerario("tester")
    assert set(items) == {"KEY001", "ARC407", "DAT402"}
    assert items["DAT402"]["code"] == "DAT402-R"  # el horario de la repetición que pidió
    assert items["KEY001"]["reservada"]  # la que ya estaba sigue marcada como reservada
    assert all(e["en_itinerario"] for e in r.json()["codigos"] if e["estado"] != "inexistente")
    assert r.json()["resumen"]["para_agregar"] == 0


def test_el_cruce_dice_cuales_estan_en_el_itinerario(client, H):
    db.add_item("tester", "KEY001", "KEY001", MAR, "08:00")
    r = _subir(client, H, b"KEY001\nARC407\nZZZ999\n").json()

    assert {e["base"]: e["en_itinerario"] for e in r["codigos"]} == {"KEY001": True, "ARC407": False, "ZZZ999": False}
    assert r["resumen"]["para_agregar"] == 1


def test_agregar_dos_veces_no_duplica(client, H):
    _subir(client, H, b"ARC407\n")
    client.post("/api/codigos/al-itinerario", headers=H)

    r = client.post("/api/codigos/al-itinerario", headers=H)

    assert r.json()["agregadas"] == 0
    assert [it["base"] for it in db.list_itinerary_items("tester")] == ["ARC407"]


def test_agregar_sin_lista_da_404_y_pide_sesion(client, H):
    client.delete("/api/codigos", headers=H)
    assert client.post("/api/codigos/al-itinerario", headers=H).status_code == 404
    assert client.post("/api/codigos/al-itinerario").status_code == 401
