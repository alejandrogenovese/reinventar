"""Fechas del viaje a Las Vegas (fuente única): re:Invent va del 30/11 al 4/12, pero la estadía arranca el domingo 29/11
y termina el lunes 7/12 a las 13:00. Shows, el contexto del LLM para eventos y la carga a mano del admin usan este
rango; las charlas no (terminan con la conferencia).

Si cambia el viaje se toca acá y en web/js/adminEventos.js (FECHA_MAX; tests/test_estadia.py verifica que coincidan).
"""
import datetime as dt
from zoneinfo import ZoneInfo

TZ_VEGAS = ZoneInfo("America/Los_Angeles")

INICIO_DE_LA_ESTADIA = dt.datetime(2026, 11, 29, tzinfo=TZ_VEGAS)    # domingo 29/11 00:00 en Las Vegas
FIN_DE_LA_ESTADIA = dt.datetime(2026, 12, 7, 13, tzinfo=TZ_VEGAS)    # lunes 7/12 13:00 en Las Vegas
