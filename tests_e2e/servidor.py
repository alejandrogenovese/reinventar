"""Servidor local de la app para la prueba E2E: uvicorn con STT/LLM/embeddings falsos, DATA_DIR temporal, un schema de
Postgres propio (se borra al final) y un usuario de prueba creado por acá. No usa credenciales reales ni APIs externas."""
import json
import os
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
USUARIO = "e2e"
CLAVE_INICIAL = "e2e-clave-inicial-1"  # BOOTSTRAP_USERS la crea como temporal; el script la cambia por CLAVE
CLAVE = "e2e-clave-de-prueba-2"
ESPERA_ARRANQUE_S = 40


@dataclass(frozen=True)
class Servidor:
    url: str
    token: str
    schema: str

    def pedir(self, ruta: str, metodo: str = "GET", cuerpo: dict | None = None) -> object:
        """JSON de la API con el token de prueba (para mirar el estado del servidor desde el script)."""
        datos = json.dumps(cuerpo).encode() if cuerpo is not None else None
        req = urllib.request.Request(self.url + ruta, data=datos, method=metodo, headers={
            "Authorization": f"Bearer {self.token}", "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read() or "null")


def _url_de_la_base() -> str:
    """La base de Postgres sale del entorno (E2E_DATABASE_URL o, si no, DATABASE_URL): en el código no va ninguna clave."""
    url = os.environ.get("E2E_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("Falta la base: exportá E2E_DATABASE_URL (o DATABASE_URL) con la URL del Postgres local. Ver docs/pruebas.md.")
    return url


def _puerto_libre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _python_del_servidor() -> str:
    """El intérprete con las dependencias de la app: E2E_PYTHON, o el .venv del repo (el venv del E2E solo trae el navegador)."""
    elegido = os.environ.get("E2E_PYTHON")
    if elegido:
        return elegido
    for candidato in (RAIZ / ".venv" / "bin" / "python", Path(sys.executable)):
        if candidato.exists():
            return str(candidato)
    return sys.executable


def _post_json(url: str, cuerpo: dict, token: str | None = None) -> dict:
    cabeceras = {"Content-Type": "application/json", **({"Authorization": f"Bearer {token}"} if token else {})}
    req = urllib.request.Request(url, data=json.dumps(cuerpo).encode(), headers=cabeceras, method="POST")
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())


def _esperar_salud(url: str, proceso: subprocess.Popen) -> None:
    limite = time.monotonic() + ESPERA_ARRANQUE_S
    while time.monotonic() < limite:
        if proceso.poll() is not None:
            raise RuntimeError(f"El servidor se cerró al arrancar (código {proceso.returncode}). Mirá el log de la corrida.")
        try:
            with urllib.request.urlopen(url + "/health", timeout=2):
                return
        except (urllib.error.URLError, ConnectionError, TimeoutError):
            time.sleep(0.3)
    raise RuntimeError(f"El servidor no respondió /health en {ESPERA_ARRANQUE_S} s.")


def _crear_usuario_de_prueba(url: str) -> str:
    """Login con la clave temporal, cambio de clave (el servidor lo exige) y token ya usable."""
    token = _post_json(url + "/api/login", {"username": USUARIO, "password": CLAVE_INICIAL})["token"]
    _post_json(url + "/api/password", {"current_password": CLAVE_INICIAL, "new_password": CLAVE}, token)
    return _post_json(url + "/api/login", {"username": USUARIO, "password": CLAVE})["token"]


def _borrar_schema(python: str, entorno: dict[str, str], schema: str) -> None:
    # La app crea además {schema}_prueba (modo sandbox); igual que tests/conftest.py, se borran los dos.
    codigo = ("from app import pg\n"
              "with pg.pool().connection() as c:\n"
              f"    c.execute('DROP SCHEMA IF EXISTS {schema} CASCADE')\n"
              f"    c.execute('DROP SCHEMA IF EXISTS {schema}_prueba CASCADE')\n"
              "pg.close()")
    subprocess.run([python, "-c", codigo], cwd=RAIZ, env=entorno, check=False, capture_output=True, timeout=30)


@contextmanager
def servidor_local(carpeta_log: Path):
    """Levanta la app y entrega un Servidor; al salir lo apaga y borra el DATA_DIR y el schema."""
    puerto = _puerto_libre()
    schema = f"app_e2e_{secrets.token_hex(4)}"
    datos = tempfile.mkdtemp(prefix="reinventar-e2e-")
    python = _python_del_servidor()
    entorno = {**os.environ, "DATABASE_URL": _url_de_la_base(),"DB_SCHEMA": schema, "DATA_DIR": datos,
               "BOOTSTRAP_USERS": f"{USUARIO}:{CLAVE_INICIAL}", "ADMIN_USERS": "", "STT_PROVIDER": "fake",
               "LLM_PROVIDER": "fake", "EMBED_PROVIDER": "off", "EVENTOS_AUTO": "0",
               "LANGFUSE_PUBLIC_KEY": "", "LANGFUSE_SECRET_KEY": "", "TICKETMASTER_API_KEY": ""}
    carpeta_log.mkdir(parents=True, exist_ok=True)
    with open(carpeta_log / "servidor.log", "w") as log:
        proceso = subprocess.Popen([python, "-m", "uvicorn", "app.main:app", "--port", str(puerto), "--host", "127.0.0.1"],
                                   cwd=RAIZ, env=entorno, stdout=log, stderr=subprocess.STDOUT)
        try:
            url = f"http://127.0.0.1:{puerto}"
            _esperar_salud(url, proceso)
            yield Servidor(url=url, token=_crear_usuario_de_prueba(url), schema=schema)
        finally:
            proceso.terminate()
            try:
                proceso.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proceso.kill()
            _borrar_schema(python, entorno, schema)
            shutil.rmtree(datos, ignore_errors=True)
