"""Motor de regras determinístico (seções 2, 3 e 5.2).

A função `avaliar` é pura: recebe o registro normalizado, o dicionário TPU e o contexto
(identidade e documentos já conhecidos) e devolve a decisão com todos os motivos.
Nenhuma chamada de rede acontece aqui, o que torna as regras testáveis e auditáveis.
"""
from .normalize import chave_texto, parse_data

VERSAO_REGRA = "regras-2026.09.22"

TIPOS_RJ = {"RJ_PEDIDO_NOVO", "RJ_TUTELA_ANTECEDENTE", "RJ_PROCESSAMENTO_DEFERIDO",
            "RJ_PROCESSAMENTO_INDEFERIDO", "RJ_PLANO_APRESENTADO", "RJ_CONCEDIDA", "RJ_FALENCIA"}

ESTAGIOS_TERMINAIS = {"CONVOLADA_EM_FALENCIA", "DISTRIBUICAO_CANCELADA", "DESISTENCIA", "INDEFERIDO", "BAIXADO"}

ORDEM_PRIORIDADE = ["MONITORAMENTO", "MEDIA", "ALTA", "URGENTE"]

_EFEITO_EVENTO = {
    "DISTRIBUICAO": ("RJ_PEDIDO_NOVO", True),
    "RJ_CONCEDIDA": ("RJ_CONCEDIDA", True),
    "RJ_FALENCIA": ("RJ_FALENCIA", True),
    "DEFERIMENTO_GENERICO": ("RJ_PROCESSAMENTO_DEFERIDO", False),
    "INDEFERIMENTO_GENERICO": ("RJ_PROCESSAMENTO_INDEFERIDO", False),
    "INDEFERIMENTO": ("RJ_PROCESSAMENTO_INDEFERIDO", True),
    "DESISTENCIA": ("DESISTENCIA", True),
    "CANCELAMENTO": ("CANCELAMENTO_DISTRIBUICAO", True),
    "BAIXA": ("BAIXA_DEFINITIVA", True),
    "RETIFICACAO_CLASSE": ("RETIFICACAO_CLASSE", True),
    "REDISTRIBUICAO": ("REDISTRIBUICAO", True),
}


def _efeito(tabelas, tabela, codigo, nome=None):
    item = tabelas.get(tabela, {}).get(str(codigo))
    if item:
        return item["efeito"]
    if nome:  # fallback por nome, para códigos locais não mapeados
        alvo = chave_texto(nome)
        for it in tabelas.get(tabela, {}).values():
            if chave_texto(it.get("nome")) == alvo:
                return it["efeito"]
    return None


def idade(data_ajuizamento, agora_dt, cfg):
    dt = parse_data(data_ajuizamento)
    if not dt:
        return None, None
    dias = (agora_dt - dt).total_seconds() / 86400
    if dias <= cfg.novo_ate_dias:
        return "NOVO", dias
    if dias <= cfg.recente_ate_dias:
        return "RECENTE", dias
    return "HISTORICO", dias


def eventos_de_movimentos(reg, tabelas):
    eventos = []
    for m in reg.get("movimentos") or []:
        ef = _efeito(tabelas, "movimentos", m.get("codigo"), m.get("nome"))
        if ef in _EFEITO_EVENTO:
            tipo, confirmado = _EFEITO_EVENTO[ef]
            eventos.append({"tipo_evento": tipo, "efeito": ef, "data_evento": m.get("data"),
                            "movimento_codigo": m.get("codigo"), "movimento_nome": m.get("nome"),
                            "confirmado": confirmado, "complementos": m.get("complementos") or []})
    return eventos


