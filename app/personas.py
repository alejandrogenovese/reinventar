"""«Personas que conocí» (#/viaje/personas): la libreta de contactos de networking de cada uno. Es privada: todas las
consultas filtran por el usuario de la sesión y un id ajeno se trata igual que uno que no existe.

El teléfono genera el id (UUID) de cada persona y la guarda con PUT /api/personas/{id}: reenviar el mismo alta (la cola
sin señal reintenta) no la duplica. Solo cuenta como alta nueva, y gasta cuota, la primera vez que llega ese id.
"""
import re
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from . import db

NOMBRE_MAX = 80
EMPRESA_MAX = 80
CARGO_MAX = 80
LINKEDIN_MAX = 200
DONDE_MAX = 120
CHARLA_CODE_MAX = 40
CHARLA_TITULO_MAX = 200
NOTA_MAX = 1000
TOPE_POR_PERSONA = 500     # contactos por usuario: un evento de una semana no llega ni cerca

# Solo perfiles de LinkedIn con https y el dominio exacto (nada de http, subdominios raros ni «linkedin.com.otro.sitio»).
LINKEDIN = re.compile(r"^https://www\.linkedin\.com/[^\s<>\"']*$")
CHARLA_CODE = re.compile(r"^[A-Za-z0-9._-]+$")

_COLUMNAS = "id, nombre, empresa, cargo, linkedin, donde, charla_code, charla_titulo, nota, creado, actualizado"


def _una_linea(v: str) -> str:
    """Sin saltos de línea ni espacios repetidos (la nota sí puede tener varias líneas)."""
    return " ".join(v.split())


class PersonaEntrada(BaseModel):
    model_config = ConfigDict(extra="ignore")

    nombre: str = Field(min_length=1, max_length=NOMBRE_MAX)
    empresa: str = Field("", max_length=EMPRESA_MAX)
    cargo: str = Field("", max_length=CARGO_MAX)
    linkedin: str = Field("", max_length=LINKEDIN_MAX)
    donde: str = Field("", max_length=DONDE_MAX)
    charla_code: str | None = Field(None, max_length=CHARLA_CODE_MAX)
    charla_titulo: str = Field("", max_length=CHARLA_TITULO_MAX)
    nota: str = Field("", max_length=NOTA_MAX)

    @field_validator("nombre")
    @classmethod
    def _nombre(cls, v: str) -> str:
        v = _una_linea(v)
        if not v:
            raise ValueError("Escribí el nombre")
        return v

    @field_validator("empresa", "cargo", "donde", "charla_titulo")
    @classmethod
    def _linea(cls, v: str) -> str:
        return _una_linea(v)

    @field_validator("nota")
    @classmethod
    def _nota(cls, v: str) -> str:
        return v.strip()

    @field_validator("linkedin")
    @classmethod
    def _linkedin(cls, v: str) -> str:
        v = v.strip()
        if v and not LINKEDIN.match(v):
            raise ValueError("El LinkedIn tiene que ser un link https://www.linkedin.com/...")
        return v

    @field_validator("charla_code")
    @classmethod
    def _charla(cls, v: str | None) -> str | None:
        v = (v or "").strip()
        if not v:
            return None
        if not CHARLA_CODE.match(v):
            raise ValueError("El código de la charla no es válido")
        return v


def _publico(r: dict) -> dict:
    return {"id": str(r["id"]), "nombre": r["nombre"], "empresa": r["empresa"], "cargo": r["cargo"],
            "linkedin": r["linkedin"], "donde": r["donde"], "charla_code": r["charla_code"],
            "charla_titulo": r["charla_titulo"], "nota": r["nota"],
            "creado": r["creado"].isoformat(), "actualizado": r["actualizado"].isoformat()}


def listar(username: str) -> list[dict]:
    """Las de la persona, la última que tocó primero."""
    with db.conn() as c:
        filas = c.execute(f"SELECT {_COLUMNAS} FROM personas_conocidas WHERE username=%s "
                          "ORDER BY actualizado DESC, id", (username,)).fetchall()
    return [_publico(f) for f in filas]


def existe(username: str, id_: UUID) -> bool:
    with db.conn() as c:
        return c.execute("SELECT 1 FROM personas_conocidas WHERE username=%s AND id=%s", (username, id_)).fetchone() is not None


def cantidad(username: str) -> int:
    with db.conn() as c:
        return c.execute("SELECT count(*) AS n FROM personas_conocidas WHERE username=%s", (username,)).fetchone()["n"]


def guardar(username: str, id_: UUID, p: PersonaEntrada) -> dict:
    """Alta o edición (upsert por usuario e id). La clave incluye al usuario: un id de otra persona no la toca."""
    datos = {"u": username, "id": id_, **p.model_dump()}
    with db.conn() as c:
        fila = c.execute(
            "INSERT INTO personas_conocidas (username, id, nombre, empresa, cargo, linkedin, donde, charla_code, "
            "charla_titulo, nota) VALUES (%(u)s, %(id)s, %(nombre)s, %(empresa)s, %(cargo)s, %(linkedin)s, %(donde)s, "
            "%(charla_code)s, %(charla_titulo)s, %(nota)s) "
            "ON CONFLICT (username, id) DO UPDATE SET nombre=EXCLUDED.nombre, empresa=EXCLUDED.empresa, "
            "cargo=EXCLUDED.cargo, linkedin=EXCLUDED.linkedin, donde=EXCLUDED.donde, charla_code=EXCLUDED.charla_code, "
            f"charla_titulo=EXCLUDED.charla_titulo, nota=EXCLUDED.nota, actualizado=now() RETURNING {_COLUMNAS}",
            datos).fetchone()
    return _publico(fila)


def borrar(username: str, id_: UUID) -> bool:
    with db.conn() as c:
        return c.execute("DELETE FROM personas_conocidas WHERE username=%s AND id=%s", (username, id_)).rowcount > 0
