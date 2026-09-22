"""Restrição de acesso por IP e login por usuário e senha."""
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
    banco = DB(":memory:")
    monkeypatch.setattr(api, "db", banco)
    monkeypatch.setattr(CONFIG, "admin_senha", "")
    api.garantir_admin(banco)
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



def test_login_do_admin_inicial(cliente):
    ip = {"x-forwarded-for": "179.191.112.34"}
    assert cliente.post("/api/login", json={"login": "joao.zocarato", "senha": "errada"}, headers=ip).status_code == 401
    r = cliente.post("/api/login", json={"login": "Joao.Zocarato", "senha": "1234"}, headers=ip)
    assert r.status_code == 200
    token = r.json()["token"]
    eu = cliente.get("/api/eu", headers={**ip, "x-token": token})
    assert eu.status_code == 200 and eu.json()["papel"] == "admin"
    cliente.post("/api/logout", headers={**ip, "x-token": token})
    assert cliente.get("/api/eu", headers={**ip, "x-token": token}).status_code == 401


def test_admin_nao_e_duplicado_e_senha_pode_ser_redefinida(cliente, monkeypatch):
    api.garantir_admin(api.db)
    assert len(api.db.todos("SELECT id FROM usuarios WHERE login='joao.zocarato'")) == 1
    monkeypatch.setattr(CONFIG, "admin_senha", "nova-senha-forte")
    api.garantir_admin(api.db)
    assert not api.db.autenticar("joao.zocarato", "1234")
    assert api.db.autenticar("joao.zocarato", "nova-senha-forte")


def test_token_antigo_nao_da_acesso(cliente):
    from anteve.db import hash_token
    api.db.exec("INSERT INTO usuarios(nome,papel,token_hash,ativo) VALUES('legado','admin',?,1)", (hash_token("ant_x"),))
    assert cliente.get("/api/eu", headers={"x-forwarded-for": SBK, "x-token": "ant_x"}).status_code == 401


def test_sem_proxy_confiavel_cabecalho_e_ignorado(cliente, monkeypatch):
    monkeypatch.setattr(CONFIG, "confiar_proxy", False)
    assert cliente.get("/", headers={"x-forwarded-for": SBK}).status_code == 403


def test_cron_fica_fora_da_restricao_mas_exige_segredo(cliente):
    assert cliente.get("/api/cron/coleta", headers={"x-forwarded-for": "8.8.8.8"}).status_code == 401
