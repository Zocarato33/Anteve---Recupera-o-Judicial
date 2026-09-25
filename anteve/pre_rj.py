"""Inteligência Pré-Recuperação Judicial (Guia Nacional de Inteligência Pré Recuperação Judicial, versão 2.0).

Módulo independente do restante do sistema: usa só dados empresariais, financeiros, regulatórios e públicos
anteriores a qualquer pedido. Nenhuma tabela de processos é lida, e qualquer fonte judicial é recusada.
O resultado é um alerta probabilístico para análise especializada, nunca uma afirmação de que a empresa
entrará em recuperação judicial.
"""
import csv
import io
import re
import time
import zipfile
from datetime import timedelta

from .normalize import agora, chave_texto, cnpj_formatar, cnpj_limpar, cnpj_valido, hash_obj, iso, parse_data

VERSAO_FORMULA = "pre-rj-2.0"
AVISO = "Análise preventiva pré-processual. Recuperação judicial não confirmada."

ESQUEMA = """
CREATE TABLE IF NOT EXISTS pre_empresas(
  id INTEGER PRIMARY KEY, cnpj TEXT UNIQUE, razao_social TEXT, nome_fantasia TEXT, cnae TEXT, porte TEXT,
  municipio TEXT, uf TEXT, situacao_cadastral TEXT, origem TEXT, evidencia_identidade TEXT,
  confianca_identidade REAL, fora_escopo TEXT, score INTEGER DEFAULT 0, faixa TEXT, tendencia TEXT,
  calculo TEXT, calculado_em TEXT, revisao_status TEXT, revisao_faixa TEXT, incluido_por TEXT, incluido_em TEXT);
CREATE TABLE IF NOT EXISTS pre_sinais(
  id INTEGER PRIMARY KEY, cnpj TEXT, codigo TEXT, dimensao TEXT, peso INTEGER, validade_dias INTEGER,
  confianca_fonte REAL, materialidade REAL, data_evento TEXT, fonte TEXT, url TEXT, trecho_original TEXT,
  descricao TEXT, hash TEXT, divergencia TEXT, status TEXT, registrado_por TEXT, registrado_em TEXT,
  atualizado_por TEXT, atualizado_em TEXT);
CREATE TABLE IF NOT EXISTS pre_candidatos(
  id INTEGER PRIMARY KEY, cnpj TEXT, razao_social TEXT, fonte TEXT, protocolo TEXT UNIQUE, categoria_fonte TEXT,
  assunto TEXT, data_evento TEXT, url TEXT, categoria_sugerida TEXT, codigo_sugerido TEXT, termos TEXT,
  status TEXT, decidido_por TEXT, decidido_em TEXT, justificativa TEXT, sinal_id INTEGER, coletado_em TEXT);
CREATE TABLE IF NOT EXISTS pre_revisoes(
  id INTEGER PRIMARY KEY, cnpj TEXT, faixa TEXT, score INTEGER, decisao TEXT, justificativa TEXT,
  analista TEXT, decidido_em TEXT);
"""

# ------------------------------------------------------------ taxonomia (seções 5 e 7 do guia)
DIMENSOES = {
    "FINANCEIRA": "Financeira", "CONTABIL": "Contábil", "FISCAL": "Fiscal administrativa", "OPERACIONAL": "Operacional",
    "TRABALHISTA": "Trabalhista não judicial", "SOCIETARIA": "Societária", "MERCADO": "Mercado", "REPUTACIONAL": "Reputacional",
}

