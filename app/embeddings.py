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


def _local_model():
    global _model
    with _model_lock:
        if _model is None:
            from fastembed import TextEmbedding  # import diferido: pesa y solo hace falta con EMBED_PROVIDER=local

            log.info("Cargando modelo de embeddings %s", config.EMBED_MODEL)
            _model = TextEmbedding(config.EMBED_MODEL, cache_dir=str(config.EMBED_CACHE_DIR))
        return _model


def embed(texts: list[str]) -> np.ndarray:
    """Una fila normalizada (norma 1) por texto: el producto punto entre filas es la similitud coseno."""
    if not texts:
        return np.zeros((0, 0), dtype=np.float32)
    if config.EMBED_PROVIDER == "fake":
        return fake_embed(texts)
    if config.EMBED_PROVIDER == "local":
        return _normalized(np.array(list(_local_model().embed(texts, batch_size=config.EMBED_BATCH))))
    raise RuntimeError(f"Embeddings deshabilitados (EMBED_PROVIDER={config.EMBED_PROVIDER})")
