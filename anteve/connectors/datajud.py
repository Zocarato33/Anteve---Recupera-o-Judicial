"""Conector DataJud (API Pública do CNJ).

Particularidades validadas em 22/09/2026 contra a API real:
* `dataAjuizamento` é gravado como texto compacto yyyyMMddHHmmss. O filtro de faixa só
  funciona corretamente com esse mesmo formato; o formato ISO do exemplo conceitual
  retorna resultados incorretos.
* `dataHoraUltimaAtualizacao` é data ISO e serve como cursor incremental confiável.
* A API pública não traz partes nem CNPJ; a identidade vem de diários, portais ou revisão.
"""
from ..config import CONFIG, UF_POR_TRIBUNAL
from ..normalize import cnj_formatar, cnj_valido, datajud_compacto, iso, parse_data
from .base import FonteIndisponivel, MudancaDeEsquema, requisitar

CAMPOS_ESPERADOS = {"numeroProcesso", "classe", "tribunal"}


def _endpoint(tribunal):
    return f"{CONFIG.datajud_url}/api_publica_{tribunal.lower()}/_search"


def _buscar(tribunal, consulta, ordenacao, limite_paginas=200):
    """Paginação com search_after, em streaming: gera um registro por vez para não
    acumular em memória processos com milhares de movimentos."""
    corpo = {"size": CONFIG.tamanho_pagina, "query": consulta, "sort": ordenacao}
    for _ in range(limite_paginas):
        r = requisitar("POST", _endpoint(tribunal), json=corpo, headers={
            "Authorization": f"APIKey {CONFIG.datajud_api_key}", "Content-Type": "application/json"})
        if r.status_code == 404:
            raise FonteIndisponivel(f"índice {tribunal} não encontrado")
        try:
            dados = r.json()
        except ValueError as exc:
            raise MudancaDeEsquema(f"resposta não JSON: {exc}")
        if "error" in dados:
            raise FonteIndisponivel(str(dados["error"])[:300])
        if "hits" not in dados or "hits" not in dados["hits"]:
            raise MudancaDeEsquema("estrutura 'hits' ausente")
        hits = dados["hits"]["hits"]
        for h in hits:
            src = h.get("_source", {})
            if not CAMPOS_ESPERADOS.issubset(src.keys()):
                raise MudancaDeEsquema(f"campos obrigatórios ausentes: {CAMPOS_ESPERADOS - set(src)}")
            yield src
        if len(hits) < CONFIG.tamanho_pagina:
            return
        corpo["search_after"] = hits[-1]["sort"]


def _faixa_captura(fim):
    from datetime import timedelta
    return {"range": {"dataAjuizamento": {"gte": datajud_compacto(fim - timedelta(days=CONFIG.janela_captura_dias))}}}


def por_atualizacao(tribunal, inicio, fim, classes):
    """Coleta incremental principal: processos das classes monitoradas atualizados na janela,
    restritos à janela de captura por ajuizamento (processos antigos não são "novos")."""
    consulta = {"bool": {"filter": [
        {"terms": {"classe.codigo": [int(c) for c in classes]}},
        {"range": {"dataHoraUltimaAtualizacao": {"gte": iso(inicio), "lte": iso(fim)}}},
        _faixa_captura(fim),
    ]}}
    return _buscar(tribunal, consulta, [{"dataHoraUltimaAtualizacao": "asc"}, {"id.keyword": "asc"}])


def por_ajuizamento(tribunal, inicio, fim, classes):
    """Reconciliação por data de ajuizamento (formato compacto obrigatório)."""
    consulta = {"bool": {"filter": [
        {"terms": {"classe.codigo": [int(c) for c in classes]}},
        {"range": {"dataAjuizamento": {"gte": datajud_compacto(inicio), "lte": datajud_compacto(fim)}}},
    ]}}
    return _buscar(tribunal, consulta, [{"dataAjuizamento": "asc"}, {"id.keyword": "asc"}])


def seguranca_por_movimentos(tribunal, inicio, fim, movimentos, classes_excluir):
    """Consulta de segurança (seção 8): atos recuperacionais em processos fora da classe RJ,
    para capturar erros de autuação. Resultado entra apenas como CANDIDATO."""
    consulta = {"bool": {
        "filter": [
            {"terms": {"movimentos.codigo": [int(m) for m in movimentos]}},
            {"range": {"dataHoraUltimaAtualizacao": {"gte": iso(inicio), "lte": iso(fim)}}},
            _faixa_captura(fim),
        ],
        "must_not": [{"terms": {"classe.codigo": [int(c) for c in classes_excluir]}}],
    }}
    return _buscar(tribunal, consulta, [{"dataHoraUltimaAtualizacao": "asc"}, {"id.keyword": "asc"}], limite_paginas=10)


def normalizar(src):
    """Transforma o retorno do DataJud no esquema interno."""
    numero = cnj_formatar(src.get("numeroProcesso"))
    tribunal = (src.get("tribunal") or "").upper()
    orgao = src.get("orgaoJulgador") or {}
    movimentos = []
    for m in src.get("movimentos") or []:
        movimentos.append({
            "codigo": str(m.get("codigo")) if m.get("codigo") is not None else None,
            "nome": m.get("nome"),
            "data": iso(parse_data(m.get("dataHora"))),
            "complementos": [c.get("nome") for c in (m.get("complementosTabelados") or []) if c.get("nome")],
        })
    movimentos.sort(key=lambda x: x["data"] or "")
    return {
        "fonte": "DataJud",
        "id_fonte": src.get("id"),
        "numero_cnj": numero,
        "cnj_valido": bool(numero and cnj_valido(numero)),
        "tribunal": tribunal,
        "uf": UF_POR_TRIBUNAL.get(tribunal),
        "grau": src.get("grau"),
        "vara": orgao.get("nome"),
        "codigo_municipio_ibge": orgao.get("codigoMunicipioIBGE"),
        "classe_codigo": str((src.get("classe") or {}).get("codigo")),
        "classe_nome": (src.get("classe") or {}).get("nome"),
        "assuntos": [{"codigo": str(a.get("codigo")), "nome": a.get("nome")} for a in (src.get("assuntos") or [])],
        "data_ajuizamento": iso(parse_data(src.get("dataAjuizamento"))),
        "data_disponivel_fonte": iso(parse_data(src.get("dataHoraUltimaAtualizacao") or src.get("@timestamp"))),
        "nivel_sigilo": src.get("nivelSigilo") or 0,
        "movimentos": movimentos,
        "sistema": (src.get("sistema") or {}).get("nome"),
    }
