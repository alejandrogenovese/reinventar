"""Buscar en lo grabado: las transcripciones se cortan en fragmentos de ~40 s y se buscan por significado y por palabras.

- Fragmentos: bloques consecutivos (de ~15 s, ver BLOCK_SECONDS) hasta juntar VENTANA_SEGUNDOS, y el siguiente arranca
  en el último bloque del anterior (solapamiento) para que una idea partida al medio aparezca entera en alguno.
  Son cortos a propósito: un fragmento tiene que hablar de una sola cosa para que el resultado apunte al minuto justo.
- Por significado: pgvector (distancia coseno, búsqueda exacta sin índice: son pocos miles de fragmentos).
- Por palabras: tsvector de Postgres sobre el texto en castellano y en inglés, con los mismos tokens que la búsqueda
  del catálogo (sin tildes ni plurales: "Neptune", "Iceberg", "migraciones" → "migracion").
- Los dos rankings se fusionan con RRF, igual que la búsqueda del catálogo (app/search.py).

Se indexa al terminar cada grabación (app/pipeline.py) y, al arrancar, lo que haya quedado sin indexar.
Si la base no tiene pgvector (db.vector_disponible), todo esto queda apagado.
"""
import logging
import threading

from . import db, embeddings, sandbox, search

log = logging.getLogger("reinventar.fragmentos")

VENTANA_SEGUNDOS = 40.0
CANDIDATOS = 50          # de cada ranking, antes de fusionar
RESULTADOS = 8
# Por significado siempre aparece "lo más parecido", aunque no tenga nada que ver. Con embeddinggemma, lo relevante da
# coseno 0,29–0,56, el ruido ≤ 0,21 y lo ajeno ("receta de empanadas") ≤ 0,06; con MiniLM era ≥ 0,30 contra ≤ 0,25.
# La escala varía por consulta: se pide un mínimo fijo y una fracción de la mejor. Si cambia EMBED_MODEL, re-medir.
SIMILITUD_MINIMA = 0.25
SIMILITUD_RELATIVA = 0.6
RRF_K = search.RRF_K
LARGO_MAXIMO_CONSULTA = 300


def armar_ventanas(blocks: list[dict], ventana: float = VENTANA_SEGUNDOS) -> list[dict]:
    """Agrupa bloques consecutivos en fragmentos de ~ventana segundos; cada uno arranca en el último bloque del anterior."""
    fragmentos, inicio = [], 0
    while inicio < len(blocks):
        fin = inicio
        while fin + 1 < len(blocks) and blocks[fin]["end_s"] - blocks[inicio]["start_s"] < ventana:
            fin += 1
        tramo = blocks[inicio:fin + 1]
        fragmentos.append({
            "start_s": tramo[0]["start_s"], "end_s": tramo[-1]["end_s"],
            "en": " ".join(b["en"] for b in tramo),
            "es": " ".join(b["es"] for b in tramo) if all(b.get("es") for b in tramo) else None,
        })
        if fin == len(blocks) - 1:
            break
        inicio = max(fin, inicio + 1)  # solapa un bloque, pero siempre avanza
    return fragmentos


def _texto_vector(f: dict) -> str:
    # Uno solo de los idiomas: con los dos, el modelo corta a la mitad. Las preguntas llegan en castellano.
    return f["es"] or f["en"]


def _texto_palabras(f: dict) -> str:
    # Los mismos tokens que la consulta (search._tokens): si cambia la normalización, hay que reindexar.
    return " ".join(search._tokens(f"{f['es'] or ''} {f['en']}"))


def _literal(v) -> str:
    return "[" + ",".join(f"{x:.6f}" for x in v) + "]"


def indexar(sid: str) -> int:
    """(Re)arma los fragmentos de una grabación. Devuelve cuántos guardó."""
    if not db.vector_disponible:
        return 0
    fragmentos = armar_ventanas(db.get_blocks(sid))
    vectores, modelo = [None] * len(fragmentos), None
    if fragmentos and embeddings.is_enabled():
        modelo = embeddings.model_name()
        vectores = [_literal(v) for v in embeddings.embed([_texto_vector(f) for f in fragmentos], embeddings.DOCUMENTO)]
    with db.conn() as c:
        c.execute("DELETE FROM fragmentos WHERE session_id=%s", (sid,))
        c.cursor().executemany(
            "INSERT INTO fragmentos (session_id,idx,start_s,end_s,es,en,modelo,vector,tsv) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s::vector,to_tsvector('simple',%s))",
            [(sid, i, f["start_s"], f["end_s"], f["es"], f["en"], modelo, vectores[i], _texto_palabras(f))
             for i, f in enumerate(fragmentos)])
    return len(fragmentos)


