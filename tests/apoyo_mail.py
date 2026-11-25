"""Ayudas compartidas por los tests de mail (MAIL_PROVIDER=fake: los mails quedan en app.mail.enviados)."""
import re
import uuid

import pytest
from fastapi.testclient import TestClient

from app import db, mail, passwords
from app.main import app

CLAVE = "inicial123"


@pytest.fixture
def c():
    mail.enviados.clear()
    with TestClient(app) as cliente:
        yield cliente


def usuario_nuevo():
    username = f"m_{uuid.uuid4().hex[:8]}"
    salt, h = passwords.hash_password(CLAVE)
    db.create_user(username, salt, h, must_change_password=False)
    return username


def mail_unico():
    return f"Persona.{uuid.uuid4().hex[:8]}@Ejemplo.com"


def codigo_enviado() -> str:
    """El código del último mail: va solo en su renglón, con sangría, en la versión de texto."""
    return re.search(r"\n    (\d{6})\n", mail.enviados[-1]["texto"]).group(1)


def verificar(c, headers, email):
    assert c.post("/api/me/email", headers=headers, json={"email": email}).status_code == 200
    return c.post("/api/me/email/verificar", headers=headers, json={"codigo": codigo_enviado()})
