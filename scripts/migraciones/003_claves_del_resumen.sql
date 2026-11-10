-- Claves extraídas del resumen con un LLM (scripts/extraer_claves.py), para buscar y filtrar mejor que con las
-- etiquetas oficiales de AWS. NULL = todavía no se extrajo; '{}' = se extrajo y no había nada.
-- actualizar_catalogo.py las vacía si AWS cambia el resumen.
ALTER TABLE speech ADD COLUMN IF NOT EXISTS servicios_mencionados text[];  -- servicios de AWS, nombre oficial
ALTER TABLE speech ADD COLUMN IF NOT EXISTS tecnologias text[];            -- productos y estándares que no son de AWS
ALTER TABLE speech ADD COLUMN IF NOT EXISTS conceptos text[];              -- en castellano (lo que muestra la app)
ALTER TABLE speech ADD COLUMN IF NOT EXISTS conceptos_en text[];           -- los mismos en inglés (para la búsqueda)
ALTER TABLE speech ADD COLUMN IF NOT EXISTS enfoque text[];                -- valores fijos: ver ENFOQUES en extraer_claves.py
