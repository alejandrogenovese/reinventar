"""«Tu re:Invent en números»: agregados del catálogo y de la agenda de cada persona, para los gráficos de la PWA.

Todo se calcula en memoria con funciones puras (listas y dicts adentro, dicts afuera), así se testea sin base:
- resumen_catalogo: charlas por día, día × hora, tipo, nivel, sede, tema, lanzamientos y walk-up. Se calcula una vez
  por carga del catálogo (catalogo() lo cachea mientras catalog.all_sessions() sea la misma lista).
- resumen_agenda: horas ocupadas (unión de intervalos), choques, «no llegás» (el hueco es menor que la caminata),
  minutos y metros caminando entre sedes, cobertura de la ficha de la entrevista y niveles.
Las duraciones de las charlas son estimadas por tipo (itinerary._DURATION_BY_TYPE): horas y choques son aproximados.
"""
from collections import Counter

from . import catalog, guided, itinerary, travel, venues

HORA_DESDE, HORA_HASTA = 8, 17      # columnas del heatmap (hora de inicio)
TOP_TIPOS, TOP_SEDES, TOP_TEMAS = 6, 5, 8
NIVELES = ("100", "200", "300", "400", "500")
KEYNOTE = "Keynote"
_CAMPOS_TEXTO = ("title", "services", "tech", "concepts", "concepts_en", "topic", "abstract")

_cache: dict | None = None
_cache_fuente: list | None = None


# ---------- catálogo ----------

def _top(contador: Counter, n: int, otros: str) -> list[dict]:
    """Los n más frecuentes y el resto sumado en «otros» (si hay)."""
    filas = [{"valor": v, "n": c} for v, c in contador.most_common() if v]
    resto = sum(f["n"] for f in filas[n:])
    return filas[:n] + ([{"valor": otros, "n": resto, "otros": True}] if resto else [])


def _hotel(instancia: dict) -> str:
    return (instancia.get("v") or "").split("|")[0].strip()


def _hora(instancia: dict) -> int | None:
    st = instancia.get("st") or ""
    return int(st[:2]) if st[:2].isdigit() else None


def _instancias(sessions: list[dict]):
    for s in sessions:
        for inst in s.get("instances") or []:
            yield s, inst


def _por_dia(sessions: list[dict]) -> dict:
    """Horarios por día, por día × hora, lanzamientos por día y sedes por día."""
    dias, dia_hora, lanzamientos, sedes = Counter(), {}, {}, {}
    for s, inst in _instancias(sessions):
        dia = inst.get("d")
        if not dia:
            continue
        dias[dia] += 1
        hora = _hora(inst)
        if hora is not None and HORA_DESDE <= hora <= HORA_HASTA:
            fila = dia_hora.setdefault(dia, [0] * (HORA_HASTA - HORA_DESDE + 1))
            fila[hora - HORA_DESDE] += 1
        if s.get("newlaunch"):
            lanzamientos.setdefault(dia, set()).add(s["base"])
        sedes.setdefault(dia, Counter())[_hotel(inst)] += 1
    orden = sorted(dias)
    return {
        "por_dia": [{"dia": d, "n": dias[d]} for d in orden],
        "horas": list(range(HORA_DESDE, HORA_HASTA + 1)),
        "dia_hora": [{"dia": d, "n": dia_hora.get(d, [0] * (HORA_HASTA - HORA_DESDE + 1))} for d in orden],
        "lanzamientos_por_dia": [{"dia": d, "n": len(lanzamientos.get(d, ()))} for d in orden],
        "sede_principal_por_dia": [{"dia": d, "sede": sedes[d].most_common(1)[0][0], "n": sedes[d].most_common(1)[0][1]}
                                   for d in orden],
    }


def resumen_catalogo(sessions: list[dict]) -> dict:
    """Agregados del catálogo. Las sedes y los días cuentan horarios (una charla repetida suma en cada uno); tipo,
    nivel y tema cuentan charlas."""
    instancias = list(_instancias(sessions))
    speakers = {p.get("id") or p.get("name") for s in sessions for p in s.get("people") or []} - {None, ""}
    tipos = Counter(s.get("type") or "" for s in sessions)
    niveles = Counter(s.get("level") or "" for s in sessions)
    temas = Counter(t for s in sessions for t in catalog.split_field(s.get("topic")))
    sedes = Counter(_hotel(i) for _, i in instancias)
    return {
        "charlas": len(sessions),
        "horarios": len(instancias),
        "speakers": len(speakers),
        "sedes": len([v for v in sedes if v]),
        "walk_up": sum(1 for _, i in instancias if i.get("walk")),
        "lanzamientos": sum(1 for s in sessions if s.get("newlaunch")),
        "por_tipo": _top(tipos, TOP_TIPOS, "Otros"),
        "por_sede": _top(sedes, TOP_SEDES, "Otras"),
        "por_tema": _top(temas, TOP_TEMAS, "Otros")[:TOP_TEMAS],
        "por_nivel": [{"valor": n, "n": niveles.get(n, 0)} for n in NIVELES],
        **_por_dia(sessions),
    }


