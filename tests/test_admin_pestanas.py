"""Administración por pestañas: la estructura del front (se verifica el JS como texto, como test_diseno) y su ruteo."""
import re
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
WEB_JS = RAIZ / "web" / "js"
MODULOS = ["adminUi", "adminTextos", "adminUsuarios", "adminEstado", "adminEventos", "adminLlm", "adminOfertas"]


def _js(nombre: str) -> str:
    return (WEB_JS / f"{nombre}.js").read_text(encoding="utf-8")


@pytest.mark.parametrize("modulo", MODULOS)
def test_cada_modulo_del_admin_esta_en_el_precache(modulo):
    assert f'"/js/{modulo}.js"' in (RAIZ / "web" / "sw.js").read_text(encoding="utf-8")


def test_account_quedo_solo_con_la_contrasena():
    cuenta = _js("account")

    assert "viewAdmin" not in cuenta and "UserRow" not in cuenta and "FunctionalCheck" not in cuenta
    assert cuenta.count("PasswordField(") == 3


def test_el_router_tiene_las_cinco_pestanas():
    app = _js("app")

    for ruta in (r"#\/admin$", r"#\/admin\/usuarios$", r"#\/admin\/eventos$", r"#\/admin\/ofertas$", r"#\/admin\/llm$"):
        assert f"/^{ruta}/" in app, ruta
    assert "viewAdminEstado(view)" in app


@pytest.mark.parametrize("modulo", MODULOS)
def test_el_admin_no_usa_dialogos_del_navegador(modulo):
    assert not re.search(r"\b(?:window\.)?(?:confirm|alert|prompt)\(", _js(modulo))


def test_las_acciones_peligrosas_piden_confirmacion():
    usuarios, ofertas = _js("adminUsuarios"), _js("adminOfertas")

    assert "confirmar(" in usuarios and "Desactivar" in usuarios and "Cerrar sesiones" in usuarios
    assert "confirmar(" in ofertas and "Dar de baja" in ofertas


def test_el_polling_de_eventos_se_corta_al_salir_y_no_repinta_el_formulario():
    eventos = _js("adminEventos")

    assert "setCleanup(parar)" in eventos and "clearTimeout(timer)" in eventos
    assert "isConnected" in eventos
    assert "silencioso" in eventos  # el sondeo repinta solo el estado de las fuentes
    assert "AddLink(paint)" not in eventos


def test_cada_pestana_carga_por_su_cuenta():
    for modulo in ("adminUsuarios", "adminEstado", "adminEventos", "adminLlm", "adminOfertas"):
        assert "Cargable(" in _js(modulo), modulo


def test_usuarios_arma_el_marco_antes_de_pedir_nada():
    usuarios = _js("adminUsuarios")

    assert "export function viewAdminUsuarios" in usuarios  # sin async: no hay await antes de AdminShell
    assert "export async function viewAdminUsuarios" not in usuarios


def test_ninguna_vista_admin_espera_antes_de_armar_el_marco():
    for modulo in ("adminUsuarios", "adminEstado", "adminEventos", "adminLlm", "adminOfertas"):
        assert not re.search(r"export async function viewAdmin", _js(modulo)), modulo


def test_un_sondeo_que_falla_no_deja_la_revision_congelada():
    eventos = _js("adminEventos")

    assert "if (ocupado) programar();" in eventos
    assert 'revisar.textContent = "Revisando…"' in eventos  # «Revisar ahora» no se rehabilita antes del sondeo


def test_si_falla_el_repintado_no_se_muestra_la_accion_como_fallida():
    assert "pero no se pudo actualizar la lista" in _js("adminUsuarios")
