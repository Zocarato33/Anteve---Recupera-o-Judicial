"""API e painel. Perfis: admin, analista, comercial, leitor. Toda consulta sensível e toda
exportação ficam registradas na auditoria."""
import csv
import io
import os
import statistics

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel

from . import orchestrator, pipeline, scoring, tpu as tpu_mod
from .config import CONFIG
from .connectors import cnpj as cnpj_conn
from .connectors.base import FonteIndisponivel
from .db import DB, PAPEIS
from .normalize import agora, cnj_formatar, cnpj_formatar, cnpj_limpar, cnpj_valido, iso, parse_data
from . import notifier

db = DB(CONFIG.db_path)
app = FastAPI(title="Antevê", version="1.0.0", description="Radar de recuperações judiciais")
_agendador = None

if CONFIG.token_admin and not db.usuario_por_token(CONFIG.token_admin):
    db.criar_usuario("Administrador", "admin", CONFIG.token_admin)

_IPS_LOCAIS = {"127.0.0.1", "::1"}


def ip_cliente(request: Request):
    if CONFIG.confiar_proxy:
        encaminhado = request.headers.get("x-forwarded-for") or request.headers.get("x-real-ip")
        if encaminhado:
            return encaminhado.split(",")[0].strip()
    return request.client.host if request.client else ""


@app.middleware("http")
async def restringir_ip(request: Request, chamar):
    if CONFIG.ips_permitidos and not request.url.path.startswith("/api/cron/"):
        ip = ip_cliente(request)
        if ip not in CONFIG.ips_permitidos and ip not in _IPS_LOCAIS:
            return JSONResponse({"detail": "acesso restrito à rede SBK"}, status_code=403)
    return await chamar(request)


def usuario(x_token: str = Header(default=None)):
    u = db.usuario_por_token(x_token)
    if not u:
        raise HTTPException(401, "token ausente ou inválido")
    return u


def exige(permissao):
    def dep(u=Depends(usuario)):
        if permissao not in PAPEIS.get(u["papel"], set()):
            raise HTTPException(403, f"perfil {u['papel']} sem permissão '{permissao}'")
        return u
    return dep


def _proc_publico(p, detalhado=False):
    p = dict(p)
    for campo in ("assuntos", "motivos", "inconsistencias"):
        p[campo] = db.js(p.get(campo), [])
    p["empresas"] = [dict(e, cnpj_formatado=cnpj_formatar(e["cnpj"])) for e in db.todos(
        "SELECT e.cnpj, e.raiz_cnpj, e.razao_social, e.nome_fantasia, e.aliases, e.municipio, e.uf, e.porte, e.cnae, "
        "e.situacao_cadastral, pe.papel, pe.polo FROM processo_empresas pe JOIN empresas e ON e.id=pe.empresa_id WHERE pe.processo_id=?", (p["id"],))]
    dtd, dta, dtf = parse_data(p.get("data_descoberta")), parse_data(p.get("data_ajuizamento")), parse_data(p.get("data_disponivel_fonte"))
    p["latencia_judicial_h"] = round((dtd - dta).total_seconds() / 3600, 1) if dtd and dta else None
    p["latencia_fonte_h"] = round((dtd - dtf).total_seconds() / 3600, 1) if dtd and dtf and dtd >= dtf else None
    op = db.um("SELECT * FROM oportunidades WHERE processo_id=? AND tipo='CONFIRMADO'", (p["id"],))
    p["oportunidade"] = dict(op, historico=db.js(op["historico"], [])) if op else None
    if detalhado:
        p["evidencias"] = db.todos("SELECT * FROM evidencias WHERE processo_id=? ORDER BY id", (p["id"],))
        p["eventos"] = db.todos("SELECT * FROM eventos WHERE processo_id=? ORDER BY data_evento", (p["id"],))
        p["historico"] = db.todos("SELECT * FROM historico_processo WHERE processo_id=? ORDER BY id DESC LIMIT 50", (p["id"],))
        p["revisoes"] = db.todos("SELECT * FROM revisoes WHERE processo_id=? ORDER BY id DESC", (p["id"],))
        p["ia"] = db.todos("SELECT modelo, versao_prompt, hash_entrada, aceita, rejeicoes, ts FROM ia_execucoes WHERE processo_id=?", (p["id"],))
    return p


# ------------------------------------------------------------ painel
@app.get("/", include_in_schema=False)
def painel():
    return FileResponse(os.path.join(os.path.dirname(__file__), "static", "index.html"))