# código: (descrição, peso inicial, validade em dias, fonte mínima, dimensão)
CATALOGO = {
    "COMUNICADO_REESTRUTURACAO": ("Comunicado da empresa sobre avaliação de alternativas de reestruturação financeira", 35, 90, "CVM, RI ou comunicado oficial", "FINANCEIRA"),
    "DEFAULT_FINANCEIRO": ("Default ou vencimento antecipado de dívida relevante", 30, 120, "Emissor, agente fiduciário ou credor autorizado", "FINANCEIRA"),
    "CONTINUIDADE_OPERACIONAL": ("Incerteza relevante de continuidade operacional", 25, 365, "Relatório de auditoria", "CONTABIL"),
    "DESCUMPRIMENTO_COVENANT": ("Descumprimento de covenant sem solução definitiva", 20, 120, "Documento do emissor ou agente fiduciário", "FINANCEIRA"),
    "PATRIMONIO_NEGATIVO": ("Patrimônio líquido negativo ou forte deterioração", 15, 365, "Demonstração financeira", "CONTABIL"),
    "FLUXO_CAIXA_NEGATIVO": ("Fluxo de caixa operacional negativo recorrente", 12, 365, "Demonstração financeira", "CONTABIL"),
    "DIVIDA_ATIVA": ("Crescimento material de dívida ativa", 12, 180, "PGFN ou fonte administrativa aberta", "FISCAL"),
    "PROTESTOS_RESTRICOES": ("Protestos ou restrições com aceleração", 12, 90, "Fonte contratada e autorizada", "MERCADO"),
    "PERDA_CONTRATOS": ("Perda material de contratos ou clientes", 10, 180, "PNCP, comunicado ou fonte primária", "OPERACIONAL"),
    "FECHAMENTO_DEMISSAO": ("Fechamento de unidades ou demissão coletiva", 8, 120, "Empresa, sindicato ou órgão oficial", "OPERACIONAL"),
    "NOTICIA_ISOLADA": ("Notícia isolada sem confirmação", 3, 30, "Veículo identificado", "REPUTACIONAL"),
}
EVENTOS_INEQUIVOCOS = {"COMUNICADO_REESTRUTURACAO", "DEFAULT_FINANCEIRO"}  # dispensam a segunda dimensão (seção 7.2)
TETO_REPUTACIONAL = 6  # peso agregado máximo de notícias e sinais reputacionais

CONFIANCA_FONTE = {"PRIMARIA": (1.0, "Fonte primária (a própria empresa, CVM, auditoria)"),
                   "OFICIAL": (0.9, "Fonte oficial ou regulatória"),
                   "LICENCIADA": (0.8, "Fonte contratada e autorizada"),
                   "NOTICIA": (0.5, "Notícia de veículo identificado")}
MATERIALIDADE = {"ALTA": (1.0, "Alta"), "MEDIA": (0.7, "Média"), "BAIXA": (0.4, "Baixa")}

# seção 9: confiança máxima por evidência de identidade; abaixo de 0,80 o alerta fica bloqueado
IDENTIDADE = {"CNPJ_PRIMARIA": (1.00, "CNPJ completo em fonte primária"),
              "CNPJ_RAIZ_RAZAO_MUNICIPIO": (0.95, "CNPJ raiz, razão social e município compatíveis"),
              "RAZAO_ENDERECO": (0.85, "Razão social exata e endereço confirmado"),
              "FANTASIA_GRUPO": (0.70, "Nome fantasia, grupo e localidade"),
              "NOME_SEMELHANTE": (0.40, "Somente nome semelhante (revisão obrigatória)")}
IDENTIDADE_MINIMA = 0.80

# seções 1 e 7.1: faixas, linguagem permitida e ação
FAIXAS = [  # (limite inferior, código, nome, linguagem permitida, ação)
    (80, "SINAL_CRITICO", "Sinal crítico", "Sinal crítico pré-processual; recuperação judicial não confirmada.", "Revisão especializada imediata; contato automático proibido."),
    (65, "RISCO_ELEVADO", "Risco elevado", "Risco elevado para avaliação especializada.", "Análise prioritária e acompanhamento frequente."),
    (45, "RISCO_RELEVANTE", "Risco relevante", "Indícios combinados de estresse empresarial.", "Revisão por analista financeiro ou empresarial."),
    (25, "ATENCAO", "Atenção", "Sinal público que requer análise.", "Aumentar frequência e buscar fonte primária."),
    (0, "MONITORAMENTO", "Monitoramento", "Empresa em acompanhamento.", "Recalcular no ciclo normal."),
]
FAIXA_REVISAO = 45  # a partir de Risco relevante, a análise humana é obrigatória

