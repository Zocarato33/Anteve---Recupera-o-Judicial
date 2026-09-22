"""Dicionário versionado das Tabelas Processuais Unificadas (TPU) do CNJ.

Os códigos abaixo foram conferidos no webservice público do SGT/CNJ em 22/09/2026.
A função `sincronizar` consulta o SGT novamente, compara nomes e grava uma nova versão
com hash. Nenhuma regra usa código fixo fora deste dicionário.
"""
import re

import requests

from .config import CONFIG
from .normalize import agora, hash_obj, iso

VERSAO_SEMENTE = "tpu-semente-2026-09-22"

# efeito: semântica usada pelo motor de regras
SEMENTE = {
    "classes": {
        "129": {"nome": "Recuperação Judicial", "efeito": "RJ"},
        "128": {"nome": "Recuperação Extrajudicial", "efeito": "RE"},
        "108": {"nome": "Falência de Empresários, Sociedades Empresárias, Microempresas e Empresas de Pequeno Porte", "efeito": "FALENCIA"},
        "111": {"nome": "Habilitação de Crédito", "efeito": "INCIDENTE"},
        "114": {"nome": "Impugnação de Crédito", "efeito": "INCIDENTE"},
        "38": {"nome": "Habilitação", "efeito": "INCIDENTE"},
        "14991": {"nome": "Classificação de Crédito Público", "efeito": "INCIDENTE"},
        "138": {"nome": "Restituição de Coisa ou Dinheiro na Falência do Devedor Empresário", "efeito": "INCIDENTE"},
        "166": {"nome": "Insolvência Requerida pelo Credor", "efeito": "INSOLVENCIA_CIVIL"},
        "167": {"nome": "Insolvência Requerida pelo Devedor ou pelo Espólio", "efeito": "INSOLVENCIA_CIVIL"},
    },
    "assuntos": {
        "4993": {"nome": "Recuperação judicial e Falência", "efeito": "NEUTRO"},
        "5000": {"nome": "Concurso de Credores", "efeito": "NEUTRO"},
        "9558": {"nome": "Administração judicial", "efeito": "NEUTRO"},
        "4994": {"nome": "Recuperação extrajudicial", "efeito": "DIVERGE_RE"},
        "9556": {"nome": "Convolação de recuperação judicial em falência", "efeito": "DIVERGE_CONVOLACAO"},
        "9559": {"nome": "Classificação de créditos", "efeito": "INCIDENTE"},
        "10179": {"nome": "Liquidação extrajudicial", "efeito": "DIVERGE_LIQUIDACAO"},
    },
    "movimentos": {
        "26": {"nome": "Distribuição", "efeito": "DISTRIBUICAO"},
        "36": {"nome": "Redistribuição", "efeito": "REDISTRIBUICAO"},
        "83": {"nome": "Cancelamento da distribuição", "efeito": "CANCELAMENTO"},
        "488": {"nome": "Cancelamento de Distribuição", "efeito": "CANCELAMENTO"},
        "12041": {"nome": "Concedida a recuperação judicial", "efeito": "RJ_CONCEDIDA"},
        "202": {"nome": "Decretada a falência", "efeito": "RJ_FALENCIA"},
        "463": {"nome": "Extinto o processo por desistência", "efeito": "DESISTENCIA"},
        "454": {"nome": "Indeferida a petição inicial", "efeito": "INDEFERIMENTO"},
        "12455": {"nome": "Indeferido o pedido", "efeito": "INDEFERIMENTO_GENERICO"},
        "12444": {"nome": "Deferido o pedido", "efeito": "DEFERIMENTO_GENERICO"},
        "22": {"nome": "Baixa Definitiva", "efeito": "BAIXA"},
        "14738": {"nome": "Classe retificada", "efeito": "RETIFICACAO_CLASSE"},
        "14739": {"nome": "Evolução da Classe Processual", "efeito": "RETIFICACAO_CLASSE"},
        "928": {"nome": "Republicação", "efeito": "REPUBLICACAO"},
        "11983": {"nome": "Retificação de movimento", "efeito": "RETIFICACAO_MOVIMENTO"},
    },
}

# Termos semânticos da seção 2.1 (reforço; nunca substituem classe e documento)
TERMOS = {
    "PEDIDO": ["pedido de recuperacao judicial", "requer o processamento", "lei 11.101/2005", "empresa recuperanda", "recuperanda"],
    "TUTELA": ["tutela cautelar antecedente", "mediacao antecedente", "suspensao das execucoes", "preparatoria de recuperacao judicial"],
    "DEFERIMENTO": ["defiro o processamento", "nomeio administrador judicial", "nomeio como administrador judicial", "art. 52", "apresentacao do plano"],
    "CREDORES": ["edital de credores", "relacao de credores", "quadro geral de credores", "habilitacao", "divergencia de credito"],
    "ENCERRAMENTO": ["encerrada a recuperacao", "convolo em falencia", "convolo a recuperacao judicial em falencia", "desistencia", "indefiro o processamento", "indeferimento do processamento"],
    "EXTRAJUDICIAL": ["recuperacao extrajudicial", "homologacao do plano de recuperacao extrajudicial"],
}


