"""Fluxo funcional (seção 5): do registro coletado até oportunidade e alerta."""
import re
from . import notifier, rules, scoring, tpu as tpu_mod
from .config import CONFIG
from .normalize import (agora, cnj_digitos, cnpj_formatar, cnpj_limpar, cnpj_raiz, cnpj_valido, hash_obj, iso,
                        normalizar_razao_social, parse_data)

CAMPOS_HISTORICO = ["status", "estagio", "tipo_evento", "classe_codigo", "prioridade", "vara", "processo_principal"]


def url_consulta_publica(tribunal, cnj):
    """Link para a consulta pública oficial, quando o padrão do portal é conhecido."""
    if not cnj:
        return None
    if tribunal == "TJSP":
        return ("https://esaj.tjsp.jus.br/cpopg/search.do?cbPesquisa=NUMPROC&dadosConsulta.tipoNuProcesso=UNIFICADO"
                f"&numeroDigitoAnoUnificado={cnj[:15]}&foroNumeroUnificado={cnj[-4:]}"
                f"&dadosConsulta.valorConsultaNuUnificado={cnj}")
    return None


def _contexto(db, processo_id):
    ctx = {"empresas_verificadas": [], "documentos": [], "opt_out": False}
    if not processo_id:
        return ctx
    for e in db.todos("SELECT e.* FROM processo_empresas pe JOIN empresas e ON e.id=pe.empresa_id "
                      "WHERE pe.processo_id=? AND e.cnpj IS NOT NULL AND e.confianca_identidade IN ('ALTA','VERIFICADA')", (processo_id,)):
        ctx["empresas_verificadas"].append(e)
        if db.um("SELECT 1 FROM opt_out WHERE cnpj=?", (e["cnpj"],)):
            ctx["opt_out"] = True
    for ev in db.todos("SELECT * FROM evidencias WHERE processo_id=? AND tipo='PUBLICACAO_OFICIAL'", (processo_id,)):
        extra = db.js(ev["documento"], {}) or {}
        ctx["documentos"].append({"nivel": ev["nivel"], "ato": extra.get("ato")})
    return ctx


def _registrar_evidencia(db, processo_id, nivel, tipo, fonte, url, trecho, documento=None, pagina=None,
                         hash_doc=None, gerada_por_ia=0, cnpj=None):
    hash_doc = hash_doc or hash_obj([fonte, url, trecho])
    db.exec("INSERT OR IGNORE INTO evidencias(processo_id,empresa_cnpj,nivel,tipo,fonte,url,documento,pagina,trecho_resumido,"
            "coletado_em,hash_documento,gerada_por_ia,versao_regra) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (processo_id, cnpj, nivel, tipo, fonte, url, db.dump(documento) if isinstance(documento, dict) else documento,
             pagina, trecho, iso(agora()), hash_doc, gerada_por_ia, rules.VERSAO_REGRA))


def _abrir_revisao(db, processo_id, fila, motivo, cnpj=None):
    filtro = "processo_id IS ? AND cnpj IS ? AND fila=?"
    if db.um(f"SELECT 1 FROM revisoes WHERE {filtro} AND status='PENDENTE'", (processo_id, cnpj, fila)):
        db.exec(f"UPDATE revisoes SET motivo=? WHERE {filtro} AND status='PENDENTE'", (motivo, processo_id, cnpj, fila))
        return
    # não reabrir o que já foi decidido por humano com o mesmo motivo
    if db.um(f"SELECT 1 FROM revisoes WHERE {filtro} AND status='DECIDIDA' AND motivo=?", (processo_id, cnpj, fila, motivo)):
        return
    db.exec("INSERT INTO revisoes(processo_id,cnpj,fila,motivo,status,criado_em) VALUES(?,?,?,?, 'PENDENTE', ?)",
            (processo_id, cnpj, fila, motivo, iso(agora())))


def _decisao_humana(db, processo_id):
    return db.um("SELECT * FROM revisoes WHERE processo_id=? AND fila='CLASSIFICACAO' AND status='DECIDIDA' ORDER BY id DESC LIMIT 1",
                 (processo_id,))


