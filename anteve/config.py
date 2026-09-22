"""Configuração central. Todos os parâmetros são ajustáveis por variável de ambiente."""
import os
from dataclasses import dataclass, field


def _env(nome, padrao):
    return os.environ.get(nome, padrao)


def _lista(nome, padrao):
    valor = os.environ.get(nome)
    if not valor:
        return list(padrao)
    return [v.strip().lower() for v in valor.split(",") if v.strip()]


TODOS_TJS = [
    "tjac", "tjal", "tjam", "tjap", "tjba", "tjce", "tjdft", "tjes", "tjgo", "tjma",
    "tjmg", "tjms", "tjmt", "tjpa", "tjpb", "tjpe", "tjpi", "tjpr", "tjrj", "tjrn",
    "tjro", "tjrr", "tjrs", "tjsc", "tjse", "tjsp", "tjto",
]

UF_POR_TRIBUNAL = {t.upper(): (t[2:].upper() if t != "tjdft" else "DF") for t in TODOS_TJS}


@dataclass
class Config:
    # DATABASE_URL (PostgreSQL) tem precedência. No Vercel, sem DATABASE_URL, o SQLite vai para /tmp
    # e é APAGADO a cada nova instância: use apenas para demonstração.
    db_path: str = (os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL") or _env(
        "ANTEVE_DB", "/tmp/anteve.db" if os.environ.get("VERCEL") else os.path.join(os.path.dirname(__file__), "..", "data", "anteve.db")))
    cron_secret: str = _env("CRON_SECRET", "")
    # Acesso: só estes IPs chegam ao painel e à API (vazio desativa). /api/cron/* fica de fora,
    # protegido pelo CRON_SECRET, porque é chamado pelo Vercel Cron e pelo GitHub Actions.
    ips_permitidos: list = field(default_factory=lambda: [
        v.strip() for v in _env("ANTEVE_IPS_PERMITIDOS", "186.193.236.194,179.191.112.34").split(",") if v.strip()])
    # Atrás de proxy (Vercel), o IP do cliente vem do X-Forwarded-For. Fora dele, da conexão.
    confiar_proxy: bool = _env("ANTEVE_CONFIAR_PROXY", "1" if os.environ.get("VERCEL") else "0") == "1"
    # Token do administrador inicial: se definido, o usuário é criado na primeira execução.
    token_admin: str = _env("ANTEVE_TOKEN_ADMIN", "")
    # DataJud: a chave pública é divulgada pelo CNJ e pode mudar a qualquer momento.
    datajud_url: str = _env("DATAJUD_URL", "https://api-publica.datajud.cnj.jus.br")
    datajud_api_key: str = _env("DATAJUD_API_KEY", "cDZHYzlZa0JadVREZDJCendQbXY6SkJlTzNjLV9TRENyQk1RdnFKZGRQdw==")
    djen_url: str = _env("DJEN_URL", "https://comunicaapi.pje.jus.br/api/v1/comunicacao")
    djen_habilitado: bool = _env("DJEN_HABILITADO", "1") == "1"
    cnpj_url: str = _env("CNPJ_URL", "https://brasilapi.com.br/api/cnpj/v1/")
    sgt_url: str = _env("SGT_URL", "https://www.cnj.jus.br/sgt/sgt_ws.php")
    tribunais: list = field(default_factory=lambda: _lista("ANTEVE_TRIBUNAIS", TODOS_TJS))
    # 3.1 Janela incremental
    intervalo_coleta_min: int = int(_env("ANTEVE_INTERVALO_MIN", "45"))
    sobreposicao_horas: int = int(_env("ANTEVE_SOBREPOSICAO_H", "72"))
    reconciliacao_diaria_dias: int = int(_env("ANTEVE_RECONC_DIARIA_DIAS", "30"))
    reconciliacao_mensal_dias: int = int(_env("ANTEVE_RECONC_MENSAL_DIAS", "365"))
    janela_captura_dias: int = int(_env("ANTEVE_JANELA_CAPTURA_DIAS", "365"))
    tamanho_pagina: int = int(_env("ANTEVE_PAGINA", "100"))
    # 3.3 Definição de novo
    novo_ate_dias: int = int(_env("ANTEVE_NOVO_DIAS", "7"))
    recente_ate_dias: int = int(_env("ANTEVE_RECENTE_DIAS", "30"))
    # 4.1 Faixas do score preventivo
    faixa_atencao: int = 25
    faixa_elevado: int = 50
    faixa_prioridade: int = 70
    preventivo_exige_revisao: bool = _env("ANTEVE_PREVENTIVO_REVISAO", "1") == "1"
    # IA
    anthropic_api_key: str = _env("ANTHROPIC_API_KEY", "")
    modelo_ia: str = _env("ANTEVE_MODELO_IA", "claude-sonnet-5")
    # Notificação
    smtp_host: str = _env("SMTP_HOST", "")
    smtp_porta: int = int(_env("SMTP_PORTA", "587"))
    smtp_usuario: str = _env("SMTP_USUARIO", "")
    smtp_senha: str = _env("SMTP_SENHA", "")
    smtp_remetente: str = _env("SMTP_REMETENTE", "anteve@localhost")
    user_agent: str = _env("ANTEVE_USER_AGENT", "Antevê/1.0 (monitoramento de recuperações judiciais)")


CONFIG = Config()
