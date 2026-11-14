FROM python:3.12-slim

# ffmpeg: une los pedazos webm/opus y corta el audio para el STT.
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg \
 && rm -rf /var/lib/apt/lists/*

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 DATA_DIR=/data
WORKDIR /srv

# Lock con hashes y solo wheels (regenerarlo: ver CONTRIBUTING.md → Dependencias).
COPY requirements.lock .
RUN pip install --no-cache-dir --require-hashes --only-binary :all: -r requirements.lock

COPY app ./app
COPY web ./web

# --no-proxy-headers: uvicorn no reescribe request.client desde X-Forwarded-For (lo manda el cliente y esquivaba el
# límite por IP). La IP sale de X-Real-IP (app/auth_api.py) y el esquema https de app/esquema_proxy.py.
# Railway inyecta PORT. Un solo worker: el pipeline corre en un thread del proceso.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1 --no-proxy-headers"]
