"""El Excel de ejemplo de «Cargar eventos desde Excel» (Eventos › Mis eventos): la persona lo baja, lo completa y lo sube.

Mismo patrón que app/codigos_ejemplo.py. Respeta lo que lee app/eventos_excel.py: una hoja «Eventos» con la cabecera
(las obligatorias con «*»), filas de ejemplo ficticias dentro de la estadía (hora de Las Vegas) y validaciones de
datos; otra hoja «Instrucciones» con una fila por columna, que el lector ignora porque no tiene la cabecera.
"""
import datetime as dt
import io

from . import estadia
from .eventos_excel import MAX_BYTES, MAX_EVENTOS, MAX_NOMBRE, MAX_NOTA, TIPOS

NOMBRE = "reinventar-eventos-ejemplo.xlsx"
MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
HOJA_EVENTOS = "Eventos"
HOJA_INSTRUCCIONES = "Instrucciones"
PRIMER_DIA = estadia.INICIO_DE_LA_ESTADIA.date()
ULTIMO_DIA = estadia.FIN_DE_LA_ESTADIA.date()
FILAS_CON_VALIDACION = 200  # hasta dónde llegan las validaciones y los formatos de fecha y hora
FORMATO_DIA = "dd/mm/yyyy"
FORMATO_HORA = "hh:mm"
_RANGO = f"entre el {PRIMER_DIA:%d/%m/%Y} y el {ULTIMO_DIA:%d/%m/%Y}"
SEDES = "Venetian, Caesars Forum, Caesars Palace, MGM Grand, Wynn/Encore (o Wynn, o Encore) y Allegiant Stadium"

# (cabecera, ancho, obligatoria, explicación)
COLUMNAS = (
    ("Nombre", 38, True, f"Cómo se llama el evento. Hasta {MAX_NOMBRE} caracteres."),
    ("Día", 13, True, f"Fecha del evento, {_RANGO}. Celda de fecha de Excel o texto dd/mm/aaaa (también vale "
                      "2026-12-01)."),
    ("Inicio", 9, True, "Hora de inicio en hora de Las Vegas, 24 h: 19:30. También vale 7:30 PM."),
    ("Fin", 9, False, "Hora de fin, en hora de Las Vegas. Si es menor que el inicio (una fiesta de 22:00 a 01:00), "
                      "termina al día siguiente: en la app ocupa hasta las 23:59 y la nota aclara a qué hora termina."),
    ("Tipo", 16, False, "Elegí de la lista: " + ", ".join(TIPOS) + ". Se anota en la nota."),
    ("Lugar", 30, True, f"Dónde es. Si escribís el nombre de una sede de re:Invent ({SEDES}) la app la reconoce y lo "
                        "ubica en el mapa; si no, queda el texto como lo escribiste."),
    ("Dirección", 34, False, "Calle y número, si no es una sede. Se anota en la nota."),
    ("Link", 36, False, "Página del evento o de la invitación. Tiene que empezar con https://. Se anota en la nota."),
    ("Precio", 14, False, "Texto libre: Gratis, USD 40, Con invitación. Se anota en la nota."),
    ("Notas", 44, False, f"Lo que quieras recordar: quién te invitó, dress code, si hay que confirmar. La nota entera "
                         f"(con Tipo, Precio, Dirección y Link) llega hasta {MAX_NOTA} caracteres. Solo la ves vos."),
)

# Eventos ficticios: ningún nombre de persona ni empresa real; los links usan example.com.
FILAS = (
    ("Cena de bienvenida del equipo", dt.date(2026, 11, 29), dt.time(20, 0), dt.time(22, 30), "cena",
     "Venetian", "", "", "Paga la empresa", "Reserva a nombre del equipo; avisar si alguien llega tarde"),
    ("Meetup de la comunidad serverless", dt.date(2026, 12, 1), dt.time(18, 30), dt.time(21, 0), "meetup técnico",
     "Caesars Forum", "", "https://example.com/meetup-serverless", "Gratis", "Hay que anotarse antes del 28/11"),
    ("Desayuno con clientes de la región", dt.date(2026, 12, 2), dt.time(7, 30), dt.time(9, 0), "desayuno",
     "Wynn/Encore", "3131 Las Vegas Blvd S, Las Vegas, NV 89109", "", "", "Llevar tarjetas"),
    ("Fiesta privada de un partner", dt.date(2026, 12, 3), dt.time(22, 0), dt.time(1, 0), "fiesta",
     "Rooftop sobre el Strip", "Dirección en la invitación", "https://example.com/invitacion-partner",
     "Con invitación", "Mostrar el QR en la puerta"),
    ("Happy hour del equipo de datos", dt.date(2026, 12, 4), dt.time(17, 0), dt.time(19, 0), "happy hour",
     "MGM Grand", "", "", "USD 25", ""),
    ("Salida grupal a un show", dt.date(2026, 12, 5), dt.time(19, 0), None, "actividad",
     "Sphere", "255 Sands Ave, Las Vegas, NV 89169", "https://example.com/entradas-show", "USD 120",
     "Entradas compradas por el grupo"),
)
INSTRUCCIONES = (
    "Un evento por fila en la hoja «Eventos». Borrá los de ejemplo y poné los tuyos.",
    "Las columnas con * son obligatorias. Las horas son de Las Vegas, aunque cargues el Excel desde otro lado.",
    "Guardalo como .xlsx (o .csv) y subilo en Eventos › Mis eventos › Cargar desde Excel. Antes de guardar te "
    "mostramos una vista previa con lo que es nuevo, lo que cambia y los errores de cada fila; las filas con error "
    "no se guardan.",
    "Si subís el mismo archivo otra vez no se duplica: un evento con el mismo nombre, día e inicio se actualiza. "
    "Si cambiás el nombre, el día o el inicio, es otro evento. Si sacás una fila, el evento no se borra: borralo "
    "desde Mis eventos.",
    f"Hasta {MAX_BYTES // 1024 // 1024} MB y {MAX_EVENTOS} eventos. Los eventos son privados: solo los ves vos.",
)