@app.get("/api/eu")
def eu(u=Depends(usuario)):
    return {"nome": u["nome"], "papel": u["papel"], "permissoes": sorted(PAPEIS[u["papel"]])}


@app.get("/api/processos")
def listar(status: str = None, tipo: str = None, uf: str = None, tribunal: str = None, idade: str = None,
           prioridade: str = None, q: str = None, camada: str = Query("rj", pattern="^(rj|todos|outros)$"),
           limite: int = 300, u=Depends(exige("ler"))):
    sql, par = "SELECT * FROM processos WHERE status != 'DESCARTADO'", []
    if camada == "rj":
        sql += " AND tipo_evento LIKE 'RJ_%'"
    elif camada == "outros":
        sql += " AND tipo_evento NOT LIKE 'RJ_%'"
    for campo, valor in (("status", status), ("tipo_evento", tipo), ("uf", uf), ("tribunal", tribunal),
                         ("idade", idade), ("prioridade", prioridade)):
        if valor:
            sql += f" AND {campo}=?"
            par.append(valor.upper())
    if q:
        sql += " AND (numero_cnj LIKE ? OR vara LIKE ? OR id IN (SELECT pe.processo_id FROM processo_empresas pe JOIN empresas e "
        sql += "ON e.id=pe.empresa_id WHERE e.razao_social LIKE ? OR e.cnpj LIKE ?))"
        par += [f"%{q}%"] * 3 + [f"%{cnpj_limpar(q)}%"]
    sql += " ORDER BY CASE prioridade WHEN 'URGENTE' THEN 0 WHEN 'ALTA' THEN 1 WHEN 'MEDIA' THEN 2 ELSE 3 END, data_ajuizamento DESC LIMIT ?"
    par.append(min(limite, 2000))
    return [_proc_publico(p) for p in db.todos(sql, par)]


@app.get("/api/processos/{numero}")
def detalhe(numero: str, u=Depends(exige("ler"))):
    p = db.um("SELECT * FROM processos WHERE numero_cnj=?", (cnj_formatar(numero) or numero,))
    if not p:
        raise HTTPException(404, "processo não encontrado")
    db.auditar(u["nome"], "processo.consultar", "processo", p["numero_cnj"])
    return _proc_publico(p, detalhado=True)


class Identidade(BaseModel):
    cnpj: str
    razao_social: str | None = None
    polo: str = "ATIVO"
    papel: str = "REQUERENTE"
    evidencia_url: str
    justificativa: str | None = None
    consultar_cadastro: bool = True


@app.post("/api/processos/{numero}/identidade")
def definir_identidade(numero: str, body: Identidade, u=Depends(exige("revisar"))):
    p = db.um("SELECT * FROM processos WHERE numero_cnj=?", (cnj_formatar(numero) or numero,))
    if not p:
        raise HTTPException(404, "processo não encontrado")
    if not cnpj_valido(body.cnpj):
        raise HTTPException(422, "CNPJ inválido")
    cadastro = None
    if body.consultar_cadastro:
        try:
            cadastro = cnpj_conn.consultar(body.cnpj)
        except (FonteIndisponivel, ValueError):
            cadastro = None
    try:
        pipeline.vincular_empresa(db, p["id"], body.cnpj, body.razao_social, body.polo, body.papel, body.evidencia_url,
                                  fonte=f"revisão humana ({u['nome']})", nivel="A", ator=u["nome"], cadastro=cadastro)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    return _proc_publico(db.um("SELECT * FROM processos WHERE id=?", (p["id"],)), detalhado=True)


@app.get("/api/cnpj/{cnpj}")
def consultar_cnpj(cnpj: str, u=Depends(exige("revisar"))):
    if not cnpj_valido(cnpj):
        raise HTTPException(422, "CNPJ inválido")
    try:
        return cnpj_conn.consultar(cnpj) or {}
    except FonteIndisponivel as exc:
        raise HTTPException(503, f"cadastro indisponível: {exc}")


class Decisao(BaseModel):
    decisao: str  # CONFIRMAR | DESCARTAR | MANTER_PROVISORIO | APROVAR_PREVENTIVO | REJEITAR_PREVENTIVO
    justificativa: str


