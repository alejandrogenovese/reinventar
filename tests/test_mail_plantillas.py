"""Los mails de la cuenta (app/mail_plantillas.py): apartado «Seguridad», navegador, IP enmascarada y escape del HTML."""
import datetime as dt

import pytest

from app import mail_plantillas as mp
from app.sandbox import EVENT_TZ

IPHONE = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.1 Mobile/15E148 Safari/604.1"
MAC_CHROME = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
ANDROID_CHROME = "Mozilla/5.0 (Linux; Android 15; Pixel 9) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Mobile Safari/537.36"
WINDOWS_EDGE = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0"
IPHONE_CHROME = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) CriOS/131.0 Mobile/15E148 Safari/604.1"
LINUX_FIREFOX = "Mozilla/5.0 (X11; Linux x86_64; rv:133.0) Gecko/20100101 Firefox/133.0"
MOMENTO = dt.datetime(2026, 11, 25, 14, 32, tzinfo=EVENT_TZ).timestamp()


def _origen(**cambios):
    datos = {"username": "mariana", "ip": "181.45.12.34", "user_agent": IPHONE, "momento": MOMENTO}
    return mp.Origen(**{**datos, **cambios})


@pytest.mark.parametrize(("ua", "esperado"), [
    (IPHONE, "Safari en iPhone"), (MAC_CHROME, "Chrome en Mac"), (ANDROID_CHROME, "Chrome en Android"),
    (WINDOWS_EDGE, "Edge en Windows"), (IPHONE_CHROME, "Chrome en iPhone"), (LINUX_FIREFOX, "Firefox en Linux"),
    ("curl/8.7.1", mp.DESCONOCIDO), ("", mp.DESCONOCIDO), (None, mp.DESCONOCIDO),
])
def test_describe_navegador_y_sistema_del_user_agent(ua, esperado):
    assert mp.describir_ua(ua) == esperado


def test_un_user_agent_enorme_no_se_lee_entero_ni_sale_largo():
    assert len(mp.describir_ua("x" * 10_000 + " Chrome/1")) <= mp.DESDE_MAX
    assert mp.describir_ua("x" * 10_000 + " Chrome/1") == mp.DESCONOCIDO


@pytest.mark.parametrize(("ip", "esperado"), [
    ("181.45.12.34", "181.45.xxx.xxx"), ("10.0.0.1", "10.0.xxx.xxx"),
    ("2800:810:4a3:1::7", "2800:810:xxxx:…"), ("2001:0db8::1", "2001:db8:xxxx:…"),
    ("no-es-ip", "desconocida"), ("", "desconocida"), (None, "desconocida"),
])
def test_la_ip_va_enmascarada(ip, esperado):
    assert mp.enmascarar_ip(ip) == esperado


def test_la_hora_va_en_las_vegas_y_rotulada():
    assert mp.cuando(MOMENTO) == "mié 25/11/2026, 14:32 (hora de Las Vegas)"


def test_el_mail_de_confirmacion_lleva_el_diseno_y_el_apartado_de_seguridad():
    m = mp.confirmar_mail(_origen(), "mariana@ejemplo.com", "482913", 15)

    assert m.asunto == "Tu código de ReinventAR: 482913"
    for pedazo in ("#1a1a1a", "#fa6400", "#ffe8d9", "Menlo", "482913", "Confirmá tu mail", "Seguridad",
                   "Pedido por el usuario", "Safari en iPhone", "181.45.xxx.xxx", "hora de Las Vegas",
                   "nunca te va a pedir este código por WhatsApp, teléfono ni mail"):
        assert pedazo in m.html, pedazo
    assert "181.45.12.34" not in m.html + m.texto


def test_el_mail_de_recuperacion_dice_si_se_busco_por_mail():
    m = mp.recuperar_contrasena(_origen(buscado_por_mail=True, user_agent=MAC_CHROME), "706158", 10, 5)

    assert m.asunto == "Código para elegir una contraseña nueva: 706 158"
    assert "Pedido por el usuario: mariana (buscado por mail)" in m.texto
    assert "<strong>mariana</strong> (buscado por mail)" in m.html
    assert "Vence en 10 minutos · 5 intentos · una sola vez" in m.html


def test_el_aviso_de_contrasena_cambiada_tambien_lleva_seguridad():
    m = mp.contrasena_cambiada(_origen())

    assert "Seguridad" in m.html
    assert "IP: 181.45.xxx.xxx" in m.texto
    assert "¿No fuiste vos?" in m.texto


def test_todo_lo_que_viene_del_usuario_va_escapado_en_el_html():
    malo = '<script>alert("x")</script>'
    origen = _origen(username=malo, user_agent=f"{malo} Chrome/1 (Macintosh)")

    for m in (mp.confirmar_mail(origen, f"{malo}@ejemplo.com", "123456", 15),
              mp.recuperar_contrasena(origen, "123456", 10, 5), mp.contrasena_cambiada(origen)):
        assert "<script>" not in m.html
        assert "&lt;script&gt;" in m.html


def test_la_version_de_texto_no_lleva_html():
    m = mp.recuperar_contrasena(_origen(), "706158", 10, 5)

    assert "<" not in m.texto
    assert "\n    706158\n" in m.texto
