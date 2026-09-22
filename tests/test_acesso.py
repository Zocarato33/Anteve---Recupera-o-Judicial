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
    assert cliente.get("/api/eu", headers={**ip, "x-token": token + "0"}).status_code == 401


def test_sessao_vale_em_outra_instancia(cliente, monkeypatch):
    """No Vercel cada instância tem seu próprio processo; a sessão não pode depender de memória local."""
    ip = {"x-forwarded-for": SBK}
    token = cliente.post("/api/login", json={"login": "joao.zocarato", "senha": "1234"}, headers=ip).json()["token"]
    outra = DB(":memory:")
    api.garantir_admin(outra)
    monkeypatch.setattr(api, "db", outra)
    assert cliente.get("/api/eu", headers={**ip, "x-token": token}).status_code == 200


def _entrar(cliente, login="joao.zocarato", senha="1234"):
    r = cliente.post("/api/login", json={"login": login, "senha": senha}, headers={"x-forwarded-for": SBK})
    assert r.status_code == 200, r.text
    return {"x-forwarded-for": SBK, "x-token": r.json()["token"]}


def test_admin_inclui_redefine_e_exclui_usuario(cliente):
    adm = _entrar(cliente)
    r = cliente.post("/api/usuarios", json={"nome": "Maria Silva", "login": "Maria.Silva", "papel": "analista"}, headers=adm)
    assert r.status_code == 200
    senha = r.json()["senha"]
    assert r.json()["login"] == "maria.silva" and len(senha) == 12
    assert cliente.post("/api/usuarios", json={"nome": "X", "login": "maria.silva"}, headers=adm).status_code == 409
    assert cliente.post("/api/usuarios", json={"nome": "X", "login": "x y"}, headers=adm).status_code == 422
    assert cliente.post("/api/usuarios", json={"nome": "X", "login": "xy.z", "senha": "123"}, headers=adm).status_code == 422
    maria = _entrar(cliente, "maria.silva", senha)
    assert cliente.get("/api/usuarios", headers=maria).status_code == 403
    uid = next(x["id"] for x in cliente.get("/api/usuarios", headers=adm).json() if x["login"] == "maria.silva")

    nova = cliente.post(f"/api/usuarios/{uid}/senha", json={}, headers=adm).json()["senha"]
    assert nova != senha
    assert cliente.get("/api/eu", headers=maria).status_code == 401  # sessão antiga encerrada
    maria = _entrar(cliente, "maria.silva", nova)

    assert cliente.delete(f"/api/usuarios/{uid}", headers=adm).status_code == 200
    assert cliente.get("/api/eu", headers=maria).status_code == 401
    assert all(x["login"] != "maria.silva" for x in cliente.get("/api/usuarios", headers=adm).json())


def test_nao_exclui_a_si_mesmo_nem_o_ultimo_admin(cliente):
    adm = _entrar(cliente)
    eu_id = api.db.um("SELECT id FROM usuarios WHERE login='joao.zocarato'")["id"]
    assert cliente.delete(f"/api/usuarios/{eu_id}", headers=adm).status_code == 409


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


def test_busca_por_parte_e_inclusao_manual(cliente):
    from anteve import pipeline
    from tests.test_especificacao import reg
    adm = _entrar(cliente)
    pid = pipeline.processar_registro(api.db, reg())["processo_id"]
    cnj = api.db.um("SELECT numero_cnj FROM processos WHERE id=?", (pid,))["numero_cnj"]
    r = cliente.post(f"/api/processos/{cnj}/partes", headers=adm,
                     json={"nome": "Topservice Terceirização Eireli", "polo": "PASSIVO", "evidencia_url": "https://srv03.tjpe.jus.br/x"})
    assert r.status_code == 200
    assert cliente.post(f"/api/processos/{cnj}/partes", headers=adm, json={"nome": "X", "evidencia_url": ""}).status_code == 422
    achados = cliente.get("/api/processos", params={"q": "terceirizacao"}, headers=adm).json()
    assert [p["numero_cnj"] for p in achados] == [cnj]
    assert achados[0]["partes"][0]["polo"] == "PASSIVO"
    assert cliente.get("/api/processos", params={"q": "nao existe ninguem"}, headers=adm).json() == []


def test_contagem_considera_a_base_inteira(cliente):
    from datetime import timedelta
    from anteve import pipeline
    from tests.test_especificacao import reg
    adm = _entrar(cliente)
    for i in range(5):
        pipeline.processar_registro(api.db, reg(numero=f"100000{i}-00.2026.8.26.0100", idf=f"N{i}"))
    n = api.db.um("SELECT COUNT(*) n FROM processos WHERE tipo_evento LIKE 'RJ_%' AND status!='DESCARTADO'")["n"]
    assert n >= 2
    assert len(cliente.get("/api/processos", params={"limite": 1}, headers=adm).json()) == 1
    c = cliente.get("/api/processos/contagem", headers=adm).json()
    assert c["total"] == n and sum(c["por_status"].values()) == n
