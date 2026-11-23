"""Estado del servicio para el banner de la PWA: reglas puras que convierten señales en avisos.

Las señales (grabaciones en proceso, hilo del pipeline, revisiones de las fuentes) las junta app/estado_api.py; acá solo
se decide, sin base ni red, así que se prueba con datos armados. Nunca se llama a un modelo: las fallas del LLM salen de
un contador en memoria que alimenta app/llm.py cuando una llamada falla.
"""
import datetime as dt
import threading
import time
from collections import deque
from dataclasses import dataclass

HORA_S = 3600
MINUTOS_DEMORA_TRANSCRIPCION = 20  # una grabación procesándose sin moverse hace más de esto: «demorado»
ERRORES_PARA_CAIDA = 3             # grabaciones con error en la última hora para dar la transcripción por caída
VENTANA_ERRORES_S = HORA_S
FALLAS_LLM_PARA_CAIDA = 3          # llamadas al LLM fallidas en la ventana para dar los resúmenes por caídos
VENTANA_FALLAS_LLM_S = 15 * 60
MAX_FALLAS_GUARDADAS = 100         # tope del contador: alcanza de sobra para el umbral
# Mismos umbrales que estadoFuente en web/js/adminAtencion.js.
FACTOR_ATRASO = 3                  # una fuente está atrasada si pasó 3 veces su intervalo sin revisarse
HORAS_CATALOGO = 3                 # el catálogo oficial se revisa cada 3 h (app/charlas_auto.py)
FUENTE_CATALOGO = "catalogo"

CAIDO, DEMORADO, ATRASADO = "caido", "demorado", "atrasado"
ORDEN_SERVICIOS = ("transcripcion", "resumenes", "eventos", "catalogo")


@dataclass(frozen=True)
class Senales:
    """Lo que se mira para armar el estado. None en una señal = no se pudo leer: esa regla no avisa nada."""
    ahora: float                                  # epoch
    pipeline_vivo: bool | None = True
    procesando: tuple[float, ...] | None = ()     # updated_at (epoch) de las grabaciones en proceso
    errores_ultima_hora: int | None = 0
    fallas_llm: tuple[float, ...] = ()            # epoch de cada falla del LLM
    eventos: dict | None = None                   # lo que devuelve eventos_auto.estado()


def iso(ts: float) -> str:
    return dt.datetime.fromtimestamp(ts, dt.UTC).isoformat(timespec="seconds")


def _aviso(servicio: str, nivel: str, desde: float | None = None, detalle_horas: int | None = None) -> dict:
    return {"id": servicio, "nivel": nivel, "desde": iso(desde) if desde is not None else None,
            "detalle_horas": detalle_horas}


def transcripcion(s: Senales) -> dict | None:
    if s.pipeline_vivo is False:
        return _aviso("transcripcion", CAIDO)
    if s.errores_ultima_hora is not None and s.errores_ultima_hora >= ERRORES_PARA_CAIDA:
        return _aviso("transcripcion", CAIDO)
    trabadas = [t for t in s.procesando or () if s.ahora - t > MINUTOS_DEMORA_TRANSCRIPCION * 60]
    return _aviso("transcripcion", DEMORADO, min(trabadas)) if trabadas else None


def resumenes(s: Senales) -> dict | None:
    recientes = [t for t in s.fallas_llm if s.ahora - t <= VENTANA_FALLAS_LLM_S]
    return _aviso("resumenes", CAIDO, min(recientes)) if len(recientes) >= FALLAS_LLM_PARA_CAIDA else None


def _epoch(valor) -> float | None:
    if isinstance(valor, dt.datetime):
        return valor.timestamp()
    if isinstance(valor, str) and valor:
        try:
            return dt.datetime.fromisoformat(valor).timestamp()
        except ValueError:
            return None
    return None


def revision_atrasada(revision: dict, horas: float | None, ahora: float) -> float | None:
    """Epoch de la última revisión si la fuente está atrasada; None si está al día, si falló (eso lo ve el admin) o si
    no hay fecha. Port de estadoFuente (web/js/adminAtencion.js)."""
    if not revision.get("ok"):
        return None
    esperado = HORAS_CATALOGO if revision.get("fuente") == FUENTE_CATALOGO else horas
    revisado = _epoch(revision.get("revisado"))
    if not esperado or revisado is None:
        return None
    return revisado if (ahora - revisado) / HORA_S > esperado * FACTOR_ATRASO else None


def _atraso(servicio: str, revisados: list[float], ahora: float) -> dict | None:
    if not revisados:
        return None
    mas_vieja = min(revisados)
    return _aviso(servicio, ATRASADO, mas_vieja, int((ahora - mas_vieja) // HORA_S))


def fuentes(s: Senales) -> list[dict]:
    """eventos (Luma, conferenceparties, Ticketmaster…) y catalogo (charlas oficiales), como en Admin › Estado: si la
    revisión automática está apagada, nada está atrasado."""
    e = s.eventos
    if not e or not e.get("activo"):
        return []
    atrasos = [(r.get("fuente"), revision_atrasada(r, e.get("horas"), s.ahora)) for r in e.get("revisiones") or ()]
    eventos = [t for f, t in atrasos if t is not None and f != FUENTE_CATALOGO]
    catalogo = [t for f, t in atrasos if t is not None and f == FUENTE_CATALOGO]
    return [a for a in (_atraso("eventos", eventos, s.ahora), _atraso("catalogo", catalogo, s.ahora)) if a]


def servicio(s: Senales) -> list[dict]:
    """Los avisos activos: primero los caídos, después demorados y atrasados; dentro de cada grupo, en ORDEN_SERVICIOS."""
    avisos = [a for a in (transcripcion(s), resumenes(s)) if a] + fuentes(s)
    return sorted(avisos, key=lambda a: (a["nivel"] != CAIDO, ORDEN_SERVICIOS.index(a["id"])))


# --- contador de fallas del LLM (en memoria, por proceso) ---------------------------------------------------------------

_fallas_llm: dict[str, deque[float]] = {}
_lock = threading.Lock()


def registrar_falla_llm(contexto: str, ahora: float | None = None) -> None:
    """Anota una llamada al LLM que falló. contexto = "real" o "prueba": las del modo prueba no tiñen el estado real."""
    momento = time.time() if ahora is None else ahora
    with _lock:
        _fallas_llm.setdefault(contexto, deque(maxlen=MAX_FALLAS_GUARDADAS)).append(momento)


def fallas_llm(contexto: str, ahora: float | None = None) -> tuple[float, ...]:
    """Las fallas de la ventana (VENTANA_FALLAS_LLM_S)."""
    momento = time.time() if ahora is None else ahora
    with _lock:
        return tuple(t for t in _fallas_llm.get(contexto, ()) if momento - t <= VENTANA_FALLAS_LLM_S)


def reiniciar_fallas_llm() -> None:
    with _lock:
        _fallas_llm.clear()
