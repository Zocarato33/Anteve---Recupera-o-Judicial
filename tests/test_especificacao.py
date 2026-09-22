"""Cenários obrigatórios (seção 11.2) e regras críticas das seções 3, 4 e 7."""
import json
import os
from datetime import timedelta

import pytest

from anteve import classifier, pipeline, rules, scoring, tpu
from anteve.config import CONFIG
from anteve.db import DB
from anteve.normalize import agora, cnj_valido, cnpj_valido, iso, parse_data

TAB = tpu.SEMENTE
AGORA = agora()
CNPJ_A = "33000167000101"  # CNPJ válido usado apenas como fixture
CNPJ_B = "12ABC34501DE35"  # exemplo oficial de CNPJ alfanumérico


def reg(classe="129", assuntos=None, movs=None, dias=2, numero="1013899-89.2026.8.26.0114", sigilo=0, idf="X1"):
    return {"fonte": "DataJud", "id_fonte": idf, "numero_cnj": numero, "cnj_valido": cnj_valido(numero),
            "tribunal": "TJSP", "uf": "SP", "grau": "G1", "vara": "1ª Vara de Falências e Recuperações Judiciais",
            "classe_codigo": classe, "classe_nome": TAB["classes"].get(classe, {}).get("nome", "Outra"),
            "assuntos": assuntos or [{"codigo": "4993", "nome": "Recuperação judicial e Falência"}],
            "data_ajuizamento": iso(AGORA - timedelta(days=dias)), "data_disponivel_fonte": iso(AGORA - timedelta(hours=1)),
            "nivel_sigilo": sigilo,
            "movimentos": movs if movs is not None else [{"codigo": "26", "nome": "Distribuição", "data": iso(AGORA - timedelta(days=dias)),
                                                          "complementos": ["sorteio"]}]}


def mov(codigo, dias=0, comp=None):
    return {"codigo": codigo, "nome": TAB["movimentos"].get(codigo, {}).get("nome", "x"), "data": iso(AGORA - timedelta(days=dias)),
            "complementos": comp or []}


@pytest.fixture
def db(monkeypatch):
    """Roda em SQLite por padrão; com TEST_DATABASE_URL roda o mesmo teste em PostgreSQL."""
    url = os.environ.get("TEST_DATABASE_URL")
    d = DB(url or ":memory:")
    if url:
        tabelas = [r["tablename"] for r in d.todos("SELECT tablename FROM pg_tables WHERE schemaname='public'")]
        d.exec("TRUNCATE " + ", ".join(tabelas) + " RESTART IDENTITY CASCADE")
    tpu.carregar(d)
    return d


# ---------------------------------------------------------------- normalização
def test_cnj_e_cnpj():
    assert cnj_valido("1013899-89.2026.8.26.0114")
    assert not cnj_valido("0000000-00.2026.8.00.0000")
    assert cnpj_valido(CNPJ_A) and cnpj_valido(CNPJ_B)
    assert not cnpj_valido("00000000000100")


def test_formato_compacto_datajud():
    assert parse_data("20260819141603").isoformat() == "2026-08-19T14:16:03-03:00"


# ---------------------------------------------------------------- 11.2 cenários
def test_classe_correta_e_documento_confirma(db):
    r = pipeline.processar_registro(db, reg())
    pid = r["processo_id"]
    pipeline.incorporar_publicacoes(db, pid, [{"fonte": "DJEN", "numero_cnj": "10138998920268260114", "hash": "h1",
        "url": "https://djen.exemplo/1", "texto": "EMPRESA EXEMPLO S.A., inscrita no CNPJ 33.000.167/0001-01, recuperanda, "
        "requer o processamento. Defiro o processamento da recuperação judicial. Nomeio administrador judicial ALFA ADMINISTRACAO LTDA, CNPJ ..."}])
    p = db.um("SELECT * FROM processos WHERE id=?", (pid,))
    assert p["status"] == "CONFIRMADO"
    assert p["tipo_evento"] == "RJ_PROCESSAMENTO_DEFERIDO"
    assert p["confianca"] >= 0.95
    assert p["contato_bloqueado"] == 0
    assert "ALFA ADMINISTRACAO LTDA" in (p["administrador_judicial"] or "")


