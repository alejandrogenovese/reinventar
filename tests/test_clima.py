"""Clima de Las Vegas para Hoy (app/clima.py, app/clima_api.py). Sin red: el proveedor fake o un httpx.MockTransport que
hace de NWS. Sin catálogo (corre en CI)."""
from datetime import datetime, timedelta

import httpx
import pytest
from fastapi.testclient import TestClient

from app import clima, config
from app.main import app
from tests.conftest import login_headers

ZONA = clima.ZONA
AHORA = datetime(2026, 12, 1, 9, 30, tzinfo=ZONA)   # martes de re:Invent, de mañana
URL_PRONOSTICO = "https://api.weather.gov/gridpoints/VEF/121,96/forecast"
URL_HORAS = "https://api.weather.gov/gridpoints/VEF/121,96/forecast/hourly"


def periodo(inicio, horas, temp, dia=True, corto="Sunny", viento="5 mph", lluvia=0):
    return clima._periodo(inicio, horas, temp, dia, corto, viento, lluvia)


def a_las(dia, hora):
    return datetime(2026, 12, dia, hora, tzinfo=ZONA)


@pytest.fixture(autouse=True)
def _cache_limpia():
    clima.reiniciar()
    yield
    clima.reiniciar()


# ---------- conversiones y traducciones ----------

@pytest.mark.parametrize("f,c", [(32, 0), (50, 10), (61, 16), (44, 7), (-40, -40)])
def test_convierte_fahrenheit_a_celsius(f, c):
    assert clima.a_celsius(f, "F") == c


def test_celsius_queda_igual_y_none_es_none():
    assert clima.a_celsius(12.4, "C") == 12
    assert clima.a_celsius(None) is None


@pytest.mark.parametrize("texto,kmh", [("10 mph", 16), ("5 to 20 mph", 32), ("15 km/h", 15), ("", None), (None, None)])
def test_viento_en_kmh_toma_el_mayor(texto, kmh):
    assert clima.viento_kmh(texto) == kmh


@pytest.mark.parametrize("corto,esperado", [
    ("Sunny", "Soleado"), ("mostly cloudy", "Mayormente nublado"),
    ("Chance Rain Showers then Mostly Sunny", "Posibles chaparrones y después mayormente soleado"),
    ("Isolated Volcanic Ash", "Isolated Volcanic Ash"),          # no está en la tabla: el original
    ("Sunny then Volcanic Ash", "Sunny then Volcanic Ash"),      # una parte sin traducir: el original entero
    ("", ""), (None, ""),
])
def test_traduce_los_shortforecast_comunes(corto, esperado):
    assert clima.traducir(corto) == esperado


# ---------- resumen ----------

def pronostico_semana(minima=44, corto_hoy="Sunny", lluvia_hoy=0):
    periodos = []
    for d in range(1, 5):
        periodos += [periodo(a_las(d, 6), 12, 60 + d, True, corto_hoy if d == 1 else "Partly Cloudy", lluvia=lluvia_hoy if d == 1 else 0),
                     periodo(a_las(d, 18), 12, minima, False, "Mostly Clear")]
    return periodos


def horas_desde(inicio, n=24, temp=58, viento="5 mph"):
    return [periodo(inicio + timedelta(hours=i), 1, temp + i % 3, viento=viento) for i in range(n)]


def test_resume_ahora_hoy_y_los_dos_dias_siguientes():
    r = clima.resumir(pronostico_semana(), horas_desde(a_las(1, 9)), AHORA)

    assert r["ahora"] == {"temp_c": 14, "descripcion": "Soleado", "viento_kmh": 8, "desde": "09:00"}
    assert [d["fecha"] for d in r["dias"]] == ["2026-12-01", "2026-12-02", "2026-12-03"]
    assert r["dias"][0] == {"fecha": "2026-12-01", "max_c": 16, "min_c": 7, "descripcion": "Soleado", "lluvia_pct": 0}
    assert r["dias"][1]["descripcion"] == "Parcialmente nublado"
    assert r["actualizado"].startswith("2026-12-01T09:30") and r["zona"] == "America/Los_Angeles"


def test_saltea_los_periodos_que_ya_terminaron():
    # NWS puede servir un pronóstico de la mañana que todavía trae «Today»: a las 20 ya no hay máxima de hoy.
    noche = a_las(1, 20)
    r = clima.resumir(pronostico_semana(), horas_desde(a_las(1, 8), n=30), noche)

    assert r["dias"][0]["max_c"] is None and r["dias"][0]["min_c"] == 7
    assert r["ahora"]["desde"] == "20:00"


def test_sin_nada_vigente_no_hay_resumen():
    assert clima.resumir(pronostico_semana(), horas_desde(a_las(1, 0), n=2), a_las(9, 12)) is None


def test_consejo_de_abrigo_con_minima_menor_a_10():
    assert clima.resumir(pronostico_semana(minima=44), [], AHORA)["consejos"] == [clima.CONSEJO_FRESCO]
    assert clima.resumir(pronostico_semana(minima=55), [], AHORA)["consejos"] == []


def test_consejos_de_viento_fuerte_y_lluvia():
    r = clima.resumir(pronostico_semana(minima=55, lluvia_hoy=60), horas_desde(a_las(1, 9), viento="15 to 25 mph"), AHORA)
    assert r["consejos"] == [clima.CONSEJO_VIENTO, clima.CONSEJO_LLUVIA]


# ---------- NWS con caché (MockTransport: no sale a la red) ----------

