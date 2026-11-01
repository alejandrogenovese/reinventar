"""Nivel "sector" arriba de la industria de cada empresa (Finanzas → Pagos y fintech → Revolut).

Vive en el schema de la app (no en reinvent) para que el sync del catálogo no lo pise y se pueda editar.
Al arrancar se cargan estos valores iniciales solo para industrias que todavía no tienen sector.
"""

FINANZAS = "Finanzas"
TECNOLOGIA = "Tecnología"
MEDIOS = "Medios, entretenimiento y telecomunicaciones"
CONSUMO = "Consumo, retail y viajes"
INDUSTRIA = "Industria, energía y movilidad"
SALUD = "Salud"
PUBLICO = "Sector público y educación"
SIN_CLASIFICAR = "Sin clasificar"

SECTOR_BY_INDUSTRY = {
    "Banca": FINANZAS,
    "Mercados de capitales e inversión": FINANZAS,
    "Pagos y fintech": FINANZAS,
    "Seguros": FINANZAS,
    "Cloud e infraestructura": TECNOLOGIA,
    "Software empresarial y SaaS": TECNOLOGIA,
    "Inteligencia artificial": TECNOLOGIA,
    "Datos y bases de datos": TECNOLOGIA,
    "Ciberseguridad": TECNOLOGIA,
    "DevOps y observabilidad": TECNOLOGIA,
    "Semiconductores y hardware": TECNOLOGIA,
    "Consultoría e integración IT": TECNOLOGIA,
    "Información y analítica de negocio": TECNOLOGIA,
    "Telecomunicaciones": MEDIOS,
    "Medios, entretenimiento y redes sociales": MEDIOS,
    "Videojuegos": MEDIOS,
    "Marketing y publicidad": MEDIOS,
    "Deportes, apuestas y casinos": MEDIOS,
    "Retail y e-commerce": CONSUMO,
    "Consumo masivo y alimentos": CONSUMO,
    "Moda y belleza": CONSUMO,
    "Aerolíneas, viajes y hotelería": CONSUMO,
    "Manufactura e industria": INDUSTRIA,
    "Energía, minería y utilities": INDUSTRIA,
    "Automotriz y movilidad": INDUSTRIA,
    "Aeroespacial y defensa": INDUSTRIA,
    "Logística y transporte": INDUSTRIA,
    "Inmobiliaria y construcción": INDUSTRIA,
    "Salud, farma y biotech": SALUD,
    "Gobierno y sector público": PUBLICO,
    "Educación e investigación": PUBLICO,
    "Sin clasificar": SIN_CLASIFICAR,
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS sector_industria (
  industria TEXT PRIMARY KEY,
  sector TEXT NOT NULL
);
"""


def ensure(c) -> None:
    """Crea la tabla y completa las industrias que falten (no pisa ediciones hechas a mano)."""
    c.execute(SCHEMA)
    c.cursor().executemany(
        "INSERT INTO sector_industria (industria, sector) VALUES (%s, %s) ON CONFLICT (industria) DO NOTHING",
        list(SECTOR_BY_INDUSTRY.items()),
    )
