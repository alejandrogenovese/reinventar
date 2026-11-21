"""Arranque de la base: idempotente, sin locks fuertes de más, y con las tablas globales solo en el schema real."""
import datetime as dt

import pytest
from fastapi.testclient import TestClient

from app import config, db, ofertas, pg, sandbox
from app.main import app

GLOBALES = ("oferta", "precio_snapshot", "oferta_job", "cotizaciones")
# Una columna agregada por ALTER en cada tabla que los tiene: tabla -> columna
COLUMNAS_AGREGADAS = (("sessions", "client_id"), ("itinerary_items", "reservada"), ("itinerary_profile", "ficha_texto"),
                      ("preferencias_avisos", "ofertas_categorias"), ("gastos", "foto_at"))


@pytest.fixture(scope="module", autouse=True)
def _base_inicializada():
    with TestClient(app):  # el lifespan corre db.init()
        yield


def _tablas(schema: str) -> set[str]:
    with sandbox.real(), db.conn() as c:
        return {r["table_name"] for r in c.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = %s", (schema,)).fetchall()}


def _columnas(schema: str, tabla: str) -> set[str]:
    with sandbox.real(), db.conn() as c:
        return {r["column_name"] for r in c.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_schema = %s AND table_name = %s",
            (schema, tabla)).fetchall()}


def test_init_dos_veces_seguidas_no_falla_y_deja_las_columnas():
    db.init()
    db.init()

    for schema in (config.DB_SCHEMA, sandbox.schema_prueba()):
        for tabla, columna in COLUMNAS_AGREGADAS:
            assert columna in _columnas(schema, tabla), (schema, tabla, columna)
    assert {"must_change_password", "modo_prueba", "prueba"} <= _columnas(config.DB_SCHEMA, "users")


def test_las_tablas_globales_estan_en_el_schema_real_y_no_en_el_de_prueba():
    real, prueba = _tablas(config.DB_SCHEMA), _tablas(sandbox.schema_prueba())

    for tabla in GLOBALES:
        assert tabla in real
        assert tabla not in prueba
    assert "sessions" in prueba  # las de datos del usuario siguen en los dos


def test_cotizaciones_no_es_una_tabla_de_datos_del_usuario():
    assert "cotizaciones" not in db.tablas_datos_usuario()
    assert db.borrar_datos_prueba() >= 0  # vaciar el schema de prueba no busca tablas que no tiene


class _Espia:
    """Conexión que anota cada consulta que se ejecuta."""

    def __init__(self, c):
        self._c, self.consultas = c, []

    def execute(self, consulta, *args, **kwargs):
        self.consultas.append(str(consulta))
        return self._c.execute(consulta, *args, **kwargs)


def test_no_hace_alter_si_las_columnas_ya_existen():
    with sandbox.real(), db.conn() as c:
        espia = _Espia(c)
        db._agregar_columnas(espia, db.COLUMNAS_DATOS_USUARIO + db.COLUMNAS_CUENTAS)

    assert not [q for q in espia.consultas if q.lstrip().upper().startswith("ALTER")]


def test_agrega_solo_la_columna_que_falta():
    with sandbox.real(), db.conn() as c:
        c.execute(f"ALTER TABLE {config.DB_SCHEMA}.gastos DROP COLUMN foto_at")
        espia = _Espia(c)
        db._agregar_columnas(espia, db.COLUMNAS_DATOS_USUARIO)
        alters = [q for q in espia.consultas if q.lstrip().upper().startswith("ALTER")]

    assert len(alters) == 1 and "foto_at" in alters[0]
    assert "foto_at" in _columnas(config.DB_SCHEMA, "gastos")


def test_el_init_toma_un_advisory_lock_y_pone_lock_timeout():
    with sandbox.real(), db.conn() as c:
        db._preparar_init(c)
        timeout = c.execute("SHOW lock_timeout").fetchone()["lock_timeout"]
        locks = c.execute("SELECT count(*) AS n FROM pg_locks WHERE locktype = 'advisory' AND pid = pg_backend_pid()"
                          ).fetchone()["n"]

    assert timeout == "5s"
    assert locks >= 1


def _contar(schema: str, tabla: str) -> int:
    with sandbox.real(), db.conn() as c:
        return c.execute(f"SELECT count(*) AS n FROM {schema}.{tabla}").fetchone()["n"]


@pytest.mark.parametrize("con_copia_huerfana", [False, True])
def test_en_modo_prueba_las_ofertas_van_al_schema_real(con_copia_huerfana):
    """Con o sin la copia huérfana que dejó el arranque viejo en bases existentes."""
    prueba = sandbox.schema_prueba()
    if con_copia_huerfana:
        with sandbox.real(), db.conn() as c:
            c.execute(f"CREATE TABLE IF NOT EXISTS {prueba}.oferta (LIKE {config.DB_SCHEMA}.oferta INCLUDING ALL)")
            c.execute(f"CREATE TABLE IF NOT EXISTS {prueba}.cotizaciones (LIKE {config.DB_SCHEMA}.cotizaciones INCLUDING ALL)")
    try:
        antes_real = _contar(config.DB_SCHEMA, "oferta")
        antes_prueba = _contar(prueba, "oferta") if con_copia_huerfana else 0

        with sandbox.activar(sandbox.Sandbox(username="alguien")):
            ahora = dt.datetime.now(dt.UTC)
            creada = ofertas.crear_manual({"categoria": "otros", "titulo": "Prueba global", "desde": ahora}, ahora)
            assert ofertas.obtener(creada.id) is not None
            from app import cotizacion
            assert cotizacion.vigente_en(ahora.date())["oficial"] is not None  # lee el real, no falla sin copia

        assert _contar(config.DB_SCHEMA, "oferta") == antes_real + 1
        if con_copia_huerfana:
            assert _contar(prueba, "oferta") == antes_prueba
    finally:
        ofertas.borrar(creada.id)
        if con_copia_huerfana:
            with sandbox.real(), db.conn() as c:
                c.execute(f"DROP TABLE IF EXISTS {prueba}.oferta")
                c.execute(f"DROP TABLE IF EXISTS {prueba}.cotizaciones")


def test_el_pool_de_prueba_ve_las_globales_del_real_por_search_path():
    with sandbox.activar(sandbox.Sandbox(username="alguien")), pg.pool().connection() as c:
        n = c.execute("SELECT count(*) AS n FROM oferta_job").fetchone()["n"]

    assert n == _contar(config.DB_SCHEMA, "oferta_job")
