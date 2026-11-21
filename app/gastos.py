"""Control de gastos del viaje: modelos validados, sincronización con el teléfono, totales y export.

El teléfono genera el client_id de cada gasto y manda sus cambios a /sync: se hace upsert por (usuario, client_id) y en un
conflicto gana el updated_at más nuevo. Borrar es lógico (deleted_at) para que el borrado viaje a los otros dispositivos.
La cotización (ARS por USD) se congela en el servidor al crear el gasto; el monto en dólares se calcula con la de tarjeta.
"""
import csv
import io
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Annotated, Literal
from uuid import UUID

from psycopg.types.json import Jsonb
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator

from . import cotizacion, db

Moneda = Literal["USD", "ARS"]
Categoria = Literal["comida", "transporte", "shows", "compras", "otros"]
CATEGORIAS = ("comida", "transporte", "shows", "compras", "otros")

NOTA_MAX = 500
MONTO_MAX = Decimal("1000000000")          # tope de cordura: evita un NUMERIC(12,2) desbordado o un typo de ceros
CAMBIOS_POR_SYNC = 200                     # gastos por pedido de /sync
CAMBIOS_MAX_RESPUESTA = 1000               # filas que devuelve /sync de una vez
RELOJ_FUTURO_MAX = timedelta(minutes=5)    # un teléfono con el reloj adelantado no puede ganar todos los conflictos
CENTAVOS = Decimal("0.01")
BOM = "﻿"
COMILLA_FORMULA = ("=", "+", "-", "@", "\t", "\r")


def _redondear(valor) -> Decimal:
    return Decimal(str(valor)).quantize(CENTAVOS, rounding=ROUND_HALF_UP)


Monto = Annotated[Decimal, Field(gt=0, le=MONTO_MAX)]


class GastoEntrada(BaseModel):
    """Un gasto como lo manda el teléfono. Los campos que decide el servidor (cotizaciones, monto_usd, foto) se ignoran."""
    model_config = ConfigDict(extra="ignore")

    client_id: UUID
    fecha: date
    monto: Monto
    moneda: Moneda
    categoria: Categoria
    nota: str = Field("", max_length=NOTA_MAX)
    reintegrable: bool = False
    compartido: bool = False
    updated_at: AwareDatetime
    deleted_at: AwareDatetime | None = None

    @field_validator("monto", mode="before")
    @classmethod
    def _monto_a_centavos(cls, v):
        try:
            return _redondear(v)
        except ArithmeticError as e:  # texto que no es un número
            raise ValueError("monto inválido") from e


class SyncPedido(BaseModel):
    cambios: list[GastoEntrada] = Field(max_length=CAMBIOS_POR_SYNC)
    desde: AwareDatetime | None = None


class Presupuesto(BaseModel):
    total_usd: Annotated[Decimal, Field(ge=0, le=MONTO_MAX)] | None = None
    diario_usd: Annotated[Decimal, Field(ge=0, le=MONTO_MAX)] | None = None
    por_categoria: dict[Categoria, Annotated[Decimal, Field(ge=0, le=MONTO_MAX)]] = Field(default_factory=dict)


def a_usd(monto: Decimal, moneda: str, tarjeta: Decimal) -> Decimal:
    """USD si ya está en dólares; si es ARS, se divide por la cotización de tarjeta congelada."""
    return monto if moneda == "USD" else (monto / tarjeta).quantize(CENTAVOS, rounding=ROUND_HALF_UP)


def _num(valor: Decimal | None) -> float | None:
    return None if valor is None else float(valor)


def url_foto(client_id) -> str:
    return f"/api/gastos/{client_id}/foto"


def a_json(fila: dict) -> dict:
    """Un gasto de la base como lo ve la PWA."""
    return {"client_id": str(fila["client_id"]), "fecha": fila["fecha"].isoformat(), "monto": _num(fila["monto"]),
            "moneda": fila["moneda"], "categoria": fila["categoria"], "nota": fila["nota"],
            "reintegrable": fila["reintegrable"], "compartido": fila["compartido"],
            "cotizacion_oficial": _num(fila["cotizacion_oficial"]), "cotizacion_blue": _num(fila["cotizacion_blue"]),
            "cotizacion_tarjeta": _num(fila["cotizacion_tarjeta"]), "monto_usd": _num(fila["monto_usd"]),
            "foto_url": url_foto(fila["client_id"]) if fila["foto_clave"] else None,
            "updated_at": fila["updated_at"].isoformat(),
            "deleted_at": fila["deleted_at"].isoformat() if fila["deleted_at"] else None}


# ---------- sincronización ----------