class NwsFalso:
    def __init__(self, edad=3600, falla=False):
        self.pedidos, self.edad, self.falla, self.user_agents = [], edad, falla, set()

    def __call__(self, request: httpx.Request):
        self.pedidos.append(str(request.url))
        self.user_agents.add(request.headers.get("user-agent"))
        if self.falla:
            return httpx.Response(503, json={"title": "caído"})
        cache = {"cache-control": f"public, max-age={self.edad}, s-maxage={self.edad}"}
        if request.url.path.startswith("/points/"):
            return httpx.Response(200, headers={"cache-control": "public, max-age=86400"},
                                  json={"properties": {"forecast": URL_PRONOSTICO, "forecastHourly": URL_HORAS}})
        if request.url.path.endswith("/hourly"):
            return httpx.Response(200, headers=cache, json={"properties": {"periods": horas_desde(a_las(1, 9))}})
        return httpx.Response(200, headers=cache, json={"properties": {"periods": pronostico_semana()}})

    def cliente(self):
        return httpx.Client(transport=httpx.MockTransport(self))


@pytest.fixture
def nws(monkeypatch):
    monkeypatch.setattr(config, "CLIMA_PROVIDER", "nws")
    return NwsFalso()


def test_pide_points_forecast_y_hourly_con_user_agent_generico(nws):
    r = clima.obtener(AHORA, nws.cliente())

    assert r["dias"][0]["max_c"] == 16
    assert nws.pedidos == [clima.URL_PUNTO, URL_PRONOSTICO, URL_HORAS]
    assert nws.user_agents == {clima.USER_AGENT}
    assert "@" not in clima.USER_AGENT


def test_no_vuelve_a_pedir_mientras_vale_el_cache_control(nws):
    clima.obtener(AHORA, nws.cliente())
    clima.obtener(AHORA + timedelta(minutes=59), nws.cliente())
    assert len(nws.pedidos) == 3

    clima.obtener(AHORA + timedelta(minutes=61), nws.cliente())   # venció: forecast y hourly; el punto dura un día
    assert nws.pedidos[3:] == [URL_PRONOSTICO, URL_HORAS]


def test_respeta_el_minimo_de_media_hora_aunque_nws_diga_menos(nws):
    nws.edad = 42
    clima.obtener(AHORA, nws.cliente())
    clima.obtener(AHORA + timedelta(minutes=20), nws.cliente())
    assert len(nws.pedidos) == 3
    clima.obtener(AHORA + timedelta(minutes=31), nws.cliente())
    assert len(nws.pedidos) == 5


def test_si_nws_falla_sin_copia_devuelve_none_y_no_insiste_en_rafaga(nws):
    nws.falla = True
    assert clima.obtener(AHORA, nws.cliente()) is None
    assert clima.obtener(AHORA + timedelta(minutes=1), nws.cliente()) is None
    assert len(nws.pedidos) == 1
    clima.obtener(AHORA + clima.PAUSA_FALLO + timedelta(seconds=1), nws.cliente())
    assert len(nws.pedidos) == 2


def test_si_nws_falla_sigue_con_el_ultimo_mientras_sea_reciente(nws):
    clima.obtener(AHORA, nws.cliente())
    nws.falla = True

    r = clima.obtener(AHORA + timedelta(hours=2), nws.cliente())
    assert r["dias"][0]["max_c"] == 16
    assert r["actualizado"].startswith("2026-12-01T09:30")   # la hora del dato, no la del pedido
    assert clima.obtener(AHORA + clima.VIGENCIA_MAX + timedelta(minutes=10), nws.cliente()) is None


def test_respuesta_inservible_cuenta_como_falla(monkeypatch):
    monkeypatch.setattr(config, "CLIMA_PROVIDER", "nws")
    cliente = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"otra": "cosa"})))
    assert clima.obtener(AHORA, cliente) is None


def test_no_sigue_urls_de_pronostico_fuera_de_nws(monkeypatch):
    monkeypatch.setattr(config, "CLIMA_PROVIDER", "nws")
    pedidos = []

    def falso(request):
        pedidos.append(str(request.url))
        return httpx.Response(200, json={"properties": {"forecast": "https://otro.example/x", "forecastHourly": URL_HORAS}})

    assert clima.obtener(AHORA, httpx.Client(transport=httpx.MockTransport(falso))) is None
    assert pedidos == [clima.URL_PUNTO]


def test_max_age_lee_cache_control_o_expires():
    assert clima.max_age(httpx.Response(200, headers={"cache-control": "public, max-age=3600"})) == timedelta(hours=1)
    assert clima.max_age(httpx.Response(200, headers={"cache-control": "public, s-maxage=3600"})) is None
    assert clima.max_age(httpx.Response(200, headers={"expires": "Thu, 01 Jan 1970 00:00:00 GMT"})) == timedelta(0)


def test_apagado_no_devuelve_nada(monkeypatch):
    monkeypatch.setattr(config, "CLIMA_PROVIDER", "off")
    assert clima.obtener(AHORA) is None


# ---------- endpoint ----------

def test_endpoint_pide_sesion_y_en_fake_devuelve_el_resumen():
    with TestClient(app) as c:
        assert c.get("/api/clima").status_code == 401
        r = c.get("/api/clima", headers=login_headers(c))

    assert r.status_code == 200, r.text
    datos = r.json()
    assert datos["ahora"]["temp_c"] == 14
    assert len(datos["dias"]) == 3 and datos["dias"][1]["max_c"] == 17
    assert clima.CONSEJO_FRESCO in datos["consejos"]