def texto(session: dict) -> str:
    """Texto de una charla sin tildes ni mayúsculas, para buscar las claves de la ficha."""
    return catalog.fold(" ".join(str(session.get(k) or "") for k in _CAMPOS_TEXTO))


def catalogo() -> dict:
    """{"resumen", "textos": {base: texto}, "por_claves": memo de cobertura_ficha} del catálogo cargado; se recalcula
    si se recargó."""
    global _cache, _cache_fuente
    sessions = catalog.all_sessions()
    if _cache is None or _cache_fuente is not sessions:
        _cache = {"resumen": resumen_catalogo(sessions), "textos": {s["base"]: texto(s) for s in sessions},
                  "por_claves": {}}
        _cache_fuente = sessions
    return _cache


# ---------- agenda de la persona ----------

def _span(card: dict) -> tuple[int, int]:
    """(inicio, fin) en minutos; el fin estimado por tipo si la fuente no lo trae."""
    return itinerary._span({**card, "end": card.get("end") or itinerary._end(card)})


def minutos_ocupados(spans: list[tuple[int, int]]) -> int:
    """Minutos cubiertos por la unión de los intervalos: dos que se pisan no suman dos veces."""
    total, fin = 0, None
    for s, e in sorted(spans):
        if fin is None or s >= fin:
            total += e - s
            fin = e
        elif e > fin:
            total += e - fin
            fin = e
    return total


