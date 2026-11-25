"""Configuración por variables de entorno (Railway → Variables)."""
import os
from pathlib import Path


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


# Acceso: cada persona tiene su usuario/contraseña, creados al arrancar si no existen.
# Formato: "usuario1:contraseña1,usuario2:contraseña2".
BOOTSTRAP_USERS = _env("BOOTSTRAP_USERS")
# Usuarios con acceso al módulo de admin: "aleg" o "aleg,otro".
ADMIN_USERS = frozenset(u.strip() for u in _env("ADMIN_USERS").split(",") if u.strip())
PASSWORD_MIN_LENGTH = 8
# Passkeys (Face ID / huella). Vacíos = se toman del dominio del request (Railway: reinventar-production.up.railway.app).
# Si se cambia de dominio, las passkeys registradas dejan de servir y hay que registrarlas de nuevo.
WEBAUTHN_RP_ID = _env("WEBAUTHN_RP_ID")
WEBAUTHN_ORIGIN = _env("WEBAUTHN_ORIGIN")

# Mails (app/mail.py): verificación del mail de cada persona y recuperación de contraseña.
#   off    → no se manda nada y el mail no se exige (default: un entorno sin configurar no deja a nadie afuera)
#   fake   → tests y desarrollo: no sale nada (en Railway cuenta como off)
#   smtp   → SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD; SMTP_SEGURIDAD = starttls (587) | ssl (465) | ninguna
#   resend → API HTTP de Resend con RESEND_API_KEY
# MAIL_FROM es el remitente («ReinventAR <no-responder@tu-dominio>»), de un dominio verificado en el proveedor.
MAIL_PROVIDER = _env("MAIL_PROVIDER", "off")
MAIL_FROM = _env("MAIL_FROM")
SMTP_HOST = _env("SMTP_HOST")
SMTP_PORT = int(_env("SMTP_PORT", "587"))
SMTP_USER = _env("SMTP_USER")
SMTP_PASSWORD = _env("SMTP_PASSWORD")
SMTP_SEGURIDAD = _env("SMTP_SEGURIDAD", "starttls").lower()
RESEND_API_KEY = _env("RESEND_API_KEY")
# URL pública de la app, para el link de recuperación de contraseña (https://staging.reinventar.app). Si falta, se usa
# WEBAUTHN_ORIGIN. Nunca sale del Host del pedido en Railway: un Host falso no puede armar un link a otro sitio.
APP_URL = _env("APP_URL").rstrip("/")

# Persistencia: Postgres para datos (estado de la app en DB_SCHEMA, catálogo en el schema reinvent)
# y un Railway Volume en /data para los archivos de audio.
DATABASE_URL = _env("DATABASE_URL")
DB_SCHEMA = _env("DB_SCHEMA", "app")
# Schema del catálogo (charlas, speakers, sedes, eventos, shows). Producción: reinvent. Staging puede usar su propia copia
# (reinvent_staging) para probar la revisión automática sin tocar lo que ve producción.
CATALOGO_SCHEMA = _env("CATALOGO_SCHEMA", "reinvent")
DB_POOL_SIZE = int(_env("DB_POOL_SIZE", "5"))
DATA_DIR = Path(_env("DATA_DIR", "/data"))
LEGACY_SQLITE_PATH = DATA_DIR / "reinventar.db"  # base anterior: se importa sola al primer arranque con Postgres
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
EXTRACT_MODEL = _env("EXTRACT_MODEL", "claude-opus-5-5")  # claves del resumen de cada charla (scripts/extraer_claves.py)
SUMMARY_MODEL = _env("SUMMARY_MODEL", "claude-opus-5-5")
TARGET_LANGUAGE = _env("TARGET_LANGUAGE", "castellano rioplatense (Argentina)")

