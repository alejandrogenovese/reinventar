-- Ids estables de AWS y campos del catálogo oficial que faltaban. Solo agrega: la app no cambia.
-- Idempotente y sin prefijo de schema (se corre con search_path apuntando al schema destino).

-- Speaker: el id de AWS (participants[].userRef) es la identidad; el nombre deja de ser único porque hay homónimos
-- (personas distintas que se llaman igual, como David Victoria de Amazon y el de Caylent).
ALTER TABLE speaker ADD COLUMN IF NOT EXISTS aws_speaker_id text;
CREATE UNIQUE INDEX IF NOT EXISTS uq_speaker__aws_speaker_id ON speaker (aws_speaker_id) WHERE aws_speaker_id IS NOT NULL;
ALTER TABLE speaker DROP CONSTRAINT IF EXISTS uq_speaker_nombre_clave;
CREATE INDEX IF NOT EXISTS ix_speaker__nombre_clave ON speaker (nombre_clave);

-- Horario: sessionID y sessionTimeID son de cada horario (no de la charla) y no cambian si AWS renombra el código.
ALTER TABLE speech_horario ADD COLUMN IF NOT EXISTS aws_session_id text;
ALTER TABLE speech_horario ADD COLUMN IF NOT EXISTS aws_time_id text;
ALTER TABLE speech_horario ADD COLUMN IF NOT EXISTS hora_fin time;
CREATE UNIQUE INDEX IF NOT EXISTS uq_speech_horario__aws_session_id ON speech_horario (aws_session_id) WHERE aws_session_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_speech_horario__aws_time_id ON speech_horario (aws_time_id) WHERE aws_time_id IS NOT NULL;

ALTER TABLE speech ADD COLUMN IF NOT EXISTS duracion_min smallint;
ALTER TABLE speech ADD COLUMN IF NOT EXISTS es_sponsoreada boolean NOT NULL DEFAULT false;
ALTER TABLE speech ADD COLUMN IF NOT EXISTS speakers_ocultos boolean NOT NULL DEFAULT false;
ALTER TABLE speech ADD COLUMN IF NOT EXISTS roles text[] NOT NULL DEFAULT '{}';
ALTER TABLE speech ADD COLUMN IF NOT EXISTS industria text[] NOT NULL DEFAULT '{}';
ALTER TABLE speech ADD COLUMN IF NOT EXISTS modificado timestamptz;

ALTER TABLE speech_speaker ADD COLUMN IF NOT EXISTS rol text;
ALTER TABLE speech_speaker ADD COLUMN IF NOT EXISTS cargo_en_charla text;

-- Códigos de horario que AWS renombró (PEX321 → PEX218). Viaja con el sync para migrar itinerarios y grabaciones.
CREATE TABLE IF NOT EXISTS codigo_renombrado (
  codigo_viejo text NOT NULL,
  codigo_nuevo text NOT NULL,
  aws_time_id  text NOT NULL,
  detectado    timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT pk_codigo_renombrado PRIMARY KEY (codigo_viejo)
);