def indexar_sin_fallar(sid: str) -> None:
    """Para el pipeline: si indexar falla, la grabación igual queda lista (solo no aparece en la búsqueda)."""
    try:
        indexar(sid)
    except Exception:
        log.exception("No se pudieron indexar los fragmentos de %s", sid)


def pendientes() -> list[str]:
    """Grabaciones listas sin fragmentos con el modelo de embeddings actual (nuevas, viejas o de otro modelo)."""
    modelo = embeddings.model_name() if embeddings.is_enabled() else None
    with db.conn() as c:
        rows = c.execute(
            "SELECT id FROM sessions s WHERE status='ready' AND NOT EXISTS ("
            "  SELECT 1 FROM fragmentos f WHERE f.session_id=s.id AND f.modelo IS NOT DISTINCT FROM %s)"
            " ORDER BY created_at", (modelo,)).fetchall()
    return [r["id"] for r in rows]


@sandbox.en_real
def indexar_pendientes() -> int:
    if not db.vector_disponible:
        return 0
    hechas = 0
    for sid in pendientes():
        indexar_sin_fallar(sid)
        hechas += 1
    if hechas:
        log.info("Fragmentos indexados de %d grabaciones", hechas)
        embeddings.devolver_memoria()
    return hechas


def indexar_pendientes_async() -> None:
    threading.Thread(target=indexar_pendientes, name="fragmentos", daemon=True).start()


# --- búsqueda ----------------------------------------------------------------
def _por_significado(c, consulta: str) -> list[tuple[str, int]]:
    if not embeddings.is_enabled():
        return []
    vector = _literal(embeddings.embed([consulta], embeddings.CONSULTA)[0])
    rows = c.execute(
        "SELECT session_id, idx, 1 - (vector <=> %s::vector) AS sim FROM fragmentos WHERE modelo=%s "
        "ORDER BY vector <=> %s::vector LIMIT %s", (vector, embeddings.model_name(), vector, CANDIDATOS)).fetchall()
    if not rows:
        return []
    corte = max(SIMILITUD_MINIMA, rows[0]["sim"] * SIMILITUD_RELATIVA)
    return [(r["session_id"], r["idx"]) for r in rows if r["sim"] >= corte]


def _por_palabras(c, consulta: str) -> list[tuple[str, int]]:
    terminos = sorted(set(search._tokens(consulta)))  # solo [a-z0-9]: no rompe la sintaxis de to_tsquery
    if not terminos:
        return []
    rows = c.execute(
        "SELECT session_id, idx FROM fragmentos, to_tsquery('simple', %s) q WHERE tsv @@ q "
        "ORDER BY ts_rank(tsv, q) DESC LIMIT %s", (" | ".join(terminos), CANDIDATOS)).fetchall()
    return [(r["session_id"], r["idx"]) for r in rows]


def _fusionar(*rankings: list[tuple[str, int]]) -> list[tuple[str, int]]:
    puntaje: dict[tuple[str, int], float] = {}
    for ranking in rankings:
        for puesto, clave in enumerate(ranking):
            puntaje[clave] = puntaje.get(clave, 0.0) + 1 / (RRF_K + puesto + 1)
    return sorted(puntaje, key=lambda k: -puntaje[k])


def _sin_solapados(claves: list[tuple[str, int]], limite: int) -> list[tuple[str, int]]:
    """Dos fragmentos vecinos de la misma grabación dicen casi lo mismo: queda el mejor puntuado."""
    elegidos: list[tuple[str, int]] = []
    for sid, idx in claves:
        if any(s == sid and abs(i - idx) <= 1 for s, i in elegidos):
            continue
        elegidos.append((sid, idx))
        if len(elegidos) == limite:
            break
    return elegidos


def buscar(consulta: str, limite: int = RESULTADOS) -> list[dict]:
    """Los fragmentos más relevantes, con la grabación a la que pertenecen y el segundo donde arrancan."""
    consulta = (consulta or "").strip()[:LARGO_MAXIMO_CONSULTA]
    if not consulta or not db.vector_disponible:
        return []
    with db.conn() as c:
        claves = _sin_solapados(_fusionar(_por_significado(c, consulta), _por_palabras(c, consulta)), limite)
        if not claves:
            return []
        rows = c.execute(
            "SELECT f.session_id, f.idx, f.start_s, f.end_s, f.es, f.en, s.title, s.kind, s.code "
            "FROM fragmentos f JOIN sessions s ON s.id = f.session_id "
            "WHERE (f.session_id, f.idx) IN (SELECT * FROM unnest(%s::text[], %s::int[]))",
            ([sid for sid, _ in claves], [idx for _, idx in claves])).fetchall()
    por_clave = {(r["session_id"], r["idx"]): dict(r) for r in rows}
    return [por_clave[k] for k in claves if k in por_clave]