# Límites.
CSP_MODO = _env("CSP_MODO", "enforce")  # enforce | report | off (ver app/cabeceras.py)
MAX_CHUNK_BYTES = int(_env("MAX_CHUNK_BYTES", str(5 * 1024 * 1024)))
TRANSLATE_BATCH = int(_env("TRANSLATE_BATCH", "60"))  # bloques por llamada (~15 min de charla)
BLOCK_SECONDS = float(_env("BLOCK_SECONDS", "15"))  # largo objetivo de cada bloque de lectura (estilo subtítulos)

WEB_DIR = Path(__file__).resolve().parent.parent / "web"

# Catálogo de sesiones y motor de recomendación/itinerario.
ITINERARY_MODEL = _env("ITINERARY_MODEL", "claude-sonnet-5-5")
GUIDED_MODEL = _env("GUIDED_MODEL", ITINERARY_MODEL)  # razones del armado guiado (una oración por opción)
ITINERARY_CANDIDATE_LIMIT = int(_env("ITINERARY_CANDIDATE_LIMIT", "150"))  # sesiones que se le mandan al LLM como candidatas
ASK_MODEL = _env("ASK_MODEL", "claude-sonnet-5-5")  # chat de búsqueda sobre el catálogo
BRIEFING_MODEL = _env("BRIEFING_MODEL", "claude-sonnet-5-5")  # ficha para conversar con un speaker o empresa

# Búsqueda por significado (embeddings). local = modelo multilingüe dentro del contenedor; off = solo por palabras.
EMBED_PROVIDER = _env("EMBED_PROVIDER", "local")
# embeddinggemma-300m cuantizado a 4 bits: el mejor en scripts/evaluar_busqueda.py (recall@10 0,80 contra 0,74 de
# MiniLM) y lee 2048 tokens. "google/embeddinggemma-300m" es el original: casi igual de bueno, el triple de RAM.
EMBED_MODEL = _env("EMBED_MODEL", "google/embeddinggemma-300m-q4")
EMBED_CACHE_DIR = DATA_DIR / "models"  # en el volumen: el modelo se baja una sola vez
EMBED_BATCH = int(_env("EMBED_BATCH", "8"))  # lotes chicos: menos pico de memoria y en la Mac hasta más rápido
EMBED_THREADS = int(_env("EMBED_THREADS", "2"))  # hilos de ONNX: cada hilo suma memoria

# Mapa de venues: key de Google Maps JavaScript API (restringida por dominio en Google Cloud Console).
GOOGLE_MAPS_API_KEY = _env("GOOGLE_MAPS_API_KEY")  # la del navegador (Maps JavaScript API, restringida por sitio)
# Key solo para el servidor (Places API New, restringida por API y sin exponerse al navegador). Si falta, Places usa la
# del navegador fingiendo el Referer, como antes: funciona, pero quien vea la key del navegador puede usar Places.
GOOGLE_PLACES_SERVER_KEY = _env("GOOGLE_PLACES_SERVER_KEY")

# Web Push (notificaciones con la app cerrada): generar las claves con `python -m app.push`.
VAPID_PUBLIC_KEY = _env("VAPID_PUBLIC_KEY")
VAPID_PRIVATE_KEY = _env("VAPID_PRIVATE_KEY")
VAPID_SUBJECT = _env("VAPID_SUBJECT", "mailto:admin@example.com")

# Estado de vuelos (app/vuelos.py), vía AeroDataBox en api.market. Sin la clave no hay alertas de demora ni de puerta:
# el resto de los avisos de viajes anda igual. El tope corta las consultas del día (cuidan la cuota del plan).
AERODATABOX_API_KEY = _env("AERODATABOX_API_KEY")
AERODATABOX_TOPE_DIARIO = int(_env("AERODATABOX_TOPE_DIARIO", "150"))

# Entorno de Railway: "production" en producción. Va como tag (prod/dev) en las trazas de Langfuse (app/trazas.py).
RAILWAY_ENVIRONMENT_NAME = _env("RAILWAY_ENVIRONMENT_NAME")
# Pisa el tag de entorno de las trazas y los scores: el servicio de staging vive en el mismo entorno de Railway que
# producción, así que lleva ENTORNO=staging para no mezclarse con "prod" en Langfuse.
ENTORNO = _env("ENTORNO")

