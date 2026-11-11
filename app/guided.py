"""Armado guiado del día: después de cada charla elegida, qué conviene ver a continuación.

El orden es determinístico (afinidad con la ficha de la entrevista, cercanía y cuánto hay que irse antes); el LLM solo
escribe en una oración por qué le sirve cada opción. Cada opción trae su estado de traslado:
  a_tiempo     sale al terminar la anterior y llega con margen
  justo        llega con menos de MARGEN_JUSTO minutos de margen
  salir_antes  tiene que irse hasta SALIR_ANTES_MAX minutos antes de que termine la anterior
  se_superpone tiene que irse más que eso: se muestra igual, al final, como recomendación con aviso
Si la charla no está reservada en el portal de AWS hay que llegar COLA_SIN_RESERVA minutos antes (fila de walk-up).
"""
import logging
import re
from dataclasses import dataclass

from . import catalog, config, db, itinerary, llm, prompts, search, travel, venues
from .interview import Ficha

log = logging.getLogger("reinventar.guided")

SALIR_ANTES_MAX = 30
COLA_SIN_RESERVA = 30
MARGEN_JUSTO = 5
VENTANA_ANTES = 30       # candidatas que empiezan hasta 30 min antes de que termine la anterior
VENTANA_DESPUES = 180    # … y hasta 3 h después
VENTANA_PRIMERA = 120    # primera del día: las que empiezan en las 2 h siguientes a la más temprana
OPCIONES = 5
OPCIONES_ROJAS = 2
PAUSA_LIBRE_MIN = 90
ALMUERZO = (11 * 60 + 30, 13 * 60 + 30)
BUSQUEDA_TOP = 200

# Puntaje: afinidad con la ficha menos lo que cuesta llegar.
PESO_BUSQUEDA = 3.0       # similitud con la consulta de la ficha, normalizada 0..1
PESO_CLAVE = 1.0          # × peso de la prioridad (1..3) si aparece alguna de sus claves
PESO_NIVEL = 1.0
PESO_FORMATO = 0.8
PENALIDAD_EVITAR = 3.0
BONO_PENDIENTE = 10.0     # "☆ para otro día": vuelve primera cuando se repite
BONO_MISMA_SEDE = 0.5
PENALIDAD_POR_MIN_CAMINANDO = 0.03
PENALIDAD_POR_MIN_SALIR_ANTES = 0.05

A_TIEMPO, JUSTO, SALIR_ANTES, SE_SUPERPONE = "a_tiempo", "justo", "salir_antes", "se_superpone"
_CAMPOS_TEXTO = ("title", "services", "tech", "concepts", "concepts_en", "topic", "abstract")


class SinFicha(Exception):
    """La persona todavía no completó la entrevista."""


class ItemInexistente(LookupError):
    pass


def minutos(hhmm_: str) -> int:
    h, m = hhmm_.split(":")
    return int(h) * 60 + int(m)


def hhmm(total: int) -> str:
    return f"{total // 60:02d}:{total % 60:02d}"


# ---------- traslado ----------

@dataclass(frozen=True)
class Traslado:
    estado: str
    llegada: str              # hora a la que hay que estar: el inicio, o antes por la cola
    salir_a: str | None       # hora a la que hay que irse de la anterior, si es antes de que termine
    salir_antes_min: int      # cuánto antes de que termine la anterior (en rojo: cuánto se superpone)


def evaluar(fin_previa: int | None, inicio: int, viaje: int | None, reservada: bool) -> Traslado:
    llegada = inicio - (0 if reservada else COLA_SIN_RESERVA)
    if fin_previa is None:
        return Traslado(A_TIEMPO, hhmm(llegada), None, 0)
    salida = llegada - (viaje or 0)
    holgura = salida - fin_previa
    if holgura >= MARGEN_JUSTO:
        return Traslado(A_TIEMPO, hhmm(llegada), None, 0)
    if holgura >= 0:
        return Traslado(JUSTO, hhmm(llegada), None, 0)
    estado = SALIR_ANTES if -holgura <= SALIR_ANTES_MAX else SE_SUPERPONE
    return Traslado(estado, hhmm(llegada), hhmm(salida), -holgura)