def processar_registro(db, reg, origem="classe", ator="coletor"):
    """Processa um registro normalizado do DataJud. Idempotente por número CNJ."""
    agora_dt = agora()
    tpu = tpu_mod.carregar(db)
    h_bruto = hash_obj(reg)
    db.exec("INSERT OR IGNORE INTO registros_brutos(fonte,tribunal,id_fonte,hash,payload,coletado_em) VALUES(?,?,?,?,?,?)",
            (reg["fonte"], reg["tribunal"], reg.get("id_fonte"), h_bruto, db.dump(reg), iso(agora_dt)))

    chave = reg.get("numero_cnj") if reg.get("cnj_valido") else f"{reg['tribunal']}:{reg.get('id_fonte')}"
    conhecido = db.um("SELECT * FROM processos WHERE numero_cnj=?", (chave,))
    ctx = _contexto(db, conhecido["id"] if conhecido else None)

    res = rules.avaliar(reg, tpu["tabelas"], ctx, agora_dt, CONFIG, conhecido=conhecido, origem=origem)
    motivo_classificacao = "; ".join(res["inconsistencias"] + [r for r in res["revisao"] if "sem CNPJ" not in r])
    precisa_classificacao = bool(res["inconsistencias"]) or res["status"] in ("PROVISORIO", "CANDIDATO")

    # Decisão humana registrada prevalece sobre a regra automática para o mesmo conteúdo
    if conhecido:
        dec = _decisao_humana(db, conhecido["id"])
        if dec and dec["decisao"] == "DESCARTAR":
            res["status"] = "DESCARTADO"
            res["motivos"].append(f"descartado em revisão humana: {dec['justificativa']}")
        elif dec and dec["decisao"] == "CONFIRMAR" and res["status"] == "PROVISORIO":
            res["status"] = "CONFIRMADO"
            res["motivos"].append(f"confirmado em revisão humana: {dec['justificativa']}")
            res["revisao"] = [r for r in res["revisao"] if "sem CNPJ" in r]
            res["confianca"] = max(res["confianca"], 0.85 if ctx["empresas_verificadas"] else 0.70)

    if res["status"] == "DESCARTADO" and not conhecido and res["tipo_evento"] in ("NAO_RELACIONADO",) \
            and "sigilo" in " ".join(res["motivos"]):
        # Sigilo: não persistir metadados além do registro de exclusão
        db.auditar(ator, "processo.excluido_sigilo", "processo", chave, {})
        return {"acao": "excluido_sigilo", "numero_cnj": chave}

    # 3.3 Retificação não reinicia a idade do pedido
    data_ajuiz = reg.get("data_ajuizamento")
    if conhecido and conhecido.get("data_ajuizamento") and data_ajuiz and conhecido["data_ajuizamento"] != data_ajuiz:
        res["inconsistencias"].append(f"data de ajuizamento retificada na fonte ({data_ajuiz}); mantida a original")
        data_ajuiz = conhecido["data_ajuizamento"]

    ultimo_mov = max([m["data"] for m in reg.get("movimentos") or [] if m.get("data")] or [None], key=lambda x: x or "")
    valores = {
        "numero_cnj": chave, "id_fonte": reg.get("id_fonte"), "tribunal": reg["tribunal"], "uf": reg.get("uf"),
        "grau": reg.get("grau"), "comarca": _comarca(reg.get("vara")), "vara": reg.get("vara"),
        "classe_codigo": reg.get("classe_codigo"), "classe_nome": reg.get("classe_nome"),
        "assuntos": db.dump(reg.get("assuntos")), "data_ajuizamento": data_ajuiz,
        "data_disponivel_fonte": reg.get("data_disponivel_fonte"),
        "tipo_evento": res["tipo_evento"], "status": res["status"], "estagio": res["estagio"], "rota": res["rota"],
        "pedido_confirmado": res["pedido_confirmado"], "processamento_deferido": res["processamento_deferido"],
        "confianca": res["confianca"], "prioridade": res["prioridade"], "idade": res["idade"],
        "motivos": db.dump(res["motivos"]), "inconsistencias": db.dump(res["inconsistencias"]),
        "revisao_humana": res["revisao_humana"], "contato_bloqueado": res["contato_bloqueado"],
        "versao_regra": res["versao_regra"], "versao_tpu": tpu["versao"],
        "url_fonte": url_consulta_publica(reg["tribunal"], reg.get("numero_cnj")),
        "atualizado_em": iso(agora_dt), "ultimo_movimento_em": ultimo_mov,
    }
    if conhecido:
        pid = conhecido["id"]
        for campo in CAMPOS_HISTORICO:
            if str(conhecido.get(campo)) != str(valores.get(campo)):
                db.exec("INSERT INTO historico_processo(processo_id,campo,anterior,novo,motivo,ts) VALUES(?,?,?,?,?,?)",
                        (pid, campo, conhecido.get(campo), valores.get(campo), "reprocessamento de fonte oficial", iso(agora_dt)))
        sets = ", ".join(f"{k}=?" for k in valores if k != "numero_cnj")
        db.exec(f"UPDATE processos SET {sets} WHERE id=?", [v for k, v in valores.items() if k != "numero_cnj"] + [pid])
    else:
        valores["data_descoberta"] = iso(agora_dt)
        cols = ", ".join(valores)
        db.exec(f"INSERT INTO processos({cols}) VALUES({', '.join('?' * len(valores))})", list(valores.values()))
        pid = db.um("SELECT id FROM processos WHERE numero_cnj=?", (chave,))["id"]
        db.auditar(ator, "processo.criar", "processo", chave, {"status": res["status"], "tipo": res["tipo_evento"]})

    # Evidência de metadado oficial (nível B), com trilha de origem
    if res["status"] != "DESCARTADO" or conhecido:
        _registrar_evidencia(db, pid, "B", "METADADO_OFICIAL", "DataJud",
                             f"{CONFIG.datajud_url}/api_publica_{reg['tribunal'].lower()}/_search#numeroProcesso={cnj_digitos(reg.get('numero_cnj'))}",
                             f"Classe {reg.get('classe_codigo')} {reg.get('classe_nome')}; ajuizamento {reg.get('data_ajuizamento')}; "
                             f"{len(reg.get('movimentos') or [])} movimentos públicos",
                             documento={"indexado_em": reg.get("data_disponivel_fonte"), "hash_bruto": h_bruto},
                             hash_doc=h_bruto)

    for ev in res["eventos"]:
        hev = hash_obj([chave, ev["tipo_evento"], ev["movimento_codigo"], ev["data_evento"]])
        db.exec("INSERT OR IGNORE INTO eventos(processo_id,tipo_evento,data_evento,movimento_codigo,movimento_nome,confirmado,data_descoberta,hash)"
                " VALUES(?,?,?,?,?,?,?,?)", (pid, ev["tipo_evento"], ev["data_evento"], ev["movimento_codigo"],
                                             ev["movimento_nome"], int(ev["confirmado"]), iso(agora_dt), hev))

    # Fila humana
    if precisa_classificacao:
        _abrir_revisao(db, pid, "CLASSIFICACAO", motivo_classificacao or "confirmação insuficiente")
    if any("sem CNPJ" in r for r in res["revisao"]):
        _abrir_revisao(db, pid, "IDENTIDADE", "empresa requerente sem CNPJ verificado; informar identidade com evidência")

    # Oportunidade (apenas RJ confirmada e ativa)
    _atualizar_oportunidade(db, pid, res)

    # Pedido de falência vira sinal preventivo quando a empresa é conhecida
    if res["tipo_evento"] == "PEDIDO_FALENCIA":
        for e in ctx["empresas_verificadas"]:
            registrar_sinal(db, e["cnpj"], "PEDIDO_FALENCIA_ATIVO", "B", "DataJud", valores["url_fonte"] or chave,
                            f"Processo {chave}", reg.get("data_ajuizamento"), ator, processo_cnj=chave)

    proc = db.um("SELECT * FROM processos WHERE id=?", (pid,))
    notifier.avaliar_e_notificar(db, proc, conhecido)
    return {"acao": "atualizado" if conhecido else "criado", "numero_cnj": chave, "status": res["status"],
            "tipo_evento": res["tipo_evento"], "processo_id": pid}


