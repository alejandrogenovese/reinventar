"""El índice de la galería: orden de features.yml, sin admin y solo con los videos que existen."""
from pathlib import Path

from scripts.subir_demos import ENTORNOS, armar_indice, orden_de_features

LIBRETOS = {
    "gastos": {"titulo": "Gastos", "beneficio": "Cargás y listo",
               "escenas": [{"subtitulo": "Dólares, pesos…\nes fácil perder la cuenta"}, {"accion": "wait 2"}]},
    "inicio-hoy": {"titulo": "Tu día", "beneficio": "De un vistazo"},
    "shows": {"titulo": "Shows"},
}


def test_respeta_el_orden_y_saltea_lo_que_no_tiene_video():
    indice = armar_indice(["inicio-hoy", "ofertas", "gastos", "shows"], LIBRETOS, {"gastos": 51, "inicio-hoy": 46})
    assert [d["feature"] for d in indice] == ["inicio-hoy", "gastos"]
    assert indice[1] == {"feature": "gastos", "titulo": "Gastos", "beneficio": "Cargás y listo", "duracion_s": 51,
                         "video": "gastos.mp4", "poster": "gastos.jpg",
                         "pasos": ["Dólares, pesos… es fácil perder la cuenta"]}


def test_sin_beneficio_queda_vacio():
    assert armar_indice(["shows"], LIBRETOS, {"shows": 50})[0]["beneficio"] == ""


def test_las_features_de_admin_no_se_publican(tmp_path: Path):
    yml = tmp_path / "features.yml"
    yml.write_text("features:\n  - id: gastos\n    audiencia: usuario\n  - id: admin-llm\n    audiencia: admin\n"
                   "  - id: shows\n", encoding="utf-8")
    assert orden_de_features(yml) == ["gastos", "shows"]



def test_la_contrasena_solo_viaja_a_entornos_de_reinventar():
    assert ENTORNOS == {"staging": "https://staging.reinventar.app", "local": "http://localhost:8000"}