@app.get("/api/revisoes")
def revisoes(status: str = "PENDENTE", fila: str = None, u=Depends(exige("revisar"))):
    sql, par = "SELECT r.*, p.numero_cnj, p.tribunal, p.vara, p.classe_nome, p.data_ajuizamento FROM revisoes r " \
               "LEFT JOIN processos p ON p.id=r.processo_id WHERE r.status=?", [status.upper()]
    if fila:
        sql += " AND r.fila=?"
        par.append(fila.upper())
    return db.todos(sql + " ORDER BY r.id DESC LIMIT 5000", par)


@app.post("/api/revisoes/{rid}/decidir")
def decidir(rid: int, body: Decisao, u=Depends(exige("revisar"))):
    r = db.um("SELECT * FROM revisoes WHERE id=?", (rid,))
    if not r or r["status"] != "PENDENTE":
        raise HTTPException(404, "revisão inexistente ou já decidida")
    if len(body.justificativa.strip()) < 10:
        raise HTTPException(422, "justificativa obrigatória (mínimo 10 caracteres)")
    validas = {"CLASSIFICACAO": {"CONFIRMAR", "DESCARTAR", "MANTER_PROVISORIO"},
               "IDENTIDADE": {"DESCARTAR", "MANTER_PROVISORIO"},
               "PREVENTIVO": {"APROVAR_PREVENTIVO", "REJEITAR_PREVENTIVO"}}
    if body.decisao not in validas.get(r["fila"], set()):
        raise HTTPException(422, f"decisão inválida para a fila {r['fila']}")
    if body.decisao == "MANTER_PROVISORIO":
        db.exec("UPDATE revisoes SET justificativa=?, revisor=? WHERE id=?", (body.justificativa, u["nome"], rid))
    else:
        db.exec("UPDATE revisoes SET status='DECIDIDA', decisao=?, justificativa=?, revisor=?, decidido_em=? WHERE id=?",
                (body.decisao, body.justificativa, u["nome"], iso(agora()), rid))
    db.auditar(u["nome"], "revisao.decidir", "revisao", rid, {"decisao": body.decisao, "justificativa": body.justificativa})
    if r["fila"] == "PREVENTIVO":
        sc = db.um("SELECT * FROM scores WHERE cnpj=?", (r["cnpj"],))
        if body.decisao == "APROVAR_PREVENTIVO" and sc:
            db.exec("UPDATE scores SET revisado=1, revisado_por=? WHERE cnpj=?", (u["nome"], r["cnpj"]))
            notifier.disparar_preventivo(db, r["cnpj"], {"score": sc["score"], "faixa": sc["faixa"], "fatores": db.js(sc["fatores"], {})})
    elif r["processo_id"] and body.decisao != "MANTER_PROVISORIO":
        if body.decisao == "DESCARTAR" and r["fila"] == "IDENTIDADE":
            db.exec("UPDATE revisoes SET status='DECIDIDA', decisao='DESCARTAR' WHERE processo_id=? AND fila='CLASSIFICACAO' AND status='PENDENTE'",
                    (r["processo_id"],))
            db.exec("INSERT INTO revisoes(processo_id,fila,motivo,status,decisao,justificativa,revisor,criado_em,decidido_em) "
                    "VALUES(?, 'CLASSIFICACAO', 'descartado na revisão de identidade', 'DECIDIDA', 'DESCARTAR', ?, ?, ?, ?)",
                    (r["processo_id"], body.justificativa, u["nome"], iso(agora()), iso(agora())))
        pipeline.reprocessar(db, r["processo_id"], u["nome"])
    return {"ok": True}


class Correcao(BaseModel):
    tipo: str  # DUPLICIDADE | ERRO | ENCERRAMENTO | IDENTIDADE_INCORRETA | CONTESTACAO_EMPRESA
    descricao: str
    solicitante: str | None = None