def _comarca(vara):
    """Heurística sobre o nome do órgão julgador (o DataJud não traz a comarca em campo próprio)."""
    if not vara:
        return None
    v = vara.upper()
    if "COMARCA DE " in v:
        return vara[v.rfind("COMARCA DE ") + 11:].strip().title()
    if " - " in vara:
        return vara.split(" - ")[0].strip().title()
    partes = vara.split(" DE ")
    return partes[-1].strip().title() if len(partes) > 1 else None


def _atualizar_oportunidade(db, pid, res):
    ts = iso(agora())
    ativa = res["tipo_evento"] in rules.TIPOS_RJ and res["status"] in ("CONFIRMADO", "ATUALIZADO") \
        and res["estagio"] not in rules.ESTAGIOS_TERMINAIS
    existente = db.um("SELECT * FROM oportunidades WHERE processo_id=? AND tipo='CONFIRMADO'", (pid,))
    if ativa and not existente:
        db.exec("INSERT INTO oportunidades(processo_id,tipo,prioridade,status_funil,historico,criado_em,atualizado_em)"
                " VALUES(?, 'CONFIRMADO', ?, 'NOVA', ?, ?, ?)",
                (pid, res["prioridade"], db.dump([{"ts": ts, "evento": "criada", "status": "NOVA"}]), ts, ts))
    elif existente:
        hist = db.js(existente["historico"], [])
        if not ativa and existente["status_funil"] != "ENCERRADA":
            hist.append({"ts": ts, "evento": "encerrada automaticamente", "motivo": res["estagio"] or res["status"]})
            db.exec("UPDATE oportunidades SET status_funil='ENCERRADA', motivo_encerramento=?, historico=?, atualizado_em=? WHERE id=?",
                    (f"processo fora do ciclo: {res['estagio'] or res['status']}", db.dump(hist), ts, existente["id"]))
        elif ativa:
            db.exec("UPDATE oportunidades SET prioridade=?, atualizado_em=? WHERE id=?", (res["prioridade"], ts, existente["id"]))