def _estagio(eventos, documentos):
    """Estágio pelo último ato decisivo, em ordem cronológica."""
    estagio = "PEDIDO_DISTRIBUIDO_AGUARDANDO_DECISAO"
    deferido = False
    motivos_revisao = []
    decisivos = sorted([e for e in eventos if e["efeito"] != "DISTRIBUICAO"], key=lambda e: e["data_evento"] or "")
    for e in decisivos:
        ef = e["efeito"]
        if ef == "RJ_FALENCIA":
            estagio = "CONVOLADA_EM_FALENCIA"
        elif ef == "CANCELAMENTO":
            estagio = "DISTRIBUICAO_CANCELADA"
        elif ef == "DESISTENCIA":
            estagio = "DESISTENCIA"
        elif ef == "INDEFERIMENTO":
            estagio = "INDEFERIDO"
        elif ef == "RJ_CONCEDIDA":
            estagio, deferido = "CONCEDIDA", True
        elif ef == "BAIXA" and estagio not in ESTAGIOS_TERMINAIS:
            estagio = "BAIXADO"
        elif ef == "DEFERIMENTO_GENERICO" and estagio == "PEDIDO_DISTRIBUIDO_AGUARDANDO_DECISAO":
            estagio = "INDICIO_DE_DEFERIMENTO"
        elif ef == "INDEFERIMENTO_GENERICO" and estagio in ("PEDIDO_DISTRIBUIDO_AGUARDANDO_DECISAO", "INDICIO_DE_DEFERIMENTO"):
            estagio = "INDICIO_DE_INDEFERIMENTO"
            motivos_revisao.append("movimento genérico de indeferimento: confirmar se atinge o processamento")
    # Documento oficial (publicação ou decisão) tem precedência sobre movimento genérico
    for d in documentos:
        if d.get("ato") == "DEFERIMENTO" and estagio in ("PEDIDO_DISTRIBUIDO_AGUARDANDO_DECISAO", "INDICIO_DE_DEFERIMENTO", "INDICIO_DE_INDEFERIMENTO"):
            estagio, deferido = "PROCESSAMENTO_DEFERIDO", True
        elif d.get("ato") == "INDEFERIMENTO" and estagio not in ESTAGIOS_TERMINAIS:
            estagio = "INDEFERIDO"
        elif d.get("ato") == "CONVOLACAO":
            estagio = "CONVOLADA_EM_FALENCIA"
    return estagio, deferido, motivos_revisao


def prioridade(res, cfg, agora_dt):
    """Seção 5.2."""
    if res["status"] in ("DESCARTADO",) or res["tipo_evento"] not in TIPOS_RJ:
        return "MONITORAMENTO"
    if res["estagio"] in ESTAGIOS_TERMINAIS:
        return "MONITORAMENTO"
    _, dias = idade(res["data_ajuizamento"], agora_dt, cfg)
    if dias is None:
        p = "MEDIA"
    elif dias <= 1:
        p = "URGENTE"
    elif dias <= cfg.novo_ate_dias:
        p = "ALTA"
    elif dias <= cfg.recente_ate_dias:
        p = "ALTA" if res["estagio"] in ("PROCESSAMENTO_DEFERIDO", "PEDIDO_DISTRIBUIDO_AGUARDANDO_DECISAO", "INDICIO_DE_DEFERIMENTO") else "MEDIA"
    else:
        p = "MEDIA" if res["estagio"] in ("PROCESSAMENTO_DEFERIDO", "INDICIO_DE_DEFERIMENTO") and dias <= 90 else "MONITORAMENTO"
    if res.get("quantidade_empresas", 0) > 1:  # grupo com múltiplas recuperandas eleva prioridade
        p = ORDEM_PRIORIDADE[min(ORDEM_PRIORIDADE.index(p) + 1, len(ORDEM_PRIORIDADE) - 1)]
    return p


def confianca(res, contexto):
    """Confiança do registro. Regra 7.1: teto de 0,70 sem CNPJ ou documento oficial."""
    if res["status"] == "DESCARTADO":
        return 0.0
    c = {"A": 0.90, "B": 0.90, "C": 0.93, "D": 0.60}.get(res["rota"], 0.5)
    tem_cnpj = bool(contexto.get("empresas_verificadas"))
    tem_doc = any(d.get("nivel") in ("A", "B") for d in contexto.get("documentos", []))
    if tem_cnpj:
        c += 0.05
    if tem_doc:
        c += 0.03
    if res["inconsistencias"]:
        c = min(c, 0.50)
    if contexto.get("ocr_baixa_qualidade"):
        c -= 0.15
    if not tem_cnpj and not tem_doc:
        c = min(c, 0.70)
    return round(max(0.0, min(c, 0.99)), 2)


