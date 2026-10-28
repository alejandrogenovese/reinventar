"""Configuración por variables de entorno (Railway → Variables)."""
import os
from pathlib import Path


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


# Acceso: cada persona tiene su usuario/contraseña, creados al arrancar si no existen.
# Formato: "usuario1:contraseña1,usuario2:contraseña2".
BOOTSTRAP_USERS = _env("BOOTSTRAP_USERS")

# Persistencia: montar un Railway Volume en /data.
DATA_DIR = Path(_env("DATA_DIR", "/data"))
DB_PATH = DATA_DIR / "reinventar.db"
SESSIONS_DIR = DATA_DIR / "sessions"

# Speech-to-text.
#   openai  → cualquier endpoint compatible con /audio/transcriptions (Groq por defecto, OpenAI, LiteLLM)
#   local   → faster-whisper dentro del contenedor (requiere instalar faster-whisper)
#   fake    → para tests
STT_PROVIDER = _env("STT_PROVIDER", "openai")
STT_BASE_URL = _env("STT_BASE_URL", "https://api.groq.com/openai/v1")
STT_API_KEY = _env("STT_API_KEY")
STT_MODEL = _env("STT_MODEL", "whisper-large-v3-turbo")
STT_LANGUAGE = _env("STT_LANGUAGE", "en")
STT_SEGMENT_SECONDS = int(_env("STT_SEGMENT_SECONDS", "600"))  # pedazos de 10 min (< 25 MB)

# LLM para traducción y resumen.
#   anthropic → API de Claude directa
#   openai    → endpoint compatible /chat/completions (p. ej. tu LiteLLM)
#   fake      → para tests
LLM_PROVIDER = _env("LLM_PROVIDER", "anthropic")
ANTHROPIC_API_KEY = _env("ANTHROPIC_API_KEY")
LLM_BASE_URL = _env("LLM_BASE_URL")
LLM_API_KEY = _env("LLM_API_KEY")
TRANSLATE_MODEL = _env("TRANSLATE_MODEL", "claude-sonnet-5-5")
SUMMARY_MODEL = _env("SUMMARY_MODEL", "claude-opus-5-5")
TARGET_LANGUAGE = _env("TARGET_LANGUAGE", "castellano rioplatense (Argentina)")

# Límites.
MAX_CHUNK_BYTES = int(_env("MAX_CHUNK_BYTES", str(5 * 1024 * 1024)))
TRANSLATE_BATCH = int(_env("TRANSLATE_BATCH", "30"))  # bloques por llamada
BLOCK_SECONDS = float(_env("BLOCK_SECONDS", "45"))  # largo objetivo de cada bloque de lectura

WEB_DIR = Path(__file__).resolve().parent.parent / "web"

# Catálogo de sesiones y motor de recomendación/itinerario.
CATALOG_PATH = Path(_env("CATALOG_PATH", str(Path(__file__).resolve().parent.parent / "data" / "reinvent2026-catalogo.json")))
ITINERARY_MODEL = _env("ITINERARY_MODEL", "claude-sonnet-5-5")
ITINERARY_CANDIDATE_LIMIT = int(_env("ITINERARY_CANDIDATE_LIMIT", "180"))  # sesiones que se le mandan al LLM como candidatas
