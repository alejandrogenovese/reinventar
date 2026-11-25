"""«¿Olvidaste tu contraseña?» con un código de 6 dígitos por mail (MAIL_PROVIDER=fake: no sale nada)."""
import time

from app import db, limites, mail, mail_api, mail_db, passkeys_db
from tests.apoyo_mail import CLAVE, c, codigo_enviado, mail_unico, usuario_nuevo, verificar
from tests.conftest import login_headers

__all__ = ["c"]  # fixture compartida (tests/apoyo_mail.py)

NUEVA = "nueva-clave-123"


def _con_mail_verificado(c):
    username, email = usuario_nuevo(), mail_unico()
    verificar(c, login_headers(c, username, CLAVE), email)
    mail.enviados.clear()
    return username, email.lower()


def _pedir(c, cuenta, **headers):
    return c.post("/api/password/olvide", json={"usuario": cuenta}, headers=headers)


def _restablecer(c, cuenta, codigo, nueva=NUEVA):
    return c.post("/api/password/restablecer", json={"usuario": cuenta, "codigo": codigo, "new_password": nueva})


def _otro_codigo(codigo: str) -> str:
    return f"{(int(codigo) + 1) % 10 ** 6:06d}"


def _mover(username, columna, segundos):
    with db.conn() as conn:
        conn.execute(f"UPDATE mail_codigos SET {columna} = {columna} - %s WHERE username=%s AND tipo='recuperar'",
                     (segundos, username))


# ---------- pedir el código ----------

def test_olvide_responde_igual_exista_o_no_la_cuenta(c):
    username, _ = _con_mail_verificado(c)

    existe, no_existe = _pedir(c, username), _pedir(c, "nadie_por_aca")

    assert existe.status_code == no_existe.status_code == 200
    assert existe.json() == no_existe.json()
    assert len(mail.enviados) == 1


def test_olvide_no_manda_nada_si_el_mail_no_esta_verificado(c):
    _pedir(c, usuario_nuevo())

    assert not mail.enviados


def test_el_mail_lleva_un_codigo_de_6_digitos_y_va_al_mail_verificado(c):
    username, email = _con_mail_verificado(c)

    _pedir(c, email.upper())

    assert mail.enviados[-1]["para"] == email
    assert len(codigo_enviado()) == 6
    assert "(buscado por mail)" in mail.enviados[-1]["texto"]


def test_el_codigo_se_guarda_hasheado(c):
    username, _ = _con_mail_verificado(c)
    _pedir(c, username)

    with db.conn() as conn:
        guardado = conn.execute("SELECT hash, vence - creado AS vigencia FROM mail_codigos WHERE username=%s "
                                "AND tipo='recuperar'", (username,)).fetchone()

    assert guardado["hash"] == mail_db.hash_codigo(username, codigo_enviado())
    assert guardado["vigencia"] == mail_api.RECUPERAR_MINUTOS * 60


def test_un_codigo_recien_mandado_no_se_pisa_con_otro_pedido(c):
    username, _ = _con_mail_verificado(c)
    _pedir(c, username)
    primero = codigo_enviado()

    _pedir(c, username)

    assert len(mail.enviados) == 1
    assert _restablecer(c, username, primero).status_code == 200


def test_pedir_otro_codigo_pasados_2_minutos_invalida_el_anterior(c, monkeypatch):
    username, _ = _con_mail_verificado(c)
    codigos = iter(["111111", "222222"])
    monkeypatch.setattr(mail_api, "_nuevo_codigo", lambda: next(codigos))
    _pedir(c, username)
    _mover(username, "creado", mail_api.RECUPERAR_ESPERA_SEGUNDOS + 1)
    _pedir(c, username)

    assert _restablecer(c, username, "111111").status_code == 400
    assert _restablecer(c, username, "222222").status_code == 200


def test_olvide_tiene_tope_por_cuenta_exista_o_no(c):
    estados = [_pedir(c, "cuenta_x").status_code for _ in range(limites.OLVIDE_POR_CUENTA + 1)]

    assert estados == [200] * limites.OLVIDE_POR_CUENTA + [429]


# ---------- restablecer con el código ----------

def test_el_codigo_correcto_cambia_la_contrasena_y_cierra_todo(c):
    username, _ = _con_mail_verificado(c)
    H = login_headers(c, username, CLAVE)
    passkeys_db.add_passkey(f"pk-{username}", username, b"clave", 0, "celu")
    _pedir(c, username)

    r = _restablecer(c, username, codigo_enviado())

    assert r.status_code == 200, r.text
    assert c.get("/api/me", headers=H).status_code == 401
    assert passkeys_db.list_passkeys(username) == []
    assert c.post("/api/login", json={"username": username, "password": NUEVA}).status_code == 200


def test_el_codigo_sirve_una_sola_vez(c):
    username, _ = _con_mail_verificado(c)
    _pedir(c, username)
    codigo = codigo_enviado()

    _restablecer(c, username, codigo)

    assert _restablecer(c, username, codigo, "otra-clave-456").status_code == 400