# seção 4: o módulo recusa qualquer fonte judicial
_JUDICIAL = re.compile(r"jus\.br|datajud|\bdjen\b|comunicaapi|\bpje\b|esaj|eproc|tribunal|processo judicial|"
                       r"recupera[cç][aã]o judicial (deferida|ajuizada|protocolada|requerida)|pedido de recupera[cç][aã]o judicial|"
                       r"pedido de fal[eê]ncia|di[aá]rio de justi[cç]a|\bvara\b", re.I)
_EM_RJ = re.compile(r"em recupera[cç][aã]o judicial|\bfalid[ao]\b|massa falida", re.I)


def fonte_judicial(*textos):
    return any(t and _JUDICIAL.search(t) for t in textos)


def garantir(db):
    """Cria as tabelas do módulo, se ainda não existirem (não toca nas demais tabelas)."""
    ddl = ESQUEMA.replace("INTEGER PRIMARY KEY,", "BIGSERIAL PRIMARY KEY,").replace(" REAL", " DOUBLE PRECISION") if db.pg else ESQUEMA
    for comando in [c.strip() for c in ddl.split(";") if c.strip()]:
        db.exec(comando)


def faixa(score):
    for limite, codigo, nome, linguagem, acao in FAIXAS:
        if score >= limite:
            return {"codigo": codigo, "nome": nome, "linguagem": linguagem, "acao": acao}


# ------------------------------------------------------------ motor de score (seção 7)
def calcular(sinais, identidade, ref=None):
    """pontos = peso × confiança da fonte × materialidade × atualidade;
    score = limitar(soma + corroboração - penalidade, 0, 100), com as proteções da seção 7.2."""
    ref = ref or agora()
    fatores, dims, reput, divergencias = [], set(), 0.0, 0
    inequivoco = False
    for s in sinais:
        dt = parse_data(s.get("data_evento"))
        f = {"id": s.get("id"), "codigo": s["codigo"], "descricao": CATALOGO[s["codigo"]][0], "dimensao": s["dimensao"],
             "peso": s["peso"], "confianca_fonte": s["confianca_fonte"], "materialidade": s["materialidade"],
             "data_evento": s.get("data_evento"), "fonte": s.get("fonte"), "url": s.get("url"), "pontos": 0.0}
        if dt and dt > ref:  # evento posterior à data de referência (tendência e backtesting)
            continue
        if s.get("status") in ("ESCLARECIDO", "REVERTIDO"):
            f["motivo"] = "esclarecido ou revertido: retirado do cálculo"
        elif not dt:
            f["motivo"] = "sem data: fator vale zero"
        else:
            idade = (ref - dt).days
            f["atualidade"] = round(max(0.0, 1 - idade / s["validade_dias"]), 3)
            f["expira_em"] = iso(dt + timedelta(days=s["validade_dias"]))
            if f["atualidade"] <= 0:
                f["motivo"] = f"expirado ({idade} dias; validade {s['validade_dias']})"
            else:
                f["pontos"] = round(s["peso"] * s["confianca_fonte"] * s["materialidade"] * f["atualidade"], 2)
                if s["dimensao"] == "REPUTACIONAL":
                    permitido = max(0.0, TETO_REPUTACIONAL - reput)
                    if f["pontos"] > permitido:
                        f["pontos"], f["motivo"] = round(permitido, 2), f"peso agregado de notícias limitado a {TETO_REPUTACIONAL} pontos"
                    reput += f["pontos"]
                if f["pontos"] > 0:
                    dims.add(s["dimensao"])
                    if s["codigo"] in EVENTOS_INEQUIVOCOS and s["confianca_fonte"] >= 0.9:
                        inequivoco = True
                if s.get("divergencia"):
                    divergencias += 1
        fatores.append(f)
    soma = sum(f["pontos"] for f in fatores)
    corroboracao = min(15, 5 * (len(dims) - 1)) if len(dims) > 1 else 0
    penalidade, motivos_pen = 0, []
    if divergencias:
        penalidade += min(15, 5 * divergencias)
        motivos_pen.append(f"{divergencias} sinal(is) com divergência")
    if identidade < IDENTIDADE_MINIMA:
        penalidade += 10
        motivos_pen.append(f"identidade com confiança {identidade:.2f}, abaixo de {IDENTIDADE_MINIMA:.2f}")
    score = max(0, min(100, round(soma + corroboracao - penalidade)))
    salvaguarda = None
    if score >= 65 and len(dims) < 2 and not inequivoco:
        score, salvaguarda = 64, "limitado a 64: risco elevado exige duas dimensões independentes, salvo evento financeiro inequívoco"
    return {"score": score, "faixa": faixa(score), "soma_pontos": round(soma, 2), "corroboracao": corroboracao,
            "dimensoes": sorted(dims), "penalidade": penalidade, "motivos_penalidade": motivos_pen, "salvaguarda": salvaguarda,
            "alerta_bloqueado": identidade < IDENTIDADE_MINIMA, "fatores": fatores, "versao": VERSAO_FORMULA, "aviso": AVISO}