_UPSERT = """
INSERT INTO gastos (username, client_id, fecha, monto, moneda, categoria, nota, reintegrable, compartido,
                    cotizacion_oficial, cotizacion_blue, cotizacion_tarjeta, monto_usd, updated_at, deleted_at,
                    sincronizado_at)
VALUES (%(username)s, %(client_id)s, %(fecha)s, %(monto)s, %(moneda)s, %(categoria)s, %(nota)s, %(reintegrable)s,
        %(compartido)s, %(oficial)s, %(blue)s, %(tarjeta)s, %(monto_usd)s, %(updated_at)s, %(deleted_at)s, now())
ON CONFLICT (username, client_id) DO UPDATE SET
  fecha = EXCLUDED.fecha, monto = EXCLUDED.monto, moneda = EXCLUDED.moneda, categoria = EXCLUDED.categoria,
  nota = EXCLUDED.nota, reintegrable = EXCLUDED.reintegrable, compartido = EXCLUDED.compartido,
  monto_usd = CASE WHEN EXCLUDED.moneda = 'USD' THEN EXCLUDED.monto
                   ELSE ROUND(EXCLUDED.monto / gastos.cotizacion_tarjeta, 2) END,
  updated_at = EXCLUDED.updated_at, deleted_at = EXCLUDED.deleted_at, sincronizado_at = now()
WHERE gastos.updated_at < EXCLUDED.updated_at
RETURNING client_id
"""


def _acotar_reloj(updated_at: datetime, ahora: datetime) -> datetime:
    return min(updated_at, ahora + RELOJ_FUTURO_MAX)


def sincronizar(username: str, cambios: list[GastoEntrada], desde: datetime | None) -> dict:
    """Aplica los cambios del teléfono y devuelve {aplicados, cambios, ahora}. Un cambio se aplica si es nuevo o si su
    updated_at es más nuevo que el guardado; reenviar el mismo no duplica ni cambia nada (cuenta como aplicado). Los que
    pierden el conflicto no se aplican y la versión del servidor vuelve en `cambios` aunque sea anterior a `desde`."""
    cot = cotizacion.actual()
    aplicados: list[str] = []
    perdidos: list[UUID] = []
    with db.conn() as c:
        ahora = c.execute("SELECT now() AS ahora").fetchone()["ahora"]
        for g in cambios:
            params = {"username": username, "client_id": g.client_id, "fecha": g.fecha, "monto": g.monto,
                      "moneda": g.moneda, "categoria": g.categoria, "nota": g.nota, "reintegrable": g.reintegrable,
                      "compartido": g.compartido, "oficial": cot["oficial"], "blue": cot["blue"],
                      "tarjeta": cot["tarjeta"], "monto_usd": a_usd(g.monto, g.moneda, cot["tarjeta"]),
                      "updated_at": _acotar_reloj(g.updated_at, ahora), "deleted_at": g.deleted_at}
            if c.execute(_UPSERT, params).fetchone():
                aplicados.append(str(g.client_id))
                continue
            guardado = c.execute("SELECT updated_at FROM gastos WHERE username=%s AND client_id=%s",
                                 (username, g.client_id)).fetchone()
            if guardado["updated_at"] == params["updated_at"]:
                aplicados.append(str(g.client_id))   # el mismo cambio otra vez: ya estaba
            else:
                perdidos.append(g.client_id)
        filas = c.execute(
            "SELECT * FROM gastos WHERE username=%s AND (sincronizado_at > %s OR client_id = ANY(%s)) "
            "ORDER BY sincronizado_at, id LIMIT %s",
            (username, desde or datetime.min.replace(tzinfo=UTC), perdidos, CAMBIOS_MAX_RESPUESTA)).fetchall()
    return {"aplicados": aplicados, "cambios": [a_json(f) for f in filas], "ahora": ahora.isoformat()}


# ---------- lectura ----------

def listar(username: str, desde: date | None, hasta: date | None) -> dict:
    """Gastos vigentes (sin borrados) en el rango, con totales en USD por categoría y por día, y el presupuesto."""
    with db.conn() as c:
        filas = c.execute(
            "SELECT * FROM gastos WHERE username=%s AND deleted_at IS NULL "
            "AND (%s::date IS NULL OR fecha >= %s) AND (%s::date IS NULL OR fecha <= %s) "
            "ORDER BY fecha DESC, updated_at DESC", (username, desde, desde, hasta, hasta)).fetchall()
    return {"gastos": [a_json(f) for f in filas], "totales": totales(filas), "presupuesto": presupuesto(username)}