def choques(spans: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Pares (i, j) de índices que se pisan. Pegados (uno termina 11:00 y el otro empieza 11:00) no chocan."""
    return [(i, j) for i in range(len(spans)) for j in range(i + 1, len(spans))
            if spans[i][0] < spans[j][1] and spans[j][0] < spans[i][1]]


def _carriles(spans: list[tuple[int, int]], en_choque: set[int]) -> dict[int, int]:
    """Carril 0/1 de lo que choca, para dibujarlo apilado en la franja (con más de dos a la vez, van al 1)."""
    fines: list[int] = [-1, -1]
    carriles = {}
    for i in sorted(en_choque, key=lambda k: spans[k]):
        carril = 0 if fines[0] <= spans[i][0] else 1
        carriles[i] = carril
        fines[carril] = max(fines[carril], spans[i][1])
    return carriles


def _metros(a: dict, b: dict) -> int | None:
    ia, ib = venues.id_by_name(a.get("hotel")), venues.id_by_name(b.get("hotel"))
    medido = travel.metros_caminando(ia, ib) if ia and ib else None
    if medido is not None:
        return medido
    if a.get("lat") is None or b.get("lat") is None:
        return None
    return round(travel.metros((a["lat"], a["lng"]), (b["lat"], b["lng"])) * travel.FACTOR_RODEO)


def _tramo(previa: dict, siguiente: dict) -> dict | None:
    """Caminata de una sede a otra entre dos ítems seguidos; None si es la misma sede o no se sabe dónde quedan."""
    a, b = previa.get("venue") or {}, siguiente.get("venue") or {}
    if not a.get("hotel") or not b.get("hotel") or a["hotel"] == b["hotel"]:
        return None
    v = guided.viaje_entre(a, b)
    return {"minutos": v.minutos, "metros": _metros(a, b) or 0, "desde": a["hotel"], "hasta": b["hotel"]} if v else None


def _resumen(card: dict) -> dict:
    return {"code": card.get("code"), "title": card.get("title"), "start": card.get("start"),
            "hotel": (card.get("venue") or {}).get("hotel")}


def _caminatas(cards: list[dict], spans: list[tuple[int, int]]) -> tuple[list[dict], set[int]]:
    """Tramos entre ítems seguidos que no se pisan, y los índices a los que no se llega (el hueco es menor que la
    caminata)."""
    tramos, no_llega = [], set()
    for i in range(1, len(cards)):
        hueco = spans[i][0] - spans[i - 1][1]
        tramo = _tramo(cards[i - 1], cards[i]) if hueco >= 0 else None
        if not tramo:
            continue
        tramo = {**tramo, "hueco": hueco, "previa": _resumen(cards[i - 1]), "siguiente": _resumen(cards[i])}
        tramos.append(tramo)
        if hueco < tramo["minutos"]:
            no_llega.add(i)
    return tramos, no_llega


def resumen_dia(dia: str, cards: list[dict]) -> dict:
    """Un día de la agenda: ítems con sus marcas para la franja, choques, «no llegás» y caminata."""
    cards = sorted((c for c in cards if c.get("start")), key=lambda c: c["start"])
    spans = [_span(c) for c in cards]
    pares = choques(spans)
    en_choque = {k for par in pares for k in par}
    carriles = _carriles(spans, en_choque)
    tramos, no_llega = _caminatas(cards, spans)
    items = [{**_resumen(c), "end": f"{e // 60:02d}:{e % 60:02d}", "kind": c.get("kind") or "talk",
              "keynote": c.get("type") == KEYNOTE, "choque": i in en_choque, "carril": carriles.get(i),
              "no_llegas": i in no_llega, "inicio_min": s, "fin_min": e}
             for i, (c, (s, e)) in enumerate(zip(cards, spans, strict=True))]
    return {
        "dia": dia, "items": items, "minutos_ocupados": minutos_ocupados(spans),
        "choques": [{"a": _resumen(cards[i]), "b": _resumen(cards[j])} for i, j in pares],
        "tramos": tramos,
        "no_llegas": [t for t in tramos if t["hueco"] < t["minutos"]],
        "caminata_min": sum(t["minutos"] for t in tramos),
        "caminata_m": sum(t["metros"] for t in tramos),
        "tramo_mas_largo": max(tramos, key=lambda t: t["minutos"], default=None),
    }


def _tocan(textos: list[str], claves: list[str]) -> int:
    return sum(1 for t in textos if any(guided.contiene(t, clave) for clave in claves))


def cobertura_ficha(ficha: dict | None, charlas: list[dict], textos: dict[str, str],
                    memo: dict | None = None) -> dict | None:
    """Cuántas charlas agendadas tocan cada prioridad de la ficha (por sus claves, sin tildes ni mayúsculas), y cuántas
    hay en el catálogo (memo guarda ese conteo por claves: recorre todo el catálogo). None si no hizo la entrevista."""
    if not ficha or not ficha.get("prioridades"):
        return None
    memo = {} if memo is None else memo
    agendadas = [textos.get(c.get("base")) or catalog.fold(c.get("title")) for c in charlas]
    catalogo_ = list(textos.values())

    def en_catalogo(claves: list[str]) -> int:
        clave = tuple(claves)
        if clave not in memo:
            memo[clave] = _tocan(catalogo_, claves)
        return memo[clave]

    prioridades = [{"tema": p["tema"], "peso": p.get("peso", 1), "agendadas": _tocan(agendadas, p.get("claves") or []),
                    "en_catalogo": en_catalogo(p.get("claves") or [])}
                   for p in ficha["prioridades"]]
    return {"prioridades": prioridades, "sin_cubrir": [p["tema"] for p in prioridades if not p["agendadas"]],
            "charlas": len(charlas), "nivel": ficha.get("nivel") or []}


def resumen_agenda(dias: list[dict], ficha: dict | None, textos: dict[str, str], memo: dict | None = None) -> dict:
    """La semana de la persona. dias: [{"day", "sessions": [tarjetas]}] como los devuelve itinerary.get_current."""
    por_dia = [resumen_dia(d["day"], d["sessions"]) for d in dias]
    tarjetas = [c for d in dias for c in d["sessions"]]
    charlas = [c for c in tarjetas if (c.get("kind") or "talk") == "talk"]
    niveles = Counter(c.get("level") for c in charlas)
    return {
        "total": len(tarjetas),
        "charlas": sum(1 for c in charlas if c.get("type") != KEYNOTE),
        "keynotes": sum(1 for c in charlas if c.get("type") == KEYNOTE),
        "eventos": len(tarjetas) - len(charlas),
        "dias": por_dia,
        "minutos_ocupados": sum(d["minutos_ocupados"] for d in por_dia),
        "choques": sum(len(d["choques"]) for d in por_dia),
        "no_llegas": sum(len(d["no_llegas"]) for d in por_dia),
        "caminata_min": sum(d["caminata_min"] for d in por_dia),
        "caminata_m": sum(d["caminata_m"] for d in por_dia),
        "ficha": cobertura_ficha(ficha, charlas, textos, memo),
        "niveles": [{"valor": n, "n": niveles.get(n, 0)} for n in NIVELES if niveles.get(n)],
    }