@app.post("/api/correcoes/{alvo}")
def corrigir(alvo: str, body: Correcao, u=Depends(exige("ler"))):
    tipos = {"DUPLICIDADE", "ERRO", "ENCERRAMENTO", "IDENTIDADE_INCORRETA", "CONTESTACAO_EMPRESA"}
    if body.tipo not in tipos:
        raise HTTPException(422, f"tipo deve ser um de {sorted(tipos)}")
    alvo_tipo = "cnpj" if cnpj_valido(alvo) else "processo"
    db.exec("INSERT INTO correcoes(alvo_tipo,alvo,tipo,descricao,solicitante,status,criado_em) VALUES(?,?,?,?,?, 'ABERTA', ?)",
            (alvo_tipo, cnpj_limpar(alvo) if alvo_tipo == "cnpj" else (cnj_formatar(alvo) or alvo), body.tipo, body.descricao,
             body.solicitante or u["nome"], iso(agora())))
    p = db.um("SELECT id FROM processos WHERE numero_cnj=?", (cnj_formatar(alvo) or alvo,))
    if p:
        db.exec("INSERT INTO revisoes(processo_id,fila,motivo,status,criado_em) VALUES(?, 'CLASSIFICACAO', ?, 'PENDENTE', ?)",
                (p["id"], f"correção solicitada ({body.tipo}): {body.descricao}", iso(agora())))
    db.auditar(u["nome"], "correcao.abrir", alvo_tipo, alvo, body.model_dump())
    return {"ok": True}


@app.get("/api/correcoes")
def listar_correcoes(u=Depends(exige("revisar"))):
    return db.todos("SELECT * FROM correcoes ORDER BY id DESC LIMIT 300")


class Sinal(BaseModel):
    cnpj: str
    tipo: str
    nivel: str
    fonte: str
    url: str
    descricao: str | None = None
    data_sinal: str


@app.post("/api/sinais")
def novo_sinal(body: Sinal, u=Depends(exige("preventivo"))):
    try:
        return pipeline.registrar_sinal(db, body.cnpj, body.tipo, body.nivel, body.fonte, body.url, body.descricao,
                                        body.data_sinal, u["nome"])
    except ValueError as exc:
        raise HTTPException(422, str(exc))


@app.get("/api/preventivo")
def preventivo(u=Depends(exige("preventivo"))):
    db.auditar(u["nome"], "preventivo.consultar", "scores", None)
    linhas = db.todos("SELECT s.*, e.razao_social, e.uf FROM scores s LEFT JOIN empresas e ON e.cnpj=s.cnpj ORDER BY s.score DESC")
    for l in linhas:
        l["fatores"] = db.js(l["fatores"], {})
        l["cnpj_formatado"] = cnpj_formatar(l["cnpj"])
        l["aviso"] = scoring.AVISO
        l["rj_confirmada"] = bool(db.um("SELECT 1 FROM processo_empresas pe JOIN empresas e ON e.id=pe.empresa_id JOIN processos p "
                                        "ON p.id=pe.processo_id WHERE e.cnpj=? AND p.pedido_confirmado=1", (l["cnpj"],)))
    return linhas


@app.get("/api/catalogo-sinais")
def catalogo(u=Depends(exige("ler"))):
    return {"positivos": {k: {"peso": v[0], "validade": v[1], "descricao": v[2]} for k, v in scoring.CATALOGO.items()},
            "negativos": {k: {"peso": v[0], "validade": v[1], "descricao": v[2]} for k, v in scoring.NEGATIVOS.items()}}


class Funil(BaseModel):
    responsavel: str | None = None
    status_funil: str | None = None  # NOVA | EM_ANALISE | CONTATO_AUTORIZADO | CONTATADA | PROPOSTA | GANHA | PERDIDA | ENCERRADA
    registro_contato: str | None = None
    motivo_encerramento: str | None = None


@app.post("/api/oportunidades/{oid}")
def atualizar_funil(oid: int, body: Funil, u=Depends(exige("comercial"))):
    op = db.um("SELECT o.*, p.contato_bloqueado FROM oportunidades o JOIN processos p ON p.id=o.processo_id WHERE o.id=?", (oid,))
    if not op:
        raise HTTPException(404, "oportunidade não encontrada")
    if body.status_funil in ("CONTATO_AUTORIZADO", "CONTATADA", "PROPOSTA") and op["contato_bloqueado"]:
        raise HTTPException(409, "contato bloqueado: identidade não verificada, revisão pendente ou opt out")
    hist = db.js(op["historico"], [])
    evento = {"ts": iso(agora()), "por": u["nome"], **{k: v for k, v in body.model_dump().items() if v}}
    hist.append(evento)
    db.exec("UPDATE oportunidades SET responsavel=COALESCE(CAST(? AS TEXT),responsavel), status_funil=COALESCE(CAST(? AS TEXT),status_funil), "
            "ultimo_contato=CASE WHEN CAST(? AS TEXT) IS NOT NULL THEN CAST(? AS TEXT) ELSE ultimo_contato END, "
            "motivo_encerramento=COALESCE(CAST(? AS TEXT),motivo_encerramento), "
            "historico=?, atualizado_em=? WHERE id=?",
            (body.responsavel, body.status_funil, body.registro_contato, iso(agora()), body.motivo_encerramento,
             db.dump(hist), iso(agora()), oid))
    db.auditar(u["nome"], "funil.atualizar", "oportunidade", oid, evento)
    return {"ok": True}