def _sinais(db, cnpj):
    return db.todos("SELECT * FROM pre_sinais WHERE cnpj=? ORDER BY data_evento DESC, id DESC", (cnpj,))


def recalcular(db, cnpj):
    emp = db.um("SELECT * FROM pre_empresas WHERE cnpj=?", (cnpj,))
    if not emp:
        return None
    sinais = _sinais(db, cnpj)
    atual = calcular(sinais, emp["confianca_identidade"] or 0)
    anterior = calcular(sinais, emp["confianca_identidade"] or 0, agora() - timedelta(days=30))
    dif = atual["score"] - anterior["score"]
    tendencia = "em alta" if dif >= 5 else ("em queda" if dif <= -5 else "estável")
    atual["tendencia"], atual["score_30_dias"] = tendencia, anterior["score"]
    revisao = emp["revisao_status"]
    if atual["score"] >= FAIXA_REVISAO and emp["revisao_faixa"] != atual["faixa"]["codigo"]:
        revisao = "PENDENTE"  # nova faixa elevada: volta para a fila humana
    elif atual["score"] < FAIXA_REVISAO:
        revisao = None
    db.exec("UPDATE pre_empresas SET score=?, faixa=?, tendencia=?, calculo=?, calculado_em=?, revisao_status=? WHERE cnpj=?",
            (atual["score"], atual["faixa"]["codigo"], tendencia, db.dump(atual), iso(agora()), revisao, cnpj))
    return atual


# ------------------------------------------------------------ empresas (watchlist)
def adicionar_empresa(db, cnpj, origem, ator, evidencia="CNPJ_PRIMARIA", cadastro=None, razao_social=None):
    c = cnpj_limpar(cnpj)
    if not cnpj_valido(c):
        raise ValueError("CNPJ inválido")
    if evidencia not in IDENTIDADE:
        raise ValueError("evidência de identidade inválida")
    cad = cadastro or {}
    razao = cad.get("razao_social") or razao_social
    fora = "razão social indica recuperação judicial ou falência já existente: fora do escopo pré-processual" if razao and _EM_RJ.search(razao) else None
    if db.um("SELECT id FROM pre_empresas WHERE cnpj=?", (c,)):
        return c, False
    db.exec("INSERT INTO pre_empresas(cnpj,razao_social,nome_fantasia,cnae,porte,municipio,uf,situacao_cadastral,origem,"
            "evidencia_identidade,confianca_identidade,fora_escopo,faixa,incluido_por,incluido_em) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (c, razao, cad.get("nome_fantasia"), cad.get("cnae"), cad.get("porte"), cad.get("municipio"), cad.get("uf"),
             cad.get("situacao_cadastral"), origem, evidencia, IDENTIDADE[evidencia][0], fora, "MONITORAMENTO", ator, iso(agora())))
    db.auditar(ator, "pre.empresa.incluir", "empresa", c, {"origem": origem, "evidencia": evidencia})
    recalcular(db, c)
    return c, True


