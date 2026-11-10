-- Maestro de sedes: una fila por edificio, con coordenadas para el mapa (antes estaban fijas en app/venues.py).
-- sede_alias traduce el texto que manda AWS ("Canonita (located in The Venetian)") a su sede; si es un lugar dentro
-- del edificio, "lugar" queda como sala del horario. speech_horario.sede (texto) pasa a id_sede con FK.
-- Idempotente y sin prefijo de schema (se corre con search_path apuntando al schema destino).

CREATE TABLE IF NOT EXISTS sede (
  id_sede   smallint PRIMARY KEY,
  nombre    text NOT NULL,
  lat       numeric(9, 6),
  lng       numeric(9, 6),
  direccion text,
  CONSTRAINT uq_sede__nombre UNIQUE (nombre),
  CONSTRAINT ck_sede__coordenadas CHECK ((lat IS NULL) = (lng IS NULL))
);

CREATE TABLE IF NOT EXISTS sede_alias (
  alias   text PRIMARY KEY,       -- tal cual lo manda AWS en times[].room
  id_sede smallint NOT NULL REFERENCES sede (id_sede),
  lugar   text                    -- bar o restaurante dentro de la sede: se guarda como sala del horario
);

INSERT INTO sede (id_sede, nombre, lat, lng, direccion) VALUES
  (1, 'Allegiant Stadium', 36.090794, -115.183952, '3333 Al Davis Way'),
  (2, 'Caesars Forum',     36.117900, -115.164100, '3911 Koval Ln'),
  (3, 'Wynn/Encore',       36.126492, -115.165741, '3131 Las Vegas Blvd S'),
  (4, 'Caesars Palace',    36.117780, -115.175000, '3570 Las Vegas Blvd S'),
  (5, 'MGM Grand',         36.102219, -115.169517, '3799 Las Vegas Blvd S'),
  (6, 'Various Locations', NULL,      NULL,        NULL),
  (7, 'Venetian',          36.121600, -115.169100, '3355 Las Vegas Blvd S')
ON CONFLICT (id_sede) DO NOTHING;

INSERT INTO sede_alias (alias, id_sede, lugar) VALUES
  ('Allegiant Stadium', 1, NULL),
  ('Caesars Forum', 2, NULL),
  ('Wynn/Encore', 3, NULL),
  ('Tableau (located in Wynn)', 3, 'Tableau'),
  ('Caesars Palace', 4, NULL),
  ('MGM Grand', 5, NULL),
  ('TAP Sports Bar (located in MGM Grand)', 5, 'TAP Sports Bar'),
  ('Various Locations', 6, NULL),
  ('Venetian', 7, NULL),
  ('Delmonico (located in The Venetian)', 7, 'Delmonico'),
  ('Canonita (located in The Venetian)', 7, 'Canonita'),
  ('Flight Club (located in The Venetian)', 7, 'Flight Club')
ON CONFLICT (alias) DO NOTHING;

-- speech_horario.sede (texto) → id_sede. Solo la primera vez: después la columna sede ya no existe.
DO $$
DECLARE
  sin_mapear text;
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.columns
             WHERE table_schema = current_schema() AND table_name = 'speech_horario' AND column_name = 'sede') THEN
    ALTER TABLE speech_horario ADD COLUMN IF NOT EXISTS id_sede smallint;
    UPDATE speech_horario h SET id_sede = a.id_sede, sala = coalesce(h.sala, a.lugar)
    FROM sede_alias a WHERE a.alias = h.sede;
    SELECT string_agg(DISTINCT sede, ', ') INTO sin_mapear FROM speech_horario WHERE id_sede IS NULL;
    IF sin_mapear IS NOT NULL THEN
      RAISE EXCEPTION 'Sedes sin mapear en sede_alias: %', sin_mapear;
    END IF;
    ALTER TABLE speech_horario ALTER COLUMN id_sede SET NOT NULL;
    ALTER TABLE speech_horario DROP COLUMN sede;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint
                 WHERE conname = 'fk_speech_horario__sede' AND connamespace = current_schema()::regnamespace) THEN
    ALTER TABLE speech_horario ADD CONSTRAINT fk_speech_horario__sede FOREIGN KEY (id_sede) REFERENCES sede (id_sede);
  END IF;
END $$;

CREATE INDEX IF NOT EXISTS ix_speech_horario__id_sede ON speech_horario (id_sede);
