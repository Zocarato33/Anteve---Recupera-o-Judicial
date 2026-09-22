"""Notificador (seções 9.2 e 9.3). Envia somente após os gates de qualidade.
Alertas confirmados, de atualização, preventivos e de correção usam assuntos e
cores distintos e nunca se confundem.

Observação de estilo: os assuntos usam barra vertical como separador, por norma
interna de escrita da organização."""
import smtplib
from email.mime.text import MIMEText

import requests

from .config import CONFIG
from .normalize import agora, cnpj_formatar, iso
from .rules import ESTAGIOS_TERMINAIS, TIPOS_RJ

ASSUNTOS = {
    "CONFIRMADO": "Nova recuperação judicial identificada | {empresa} | {uf}",
    "ATUALIZACAO": "Atualização de recuperação judicial | {evento} | {empresa}",
    "PREVENTIVO": "Sinal preventivo para análise | recuperação não confirmada | {empresa}",
    "CORRECAO": "Correção de alerta anterior | {empresa} | {numero_cnj}",
}

PROXIMA_ACAO = {
    "PEDIDO_DISTRIBUIDO_AGUARDANDO_DECISAO": "Validar identidade da requerente e avaliar apoio antes da decisão de processamento",
    "INDICIO_DE_DEFERIMENTO": "Confirmar o deferimento em documento oficial e identificar o administrador judicial",
    "PROCESSAMENTO_DEFERIDO": "Mapear prazos do art. 52 e preparar abordagem consultiva",
    "CONCEDIDA": "Acompanhar cumprimento do plano",
}


def _empresas(db, processo_id):
    return db.todos("SELECT e.razao_social, e.cnpj, pe.papel FROM processo_empresas pe JOIN empresas e ON e.id=pe.empresa_id "
                    "WHERE pe.processo_id=?", (processo_id,))


def montar_alerta(db, proc, tipo):
    emps = _empresas(db, proc["id"])
    nome = emps[0]["razao_social"] if emps and emps[0]["razao_social"] else "Empresa não identificada"
    evid = db.todos("SELECT fonte, nivel, url, trecho_resumido, coletado_em FROM evidencias WHERE processo_id=? ORDER BY id", (proc["id"],))
    corpo = {
        "tipo": tipo,
        "empresa": [{"razao_social": e["razao_social"], "cnpj": cnpj_formatar(e["cnpj"]), "papel": e["papel"]} for e in emps],
        "numero_cnj": proc["numero_cnj"], "tribunal": proc["tribunal"], "uf": proc["uf"], "vara": proc["vara"],
        "evento": proc["tipo_evento"], "estagio": proc["estagio"],
        "data_evento": proc["data_ajuizamento"], "data_descoberta": proc["data_descoberta"],
        "resumo": _resumo(proc, nome),
        "evidencias": evid, "link_oficial": proc["url_fonte"],
        "confianca": proc["confianca"], "divergencias": db.js(proc["inconsistencias"], []),
        "contato_bloqueado": bool(proc["contato_bloqueado"]),
        "proxima_acao": PROXIMA_ACAO.get(proc["estagio"], "Analisar evidências e atualizar o funil"),
        "classificacao_sujeita_a_validacao_juridica": True,
    }
    assunto = ASSUNTOS[tipo].format(empresa=nome, uf=proc["uf"] or "", evento=(proc["tipo_evento"] or "").replace("_", " ").lower(),
                                    numero_cnj=proc["numero_cnj"])
    return assunto, corpo


def _resumo(proc, nome):
    base = f"Pedido de recuperação judicial identificado em fonte oficial: processo {proc['numero_cnj']} no {proc['tribunal']}"
    if proc["vara"]:
        base += f", {proc['vara']}"
    base += f". Estágio: {(proc['estagio'] or '').replace('_', ' ').lower()}."
    if nome == "Empresa não identificada":
        base += " A API pública não informa as partes; identidade pendente de validação."
    return base