def _viaje(a: dict | None, b: dict | None) -> travel.Viaje | None:
    """Minutos caminando entre dos lugares de tarjetas (charla, evento): por sede, o por coordenadas."""
    if not a or not b:
        return None
    ia, ib = venues.id_by_name(a.get("hotel")), venues.id_by_name(b.get("hotel"))
    medido = travel.viaje(ia, ib) if ia and ib else None
    if medido:
        return medido
    if a.get("lat") is None or b.get("lat") is None:
        return None
    return travel.Viaje(travel.estimar_minutos((a["lat"], a["lng"]), (b["lat"], b["lng"])), estimado=True)


# ---------- afinidad ----------

def _contiene(texto: str, frase: str) -> bool:
    """Frase entera, con o sin plural ("knowledge graph" está en "knowledge graphs"), pero no adentro de otra palabra
    ("AI" no está en "maintain")."""
    f = catalog.fold(frase).strip()
    return bool(f) and re.search(rf"(?<![a-z0-9]){re.escape(f)}(?:e?s)?(?![a-z0-9])", texto) is not None


def _nivel(session: dict) -> int | None:
    try:
        return int(session.get("level") or 0) or None
    except ValueError:
        return None


def afinidad(session: dict, ficha: Ficha, busqueda: float = 0.0, pendiente: bool = False) -> tuple[float, list[str]]:
    """(puntaje, temas de la ficha que toca). Solo mira la charla: el traslado se descuenta aparte."""
    texto = catalog.fold(" ".join(str(session.get(k) or "") for k in _CAMPOS_TEXTO))
    motivos = [p.tema for p in ficha.prioridades if any(_contiene(texto, c) for c in p.claves)]
    puntaje = PESO_BUSQUEDA * busqueda
    puntaje += sum(PESO_CLAVE * p.peso for p in ficha.prioridades if p.tema in motivos)
    nivel = _nivel(session)
    if nivel in ficha.nivel:
        puntaje += PESO_NIVEL
    elif nivel and nivel < min(ficha.nivel):
        puntaje -= PESO_NIVEL
    if session.get("type") in ficha.formatos:
        puntaje += PESO_FORMATO
    titulo_y_resumen = catalog.fold(f"{session.get('title') or ''} {session.get('abstract') or ''}")
    if any(_contiene(titulo_y_resumen, e) for e in ficha.evitar):
        puntaje -= PENALIDAD_EVITAR
    if pendiente:
        puntaje += BONO_PENDIENTE
    return puntaje, motivos


def _busqueda(ficha: Ficha) -> dict[str, float]:
    """Similitud (palabras + embeddings) de cada charla con la consulta de la ficha, normalizada a 0..1."""
    claves = " ".join(c for p in ficha.prioridades for c in p.claves)
    ranking = search.ranked(f"{ficha.consulta_busqueda} {claves}", BUSQUEDA_TOP)
    tope = max((score for _, score in ranking), default=0.0)
    return {s["base"]: score / tope for s, score in ranking if score > 0} if tope else {}


# ---------- opciones ----------

@dataclass(frozen=True)
class _Contexto:
    ficha: Ficha
    previa: dict | None
    inicio_previa: int | None
    fin_previa: int | None
    ocupado: list[tuple[int, int]]     # otros ítems del día (inicio, fin)
    agendadas: set[str]
    pendientes: dict[str, str]         # base → día en que se marcó
    busqueda: dict[str, float]


def _ficha(username: str) -> Ficha:
    guardada = db.get_interview(username)["ficha"]
    if not guardada:
        raise SinFicha("Primero completá la entrevista para que te conozcamos.")
    return Ficha(**guardada)


def _contexto(username: str, day: str, after: str | None) -> _Contexto:
    ficha = _ficha(username)
    del_dia = next((d["sessions"] for d in itinerary.get_current(username)["days"] if d["day"] == day), [])
    previa = None
    if after:
        previa = next((c for c in del_dia if c["code"] == after), None)
        if previa is None:
            raise ItemInexistente(f"{after} no está en tu itinerario de ese día")
    inicio_previa, fin_previa = itinerary._span(previa) if previa else (None, None)
    ocupado = [itinerary._span(c) for c in del_dia if c is not previa and c.get("start")]
    return _Contexto(ficha, previa, inicio_previa, fin_previa, ocupado,
                     {it["base"] for it in db.list_itinerary_items(username)},
                     {p["base"]: p["dia_marcada"] for p in db.list_pending(username)}, _busqueda(ficha))


