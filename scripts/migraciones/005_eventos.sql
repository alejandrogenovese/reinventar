-- Eventos de networking alrededor de re:Invent (desayunos, happy hours, fiestas, meetups), de Luma y otras fuentes.
-- Los carga scripts/cargar_eventos.py: datos de la fuente + su página pública + resumen y tipo con un LLM.
-- Lo que agrega cada usuario va a su itinerario (app.itinerary_items, tipo = 'evento'), sin FK entre schemas.
-- Idempotente y sin prefijo de schema (se corre con search_path apuntando al schema destino).

CREATE TABLE IF NOT EXISTS evento (
  id_evento           text PRIMARY KEY,              -- id de la fuente (Luma: event_api_id, evt-…)
  plataforma          text NOT NULL,                 -- luma, …
  url                 text NOT NULL,
  nombre              text NOT NULL,
  inicio              timestamptz NOT NULL,
  fin                 timestamptz,
  imagen_url          text,
  lat                 numeric(9, 6),
  lng                 numeric(9, 6),
  lugar               text,                          -- "Topgolf Las Vegas"
  direccion           text,
  direccion_exacta    boolean NOT NULL DEFAULT false, -- false: la fuente solo dice la ciudad hasta que te anotás
  google_place_id     text,
  descripcion         text,                          -- original, en inglés
  resumen_es          text,                          -- qué es, para quién y por qué ir (LLM)
  tipo                text,                          -- ver TIPOS en scripts/cargar_eventos.py
  temas               text[] NOT NULL DEFAULT '{}',
  organizadores       text[] NOT NULL DEFAULT '{}',  -- empresas que lo organizan
  anotados            integer,
  lleno               boolean NOT NULL DEFAULT false,
  precio              text,                          -- "Gratis", "USD 50"
  requiere_aprobacion boolean NOT NULL DEFAULT false,
  id_sede_cercana     smallint REFERENCES sede (id_sede),
  metros_a_sede       integer,
  actualizado         timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT ck_evento__coordenadas CHECK ((lat IS NULL) = (lng IS NULL)),
  CONSTRAINT ck_evento__fin CHECK (fin IS NULL OR fin >= inicio)
);

CREATE INDEX IF NOT EXISTS ix_evento__inicio ON evento (inicio);
