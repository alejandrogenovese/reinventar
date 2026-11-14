-- Charlas que se bajan o cambian (app/charlas_auto.py): la app de producción compara speech_horario con el buscador
-- público del catálogo oficial. Aditiva e idempotente: solo agrega columnas. Sin prefijo de schema.

-- falta_desde: la primera revisión en la que el horario no apareció en el catálogo oficial (NULL si apareció en la
--              última). La app muestra un aviso en la charla.
-- cancelado_desde: faltó en dos revisiones seguidas: la charla figura como «Cancelada». Si reaparece, vuelve a NULL.
ALTER TABLE speech_horario ADD COLUMN IF NOT EXISTS falta_desde timestamptz;
ALTER TABLE speech_horario ADD COLUMN IF NOT EXISTS cancelado_desde timestamptz;

-- alta: cuándo la encontró la revisión automática (NULL para lo que vino con la carga manual). Son las «Charlas
-- nuevas» del admin: entran con el resumen en inglés hasta la próxima carga manual.
ALTER TABLE speech ADD COLUMN IF NOT EXISTS alta timestamptz;