def completar_cadastro(db, cnpj, consultar):
    """Companhias trazidas pela CVM entram só com CNPJ e nome; o cadastro da Receita é buscado na primeira consulta."""
    e = db.um("SELECT * FROM pre_empresas WHERE cnpj=?", (cnpj,))
    if not e or e["situacao_cadastral"]:
        return
    try:
        cad = consultar(cnpj)
    except Exception:
        return  # fonte indisponível: tenta de novo na próxima abertura
    if not cad:
        return
    db.exec("UPDATE pre_empresas SET razao_social=COALESCE(CAST(? AS TEXT),razao_social), nome_fantasia=?, cnae=?, porte=?, municipio=?, uf=?, "
            "situacao_cadastral=? WHERE cnpj=?", (cad.get("razao_social"), cad.get("nome_fantasia"), cad.get("cnae"), cad.get("porte"),
                                                  cad.get("municipio"), cad.get("uf"), cad.get("situacao_cadastral") or "não informada", cnpj))
    if cad.get("razao_social") and _EM_RJ.search(cad["razao_social"]) and not e["fora_escopo"]:
        db.exec("UPDATE pre_empresas SET fora_escopo=? WHERE cnpj=?",
                ("razão social indica recuperação judicial ou falência já existente: fora do escopo pré-processual", cnpj))


def registrar_sinal(db, cnpj, codigo, confianca, materialidade, data_evento, fonte, url, trecho, ator, descricao=None, divergencia=None):
    c = cnpj_limpar(cnpj)
    emp = db.um("SELECT * FROM pre_empresas WHERE cnpj=?", (c,))
    if not emp:
        raise ValueError("empresa não está na lista monitorada")
    if emp["fora_escopo"]:
        raise ValueError("empresa fora do escopo pré-processual")
    if codigo not in CATALOGO:
        raise ValueError("sinal fora do catálogo")
    if confianca not in CONFIANCA_FONTE or materialidade not in MATERIALIDADE:
        raise ValueError("confiança da fonte ou materialidade inválida")
    if not (fonte or "").strip() or not re.match(r"^https?://", url or ""):
        raise ValueError("sinal exige fonte identificada e URL")
    if not (trecho or "").strip():
        raise ValueError("sinal exige o trecho original da fonte (resumo não vale como evidência)")
    if not parse_data(data_evento):
        raise ValueError("sinal exige a data do evento")
    if fonte_judicial(fonte, url, trecho, descricao):
        raise ValueError("fonte ou conteúdo judicial: fora do escopo pré-processual")
    h = hash_obj([c, codigo, url, trecho.strip()])
    if db.um("SELECT 1 FROM pre_sinais WHERE hash=?", (h,)):
        raise ValueError("sinal já registrado")
    desc, peso, validade, _, dim = CATALOGO[codigo]
    db.exec("INSERT INTO pre_sinais(cnpj,codigo,dimensao,peso,validade_dias,confianca_fonte,materialidade,data_evento,fonte,url,"
            "trecho_original,descricao,hash,divergencia,status,registrado_por,registrado_em) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (c, codigo, dim, peso, validade, CONFIANCA_FONTE[confianca][0], MATERIALIDADE[materialidade][0],
             iso(parse_data(data_evento)), fonte.strip(), url.strip(), trecho.strip(), (descricao or "").strip() or None, h,
             (divergencia or "").strip() or None, "ATIVO", ator, iso(agora())))
    sid = db.um("SELECT id FROM pre_sinais WHERE hash=?", (h,))["id"]
    db.auditar(ator, "pre.sinal.registrar", "empresa", c, {"codigo": codigo, "url": url})
    recalcular(db, c)
    return sid