# ------------------------------------------------------------ identidade
def vincular_empresa(db, processo_id, cnpj, razao_social=None, polo="ATIVO", papel="REQUERENTE",
                     evidencia_url=None, fonte="revisão humana", nivel="A", ator="analista", cadastro=None):
    c = cnpj_limpar(cnpj)
    if not cnpj_valido(c):
        raise ValueError("CNPJ inválido (dígito verificador)")
    if not evidencia_url:
        raise ValueError("evidência obrigatória para vincular identidade")
    ts = iso(agora())
    emp = db.um("SELECT * FROM empresas WHERE cnpj=?", (c,))
    razao = normalizar_razao_social((cadastro or {}).get("razao_social") or razao_social)
    aliases = set(db.js(emp["aliases"], []) if emp else [])
    for n in (razao_social, (cadastro or {}).get("nome_fantasia")):
        n = normalizar_razao_social(n)
        if n and n != razao:
            aliases.add(n)
    dados = {"raiz_cnpj": cnpj_raiz(c), "razao_social": razao, "aliases": db.dump(sorted(aliases)),
             "confianca_identidade": "VERIFICADA", "fonte_identidade": fonte, "atualizado_em": ts}
    if cadastro:
        dados.update({k: cadastro.get(k) for k in ("nome_fantasia", "municipio", "uf", "cnae", "porte", "situacao_cadastral")})
    if emp:
        db.exec(f"UPDATE empresas SET {', '.join(f'{k}=?' for k in dados)} WHERE id=?", list(dados.values()) + [emp["id"]])
        eid = emp["id"]
    else:
        dados["cnpj"] = c
        db.exec(f"INSERT INTO empresas({', '.join(dados)}) VALUES({', '.join('?' * len(dados))})", list(dados.values()))
        eid = db.um("SELECT id FROM empresas WHERE cnpj=?", (c,))["id"]
    _registrar_evidencia(db, processo_id, nivel, "IDENTIDADE", fonte, evidencia_url,
                         f"Empresa {razao or ''} CNPJ {cnpj_formatar(c)} como {papel.lower()}", cnpj=c)
    ev = db.um("SELECT id FROM evidencias WHERE processo_id=? AND tipo='IDENTIDADE' AND empresa_cnpj=? ORDER BY id DESC", (processo_id, c))
    db.exec("INSERT OR REPLACE INTO processo_empresas(processo_id,empresa_id,polo,papel,evidencia_id) VALUES(?,?,?,?,?)",
            (processo_id, eid, polo, papel, ev["id"] if ev else None))
    qtd = db.um("SELECT COUNT(*) n FROM processo_empresas WHERE processo_id=? AND papel LIKE 'REQUERENTE%'", (processo_id,))["n"]
    db.exec("UPDATE processos SET quantidade_empresas=? WHERE id=?", (qtd, processo_id))
    db.exec("UPDATE revisoes SET status='DECIDIDA', decisao='IDENTIDADE_VINCULADA', justificativa=?, revisor=?, decidido_em=? "
            "WHERE processo_id=? AND fila='IDENTIDADE' AND status='PENDENTE'", (f"CNPJ {cnpj_formatar(c)}; evidência {evidencia_url}", ator, ts, processo_id))
    db.auditar(ator, "identidade.vincular", "processo", processo_id, {"cnpj": c, "evidencia": evidencia_url})
    reprocessar(db, processo_id, ator)
    return eid