def _cabecera(hoja) -> None:
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    hoja.append([nombre + (" *" if obligatoria else "") for nombre, _, obligatoria, _ in COLUMNAS])
    relleno = PatternFill("solid", fgColor="DDE7F3")
    for celda in hoja[1]:
        celda.font = Font(bold=True)
        celda.fill = relleno
        celda.alignment = Alignment(vertical="center")
    for i, (_, ancho, _, _) in enumerate(COLUMNAS, start=1):
        hoja.column_dimensions[get_column_letter(i)].width = ancho
    hoja.freeze_panes = "A2"


def _filas(hoja) -> None:
    for fila in FILAS:
        hoja.append([valor if valor not in ("", None) else None for valor in fila])
    for fila in hoja.iter_rows(min_row=2, max_row=FILAS_CON_VALIDACION):
        fila[1].number_format = FORMATO_DIA
        fila[2].number_format = FORMATO_HORA
        fila[3].number_format = FORMATO_HORA


def _validaciones(hoja) -> None:
    from openpyxl.worksheet.datavalidation import DataValidation

    ultimo = FILAS_CON_VALIDACION
    tipo = DataValidation(type="list", formula1='"' + ",".join(TIPOS) + '"', allow_blank=True,
                          errorTitle="Tipo", error="Elegí un tipo de la lista.", showErrorMessage=True)
    dia = DataValidation(type="date", operator="between", allow_blank=True,
                         formula1=f"DATE({PRIMER_DIA.year},{PRIMER_DIA.month},{PRIMER_DIA.day})",
                         formula2=f"DATE({ULTIMO_DIA.year},{ULTIMO_DIA.month},{ULTIMO_DIA.day})",
                         errorTitle="Día", error=f"Una fecha {_RANGO} (dd/mm/aaaa).",
                         promptTitle="Día", prompt=f"dd/mm/aaaa, {_RANGO}", showErrorMessage=True,
                         showInputMessage=True)
    hora = DataValidation(type="time", operator="between", allow_blank=True, formula1="0", formula2="0.999988426",
                          errorTitle="Hora", error="Una hora en formato hh:mm (hora de Las Vegas).",
                          promptTitle="Hora", prompt="hh:mm, hora de Las Vegas", showErrorMessage=True,
                          showInputMessage=True)
    nombre = DataValidation(type="textLength", operator="lessThanOrEqual", formula1=str(MAX_NOMBRE), allow_blank=True,
                            error=f"Hasta {MAX_NOMBRE} caracteres.", showErrorMessage=True)
    notas = DataValidation(type="textLength", operator="lessThanOrEqual", formula1=str(MAX_NOTA), allow_blank=True,
                           error=f"Hasta {MAX_NOTA} caracteres.", showErrorMessage=True)
    link = DataValidation(type="custom", formula1='LEFT(H2,8)="https://"', allow_blank=True,
                          error="El link tiene que empezar con https://", showErrorMessage=True)
    for validacion, rango in ((nombre, f"A2:A{ultimo}"), (dia, f"B2:B{ultimo}"), (hora, f"C2:D{ultimo}"),
                              (tipo, f"E2:E{ultimo}"), (link, f"H2:H{ultimo}"), (notas, f"J2:J{ultimo}")):
        validacion.add(rango)
        hoja.add_data_validation(validacion)


def _instrucciones(hoja) -> None:
    from openpyxl.styles import Alignment, Font

    hoja.append(["Cómo completar este Excel"])
    hoja["A1"].font = Font(bold=True, size=13)
    for linea in (*INSTRUCCIONES, ""):
        hoja.append([linea or None])
    hoja.append(["Columna", "Obligatoria", "Qué va"])
    for celda in hoja[hoja.max_row]:
        celda.font = Font(bold=True)
    for nombre, _, obligatoria, explicacion in COLUMNAS:
        hoja.append([nombre, "Sí" if obligatoria else "No", explicacion])
    for fila in hoja.iter_rows(min_row=1):
        for celda in fila:
            celda.alignment = Alignment(wrap_text=True, vertical="top")
    hoja.column_dimensions["A"].width = 14
    hoja.column_dimensions["B"].width = 12
    hoja.column_dimensions["C"].width = 90


def generar() -> bytes:
    """Los bytes del .xlsx: la hoja de eventos primero (la que se abre) y las instrucciones aparte."""
    import openpyxl  # diferido, como en codigos_ejemplo: solo hace falta al pedir el ejemplo

    libro = openpyxl.Workbook()
    eventos = libro.active
    eventos.title = HOJA_EVENTOS
    _cabecera(eventos)
    _filas(eventos)
    _validaciones(eventos)
    _instrucciones(libro.create_sheet(HOJA_INSTRUCCIONES))
    salida = io.BytesIO()
    libro.save(salida)
    return salida.getvalue()
