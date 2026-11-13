"""Vectores de significado para textos (embeddings), intercambiables por EMBED_PROVIDER.

  local → modelo multilingüe con fastembed dentro del contenedor (sin API key; se baja una vez a DATA_DIR/models)
  fake  → hashing de palabras, determinístico y sin dependencias (tests)
  off   → sin vectores: la búsqueda queda solo por palabras
"""
import logging
import re
import threading
import zlib

import numpy as np

from . import catalog, config

log = logging.getLogger("reinventar.embeddings")

FAKE_DIM = 256

# Algunos modelos esperan un prefijo distinto para la consulta y para el documento (así fueron entrenados).
# (prefijo de consulta, prefijo de documento); los que no figuran no llevan prefijo.
PREFIJOS = {
    "google/embeddinggemma-300m": ("task: search result | query: ", "title: none | text: "),
    "intfloat/multilingual-e5-large": ("query: ", "passage: "),
}
CONSULTA, DOCUMENTO = "consulta", "documento"

# Versión cuantizada a 4 bits de embeddinggemma (mismo repo ONNX, pesos comprimidos). Medido con
# scripts/evaluar_busqueda.py: recall@10 0,80 contra 0,81 del original, con 0,4 GB de RAM en reposo contra 1,2 GB.
# (La de 8 bits ocupaba más que el original: descartada.) Nombre propio, porque speech_embedding guarda los
# vectores por modelo y así no se mezclan con los del original.
_GEMMA = "google/embeddinggemma-300m"
_GEMMA_ONNX = "onnx-community/embeddinggemma-300m-ONNX"
VARIANTES = {f"{_GEMMA}-q4": "onnx/model_q4.onnx"}
_model = None
_model_lock = threading.Lock()


def is_enabled() -> bool:
    return config.EMBED_PROVIDER in ("local", "fake")


def model_name() -> str:
    return "fake-hash" if config.EMBED_PROVIDER == "fake" else config.EMBED_MODEL


def _normalized(matrix: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    return (matrix / np.where(norms == 0, 1, norms)).astype(np.float32)


def fake_embed(texts: list[str]) -> np.ndarray:
    """Bolsa de palabras con hashing: textos con palabras en común quedan cerca."""
    out = np.zeros((len(texts), FAKE_DIM), dtype=np.float32)
    for row, text in enumerate(texts):
        for word in re.findall(r"\w{3,}", catalog.fold(text)):
            out[row, zlib.crc32(word.encode()) % FAKE_DIM] += 1
    return _normalized(out)


def modelo_base(nombre: str) -> str:
    """Las variantes cuantizadas se usan igual que el modelo original (mismos prefijos)."""
    return _GEMMA if nombre in VARIANTES else nombre


def _registrar_variante(nombre: str) -> None:
    from fastembed import TextEmbedding
    from fastembed.common.model_description import ModelSource, PoolingType

    if any(m.model == nombre for m in TextEmbedding._list_supported_models()):
        return
    archivo = VARIANTES[nombre]
    TextEmbedding.add_custom_model(
        model=nombre, pooling=PoolingType.DISABLED, normalization=True, dim=768,
        sources=ModelSource(hf=_GEMMA_ONNX), model_file=archivo, additional_files=[f"{archivo}_data"],
        output_name="sentence_embedding", license="gemma")


def _local_model():
    global _model
    with _model_lock:
        if _model is None:
            from fastembed import TextEmbedding  # import diferido: pesa y solo hace falta con EMBED_PROVIDER=local

            if config.EMBED_MODEL in VARIANTES:
                _registrar_variante(config.EMBED_MODEL)
            log.info("Cargando modelo de embeddings %s", config.EMBED_MODEL)
            # Hilos fijos: si no, ONNX abre uno por cada CPU que ve (en Railway, las del servidor físico),
            # cada uno con su memoria.
            _model = TextEmbedding(config.EMBED_MODEL, cache_dir=str(config.EMBED_CACHE_DIR),
                                   threads=config.EMBED_THREADS)
        return _model


def con_prefijo(texts: list[str], tipo: str) -> list[str]:
    consulta, documento = PREFIJOS.get(modelo_base(config.EMBED_MODEL), ("", ""))
    prefijo = consulta if tipo == CONSULTA else documento
    return [prefijo + t for t in texts]


def embed(texts: list[str], tipo: str = DOCUMENTO) -> np.ndarray:
    """Una fila normalizada (norma 1) por texto: el producto punto entre filas es la similitud coseno.
    tipo: CONSULTA para lo que escribe la persona, DOCUMENTO para lo que se indexa (charlas, fragmentos)."""
    if not texts:
        return np.zeros((0, 0), dtype=np.float32)
    if config.EMBED_PROVIDER == "fake":
        return fake_embed(texts)
    if config.EMBED_PROVIDER == "local":
        textos = con_prefijo(texts, tipo)
        return _normalized(np.array(list(_local_model().embed(textos, batch_size=config.EMBED_BATCH))))
    raise RuntimeError(f"Embeddings deshabilitados (EMBED_PROVIDER={config.EMBED_PROVIDER})")
