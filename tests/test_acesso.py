"""Restrição de acesso por IP e token do administrador inicial."""
import os

os.environ["ANTEVE_AGENDADOR"] = "0"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from anteve import api  # noqa: E402
from anteve.config import CONFIG  # noqa: E402
from anteve.db import DB  # noqa: E402

SBK = "186.193.236.194"


@pytest.fixture
def cliente(monkeypatch):
    monkeypatch.setattr(api, "db", DB(":memory:"))
    monkeypatch.setattr(CONFIG, "ips_permitidos", [SBK, "179.191.112.34"])
    monkeypatch.setattr(CONFIG, "confiar_proxy", True)
    monkeypatch.setattr(CONFIG, "cron_secret", "segredo")
    return TestClient(api.app)


def test_ip_fora_da_lista_e_bloqueado(cliente):
    assert cliente.get("/", headers={"x-forwarded-for": "8.8.8.8"}).status_code == 403
    assert cliente.get("/api/eu", headers={"x-forwarded-for": "8.8.8.8, " + SBK}).status_code == 403


def test_ip_sbk_chega_ao_login(cliente):
    assert cliente.get("/", headers={"x-forwarded-for": SBK}).status_code == 200
    assert cliente.get("/api/eu", headers={"x-forwarded-for": SBK}).status_code == 401
    token = api.db.criar_usuario("Admin", "admin", "tk_teste")
    r = cliente.get("/api/eu", headers={"x-forwarded-for": "179.191.112.34", "x-token": token})
    assert r.status_code == 200 and r.json()["papel"] == "admin"


def test_sem_proxy_confiavel_cabecalho_e_ignorado(cliente, monkeypatch):
    monkeypatch.setattr(CONFIG, "confiar_proxy", False)
    assert cliente.get("/", headers={"x-forwarded-for": SBK}).status_code == 403


def test_cron_fica_fora_da_restricao_mas_exige_segredo(cliente):
    assert cliente.get("/api/cron/coleta", headers={"x-forwarded-for": "8.8.8.8"}).status_code == 401