def test_sem_cnpj_confianca_limitada_e_contato_bloqueado():
    r = rules.avaliar(reg(), TAB, {}, AGORA, CONFIG)
    assert r["status"] == "CONFIRMADO" and r["tipo_evento"] == "RJ_PEDIDO_NOVO"
    assert r["confianca"] <= 0.70
    assert r["contato_bloqueado"] == 1


def test_classe_generica_com_pedido_na_inicial_nao_confirma_sozinha():
    r = rules.avaliar(reg(classe="7"), TAB, {"documentos": [{"nivel": "B", "ato": "DISTRIBUICAO"}]}, AGORA, CONFIG, origem="seguranca")
    assert r["status"] != "CONFIRMADO"


def test_habilitacao_distribuida_hoje_e_incidente():
    r = rules.avaliar(reg(classe="111", dias=0), TAB, {}, AGORA, CONFIG)
    assert r["tipo_evento"] == "INCIDENTE_RELACIONADO" and r["status"] == "DESCARTADO"


def test_acordao_que_cita_jurisprudencia_e_mera_mencao():
    saida = json.dumps({"classificacao": "MERA_MENCAO", "confirmado": False, "empresa_requerente": [], "evidencias": [
        {"fonte": "DJEN", "documento": "acórdão", "pagina": "3", "trecho_resumido": "cita precedente sobre RJ"}],
        "divergencias": [], "confianca": 0.9, "necessita_revisao_humana": False})
    out, rej = classifier.validar_saida(saida, {"numero_cnj": "x"}, [{"nivel": "B", "texto": "..."}])
    assert out["classificacao"] == "MERA_MENCAO" and out["confianca"] <= 0.70


def test_recuperacao_extrajudicial_separada():
    r = rules.avaliar(reg(classe="128"), TAB, {}, AGORA, CONFIG)
    assert r["tipo_evento"] == "RE_EXTRAJUDICIAL" and r["pedido_confirmado"] == 0


def test_classe_rj_com_assunto_extrajudicial_vai_para_revisao():
    r = rules.avaliar(reg(assuntos=[{"codigo": "4994", "nome": "Recuperação extrajudicial"}]), TAB, {}, AGORA, CONFIG)
    assert r["status"] == "PROVISORIO" and r["rota"] == "D" and r["revisao_humana"]


def test_pedido_de_falencia_e_sinal_preventivo():
    r = rules.avaliar(reg(classe="108"), TAB, {}, AGORA, CONFIG)
    assert r["tipo_evento"] == "PEDIDO_FALENCIA" and r["pedido_confirmado"] == 0


def test_mesmo_processo_em_tres_fontes_um_registro(db):
    pipeline.processar_registro(db, reg())
    r2 = reg(); r2["movimentos"] = r2["movimentos"] + [mov("51", 1)]
    pipeline.processar_registro(db, r2)
    pid = db.um("SELECT id FROM processos")["id"]
    pipeline.incorporar_publicacoes(db, pid, [{"fonte": "DJEN", "numero_cnj": "10138998920268260114", "hash": "p1",
                                               "url": "https://djen.exemplo/2", "texto": "pedido de recuperação judicial"}])
    assert db.um("SELECT COUNT(*) n FROM processos")["n"] == 1
    assert db.um("SELECT COUNT(DISTINCT fonte||hash_documento) n FROM evidencias WHERE processo_id=?", (pid,))["n"] >= 3


def test_homonimos_nao_sao_unidos(db):
    r = pipeline.processar_registro(db, reg())
    pid = r["processo_id"]
    with pytest.raises(ValueError):
        pipeline.vincular_empresa(db, pid, "00000000000000", "EMPRESA X", evidencia_url="https://x")
    # Sem CNPJ, somente o nome não cria vínculo: a publicação abaixo gera revisão, não identidade
    pipeline.incorporar_publicacoes(db, pid, [{"fonte": "DJEN", "numero_cnj": "10138998920268260114", "hash": "p9",
                                               "url": "https://djen.exemplo/9", "texto": "EMPRESA X LTDA requer recuperação judicial",
                                               "destinatarios": [{"nome": "EMPRESA X LTDA", "polo": "A"}]}])
    assert db.um("SELECT COUNT(*) n FROM processo_empresas")["n"] == 0


