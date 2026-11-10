"""Búsqueda híbrida sobre el catálogo: por significado (embeddings) y por palabras (BM25), fusionadas con RRF.

- Por significado: "bajar costos de IA" encuentra "Optimize AI inference costs" aunque no compartan palabras,
  y una pregunta en castellano encuentra resúmenes en inglés.
- Por palabras: nombres propios (Nubank, Bedrock, Itaú) que el modelo de embeddings no conoce.
- RRF (Reciprocal Rank Fusion): cada ranking aporta 1/(60 + puesto); no hace falta calibrar puntajes entre sí.

Los vectores de cada charla se guardan en speech_embedding (schema de la app) y se recalculan solo si cambia el texto.
Mientras se calculan (primer arranque, recarga del catálogo) la búsqueda sigue funcionando solo por palabras.
"""
import hashlib
import logging
import math
import re
import threading
import time
from collections import Counter

import numpy as np

from . import catalog, embeddings, pg

log = logging.getLogger("reinventar.search")

RRF_K = 60
SEMANTIC_TOP = 100
LEXICAL_TOP = 100
INTEREST_BOOST = 0.5 / RRF_K  # cada interés elegido que coincide con el tópico/área de la charla
NEWLAUNCH_BOOST = 0.1 / RRF_K  # desempate a favor de los lanzamientos, solo entre charlas que ya calzan
WARM_RETRY_SECONDS = 600
BM25_K1, BM25_B = 1.2, 0.75

_STOPWORDS = {
    "de", "la", "el", "en", "y", "que", "los", "las", "un", "una", "con", "para", "del", "por", "su", "como", "me",
    "quiero", "ver", "sobre", "hay", "charlas", "charla", "the", "and", "for", "with", "that", "this", "from", "are",
    "our", "you", "your", "how", "into", "using", "learn", "session",
}
_TOKEN = re.compile(r"[a-z0-9]{2,}")

