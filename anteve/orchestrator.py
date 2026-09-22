"""Orquestrador (seções 3.1, 8.1 e 8.2): agenda consultas, controla cursores, retentativas,
saúde por fonte e reconciliações diária e mensal."""
import os
import threading
import time
from datetime import timedelta

from . import pipeline, tpu as tpu_mod
from .config import CONFIG
from .connectors import datajud, djen
from .connectors.base import FonteIndisponivel, MudancaDeEsquema
from .normalize import agora, iso, parse_data

CLASSES_MONITORADAS = ["129", "128", "108"]
MOVIMENTOS_SEGURANCA = ["12041", "202"]


def _saude(db, fonte, tribunal, status, erro=None, latencia=None, registros=None):
    atual = db.um("SELECT * FROM saude_fontes WHERE fonte=? AND tribunal=?", (fonte, tribunal)) or {}
    ts = iso(agora())
    db.exec("INSERT OR REPLACE INTO saude_fontes(fonte,tribunal,status,ultimo_sucesso,ultima_falha,erro,latencia_ms,registros)"
            " VALUES(?,?,?,?,?,?,?,?)",
            (fonte, tribunal, status, ts if status == "OK" else atual.get("ultimo_sucesso"),
             ts if status != "OK" else atual.get("ultima_falha"), erro if status != "OK" else None,
             latencia, registros))


def _cursor(db, fonte, tribunal, modo):
    c = db.um("SELECT cursor_ts FROM cursores WHERE fonte=? AND tribunal=? AND modo=?", (fonte, tribunal, modo))
    return parse_data(c["cursor_ts"]) if c else None


def _gravar_cursor(db, fonte, tribunal, modo, ts):
    db.exec("INSERT OR REPLACE INTO cursores(fonte,tribunal,modo,cursor_ts,atualizado_em) VALUES(?,?,?,?,?)",
            (fonte, tribunal, modo, iso(ts), iso(agora())))


def coletar_tribunal(db, tribunal, modo="incremental", dias=None, inicio_inicial_dias=30, prazo=None):
    """Executa uma coleta para um tribunal. Nunca converte falha em 'nenhum processo'."""
    t0 = time.time()
    fim = agora()
    resumo = {"tribunal": tribunal.upper(), "modo": modo, "coletados": 0, "criados": 0, "atualizados": 0,
              "confirmados": 0, "provisorios": 0, "descartados": 0, "erro": None}
    maior_ts = None
    try:
        if modo == "incremental":
            cursor = _cursor(db, "DataJud", tribunal, "atualizacao")
            # Após uma execução parcial, retoma exatamente do ponto processado (sem sobreposição),
            # para não reler indefinidamente a mesma janela quando o volume é grande.
            parcial = db.estado(f"parcial:{tribunal}") == "1"
            sobrepor = timedelta(0) if parcial else timedelta(hours=CONFIG.sobreposicao_horas)
            inicio = (cursor or (fim - timedelta(days=inicio_inicial_dias))) - sobrepor
            lotes = (("classe", datajud.por_atualizacao(tribunal, inicio, fim, CLASSES_MONITORADAS)),
                     ("seguranca", datajud.seguranca_por_movimentos(tribunal, inicio, fim, MOVIMENTOS_SEGURANCA, CLASSES_MONITORADAS)))
        else:
            inicio = fim - timedelta(days=dias or CONFIG.reconciliacao_diaria_dias)
            lotes = (("classe", datajud.por_ajuizamento(tribunal, inicio, fim, CLASSES_MONITORADAS)),)
        for origem, lote in lotes:
            for src in lote:  # streaming: a falha pode ocorrer no meio da paginação
                if prazo and time.time() > prazo:
                    resumo["parcial"] = True
                    break
                reg = datajud.normalizar(src)
                r = pipeline.processar_registro(db, reg, origem=origem)
                resumo["coletados"] += 1
                resumo["criados" if r["acao"] == "criado" else "atualizados"] += 1
                st = r.get("status")
                if st in ("CONFIRMADO", "ATUALIZADO", "ENCERRADO"):
                    resumo["confirmados"] += 1
                elif st in ("PROVISORIO", "CANDIDATO"):
                    resumo["provisorios"] += 1
                elif st == "DESCARTADO":
                    resumo["descartados"] += 1
                ts = parse_data(reg.get("data_disponivel_fonte"))
                if ts and (not maior_ts or ts > maior_ts):
                    maior_ts = ts
            if resumo.get("parcial"):
                break
    except MudancaDeEsquema as exc:
        resumo["erro"] = f"mudança de esquema: {exc}"
        _saude(db, "DataJud", tribunal.upper(), "INTERROMPIDO_ESQUEMA", resumo["erro"])
        db.auditar("orquestrador", "fonte.esquema_alterado", "fonte", f"DataJud:{tribunal}", {"erro": str(exc)})
        return resumo
    except FonteIndisponivel as exc:
        resumo["erro"] = f"fonte indisponível: {exc}"
        _saude(db, "DataJud", tribunal.upper(), "INDISPONIVEL", resumo["erro"])
        return resumo  # cursor não avança; a janela sobreposta recupera o que faltou

    if modo == "incremental":
        if resumo.get("parcial"):
            # Ordenação ascendente por atualização: tudo até maior_ts foi processado
            if maior_ts:
                _gravar_cursor(db, "DataJud", tribunal, "atualizacao", maior_ts)
            db.estado(f"parcial:{tribunal}", "1")
            _saude(db, "DataJud", tribunal.upper(), "PARCIAL", "prazo da execução atingido; continua na próxima chamada",
                   latencia=int((time.time() - t0) * 1000), registros=resumo["coletados"])
            return resumo
        db.estado(f"parcial:{tribunal}", "0")
        _gravar_cursor(db, "DataJud", tribunal, "atualizacao", maior_ts or fim)
    _saude(db, "DataJud", tribunal.upper(), "OK", latencia=int((time.time() - t0) * 1000), registros=resumo["coletados"])
    return resumo


