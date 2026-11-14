"""scripts/resetear_password.py: cambiar la contraseña desde la Terminal cuando nadie puede entrar a Administración."""
import pytest

from app import passwords
from scripts import resetear_password as rp


class Resultado:
    def __init__(self, fila=None, rowcount=0):
        self._fila, self.rowcount = fila, rowcount

    def fetchone(self):
        return self._fila


class ConexionFalsa:
    """Registra cada consulta (texto armado, parámetros) y simula users y auth_tokens."""

    def __init__(self, existe=True, sesiones=2):
        self.existe, self.sesiones, self.consultas = existe, sesiones, []

    def execute(self, consulta, params=()):
        texto = repr(consulta)
        self.consultas.append((texto, params))
        if "SELECT 1" in texto:
            return Resultado((1,) if self.existe else None)
        if "DELETE" in texto:
            return Resultado(rowcount=self.sesiones)
        return Resultado(rowcount=1)


def _update(conn):
    return next(p for t, p in conn.consultas if "UPDATE" in t)


def test_guarda_un_hash_que_verifica_con_la_contrasena_nueva_y_cierra_las_sesiones():
    conn = ConexionFalsa(sesiones=3)

    cerradas = rp.resetear(conn, "app_staging", "aleg", "una-clave-larga")

    salt, password_hash, forzar, usuario = _update(conn)
    assert passwords.verify_password("una-clave-larga", salt, password_hash)
    assert (forzar, usuario, cerradas) == (False, "aleg", 3)


def test_usa_el_schema_pedido_en_todas_las_consultas():
    conn = ConexionFalsa()

    rp.resetear(conn, "app_staging", "aleg", "una-clave-larga")

    assert len(conn.consultas) == 3
    assert all("app_staging" in t for t, _ in conn.consultas)


def test_forzar_cambio_hace_que_la_app_la_pida_al_entrar():
    conn = ConexionFalsa()

    rp.resetear(conn, "app", "aleg", "una-clave-larga", forzar_cambio=True)

    assert _update(conn)[2] is True


def test_usuario_inexistente_no_toca_nada():
    conn = ConexionFalsa(existe=False)

    with pytest.raises(rp.ErrorReset, match="No existe el usuario"):
        rp.resetear(conn, "app", "nadie", "una-clave-larga")
    assert len(conn.consultas) == 1


@pytest.mark.parametrize(("clave", "repetida", "error"), [
    ("una-clave-larga", "otra-clave-larga", "no coinciden"),
    ("corta", "corta", "entre"),
    ("x" * 201, "x" * 201, "entre"),
])
def test_valida_la_contrasena_antes_de_conectarse(clave, repetida, error):
    with pytest.raises(rp.ErrorReset, match=error):
        rp.validar(clave, repetida)


def test_sin_url_de_la_base_corta_antes_de_pedir_la_contrasena(monkeypatch):
    monkeypatch.delenv("RAILWAY_DATABASE_URL", raising=False)
    monkeypatch.setattr(rp.getpass, "getpass", lambda *_: pytest.fail("no tenía que pedir la contraseña"))

    with pytest.raises(SystemExit, match="RAILWAY_DATABASE_URL"):
        rp.main(["--schema", "app", "--usuario", "aleg"])


def test_el_schema_es_obligatorio():
    with pytest.raises(SystemExit):
        rp.main(["--usuario", "aleg"])