class OptOut(BaseModel):
    cnpj: str
    motivo: str
    solicitante: str | None = None


@app.post("/api/optout")
def optout(body: OptOut, u=Depends(exige("ler"))):
    if not cnpj_valido(body.cnpj):
        raise HTTPException(422, "CNPJ inválido")
    c = cnpj_limpar(body.cnpj)
    db.exec("INSERT OR REPLACE INTO opt_out(cnpj,motivo,solicitante,ts) VALUES(?,?,?,?)", (c, body.motivo, body.solicitante or u["nome"], iso(agora())))
    for p in db.todos("SELECT pe.processo_id FROM processo_empresas pe JOIN empresas e ON e.id=pe.empresa_id WHERE e.cnpj=?", (c,)):
        db.exec("UPDATE processos SET contato_bloqueado=1 WHERE id=?", (p["processo_id"],))
        db.exec("UPDATE oportunidades SET opt_out=1 WHERE processo_id=?", (p["processo_id"],))
    db.auditar(u["nome"], "optout.registrar", "empresa", c, {"motivo": body.motivo})
    return {"ok": True}


@app.get("/api/alertas")
def alertas(u=Depends(exige("ler"))):
    linhas = db.todos("SELECT * FROM alertas WHERE canal='painel' ORDER BY id DESC LIMIT 200")
    perm = PAPEIS[u["papel"]]
    saida = []
    for a in linhas:
        if a["tipo"] == "PREVENTIVO" and "preventivo" not in perm:
            continue
        a["corpo"] = db.js(a["corpo"], {})
        saida.append(a)
    return saida


class Preferencias(BaseModel):
    tribunais: str | None = None
    ufs: str | None = None
    eventos: str | None = None
    canais: str | None = None
    frequencia: str = "IMEDIATA"
    email: str | None = None
    webhook_url: str | None = None
    slack_url: str | None = None
    teams_url: str | None = None
    incluir_preventivo: bool = False


@app.get("/api/preferencias")
def ver_pref(u=Depends(usuario)):
    return db.um("SELECT * FROM preferencias WHERE usuario_id=?", (u["id"],)) or {}


@app.post("/api/preferencias")
def salvar_pref(body: Preferencias, u=Depends(usuario)):
    d = body.model_dump()
    if d["incluir_preventivo"] and "preventivo" not in PAPEIS[u["papel"]]:
        d["incluir_preventivo"] = False
    db.exec("INSERT OR REPLACE INTO preferencias(usuario_id,tribunais,ufs,eventos,canais,frequencia,email,webhook_url,slack_url,teams_url,incluir_preventivo)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?)", (u["id"], d["tribunais"], d["ufs"], d["eventos"], d["canais"], d["frequencia"],
                                               d["email"], d["webhook_url"], d["slack_url"], d["teams_url"], int(d["incluir_preventivo"])))
    db.auditar(u["nome"], "preferencias.salvar", "usuario", u["id"], {k: v for k, v in d.items() if "url" not in k})
    return {"ok": True}


@app.get("/api/fontes")
def fontes(u=Depends(exige("ler"))):
    return {"saude": db.todos("SELECT * FROM saude_fontes ORDER BY fonte, tribunal"),
            "cursores": db.todos("SELECT * FROM cursores ORDER BY tribunal"),
            "execucoes": [dict(e, resumo=db.js(e["resumo"], {})) for e in db.todos("SELECT * FROM execucoes ORDER BY id DESC LIMIT 20")],
            "tpu": {k: v for k, v in tpu_mod.carregar(db).items() if k != "tabelas"}}


class Coleta(BaseModel):
    tribunais: list[str] | None = None
    modo: str = "incremental"
    dias: int | None = None


@app.post("/api/coleta")
def coletar(body: Coleta, u=Depends(exige("administrar"))):
    trib = [t.lower() for t in (body.tribunais or CONFIG.tribunais)]
    db.auditar(u["nome"], "coleta.executar", "sistema", None, body.model_dump())
    if body.modo == "incremental":
        return orchestrator.ciclo(db, trib)
    return [orchestrator.coletar_tribunal(db, t, modo="reconciliacao", dias=body.dias) for t in trib]