# Langfuse (opcional): con las dos claves, la app manda scores de calidad sobre las trazas (app/langfuse_scores.py) y el
# portal de admin lee sus métricas (app/langfuse_metricas.py), siempre desde el servidor: las claves nunca van al
# navegador. Sin claves, no se mandan scores y el tablero de LLM dice que no está disponible. Las trazas en sí las
# manda el gateway LiteLLM, con sus propias claves.
LANGFUSE_PUBLIC_KEY = _env("LANGFUSE_PUBLIC_KEY")
LANGFUSE_SECRET_KEY = _env("LANGFUSE_SECRET_KEY")
LANGFUSE_HOST = _env("LANGFUSE_HOST", "https://us.cloud.langfuse.com")

# Eventos automáticos (app/eventos_auto.py): revisión de Luma, conferenceparties y links sueltos cada N horas.
# Prendido (EVENTOS_AUTO=1) en un solo servicio por schema de catálogo: producción en reinvent; staging, solo si usa
# su copia (CATALOGO_SCHEMA=reinvent_staging), si no haría el trabajo y los push dos veces sobre lo de producción.
EVENTOS_AUTO = _env("EVENTOS_AUTO") == "1"
EVENTOS_AUTO_HORAS = float(_env("EVENTOS_AUTO_HORAS", "3"))
EVENTOS_AUTO_TOPE = int(_env("EVENTOS_AUTO_TOPE", "50"))  # eventos al LLM por revisión; lo que sobra, a la próxima

# Control de gastos del viaje (app/gastos.py, app/cotizacion.py, app/tickets_almacen.py).
# Dólar tarjeta = dólar oficial (venta) × este factor. Es el recargo de percepciones sobre los consumos en dólares con
# tarjeta (hoy 30 %): si cambia, se ajusta acá sin tocar código. Los gastos ya cargados conservan su cotización congelada.
TARJETA_FACTOR = float(_env("TARJETA_FACTOR", "1.30"))
# Hay entorno de Railway (producción y staging): ahí se exige bucket para las fotos y se avisa si falta FOTOS_LINK_SECRET.
EN_PRODUCCION = bool(RAILWAY_ENVIRONMENT_NAME)
# Actualización de la cotización cada tanto en segundo plano (y una al arrancar). Prendida salvo COTIZACION_AUTO=0;
# tests/conftest.py la apaga para que los tests no peguen a la red. No depende de ningún proveedor de STT/LLM.
COTIZACION_AUTO = _env("COTIZACION_AUTO", "1") == "1"
COTIZACION_MINUTOS = float(_env("COTIZACION_MINUTOS", "30"))
# Conversor › «Leer con la cámara» (app/conversor_api.py): apagado salvo CONVERSOR_FOTO=1. Apagado, POST
# /api/conversor/foto da 503 y el botón no aparece. Necesita el alias rx-foto (modelo con visión) en el gateway.
CONVERSOR_FOTO = _env("CONVERSOR_FOTO", "0") == "1"
# Fotos de ticket: bucket S3-compatible (el de Railway) si están las cinco variables; si no, disco local (dev y tests).
TICKETS_S3_ENDPOINT = _env("TICKETS_S3_ENDPOINT")
TICKETS_S3_BUCKET = _env("TICKETS_S3_BUCKET")
TICKETS_S3_KEY_ID = _env("TICKETS_S3_KEY_ID")
TICKETS_S3_SECRET = _env("TICKETS_S3_SECRET")
TICKETS_S3_REGION = _env("TICKETS_S3_REGION")
# Videos demo (galería pública /demos/, app/demos.py): su propio bucket. Sin las cinco variables, la galería dice que no
# hay demos (así está en producción hasta que se carguen).
DEMOS_S3_ENDPOINT = _env("DEMOS_S3_ENDPOINT")
DEMOS_S3_BUCKET = _env("DEMOS_S3_BUCKET")
DEMOS_S3_KEY_ID = _env("DEMOS_S3_KEY_ID")
DEMOS_S3_SECRET = _env("DEMOS_S3_SECRET")
DEMOS_S3_REGION = _env("DEMOS_S3_REGION")
DEMOS_LINK_HORAS = float(_env("DEMOS_LINK_HORAS", "6"))  # cuánto vale un link firmado a un video
# Links firmados a las fotos del CSV de reintegros (app/gastos_links.py). Sin FOTOS_LINK_SECRET se deriva de DATABASE_URL.
FOTOS_LINK_SECRET = _env("FOTOS_LINK_SECRET")
FOTOS_LINK_DIAS = float(_env("FOTOS_LINK_DIAS", "30"))
# Link público de solo lectura al resumen de una grabación (app/grabaciones_links.py): cuántos días vale. Usa la misma
# FOTOS_LINK_SECRET, con otra derivación: un link de foto no sirve como link de grabación ni al revés.
GRABACION_LINK_DIAS = float(_env("GRABACION_LINK_DIAS", "14"))
TICKETS_DIR = Path(_env("TICKETS_DIR", str(DATA_DIR / "tickets")))

