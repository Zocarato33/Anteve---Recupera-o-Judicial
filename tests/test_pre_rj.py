"""Inteligência Pré-Recuperação Judicial: regras do Guia Nacional (versão 2.0)."""
import io
import os
import zipfile
from datetime import timedelta

os.environ["ANTEVE_AGENDADOR"] = "0"

import pytest  # noqa: E402

from anteve import pre_rj  # noqa: E402
from anteve.db import DB  # noqa: E402
from anteve.normalize import agora, iso  # noqa: E402

CNPJ = "33000167000101"
URL = "https://ri.exemplo.com.br/comunicado"


@pytest.fixture
def db():
    d = DB(":memory:")
    pre_rj.garantir(d)
    pre_rj.adicionar_empresa(d, CNPJ, "teste", "analista", razao_social="EMPRESA EXEMPLO S.A.")
    return d


def sinal(db, codigo, dias=0, conf="PRIMARIA", mat="ALTA", url=URL, trecho=None, **kw):
    return pre_rj.registrar_sinal(db, CNPJ, codigo, conf, mat, iso(agora() - timedelta(days=dias)), "RI da empresa",
                                  url, trecho or f"trecho {codigo} {dias} {url}", "analista", **kw)


def score(db):
    return db.um("SELECT * FROM pre_empresas WHERE cnpj=?", (CNPJ,))


def test_formula_peso_confianca_materialidade_atualidade(db):
    sinal(db, "DESCUMPRIMENTO_COVENANT", dias=60, conf="OFICIAL", mat="MEDIA")
    f = db.js(score(db)["calculo"])["fatores"][0]
    assert f["atualidade"] == pytest.approx(0.5, abs=0.01)
    assert f["pontos"] == pytest.approx(20 * 0.9 * 0.7 * 0.5, abs=0.2)


def test_duas_dimensoes_para_risco_elevado_e_corroboracao(db):
    sinal(db, "DESCUMPRIMENTO_COVENANT")
    sinal(db, "DESCUMPRIMENTO_COVENANT", url=URL + "/2")
    sinal(db, "DESCUMPRIMENTO_COVENANT", url=URL + "/3")
    s = score(db)
    assert s["score"] == 60 and s["faixa"] == "RISCO_RELEVANTE"
    sinal(db, "DESCUMPRIMENTO_COVENANT", url=URL + "/4")  # 80 pontos, uma só dimensão, sem evento inequívoco
    calc = db.js(score(db)["calculo"])
    assert score(db)["score"] == 64 and calc["salvaguarda"]
    sinal(db, "PATRIMONIO_NEGATIVO")  # segunda dimensão: corroboração de 5 e trava liberada
    s = score(db)
    assert s["score"] == 100 and s["faixa"] == "SINAL_CRITICO" and db.js(s["calculo"])["corroboracao"] == 5


def test_evento_inequivoco_dispensa_segunda_dimensao(db):
    sinal(db, "COMUNICADO_REESTRUTURACAO")
    sinal(db, "DEFAULT_FINANCEIRO")
    assert score(db)["score"] == 65 and score(db)["faixa"] == "RISCO_ELEVADO"


def test_noticias_limitadas_e_expiracao(db):
    for i in range(5):
        sinal(db, "NOTICIA_ISOLADA", conf="NOTICIA", url=URL + f"/n{i}")
    assert score(db)["score"] <= pre_rj.TETO_REPUTACIONAL
    sinal(db, "FECHAMENTO_DEMISSAO", dias=200, url=URL + "/velho")
    velho = [f for f in db.js(score(db)["calculo"])["fatores"] if f["codigo"] == "FECHAMENTO_DEMISSAO"][0]
    assert velho["pontos"] == 0 and "expirado" in velho["motivo"]


def test_esclarecido_sai_do_calculo_e_revisao_humana(db):
    a = sinal(db, "COMUNICADO_REESTRUTURACAO")
    sinal(db, "CONTINUIDADE_OPERACIONAL")
    assert score(db)["score"] >= 45 and score(db)["revisao_status"] == "PENDENTE"
    pre_rj.revisar(db, CNPJ, "ANALISE_CONFIRMADA", "conferido no fato relevante da companhia", "analista")
    assert score(db)["revisao_status"] == "ANALISE_CONFIRMADA"
    pre_rj.alterar_status_sinal(db, a, "ESCLARECIDO", "analista", "empresa esclareceu o comunicado")
    assert score(db)["score"] < 45 and score(db)["revisao_status"] is None


def test_identidade_baixa_penaliza_e_bloqueia(db):
    pre_rj.adicionar_empresa(db, "11222333000181", "teste", "analista", evidencia="NOME_SEMELHANTE", razao_social="X")
    pre_rj.registrar_sinal(db, "11222333000181", "DEFAULT_FINANCEIRO", "PRIMARIA", "ALTA", iso(agora()), "RI", URL, "default", "analista")
    calc = db.js(db.um("SELECT calculo FROM pre_empresas WHERE cnpj='11222333000181'")["calculo"])
    assert calc["alerta_bloqueado"] and calc["penalidade"] == 10 and calc["score"] == 20