@app.post("/api/tpu/sincronizar")
def sync_tpu(u=Depends(exige("administrar"))):
    return tpu_mod.sincronizar(db)


class Amostra(BaseModel):
    numeros_cnj: list[str]
    origem: str


@app.post("/api/controle")
def amostra(body: Amostra, u=Depends(exige("administrar"))):
    n = 0
    for x in body.numeros_cnj:
        f = cnj_formatar(x)
        if f:
            db.exec("INSERT OR IGNORE INTO amostra_controle(numero_cnj,origem,incluido_em) VALUES(?,?,?)", (f, body.origem, iso(agora())))
            n += 1
    return {"incluidos": n}


def _pct(v):
    return round(v * 100, 1) if v is not None else None


@app.get("/api/metricas")
def metricas(u=Depends(exige("ler"))):
    tot_ctrl = db.um("SELECT COUNT(*) n FROM amostra_controle")["n"]
    achados = db.um("SELECT COUNT(*) n FROM amostra_controle a JOIN processos p ON p.numero_cnj=a.numero_cnj AND p.pedido_confirmado=1")["n"]
    classificados = db.um("SELECT COUNT(*) n FROM processos WHERE pedido_confirmado=1")["n"]
    descart_humano = db.um("SELECT COUNT(DISTINCT processo_id) n FROM revisoes WHERE fila='CLASSIFICACAO' AND decisao='DESCARTAR'")["n"]
    decididas = db.um("SELECT COUNT(DISTINCT processo_id) n FROM revisoes WHERE fila='CLASSIFICACAO' AND status='DECIDIDA'")["n"]
    primeira = db.um("SELECT MIN(inicio) t FROM execucoes")["t"]
    lat = []
    for p in db.todos("SELECT data_descoberta, data_disponivel_fonte FROM processos WHERE pedido_confirmado=1"):
        d, f = parse_data(p["data_descoberta"]), parse_data(p["data_disponivel_fonte"])
        if d and f and primeira and f >= parse_data(primeira) and d >= f:
            lat.append((d - f).total_seconds() / 3600)
    lat_jud = []
    for p in db.todos("SELECT data_descoberta, data_ajuizamento FROM processos WHERE pedido_confirmado=1 AND idade IN ('NOVO','RECENTE')"):
        d, a = parse_data(p["data_descoberta"]), parse_data(p["data_ajuizamento"])
        if d and a:
            lat_jud.append((d - a).total_seconds() / 3600)
    brutos = db.um("SELECT COUNT(*) n FROM registros_brutos")["n"]
    procs = db.um("SELECT COUNT(*) n FROM processos")["n"]
    dup_err = db.um("SELECT COUNT(*) n FROM correcoes WHERE tipo='DUPLICIDADE'")["n"]
    alert_proc = db.todos("SELECT DISTINCT processo_id FROM alertas WHERE processo_id IS NOT NULL")
    rastreaveis = sum(1 for a in alert_proc if db.um(
        "SELECT 1 FROM evidencias WHERE processo_id=? AND fonte IS NOT NULL AND url IS NOT NULL AND versao_regra IS NOT NULL", (a["processo_id"],)))

    def pctl(v, q):
        if not v:
            return None
        v = sorted(v)
        return round(v[min(len(v) - 1, int(q * len(v)))], 1)
    return {
        "cobertura": {"valor": _pct(achados / tot_ctrl) if tot_ctrl else None, "meta": ">= 95%", "amostra": tot_ctrl, "achados": achados},
        "precisao": {"valor": _pct(1 - descart_humano / classificados) if classificados and decididas else None, "meta": ">= 98%",
                     "decisoes_humanas": decididas,
                     "classificados": classificados, "descartados_em_revisao": descart_humano},
        "latencia_fonte_h": {"p50": pctl(lat, .5), "p95": pctl(lat, .95), "meta": "P50 <= 2 h; P95 <= 24 h", "amostras": len(lat)},
        "latencia_judicial_h": {"p50": pctl(lat_jud, .5), "p95": pctl(lat_jud, .95), "media": round(statistics.mean(lat_jud), 1) if lat_jud else None,
                                "observacao": "tempo entre ajuizamento e descoberta; inclui o atraso de envio dos tribunais ao DataJud"},
        "deduplicacao": {"valor": _pct(1 - dup_err / procs) if procs else None, "meta": ">= 99%", "registros_brutos": brutos, "processos_unicos": procs},
        "rastreabilidade": {"valor": _pct(rastreaveis / len(alert_proc)) if alert_proc else None, "meta": "100%"},
        "por_status": db.todos("SELECT status, COUNT(*) n FROM processos GROUP BY status"),
        "por_tipo": db.todos("SELECT tipo_evento, COUNT(*) n FROM processos GROUP BY tipo_evento"),
        "revisoes_pendentes": db.todos("SELECT fila, COUNT(*) n FROM revisoes WHERE status='PENDENTE' GROUP BY fila"),
    }


