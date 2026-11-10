#!/usr/bin/env bash
# Sube el schema "reinvent" (catálogo, speakers, empresas) del docker local al Postgres de Railway.
# Solo pisa el schema reinvent: el schema "app" (usuarios, grabaciones, itinerarios) no se toca.
#
# Uso:  RAILWAY_DATABASE_URL='postgresql://...' scripts/sync_to_railway.sh
#       (URL pública: PGUSER, PGPASSWORD y PGDATABASE del servicio pgvector en Railway, con el host y puerto
#        del TCP Proxy: RAILWAY_TCP_PROXY_DOMAIN y RAILWAY_TCP_PROXY_PORT)
#
# Versiones: el docker local corre Postgres 16 y Railway Postgres 18. pg_dump 16 → pg_restore en 18 está soportado
# (un dump siempre se puede restaurar en una versión mayor); al revés no, así que no bajes Railway a una versión menor.
#
# Al final corre scripts/migrar_codigos_app.sql: pasa itinerarios y grabaciones de los códigos que AWS renombró
# (tabla reinvent.codigo_renombrado, que carga scripts/actualizar_catalogo.py) a los códigos nuevos.
set -euo pipefail

LOCAL_CONTAINER="${LOCAL_CONTAINER:-reinvent-pg}"
SCHEMA="reinvent"
APP_SCHEMA="${APP_SCHEMA:-app}"
: "${RAILWAY_DATABASE_URL:?Falta RAILWAY_DATABASE_URL (URL pública del Postgres de Railway por el TCP Proxy)}"

DUMP="$(mktemp -t reinvent-sync).dump"
trap 'rm -f "${DUMP}"' EXIT

echo "> Exportando schema ${SCHEMA} desde ${LOCAL_CONTAINER}..."
docker exec "${LOCAL_CONTAINER}" pg_dump -U reinvent -d reinvent -n "${SCHEMA}" -Fc --no-owner --no-privileges > "${DUMP}"

# pg_restore corre dentro del contenedor local (misma versión de Postgres) para no depender de un cliente en la Mac.
# Si alguna extensión quedó instalada dentro de ${SCHEMA}, el DROP ... CASCADE se la llevaría (y con ella los índices
# y columnas que dependen de ella en el schema app). Se aborta antes de tocar nada.
EXT_EN_SCHEMA="$(docker exec "${LOCAL_CONTAINER}" psql "${RAILWAY_DATABASE_URL}" -At -v ON_ERROR_STOP=1 -c "
  SELECT string_agg(e.extname, ', ') FROM pg_extension e JOIN pg_namespace n ON n.oid = e.extnamespace
  WHERE n.nspname = '${SCHEMA}'")"
if [[ -n "${EXT_EN_SCHEMA}" ]]; then
  echo "ERROR: en Railway las extensiones ${EXT_EN_SCHEMA} viven en el schema ${SCHEMA}; el DROP las borraría." >&2
  echo "       Movelas a public antes de sincronizar (ALTER EXTENSION <nombre> SET SCHEMA public)." >&2
  exit 1
fi

# Primero el DROP y después las extensiones, en public: así nunca quedan adentro del schema que se reemplaza.
echo "> Restaurando en Railway (reemplaza el schema ${SCHEMA})..."
docker exec -i "${LOCAL_CONTAINER}" sh -c "
  psql '${RAILWAY_DATABASE_URL}' -v ON_ERROR_STOP=1 -q \
    -c 'DROP SCHEMA IF EXISTS ${SCHEMA} CASCADE' \
    -c 'CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public' \
    -c 'CREATE EXTENSION IF NOT EXISTS pg_trgm WITH SCHEMA public' \
    -c 'CREATE EXTENSION IF NOT EXISTS unaccent WITH SCHEMA public' &&
  pg_restore -d '${RAILWAY_DATABASE_URL}' --no-owner --no-privileges --exit-on-error
" < "${DUMP}"

# El DROP ... CASCADE se lleva los permisos: el rol de solo lectura de los colaboradores (si existe) los recupera.
docker exec "${LOCAL_CONTAINER}" psql "${RAILWAY_DATABASE_URL}" -v ON_ERROR_STOP=1 -q -c "
  DO \$\$ BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'colaborador') THEN
      GRANT USAGE ON SCHEMA ${SCHEMA} TO colaborador;
      GRANT SELECT ON ALL TABLES IN SCHEMA ${SCHEMA} TO colaborador;
      ALTER DEFAULT PRIVILEGES IN SCHEMA ${SCHEMA} GRANT SELECT ON TABLES TO colaborador;
    END IF;
  END \$\$"

echo "> Migrando itinerarios y grabaciones a los códigos renombrados (schema ${APP_SCHEMA})..."
docker exec -i "${LOCAL_CONTAINER}" psql "${RAILWAY_DATABASE_URL}" -1 -q -v ON_ERROR_STOP=1 \
  -v catalogo="${SCHEMA}" -v app="${APP_SCHEMA}" -f - < "$(dirname "$0")/migrar_codigos_app.sql"

echo "> Verificación en Railway:"
docker exec "${LOCAL_CONTAINER}" psql "${RAILWAY_DATABASE_URL}" -P pager=off -c "
  SELECT (SELECT count(*) FROM ${SCHEMA}.speech)         AS speech,
         (SELECT count(*) FROM ${SCHEMA}.speech_horario) AS horarios,
         (SELECT count(*) FROM ${SCHEMA}.speaker)        AS speakers,
         (SELECT count(*) FROM ${SCHEMA}.empresa)        AS empresas,
         (SELECT count(*) FROM ${APP_SCHEMA}.itinerary_items i
           WHERE NOT EXISTS (SELECT 1 FROM ${SCHEMA}.speech_horario h WHERE h.codigo = i.code)) AS itinerarios_huerfanos"