_SQL_ALVOS_DIARIO = (
    "FROM processos p WHERE p.status IN ('CONFIRMADO','ATUALIZADO','PROVISORIO') AND p.tipo_evento LIKE 'RJ_%' "
    "AND (NOT EXISTS (SELECT 1 FROM evidencias e WHERE e.processo_id=p.id AND e.tipo='PUBLICACAO_OFICIAL') "
    "OR NOT EXISTS (SELECT 1 FROM partes pa WHERE pa.processo_id=p.id)) "
    "AND (p.diario_consultado_em IS NULL OR p.diario_consultado_em < ?)")


def pendentes_diario(db):
    return db.um("SELECT COUNT(*) n " + _SQL_ALVOS_DIARIO, (iso(agora() - timedelta(hours=24)),))["n"]


def enriquecer_com_diario(db, limite=25, prazo=None):
    """Busca publicações oficiais (DJEN) para processos ativos ainda sem documento ou sem partes.
    Cada processo consultado só volta à fila 24 h depois, para um processo sem publicação não
    bloquear os demais."""
    if not CONFIG.djen_habilitado:
        return {"status": "desabilitado"}
    alvos = db.todos("SELECT p.id, p.numero_cnj " + _SQL_ALVOS_DIARIO +
                     " ORDER BY p.diario_consultado_em IS NOT NULL, p.diario_consultado_em, p.data_ajuizamento DESC LIMIT ?",
                     (iso(agora() - timedelta(hours=24)), limite))
    total, consultados, partes_antes = 0, 0, db.um("SELECT COUNT(*) n FROM partes")["n"]
    for a in alvos:
        if prazo and time.time() > prazo:
            break
        try:
            pubs = djen.por_processo(a["numero_cnj"])
        except FonteIndisponivel as exc:
            _saude(db, "DJEN", "NACIONAL", "INDISPONIVEL", str(exc))
            return {"status": "indisponivel", "erro": str(exc), "processados": consultados}
        total += pipeline.incorporar_publicacoes(db, a["id"], pubs)
        db.exec("UPDATE processos SET diario_consultado_em=? WHERE id=?", (iso(agora()), a["id"]))
        consultados += 1
    _saude(db, "DJEN", "NACIONAL", "OK", registros=total)
    return {"status": "ok", "consultados": consultados, "novas_evidencias": total,
            "novas_partes": db.um("SELECT COUNT(*) n FROM partes")["n"] - partes_antes, "pendentes": pendentes_diario(db)}


