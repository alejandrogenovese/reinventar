"""Variables de entorno por defecto, antes de que cualquier test importe app.main (app.config las lee una sola vez)."""
import os
import tempfile

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="reinventar-test-"))
os.environ.setdefault("APP_TOKEN", "secreto")
os.environ.setdefault("STT_PROVIDER", "fake")
os.environ.setdefault("LLM_PROVIDER", "fake")