def totales(filas: list[dict]) -> dict:
    por_categoria: dict[str, Decimal] = {}
    por_dia: dict[str, Decimal] = {}
    for f in filas:
        por_categoria[f["categoria"]] = por_categoria.get(f["categoria"], Decimal(0)) + f["monto_usd"]
        dia = f["fecha"].isoformat()
        por_dia[dia] = por_dia.get(dia, Decimal(0)) + f["monto_usd"]
    return {"usd": float(sum(por_categoria.values(), Decimal(0))),
            "por_categoria": {k: float(v) for k, v in sorted(por_categoria.items())},
            "por_dia": {k: float(v) for k, v in sorted(por_dia.items())}}


def presupuesto(username: str) -> dict:
    with db.conn() as c:
        f = c.execute("SELECT total_usd, diario_usd, por_categoria FROM gastos_presupuesto WHERE username=%s",
                      (username,)).fetchone()
    if not f:
        return {"total_usd": None, "diario_usd": None, "por_categoria": {}}
    return {"total_usd": _num(f["total_usd"]), "diario_usd": _num(f["diario_usd"]), "por_categoria": f["por_categoria"]}


def guardar_presupuesto(username: str, p: Presupuesto) -> dict:
    por_categoria = {k: float(v) for k, v in p.por_categoria.items()}
    with db.conn() as c:
        c.execute(
            "INSERT INTO gastos_presupuesto (username, total_usd, diario_usd, por_categoria) VALUES (%s, %s, %s, %s) "
            "ON CONFLICT (username) DO UPDATE SET total_usd = EXCLUDED.total_usd, diario_usd = EXCLUDED.diario_usd, "
            "por_categoria = EXCLUDED.por_categoria",
            (username, p.total_usd, p.diario_usd, Jsonb(por_categoria)))
    return presupuesto(username)


def compartidos(username: str) -> dict:
    """Lo marcado como compartido. La división entre personas queda para más adelante: acá solo está el dato."""
    with db.conn() as c:
        filas = c.execute("SELECT * FROM gastos WHERE username=%s AND compartido AND deleted_at IS NULL "
                          "ORDER BY fecha DESC, updated_at DESC", (username,)).fetchall()
    return {"gastos": [a_json(f) for f in filas], "total_usd": totales(filas)["usd"]}


def obtener(username: str, client_id: UUID) -> dict | None:
    """El gasto vigente de esa persona (None si no existe, es de otra o está borrado)."""
    with db.conn() as c:
        return c.execute("SELECT * FROM gastos WHERE username=%s AND client_id=%s AND deleted_at IS NULL",
                         (username, client_id)).fetchone()


def poner_foto(username: str, client_id: UUID, clave: str | None) -> None:
    """Guarda la clave de la foto. Solo el servidor la toca: /sync nunca la pisa. No cambia updated_at (que es del
    teléfono), pero sí sincronizado_at, para que los otros dispositivos se enteren."""
    with db.conn() as c:
        c.execute("UPDATE gastos SET foto_clave=%s, sincronizado_at=now() WHERE username=%s AND client_id=%s",
                  (clave, username, client_id))


# ---------- export ----------

def _celda(texto: str) -> str:
    """Una celda que empieza con = + - @ la ejecutaría Excel como fórmula: se le antepone una comilla."""
    return "'" + texto if texto.startswith(COMILLA_FORMULA) else texto


def _decimal_es(valor: Decimal | None) -> str:
    return "" if valor is None else f"{valor:f}".replace(".", ",")


def exportar_csv(username: str, base_url: str) -> bytes:
    """Solo lo reintegrable y no borrado. Separador ; y decimales con coma (lo que espera Excel en castellano) y BOM
    UTF-8 para que abra bien las tildes."""
    with db.conn() as c:
        filas = c.execute("SELECT * FROM gastos WHERE username=%s AND reintegrable AND deleted_at IS NULL "
                          "ORDER BY fecha, updated_at", (username,)).fetchall()
    salida = io.StringIO()
    w = csv.writer(salida, delimiter=";", lineterminator="\r\n")
    w.writerow(["fecha", "concepto", "moneda", "monto", "monto_usd", "cotizacion_usada", "foto"])
    for f in filas:
        concepto = f["categoria"] + (f" - {f['nota']}" if f["nota"] else "")
        cotizacion_usada = f["cotizacion_tarjeta"] if f["moneda"] == "ARS" else None
        foto = f"{base_url.rstrip('/')}{url_foto(f['client_id'])}" if f["foto_clave"] else ""
        w.writerow([f["fecha"].isoformat(), _celda(concepto), f["moneda"], _decimal_es(f["monto"]),
                    _decimal_es(f["monto_usd"]), _decimal_es(cotizacion_usada), foto])
    return (BOM + salida.getvalue()).encode("utf-8")
