-- Pasa los itinerarios y grabaciones de la app a los códigos nuevos que registró actualizar_catalogo.py en
-- codigo_renombrado (AWS renombró PEX321 → PEX218). Idempotente. Se corre donde están los datos de usuarios (Railway),
-- después del sync:
--   psql "$URL" -1 -v ON_ERROR_STOP=1 -v catalogo=reinvent -v app=app -f scripts/migrar_codigos_app.sql

-- Sigue cadenas (A → B → C) hasta el código que existe hoy. Un código viejo que volvió al catálogo no se migra:
-- AWS lo reusó y lo que apunta a él es válido.
DROP TABLE IF EXISTS pg_temp.mapa_codigos;
CREATE TEMP TABLE mapa_codigos AS
WITH RECURSIVE cadena (viejo, nuevo, saltos) AS (
  SELECT codigo_viejo, codigo_nuevo, 1 FROM :"catalogo".codigo_renombrado
  UNION ALL
  SELECT c.viejo, r.codigo_nuevo, c.saltos + 1
  FROM cadena c JOIN :"catalogo".codigo_renombrado r ON r.codigo_viejo = c.nuevo
  WHERE c.saltos < 20 AND r.codigo_nuevo <> c.viejo  -- corta ciclos A → B → A
)
SELECT DISTINCT ON (c.viejo) c.viejo, c.nuevo, h.id_speech AS base_nueva
FROM cadena c JOIN :"catalogo".speech_horario h ON h.codigo = c.nuevo
WHERE NOT EXISTS (SELECT 1 FROM :"catalogo".speech_horario x WHERE x.codigo = c.viejo)
ORDER BY c.viejo, c.saltos DESC;

-- Si el usuario ya tiene el código nuevo, o dos códigos viejos suyos terminan en el mismo nuevo, sobran los repetidos
-- (se queda el código nuevo, o el primer viejo en orden alfabético).
DELETE FROM :"app".itinerary_items i
USING mapa_codigos m
WHERE i.code = m.viejo
  AND (EXISTS (SELECT 1 FROM :"app".itinerary_items x WHERE x.username = i.username AND x.code = m.nuevo)
       OR EXISTS (SELECT 1 FROM :"app".itinerary_items y JOIN mapa_codigos m2 ON m2.viejo = y.code
                  WHERE y.username = i.username AND m2.nuevo = m.nuevo AND y.code < i.code));

UPDATE :"app".itinerary_items i SET code = m.nuevo, base = m.base_nueva
FROM mapa_codigos m WHERE i.code = m.viejo;

-- Las grabaciones guardan el código del horario o el de la charla.
UPDATE :"app".sessions s SET code = m.nuevo
FROM mapa_codigos m WHERE upper(s.code) = m.viejo;

UPDATE :"app".sessions s SET code = m.base_nueva
FROM mapa_codigos m
WHERE upper(s.code) = regexp_replace(m.viejo, '-R\d*$', '')
  AND NOT EXISTS (SELECT 1 FROM :"catalogo".speech x WHERE x.id_speech = upper(s.code))
  AND NOT EXISTS (SELECT 1 FROM :"catalogo".speech_horario x WHERE x.codigo = upper(s.code));
