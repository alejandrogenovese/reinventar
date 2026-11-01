"""Explorador por facetas sobre el catálogo en memoria.

- Dentro de una faceta los valores se combinan con O (Finanzas o Salud); entre facetas, con Y.
- Cada faceta cuenta ignorando su propio filtro (conteo disyuntivo): con "Finanzas" elegido se sigue viendo
  cuántas charlas sumaría "Salud".
- día y sede se evalúan sobre el mismo horario: "2026-12-02" + "Caesars Palace" = se da ese día en esa sede.
"""
from . import catalog, clusters

SESSION_FACETS = ("tema", "sector", "industria", "empresa", "seniority", "topico", "area", "servicio", "tipo", "nivel", "lanzamiento")
INSTANCE_FACETS = ("dia", "sede")
FACETS = SESSION_FACETS + INSTANCE_FACETS
GROUPS_LIMIT = 30
GROUP_RESULTS_LIMIT = 10

_PEOPLE_FIELD = {"sector": "sector", "industria": "industry", "empresa": "company", "seniority": "seniority"}
_SPLIT_FIELD = {"topico": "topic", "area": "aoi", "servicio": "services"}
_SORT_BY_VALUE = {"dia", "nivel"}

_entries: list[dict] | None = None
_entries_source: list | None = None
_entries_clusters = -1


def _session_values(s: dict) -> dict[str, set[str]]:
    values = {f: {p[k] for p in s.get("people", []) if p.get(k)} for f, k in _PEOPLE_FIELD.items()}
    values.update({f: set(catalog.split_field(s.get(k))) for f, k in _SPLIT_FIELD.items()})
    values["tipo"] = {s["type"]} if s.get("type") else set()
    values["nivel"] = {s["level"]} if s.get("level") else set()
    values["lanzamiento"] = {"Sí" if s.get("newlaunch") else "No"}
    tema = clusters.label_for(s["base"])
    values["tema"] = {tema} if tema else set()
    return values


def _entry(s: dict) -> dict:
    names = " ".join(p.get("name") or "" for p in s.get("people", []))
    text = " ".join(filter(None, (s.get("title"), s.get("abstract"), names, catalog._people_text(s))))
    instances = [(i["d"], (i.get("v") or "").split("|")[0].strip(), i) for i in s.get("instances", [])]
    return {"session": s, "values": _session_values(s), "instances": instances, "text": catalog.fold(text)}


def _all_entries() -> list[dict]:
    """Valores de faceta y texto normalizado por sesión; se recalcula si se recargó el catálogo o cambiaron los temas."""
    global _entries, _entries_source, _entries_clusters
    sessions = catalog.all_sessions()
    if _entries is None or _entries_source is not sessions or _entries_clusters != clusters.version():
        _entries, _entries_source, _entries_clusters = [_entry(s) for s in sessions], sessions, clusters.version()
    return _entries


def _matching_instances(entry: dict, filters: dict[str, set[str]], skip: str | None) -> list:
    """Horarios de la sesión que cumplen todos los filtros (menos `skip`); vacío si la sesión no entra."""
    for facet in SESSION_FACETS:
        selected = filters.get(facet)
        if selected and facet != skip and not (entry["values"][facet] & selected):
            return []
    days = filters.get("dia") if skip != "dia" else None
    venues = filters.get("sede") if skip != "sede" else None
    return [i for i in entry["instances"] if (not days or i[0] in days) and (not venues or i[1] in venues)]


def _values_for(facet: str, entry: dict, instances: list) -> set[str]:
    if facet == "dia":
        return {i[0] for i in instances}
    if facet == "sede":
        return {i[1] for i in instances if i[1]}
    return entry["values"][facet]


def _ranked(counter: dict[str, int], facet: str) -> list[dict]:
    key = (lambda kv: kv[0]) if facet in _SORT_BY_VALUE else (lambda kv: (-kv[1], kv[0]))
    return [{"value": v, "count": n} for v, n in sorted(counter.items(), key=key)]


def explore(filters: dict[str, set[str]], q: str = "", group_by: str | None = None, limit: int = 50, offset: int = 0) -> dict:
    needle = catalog.fold(q.strip())
    entries = [e for e in _all_entries() if not needle or needle in e["text"]]

    facets = {}
    for facet in FACETS:
        counter: dict[str, int] = {}
        for e in entries:
            instances = _matching_instances(e, filters, skip=facet)
            if instances:
                for value in _values_for(facet, e, instances):
                    counter[value] = counter.get(value, 0) + 1
        facets[facet] = _ranked(counter, facet)

    matched = [(e, inst) for e in entries if (inst := _matching_instances(e, filters, skip=None))]
    results = [catalog.card(e["session"], inst[0][2]) for e, inst in matched[offset:offset + limit]]
    out = {"total": len(matched), "results": results, "facets": facets}
    if group_by:
        out["groups"] = _groups(matched, group_by)
    return out


def _groups(matched: list, facet: str) -> list[dict]:
    """Resultados agrupados por los valores de una faceta (una charla puede estar en varios grupos)."""
    groups: dict[str, list] = {}
    for e, instances in matched:
        for value in _values_for(facet, e, instances):
            groups.setdefault(value, []).append((e, instances))
    ranked = sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0]))[:GROUPS_LIMIT]
    return [{"value": value, "count": len(items),
             "results": [catalog.card(e["session"], inst[0][2]) for e, inst in items[:GROUP_RESULTS_LIMIT]]}
            for value, items in ranked]
