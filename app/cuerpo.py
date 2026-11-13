"""Lectura del cuerpo de un pedido con tope: se corta apenas se pasa del máximo, sin cargar todo en memoria antes."""
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
