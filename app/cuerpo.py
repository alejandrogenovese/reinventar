"""Lectura del cuerpo de un pedido con tope (se corta apenas se pasa del máximo, sin cargar todo en memoria antes) y
extracción de las partes de un multipart/form-data, a mano en vez de sumar python-multipart."""
from email.message import Message
from email.parser import BytesParser

from fastapi import HTTPException, Request


async def leer_con_tope(request: Request, tope: int, mensaje: str = "El archivo es demasiado grande") -> bytes:
    largo = request.headers.get("content-length", "")
    if largo.isdigit() and int(largo) > tope:
        raise HTTPException(413, mensaje)
    partes, total = [], 0
    async for trozo in request.stream():
        total += len(trozo)
        if total > tope:
            raise HTTPException(413, mensaje)
        partes.append(trozo)
    return b"".join(partes)


def partes_multipart(content_type: str, cuerpo: bytes) -> dict[str, tuple[str, bytes]] | None:
    """{nombre del campo: (Content-Type declarado, bytes)} de un multipart/form-data, o None si no lo es. Si un campo
    viene repetido vale el primero. El Content-Type declarado es solo informativo: los bytes se validan aparte."""
    cabecera = Message()
    cabecera["content-type"] = content_type
    if cabecera.get_content_type() != "multipart/form-data" or not cabecera.get_param("boundary"):
        return None
    delimitador = b"--" + str(cabecera.get_param("boundary")).encode()
    campos: dict[str, tuple[str, bytes]] = {}
    for parte in cuerpo.split(delimitador)[1:]:
        parte = parte.removeprefix(b"\r\n")
        corte = parte.find(b"\r\n\r\n")
        if corte < 0:
            continue
        encabezados = BytesParser().parsebytes(parte[: corte + 4])
        nombre = encabezados.get_param("name", header="content-disposition")
        if isinstance(nombre, str) and nombre not in campos:
            campos[nombre] = (encabezados.get_content_type(), parte[corte + 4:].removesuffix(b"\r\n"))
    return campos