def efeito(dicionario, tabela, codigo):
    item = dicionario["tabelas"][tabela].get(str(codigo))
    return item["efeito"] if item else None


def carregar(db):
    """Retorna a versão vigente do dicionário gravada no banco, ou grava a semente."""
    linha = db.um("SELECT * FROM tpu_versoes ORDER BY id DESC LIMIT 1")
    if linha:
        return {"versao": linha["versao"], "hash": linha["hash"], "tabelas": db.js(linha["conteudo"])}
    return registrar(db, VERSAO_SEMENTE, SEMENTE, "semente embarcada")


def registrar(db, versao, tabelas, origem):
    h = hash_obj(tabelas)
    atual = db.um("SELECT * FROM tpu_versoes WHERE hash=?", (h,))
    if atual:
        return {"versao": atual["versao"], "hash": h, "tabelas": tabelas}
    db.exec("INSERT INTO tpu_versoes(versao,hash,conteudo,origem,criado_em) VALUES(?,?,?,?,?)",
            (versao, h, db.dump(tabelas), origem, iso(agora())))
    db.auditar("sistema", "tpu.versao", "tpu", versao, {"hash": h, "origem": origem})
    return {"versao": versao, "hash": h, "tabelas": tabelas}


def _sgt_detalhe(codigo, tipo):
    corpo = (
        '<?xml version="1.0"?><soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" '
        'xmlns:sgt="https://www.cnj.jus.br/sgt/sgt_ws.php"><soapenv:Body><sgt:pesquisarItemPublicoWS>'
        f"<tipoTabela>{tipo}</tipoTabela><tipoPesquisa>C</tipoPesquisa><valorPesquisa>{codigo}</valorPesquisa>"
        "</sgt:pesquisarItemPublicoWS></soapenv:Body></soapenv:Envelope>"
    )
    r = requests.post(CONFIG.sgt_url, data=corpo.encode("utf-8"), timeout=40, headers={
        "Content-Type": "text/xml; charset=utf-8",
        "SOAPAction": '"https://www.cnj.jus.br/sgt/sgt_ws.php#pesquisarItemPublicoWS"',
        "User-Agent": CONFIG.user_agent})
    r.raise_for_status()
    for item in re.findall(r"<ns1:Item>(.*?)</ns1:Item>", r.text, re.S):
        cod = re.search(r"<cod_item>(.*?)</cod_item>", item)
        nome = re.search(r"<nome>(.*?)</nome>", item, re.S)
        if cod and cod.group(1).strip() == str(codigo):
            return nome.group(1).strip() if nome else None
    return None


def sincronizar(db):
    """Consulta o SGT para cada código do dicionário vigente e grava nova versão se houver mudança."""
    vigente = carregar(db)
    tabelas = {k: {c: dict(v) for c, v in t.items()} for k, t in vigente["tabelas"].items()}
    tipos = {"classes": "C", "assuntos": "A", "movimentos": "M"}
    relatorio = {"conferidos": 0, "alterados": [], "nao_encontrados": [], "erros": []}
    for tabela, tipo in tipos.items():
        for codigo, item in tabelas[tabela].items():
            try:
                nome = _sgt_detalhe(codigo, tipo)
            except Exception as exc:  # fonte indisponível não altera o dicionário
                relatorio["erros"].append(f"{tabela}:{codigo}: {exc}")
                continue
            relatorio["conferidos"] += 1
            if nome is None:
                item["status_sgt"] = "NAO_ENCONTRADO"
                relatorio["nao_encontrados"].append(f"{tabela}:{codigo}")
            else:
                item["status_sgt"] = "VIGENTE"
                if nome != item.get("nome_sgt"):
                    item["nome_sgt"] = nome
                    relatorio["alterados"].append(f"{tabela}:{codigo}={nome}")
    if relatorio["erros"] and not relatorio["conferidos"]:
        relatorio["versao"] = vigente["versao"]
        return relatorio
    versao = "tpu-sgt-" + agora().strftime("%Y%m%d%H%M")
    nova = registrar(db, versao, tabelas, "sincronização SGT/CNJ")
    relatorio["versao"] = nova["versao"]
    return relatorio
