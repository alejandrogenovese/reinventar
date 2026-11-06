"""Agrupaciones emergentes: temas que salen de los datos, no de una lista fija.

Las charlas se agrupan por significado (k-means esférico sobre sus embeddings) y el LLM le pone nombre a cada grupo
mirando sus títulos más representativos. El resultado se guarda en speech_cluster: mientras los vectores no cambien,
no se recalcula ni se vuelve a llamar al LLM. Si el LLM falla, cada grupo se nombra por su tópico más común y no se
guarda (se reintenta en el próximo arranque o recarga del catálogo).
"""
import hashlib
import logging
import threading
from collections import Counter

import numpy as np

from . import catalog, config, embeddings, llm, pg, prompts, search

log = logging.getLogger("reinventar.clusters")

CLUSTER_COUNT = 30
KMEANS_ITERATIONS = 40
KMEANS_SEED = 7
TITLES_PER_GROUP = 10
NAMING_MAX_TOKENS = 3000

_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS speech_cluster (
  source_hash TEXT NOT NULL,
  id_speech   TEXT NOT NULL,
  label       TEXT NOT NULL,
  PRIMARY KEY (source_hash, id_speech)
)"""

_labels: dict[str, str] = {}
_version = 0
_lock = threading.Lock()


def reset() -> None:
    global _labels, _version
    _labels, _version = {}, _version + 1


def version() -> int:
    """Cambia cada vez que cambian los temas (el explorador lo usa para invalidar su caché)."""
    return _version


def label_for(base: str) -> str | None:
    return _labels.get(base)


# --- k-means esférico (vectores normalizados: similitud = producto punto) ----------------------
def _normalize(m: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(m, axis=1, keepdims=True)
    return m / np.where(norms == 0, 1, norms)


def _init_centers(X: np.ndarray, k: int, rng: np.random.Generator) -> np.ndarray:
    """k-means++: cada centro nuevo, con más chance cuanto más lejos esté de los ya elegidos."""
    centers = [X[rng.integers(len(X))]]
    for _ in range(1, k):
        distance = np.clip(1 - np.max(X @ np.array(centers).T, axis=1), 0, None) ** 2
        total = distance.sum()
        centers.append(X[rng.choice(len(X), p=distance / total)] if total > 0 else X[rng.integers(len(X))])
    return np.array(centers)


def kmeans(X: np.ndarray, k: int) -> tuple[np.ndarray, np.ndarray]:
    """(grupo de cada fila, centros). Determinístico: misma entrada, mismos grupos."""
    rng = np.random.default_rng(KMEANS_SEED)
    centers = _init_centers(X, k, rng)
    labels = np.argmax(X @ centers.T, axis=1)
    for _ in range(KMEANS_ITERATIONS):
        new_centers = _normalize(np.array([X[labels == j].mean(axis=0) if np.any(labels == j) else centers[j] for j in range(k)]))
        new_labels = np.argmax(X @ new_centers.T, axis=1)
        centers = new_centers
        if np.array_equal(new_labels, labels):
            break
        labels = new_labels
    return labels, centers


# --- nombres -------------------------------------------------------------------------------------
def _groups(sessions: list[dict], X: np.ndarray, labels: np.ndarray, centers: np.ndarray) -> list[dict]:
    """Por grupo no vacío: índices de sus charlas y los títulos más cercanos al centro."""
    groups = []
    for j in range(len(centers)):
        members = np.flatnonzero(labels == j)
        if not len(members):
            continue
        closest = members[np.argsort(-(X[members] @ centers[j]))][:TITLES_PER_GROUP]
        groups.append({"members": members, "titles": [sessions[i]["title"] for i in closest]})
    return groups


def _fallback_name(sessions: list[dict], members: np.ndarray) -> str:
    topics = Counter(t for i in members for t in catalog.split_field(sessions[i].get("area")) or catalog.split_field(sessions[i].get("topic")))
    return topics.most_common(1)[0][0] if topics else "Otros"


def _unique(names: list[str]) -> list[str]:
    seen: Counter = Counter()
    out = []
    for name in names:
        seen[name] += 1
        out.append(name if seen[name] == 1 else f"{name} ({seen[name]})")
    return out


def _llm_names(groups: list[dict]) -> list[str] | None:
    try:
        raw = llm.complete(config.ASK_MODEL, prompts.CLUSTERS_SYSTEM, prompts.clusters_user(groups), NAMING_MAX_TOKENS)
        by_id = {int(g["id"]): str(g["name"]).strip() for g in llm.parse_json(raw).get("groups", [])}
    except Exception:
        log.exception("No se pudieron nombrar los temas emergentes; se usan nombres de respaldo")
        return None
    names = [by_id.get(i) for i in range(len(groups))]
    if not all(names):
        log.error("El LLM no nombró todos los grupos (%d de %d)", sum(map(bool, names)), len(groups))
        return None
    return names


# --- persistencia --------------------------------------------------------------------------------
def _source_hash(sessions: list[dict], X: np.ndarray) -> str:
    h = hashlib.sha256(f"{embeddings.model_name()}|{CLUSTER_COUNT}|".encode())
    h.update("|".join(s["base"] for s in sessions).encode())
    h.update(np.ascontiguousarray(X, dtype=np.float32).tobytes())
    return h.hexdigest()


def _load(source_hash: str) -> dict[str, str]:
    with pg.pool().connection() as c:
        c.execute(_TABLE_SQL)
        rows = c.execute("SELECT id_speech, label FROM speech_cluster WHERE source_hash = %s", (source_hash,)).fetchall()
    return {r["id_speech"]: r["label"] for r in rows}


def _save(source_hash: str, labels: dict[str, str]) -> None:
    with pg.pool().connection() as c, c.cursor() as cur:
        cur.execute(_TABLE_SQL)
        cur.execute("DELETE FROM speech_cluster")  # solo vale la última corrida
        cur.executemany("INSERT INTO speech_cluster (source_hash, id_speech, label) VALUES (%s, %s, %s)",
                        [(source_hash, base, label) for base, label in labels.items()])


def _compute(sessions: list[dict], X: np.ndarray) -> tuple[dict[str, str], bool]:
    """(tema de cada charla, si los nombres vinieron del LLM)."""
    labels, centers = kmeans(X, min(CLUSTER_COUNT, len(sessions)))
    groups = _groups(sessions, X, labels, centers)
    names = _llm_names(groups)
    named_by_llm = names is not None
    names = _unique(names or [_fallback_name(sessions, g["members"]) for g in groups])
    return {sessions[i]["base"]: names[gi] for gi, g in enumerate(groups) for i in g["members"]}, named_by_llm


def ensure() -> None:
    """Arma (o recupera de la base) los temas para el catálogo actual. Sin embeddings listos, no hace nada."""
    global _labels, _version
    X = search.ready_vectors()
    if X is None:
        return
    with _lock:
        sessions = catalog.all_sessions()
        source_hash = _source_hash(sessions, X)
        labels = _load(source_hash)
        if len(labels) != len(sessions):
            labels, named_by_llm = _compute(sessions, _normalize(X))
            if named_by_llm:
                _save(source_hash, labels)
            log.info("Temas emergentes: %d grupos para %d charlas", len(set(labels.values())), len(labels))
        _labels, _version = labels, _version + 1