def test_codigo_incorrecto_vencido_sin_intentos_o_cuenta_inexistente_dan_el_mismo_error(c):
    incorrecto, _ = _con_mail_verificado(c)
    _pedir(c, incorrecto)
    malo = _otro_codigo(codigo_enviado())
    vencido, _ = _con_mail_verificado(c)
    _pedir(c, vencido)
    codigo_vencido = codigo_enviado()
    _mover(vencido, "vence", mail_api.RECUPERAR_MINUTOS * 60 + 1)

    respuestas = [_restablecer(c, incorrecto, malo), _restablecer(c, vencido, codigo_vencido),
                  _restablecer(c, "nadie_por_aca", "123456"), _restablecer(c, "nadie@ejemplo.com", "123456")]

    assert {(r.status_code, r.json()["detail"]) for r in respuestas} == {(400, mail_api.ERROR_RESTABLECER)}


def test_el_codigo_tiene_intentos_limitados(c):
    username, _ = _con_mail_verificado(c)
    _pedir(c, username)
    bueno = codigo_enviado()

    fallos = [_restablecer(c, username, _otro_codigo(bueno)).status_code for _ in range(mail_api.RECUPERAR_INTENTOS)]

    assert fallos == [400] * mail_api.RECUPERAR_INTENTOS
    assert _restablecer(c, username, bueno).status_code == 400


def test_el_codigo_no_sirve_si_despues_cambio_el_mail(c):
    username, _ = _con_mail_verificado(c)
    _pedir(c, username)
    codigo = codigo_enviado()
    mail_db.fijar_email(username, mail_unico().lower())

    assert _restablecer(c, username, codigo).status_code == 400


def test_restablecer_aplica_el_largo_minimo_de_contrasena(c):
    username, _ = _con_mail_verificado(c)
    _pedir(c, username)

    assert _restablecer(c, username, codigo_enviado(), "corta").status_code == 422


def test_al_restablecer_avisa_al_mail_de_la_cuenta_con_el_apartado_de_seguridad(c):
    username, email = _con_mail_verificado(c)
    _pedir(c, username)

    c.post("/api/password/restablecer", json={"usuario": username, "codigo": codigo_enviado(), "new_password": NUEVA},
           headers={"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) Version/18.0 Safari/604.1"})

    aviso = mail.enviados[-1]
    assert (aviso["para"], aviso["asunto"]) == (email, "Tu contraseña de ReinventAR cambió")
    assert "Safari en iPhone" in aviso["texto"]
    assert "Seguridad" in aviso["html"]


def test_el_apartado_de_seguridad_usa_la_ip_y_el_navegador_del_pedido(c):
    username, _ = _con_mail_verificado(c)

    _pedir(c, username, **{"X-Real-IP": "181.45.12.34", "User-Agent": "Mozilla/5.0 (Macintosh) Chrome/131.0 Safari/537.36"})

    texto = mail.enviados[-1]["texto"]
    assert "IP: 181.45.xxx.xxx" in texto
    assert "Desde: Chrome en Mac" in texto
    assert f"Pedido por el usuario: {username}\n" in texto
    assert "181.45.12.34" not in texto


def test_restablecer_tiene_tope_por_ip(c):
    estados = [_restablecer(c, "nadie", "123456").status_code for _ in range(limites.RESTABLECER_POR_IP + 1)]

    assert estados[-1] == 429


def test_el_codigo_vencido_se_borra_de_la_base(c):
    username, _ = _con_mail_verificado(c)
    _pedir(c, username)
    codigo = codigo_enviado()
    _mover(username, "vence", int(time.time()))

    _restablecer(c, username, codigo)

    with db.conn() as conn:
        assert conn.execute("SELECT 1 FROM mail_codigos WHERE username=%s AND tipo='recuperar'",
                            (username,)).fetchone() is None


def test_gastar_los_intentos_a_proposito_no_habilita_otro_codigo_en_seguida(c):
    username, _ = _con_mail_verificado(c)
    _pedir(c, username)
    bueno = codigo_enviado()
    for _ in range(mail_api.RECUPERAR_INTENTOS):
        _restablecer(c, username, _otro_codigo(bueno))

    _pedir(c, f" {username.upper()} ")

    assert len(mail.enviados) == 1


def test_pedir_la_cuenta_por_usuario_y_por_mail_no_duplica_el_tope(c):
    username, email = _con_mail_verificado(c)

    for i in range(limites.CODIGOS_RECUPERACION_POR_USUARIO + 1):
        _pedir(c, username if i % 2 else email)
        _mover(username, "creado", mail_api.RECUPERAR_ESPERA_SEGUNDOS + 1)

    assert len(mail.enviados) == limites.CODIGOS_RECUPERACION_POR_USUARIO


def test_las_claves_viejas_del_tope_se_purgan():
    tope = limites.Limite(3, ventana=10)
    tope.sumar("cuenta-tipeada", ahora=1.0)

    tope.purgar(ahora=100.0)

    assert "cuenta-tipeada" not in tope._eventos