def reprocessar(db, processo_id, ator="sistema"):
    """Reaplica as regras sobre o último registro bruto do processo (após identidade, revisão ou documento)."""
    p = db.um("SELECT * FROM processos WHERE id=?", (processo_id,))
    if not p:
        return None
    bruto = db.um("SELECT payload FROM registros_brutos WHERE tribunal=? AND id_fonte=? ORDER BY id DESC LIMIT 1",
                  (p["tribunal"], p["id_fonte"]))
    if not bruto:
        return None
    return processar_registro(db, db.js(bruto["payload"]), ator=ator)


# ------------------------------------------------------------ documentos
POLOS = {"A": "ATIVO", "ATIVO": "ATIVO", "P": "PASSIVO", "PASSIVO": "PASSIVO"}


def registrar_parte(db, processo_id, nome, polo, tipo="PARTE", oab=None, fonte="DJEN", url=None, ator="coletor-diario"):
    """Parte ou advogado do processo. Guarda só nome, polo e OAB; nenhum documento de pessoa física."""
    from .normalize import chave_texto
    nome = re.sub(r"\s+", " ", (nome or "")).strip()
    if len(nome) < 2:
        return False
    polo = POLOS.get((polo or "").strip().upper(), "OUTRO")
    antes = db.um("SELECT COUNT(*) n FROM partes WHERE processo_id=?", (processo_id,))["n"]
    db.exec("INSERT OR IGNORE INTO partes(processo_id,nome,chave,polo,tipo,oab,fonte,url,registrado_por,coletado_em) "
            "VALUES(?,?,?,?,?,?,?,?,?,?)", (processo_id, nome.upper(), chave_texto(nome), polo, tipo, oab, fonte, url, ator, iso(agora())))
    return db.um("SELECT COUNT(*) n FROM partes WHERE processo_id=?", (processo_id,))["n"] > antes


