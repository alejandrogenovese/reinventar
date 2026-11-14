"""Catálogo oficial de re:Invent → filas del schema reinvent. Funciones puras, sin base (salvo bajar_buscador, que pide
el buscador público por HTTP).

Lo usan scripts/actualizar_catalogo.py (con sessions_full.json, la carga manual) y app/charlas_auto.py (con el buscador
público catalog.awsevents.com/api/search, sin login: la revisión automática de bajas y cambios).

En el JSON cada item es UN horario: las repeticiones (-R, -R1…) vienen como items aparte, cada uno con su sessionID y
su sessionTimeID. La charla se identifica por el código base (el código sin el sufijo -R\\d*).
Los speakers se identifican por participants[].userRef: el nombre no alcanza porque hay homónimos.
"""
import datetime as dt
import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass

LIST_SEP = ";"  # mismo separador que usa la app para area_interes y formato mientras sean texto
_SUFIJO_REPETICION = re.compile(r"-R\d*$")
_PARENTESIS = re.compile(r"\([^)]*\)")
_NO_ALFANUM = re.compile(r"[^a-z0-9]")
_NIVEL = re.compile(r"(\d{3})")
_AMAZON = "amazon"


@dataclass(frozen=True)
class Charla:
    id_speech: str
    titulo: str
    tipo: str
    nivel: int | None
    topicos: tuple[str, ...]
    servicios: tuple[str, ...]
    area_interes: str | None
    formato: str | None
    roles: tuple[str, ...]
    industria: tuple[str, ...]
    es_lanzamiento: bool
    es_sponsoreada: bool
    speakers_ocultos: bool
    duracion_min: int | None
    resumen: str | None
    speakers_original: str | None
    modificado: dt.datetime | None


@dataclass(frozen=True)
class Horario:
    codigo: str
    id_speech: str
    fecha: dt.date
    hora_inicio: dt.time
    hora_fin: dt.time | None
    sede: str
    sala: str | None
    cupo: int | None
    walk_up: bool
    aws_session_id: str
    aws_time_id: str


@dataclass(frozen=True)
class Participacion:
    id_speech: str
    aws_speaker_id: str
    nombre: str
    orden: int
    rol: str | None
    cargo: str | None
    empresa_original: str | None


@dataclass(frozen=True)
class Catalogo:
    charlas: tuple[Charla, ...]
    horarios: tuple[Horario, ...]
    participaciones: tuple[Participacion, ...]


def codigo_base(codigo: str) -> str:
    return _SUFIJO_REPETICION.sub("", codigo.strip())


def clave(nombre: str) -> str:
    """Clave para reconocer a la misma persona aunque AWS cambie cómo la escribe: sin tildes, mayúsculas,
    agregados entre paréntesis ("(AWS)", apodos), espacios ni guiones."""
    sin_parentesis = _PARENTESIS.sub(" ", nombre or "")
    sin_tildes = "".join(c for c in unicodedata.normalize("NFKD", sin_parentesis) if not unicodedata.combining(c))
    return _NO_ALFANUM.sub("", sin_tildes.lower()) or (nombre or "").strip().lower()


def _limpio(texto: str | None) -> str:
    return re.sub(r"\s+", " ", (texto or "").replace(" ", " ")).strip()


def _o_none(texto: str | None) -> str | None:
    return _limpio(texto) or None


def _atributos(item: dict) -> dict[str, list[str]]:
    out: dict[str, list[str]] = defaultdict(list)
    for a in item.get("attributevalues") or []:
        valor = _limpio(a.get("value"))
        if valor and valor not in out[a["attribute"]]:
            out[a["attribute"]].append(valor)
    return out


def _nivel(valores: list[str]) -> int | None:
    m = _NIVEL.match(valores[0]) if valores else None
    return int(m.group(1)) if m else None


def _sede_y_sala(room: str | None) -> tuple[str, str | None]:
    """'MGM Grand | Level 3 | Premier 311' → ('MGM Grand', 'Level 3 · Premier 311')."""
    partes = [p.strip() for p in (room or "").split("|") if p.strip()]
    return (partes[0], " · ".join(partes[1:]) or None) if partes else ("", None)


def _es_sponsoreada(codigo: str, attrs: dict) -> bool:
    return "Sponsored" in attrs.get("Session Appendices", []) or codigo_base(codigo).endswith("-S")


