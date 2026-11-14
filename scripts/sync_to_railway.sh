#!/usr/bin/env bash
# Sube el schema "reinvent" (catálogo, speakers, empresas, eventos, sedes y tiempos entre sedes) del docker local al
# Postgres de Railway, todo en UNA transacción:
#   - sin flags: modo prueba. Reemplaza, migra códigos, verifica y hace ROLLBACK (Railway queda igual).
#   - --aplicar: antes hace backup de Railway (reinvent + app) y al final COMMIT.
# El schema "app" (usuarios, grabaciones, itinerarios) no se reemplaza: solo se migran los códigos que AWS renombró
# (scripts/migrar_codigos_app.sql, con la tabla reinvent.codigo_renombrado que carga scripts/actualizar_catalogo.py).
#
# Uso (desde cualquier carpeta; corrélo en tu Terminal, no con "!": pide la clave sin mostrarla):
#   scripts/sync_to_railway.sh             # prueba
#   scripts/sync_to_railway.sh --aplicar   # backup + aplica
# Pide host, puerto, usuario y clave del TCP Proxy del servicio pgvector, o usa RAILWAY_DATABASE_URL si está exportada
# (postgresql://<PGUSER>:<PGPASSWORD>@<RAILWAY_TCP_PROXY_DOMAIN>:<RAILWAY_TCP_PROXY_PORT>/<PGDATABASE>).
# Después de aplicar, reiniciá el servicio de la app (o "Recargar catálogo" en Administración).
#
# Eventos: desde que la app los mantiene sola (app/eventos_auto.py, links cargados a mano, cancelados), los de Railway
# mandan: reinvent.evento y reinvent.evento_revision se guardan antes del DROP y se reponen después (por nombre de
# columna, así una base sin la migración 007 también sirve). Para pisarlos con los del docker local:
#   REEMPLAZAR_EVENTOS=1 scripts/sync_to_railway.sh --aplicar
#
# Versiones: el docker local corre Postgres 16 y Railway 18. Restaurar en una versión mayor está soportado; el backup
# de Railway se hace con un contenedor pgvector de la versión del servidor (pg_dump tiene que ser igual o más nuevo).
set -euo pipefail

MODO="${1:-}"
REPO="$(cd "$(dirname "$0")/.." && pwd)"
LOCAL_CONTAINER="${LOCAL_CONTAINER:-reinvent-pg}"
REEMPLAZAR_EVENTOS="${REEMPLAZAR_EVENTOS:-0}"
BACKUP_DIR="${BACKUP_DIR:-$HOME/Documents/Proyectos/Scripts/reinventar/backups_reinvent}"
STAMP="$(date +%Y%m%d-%H%M%S)"

if [[ -n "$MODO" && "$MODO" != "--aplicar" ]]; then
  echo "Uso: $0 [--aplicar]" >&2
  exit 2
fi

