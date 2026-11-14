"""IP del cliente para los límites por IP: manda X-Real-IP; un X-Forwarded-For falso no la cambia."""
import pytest
from starlette.requests import Request

from app import auth_api

PEER = "100.64.0.9"


def _pedido(**headers: str) -> Request:
    crudos = [(k.replace("_", "-").lower().encode(), v.encode()) for k, v in headers.items()]
    return Request({"type": "http", "headers": crudos, "client": (PEER, 5000)})


def test_usa_la_ip_del_header_del_proxy():
    assert auth_api.ip_cliente(_pedido(x_real_ip="198.51.100.4")) == "198.51.100.4"


@pytest.mark.parametrize("falso", ["1.1.1.1", "1.1.1.1, 2.2.2.2", "9.9.9.9, 8.8.8.8, 7.7.7.7"])
def test_un_x_forwarded_for_falso_no_cambia_la_ip(falso):
    con_real = _pedido(x_real_ip="198.51.100.4", x_forwarded_for=falso)
    sin_real = _pedido(x_forwarded_for=falso)

    assert auth_api.ip_cliente(con_real) == "198.51.100.4"
    assert auth_api.ip_cliente(sin_real) == PEER  # sin X-Real-IP se usa el peer, nunca el X-Forwarded-For


@pytest.mark.parametrize("roto", ["", "no-es-una-ip", "1.1.1.1, 2.2.2.2"])
def test_un_x_real_ip_invalido_cae_al_peer(roto):
    assert auth_api.ip_cliente(_pedido(x_real_ip=roto)) == PEER


def test_el_nombre_del_header_es_configurable(monkeypatch):
    monkeypatch.setattr(auth_api, "HEADER_IP_CLIENTE", "cf-connecting-ip")

    assert auth_api.ip_cliente(_pedido(cf_connecting_ip="203.0.113.5", x_real_ip="198.51.100.4")) == "203.0.113.5"


def test_el_limite_por_ip_no_se_esquiva_cambiando_el_x_forwarded_for():
    from fastapi.testclient import TestClient

    from app import limites
    from app.main import app

    with TestClient(app) as c:
        for i in range(limites.FALLOS_POR_IP):
            r = c.post("/api/login", json={"username": f"nadie{i}", "password": "x"},
                       headers={"X-Real-IP": "198.51.100.4", "X-Forwarded-For": f"10.0.0.{i}"})
            assert r.status_code == 401
        r = c.post("/api/login", json={"username": "otro", "password": "x"},
                   headers={"X-Real-IP": "198.51.100.4", "X-Forwarded-For": "10.9.9.9"})
        otra_ip = c.post("/api/login", json={"username": "otro2", "password": "x"},
                         headers={"X-Real-IP": "198.51.100.5"})

    assert r.status_code == 429
    assert otra_ip.status_code == 401
