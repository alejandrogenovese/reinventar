-- Minutos caminando entre sedes (para avisar "si salís 30 min antes llegás"). Se calcula una sola vez con la Routes API
-- (scripts/calcular_tiempos_sedes.py) porque entre edificios no cambia. Un par que falta se estima en la app
-- (app/travel.py) por distancia en línea recta.
-- Idempotente y sin prefijo de schema (se corre con search_path apuntando al schema destino).

CREATE TABLE IF NOT EXISTS sede_tiempo (
  id_origen  smallint    NOT NULL REFERENCES sede (id_sede),
  id_destino smallint    NOT NULL REFERENCES sede (id_sede),
  minutos    smallint    NOT NULL,
  metros     integer     NOT NULL,
  calculado  timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT pk_sede_tiempo PRIMARY KEY (id_origen, id_destino),
  CONSTRAINT ck_sede_tiempo__distintas CHECK (id_origen <> id_destino),
  CONSTRAINT ck_sede_tiempo__positivos CHECK (minutos > 0 AND metros > 0)
);
