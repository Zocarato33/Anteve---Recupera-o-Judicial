"""Persistência (SQLite em modo WAL). O esquema segue a seção 6.1 da especificação.
Para produção com múltiplas instâncias, o mesmo esquema pode ser portado para PostgreSQL."""
import hashlib
import json
import os
import re
import secrets
import sqlite3
import threading

from .normalize import agora, iso

ESQUEMA = """
CREATE TABLE IF NOT EXISTS registros_brutos(
  id INTEGER PRIMARY KEY, fonte TEXT, tribunal TEXT, id_fonte TEXT, hash TEXT UNIQUE,
  payload TEXT, coletado_em TEXT);
CREATE TABLE IF NOT EXISTS processos(
  id INTEGER PRIMARY KEY, numero_cnj TEXT UNIQUE, id_fonte TEXT, tribunal TEXT, uf TEXT, grau TEXT,
  comarca TEXT, vara TEXT, classe_codigo TEXT, classe_nome TEXT, assuntos TEXT,
  data_ajuizamento TEXT, data_descoberta TEXT, data_disponivel_fonte TEXT,
  tipo_evento TEXT, status TEXT, estagio TEXT, rota TEXT, processo_principal TEXT,
  pedido_confirmado INTEGER DEFAULT 0, processamento_deferido INTEGER DEFAULT 0,
  administrador_judicial TEXT, valor_causa REAL, quantidade_empresas INTEGER DEFAULT 0,
  confianca REAL, prioridade TEXT, idade TEXT, motivos TEXT, inconsistencias TEXT,
  revisao_humana INTEGER DEFAULT 0, contato_bloqueado INTEGER DEFAULT 1,
  versao_regra TEXT, versao_tpu TEXT, versao_prompt TEXT, url_fonte TEXT,
  atualizado_em TEXT, ultimo_movimento_em TEXT);
CREATE INDEX IF NOT EXISTS ix_proc_status ON processos(status);
CREATE INDEX IF NOT EXISTS ix_proc_trib ON processos(tribunal);
CREATE TABLE IF NOT EXISTS historico_processo(
  id INTEGER PRIMARY KEY, processo_id INTEGER, campo TEXT, anterior TEXT, novo TEXT, motivo TEXT, ts TEXT);
CREATE TABLE IF NOT EXISTS empresas(
  id INTEGER PRIMARY KEY, cnpj TEXT UNIQUE, raiz_cnpj TEXT, razao_social TEXT, nome_fantasia TEXT,
  aliases TEXT, municipio TEXT, uf TEXT, cnae TEXT, porte TEXT, situacao_cadastral TEXT,
  grupo_economico TEXT, confianca_identidade TEXT, fonte_identidade TEXT, atualizado_em TEXT);
CREATE INDEX IF NOT EXISTS ix_emp_raiz ON empresas(raiz_cnpj);
CREATE TABLE IF NOT EXISTS processo_empresas(
  processo_id INTEGER, empresa_id INTEGER, polo TEXT, papel TEXT, evidencia_id INTEGER,
  PRIMARY KEY(processo_id, empresa_id));
CREATE TABLE IF NOT EXISTS eventos(
  id INTEGER PRIMARY KEY, processo_id INTEGER, tipo_evento TEXT, data_evento TEXT,
  movimento_codigo TEXT, movimento_nome TEXT, confirmado INTEGER, data_descoberta TEXT, hash TEXT UNIQUE);
CREATE TABLE IF NOT EXISTS evidencias(
  id INTEGER PRIMARY KEY, processo_id INTEGER, empresa_cnpj TEXT, nivel TEXT, tipo TEXT, fonte TEXT,
  url TEXT, documento TEXT, pagina TEXT, trecho_resumido TEXT, coletado_em TEXT,
  hash_documento TEXT, gerada_por_ia INTEGER DEFAULT 0, versao_regra TEXT,
  UNIQUE(processo_id, fonte, hash_documento));
CREATE TABLE IF NOT EXISTS sinais(
  id INTEGER PRIMARY KEY, cnpj TEXT, raiz_cnpj TEXT, tipo TEXT, peso INTEGER, nivel TEXT,
  fonte TEXT, url TEXT, descricao TEXT, data_sinal TEXT, validade_dias INTEGER,
  negativo INTEGER DEFAULT 0, processo_cnj TEXT, registrado_por TEXT, criado_em TEXT, ativo INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS scores(
  cnpj TEXT PRIMARY KEY, score INTEGER, faixa TEXT, fatores TEXT, calculado_em TEXT, versao_regra TEXT,
  revisado INTEGER DEFAULT 0, revisado_por TEXT);
CREATE TABLE IF NOT EXISTS revisoes(
  id INTEGER PRIMARY KEY, processo_id INTEGER, cnpj TEXT, fila TEXT, motivo TEXT, status TEXT,
  decisao TEXT, justificativa TEXT, revisor TEXT, criado_em TEXT, decidido_em TEXT);
CREATE TABLE IF NOT EXISTS oportunidades(
  id INTEGER PRIMARY KEY, processo_id INTEGER, cnpj TEXT, tipo TEXT, prioridade TEXT, responsavel TEXT,
  status_funil TEXT, ultimo_contato TEXT, opt_out INTEGER DEFAULT 0, motivo_encerramento TEXT,
  historico TEXT, criado_em TEXT, atualizado_em TEXT, UNIQUE(processo_id, tipo));
CREATE TABLE IF NOT EXISTS alertas(
  id INTEGER PRIMARY KEY, tipo TEXT, assunto TEXT, corpo TEXT, processo_id INTEGER, cnpj TEXT,
  canal TEXT, destino TEXT, status TEXT, erro TEXT, criado_em TEXT, enviado_em TEXT, chave TEXT UNIQUE);
CREATE TABLE IF NOT EXISTS cursores(
  fonte TEXT, tribunal TEXT, modo TEXT, cursor_ts TEXT, atualizado_em TEXT, PRIMARY KEY(fonte, tribunal, modo));
CREATE TABLE IF NOT EXISTS saude_fontes(
  fonte TEXT, tribunal TEXT, status TEXT, ultimo_sucesso TEXT, ultima_falha TEXT, erro TEXT,
  latencia_ms INTEGER, registros INTEGER, PRIMARY KEY(fonte, tribunal));
CREATE TABLE IF NOT EXISTS execucoes(
  id INTEGER PRIMARY KEY, tipo TEXT, inicio TEXT, fim TEXT, resumo TEXT);
CREATE TABLE IF NOT EXISTS auditoria(
  id INTEGER PRIMARY KEY, ts TEXT, ator TEXT, acao TEXT, entidade TEXT, entidade_id TEXT, detalhe TEXT);
CREATE TABLE IF NOT EXISTS tpu_versoes(
  id INTEGER PRIMARY KEY, versao TEXT, hash TEXT UNIQUE, conteudo TEXT, origem TEXT, criado_em TEXT);
CREATE TABLE IF NOT EXISTS ia_execucoes(
  id INTEGER PRIMARY KEY, processo_id INTEGER, modelo TEXT, versao_prompt TEXT, hash_entrada TEXT,
  tokens_entrada INTEGER, tokens_saida INTEGER, resposta TEXT, aceita INTEGER, rejeicoes TEXT, ts TEXT);
CREATE TABLE IF NOT EXISTS opt_out(
  cnpj TEXT PRIMARY KEY, motivo TEXT, solicitante TEXT, ts TEXT);
CREATE TABLE IF NOT EXISTS correcoes(
  id INTEGER PRIMARY KEY, alvo_tipo TEXT, alvo TEXT, tipo TEXT, descricao TEXT, solicitante TEXT,
  status TEXT, resposta TEXT, criado_em TEXT, resolvido_em TEXT);
CREATE TABLE IF NOT EXISTS amostra_controle(
  numero_cnj TEXT PRIMARY KEY, origem TEXT, incluido_em TEXT);
CREATE TABLE IF NOT EXISTS usuarios(
  id INTEGER PRIMARY KEY, nome TEXT, papel TEXT, token_hash TEXT UNIQUE, ativo INTEGER DEFAULT 1, criado_em TEXT);
CREATE TABLE IF NOT EXISTS estado(
  chave TEXT PRIMARY KEY, valor TEXT);
CREATE TABLE IF NOT EXISTS preferencias(
  usuario_id INTEGER PRIMARY KEY, tribunais TEXT, ufs TEXT, eventos TEXT, canais TEXT,
  frequencia TEXT, email TEXT, webhook_url TEXT, slack_url TEXT, teams_url TEXT, incluir_preventivo INTEGER DEFAULT 0);
"""

