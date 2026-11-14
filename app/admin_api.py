"""Módulo de admin (solo ADMIN_USERS): gestión de usuarios y uso de la app."""
import datetime as dt
import re
import shutil
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from psycopg.errors import UndefinedColumn, UndefinedTable
from pydantic import BaseModel, Field

from . import (
    catalog,
    charlas_auto,
    config,
    db,
    eventos_auto,
    eventos_link,
    events,
    healthcheck,
    langfuse_metricas,
    passkeys_db,
    passwords,
    prompts,
    sandbox,
    search,
    venues,
)
from .auth import admin, is_admin

router = APIRouter(prefix="/api/admin")

_USERNAME = re.compile(r"^[a-z0-9_.-]{2,40}$")


class NewUser(BaseModel):
    username: str = Field(min_length=2, max_length=40)
    password: str = Field(min_length=config.PASSWORD_MIN_LENGTH, max_length=200)


class ResetPassword(BaseModel):
    password: str = Field(min_length=config.PASSWORD_MIN_LENGTH, max_length=200)


class SetActive(BaseModel):
    active: bool


class SandboxSettings(BaseModel):
    """Modo prueba de un usuario. clock: hora simulada en Las Vegas (sin zona = hora de Las Vegas); None = reloj real."""
    active: bool
    stt: Literal["fake", "real"] = "fake"
    llm: Literal["fake", "real"] = "fake"
    clock: dt.datetime | None = None
    venue_id: int | None = None


class LinkUrl(BaseModel):
    url: str = Field(min_length=12, max_length=2000)


class LinkEvento(BaseModel):
    """La vista previa de un evento por link, revisada (y corregida si hizo falta) por el admin."""
    model_config = {"extra": "forbid"}
    url: str = Field(min_length=12, max_length=2000, pattern=r"^https://")
    nombre: str = Field(min_length=2, max_length=200)
    fecha: dt.date
    inicio: str = Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    fin: str | None = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    lugar: str | None = Field(default=None, max_length=120)
    direccion: str | None = Field(default=None, max_length=200)
    imagen: str | None = Field(default=None, max_length=2000, pattern=r"^https://")
    descripcion: str | None = Field(default=None, max_length=4000)
    resumen_es: str | None = Field(default=None, max_length=1200)
    tipo: str | None = Field(default=None, max_length=40)
    temas: list[str] = Field(default_factory=list, max_length=4)
    organizadores: list[str] = Field(default_factory=list, max_length=8)


class AdvanceClock(BaseModel):
    minutes: int = Field(ge=-1440, le=1440)


def _sandbox_view(user: dict) -> dict | None:
    sb = sandbox.desde_usuario(user)
    return sandbox.info(sb, venues.by_id(sb.id_sede) if sb else None)


def _user_or_404(username: str) -> dict:
    user = db.get_user(username)
    if not user:
        raise HTTPException(404, "Usuario inexistente")
    return user


def _cortar_accesos(username: str) -> None:
    """Cierra todas las sesiones, borra las passkeys, da de baja las notificaciones y borra la sede reciente: lo que
    hace falta para recuperar una cuenta comprometida (o dejar afuera a alguien desactivado)."""
    db.revoke_tokens(username)
    passkeys_db.delete_all(username)
    db.delete_push_subscriptions(username)
    db.delete_ubicacion(username)


@router.get("/users")
def list_users(_admin: str = Depends(admin)):
    return {"users": [{**{k: v for k, v in u.items() if k != "prueba"}, "is_admin": is_admin(u["username"]),
                       "sandbox": _sandbox_view(u)} for u in db.list_users()]}


@router.post("/users")
def create_user(body: NewUser, _admin: str = Depends(admin)):
    username = body.username.strip().lower()
    if not _USERNAME.match(username):
        raise HTTPException(422, "Usuario: 2 a 40 caracteres, solo minúsculas, números, punto, guion o guion bajo")
    if db.get_user(username):
        raise HTTPException(409, "Ese usuario ya existe")
    salt, password_hash = passwords.hash_password(body.password)
    db.create_user(username, salt, password_hash, must_change_password=True)
    return {"ok": True, "username": username}


@router.post("/users/{username}/reset-password")
def reset_password(username: str, body: ResetPassword, _admin: str = Depends(admin)):
    _user_or_404(username)
    salt, password_hash = passwords.hash_password(body.password)
    db.set_password(username, salt, password_hash, must_change_password=True)
    _cortar_accesos(username)
    return {"ok": True}


@router.post("/users/{username}/active")
def set_active(username: str, body: SetActive, current: str = Depends(admin)):
    _user_or_404(username)
    if username == current and not body.active:
        raise HTTPException(400, "No podés desactivar tu propio usuario")
    db.set_user_active(username, body.active)
    if not body.active:
        _cortar_accesos(username)
    return {"ok": True}


@router.delete("/users/{username}/sessions")
def revoke_sessions(username: str, _admin: str = Depends(admin)):
    _user_or_404(username)
    _cortar_accesos(username)
    return {"ok": True}


@router.put("/users/{username}/sandbox")
def set_sandbox(username: str, body: SandboxSettings, _admin: str = Depends(admin)):
    """Prende, configura o apaga el modo prueba de un usuario. Sus datos reales no se tocan."""
    _user_or_404(username)
    if body.venue_id is not None and not venues.by_id(body.venue_id):
        raise HTTPException(422, "Sede inexistente")
    clock = body.clock.replace(tzinfo=sandbox.EVENT_TZ) if body.clock and body.clock.tzinfo is None else body.clock
    cfg = sandbox.config_json(stt=body.stt, llm=body.llm, reloj=clock, id_sede=body.venue_id)
    db.set_user_sandbox(username, body.active, cfg)
    return {"ok": True, "sandbox": _sandbox_view(db.get_user(username))}