def _libre(inicio: int, duracion: int, ocupado: list[tuple[int, int]]) -> bool:
    return all(not (inicio < fin and ini < inicio + duracion) for ini, fin in ocupado)


def _instancias_del_dia(day: str, ctx: _Contexto, desde: int) -> list[tuple[dict, dict]]:
    out = []
    for s in catalog.all_sessions():
        if s["base"] in ctx.agendadas:
            continue
        for inst in s.get("instances") or []:
            if inst["d"] != day or not inst.get("st"):
                continue
            inicio = minutos(inst["st"])
            if inicio >= desde and _libre(inicio, itinerary._duration(s.get("type")), ctx.ocupado):
                out.append((s, inst))
    return out


def _ventana(day: str, ctx: _Contexto, desde: str | None) -> list[tuple[dict, dict]]:
    if ctx.fin_previa is not None:
        tope = ctx.fin_previa + VENTANA_DESPUES
        return [(s, i) for s, i in _instancias_del_dia(day, ctx, ctx.fin_previa - VENTANA_ANTES)
                if minutos(i["st"]) <= tope]
    todas = _instancias_del_dia(day, ctx, minutos(desde) if desde else 0)
    if not todas:
        return []
    tope = min(minutos(i["st"]) for _, i in todas) + VENTANA_PRIMERA
    return [(s, i) for s, i in todas if minutos(i["st"]) <= tope]


def _opcion(session: dict, inst: dict, ctx: _Contexto) -> dict:
    card = {**catalog.card(session, inst), "kind": "talk"}
    card["end"] = itinerary._end(card)
    previa_lugar = (ctx.previa or {}).get("venue")
    v = _viaje(previa_lugar, card.get("venue")) if ctx.previa else None
    t = evaluar(ctx.fin_previa, minutos(card["start"]), v.minutos if v else None, reservada=False)
    af, motivos = afinidad(session, ctx.ficha, ctx.busqueda.get(session["base"], 0.0),
                           session["base"] in ctx.pendientes)
    misma_sede = bool(ctx.previa) and (previa_lugar or {}).get("hotel") == (card.get("venue") or {}).get("hotel")
    puntaje = (af - (v.minutos if v else 0) * PENALIDAD_POR_MIN_CAMINANDO
               - t.salir_antes_min * PENALIDAD_POR_MIN_SALIR_ANTES + (BONO_MISMA_SEDE if misma_sede else 0))
    return {"card": card, "estado": t.estado, "llegada": t.llegada, "salir_a": t.salir_a,
            "salir_antes_min": t.salir_antes_min, "viaje_min": v.minutos if v else None,
            "viaje_estimado": v.estimado if v else None, "misma_sede": misma_sede, "afinidad": round(af, 2),
            "puntaje": round(puntaje, 2), "motivos": motivos, "pendiente": ctx.pendientes.get(session["base"]),
            "razon": None}


def _posible(o: dict, ctx: _Contexto) -> bool:
    """Una roja que obliga a irse antes de que empiece la anterior no es una opción: es elegir otra cosa."""
    return ctx.inicio_previa is None or o["salir_antes_min"] < ctx.fin_previa - ctx.inicio_previa


def _mejor_por_charla(opciones_: list[dict]) -> list[dict]:
    mejor: dict[str, dict] = {}
    for o in opciones_:
        base = o["card"]["base"]
        if base not in mejor or o["puntaje"] > mejor[base]["puntaje"]:
            mejor[base] = o
    return list(mejor.values())