if [[ -z "${RAILWAY_DATABASE_URL:-}" ]]; then
  echo "Datos de conexión de Railway (servicio pgvector → Variables / Settings → Networking → TCP Proxy)."
  read -r -p "  Host del TCP Proxy (RAILWAY_TCP_PROXY_DOMAIN) o URL completa: " PG_HOST
  if [[ "$PG_HOST" == postgres*://* ]]; then
    RAILWAY_DATABASE_URL="$PG_HOST"
  else
    read -r -p "  Puerto (RAILWAY_TCP_PROXY_PORT): " PG_PORT
    read -r -p "  Usuario (PGUSER) [postgres]: " PG_USER; PG_USER="${PG_USER:-postgres}"
    read -r -s -p "  Clave (PGPASSWORD, no se muestra): " PG_PASS; echo
    read -r -p "  Base (PGDATABASE) [railway]: " PG_DB; PG_DB="${PG_DB:-railway}"
    PG_PASS_ENC="$(python3 -c 'import sys, urllib.parse; print(urllib.parse.quote(sys.argv[1], safe=""))' "$PG_PASS")"
    RAILWAY_DATABASE_URL="postgresql://${PG_USER}:${PG_PASS_ENC}@${PG_HOST}:${PG_PORT}/${PG_DB}"
  fi
  unset PG_PASS PG_PASS_ENC
fi
echo "> Railway: ${RAILWAY_DATABASE_URL%%://*}://***@${RAILWAY_DATABASE_URL##*@}"

docker ps --format '{{.Names}}' | grep -qx "$LOCAL_CONTAINER" || { echo "El contenedor $LOCAL_CONTAINER no está corriendo." >&2; exit 1; }
# psql corre dentro del contenedor local para no depender de un cliente de Postgres en la Mac.
remote_psql() { docker exec -i "$LOCAL_CONTAINER" psql "$RAILWAY_DATABASE_URL" -v ON_ERROR_STOP=1 "$@"; }

# Si alguna extensión quedó instalada dentro de reinvent, el DROP ... CASCADE se la llevaría (y con ella índices y
# columnas del schema app). Se aborta antes de tocar nada.
EXT="$(remote_psql -At -c "SELECT string_agg(e.extname, ', ') FROM pg_extension e
  JOIN pg_namespace n ON n.oid = e.extnamespace WHERE n.nspname = 'reinvent'")"
if [[ -n "$EXT" ]]; then
  echo "ERROR: en Railway las extensiones $EXT viven en el schema reinvent; el DROP las borraría." >&2
  echo "       Movelas a public antes de sincronizar (ALTER EXTENSION <nombre> SET SCHEMA public)." >&2
  exit 1
fi

echo "> Antes, en Railway:"
remote_psql -P pager=off -c "SELECT (SELECT count(*) FROM information_schema.tables WHERE table_schema='reinvent') AS tablas_reinvent,
  (SELECT count(*) FROM app.users) AS usuarios, (SELECT count(*) FROM app.itinerary_items) AS items_itinerario"

if [[ "$MODO" == "--aplicar" ]]; then
  mkdir -p "$BACKUP_DIR"
  MAJOR=$(( $(remote_psql -At -c 'SHOW server_version_num') / 10000 ))
  IMG="pgvector/pgvector:pg${MAJOR}"
  BK="$BACKUP_DIR/railway_antes_sync_${STAMP}.dump"
  echo "> Backup de Railway (reinvent + app) con $IMG → $BK"
  docker pull -q "$IMG" >/dev/null
  docker run --rm -i "$IMG" pg_dump "$RAILWAY_DATABASE_URL" -n reinvent -n app -Fc --no-owner --no-privileges > "$BK"
  echo "    $(du -h "$BK" | cut -f1)"
  FIN="COMMIT;"
else
  echo "> MODO PRUEBA: todo corre en una transacción que termina en ROLLBACK."
  FIN="ROLLBACK;"
fi

# Se exporta a un archivo ANTES de abrir la transacción: si la fuente y el destino fueran la misma base, un pg_dump
# en paralelo esperaría el lock del DROP SCHEMA para siempre.
echo "> Exportando reinvent del docker local..."
SQL_LOCAL="$(mktemp -t reinvent-sync).sql"
trap 'rm -f "$SQL_LOCAL"' EXIT
docker exec "$LOCAL_CONTAINER" sh -c "pg_dump -U reinvent -d reinvent -n reinvent -Fc --no-owner --no-privileges | pg_restore --no-owner --no-privileges -f -" > "$SQL_LOCAL"
echo "    $(du -h "$SQL_LOCAL" | cut -f1)"

# Primero el DROP y después las extensiones, en public: así nunca quedan adentro del schema que se reemplaza.
echo "> Aplicando en Railway (una sola transacción)..."
{
  echo "BEGIN;"
  if [[ "$REEMPLAZAR_EVENTOS" != "1" ]]; then
    cat <<'SQL'
DO $$ BEGIN
  IF to_regclass('reinvent.evento') IS NOT NULL THEN
    EXECUTE 'CREATE TEMP TABLE guardado_evento ON COMMIT DROP AS SELECT * FROM reinvent.evento';
  END IF;
  IF to_regclass('reinvent.evento_revision') IS NOT NULL THEN
    EXECUTE 'CREATE TEMP TABLE guardado_evento_revision ON COMMIT DROP AS SELECT * FROM reinvent.evento_revision';
  END IF;
END $$;
SQL
  fi
  echo "DROP SCHEMA IF EXISTS reinvent CASCADE;"
  echo "CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public;"
  echo "CREATE EXTENSION IF NOT EXISTS pg_trgm WITH SCHEMA public;"
  echo "CREATE EXTENSION IF NOT EXISTS unaccent WITH SCHEMA public;"
  cat "$SQL_LOCAL"
  if [[ "$REEMPLAZAR_EVENTOS" != "1" ]]; then
    cat <<'SQL'
\echo '> Reponiendo los eventos de Railway (los mantiene la app)...'
DO $$ BEGIN
  IF to_regclass('pg_temp.guardado_evento') IS NOT NULL THEN
    -- Si Railway ya tiene las columnas de la revisión automática y el docker local no, se perderían los cancelados.
    IF EXISTS (SELECT 1 FROM pg_attribute WHERE attrelid = to_regclass('pg_temp.guardado_evento')
                 AND attname = 'cancelado_desde' AND NOT attisdropped)
       AND NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'reinvent'
                         AND table_name = 'evento' AND column_name = 'cancelado_desde') THEN
      RAISE EXCEPTION 'El docker local no tiene la migración 007: corré las migraciones locales antes del sync';
    END IF;
    IF EXISTS (SELECT 1 FROM pg_temp.guardado_evento) THEN  -- Railway sin eventos: quedan los del docker local
    EXECUTE 'DELETE FROM reinvent.evento';
    -- Por nombre de columna; una sede que ya no existe en el maestro local queda vacía (no rompe la FK).
    EXECUTE $q$
      INSERT INTO reinvent.evento
      SELECT (jsonb_populate_record(NULL::reinvent.evento, to_jsonb(g) ||
              CASE WHEN g.id_sede_cercana IS NULL
                     OR EXISTS (SELECT 1 FROM reinvent.sede s WHERE s.id_sede = g.id_sede_cercana)
                   THEN '{}'::jsonb ELSE '{"id_sede_cercana": null, "metros_a_sede": null}'::jsonb END)).*
      FROM pg_temp.guardado_evento g
    $q$;
    END IF;
  END IF;
  IF to_regclass('pg_temp.guardado_evento_revision') IS NOT NULL
     AND to_regclass('reinvent.evento_revision') IS NOT NULL THEN
    EXECUTE 'DELETE FROM reinvent.evento_revision';
    EXECUTE 'INSERT INTO reinvent.evento_revision SELECT (jsonb_populate_record(NULL::reinvent.evento_revision, '
            'to_jsonb(g))).* FROM pg_temp.guardado_evento_revision g';
  END IF;
END $$;
SQL
  fi
  # El DROP ... CASCADE se lleva los permisos: el rol de solo lectura de los colaboradores (si existe) los recupera.
  cat <<'SQL'
DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'colaborador') THEN
    GRANT USAGE ON SCHEMA reinvent TO colaborador;
    GRANT SELECT ON ALL TABLES IN SCHEMA reinvent TO colaborador;
    ALTER DEFAULT PRIVILEGES IN SCHEMA reinvent GRANT SELECT ON TABLES TO colaborador;
  END IF;
END $$;
SQL
  cat "$REPO/scripts/migrar_codigos_app.sql"
  # Solo las charlas tienen que existir en el catálogo: los eventos (kind=event) y los propios (kind=mine) no.
  cat <<'SQL'
\echo '> Verificación (dentro de la transacción):'
\pset pager off
SELECT (SELECT count(*) FROM reinvent.speech) AS speech, (SELECT count(*) FROM reinvent.speech_horario) AS horarios,
       (SELECT count(*) FROM reinvent.speaker) AS speakers, (SELECT count(*) FROM reinvent.sede) AS sedes,
       (SELECT count(*) FROM reinvent.evento) AS eventos,
       (SELECT count(*) FROM reinvent.sede_tiempo) AS tiempos_entre_sedes,
       (SELECT count(*) FROM app.users) AS usuarios, (SELECT count(*) FROM app.itinerary_items) AS items_itinerario;
SELECT calidad_match, count(*) FROM reinvent.speaker_perfil GROUP BY 1 ORDER BY 1;
SELECT count(*) AS charlas_del_itinerario_sin_horario FROM app.itinerary_items i
 WHERE coalesce(to_jsonb(i)->>'kind', 'talk') = 'talk'
   AND NOT EXISTS (SELECT 1 FROM reinvent.speech_horario h WHERE h.codigo = i.code);
SQL
  echo "$FIN"
} | remote_psql -q -v catalogo=reinvent -v app=app -f -

if [[ "$MODO" == "--aplicar" ]]; then
  echo "Listo: aplicado. Backup en $BK"
  echo "Reiniciá el servicio de la app en Railway (o \"Recargar catálogo\" en Administración) para que lo tome."
else
  echo "Prueba OK: Railway quedó igual. Para aplicar: $0 --aplicar"
fi