@router.post("/users/{username}/sandbox/advance")
def advance_sandbox_clock(username: str, body: AdvanceClock, _admin: str = Depends(admin)):
    """Adelanta (o atrasa) el reloj simulado: para probar "Hoy", el countdown y las alertas sin esperar."""
    user = _user_or_404(username)
    sb = sandbox.desde_usuario(user)
    if not sb or sb.reloj is None:
        raise HTTPException(409, "Ese usuario no tiene el reloj simulado")
    with sandbox.activar(sb):
        nueva = sandbox.ahora() + dt.timedelta(minutes=body.minutes)
    db.set_user_sandbox(username, True, sandbox.config_json(stt=sb.stt, llm=sb.llm, reloj=nueva, id_sede=sb.id_sede))
    return {"ok": True, "sandbox": _sandbox_view(db.get_user(username))}


@router.delete("/sandbox/data")
def clear_sandbox_data(_admin: str = Depends(admin)):
    """Borra todo lo creado en modo prueba (grabaciones, itinerarios), de todos los usuarios. Lo real no se toca."""
    rows = db.borrar_datos_prueba()
    shutil.rmtree(config.DATA_DIR / "prueba", ignore_errors=True)
    return {"ok": True, "rows": rows}


@router.get("/check")
def functional_check(_admin: str = Depends(admin)):
    """Chequeo funcional: cada parte de la app, sin tocar datos reales ni gastar en APIs."""
    return {"checks": healthcheck.run_all()}


@router.get("/venues")
def list_venues(_admin: str = Depends(admin)):
    return {"venues": venues.all_venues()}


@router.post("/catalog/reload")
def reload_catalog(_admin: str = Depends(admin)):
    """Relee el catálogo de Postgres (después de correr scripts/sync_to_railway.sh) sin reiniciar la app."""
    sessions = catalog.load()
    events.load()
    search.warm_async()  # recalcula en segundo plano solo los embeddings de charlas nuevas o cambiadas
    return {"ok": True, "sessions": sessions}


@router.get("/usage")
def usage(_admin: str = Depends(admin)):
    return {
        "recordings_by_status": db.recordings_by_status(),
        "recent_errors": db.recent_errors(),
        "users": db.list_users(),
    }


@router.get("/llm")
def llm_dashboard(_admin: str = Depends(admin)):
    """Tablero de LLM: costo, demora, errores y scores de los últimos 7 días, leídos de Langfuse (cache de 5 min)."""
    return langfuse_metricas.tablero()


# ---------- eventos automáticos ----------

def _eventos_activos() -> None:
    if not config.EVENTOS_AUTO:
        raise HTTPException(409, "Los eventos automáticos están apagados en este entorno (EVENTOS_AUTO)")


@router.get("/eventos")
def eventos_estado(_admin: str = Depends(admin)):
    """Última revisión de cada fuente (también el catálogo oficial de charlas), los eventos cargados por link y las
    charlas nuevas que encontró la revisión."""
    estado = eventos_auto.estado()
    return {**estado, "ocupado": estado["ocupado"] or charlas_auto.ocupado(), "charlas_nuevas": charlas_auto.nuevas()}


@router.post("/eventos/revisar", status_code=202)
def eventos_revisar(_admin: str = Depends(admin)):
    """Arranca una revisión ya de eventos y de charlas (en segundo plano: el estado se ve en GET /eventos)."""
    _eventos_activos()
    eventos, charlas = eventos_auto.en_segundo_plano(), charlas_auto.en_segundo_plano()
    if not (eventos or charlas):
        raise HTTPException(409, "Ya hay una revisión en curso")
    return {"ok": True}


@router.post("/eventos/link/vista-previa")
def eventos_link_vista_previa(body: LinkUrl, _admin: str = Depends(admin)):
    """Baja la página y saca los datos del evento con el LLM, para revisarlos antes de guardar. No guarda nada."""
    _eventos_activos()
    try:
        previa = eventos_link.vista_previa(body.url)
        repetido = eventos_auto.ya_cargado(previa["url"])
    except eventos_link.LinkInvalido as e:
        raise HTTPException(422, str(e)) from e
    except (UndefinedTable, UndefinedColumn) as e:
        raise HTTPException(409, "Falta la migración 007 en la base") from e
    return {**previa, "ya_cargado": repetido}


@router.post("/eventos/link")
def eventos_link_guardar(body: LinkEvento, _admin: str = Depends(admin)):
    _eventos_activos()
    datos = {**body.model_dump(), "fecha": body.fecha.isoformat()}
    resumen = {"resumen_es": body.resumen_es, "tipo": body.tipo if body.tipo in prompts.EVENT_TYPES else None,
               "temas": body.temas, "organizadores": body.organizadores}
    try:
        id_evento = eventos_auto.guardar_link(datos, resumen=resumen)
    except eventos_auto.LinkRepetido as e:
        raise HTTPException(409, str(e)) from e
    except eventos_link.LinkInvalido as e:
        raise HTTPException(422, str(e)) from e
    events.load()
    return {"ok": True, "id": id_evento}