def _gate(proc, anterior):
    """Decide o tipo de alerta, ou None. Provisório e descartado nunca geram alerta de nova RJ."""
    if anterior and anterior["status"] in ("CONFIRMADO", "ATUALIZADO") and proc["status"] in ("DESCARTADO", "PROVISORIO"):
        return "CORRECAO"
    if proc["tipo_evento"] not in TIPOS_RJ:
        return None
    if proc["status"] == "CONFIRMADO" and (not anterior or anterior["status"] in ("COLETADO", "CANDIDATO", "PROVISORIO", None)):
        return "CONFIRMADO" if proc["estagio"] not in ESTAGIOS_TERMINAIS else None
    if anterior and anterior["status"] in ("CONFIRMADO", "ATUALIZADO") and (
            proc["estagio"] != anterior["estagio"] or proc["tipo_evento"] != anterior["tipo_evento"]):
        return "ATUALIZACAO"
    return None


def disparar_preventivo(db, cnpj, score):
    """Somente após revisão humana do score (gate da fase inicial) e nunca como lista aberta."""
    emp = db.um("SELECT * FROM empresas WHERE cnpj=?", (cnpj,)) or {}
    nome = emp.get("razao_social") or cnpj_formatar(cnpj)
    assunto = ASSUNTOS["PREVENTIVO"].format(empresa=nome)
    corpo = {"tipo": "PREVENTIVO", "empresa": [{"razao_social": nome, "cnpj": cnpj_formatar(cnpj)}],
             "score": score["score"], "faixa": score["faixa"], "fatores": score.get("fatores"),
             "aviso": "Recuperação judicial não confirmada", "classificacao_sujeita_a_validacao_juridica": True}
    chave = f"PREVENTIVO:{cnpj}:{score['score']}"
    _registrar(db, chave, "PREVENTIVO", assunto, corpo, None, "painel", None, "ENTREGUE")
    db.exec("UPDATE alertas SET cnpj=? WHERE chave=?", (cnpj, chave))
    for u in db.todos("SELECT u.id, p.* FROM usuarios u JOIN preferencias p ON p.usuario_id=u.id "
                      "WHERE u.ativo=1 AND p.incluir_preventivo=1 AND u.papel IN ('admin','analista')"):
        for canal in [c.strip().lower() for c in (u.get("canais") or "").split(",") if c.strip()]:
            destino = {"email": u.get("email"), "webhook": u.get("webhook_url"), "slack": u.get("slack_url"), "teams": u.get("teams_url")}.get(canal)
            if destino:
                try:
                    _enviar(canal, destino, assunto, corpo)
                    _registrar(db, f"{chave}:{u['id']}:{canal}", "PREVENTIVO", assunto, corpo, None, canal, destino, "ENVIADO")
                except Exception as exc:
                    _registrar(db, f"{chave}:{u['id']}:{canal}", "PREVENTIVO", assunto, corpo, None, canal, destino, "FALHA", str(exc)[:300])


def _aceita(pref, proc, tipo):
    if not pref:
        return True
    js = lambda s: [x.strip().upper() for x in (s or "").split(",") if x.strip()]
    if js(pref.get("tribunais")) and proc["tribunal"] not in js(pref["tribunais"]):
        return False
    if js(pref.get("ufs")) and (proc["uf"] or "") not in js(pref["ufs"]):
        return False
    if js(pref.get("eventos")) and proc["tipo_evento"] not in js(pref["eventos"]) and tipo != "CORRECAO":
        return False
    return True


def avaliar_e_notificar(db, proc, anterior):
    tipo = _gate(proc, anterior)
    if not tipo:
        return []
    return disparar(db, proc, tipo)


def disparar(db, proc, tipo):
    assunto, corpo = montar_alerta(db, proc, tipo)
    enviados = []
    chave_base = f"{tipo}:{proc['numero_cnj']}:{proc['estagio']}:{proc['tipo_evento']}"
    _registrar(db, chave_base + ":painel", tipo, assunto, corpo, proc, "painel", None, "ENTREGUE")
    enviados.append("painel")
    for u in db.todos("SELECT u.id, p.* FROM usuarios u LEFT JOIN preferencias p ON p.usuario_id=u.id WHERE u.ativo=1"):
        if not u.get("canais") or not _aceita(u, proc, tipo):
            continue
        if (u.get("frequencia") or "IMEDIATA").upper() == "DIARIA":
            _registrar(db, f"{chave_base}:{u['id']}:resumo", tipo, assunto, corpo, proc, "resumo_diario", u.get("email"), "AGUARDANDO_RESUMO")
            continue
        for canal in [c.strip().lower() for c in u["canais"].split(",")]:
            destino = {"email": u.get("email"), "webhook": u.get("webhook_url"), "slack": u.get("slack_url"), "teams": u.get("teams_url")}.get(canal)
            if not destino:
                continue
            chave = f"{chave_base}:{u['id']}:{canal}"
            if db.um("SELECT 1 FROM alertas WHERE chave=?", (chave,)):
                continue
            try:
                _enviar(canal, destino, assunto, corpo)
                _registrar(db, chave, tipo, assunto, corpo, proc, canal, destino, "ENVIADO")
                enviados.append(canal)
            except Exception as exc:
                _registrar(db, chave, tipo, assunto, corpo, proc, canal, destino, "FALHA", str(exc)[:300])
    return enviados


