# Gateway de LLM (LiteLLM) para ReinventAR: un alias por tarea de la app (config.yaml) y trazas en Langfuse.
# En Railway: servicio aparte con Root Directory = infra/litellm. Las keys van en las variables del servicio, nunca acá.
# Imagen "-database": incluye lo necesario para el panel y las claves virtuales (DATABASE_URL). Versión fija: se
# actualiza a mano, probando antes.
FROM ghcr.io/berriai/litellm-database:v1.108.5-lts

COPY config.yaml /app/config.yaml

EXPOSE 4000
CMD ["--config", "/app/config.yaml", "--host", "0.0.0.0", "--port", "4000"]
