"""«Mi ficha»: qué le falta completar a la persona y qué conviene avisarle en el banner. Reglas puras, sin base ni red: los
datos los junta app/ficha_api.py y acá solo se decide, así que se prueba con datos armados.

Prioridad (1 es la más importante), pensada para lo que sirve antes de llegar a Las Vegas el 29/11:
  1 vuelo de ida      sin él no hay check-in, demoras ni «Próximo» del viaje.
  2 vuelo de vuelta   lo mismo para la vuelta; es lo único del viaje que sigue sirviendo una vez allá.
  3 hotel             para «Llevame» al hotel y los avisos de check-in y check-out.
  4 notificaciones    depende del permiso del navegador en cada dispositivo: lo decide el front (web/js/fichaReglas.js).
  5 documentos        pasaporte o ESTA a mano sin señal (solo si no subió ninguno).
  6 perfil            mejora las recomendaciones, pero la app anda sin él.
  7 pendientes        la checklist del viaje.
  8 agenda            charlas fijadas o la lista del Excel.
  9 passkey           solo en la ficha: entrar con huella o cara es cómodo, pero no se insiste en el banner.

En el banner: antes de la estadía, todos menos la passkey; durante la estadía (29/11 al 7/12, app/estadia.py) solo lo
crítico (la vuelta y las notificaciones: avisos de salida, demoras y check-in); después del viaje, nada.
"""
import datetime as dt
from dataclasses import asdict, dataclass

from . import estadia

# Un vuelo hasta el primer día de re:Invent es de ida; desde el último, de vuelta.
DIA_PRIMERA_CHARLA = dt.date(2026, 11, 30)
DIA_ULTIMA_CHARLA = dt.date(2026, 12, 4)

ANTES, DURANTE, DESPUES = "antes", "durante", "despues"

LINK_VIAJES = "#/viajes"
LINK_DOCUMENTOS = "#/viajes/documentos"
LINK_PENDIENTES = "#/viajes/pendientes"
LINK_PERFIL = "#/itinerario/entrevista"
LINK_AGENDA = "#/itinerario"
LINK_AJUSTES = "#/ajustes"


@dataclass(frozen=True)
class DatosFicha:
    """Lo que se sabe de la persona. Las fechas de vuelo van como texto ISO (YYYY-MM-DD), como en viajes_vuelos."""
    perfil_completo: bool = False
    fechas_vuelos: tuple[str, ...] = ()
    hoteles: int = 0
    documentos: int = 0
    pendientes_hechos: int = 0
    pendientes_total: int = 0
    charlas: int = 0
    codigos_excel: int = 0
    passkeys: int = 0


@dataclass(frozen=True)
class Faltante:
    id: str
    texto: str        # lo que dice la ficha y el banner: «Cargá tu hotel»
    prioridad: int    # 1 es la más importante
    link: str         # la pantalla donde se completa (ruta de la app)
    critico: bool     # también se avisa durante la estadía
    banner: bool = True

    def publico(self) -> dict:
        return asdict(self)


def _fecha(texto: str) -> dt.date | None:
    try:
        return dt.date.fromisoformat(texto)
    except (TypeError, ValueError):
        return None


def tiene_ida(fechas: tuple[str, ...]) -> bool:
    return any(f is not None and f <= DIA_PRIMERA_CHARLA for f in map(_fecha, fechas))


def tiene_vuelta(fechas: tuple[str, ...]) -> bool:
    return any(f is not None and f >= DIA_ULTIMA_CHARLA for f in map(_fecha, fechas))


def _plural(n: int, uno: str, varios: str) -> str:
    return f"{n} {uno if n == 1 else varios}"


def _pendientes(d: DatosFicha) -> Faltante | None:
    if not d.pendientes_total:  # nunca abrió la lista: todavía no se sembraron los sugeridos
        return Faltante("pendientes", "Revisá los pendientes del viaje", 7, LINK_PENDIENTES, critico=False)
    faltan = d.pendientes_total - d.pendientes_hechos
    if faltan <= 0:
        return None
    texto = f"Te {'falta' if faltan == 1 else 'faltan'} {_plural(faltan, 'pendiente', 'pendientes')} antes del viaje"
    return Faltante("pendientes", texto, 7, LINK_PENDIENTES, critico=False)


def faltantes(d: DatosFicha) -> list[Faltante]:
    """Todo lo que falta (salvo las notificaciones, que decide el front), de la prioridad más alta a la más baja."""
    candidatos = [
        None if tiene_ida(d.fechas_vuelos) else Faltante("vuelo_ida", "Cargá tu vuelo de ida", 1, LINK_VIAJES, critico=False),
        None if tiene_vuelta(d.fechas_vuelos) else Faltante("vuelo_vuelta", "Cargá tu vuelo de vuelta", 2, LINK_VIAJES, critico=True),
        None if d.hoteles else Faltante("hotel", "Cargá tu hotel", 3, LINK_VIAJES, critico=False),
        None if d.documentos else Faltante("documentos", "Subí tu pasaporte o ESTA", 5, LINK_DOCUMENTOS, critico=False),
        None if d.perfil_completo else Faltante("perfil", "Completá tu perfil para recomendaciones", 6, LINK_PERFIL, critico=False),
        _pendientes(d),
        None if d.charlas or d.codigos_excel else Faltante("agenda", "Armá tu agenda de charlas", 8, LINK_AGENDA, critico=False),
        None if d.passkeys else Faltante("passkey", "Entrá con huella o cara", 9, LINK_AJUSTES, critico=False, banner=False),
    ]
    return sorted((f for f in candidatos if f), key=lambda f: f.prioridad)


def fase(ahora: dt.datetime) -> str:
    """antes, durante o después de la estadía en Las Vegas (app/estadia.py). `ahora` tiene que tener zona."""
    if ahora < estadia.INICIO_DE_LA_ESTADIA:
        return ANTES
    return DURANTE if ahora < estadia.FIN_DE_LA_ESTADIA else DESPUES


def para_banner(lista: list[Faltante], fase_: str) -> list[Faltante]:
    """Los que se pueden avisar en el banner en esta fase, en el mismo orden."""
    if fase_ == DESPUES:
        return []
    return [f for f in lista if f.banner and (fase_ == ANTES or f.critico)]