def test_fonte_indisponivel_nao_retorna_nenhum_processo(db, monkeypatch):
    from anteve import orchestrator
    from anteve.connectors import datajud
    from anteve.connectors.base import FonteIndisponivel

    def falha(*a, **k):
        raise FonteIndisponivel("HTTP 503")
    monkeypatch.setattr(datajud, "por_atualizacao", falha)
    res = orchestrator.coletar_tribunal(db, "tjsp")
    assert res["erro"] and "indispon" in res["erro"]
    assert db.um("SELECT status FROM saude_fontes WHERE tribunal='TJSP'")["status"] == "INDISPONIVEL"
    assert db.um("SELECT * FROM cursores") is None  # cursor não avança em falha


def test_indeferimento_posterior_atualiza_e_notifica(db):
    pipeline.processar_registro(db, reg())
    r2 = reg(); r2["movimentos"] = r2["movimentos"] + [mov("454", 0)]
    pipeline.processar_registro(db, r2)
    p = db.um("SELECT * FROM processos")
    assert p["estagio"] == "INDEFERIDO" and p["status"] == "ENCERRADO"
    tipos = {a["tipo"] for a in db.todos("SELECT tipo FROM alertas")}
    assert {"CONFIRMADO", "ATUALIZACAO"} <= tipos
    assert db.um("SELECT status_funil FROM oportunidades")["status_funil"] == "ENCERRADA"


# ---------------------------------------------------------------- outras regras
def test_convolacao_retira_da_fila_de_nova_rj():
    r = rules.avaliar(reg(movs=[mov("26", 40), mov("202", 1)], dias=40), TAB, {}, AGORA, CONFIG)
    assert r["tipo_evento"] == "RJ_FALENCIA" and r["prioridade"] == "MONITORAMENTO"


def test_cancelamento_de_distribuicao_encerra():
    r = rules.avaliar(reg(movs=[mov("26", 5), mov("488", 2)], dias=5), TAB, {}, AGORA, CONFIG)
    assert r["status"] == "ENCERRADO" and r["estagio"] == "DISTRIBUICAO_CANCELADA"


def test_distribuicao_por_dependencia_vai_para_revisao():
    r = rules.avaliar(reg(movs=[mov("26", 2, ["dependência"])]), TAB, {}, AGORA, CONFIG)
    assert r["status"] == "PROVISORIO"


def test_sigilo_excluido(db):
    r = pipeline.processar_registro(db, reg(sigilo=5))
    assert r["acao"] == "excluido_sigilo"
    assert db.um("SELECT COUNT(*) n FROM processos")["n"] == 0


def test_prioridade_ultimas_24h_urgente():
    r = rules.avaliar(reg(dias=0.5), TAB, {}, AGORA, CONFIG)
    assert r["prioridade"] == "URGENTE"


def test_retificacao_nao_reinicia_idade(db):
    pipeline.processar_registro(db, reg(dias=20))
    original = db.um("SELECT data_ajuizamento FROM processos")["data_ajuizamento"]
    pipeline.processar_registro(db, reg(dias=1))
    assert db.um("SELECT data_ajuizamento FROM processos")["data_ajuizamento"] == original


def test_fora_da_janela_descartado():
    r = rules.avaliar(reg(dias=900), TAB, {}, AGORA, CONFIG)
    assert r["status"] == "DESCARTADO"


# ---------------------------------------------------------------- score preventivo
def _s(tipo, nivel="B", dias=5, url="https://fonte"):
    return {"tipo": tipo, "nivel": nivel, "fonte": "Fonte", "url": url, "data_sinal": iso(AGORA - timedelta(days=dias))}


def test_exemplo_de_calculo_da_especificacao():
    r = scoring.calcular([_s("PEDIDO_FALENCIA_ATIVO"), _s("CRESCIMENTO_EXECUCOES", "C"), _s("NOTICIA_ISOLADA", "D")], AGORA, CONFIG)
    assert r["score"] == 38 and r["faixa"] == "ATENCAO" and r["aviso"] == "Recuperação judicial não confirmada"


def test_pesos_expiram():
    r = scoring.calcular([_s("NOTICIA_ISOLADA", "D", dias=45)], AGORA, CONFIG)
    assert r["score"] == 0


def test_sinais_negativos_reduzem():
    r = scoring.calcular([_s("PEDIDO_FALENCIA_ATIVO"), _s("EXTINCAO_PEDIDO_FALENCIA")], AGORA, CONFIG)
    assert r["score"] == 0