def alterar_status_sinal(db, sinal_id, status, ator, justificativa):
    if status not in ("ATIVO", "ESCLARECIDO", "REVERTIDO"):
        raise ValueError("status inválido")
    s = db.um("SELECT * FROM pre_sinais WHERE id=?", (sinal_id,))
    if not s:
        raise LookupError("sinal não encontrado")
    db.exec("UPDATE pre_sinais SET status=?, atualizado_por=?, atualizado_em=? WHERE id=?", (status, ator, iso(agora()), sinal_id))
    db.auditar(ator, "pre.sinal.status", "sinal", sinal_id, {"status": status, "justificativa": justificativa})
    return recalcular(db, s["cnpj"])


def revisar(db, cnpj, decisao, justificativa, ator):
    emp = db.um("SELECT * FROM pre_empresas WHERE cnpj=?", (cnpj_limpar(cnpj),))
    if not emp:
        raise LookupError("empresa não encontrada")
    if decisao not in ("ANALISE_CONFIRMADA", "ALERTA_DESCARTADO"):
        raise ValueError("decisão inválida")
    if len((justificativa or "").strip()) < 10:
        raise ValueError("justificativa obrigatória (mínimo 10 caracteres)")
    db.exec("INSERT INTO pre_revisoes(cnpj,faixa,score,decisao,justificativa,analista,decidido_em) VALUES(?,?,?,?,?,?,?)",
            (emp["cnpj"], emp["faixa"], emp["score"], decisao, justificativa.strip(), ator, iso(agora())))
    db.exec("UPDATE pre_empresas SET revisao_status=?, revisao_faixa=? WHERE cnpj=?", (decisao, emp["faixa"], emp["cnpj"]))
    db.auditar(ator, "pre.revisao", "empresa", emp["cnpj"], {"decisao": decisao, "faixa": emp["faixa"]})


# ------------------------------------------------------------ busca automática na CVM (seções 3.1, 5.1 e 10.1)
URL_IPE = "https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/IPE/DADOS/ipe_cia_aberta_{ano}.zip"
CATEGORIAS_IPE = {"Fato Relevante", "Comunicado ao Mercado", "Assembleia", "Aviso aos Acionistas", "Reunião da Administração"}

# categoria do guia, sinal sugerido e expressões (dicionário textual da seção 5.1)
REGRAS_CVM = [  # a ordem importa: ajuste de índices e waiver é covenant, não default
    ("DESCUMPRIMENTO_COVENANT", "DESCUMPRIMENTO_COVENANT", ["waiver", "covenant", "indices financeiros", "indice financeiro", "nao observancia",
                                                             "nao declaracao de vencimento antecipado", "nao declarar o vencimento antecipado"]),
    ("DEFAULT_FINANCEIRO", "DEFAULT_FINANCEIRO", ["default", "inadimplemento", "inadimplencia", "vencimento antecipado", "nao pagamento", "evento de inadimplemento"]),
    ("RENEGOCIACAO_DIVIDA", "COMUNICADO_REESTRUTURACAO", ["reestruturacao financeira", "reestruturacao de divida", "reestruturacao do passivo",
                                                           "reestruturacao de dividas", "alternativas de reestruturacao", "renegociacao de divida",
                                                           "renegociacao de dividas", "standstill", "assessor financeiro para reestruturacao"]),
    ("CONTINUIDADE_OPERACIONAL", "CONTINUIDADE_OPERACIONAL", ["continuidade operacional", "going concern", "risco de continuidade"]),
    ("DETERIORACAO_OPERACIONAL", "FECHAMENTO_DEMISSAO", ["fechamento de unidade", "encerramento das atividades", "paralisacao", "demissao coletiva"]),
    ("DETERIORACAO_OPERACIONAL", "PERDA_CONTRATOS", ["venda de ativos", "desinvestimento", "alienacao de ativos"]),
    ("DETERIORACAO_CONTABIL", "FLUXO_CAIXA_NEGATIVO", ["insuficiencia de caixa", "capital de giro", "restricao de liquidez", "necessidade de financiamento"]),
    ("REBAIXAMENTO_RATING", None, ["rebaixamento", "rating"]),
]


