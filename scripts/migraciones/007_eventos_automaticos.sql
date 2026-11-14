-- Eventos automáticos (app/eventos_auto.py): la app de producción revisa las fuentes cada 3 horas.
-- Aditiva e idempotente: solo agrega columnas y una tabla. Sin prefijo de schema (search_path al schema destino).

-- falta_desde: la primera revisión en la que el evento no apareció en su fuente (NULL si apareció en la última).
-- cancelado_desde: faltó en dos revisiones seguidas; si vuelve a aparecer, se pone en NULL.
-- alta: cuándo lo encontró la revisión automática (NULL para la carga inicial y lo cargado a mano): dispara el push
--       de "eventos nuevos".
ALTER TABLE evento ADD COLUMN IF NOT EXISTS falta_desde timestamptz;
ALTER TABLE evento ADD COLUMN IF NOT EXISTS cancelado_desde timestamptz;
ALTER TABLE evento ADD COLUMN IF NOT EXISTS alta timestamptz;

-- Estado de la última revisión de cada fuente (lo muestra el admin): luma, conferenceparties, links.
CREATE TABLE IF NOT EXISTS evento_revision (
  fuente      text PRIMARY KEY,
  revisado    timestamptz NOT NULL,
  ok          boolean NOT NULL,
  total       integer NOT NULL DEFAULT 0,      -- eventos que trajo la fuente
  nuevos      integer NOT NULL DEFAULT 0,
  cambiados   integer NOT NULL DEFAULT 0,
  cancelados  integer NOT NULL DEFAULT 0,
  pendientes  integer NOT NULL DEFAULT 0,      -- sin resumen todavía (quedaron afuera del tope del LLM)
  detalle     text                             -- error o aviso, sin datos sensibles
);