def test_fontes_judiciais_e_rj_existente_fora_do_escopo(db):
    for url, trecho in (("https://esaj.tjsp.jus.br/cpopg/x", "decisão"), (URL + "/j", "pedido de recuperação judicial protocolado")):
        with pytest.raises(ValueError, match="judicial"):
            sinal(db, "DEFAULT_FINANCEIRO", url=url, trecho=trecho)
    with pytest.raises(ValueError, match="trecho original"):
        pre_rj.registrar_sinal(db, CNPJ, "DEFAULT_FINANCEIRO", "PRIMARIA", "ALTA", iso(agora()), "RI", URL, " ", "analista")
    pre_rj.adicionar_empresa(db, "11222333000181", "teste", "analista", razao_social="ACME S.A. - EM RECUPERAÇÃO JUDICIAL")
    assert db.um("SELECT fora_escopo FROM pre_empresas WHERE cnpj='11222333000181'")["fora_escopo"]
    with pytest.raises(ValueError, match="fora do escopo"):
        pre_rj.registrar_sinal(db, "11222333000181", "DEFAULT_FINANCEIRO", "PRIMARIA", "ALTA", iso(agora()), "RI", URL, "x", "analista")


def _zip_ipe(linhas):
    cab = "CNPJ_Companhia;Nome_Companhia;Codigo_CVM;Data_Referencia;Categoria;Tipo;Especie;Assunto;Data_Entrega;Tipo_Apresentacao;Protocolo_Entrega;Versao;Link_Download"
    txt = "\n".join([cab] + [";".join(l) for l in linhas])
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("ipe_cia_aberta_2026.csv", txt.encode("latin-1"))
    return buf.getvalue()


def test_busca_cvm_gera_candidatos_que_so_pontuam_apos_aprovacao(db):
    hoje = agora().strftime("%Y-%m-%d")
    base = ["", "", "", "", "", "", hoje, "AP", "", "1", "https://www.rad.cvm.gov.br/doc"]
    zip_ = _zip_ipe([
        ["11.222.333/0001-81", "ALFA S.A.", "1", hoje, "Fato Relevante", "", "", "Contratação de assessor para reestruturação financeira", hoje, "AP", "P1", "1", "https://www.rad.cvm.gov.br/1"],
        ["11.222.333/0001-81", "ALFA S.A.", "1", hoje, "Assembleia", "", "", "Aprovar waiver de índices financeiros das debêntures", hoje, "AP", "P2", "1", "https://www.rad.cvm.gov.br/2"],
        ["00.359.742/0001-08", "BETA S.A. - EM RECUPERAÇÃO JUDICIAL", "2", hoje, "Fato Relevante", "", "", "Reestruturação financeira", hoje, "AP", "P3", "1", "https://www.rad.cvm.gov.br/3"],
        ["11.222.333/0001-81", "ALFA S.A.", "1", hoje, "Fato Relevante", "", "", "Pedido de recuperação judicial ajuizado", hoje, "AP", "P4", "1", "https://www.rad.cvm.gov.br/4"],
        ["11.222.333/0001-81", "ALFA S.A.", "1", hoje, "Fato Relevante", "", "", "Aprovação do orçamento anual", hoje, "AP", "P5", "1", "https://www.rad.cvm.gov.br/5"],
    ])
    r = pre_rj.buscar_cvm(db, "analista", baixar=lambda u: zip_)
    assert r["candidatos_novos"] == 2 and r["ignorados_fora_escopo"] == 1 and r["empresas_novas"] == 1
    assert pre_rj.buscar_cvm(db, "analista", baixar=lambda u: zip_)["candidatos_novos"] == 0  # idempotente
    assert db.um("SELECT score FROM pre_empresas WHERE cnpj='11222333000181'")["score"] == 0
    cands = {c["codigo_sugerido"]: c for c in db.todos("SELECT * FROM pre_candidatos")}
    assert set(cands) == {"COMUNICADO_REESTRUTURACAO", "DESCUMPRIMENTO_COVENANT"}
    pre_rj.decidir_candidato(db, cands["COMUNICADO_REESTRUTURACAO"]["id"], True, "analista", "fato relevante confirmado na CVM", materialidade="ALTA")
    pre_rj.decidir_candidato(db, cands["DESCUMPRIMENTO_COVENANT"]["id"], False, "analista", "waiver preventivo, sem descumprimento")
    e = db.um("SELECT * FROM pre_empresas WHERE cnpj='11222333000181'")
    assert e["score"] == 35 and e["faixa"] == "ATENCAO"


def test_classificacao_cvm_e_cadastro(db):
    assert pre_rj.classificar_assunto("Aprovar alterações nos eventos de inadimplemento e índices financeiros das debêntures")[1] == "DESCUMPRIMENTO_COVENANT"
    assert pre_rj.classificar_assunto("Declaração de vencimento antecipado das debêntures")[1] == "DEFAULT_FINANCEIRO"
    assert pre_rj.classificar_assunto("Reestruturação organizacional da companhia")[0] is None
    pre_rj.adicionar_empresa(db, "11222333000181", "CVM", "analista", razao_social="ALFA S.A.")
    pre_rj.completar_cadastro(db, "11222333000181", lambda c: {"razao_social": "ALFA S.A. - EM RECUPERACAO JUDICIAL", "uf": "SP", "situacao_cadastral": "ATIVA"})
    e = db.um("SELECT * FROM pre_empresas WHERE cnpj='11222333000181'")
    assert e["uf"] == "SP" and e["fora_escopo"]