def avaliar(reg, tabelas, contexto, agora_dt, cfg, conhecido=None, origem="classe"):
    """Decide tipo, status, estágio, rota, confiança e prioridade de um registro."""
    contexto = contexto or {}
    motivos, inconsistencias, revisao = [], [], []
    res = {
        "tipo_evento": "NAO_RELACIONADO", "status": "COLETADO", "estagio": None, "rota": None,
        "pedido_confirmado": 0, "processamento_deferido": 0,
        "data_ajuizamento": reg.get("data_ajuizamento"),
        "quantidade_empresas": len(contexto.get("empresas_verificadas", [])),
        "motivos": motivos, "inconsistencias": inconsistencias, "revisao": revisao,
        "eventos": [], "nivel_evidencia": "B", "versao_regra": VERSAO_REGRA,
    }

    # 2.2 Exclusão obrigatória: sigilo
    if reg.get("nivel_sigilo", 0) and int(reg.get("nivel_sigilo") or 0) > 0:
        res.update(status="DESCARTADO", tipo_evento="NAO_RELACIONADO")
        motivos.append("processo com sigilo: excluído por regra de governança")
        return _finalizar(res, contexto, agora_dt, cfg)

    ef_classe = _efeito(tabelas, "classes", reg.get("classe_codigo"), reg.get("classe_nome"))
    efeitos_assunto = {_efeito(tabelas, "assuntos", a.get("codigo"), a.get("nome")) for a in reg.get("assuntos") or []}
    eventos = eventos_de_movimentos(reg, tabelas)
    res["eventos"] = eventos
    documentos = contexto.get("documentos", [])

    if not reg.get("cnj_valido"):
        inconsistencias.append("número CNJ ausente ou com dígito verificador inválido")

    # Classes que não são RJ
    if ef_classe == "RE":
        res.update(tipo_evento="RE_EXTRAJUDICIAL", status="CONFIRMADO", rota="A")
        motivos.append("classe oficial de recuperação extrajudicial: classificação distinta, não soma como RJ")
        return _finalizar(res, contexto, agora_dt, cfg)
    if ef_classe == "FALENCIA":
        res.update(tipo_evento="PEDIDO_FALENCIA", status="CONFIRMADO", rota="A")
        motivos.append("pedido de falência: sinal preventivo relevante, não é RJ confirmada")
        return _finalizar(res, contexto, agora_dt, cfg)
    if ef_classe == "INCIDENTE":
        res.update(tipo_evento="INCIDENTE_RELACIONADO", status="DESCARTADO")
        motivos.append("classe de incidente (habilitação, impugnação ou similar): vincular ao principal, não é nova RJ")
        return _finalizar(res, contexto, agora_dt, cfg)
    if ef_classe == "INSOLVENCIA_CIVIL":
        res.update(tipo_evento="NAO_RELACIONADO", status="DESCARTADO")
        motivos.append("insolvência civil não é recuperação judicial")
        return _finalizar(res, contexto, agora_dt, cfg)
    if ef_classe != "RJ":
        # Veio da consulta de segurança por movimentos: possível erro de autuação
        if origem == "seguranca" and any(e["efeito"] in ("RJ_CONCEDIDA", "RJ_FALENCIA") for e in eventos):
            res.update(tipo_evento="REVISAO_MANUAL", status="CANDIDATO", rota="D")
            motivos.append("ato recuperacional em processo fora da classe RJ: possível erro de autuação")
            revisao.append("confirmar classe e natureza do processo antes de qualquer oferta")
        else:
            res.update(status="DESCARTADO")
            motivos.append("classe fora do escopo recuperacional")
        return _finalizar(res, contexto, agora_dt, cfg)

    # Classe RJ: Rota A como base
    res["tipo_evento"] = "RJ_PEDIDO_NOVO"
    res["pedido_confirmado"] = 1
    motivos.append("classe oficial 129 Recuperação Judicial (metadado DataJud, nível B)")

    if "DIVERGE_RE" in efeitos_assunto:
        inconsistencias.append("classe Recuperação Judicial com assunto Recuperação extrajudicial")
    if "DIVERGE_LIQUIDACAO" in efeitos_assunto:
        inconsistencias.append("classe Recuperação Judicial com assunto Liquidação extrajudicial")
    if "DIVERGE_CONVOLACAO" in efeitos_assunto and not any(e["efeito"] == "RJ_FALENCIA" for e in eventos):
        inconsistencias.append("assunto de convolação em falência sem decreto de falência nos movimentos")
    if "INCIDENTE" in efeitos_assunto:
        inconsistencias.append("assunto típico de incidente (classificação de créditos) autuado na classe RJ")
    dist = [e for e in eventos if e["efeito"] == "DISTRIBUICAO"]
    if dist and any("dependencia" in chave_texto(c) for c in dist[0]["complementos"]):
        inconsistencias.append("distribuição por dependência: pode ser incidente ou litisconsórcio de grupo econômico")

    # Documento oficial divergente da classe
    for d in documentos:
        if d.get("ato") == "EXTRAJUDICIAL":
            inconsistencias.append("documento oficial indica recuperação extrajudicial")
        if d.get("ato") == "MERA_MENCAO":
            inconsistencias.append("documento apenas menciona recuperação judicial")

    if not reg.get("data_ajuizamento"):
        inconsistencias.append("data de ajuizamento ausente")

    # Janela de novidade
    cat, dias = idade(reg.get("data_ajuizamento"), agora_dt, cfg)
    if dias is not None and dias > cfg.janela_captura_dias and not conhecido:
        res.update(status="DESCARTADO")
        motivos.append(f"ajuizamento há {int(dias)} dias, fora da janela de captura de {cfg.janela_captura_dias} dias")
        return _finalizar(res, contexto, agora_dt, cfg)

    estagio, deferido, mot_rev = _estagio(eventos, documentos)
    res["estagio"] = estagio
    res["processamento_deferido"] = int(deferido)
    revisao.extend(mot_rev)
    if estagio == "CONCEDIDA":
        res["tipo_evento"] = "RJ_CONCEDIDA"
    elif estagio == "CONVOLADA_EM_FALENCIA":
        res["tipo_evento"] = "RJ_FALENCIA"
        motivos.append("convolação em falência: retirado da fila de nova RJ")
    elif estagio == "INDEFERIDO":
        res["tipo_evento"] = "RJ_PROCESSAMENTO_INDEFERIDO"
    elif estagio == "PROCESSAMENTO_DEFERIDO":
        res["tipo_evento"] = "RJ_PROCESSAMENTO_DEFERIDO"
    if any(d.get("ato") == "TUTELA_ANTECEDENTE" for d in documentos):
        res["tipo_evento"] = "RJ_TUTELA_ANTECEDENTE"

    if inconsistencias:  # Rota D
        res.update(status="PROVISORIO", rota="D")
        revisao.append("metadado e evidência divergem: validação humana antes da oferta comercial")
    else:
        res["rota"] = "C" if any(d.get("nivel") in ("A", "B") and d.get("ato") in ("DEFERIMENTO", "DISTRIBUICAO") for d in documentos) else "A"
        res["status"] = "CONFIRMADO"
        if estagio in ESTAGIOS_TERMINAIS:
            res["status"] = "ENCERRADO"
            motivos.append(f"estágio terminal: {estagio.lower().replace('_', ' ')}")
        elif conhecido and conhecido.get("status") in ("CONFIRMADO", "ATUALIZADO") and (
                conhecido.get("estagio") != estagio or conhecido.get("tipo_evento") != res["tipo_evento"]):
            res["status"] = "ATUALIZADO"
    if revisao and res["status"] == "CONFIRMADO":
        res["status"] = "PROVISORIO"
    return _finalizar(res, contexto, agora_dt, cfg)


def _finalizar(res, contexto, agora_dt, cfg):
    res["idade"], _ = idade(res.get("data_ajuizamento"), agora_dt, cfg)
    res["confianca"] = confianca(res, contexto)
    res["prioridade"] = prioridade(res, cfg, agora_dt)
    sem_identidade = not contexto.get("empresas_verificadas")
    res["contato_bloqueado"] = int(sem_identidade or res["status"] not in ("CONFIRMADO", "ATUALIZADO")
                                   or bool(contexto.get("opt_out")) or bool(res["revisao"]))
    if sem_identidade and res["tipo_evento"] in TIPOS_RJ and res["status"] not in ("DESCARTADO",):
        res["revisao"].append("empresa sem CNPJ verificado: contato bloqueado até validação de identidade")
    res["revisao_humana"] = int(bool(res["revisao"]))
    return res