# Documentos de viaje (pasaporte, visa, seguro, reservas; app/documentos.py): bucket propio, nunca el de tickets. Los
# archivos se cifran en la app (AES-256-GCM) con DOCS_ENC_KEY: 32 bytes en base64 (generarla con
# `python -c "import base64,os; print(base64.b64encode(os.urandom(32)).decode())"`). En Railway, sin las cinco DOCS_S3_*
# o sin la clave, la sección queda apagada (503): nunca cae al disco del contenedor. DOCS_DIR es solo para dev y tests.
DOCS_S3_ENDPOINT = _env("DOCS_S3_ENDPOINT")
DOCS_S3_BUCKET = _env("DOCS_S3_BUCKET")
DOCS_S3_KEY_ID = _env("DOCS_S3_KEY_ID")
DOCS_S3_SECRET = _env("DOCS_S3_SECRET")
DOCS_S3_REGION = _env("DOCS_S3_REGION")
DOCS_DIR = Path(_env("DOCS_DIR", str(DATA_DIR / "documentos")))
DOCS_ENC_KEY = _env("DOCS_ENC_KEY")

# Shows de Ticketmaster (app/ticketmaster.py): conciertos, espectáculos, deportes y actividades en Las Vegas, dentro de
# la misma revisión automática. Sin la key, la pestaña Shows no aparece y no se pide nada. La key viaja en la URL: nunca
# se loguea (ver app/ticketmaster.py).
TICKETMASTER_API_KEY = _env("TICKETMASTER_API_KEY")

# Excursiones de Viator (app/viator.py, Partner API de afiliado): pestaña Excursiones de Actividades. Sin la clave la
# pestaña no aparece y no se pide nada. Va en el header exp-api-key y nunca se loguea.
VIATOR_API_KEY = _env("VIATOR_API_KEY")

# Alertas de ofertas por push (app/ofertas.py y app/ofertas_avisos.py).
OFERTAS_MAX_POR_DIA = int(_env("OFERTAS_MAX_POR_DIA", "3"))        # push de ofertas por persona y por día (Las Vegas)
OFERTAS_VENTANA_HORAS = float(_env("OFERTAS_VENTANA_HORAS", "12"))  # una oferta que arrancó hace más que esto ya no se avisa
OFERTAS_SNAPSHOT_HORAS = float(_env("OFERTAS_SNAPSHOT_HORAS", "6"))  # cada cuánto se miran los precios de los shows
OFERTAS_BAJA_PORCENTAJE = float(_env("OFERTAS_BAJA_PORCENTAJE", "15"))  # una baja de precio es oferta desde este %...
OFERTAS_BAJA_USD = float(_env("OFERTAS_BAJA_USD", "20"))           # ...o desde estos dólares
