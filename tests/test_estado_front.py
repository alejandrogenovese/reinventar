"""Banner de estado y franja del día: el cableado del front (la lógica está en tests/js/estado.test.mjs y dia.test.mjs)."""
import re
from pathlib import Path

from app import estadia

WEB = Path(__file__).resolve().parent.parent / "web"


def _js(nombre):
    return (WEB / "js" / nombre).read_text(encoding="utf-8")


def test_el_banner_va_despues_del_modo_prueba_y_antes_de_los_cambios():
    index = (WEB / "index.html").read_text(encoding="utf-8")
    banner = '<div id="estado-banner" class="estado-banner" role="status" aria-live="polite" aria-atomic="true" hidden></div>'
    assert banner in index
    assert index.index('id="sandbox-banner"') < index.index(banner) < index.index('id="changes-banner"') < index.index('id="countdown-banner"')
    # vive dentro del masthead: el ResizeObserver de app.js recalcula --masthead-h cuando aparece o cambia de alto
    assert index.index('id="masthead"') < index.index(banner) < index.index('<header class="topbar">')


def test_la_app_arranca_el_banner_y_lo_refresca_al_navegar():
    app = _js("app.js")
    assert "iniciarEstado();" in app
    assert "refrescarEstado();" in app


def test_el_estilo_del_banner_sigue_el_mock():
    css = (WEB / "styles.css").read_text(encoding="utf-8")
    assert ".top-banners { container-type: inline-size; }" in css
    assert "@container (max-width: 520px)" in css
    assert "@media (prefers-reduced-motion: reduce) { .eb-gira { animation: none; } }" in css
    for tono, fondo, texto in [("warn", "warning", "warning"), ("error", "error", "error"), ("info", "info", "info"), ("ok", "success", "success")]:
        regla = re.search(rf"\.estado-banner\.is-{tono} \{{([^}}]*)\}}", css).group(1)
        assert f"var(--{fondo}-soft)" in regla and f"var(--on-{texto}-soft)" in regla, tono
    banner = re.search(r"\.estado-banner \{([^}]*)\}", css).group(1)
    assert "var(--brand" not in banner  # nunca naranja en el banner


def test_la_franja_del_dia_usa_el_rango_de_la_estadia():
    dia = _js("dia.js")
    inicio = estadia.INICIO_DE_LA_ESTADIA.date()
    fin = estadia.FIN_DE_LA_ESTADIA
    assert f'llegada: "{inicio.isoformat()}"' in dia
    assert f'salida: "{fin.date().isoformat()}", horaSalida: "{fin:%H:%M}"' in dia
    assert 'inicio: "2026-11-30", fin: "2026-12-04"' in dia  # re:Invent: lunes 30/11 a viernes 4/12


def test_la_franja_va_arriba_de_hoy_con_la_hora_de_la_app():
    app = _js("app.js")
    assert "diaSlot, todaySlot" in app  # arriba de Hoy
    hoy = _js("today.js")
    assert "diaDeEvento(sandboxNow())" in hoy
    assert 'h("span", { class: "vivo" }, "Keynote en vivo")' in hoy


def test_la_ultima_sincronizacion_la_marcan_las_dos_colas():
    assert "marcarUltimaSync();" in _js("recorder.js")
    assert "marcarUltimaSync();" in _js("gastos.js")
