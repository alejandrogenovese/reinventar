"""Capa visual del admin: web/css/admin.css con tokens existentes, enlazado y precacheado, y la estructura nueva del front
(se verifica el CSS y el JS como texto, igual que test_admin_pestanas y test_gastos_front)."""
import re
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
WEB = RAIZ / "web"
CSS = (WEB / "css" / "admin.css").read_text(encoding="utf-8") if (WEB / "css" / "admin.css").exists() else ""
SIN_COMENTARIOS = re.sub(r"/\*.*?\*/", "", CSS, flags=re.S)
TOKENS = (WEB / "css" / "tokens.css").read_text(encoding="utf-8")
SW = (WEB / "sw.js").read_text(encoding="utf-8")
INDEX = (WEB / "index.html").read_text(encoding="utf-8")


def _js(nombre: str) -> str:
    return (WEB / "js" / f"{nombre}.js").read_text(encoding="utf-8")


def test_el_css_existe_esta_enlazado_y_precacheado():
    assert CSS, "falta web/css/admin.css"
    assert '<link rel="stylesheet" href="/css/admin.css">' in INDEX
    assert '"/css/admin.css"' in SW
    for modulo in ("adminAtencion", "adminCharlas"):
        assert f'"/js/{modulo}.js"' in SW, modulo


def test_no_se_toca_la_version_del_service_worker():
    assert 'const VERSION = "reinventar-v1.0.0";' in SW


def test_solo_usa_tokens_que_existen():
    definidos = set(re.findall(r"(--[\w-]+)\s*:", TOKENS))
    usados = set(re.findall(r"var\((--[\w-]+)", SIN_COMENTARIOS)) - {"--masthead-h"}  # --masthead-h la calcula app.js
    assert CSS and usados - definidos == set(), f"tokens inexistentes: {sorted(usados - definidos)}"


def test_no_hay_colores_nuevos():
    assert CSS
    assert re.findall(r"#[0-9a-fA-F]{3,8}\b", SIN_COMENTARIOS) == []
    assert not re.search(r"\b(?:rgb|rgba|hsl|hsla)\(", SIN_COMENTARIOS)


def test_letra_y_radios_salen_de_la_escala():
    assert CSS
    assert re.findall(r"font:\s*\d{3}\s+\d+px", SIN_COMENTARIOS) == []
    radios = [int(px) for valor in re.findall(r"border-radius:\s*([^;}]+)", SIN_COMENTARIOS) for px in re.findall(r"(\d+)px", valor)]
    assert radios == []  # todos con --radius-*


def test_las_pestanas_viven_en_admin_css_y_no_en_styles():
    styles = (WEB / "styles.css").read_text(encoding="utf-8")
    assert ".admin-tabs" not in styles
    assert ".ra-adm-tabs" in SIN_COMENTARIOS and "var(--touch)" in SIN_COMENTARIOS


def test_el_foco_visible_y_los_objetivos_tactiles_estan_cubiertos():
    assert re.search(r"\.ra-adm-fila:focus-visible", SIN_COMENTARIOS)
    assert re.search(r"\.ra-adm-det > summary:focus-visible", SIN_COMENTARIOS)
    assert re.search(r"min-height:\s*var\(--touch\)", SIN_COMENTARIOS)


def test_las_barras_se_ven_en_tema_claro_y_el_estado_no_es_solo_color():
    assert ':root[data-theme="light"] .ra-adm-view .ra-bar-track' in SIN_COMENTARIOS
    assert ':root[data-theme="light"] .ra-adm-view .ra-bar-fill' in SIN_COMENTARIOS
    assert "Cerca del límite" in _js("adminLlm")  # el texto acompaña al color de la barra


def test_estado_arma_requiere_atencion_con_la_funcion_pura():
    estado = _js("adminEstado")
    assert 'from "./adminAtencion.js"' in estado and "atencion(" in estado
    assert "Requiere atención" in estado and "Todo en orden" in estado
    assert "Herramientas" in estado and "Borrar datos de prueba" in estado
    assert "ra-adm-det" in estado


def test_borrar_datos_de_prueba_es_el_unico_boton_rojo_lleno_del_admin():
    llenos = {m: _js(m).count('variant: "danger"') for m in ("adminEstado", "adminUsuarios", "adminOfertas", "adminEventos", "adminLlm")}
    assert llenos == {"adminEstado": 1, "adminUsuarios": 0, "adminOfertas": 0, "adminEventos": 0, "adminLlm": 0}
    assert "ra-adm-btn-err" in _js("adminUsuarios") and "ra-adm-btn-err" in _js("adminOfertas")


def test_eventos_agrupa_busca_filtra_y_pliega():
    eventos = _js("adminEventos")
    assert 'from "./adminCharlas.js"' in eventos
    for fragmento in ("agruparCharlas(", "filtrarCharlas(", "visibles(", "Ver las ", "Cargados por link", "ra-searchfield", "aria-pressed"):
        assert fragmento in eventos, fragmento


def test_usuarios_compactos_con_las_acciones_adentro_y_nuevo_usuario_plegado():
    usuarios = _js("adminUsuarios")
    for fragmento in ("ra-adm-usuario", "ra-adm-nuevo", '"details"', "Nuevo usuario"):
        assert fragmento in usuarios, fragmento


def test_ofertas_muestra_vigentes_primero_y_carga_plegada():
    ofertas = _js("adminOfertas")
    assert 'Plegable("Cargar oferta"' in ofertas
    assert ofertas.index('"Vigentes"') < ofertas.index('Plegable("Cargar oferta"')


def test_llm_en_tarjetas_con_hora_y_actualizar_arriba():
    llm = _js("adminLlm")
    assert "ra-num-card" in llm and "Actualizado" in llm and "ra-sec-action" in llm
    assert llm.index("Cabecera(updated") < llm.index("CostByTask(d.tareas)")  # la hora y «Actualizar» van arriba de todo


@pytest.mark.parametrize("modulo", ["adminEstado", "adminEventos", "adminLlm", "adminUsuarios", "adminOfertas", "adminAtencion", "adminCharlas"])
def test_nada_de_innerhtml_con_datos_del_servidor(modulo):
    assert "innerHTML" not in _js(modulo) if (WEB / "js" / f"{modulo}.js").exists() else False


def test_los_avisos_de_error_ocultos_no_se_pintan_como_barras_vacias():
    # .ra-hint es display:flex y pisa el atributo hidden: sin esta regla el aviso vacío del alta de usuario se ve como una barra roja.
    assert re.search(r"\.ra-hint\[hidden\]\s*\{\s*display:\s*none", SIN_COMENTARIOS)
    usuarios = _js("adminUsuarios")
    assert 'class: "ra-hint is-error"' in usuarios and "hidden: true" in usuarios


def test_el_admin_no_deja_hints_vacios_fuera_del_alta_de_usuario():
    for modulo in ("adminOfertas", "adminEventos", "adminEstado", "adminLlm"):
        assert "hidden:" not in _js(modulo).replace('"aria-hidden"', ""), modulo