def _charla(item: dict, attrs: dict, nombres: list[str]) -> Charla:
    codigo = item["code"].strip()
    return Charla(
        id_speech=codigo_base(codigo),
        titulo=_limpio(item.get("title")),
        tipo=_limpio(item.get("type")),
        nivel=_nivel(attrs.get("Level", [])),
        topicos=tuple(attrs.get("Topic", [])),
        servicios=tuple(attrs.get("Services", [])),
        area_interes=LIST_SEP.join(attrs.get("Area of Interest", [])) or None,
        formato=LIST_SEP.join(attrs.get("Features", [])) or None,
        roles=tuple(attrs.get("Role", [])),
        industria=tuple(attrs.get("Industry", [])),
        es_lanzamiento=bool(attrs.get("New launch sessions")),
        es_sponsoreada=_es_sponsoreada(codigo, attrs),
        speakers_ocultos=attrs.get("Hide Speakers?") == ["Yes"],
        duracion_min=int(item.get("length") or 0) or None,
        resumen=_o_none(item.get("abstract")),
        speakers_original=", ".join(nombres) or None,
        modificado=dt.datetime.fromisoformat(item["modified"]) if item.get("modified") else None,
    )


def _horario(item: dict, attrs: dict, t: dict | None = None) -> Horario:
    t = t or item["times"][0]
    sede, sala = _sede_y_sala(t.get("room"))
    cupo = str(t.get("capacity") or "")
    return Horario(
        codigo=item["code"].strip(),
        id_speech=codigo_base(item["code"]),
        fecha=dt.date.fromisoformat(t["date"]),
        hora_inicio=dt.time.fromisoformat(t["startTime"]),
        hora_fin=dt.time.fromisoformat(t["endTime"]) if t.get("endTime") else None,
        sede=sede or (attrs.get("Venue") or ["Sin sede"])[0],
        sala=sala,
        cupo=int(cupo) if cupo.isdigit() else None,
        walk_up=bool(attrs.get("Walk up only session")),
        aws_session_id=item["sessionID"],
        aws_time_id=t["sessionTimeID"],
    )


def _personas(item: dict) -> list[dict]:
    validas = [p for p in item.get("participants") or [] if p.get("userRef") and _limpio(p.get("globalFullName"))]
    return sorted(validas, key=lambda p: float(p.get("displayorder") or 0))


def _validar_ids_unicos(horarios: list[Horario]) -> None:
    """sessionID y sessionTimeID identifican el horario: repetidos entre códigos distintos romperían el match."""
    for nombre, valores in (("sessionTimeID", [h.aws_time_id for h in horarios]),
                            ("sessionID", [h.aws_session_id for h in horarios])):
        repetidos = sorted({v for v in valores if valores.count(v) > 1})
        if repetidos:
            raise ValueError(f"{nombre} repetido entre códigos distintos: {', '.join(repetidos[:10])}")


def parsear(crudo: dict) -> Catalogo:
    """Agrupa los horarios por charla. Para los datos de la charla y el orden de los speakers gana el item
    modificado más recientemente; los speakers de todas las repeticiones se suman."""
    items = [it for sec in crudo.get("sectionList", []) for it in sec.get("items", []) if it.get("times")]
    con_varios = [it["code"] for it in items if len(it["times"]) > 1]
    if con_varios:
        raise ValueError(f"Items con más de un horario (no soportado): {', '.join(con_varios[:10])}")
    charlas: dict[str, Charla] = {}
    horarios: dict[str, Horario] = {}  # por código: si AWS lo repite, gana el más reciente
    participaciones: dict[tuple[str, str], Participacion] = {}

    for item in sorted(items, key=lambda x: x.get("modified") or ""):
        attrs = _atributos(item)
        personas = _personas(item)
        charla = _charla(item, attrs, [_limpio(p["globalFullName"]) for p in personas])
        charlas[charla.id_speech] = charla
        horario = _horario(item, attrs)
        horarios[horario.codigo] = horario
        for orden, p in enumerate(personas):
            participaciones[(charla.id_speech, p["userRef"])] = Participacion(
                id_speech=charla.id_speech,
                aws_speaker_id=p["userRef"],
                nombre=_limpio(p["globalFullName"]),
                orden=orden,
                rol=_o_none(p.get("roles")),
                cargo=_o_none(p.get("globalJobtitle") or p.get("jobTitle")),
                empresa_original=_o_none(p.get("companyName") or p.get("globalCompany")),
            )

    _validar_ids_unicos(list(horarios.values()))
    return Catalogo(
        charlas=tuple(sorted(charlas.values(), key=lambda c: c.id_speech)),
        horarios=tuple(sorted(horarios.values(), key=lambda h: (h.fecha, h.hora_inicio, h.codigo))),
        participaciones=tuple(sorted(participaciones.values(), key=lambda p: (p.id_speech, p.orden))),
    )


