"""El Excel de ejemplo de «Cruzar con mi Excel»: la persona lo baja, lo completa y lo sube.

Respeta lo que lee app/codigos_excel.py: el lector toma la columna (de cualquier hoja) con más celdas con código, así
que la columna Código es la única que trae códigos. Los títulos, las notas y la hoja de instrucciones no escriben
ninguno (ni de ejemplo): si los tuvieran, al reemplazar los códigos de ejemplo por los propios aparecerían como
«códigos que quedaron afuera»."""
import io

from .codigos_excel import MAX_BYTES, MAX_CODIGOS

NOMBRE = "reinventar-codigos-ejemplo.xlsx"
MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
HOJA_CODIGOS = "Mis charlas"
HOJA_INSTRUCCIONES = "Instrucciones"
CABECERA = ("Código", "Título (opcional)", "Notas (opcional)")
FILAS = (
    ("KEY001", "Keynote de apertura", "Llegar temprano"),
    ("AIM301", "Agentes con Bedrock", ""),
    ("DAT402-R", "Aurora DSQL a fondo", "La repetición, que me queda mejor de horario"),
    ("SEC201", "Seguridad para agentes", ""),
)
INSTRUCCIONES = (
    "Cómo completar este Excel",
    "",
    "1. En la hoja «Mis charlas», escribí una charla por fila en la columna Código.",
    "2. El código es el del catálogo de re:Invent: tres letras y tres números. Para una repetición, sumale el sufijo (-R, -R1).",
    "3. Borrá las filas de ejemplo y poné las tuyas. Título y Notas son opcionales: la app no los lee.",
    "4. Guardalo como .xlsx (o .csv) y subilo en Itinerario › Cruzar con mi Excel.",
    "",
    f"Hasta {MAX_BYTES // 1024 // 1024} MB y {MAX_CODIGOS} códigos distintos. Si un código se repite, cuenta una sola vez.",
)
_ANCHOS = (14, 36, 44)
_ANCHO_INSTRUCCIONES = 110


def _hoja_codigos(hoja) -> None:
    from openpyxl.styles import Font

    hoja.title = HOJA_CODIGOS
    hoja.append(CABECERA)
    for celda in hoja[1]:
        celda.font = Font(bold=True)
    for fila in FILAS:
        hoja.append([valor or None for valor in fila])
    for letra, ancho in zip("ABC", _ANCHOS, strict=True):
        hoja.column_dimensions[letra].width = ancho
    hoja.freeze_panes = "A2"


def _hoja_instrucciones(hoja) -> None:
    from openpyxl.styles import Font

    for linea in INSTRUCCIONES:
        hoja.append([linea or None])
    hoja["A1"].font = Font(bold=True)
    hoja.column_dimensions["A"].width = _ANCHO_INSTRUCCIONES


def generar() -> bytes:
    """Los bytes del .xlsx: la hoja de códigos primero (la que se abre) y las instrucciones aparte."""
    import openpyxl  # diferido, como en codigos_excel: solo hace falta al pedir el ejemplo

    libro = openpyxl.Workbook()
    _hoja_codigos(libro.active)
    _hoja_instrucciones(libro.create_sheet(HOJA_INSTRUCCIONES))
    salida = io.BytesIO()
    libro.save(salida)
    return salida.getvalue()