_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS speech_embedding (
  id_speech TEXT NOT NULL,
  model     TEXT NOT NULL,
  doc_hash  TEXT NOT NULL,
  vector    REAL[] NOT NULL,
  PRIMARY KEY (id_speech, model)
)"""

_lexical_index: dict | None = None
_lexical_source: list | None = None
_matrix: np.ndarray | None = None
_matrix_source: list | None = None
_build_lock = threading.Lock()
_warm_thread: threading.Thread | None = None
_warm_failed_at = 0.0


# --- textos ------------------------------------------------------------------
def _tokens(text: str) -> list[str]:
    return [t for t in _TOKEN.findall(catalog.fold(text)) if t not in _STOPWORDS]


def _companies(s: dict) -> str:
    return ", ".join(sorted({p["company"] for p in s.get("people", []) if p.get("company") and not p.get("is_amazon")}))


def _doc_text(s: dict) -> str:
    """Lo que el modelo de embeddings "lee" de cada charla."""
    companies = _companies(s)
    parts = [
        f"{s.get('title', '')}.", s.get("abstract") or "",
        f"Servicios: {s['services'].replace(';', ', ')}." if s.get("services") else "",
        f"Tópicos: {s['topic'].replace(';', ', ')}." if s.get("topic") else "",
        f"Tecnologías: {s['tech'].replace(';', ', ')}." if s.get("tech") else "",
        f"Conceptos: {s['concepts'].replace(';', ', ')}." if s.get("concepts") else "",
        f"Empresas: {companies}." if companies else "",
    ]
    return " ".join(p for p in parts if p)


def _lexical_text(s: dict) -> str:
    names = " ".join(p.get("name") or "" for p in s.get("people", []))
    title = s.get("title", "")
    return " ".join((title, title, _doc_text(s), s.get("aoi") or "", (s.get("concepts_en") or "").replace(";", " "),
                     names, catalog._people_text(s)))


# --- BM25 (por palabras) -----------------------------------------------------
def _build_lexical(sessions: list[dict]) -> dict:
    postings: dict[str, list[tuple[int, int]]] = {}
    lengths = []
    for idx, s in enumerate(sessions):
        counts = Counter(_tokens(_lexical_text(s)))
        lengths.append(sum(counts.values()))
        for term, tf in counts.items():
            postings.setdefault(term, []).append((idx, tf))
    return {"postings": postings, "lengths": lengths, "avg": (sum(lengths) / len(lengths)) if lengths else 0}


def _lexical() -> dict:
    global _lexical_index, _lexical_source
    sessions = catalog.all_sessions()
    if _lexical_index is None or _lexical_source is not sessions:
        _lexical_index, _lexical_source = _build_lexical(sessions), sessions
    return _lexical_index


def _lexical_ranking(query: str, top: int) -> list[int]:
    index = _lexical()
    n = len(index["lengths"])
    scores: dict[int, float] = {}
    for term in set(_tokens(query)):
        docs = index["postings"].get(term, [])
        idf = math.log(1 + (n - len(docs) + 0.5) / (len(docs) + 0.5))
        for idx, tf in docs:
            norm = BM25_K1 * (1 - BM25_B + BM25_B * index["lengths"][idx] / index["avg"])
            scores[idx] = scores.get(idx, 0.0) + idf * tf * (BM25_K1 + 1) / (tf + norm)
    return [idx for idx, _ in sorted(scores.items(), key=lambda kv: -kv[1])[:top]]


# --- embeddings (por significado) --------------------------------------------
def _hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def ensure_index(force: bool = False) -> None:
    """Sincroniza speech_embedding con el catálogo (calcula solo lo nuevo o cambiado) y arma la matriz en memoria."""
    global _matrix, _matrix_source
    if not embeddings.is_enabled():
        return
    with _build_lock:
        sessions = catalog.all_sessions()
        if not force and _matrix_source is sessions:
            return
        model = embeddings.model_name()
        docs = [_doc_text(s) for s in sessions]
        hashes = [_hash(d) for d in docs]
        with pg.pool().connection() as c:
            c.execute(_TABLE_SQL)
            rows = c.execute("SELECT id_speech, doc_hash, vector FROM speech_embedding WHERE model = %s", (model,)).fetchall()
        stored = {r["id_speech"]: r for r in rows}
        stale = [i for i, s in enumerate(sessions) if (stored.get(s["base"]) or {}).get("doc_hash") != hashes[i]]
        fresh = {}
        if stale:
            log.info("Calculando embeddings de %d charlas (%s)", len(stale), model)
            vectors = embeddings.embed([docs[i] for i in stale])
            fresh = {sessions[i]["base"]: (hashes[i], vectors[row].tolist()) for row, i in enumerate(stale)}
            _save(model, fresh)
        matrix = [fresh[s["base"]][1] if s["base"] in fresh else stored[s["base"]]["vector"] for s in sessions]
        _matrix, _matrix_source = np.array(matrix, dtype=np.float32), sessions
        log.info("Índice de embeddings listo: %d charlas (%d recalculadas)", len(sessions), len(stale))


def _save(model: str, fresh: dict[str, tuple[str, list[float]]]) -> None:
    with pg.pool().connection() as c, c.cursor() as cur:
        cur.executemany(
            """INSERT INTO speech_embedding (id_speech, model, doc_hash, vector) VALUES (%s, %s, %s, %s::real[])
               ON CONFLICT (id_speech, model) DO UPDATE SET doc_hash = EXCLUDED.doc_hash, vector = EXCLUDED.vector""",
            [(base, model, doc_hash, vector) for base, (doc_hash, vector) in fresh.items()],
        )


def _warm() -> None:
    global _warm_failed_at
    try:
        ensure_index()
    except Exception:
        _warm_failed_at = time.monotonic()
        log.exception("No se pudo armar el índice de embeddings; la búsqueda sigue solo por palabras")
        return
    from . import clusters  # import diferido: clusters depende de este módulo

    try:
        clusters.ensure()
    except Exception:
        log.exception("No se pudieron armar los temas emergentes; el explorador sigue sin esa faceta")


def ready_vectors() -> np.ndarray | None:
    """La matriz de embeddings si ya está armada para el catálogo actual (sin disparar el armado)."""
    return _matrix if _matrix is not None and _matrix_source is catalog.all_sessions() else None


def warm_async() -> None:
    """Arma el índice en segundo plano (el primer arranque baja el modelo y tarda un par de minutos)."""
    global _warm_thread
    if not embeddings.is_enabled() or (_warm_thread and _warm_thread.is_alive()):
        return
    if _warm_failed_at and time.monotonic() - _warm_failed_at < WARM_RETRY_SECONDS:
        return
    _warm_thread = threading.Thread(target=_warm, name="embeddings-warm", daemon=True)
    _warm_thread.start()


def _vectors() -> np.ndarray | None:
    """Matriz alineada con catalog.all_sessions(), o None si todavía no está (y se pide armarla)."""
    if _matrix is not None and _matrix_source is catalog.all_sessions():
        return _matrix
    warm_async()
    return None


def _semantic_ranking(query: str, top: int) -> list[int]:
    vectors = _vectors()
    if vectors is None:
        return []
    try:
        query_vector = embeddings.embed([query])[0]
    except Exception:
        log.exception("No se pudo calcular el embedding de la consulta; se busca solo por palabras")
        return []
    return np.argsort(-(vectors @ query_vector))[:top].tolist()


# --- búsqueda ----------------------------------------------------------------
def _interest_overlap(s: dict, interests: set[str]) -> int:
    return len(interests & set(catalog.split_field(s.get("topic")) + catalog.split_field(s.get("aoi"))))


def ranked(query: str, limit: int, interests=()) -> list[tuple[dict, float]]:
    """(sesión, puntaje) de mayor a menor. A igual puntaje queda el orden del catálogo (por fecha)."""
    sessions = catalog.all_sessions()
    scores = [0.0] * len(sessions)
    query = (query or "").strip()
    if query:
        for ranking in (_lexical_ranking(query, LEXICAL_TOP), _semantic_ranking(query, SEMANTIC_TOP)):
            for position, idx in enumerate(ranking):
                scores[idx] += 1 / (RRF_K + position + 1)
    wanted = set(interests or ())
    for idx, s in enumerate(sessions):
        if wanted:
            scores[idx] += INTEREST_BOOST * _interest_overlap(s, wanted)
        if scores[idx] and s.get("newlaunch"):
            scores[idx] += NEWLAUNCH_BOOST
    order = sorted(range(len(sessions)), key=lambda i: -scores[i])
    return [(sessions[i], scores[i]) for i in order[:limit]]


def hybrid(query: str, limit: int, interests=()) -> list[dict]:
    return [s for s, _ in ranked(query, limit, interests)]


def prefilter(profile: dict, prompt: str, limit: int) -> list[dict]:
    """Candidatas para el LLM del itinerario: el pedido + rol + experiencia, con más peso a los intereses elegidos.
    Siempre devuelve `limit` sesiones (si no hay señales, en orden del catálogo)."""
    interests = profile.get("interests") or []
    query = " ".join(filter(None, (prompt, profile.get("role"), profile.get("experience"), " ".join(interests))))
    return [
        {**s, "topic": catalog.split_field(s.get("topic")), "aoi": catalog.split_field(s.get("aoi")), "relevance": round(score * RRF_K, 2)}
        for s, score in ranked(query, limit, interests)
    ]