@app.get("/api/auditoria")
def auditoria(u=Depends(exige("administrar"))):
    return db.todos("SELECT * FROM auditoria ORDER BY id DESC LIMIT 500")


@app.get("/api/exportar.csv")
def exportar(u=Depends(exige("exportar"))):
    """Exporta apenas RJ confirmadas. Preventivos nunca saem em lista (seção 4.2); opt out é respeitado."""
    linhas = db.todos("SELECT * FROM processos WHERE pedido_confirmado=1 AND status IN ('CONFIRMADO','ATUALIZADO') AND tipo_evento LIKE 'RJ_%'")
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(["numero_cnj", "tribunal", "uf", "vara", "classe", "tipo_evento", "estagio", "data_ajuizamento", "data_descoberta",
                "razao_social", "cnpj", "confianca", "prioridade", "contato_bloqueado", "url_fonte", "versao_regra"])
    for p in linhas:
        emps = db.todos("SELECT e.razao_social, e.cnpj FROM processo_empresas pe JOIN empresas e ON e.id=pe.empresa_id WHERE pe.processo_id=?", (p["id"],))
        emps = [e for e in emps if not db.um("SELECT 1 FROM opt_out WHERE cnpj=?", (e["cnpj"],))] or [{"razao_social": "", "cnpj": ""}]
        for e in emps:
            w.writerow([p["numero_cnj"], p["tribunal"], p["uf"], p["vara"], p["classe_nome"], p["tipo_evento"], p["estagio"],
                        p["data_ajuizamento"], p["data_descoberta"], e["razao_social"], cnpj_formatar(e["cnpj"]) or "",
                        p["confianca"], p["prioridade"], p["contato_bloqueado"], p["url_fonte"] or "", p["versao_regra"]])
    db.auditar(u["nome"], "exportar.csv", "processos", None, {"linhas": len(linhas)})
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": "attachment; filename=anteve_rj_confirmadas.csv"})


# ------------------------------------------------------------ agendamento externo (Vercel Cron, GitHub Actions)
def _cron_autorizado(request: Request):
    """Vercel Cron envia 'Authorization: Bearer <CRON_SECRET>'. Sem segredo configurado, o endpoint fica fechado."""
    if not CONFIG.cron_secret or request.headers.get("authorization") != f"Bearer {CONFIG.cron_secret}":
        raise HTTPException(401, "não autorizado")


@app.get("/api/cron/coleta")
def cron_coleta(request: Request):
    _cron_autorizado(request)
    orcamento = int(os.environ.get("ANTEVE_ORCAMENTO_S", "45"))
    return orchestrator.executar_com_orcamento(db, "incremental", orcamento_s=orcamento)


@app.get("/api/cron/reconciliacao")
def cron_reconciliacao(request: Request, dias: int = 30):
    _cron_autorizado(request)
    orcamento = int(os.environ.get("ANTEVE_ORCAMENTO_S", "45"))
    return orchestrator.executar_com_orcamento(db, "reconciliacao", dias=min(dias, 365), orcamento_s=orcamento)


@app.get("/api/saude")
def saude_publica():
    """Verificação simples para o monitoramento de disponibilidade. Não expõe dados."""
    return {"ok": True, "banco": "postgresql" if db.pg else "sqlite", "persistente": db.pg or not os.environ.get("VERCEL")}


@app.on_event("startup")
def iniciar():
    global _agendador
    tpu_mod.carregar(db)
    # No Vercel não há processo contínuo: o agendamento vem de fora (Cron ou GitHub Actions)
    if os.environ.get("ANTEVE_AGENDADOR", "0" if os.environ.get("VERCEL") else "1") == "1":
        _agendador = orchestrator.Agendador(db)
        _agendador.start()