def _registrar(db, chave, tipo, assunto, corpo, proc, canal, destino, status, erro=None):
    db.exec("INSERT OR IGNORE INTO alertas(tipo,assunto,corpo,processo_id,canal,destino,status,erro,criado_em,enviado_em,chave)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (tipo, assunto, db.dump(corpo), proc["id"] if proc else None, canal, destino, status, erro, iso(agora()),
             iso(agora()) if status in ("ENVIADO", "ENTREGUE") else None, chave))


def _texto(assunto, corpo):
    linhas = [assunto, "", corpo.get("resumo", "")]
    if corpo.get("empresa"):
        linhas.append("Empresa: " + "; ".join(f"{e['razao_social']} ({e['cnpj']})" for e in corpo["empresa"]))
    linhas += [f"Processo: {corpo.get('numero_cnj')} | {corpo.get('tribunal')}",
               f"Evento: {corpo.get('evento')} | Estágio: {corpo.get('estagio')}",
               f"Ajuizamento: {corpo.get('data_evento')} | Descoberta: {corpo.get('data_descoberta')}",
               f"Confiança: {corpo.get('confianca')} | Divergências: {', '.join(corpo.get('divergencias') or []) or 'nenhuma'}",
               "Evidências: " + "; ".join(f"{e['fonte']} ({e['nivel']}) {e.get('url') or ''}" for e in corpo.get("evidencias", [])),
               f"Próxima ação: {corpo.get('proxima_acao')}",
               "Classificação sujeita a validação jurídica."]
    return "\n".join(linhas)


def _enviar(canal, destino, assunto, corpo):
    if canal == "email":
        if not CONFIG.smtp_host:
            raise RuntimeError("SMTP não configurado")
        msg = MIMEText(_texto(assunto, corpo), "plain", "utf-8")
        msg["Subject"], msg["From"], msg["To"] = assunto, CONFIG.smtp_remetente, destino
        with smtplib.SMTP(CONFIG.smtp_host, CONFIG.smtp_porta, timeout=30) as s:
            s.starttls()
            if CONFIG.smtp_usuario:
                s.login(CONFIG.smtp_usuario, CONFIG.smtp_senha)
            s.send_message(msg)
    elif canal == "webhook":
        requests.post(destino, json={"assunto": assunto, **corpo}, timeout=20).raise_for_status()
    elif canal in ("slack", "teams"):
        requests.post(destino, json={"text": _texto(assunto, corpo)}, timeout=20).raise_for_status()


def enviar_resumos_diarios(db):
    pend = db.todos("SELECT * FROM alertas WHERE status='AGUARDANDO_RESUMO'")
    por_destino = {}
    for a in pend:
        por_destino.setdefault(a["destino"], []).append(a)
    for destino, itens in por_destino.items():
        texto = "\n\n".join(_texto(a["assunto"], db.js(a["corpo"], {})) for a in itens)
        try:
            if destino and CONFIG.smtp_host:
                msg = MIMEText(texto, "plain", "utf-8")
                msg["Subject"], msg["From"], msg["To"] = f"Resumo diário Antevê | {len(itens)} alertas", CONFIG.smtp_remetente, destino
                with smtplib.SMTP(CONFIG.smtp_host, CONFIG.smtp_porta, timeout=30) as s:
                    s.starttls()
                    if CONFIG.smtp_usuario:
                        s.login(CONFIG.smtp_usuario, CONFIG.smtp_senha)
                    s.send_message(msg)
                status = "ENVIADO"
            else:
                status = "FALHA"
        except Exception:
            status = "FALHA"
        for a in itens:
            db.exec("UPDATE alertas SET status=?, enviado_em=? WHERE id=?", (status, iso(agora()), a["id"]))