PAPEIS = {
    "admin": {"ler", "revisar", "comercial", "preventivo", "exportar", "administrar"},
    "analista": {"ler", "revisar", "preventivo", "exportar"},
    "comercial": {"ler", "comercial"},
    "leitor": {"ler"},
}


def hash_token(token):
    return hashlib.sha256(token.encode()).hexdigest()


# Chaves de conflito para traduzir "INSERT OR REPLACE" do SQLite em upsert do PostgreSQL
CHAVES_UPSERT = {
    "saude_fontes": ["fonte", "tribunal"], "cursores": ["fonte", "tribunal", "modo"], "scores": ["cnpj"],
    "processo_empresas": ["processo_id", "empresa_id"], "opt_out": ["cnpj"], "preferencias": ["usuario_id"],
    "estado": ["chave"],
}
_RE_INSERT = re.compile(r"^\s*INSERT\s+OR\s+(IGNORE|REPLACE)\s+INTO\s+(\w+)\s*\(([^)]*)\)", re.I | re.S)


def traduzir_pg(sql):
    """Traduz o dialeto SQLite usado no código para PostgreSQL."""
    m = _RE_INSERT.match(sql)
    sufixo = ""
    if m:
        modo, tabela, cols = m.group(1).upper(), m.group(2), [c.strip() for c in m.group(3).split(",")]
        sql = _RE_INSERT.sub(f"INSERT INTO {tabela}({m.group(3)})", sql, count=1)
        if modo == "IGNORE":
            sufixo = " ON CONFLICT DO NOTHING"
        else:
            chaves = CHAVES_UPSERT[tabela]
            resto = [c for c in cols if c not in chaves]
            sufixo = f" ON CONFLICT ({', '.join(chaves)}) DO UPDATE SET " + ", ".join(f"{c}=EXCLUDED.{c}" for c in resto)
    sql = re.sub(r"\bIS\s+\?", "IS NOT DISTINCT FROM ?", sql)
    sql = sql.replace("%", "%%").replace("?", "%s")
    return sql.rstrip().rstrip(";") + sufixo