def classificar_assunto(assunto):
    t = chave_texto(assunto or "")
    if fonte_judicial(assunto):
        return None, None, []  # FORA_ESCOPO: comunicado sobre evento judicial
    for categoria, codigo, termos in REGRAS_CVM:
        achados = [x for x in termos if x in t]
        if categoria == "REBAIXAMENTO_RATING":
            achados = achados if ("rebaixamento" in t and ("rating" in t or "classificacao de risco" in t)) else []
        if achados:
            return categoria, codigo, achados
    return None, None, []


def ler_ipe(conteudo_zip):
    z = zipfile.ZipFile(io.BytesIO(conteudo_zip))
    nome = z.namelist()[0]
    return list(csv.DictReader(io.TextIOWrapper(z.open(nome), encoding="latin-1"), delimiter=";"))


def buscar_cvm(db, ator, ano=None, baixar=None, prazo=None):
    """Lê os comunicados de companhias abertas (IPE), cria candidatos a sinal por expressões do dicionário
    e inclui a companhia na lista monitorada. Candidatos não pontuam até a aprovação de um analista."""
    from .connectors.base import requisitar, FonteIndisponivel
    ano = ano or agora().year
    if baixar is None:
        def baixar(u):
            r = requisitar("GET", u, tentativas=2, timeout=40)
            if r.status_code != 200:
                raise FonteIndisponivel(f"HTTP {r.status_code}")
            return r.content
    linhas = ler_ipe(baixar(URL_IPE.format(ano=ano)))
    novos, empresas_novas, fora = 0, 0, 0
    for l in linhas:
        if prazo and time.time() > prazo:
            break
        if l.get("Categoria") not in CATEGORIAS_IPE:
            continue
        categoria, codigo, termos = classificar_assunto(l.get("Assunto"))
        if not categoria:
            continue
        cnpj = cnpj_limpar(l.get("CNPJ_Companhia"))
        protocolo = f"CVM-IPE:{l.get('Protocolo_Entrega')}:{l.get('Versao')}"
        if not cnpj_valido(cnpj) or db.um("SELECT 1 FROM pre_candidatos WHERE protocolo=?", (protocolo,)):
            continue
        if _EM_RJ.search(l.get("Nome_Companhia") or ""):
            fora += 1
            continue  # recuperação já existente: fora do escopo
        _, nova = adicionar_empresa(db, cnpj, "CVM (companhia aberta)", ator, "CNPJ_PRIMARIA", razao_social=l.get("Nome_Companhia"))
        empresas_novas += int(nova)
        db.exec("INSERT INTO pre_candidatos(cnpj,razao_social,fonte,protocolo,categoria_fonte,assunto,data_evento,url,categoria_sugerida,"
                "codigo_sugerido,termos,status,coletado_em) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (cnpj, l.get("Nome_Companhia"), "CVM IPE", protocolo, l.get("Categoria"), (l.get("Assunto") or "").strip(),
                 iso(parse_data(l.get("Data_Entrega"))), l.get("Link_Download"), categoria, codigo, db.dump(termos), "PENDENTE", iso(agora())))
        novos += 1
    db.auditar(ator, "pre.cvm.buscar", "fonte", "CVM IPE", {"ano": ano, "novos": novos})
    return {"linhas_lidas": len(linhas), "candidatos_novos": novos, "empresas_novas": empresas_novas, "ignorados_fora_escopo": fora}


