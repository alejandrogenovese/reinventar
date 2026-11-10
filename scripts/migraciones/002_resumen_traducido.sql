-- Resumen de la charla traducido al castellano, al lado del original en inglés (la app deja elegir cuál ver).
-- Lo completa scripts/traducir_resumenes.py; actualizar_catalogo.py lo vacía si AWS cambia el resumen original.
ALTER TABLE speech ADD COLUMN IF NOT EXISTS resumen_es text;
