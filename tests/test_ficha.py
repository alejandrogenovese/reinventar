"""«Mi ficha»: reglas puras de completitud (cada faltante aparece y desaparece, prioridades, silencio durante la estadía)
y GET /api/ficha (lee la base, sin contenido de documentos y con aislamiento entre usuarios)."""
import dataclasses
import datetime as dt
import time
import uuid

import pytest
from fastapi.testclient import TestClient

from app import db, estadia
from app import ficha as f
from app.main import app
from tests.conftest import TEST_ADMIN, TEST_ADMIN_PASSWORD, TEST_USER, login_headers

LV = estadia.TZ_VEGAS
COMPLETA = f.DatosFicha(perfil_completo=True, fechas_vuelos=("2026-11-29", "2026-12-07"), hoteles=1, documentos=2,
                        pendientes_hechos=10, pendientes_total=10, charlas=5, codigos_excel=0, passkeys=1)


def _ids(lista):
    return [x.id for x in lista]


# ---------- reglas puras ----------

def test_con_todo_cargado_no_falta_nada():
    assert f.faltantes(COMPLETA) == []


@pytest.mark.parametrize(("cambio", "id_", "texto"), [
    ({"fechas_vuelos": ("2026-12-07",)}, "vuelo_ida", "Cargá tu vuelo de ida"),
    ({"fechas_vuelos": ("2026-11-29",)}, "vuelo_vuelta", "Cargá tu vuelo de vuelta"),
    ({"hoteles": 0}, "hotel", "Cargá tu hotel"),
    ({"documentos": 0}, "documentos", "Subí tu pasaporte o ESTA"),
    ({"perfil_completo": False}, "perfil", "Completá tu perfil para recomendaciones"),
    ({"pendientes_hechos": 7}, "pendientes", "Te faltan 3 pendientes antes del viaje"),
    ({"pendientes_hechos": 9}, "pendientes", "Te falta 1 pendiente antes del viaje"),
    ({"pendientes_hechos": 0, "pendientes_total": 0}, "pendientes", "Revisá los pendientes del viaje"),
    ({"charlas": 0}, "agenda", "Armá tu agenda de charlas"),
    ({"passkeys": 0}, "passkey", "Entrá con huella o cara"),
])
def test_cada_faltante_aparece_y_desaparece_al_completarse(cambio, id_, texto):
    incompleta = dataclasses.replace(COMPLETA, **cambio)
    [faltante] = f.faltantes(incompleta)
    assert (faltante.id, faltante.texto) == (id_, texto)
    assert faltante.link.startswith("#/")
    assert f.faltantes(COMPLETA) == []


def test_la_agenda_cuenta_tambien_los_codigos_del_excel():
    assert f.faltantes(dataclasses.replace(COMPLETA, charlas=0, codigos_excel=12)) == []


def test_una_fecha_rota_no_cuenta_como_vuelo():
    assert _ids(f.faltantes(dataclasses.replace(COMPLETA, fechas_vuelos=("mañana",)))) == ["vuelo_ida", "vuelo_vuelta"]


def test_sin_nada_salen_todos_en_orden_de_prioridad():
    lista = f.faltantes(f.DatosFicha())
    assert _ids(lista) == ["vuelo_ida", "vuelo_vuelta", "hotel", "documentos", "perfil", "pendientes", "agenda", "passkey"]
    assert [x.prioridad for x in lista] == sorted(x.prioridad for x in lista)
    assert 4 not in [x.prioridad for x in lista], "el 4 es de las notificaciones, que decide el front"


def test_la_passkey_nunca_va_al_banner():
    solo_passkey = f.faltantes(dataclasses.replace(COMPLETA, passkeys=0))
    assert f.para_banner(solo_passkey, f.ANTES) == []


@pytest.mark.parametrize(("ahora", "fase"), [
    (dt.datetime(2026, 11, 23, 12, tzinfo=LV), f.ANTES),
    (dt.datetime(2026, 11, 28, 23, 59, tzinfo=LV), f.ANTES),
    (dt.datetime(2026, 11, 29, 0, 0, tzinfo=LV), f.DURANTE),
    (dt.datetime(2026, 12, 2, 10, tzinfo=LV), f.DURANTE),
    (dt.datetime(2026, 12, 7, 12, 59, tzinfo=LV), f.DURANTE),
    (dt.datetime(2026, 12, 7, 13, 0, tzinfo=LV), f.DESPUES),
])
def test_fase_segun_la_estadia(ahora, fase):
    assert f.fase(ahora) == fase


def test_antes_del_viaje_el_banner_avisa_todo_menos_la_passkey():
    lista = f.faltantes(f.DatosFicha())
    assert _ids(f.para_banner(lista, f.ANTES)) == _ids(lista)[:-1]


def test_durante_la_estadia_solo_avisa_lo_critico():
    lista = f.faltantes(f.DatosFicha())
    assert _ids(f.para_banner(lista, f.DURANTE)) == ["vuelo_vuelta"]
    # sin nada crítico pendiente, silencio total aunque falten cosas
    sin_vuelta = f.faltantes(dataclasses.replace(f.DatosFicha(), fechas_vuelos=("2026-12-06",)))
    assert f.para_banner(sin_vuelta, f.DURANTE) == []


def test_despues_del_viaje_no_avisa_nada():
    assert f.para_banner(f.faltantes(f.DatosFicha()), f.DESPUES) == []


# ---------- endpoint ----------

def _limpiar():
    usuarios = (TEST_USER, TEST_ADMIN)
    with db.conn() as c:
        for t in ("viajes_vuelos", "viajes_hoteles", "viajes_documentos", "viajes_pendientes", "itinerary_items",
                  "itinerary_profile", "codigos_deseados", "passkeys"):
            c.execute(f"DELETE FROM {t} WHERE username = ANY(%s)", (list(usuarios),))


