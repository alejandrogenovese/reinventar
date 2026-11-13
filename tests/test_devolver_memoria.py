"""Después de los cálculos grandes de embeddings se le devuelve al sistema la memoria libre (malloc_trim en Linux)."""
from app import clusters, embeddings, search


class _LibcFalsa:
    def __init__(self):
        self.llamadas = []

    def malloc_trim(self, pad):
        self.llamadas.append(pad)
        return 1


def test_con_glibc_llama_a_malloc_trim(monkeypatch):
    libc = _LibcFalsa()
    monkeypatch.setattr(embeddings.ctypes.util, "find_library", lambda _n: "libc.so.6")
    monkeypatch.setattr(embeddings.ctypes, "CDLL", lambda _n: libc)

    assert embeddings.devolver_memoria() is True
    assert libc.llamadas == [0]


def test_sin_malloc_trim_no_hace_nada(monkeypatch):
    monkeypatch.setattr(embeddings.ctypes.util, "find_library", lambda _n: "libc.dylib")
    monkeypatch.setattr(embeddings.ctypes, "CDLL", lambda _n: object())  # sin malloc_trim, como macOS

    assert embeddings.devolver_memoria() is False


def test_sin_libc_no_hace_nada(monkeypatch):
    monkeypatch.setattr(embeddings.ctypes.util, "find_library", lambda _n: None)

    assert embeddings.devolver_memoria() is False


def test_en_esta_maquina_no_falla():
    assert embeddings.devolver_memoria() in (True, False)


def test_al_terminar_el_indice_del_catalogo_devuelve_la_memoria(monkeypatch):
    llamadas = []
    monkeypatch.setattr(search, "ensure_index", lambda: None)
    monkeypatch.setattr(clusters, "ensure", lambda: None)
    monkeypatch.setattr(embeddings, "devolver_memoria", lambda: llamadas.append(1) or True)

    search._warm()

    assert llamadas == [1]


def test_aunque_fallen_los_temas_emergentes_devuelve_la_memoria(monkeypatch):
    llamadas = []

    def falla():
        raise RuntimeError("sin LLM")

    monkeypatch.setattr(search, "ensure_index", lambda: None)
    monkeypatch.setattr(clusters, "ensure", falla)
    monkeypatch.setattr(embeddings, "devolver_memoria", lambda: llamadas.append(1) or True)

    search._warm()

    assert llamadas == [1]