def ciclo(db, tribunais=None):
    inicio = iso(agora())
    resultados = [coletar_tribunal(db, t) for t in (tribunais or CONFIG.tribunais)]
    diario = enriquecer_com_diario(db)
    _reconciliacoes_agendadas(db, tribunais)
    for s in db.todos("SELECT DISTINCT cnpj FROM scores"):
        pipeline.recalcular_score(db, s["cnpj"])  # expiração de pesos
    db.exec("INSERT INTO execucoes(tipo,inicio,fim,resumo) VALUES('ciclo',?,?,?)",
            (inicio, iso(agora()), db.dump({"tribunais": resultados, "diario": diario})))
    return {"tribunais": resultados, "diario": diario}


def _reconciliacoes_agendadas(db, tribunais=None):
    hoje = agora()
    for tipo, dias, intervalo in (("reconciliacao_diaria", CONFIG.reconciliacao_diaria_dias, timedelta(days=1)),
                                  ("reconciliacao_mensal", CONFIG.reconciliacao_mensal_dias, timedelta(days=30))):
        ultima = db.um("SELECT fim FROM execucoes WHERE tipo=? ORDER BY id DESC LIMIT 1", (tipo,))
        if ultima and hoje - parse_data(ultima["fim"]) < intervalo:
            continue
        ini = iso(hoje)
        res = [coletar_tribunal(db, t, modo="reconciliacao", dias=dias) for t in (tribunais or CONFIG.tribunais)]
        db.exec("INSERT INTO execucoes(tipo,inicio,fim,resumo) VALUES(?,?,?,?)", (tipo, ini, iso(agora()), db.dump(res)))


class Agendador(threading.Thread):
    def __init__(self, db):
        super().__init__(daemon=True)
        self.db = db
        self.parar = threading.Event()

    def run(self):
        tpu_mod.carregar(self.db)
        while not self.parar.is_set():
            try:
                ciclo(self.db)
            except Exception as exc:  # o agendador não pode morrer silenciosamente
                self.db.auditar("orquestrador", "ciclo.erro", "sistema", None, {"erro": str(exc)})
            self.parar.wait(CONFIG.intervalo_coleta_min * 60)


def executar_com_orcamento(db, modo="incremental", dias=None, orcamento_s=45, diario_limite=40, paralelo=None):
    """Execução para ambiente sem servidor (Vercel). Cada chamada processa um lote de tribunais
    em paralelo (a espera é de rede; o acesso ao banco é serializado) e avança o ponteiro do
    rodízio no banco, para a chamada seguinte continuar de onde esta parou."""
    from concurrent.futures import ThreadPoolExecutor
    t0 = time.time()
    tribunais = list(CONFIG.tribunais)
    paralelo = paralelo or int(os.environ.get("ANTEVE_PARALELO", "6"))
    chave = f"rodizio:{modo}:{dias or ''}"
    pos = int(db.estado(chave) or 0) % len(tribunais)
    lote = [tribunais[(pos + i) % len(tribunais)] for i in range(min(paralelo, len(tribunais)))]
    with ThreadPoolExecutor(max_workers=len(lote)) as ex:
        prazo = t0 + orcamento_s
        feitos = list(ex.map(lambda t: coletar_tribunal(db, t, modo=modo, dias=dias, prazo=prazo), lote))
    db.estado(chave, (pos + len(lote)) % len(tribunais))
    diario = None
    if modo == "incremental" and time.time() - t0 < orcamento_s:
        diario = enriquecer_com_diario(db, limite=diario_limite, prazo=t0 + orcamento_s)
        for s in db.todos("SELECT DISTINCT cnpj FROM scores"):
            pipeline.recalcular_score(db, s["cnpj"])
    db.exec("INSERT INTO execucoes(tipo,inicio,fim,resumo) VALUES(?,?,?,?)",
            (f"cron_{modo}", iso(agora() - timedelta(seconds=time.time() - t0)), iso(agora()),
             db.dump({"tribunais": feitos, "diario": diario})))
    return {"modo": modo, "tribunais_processados": [f["tribunal"] for f in feitos],
            "erros": {f["tribunal"]: f["erro"] for f in feitos if f["erro"]},
            "proximo": tribunais[int(db.estado(chave) or 0)], "segundos": round(time.time() - t0, 1), "diario": diario}
