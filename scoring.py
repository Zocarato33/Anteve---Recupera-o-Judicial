"""Motor preventivo de sinais (seção 4). Explicável, recalculável e sempre rotulado
como "Recuperação judicial não confirmada"."""
from .normalize import parse_data

VERSAO_SCORE = "score-2026.09.22"
AVISO = "Recuperação judicial não confirmada"

# tipo: (peso, validade em dias, descrição, nível mínimo esperado)
CATALOGO = {
    "TUTELA_ANTECEDENTE_PREPARATORIA": (35, 90, "Tutela cautelar antecedente explicitamente preparatória"),
    "COMUNICADO_EMPRESA_RISCO_RJ": (30, 90, "Fato relevante ou comunicado da própria empresa sobre negociação coletiva ou risco de RJ"),
    "PEDIDO_FALENCIA_ATIVO": (20, 180, "Pedido de falência ativo"),
    "CRESCIMENTO_EXECUCOES": (15, 90, "Crescimento relevante de execuções frente à linha de base da empresa"),
    "PROTESTOS_RESTRICOES": (15, 60, "Múltiplos protestos ou restrições em fonte licenciada"),
    "ATRASO_CREDORES_EMPREGADOS": (10, 60, "Atraso público relevante com credores ou empregados, confirmado por fonte confiável"),
    "FECHAMENTO_DEMISSAO_COLETIVA": (8, 90, "Fechamento de unidades ou demissão coletiva oficialmente anunciada"),
    "NOTICIA_ISOLADA": (3, 30, "Notícia isolada sem confirmação primária"),
}

# Sinais negativos reduzem o score (seção 4.2)
NEGATIVOS = {
    "QUITACAO": (-15, 180, "Quitação ou acordo com credores comprovado"),
    "EXTINCAO_PEDIDO_FALENCIA": (-20, 180, "Extinção do pedido de falência"),
    "ESCLARECIMENTO_OFICIAL": (-10, 90, "Esclarecimento oficial da empresa afastando o risco"),
}

NIVEIS_CONFIAVEIS = {"A", "B", "C"}


def faixa(score, cfg):
    if score >= cfg.faixa_prioridade:
        return "PRIORIDADE_ANALISE_HUMANA"
    if score >= cfg.faixa_elevado:
        return "RISCO_ELEVADO"
    if score >= cfg.faixa_atencao:
        return "ATENCAO"
    return "MONITORAMENTO"


def calcular(sinais, agora_dt, cfg):
    """sinais: lista de dicts com tipo, nivel, fonte, url, data_sinal, peso?, validade_dias?, negativo?"""
    fatores, total, confiavel = [], 0, 0
    for s in sinais:
        tipo = s["tipo"]
        catalogo = NEGATIVOS if tipo in NEGATIVOS else CATALOGO
        if tipo not in catalogo:
            continue
        peso, validade, descricao = catalogo[tipo]
        validade = s.get("validade_dias") or validade
        dt = parse_data(s.get("data_sinal"))
        if not s.get("fonte") or not s.get("url"):
            fatores.append({"tipo": tipo, "descricao": descricao, "pontos": 0, "motivo": "sem fonte identificada: fator vale zero"})
            continue
        if not dt:
            fatores.append({"tipo": tipo, "descricao": descricao, "pontos": 0, "motivo": "sem data: fator vale zero"})
            continue
        idade = (agora_dt - dt).days
        if idade > validade:
            fatores.append({"tipo": tipo, "descricao": descricao, "pontos": 0, "motivo": f"expirado ({idade} dias; validade {validade})",
                            "fonte": s.get("fonte"), "url": s.get("url")})
            continue
        # Notícia ou sinal nível D nunca passa do peso de notícia isolada
        nivel = (s.get("nivel") or "D").upper()
        if nivel == "D" and peso > 0:
            peso = min(peso, CATALOGO["NOTICIA_ISOLADA"][0])
        total += peso
        if nivel in NIVEIS_CONFIAVEIS and peso > 0:
            confiavel += peso
        fatores.append({"tipo": tipo, "descricao": descricao, "pontos": peso, "nivel": nivel,
                        "fonte": s.get("fonte"), "url": s.get("url"), "data": s.get("data_sinal"),
                        "expira_em_dias": validade - idade})
    total = max(0, min(100, total))
    # Nenhum sinal de baixa confiabilidade pode, sozinho, levar a risco elevado
    salvaguarda = None
    if total >= cfg.faixa_elevado and confiavel < cfg.faixa_elevado:
        total = cfg.faixa_elevado - 1
        salvaguarda = "limitado a 49: contribuição de fontes confiáveis insuficiente para risco elevado"
    return {"score": total, "faixa": faixa(total, cfg), "fatores": fatores, "salvaguarda": salvaguarda,
            "aviso": AVISO, "versao": VERSAO_SCORE}