# ---------- Buscador público (catalog.awsevents.com/api/search) ----------

URL_BUSCADOR = "https://catalog.awsevents.com/api/search"
# Perfil público del catálogo web de AWS (va en el JavaScript de la página): no es una credencial ni toca ninguna cuenta.
PERFIL_BUSCADOR = "W7g1iXGSnubuepOruvDWMM9ecuUXKP4v"
POR_PAGINA_BUSCADOR = 50     # el buscador devuelve como mucho 50 por pedido aunque se le pida más
MAX_PAGINAS_BUSCADOR = 120   # ~6000 horarios: más que eso es un buscador que no corta


class BuscadorRoto(ValueError):
    """El buscador respondió algo que no se puede leer (o vino incompleto)."""


def pagina_del_buscador(datos: dict) -> tuple[list[dict], int]:
    """(items, total). La primera página viene en sectionList; las siguientes, en items sueltos."""
    if str(datos.get("responseCode")) != "0":
        raise BuscadorRoto(f"responseCode {datos.get('responseCode')!r}: {str(datos.get('responseMessage'))[:100]}")
    if "sectionList" in datos:
        secciones = datos["sectionList"] or []
        items = [it for sec in secciones for it in sec.get("items") or []]
        total = datos.get("totalSearchItems", secciones[0].get("total") if secciones else 0)
    else:
        items, total = datos.get("items"), datos.get("total")
    if not isinstance(items, list) or not isinstance(total, int):
        raise BuscadorRoto("la respuesta no trae items ni total")
    return items, total


def bajar_buscador(http, pausa) -> list[dict]:
    """Todos los items del buscador, de a POR_PAGINA_BUSCADOR, con una pausa entre pedidos. http: httpx.Client."""
    items: list[dict] = []
    total = 0
    for _ in range(MAX_PAGINAS_BUSCADOR):
        r = http.post(URL_BUSCADOR, data={"type": "session", "size": str(POR_PAGINA_BUSCADOR), "from": str(len(items))},
                      headers={"rfApiProfileId": PERFIL_BUSCADOR})
        r.raise_for_status()
        pagina, total = pagina_del_buscador(r.json())
        items += pagina
        if not pagina or len(items) >= total:
            break
        pausa()
    if len(items) < total:
        raise BuscadorRoto(f"vino incompleto: {len(items)} de {total}")
    return items


def leer_buscador(items: list[dict]) -> tuple[list[Horario], dict[str, Charla]]:
    """(horarios, charlas por código base). A diferencia de parsear(), no corta por un item raro: uno con varios
    horarios da varios Horario (con el mismo código; quien compara se queda con uno) y uno sin horarios no da ninguno.
    Si un sessionTimeID se repite, gana el item modificado más recientemente."""
    horarios: dict[str, Horario] = {}
    charlas: dict[str, Charla] = {}
    for item in sorted(items, key=lambda x: x.get("modified") or ""):
        if not item.get("times"):
            continue
        attrs = _atributos(item)
        for t in item["times"]:
            h = _horario(item, attrs, t)
            horarios[h.aws_time_id] = h
        charla = _charla(item, attrs, [_limpio(p["globalFullName"]) for p in _personas(item)])
        charlas[charla.id_speech] = charla
    return sorted(horarios.values(), key=lambda h: (h.fecha, h.hora_inicio, h.codigo)), charlas


# ---------- Speakers: id de AWS primero, nombre como respaldo ----------

@dataclass(frozen=True)
class SpeakerExistente:
    id_speaker: int
    nombre: str
    nombre_clave: str
    aws_speaker_id: str | None
    empresa_perfil: str | None  # speaker_perfil.empresa_actual (Crustdata), para desempatar homónimos


@dataclass(frozen=True)
class SpeakerOficial:
    aws_speaker_id: str
    nombre: str
    empresas: frozenset[str]
    charlas: int


@dataclass(frozen=True)
class SpeakerNuevo:
    aws_speaker_id: str
    nombre: str
    nombre_clave: str


