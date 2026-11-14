-- Shows de Ticketmaster (app/ticketmaster.py): cada fila es una función (un evento de Ticketmaster con día y hora).
-- Las funciones del mismo artista en la misma sala comparten id_show (la tarjeta de la lista es el show).
-- Aditiva e idempotente. Sin prefijo de schema (search_path al schema destino).
-- La mantiene la revisión automática de producción: se refresca en cada revisión y se borra lo que ya pasó.
CREATE TABLE IF NOT EXISTS show_funcion (
  id_funcion    text PRIMARY KEY,                  -- id del evento en Ticketmaster
  id_show       text NOT NULL,                     -- artista (o nombre normalizado) + sala
  nombre        text NOT NULL,
  artista       text,
  tipo          text NOT NULL,                     -- musica | teatro | comedia | deportes | actividades
  sala          text NOT NULL,
  direccion     text,
  lat           numeric(9, 6),
  lng           numeric(9, 6),
  inicio        timestamptz NOT NULL,
  estado        text NOT NULL DEFAULT 'onsale',    -- onsale | offsale | canceled | postponed | rescheduled
  precio_desde  numeric(10, 2),                    -- en dólares, solo si Ticketmaster lo trae
  imagen_url    text,
  url           text,
  actualizado   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS show_funcion_inicio ON show_funcion (inicio);
CREATE INDEX IF NOT EXISTS show_funcion_show ON show_funcion (id_show);
