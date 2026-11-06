#!/usr/bin/env bash
# Sube el schema "reinvent" (catálogo, speakers, empresas) del docker local al Postgres de Railway.
# Solo pisa el schema reinvent: el schema "app" (usuarios, grabaciones, itinerarios) no se toca.
#
# Uso:  RAILWAY_DATABASE_URL='postgresql://...' scripts/sync_to_railway.sh
#       (URL pública: PGUSER, PGPASSWORD y PGDATABASE del servicio pgvector en Railway, con el host y puerto
#        del TCP Proxy: RAILWAY_TCP_PROXY_DOMAIN y RAILWAY_TCP_PROXY_PORT)
set -euo pipefail

LOCAL_CONTAINER="${LOCAL_CONTAINER:-reinvent-pg}"
SCHEMA="reinvent"
: "${RAILWAY_DATABASE_URL:?Falta RAILWAY_DATABASE_URL (URL pública del Postgres de Railway por el TCP Proxy)}"

DUMP="$(mktemp -t reinvent-sync).dump"
trap 'rm -f "${DUMP}"' EXIT

echo "> Exportando schema ${SCHEMA} desde ${LOCAL_CONTAINER}..."
docker exec "${LOCAL_CONTAINER}" pg_dump -U reinvent -d reinvent -n "${SCHEMA}" -Fc --no-owner --no-privileges > "${DUMP}"

# pg_restore corre dentro del contenedor local (misma versión de Postgres) para no depender de un cliente en la Mac.
echo "> Restaurando en Railway (reemplaza el schema ${SCHEMA})..."
docker exec -i "${LOCAL_CONTAINER}" sh -c "
  psql '${RAILWAY_DATABASE_URL}' -v ON_ERROR_STOP=1 -q \
    -c 'CREATE EXTENSION IF NOT EXISTS vector' \
    -c 'CREATE EXTENSION IF NOT EXISTS pg_trgm' \
    -c 'CREATE EXTENSION IF NOT EXISTS unaccent' \
    -c 'DROP SCHEMA IF EXISTS ${SCHEMA} CASCADE' &&
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

echo "> Verificación en Railway:"
docker exec "${LOCAL_CONTAINER}" psql "${RAILWAY_DATABASE_URL}" -P pager=off -c "
  SELECT (SELECT count(*) FROM ${SCHEMA}.speech)         AS speech,
         (SELECT count(*) FROM ${SCHEMA}.speech_horario) AS horarios,
         (SELECT count(*) FROM ${SCHEMA}.speaker)        AS speakers,
         (SELECT count(*) FROM ${SCHEMA}.empresa)        AS empresas"