def test_baixa_confiabilidade_nao_gera_risco_elevado():
    sinais = [_s("COMUNICADO_EMPRESA_RISCO_RJ", "D", url=f"https://n{i}") for i in range(10)]
    r = scoring.calcular(sinais, AGORA, CONFIG)
    assert r["score"] < 50


def test_sem_fonte_vale_zero():
    r = scoring.calcular([{"tipo": "PEDIDO_FALENCIA_ATIVO", "nivel": "B", "fonte": "", "url": "", "data_sinal": iso(AGORA)}], AGORA, CONFIG)
    assert r["score"] == 0


# ---------------------------------------------------------------- 7.1 regras pós-modelo
def test_rejeita_json_invalido():
    out, rej = classifier.validar_saida("Aqui está: {", {}, [])
    assert out is None


def test_rejeita_categoria_fora_da_enumeracao():
    out, _ = classifier.validar_saida(json.dumps({"classificacao": "RJ_TALVEZ"}), {}, [])
    assert out is None


def test_rejeita_confirmado_sem_cnj_e_nivel_a_b():
    s = json.dumps({"classificacao": "RJ_PEDIDO_NOVO", "confirmado": True, "empresa_requerente": [], "evidencias": [{"fonte": "x"}],
                    "confianca": 0.95})
    out, rej = classifier.validar_saida(s, {"numero_cnj": ""}, [{"nivel": "D", "texto": "notícia"}])
    assert out["confirmado"] is False and out["confianca"] <= 0.70


def test_cnpj_inventado_pela_ia_e_descartado():
    s = json.dumps({"classificacao": "RJ_PEDIDO_NOVO", "confirmado": True, "evidencias": [{"fonte": "DJEN"}], "confianca": 0.9,
                    "empresa_requerente": [{"razao_social": "X", "cnpj": CNPJ_A, "confianca": 0.9}]})
    out, rej = classifier.validar_saida(s, {"numero_cnj": "1013899-89.2026.8.26.0114", "classe_codigo": "129"},
                                        [{"nivel": "B", "texto": "sem cnpj no texto"}])
    assert out["empresa_requerente"][0]["cnpj"] == "" and out["confianca"] <= 0.70


def test_preventivo_declara_nao_confirmado():
    s = json.dumps({"classificacao": "SINAL_PREVENTIVO", "confirmado": True, "fundamentos": [], "evidencias": [{"fonte": "x"}], "confianca": 0.5})
    out, _ = classifier.validar_saida(s, {"numero_cnj": "x"}, [{"nivel": "B"}])
    assert "Recuperação judicial não confirmada" in out["fundamentos"] and out["confirmado"] is False


def test_ia_nao_acionada_sem_evidencia(db):
    assert classifier.classificar(db, 1, {"numero_cnj": "x"}, [], tpu.carregar(db), chamador=lambda p: ("{}", {})) is None


def test_auditoria_da_ia(db):
    s = json.dumps({"classificacao": "RJ_PEDIDO_NOVO", "confirmado": True, "evidencias": [{"fonte": "DJEN"}], "confianca": 0.8,
                    "empresa_requerente": []})
    classifier.classificar(db, 1, {"numero_cnj": "1013899-89.2026.8.26.0114"}, [{"nivel": "B", "texto": "t"}], tpu.carregar(db),
                           chamador=lambda p: (s, {"input_tokens": 10, "output_tokens": 5}))
    ex = db.um("SELECT * FROM ia_execucoes")
    assert ex["versao_prompt"] == classifier.VERSAO_PROMPT and len(ex["hash_entrada"]) == 64


def test_gate_provisorio_nao_gera_alerta(db):
    pipeline.processar_registro(db, reg(assuntos=[{"codigo": "4994", "nome": "Recuperação extrajudicial"}]))
    assert db.um("SELECT COUNT(*) n FROM alertas")["n"] == 0


def test_revisao_humana_confirma_e_nao_reabre(db):
    r = pipeline.processar_registro(db, reg(movs=[mov("26", 2, ["dependência"])]))
    rev = db.um("SELECT * FROM revisoes WHERE fila='CLASSIFICACAO' AND status='PENDENTE'")
    db.exec("UPDATE revisoes SET status='DECIDIDA', decisao='CONFIRMAR', justificativa='petição inicial conferida', decidido_em='x' WHERE id=?", (rev["id"],))
    pipeline.reprocessar(db, r["processo_id"])
    assert db.um("SELECT status FROM processos")["status"] == "CONFIRMADO"
    assert db.um("SELECT COUNT(*) n FROM revisoes WHERE fila='CLASSIFICACAO' AND status='PENDENTE'")["n"] == 0