def esquema_pg():
    ddl = ESQUEMA.replace("INTEGER PRIMARY KEY,", "BIGSERIAL PRIMARY KEY,").replace(" REAL", " DOUBLE PRECISION")
    return ddl


class DB:
    """Banco com dois motores: SQLite (local, arquivo) e PostgreSQL (produção e Vercel).
    O motor é escolhido pela URL: postgres://... ou postgresql://... usa PostgreSQL."""

    def __init__(self, caminho):
        self.caminho = caminho
        self.pg = str(caminho).startswith(("postgres://", "postgresql://"))
        self._lock = threading.RLock()
        self._conectar()
        self._criar_esquema()

    def _conectar(self):
        if self.pg:
            import psycopg
            from psycopg.rows import dict_row
            # prepare_threshold=None: compatível com pooler em modo transação (Supabase, Neon, PgBouncer)
            self.con = psycopg.connect(self.caminho, autocommit=True, row_factory=dict_row, prepare_threshold=None,
                                       connect_timeout=15)
        else:
            if self.caminho != ":memory:":
                os.makedirs(os.path.dirname(os.path.abspath(self.caminho)), exist_ok=True)
            self.con = sqlite3.connect(self.caminho, check_same_thread=False, isolation_level=None)
            self.con.row_factory = sqlite3.Row
            self.con.execute("PRAGMA journal_mode=WAL")
            self.con.execute("PRAGMA foreign_keys=ON")

    def _criar_esquema(self):
        with self._lock:
            if self.pg:
                with self.con.cursor() as cur:
                    cur.execute("SELECT pg_advisory_lock(424242)")
                    try:
                        for comando in [c.strip() for c in esquema_pg().split(";") if c.strip()]:
                            cur.execute(comando)
                    finally:
                        cur.execute("SELECT pg_advisory_unlock(424242)")
            else:
                self.con.executescript(ESQUEMA)

    # utilidades -------------------------------------------------------
    @staticmethod
    def dump(obj):
        return json.dumps(obj, ensure_ascii=False, default=str)

    @staticmethod
    def js(texto, padrao=None):
        if texto is None or texto == "":
            return padrao
        try:
            return json.loads(texto)
        except (TypeError, ValueError):
            return padrao

    def _executar(self, sql, params):
        if not self.pg:
            return self.con.execute(sql, params)
        import psycopg
        q = traduzir_pg(sql)
        for tentativa in (1, 2):
            try:
                cur = self.con.cursor()
                cur.execute(q, list(params))
                return cur
            except psycopg.OperationalError:
                if tentativa == 2:
                    raise
                self._conectar()  # conexão reaproveitada entre invocações pode ter caído

    def exec(self, sql, params=()):
        with self._lock:
            return self._executar(sql, params)

    def um(self, sql, params=()):
        with self._lock:
            r = self._executar(sql, params).fetchone()
            return dict(r) if r else None

    def todos(self, sql, params=()):
        with self._lock:
            return [dict(r) for r in self._executar(sql, params).fetchall()]

    def transacao(self):
        return _Transacao(self)

    def estado(self, chave, valor=None):
        if valor is None:
            r = self.um("SELECT valor FROM estado WHERE chave=?", (chave,))
            return r["valor"] if r else None
        self.exec("INSERT OR REPLACE INTO estado(chave,valor) VALUES(?,?)", (chave, str(valor)))

    def auditar(self, ator, acao, entidade, entidade_id, detalhe=None):
        self.exec("INSERT INTO auditoria(ts,ator,acao,entidade,entidade_id,detalhe) VALUES(?,?,?,?,?,?)",
                  (iso(agora()), ator, acao, entidade, str(entidade_id) if entidade_id is not None else None,
                   self.dump(detalhe or {})))

    # usuários --------------------------------------------------------
    def criar_usuario(self, nome, papel):
        if papel not in PAPEIS:
            raise ValueError("papel inválido")
        token = "ant_" + secrets.token_urlsafe(24)
        self.exec("INSERT INTO usuarios(nome,papel,token_hash,criado_em) VALUES(?,?,?,?)",
                  (nome, papel, hash_token(token), iso(agora())))
        self.auditar("sistema", "usuario.criar", "usuario", nome, {"papel": papel})
        return token

    def usuario_por_token(self, token):
        if not token:
            return None
        return self.um("SELECT * FROM usuarios WHERE token_hash=? AND ativo=1", (hash_token(token),))


class _Transacao:
    def __init__(self, db):
        self.db = db

    def __enter__(self):
        self.db._lock.acquire()
        self.db._executar("BEGIN", ())
        return self.db

    def __exit__(self, tipo, valor, tb):
        try:
            self.db._executar("ROLLBACK" if tipo else "COMMIT", ())
        finally:
            self.db._lock.release()
        return False