@pytest.fixture
def cli():
    with TestClient(app) as c:
        c.H = login_headers(c)
        c.H2 = login_headers(c, TEST_ADMIN, TEST_ADMIN_PASSWORD)
        _limpiar()
        yield c
        _limpiar()


def _cargar_de_todo(username):
    ahora = time.time()
    with db.conn() as c:
        c.execute("INSERT INTO viajes_vuelos (username,id,numero,fecha,zona,creado) VALUES (%s,'v1','UA1355','2026-11-29',"
                  "'America/Argentina/Buenos_Aires',%s), (%s,'v2','UA1356','2026-12-07','America/Los_Angeles',%s)",
                  (username, ahora, username, ahora))
        c.execute("INSERT INTO viajes_hoteles (username,id,nombre,checkin,checkout,zona,creado) "
                  "VALUES (%s,'h1','Hotel de prueba','2026-11-29','2026-12-07','America/Los_Angeles',%s)", (username, ahora))
        c.execute("INSERT INTO viajes_documentos (username,id,tipo,titulo,notas,archivo_clave,archivo_tipo,bytes,sha256) "
                  "VALUES (%s,%s,'pasaporte','Pasaporte','nota secreta','clave/objeto','application/pdf',10,'x')",
                  (username, uuid.uuid4()))
        c.execute("INSERT INTO viajes_pendientes (username,id,texto,origen,hecho_en,creado) "
                  "VALUES (%s,'p1','Hecho','propio',now(),%s)", (username, ahora))
        c.execute("INSERT INTO itinerary_items (username,code,base,day,start,added_at) VALUES (%s,'ARC407','ARC407','Mon','10:00',%s)",
                  (username, ahora))
        c.execute("INSERT INTO passkeys (id,username,public_key,created_at) VALUES (%s,%s,%s,%s)",
                  (f"pk-{username}", username, b"k", ahora))
    db.save_profile(username, "Arquitecta de datos", "senior", ["Datos", "IA generativa"], "Ver novedades")


def test_sin_sesion_da_401():
    with TestClient(app) as c:
        assert c.get("/api/ficha").status_code == 401


def test_sin_nada_cargado_devuelve_todos_los_faltantes(cli):
    r = cli.get("/api/ficha", headers=cli.H)
    assert r.status_code == 200
    d = r.json()
    assert d["usuario"] == TEST_USER
    assert [x["id"] for x in d["faltantes"]] == ["vuelo_ida", "vuelo_vuelta", "hotel", "documentos", "perfil",
                                                 "pendientes", "agenda", "passkey"]
    assert d["fase"] in (f.ANTES, f.DURANTE, f.DESPUES)
    assert all(x["banner"] for x in d["banner"])


def test_con_todo_cargado_la_ficha_esta_completa_y_sin_contenido_de_documentos(cli):
    _cargar_de_todo(TEST_USER)
    d = cli.get("/api/ficha", headers=cli.H).json()
    assert d["faltantes"] == [] and d["banner"] == []
    assert d["perfil"] == {"completo": True, "rol": "Arquitecta de datos", "industria": None,
                           "intereses": ["Datos", "IA generativa"]}
    assert d["viaje"]["ida"] and d["viaje"]["vuelta"]
    assert [v["numero"] for v in d["viaje"]["vuelos"]] == ["UA1355", "UA1356"]
    assert d["viaje"]["hoteles"][0]["nombre"] == "Hotel de prueba"
    assert d["documentos"] == 1
    assert d["pendientes"] == {"hechos": 1, "total": 1}
    assert d["agenda"] == {"charlas": 1, "codigos_excel": 0}
    assert d["passkeys"] == 1
    texto = str(d)
    assert "nota secreta" not in texto and "clave/objeto" not in texto


def test_cada_usuario_ve_solo_lo_suyo(cli):
    _cargar_de_todo(TEST_USER)
    otro = cli.get("/api/ficha", headers=cli.H2).json()
    assert otro["usuario"] == TEST_ADMIN
    assert otro["viaje"]["vuelos"] == [] and otro["viaje"]["hoteles"] == []
    assert otro["documentos"] == 0 and otro["passkeys"] == 0
    assert otro["pendientes"] == {"hechos": 0, "total": 0}
    assert len(otro["faltantes"]) == 8


def test_la_ficha_de_la_entrevista_manda_sobre_el_armado_rapido():
    from app.ficha_api import _perfil

    p = {"role": "Dev", "interests": ["Lambda"], "respuestas": {"rol": {"texto": "Líder técnica", "industria": "banca"}},
         "ficha": {"industria": "banca", "prioridades": [{"tema": "Serverless", "peso": 3}]}}
    assert _perfil(p) == {"completo": True, "rol": "Líder técnica", "industria": "banca", "intereses": ["Serverless"]}
    assert _perfil(None)["completo"] is False
    assert _perfil({"role": "Dev", "interests": []})["completo"] is False


def test_armar_durante_la_estadia_solo_deja_el_vuelo_de_vuelta_en_el_banner(cli):
    from app.ficha_api import armar

    d = armar(TEST_USER, dt.datetime(2026, 12, 2, 10, tzinfo=LV))
    assert d["fase"] == f.DURANTE
    assert [x["id"] for x in d["banner"]] == ["vuelo_vuelta"]
    assert len(d["faltantes"]) == 8, "la ficha sigue mostrando todo lo que falta"


def test_armar_despues_del_viaje_no_deja_nada_en_el_banner(cli):
    from app.ficha_api import armar

    d = armar(TEST_USER, dt.datetime(2026, 12, 8, 10, tzinfo=LV))
    assert d["fase"] == f.DESPUES
    assert d["banner"] == []