def _elegir(opciones_: list[dict]) -> list[dict]:
    """Las mejores OPCIONES que se llegan (con al menos una de la misma sede si hay) + al final las rojas que interesan
    más que alguna de esas (si no, no vale la pena recortar la anterior)."""
    llegables = sorted((o for o in opciones_ if o["estado"] != SE_SUPERPONE), key=lambda o: -o["puntaje"])
    elegidas = llegables[:OPCIONES]
    misma = next((o for o in llegables[OPCIONES:] if o["misma_sede"]), None)
    if misma and not any(o["misma_sede"] for o in elegidas):
        elegidas = elegidas[:OPCIONES - 1] + [misma]
    umbral = min((o["afinidad"] for o in elegidas), default=float("-inf"))
    rojas = sorted((o for o in opciones_ if o["estado"] == SE_SUPERPONE and o["afinidad"] > umbral),
                   key=lambda o: -o["afinidad"])
    return elegidas + rojas[:OPCIONES_ROJAS]


def _pausa(ctx: _Contexto, elegidas: list[dict]) -> str | None:
    """Sugerencia de bloque libre: almuerzo (si lo pidió en el ritmo) o un hueco largo hasta la próxima."""
    if ctx.fin_previa is None:
        return None
    if ctx.ficha.ritmo.almuerzo and ALMUERZO[0] <= ctx.fin_previa <= ALMUERZO[1]:
        return "almuerzo"
    llegables = [minutos(o["card"]["start"]) for o in elegidas if o["estado"] != SE_SUPERPONE]
    if not llegables or min(llegables) - ctx.fin_previa > PAUSA_LIBRE_MIN:
        return "libre"
    return None


def _razones(ficha_texto: str, elegidas: list[dict]) -> dict[str, str]:
    """Una oración por opción, en una sola llamada. Si el LLM falla, las opciones se muestran sin razón."""
    if not elegidas:
        return {}
    items = [{"code": o["card"]["code"], "title": o["card"]["title"], "type": o["card"]["type"],
              "level": o["card"]["level"], "resumen": (o["card"].get("abstract") or "")[:500]} for o in elegidas]
    try:
        data = llm.parse_json(llm.complete(config.GUIDED_MODEL, prompts.GUIDED_REASONS_SYSTEM,
                                           prompts.guided_reasons_user(ficha_texto, items), max_tokens=2000))
        return {str(r["code"]): str(r["razon"])[:300] for r in data.get("razones", []) if r.get("code")}
    except Exception as e:  # noqa: BLE001 - las razones son un extra: sin ellas el armado sigue
        log.warning("No se pudieron generar las razones del armado guiado: %s", e)
        return {}


def opciones(username: str, day: str, after: str | None = None, desde: str | None = None) -> dict:
    ctx = _contexto(username, day, after)
    candidatas = _mejor_por_charla([o for s, i in _ventana(day, ctx, desde) if _posible(o := _opcion(s, i, ctx), ctx)])
    elegidas = _elegir(candidatas)
    razones = _razones(db.get_interview(username)["ficha_texto"] or "", elegidas)
    previa = ctx.previa
    return {
        "day": day,
        "previa": {"code": previa["code"], "title": previa["title"], "end": previa.get("end")} if previa else None,
        "fin_previa": hhmm(ctx.fin_previa) if ctx.fin_previa is not None else None,
        "opciones": [{**o, "razon": razones.get(o["card"]["code"])} for o in elegidas],
        "pausa": _pausa(ctx, elegidas),
    }


# ---------- pendientes ("☆ Me interesa, para otro día") ----------

def pendientes(username: str) -> list[dict]:
    """Cada pendiente con todos sus horarios, para mostrar cuándo se repite."""
    out = []
    for p in db.list_pending(username):
        s = catalog.get_session(p["base"])
        if not s:
            continue
        horarios = [{"code": i["c"], "day": i["d"], "start": i["st"],
                     "venue": (venues.resolve(i.get("v", "")) or {}).get("hotel")} for i in s.get("instances") or []]
        out.append({"base": s["base"], "title": s["title"], "dia_marcada": p["dia_marcada"], "horarios": horarios})
    return out


def marcar_pendiente(username: str, base: str, day: str) -> None:
    if not catalog.get_session(base):
        raise ItemInexistente("Charla inexistente")
    db.add_pending(username, base, day)