@dataclass(frozen=True)
class Homonimo:
    nombre: str
    id_speaker: int
    aws_speaker_id: str
    otros: tuple[str, ...]
    criterio: str


@dataclass(frozen=True)
class PlanSpeakers:
    asignados: dict[str, int]          # userRef → id_speaker existente
    ids_completados: dict[int, str]    # id_speaker que recibe su userRef por primera vez
    nuevos: tuple[SpeakerNuevo, ...]
    homonimos: tuple[Homonimo, ...]


def speakers_oficiales(cat: Catalogo) -> list[SpeakerOficial]:
    por_ref: dict[str, list[Participacion]] = defaultdict(list)
    for p in cat.participaciones:
        por_ref[p.aws_speaker_id].append(p)
    return [SpeakerOficial(ref, ps[-1].nombre, frozenset(p.empresa_original for p in ps if p.empresa_original),
                           len({p.id_speech for p in ps}))
            for ref, ps in sorted(por_ref.items())]


def _empresa_clave(empresa: str) -> str:
    k = clave(empresa)
    return _AMAZON if k.startswith(("amazon", "aws")) else k


def _coincide_empresa(perfil: str | None, empresas: frozenset[str]) -> bool:
    p = _empresa_clave(perfil or "")
    return bool(p) and any((e := _empresa_clave(x)) and (e in p or p in e) for x in empresas)


def _elegir_homonimo(existente: SpeakerExistente, candidatos: list[SpeakerOficial]) -> tuple[SpeakerOficial, str]:
    """El speaker existente (con su perfil) queda con quien coincide la empresa del perfil. Si no se puede decidir
    por empresa, con quien tiene más charlas, y el caso queda marcado para revisar a mano."""
    por_perfil = [c for c in candidatos if _coincide_empresa(existente.empresa_perfil, c.empresas)]
    if len(por_perfil) == 1:
        return por_perfil[0], "empresa del perfil"
    elegido = max(candidatos, key=lambda c: (c.charlas, c.aws_speaker_id))
    if not existente.empresa_perfil:
        return elegido, "más charlas (sin perfil)"
    motivo = "varios coinciden con" if por_perfil else "ninguno coincide con"
    return elegido, f"más charlas: revisar, {motivo} el perfil ({existente.empresa_perfil})"


def _libres_por_clave(existentes: list[SpeakerExistente]) -> dict[str, SpeakerExistente]:
    libres: dict[str, SpeakerExistente] = {}
    for e in sorted(existentes, key=lambda e: e.id_speaker):
        if e.aws_speaker_id is None:
            for k in (e.nombre_clave, clave(e.nombre)):
                libres.setdefault(k, e)
    return libres


def planear_speakers(existentes: list[SpeakerExistente], oficiales: list[SpeakerOficial]) -> PlanSpeakers:
    por_aws = {e.aws_speaker_id: e.id_speaker for e in existentes if e.aws_speaker_id}
    libres = _libres_por_clave(existentes)
    grupos: dict[str, list[SpeakerOficial]] = defaultdict(list)
    for o in oficiales:
        grupos[clave(o.nombre)].append(o)

    asignados = {o.aws_speaker_id: por_aws[o.aws_speaker_id] for o in oficiales if o.aws_speaker_id in por_aws}
    completados: dict[int, str] = {}
    nuevos: list[SpeakerNuevo] = []
    homonimos: list[Homonimo] = []

    for k, grupo in sorted(grupos.items()):
        candidatos = [o for o in grupo if o.aws_speaker_id not in por_aws]
        existente = libres.get(k)
        if existente is not None and existente.id_speaker in completados:
            existente = None
        elegido = None
        if candidatos and existente is not None:
            if len(grupo) == 1 or (len(candidatos) == 1 and not existente.empresa_perfil):
                elegido = candidatos[0]
            else:
                elegido, criterio = _elegir_homonimo(existente, candidatos)
                otros = tuple(c.aws_speaker_id for c in candidatos if c is not elegido)
                homonimos.append(Homonimo(elegido.nombre, existente.id_speaker, elegido.aws_speaker_id, otros, criterio))
            asignados[elegido.aws_speaker_id] = existente.id_speaker
            completados[existente.id_speaker] = elegido.aws_speaker_id
        nuevos.extend(SpeakerNuevo(c.aws_speaker_id, c.nombre, clave(c.nombre)) for c in candidatos if c is not elegido)

    return PlanSpeakers(asignados, completados, tuple(nuevos), tuple(homonimos))
