"""Coletor de Diário: Diário de Justiça Eletrônico Nacional (DJEN/CNJ), API de comunicações.

Observação operacional: a API é publicada atrás de CDN com restrição geográfica. Deve
ser executada a partir de infraestrutura no Brasil. Fora do país ela responde 403 e o
conector registra FonteIndisponivel, sem interpretar isso como ausência de publicação.
"""
from ..config import CONFIG
from ..normalize import cnj_digitos, cnj_formatar, hash_obj, iso, parse_data
from .base import FonteIndisponivel, requisitar


def _itens(params):
    r = requisitar("GET", CONFIG.djen_url, params=params, tentativas=3, timeout=45)
    if r.status_code != 200:
        raise FonteIndisponivel(f"HTTP {r.status_code}")
    try:
        dados = r.json()
    except ValueError:
        raise FonteIndisponivel("resposta não JSON (possível bloqueio geográfico)")
    return dados.get("items") or dados.get("itens") or []


def _normalizar(item):
    texto = item.get("texto") or ""
    numero = cnj_formatar(item.get("numero_processo") or item.get("numeroprocessocommascara") or "")
    destinatarios = []
    for d in item.get("destinatarios") or []:
        destinatarios.append({"nome": d.get("nome"), "polo": d.get("polo")})
    advogados = []
    for d in item.get("destinatarioadvogados") or []:
        a = d.get("advogado") or d
        if a.get("nome"):
            oab = f"{a.get('numero_oab')}/{a.get('uf_oab')}" if a.get("numero_oab") else None
            advogados.append({"nome": a.get("nome"), "oab": oab})
    return {
        "fonte": "DJEN",
        "numero_cnj": numero,
        "tribunal": item.get("siglaTribunal"),
        "data": iso(parse_data(item.get("data_disponibilizacao") or item.get("datadisponibilizacao"))),
        "tipo": item.get("tipoComunicacao") or item.get("tipoDocumento"),
        "orgao": item.get("nomeOrgao"),
        "classe": item.get("nomeClasse"),
        "texto": texto,
        "destinatarios": destinatarios,
        "advogados": advogados,
        "url": item.get("link"),
        "hash": item.get("hash") or hash_obj(texto),
    }


def por_processo(numero_cnj):
    return [_normalizar(i) for i in _itens({"numeroProcesso": cnj_digitos(numero_cnj), "itensPorPagina": 100})]


def por_termo(termo, inicio, fim, tribunal=None):
    params = {"texto": termo, "dataDisponibilizacaoInicio": inicio.strftime("%Y-%m-%d"),
              "dataDisponibilizacaoFim": fim.strftime("%Y-%m-%d"), "itensPorPagina": 100}
    if tribunal:
        params["siglaTribunal"] = tribunal.upper()
    return [_normalizar(i) for i in _itens(params)]