def decidir_candidato(db, cid, aprovar, ator, justificativa, codigo=None, confianca="PRIMARIA", materialidade="MEDIA"):
    c = db.um("SELECT * FROM pre_candidatos WHERE id=?", (cid,))
    if not c or c["status"] != "PENDENTE":
        raise LookupError("candidato inexistente ou já decidido")
    if len((justificativa or "").strip()) < 10:
        raise ValueError("justificativa obrigatória (mínimo 10 caracteres)")
    sid = None
    if aprovar:
        sid = registrar_sinal(db, c["cnpj"], codigo or c["codigo_sugerido"], confianca, materialidade, c["data_evento"],
                              f"CVM | {c['categoria_fonte']}", c["url"], c["assunto"], ator,
                              descricao=f"Aprovado a partir da CVM: {justificativa.strip()}")
    db.exec("UPDATE pre_candidatos SET status=?, decidido_por=?, decidido_em=?, justificativa=?, sinal_id=? WHERE id=?",
            ("APROVADO" if aprovar else "DESCARTADO", ator, iso(agora()), justificativa.strip(), sid, cid))
    db.auditar(ator, "pre.candidato.decidir", "candidato", cid, {"aprovar": aprovar})
    return sid


# ------------------------------------------------------------ leitura para o painel
def resumo_empresa(db, e):
    calc = db.js(e.get("calculo"), {}) or {}
    return {"cnpj": e["cnpj"], "cnpj_formatado": cnpj_formatar(e["cnpj"]), "razao_social": e["razao_social"], "uf": e["uf"],
            "municipio": e["municipio"], "origem": e["origem"], "score": e["score"], "faixa": faixa(e["score"] or 0),
            "tendencia": e["tendencia"], "dimensoes": calc.get("dimensoes", []), "revisao_status": e["revisao_status"],
            "confianca_identidade": e["confianca_identidade"], "alerta_bloqueado": calc.get("alerta_bloqueado"),
            "fora_escopo": e["fora_escopo"], "sinais_ativos": sum(1 for f in calc.get("fatores", []) if f.get("pontos")),
            "candidatos": db.um("SELECT COUNT(*) n FROM pre_candidatos WHERE cnpj=? AND status='PENDENTE'", (e["cnpj"],))["n"]}


def detalhe(db, cnpj):
    e = db.um("SELECT * FROM pre_empresas WHERE cnpj=?", (cnpj_limpar(cnpj),))
    if not e:
        return None
    out = resumo_empresa(db, e)
    out.update({"cadastro": {k: e[k] for k in ("nome_fantasia", "cnae", "porte", "situacao_cadastral")},
                "evidencia_identidade": IDENTIDADE.get(e["evidencia_identidade"], (None, e["evidencia_identidade"]))[1],
                "calculo": db.js(e["calculo"], {}), "sinais": _sinais(db, e["cnpj"]),
                "candidatos": db.todos("SELECT * FROM pre_candidatos WHERE cnpj=? ORDER BY data_evento DESC", (e["cnpj"],)),
                "revisoes": db.todos("SELECT * FROM pre_revisoes WHERE cnpj=? ORDER BY id DESC", (e["cnpj"],))})
    return out


def referencias():
    """Tabelas do guia exibidas na aba Metodologia."""
    return {"catalogo": [{"codigo": k, "descricao": v[0], "peso": v[1], "validade": v[2], "fonte_minima": v[3], "dimensao": DIMENSOES[v[4]]}
                         for k, v in CATALOGO.items()],
            "faixas": [{"inicio": f[0], "codigo": f[1], "nome": f[2], "linguagem": f[3], "acao": f[4]} for f in reversed(FAIXAS)],
            "confianca": {k: {"valor": v[0], "nome": v[1]} for k, v in CONFIANCA_FONTE.items()},
            "materialidade": {k: {"valor": v[0], "nome": v[1]} for k, v in MATERIALIDADE.items()},
            "identidade": {k: {"valor": v[0], "nome": v[1]} for k, v in IDENTIDADE.items()},
            "dimensoes": DIMENSOES, "versao": VERSAO_FORMULA, "aviso": AVISO}