def test_execucao_parcial_retoma_sem_perder_registros(db, monkeypatch):
    """Vercel: ao atingir o prazo, grava o cursor no último registro processado e retoma dali."""
    import time as _t
    from anteve import orchestrator
    from anteve.connectors import datajud

    def fonte(n0, n):
        def gen(*a, **k):
            for i in range(n0, n):
                yield {"id": f"TJSP_{i}", "numeroProcesso": "10138998920268260114", "tribunal": "TJSP", "classe": {"codigo": 129, "nome": "Recuperação Judicial"},
                       "dataAjuizamento": (AGORA - timedelta(days=3)).strftime("%Y%m%d%H%M%S"),
                       "dataHoraUltimaAtualizacao": (AGORA - timedelta(hours=10 - i)).isoformat(), "movimentos": []}
        return gen
    monkeypatch.setattr(datajud, "seguranca_por_movimentos", lambda *a, **k: iter([]))
    monkeypatch.setattr(datajud, "por_atualizacao", fonte(0, 5))
    res = orchestrator.coletar_tribunal(db, "tjsp", prazo=_t.time() - 1)
    assert res.get("parcial") and db.estado("parcial:tjsp") == "1"
    assert db.um("SELECT status FROM saude_fontes")["status"] == "PARCIAL"
    res = orchestrator.coletar_tribunal(db, "tjsp")
    assert not res.get("parcial") and db.estado("parcial:tjsp") == "0"
    assert db.um("SELECT status FROM saude_fontes")["status"] == "OK"


# ---------------------------------------------------------------- partes
def _pub_partes(hash_="pp1"):
    from anteve.connectors import djen
    item = {"numero_processo": "10138998920268260114", "siglaTribunal": "TJSP", "texto": "Intimação no pedido de recuperação judicial",
            "hash": hash_, "link": "https://djen.exemplo/pp",
            "destinatarios": [{"nome": "JOAO VARELLA SOCIEDADE DE ADVOGADOS", "polo": "A"},
                              {"nome": "TOPSERVICE TERCEIRIZAÇÃO EIRELI", "polo": "P"}],
            "destinatarioadvogados": [{"advogado": {"nome": "João Campiello Varella Neto", "numero_oab": "12345", "uf_oab": "PE"}}]}
    return djen._normalizar(item)


def test_partes_do_djen_sao_gravadas_sem_duplicar(db):
    pid = pipeline.processar_registro(db, reg())["processo_id"]
    pipeline.incorporar_publicacoes(db, pid, [_pub_partes("pp1")])
    pipeline.incorporar_publicacoes(db, pid, [_pub_partes("pp2")])  # outra publicação com as mesmas partes
    partes = {(x["polo"], x["tipo"], x["nome"], x["oab"]) for x in db.todos("SELECT * FROM partes WHERE processo_id=?", (pid,))}
    assert partes == {("ATIVO", "PARTE", "JOAO VARELLA SOCIEDADE DE ADVOGADOS", None),
                      ("PASSIVO", "PARTE", "TOPSERVICE TERCEIRIZAÇÃO EIRELI", None),
                      ("OUTRO", "ADVOGADO", "JOÃO CAMPIELLO VARELLA NETO", "12345/PE")}
    # nome sem CNPJ continua sem criar vínculo de identidade
    assert db.um("SELECT COUNT(*) n FROM processo_empresas")["n"] == 0


def test_fila_do_diario_nao_repete_processo_em_24h(db, monkeypatch):
    from anteve import orchestrator
    from anteve.connectors import djen
    consultas = []
    monkeypatch.setattr(djen, "por_processo", lambda n: consultas.append(n) or [])
    pipeline.processar_registro(db, reg())
    assert orchestrator.enriquecer_com_diario(db)["consultados"] == 1
    r = orchestrator.enriquecer_com_diario(db)
    assert r["consultados"] == 0 and r["pendentes"] == 0 and len(consultas) == 1