def incorporar_publicacoes(db, processo_id, publicacoes, ator="coletor-diario"):
    from . import documentos as docs
    p = db.um("SELECT * FROM processos WHERE id=?", (processo_id,))
    novos = 0
    for pub in publicacoes:
        a = docs.analisar_publicacao(pub, p["numero_cnj"])
        if not a["vinculada"]:
            continue
        for d in pub.get("destinatarios") or []:
            registrar_parte(db, processo_id, d.get("nome"), d.get("polo"), fonte=pub.get("fonte", "DJEN"), url=pub.get("url"), ator=ator)
        for adv in pub.get("advogados") or []:
            registrar_parte(db, processo_id, adv.get("nome"), "OUTRO", tipo="ADVOGADO", oab=adv.get("oab"),
                            fonte=pub.get("fonte", "DJEN"), url=pub.get("url"), ator=ator)
        antes = db.um("SELECT COUNT(*) n FROM evidencias WHERE processo_id=?", (processo_id,))["n"]
        _registrar_evidencia(db, processo_id, a["nivel"], "PUBLICACAO_OFICIAL", pub.get("fonte", "DJEN"), pub.get("url"),
                             a["resumo"], documento={"ato": a["ato"], "data": pub.get("data"), "orgao": pub.get("orgao")},
                             hash_doc=pub.get("hash"))
        novos += db.um("SELECT COUNT(*) n FROM evidencias WHERE processo_id=?", (processo_id,))["n"] - antes
        if a["administrador_judicial"]:
            db.exec("UPDATE processos SET administrador_judicial=? WHERE id=?", (a["administrador_judicial"], processo_id))
        for r in a["requerentes"]:
            if r["cnpj"] and r["papel"] == "REQUERENTE":
                try:
                    vincular_empresa(db, processo_id, r["cnpj"], r["razao_social"], evidencia_url=pub.get("url") or pub.get("hash"),
                                     fonte=pub.get("fonte", "DJEN"), nivel="B", ator=ator)
                except ValueError:
                    pass
            elif r["cnpj"] and r["papel"] == "INDEFINIDO":
                _abrir_revisao(db, processo_id, "IDENTIDADE",
                               f"CNPJ {cnpj_formatar(r['cnpj'])} encontrado na publicação sem papel inequívoco de requerente")
    if novos:
        reprocessar(db, processo_id, ator)
    return novos


# ------------------------------------------------------------ preventivo
def registrar_sinal(db, cnpj, tipo, nivel, fonte, url, descricao, data_sinal, ator, negativo=False, processo_cnj=None):
    c = cnpj_limpar(cnpj)
    if not cnpj_valido(c):
        raise ValueError("CNPJ inválido")
    if tipo not in scoring.CATALOGO and tipo not in scoring.NEGATIVOS:
        raise ValueError("tipo de sinal desconhecido")
    if not fonte or not url:
        raise ValueError("sinal exige fonte e URL identificadas")
    if db.um("SELECT 1 FROM sinais WHERE cnpj=? AND tipo=? AND url=? AND ativo=1", (c, tipo, url)):
        return recalcular_score(db, c)
    db.exec("INSERT INTO sinais(cnpj,raiz_cnpj,tipo,peso,nivel,fonte,url,descricao,data_sinal,negativo,processo_cnj,registrado_por,criado_em)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (c, cnpj_raiz(c), tipo, (scoring.NEGATIVOS.get(tipo) or scoring.CATALOGO.get(tipo))[0], (nivel or "D").upper(),
             fonte, url, descricao, iso(parse_data(data_sinal)) if data_sinal else None, int(negativo or tipo in scoring.NEGATIVOS),
             processo_cnj, ator, iso(agora())))
    db.auditar(ator, "sinal.registrar", "empresa", c, {"tipo": tipo, "fonte": fonte, "url": url})
    return recalcular_score(db, c)


def recalcular_score(db, cnpj):
    sinais = db.todos("SELECT * FROM sinais WHERE cnpj=? AND ativo=1", (cnpj,))
    r = scoring.calcular(sinais, agora(), CONFIG)
    anterior = db.um("SELECT * FROM scores WHERE cnpj=?", (cnpj,))
    revisado = anterior["revisado"] if anterior and anterior["score"] == r["score"] else 0
    db.exec("INSERT OR REPLACE INTO scores(cnpj,score,faixa,fatores,calculado_em,versao_regra,revisado,revisado_por) VALUES(?,?,?,?,?,?,?,?)",
            (cnpj, r["score"], r["faixa"], db.dump({"fatores": r["fatores"], "salvaguarda": r["salvaguarda"], "aviso": r["aviso"]}),
             iso(agora()), r["versao"], revisado, anterior["revisado_por"] if revisado else None))
    if r["faixa"] in ("RISCO_ELEVADO", "PRIORIDADE_ANALISE_HUMANA") and not revisado:
        _abrir_revisao(db, None, "PREVENTIVO", f"score {r['score']} ({r['faixa']}): revisar antes de qualquer comunicação. {scoring.AVISO}", cnpj=cnpj)
    return r
