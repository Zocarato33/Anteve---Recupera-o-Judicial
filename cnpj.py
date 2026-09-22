"""Enriquecimento cadastral por CNPJ a partir de dados abertos da Receita Federal
(via BrasilAPI). Minimização: o quadro societário (dados pessoais) NÃO é armazenado."""
from ..config import CONFIG
from ..normalize import cnpj_limpar, cnpj_valido
from .base import FonteIndisponivel, requisitar


def consultar(cnpj):
    c = cnpj_limpar(cnpj)
    if not cnpj_valido(c):
        raise ValueError("CNPJ inválido")
    r = requisitar("GET", CONFIG.cnpj_url + c, tentativas=3, timeout=30)
    if r.status_code == 404:
        return None
    if r.status_code != 200:
        raise FonteIndisponivel(f"HTTP {r.status_code}")
    d = r.json()
    return {
        "cnpj": c,
        "razao_social": d.get("razao_social"),
        "nome_fantasia": d.get("nome_fantasia") or None,
        "municipio": d.get("municipio"),
        "uf": d.get("uf"),
        "cnae": f"{d.get('cnae_fiscal')} {d.get('cnae_fiscal_descricao') or ''}".strip(),
        "porte": d.get("porte") or d.get("descricao_porte"),
        "situacao_cadastral": d.get("descricao_situacao_cadastral"),
        "fonte": "Dados abertos CNPJ/Receita Federal (BrasilAPI)",
    }
