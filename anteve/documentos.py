"""Leitura determinística de publicações oficiais (DJEN, decisões, editais).
Identifica o ato praticado, a empresa requerente e o administrador judicial. Tudo que
for extraído aponta para o trecho de origem; nada é inferido sem texto."""
import re

from .normalize import chave_texto, cnj_formatar, cnpj_limpar, extrair_cnpjs, normalizar_razao_social
from .tpu import TERMOS

_ANCORAS_REQUERENTE = ["recuperanda", "requerente", "autora", "devedora", "requer o processamento"]
_ANCORAS_TERCEIRO = ["credor", "credora", "impugnante", "habilitante", "reu", "requerida", "terceiro interessado"]


def _contem(txt, grupo):
    return [t for t in TERMOS[grupo] if t in txt]


def detectar_ato(texto):
    t = chave_texto(texto)
    achados = {g: _contem(t, g) for g in TERMOS}
    if achados["EXTRAJUDICIAL"] and not achados["PEDIDO"]:
        return "EXTRAJUDICIAL", achados["EXTRAJUDICIAL"]
    if any(x in t for x in ("convolo em falencia", "convolo a recuperacao judicial em falencia", "decreto a falencia")):
        return "CONVOLACAO", ["convolação ou decreto de falência"]
    if any(x in t for x in ("indefiro o processamento", "indeferimento do processamento", "indefiro o pedido de recuperacao")):
        return "INDEFERIMENTO", ["indeferimento do processamento"]
    if "defiro o processamento" in t or ("nomeio" in t and "administrador judicial" in t and "recupera" in t):
        return "DEFERIMENTO", achados["DEFERIMENTO"] or ["deferimento do processamento"]
    if achados["TUTELA"] and "recuperacao judicial" in t:
        return "TUTELA_ANTECEDENTE", achados["TUTELA"]
    if achados["CREDORES"] and ("edital" in t or "relacao de credores" in t):
        return "EDITAL_CREDORES", achados["CREDORES"]
    if achados["PEDIDO"]:
        return "DISTRIBUICAO", achados["PEDIDO"]
    if "recuperacao judicial" in t:
        return "MERA_MENCAO", ["menção a recuperação judicial sem ato do processo"]
    return None, []


def extrair_requerentes(texto, destinatarios=None):
    """CNPJs próximos de âncoras de requerente; ignora os próximos de âncoras de terceiros."""
    up = texto or ""
    baixo = chave_texto(up)
    resultado = []
    for c in extrair_cnpjs(up):
        # localizar a posição aproximada do CNPJ no texto normalizado
        fmt = f"{c[:2]}.{c[2:5]}.{c[5:8]}/{c[8:12]}-{c[12:]}".lower()
        pos = baixo.find(fmt)
        if pos < 0:
            pos = baixo.find(c.lower())
        janela = baixo[max(0, pos - 220): pos + 60] if pos >= 0 else ""
        req = any(a in janela for a in _ANCORAS_REQUERENTE)
        terc = any(a in janela for a in _ANCORAS_TERCEIRO)
        nome = None
        m = re.search(r"([A-ZÀ-Ü0-9][A-ZÀ-Ü0-9 .,&'/-]{3,120}?)\s*[,(-]?\s*(?:inscrita|inscrito|pessoa jur[ií]dica|CNPJ)",
                      up[max(0, pos - 200): pos + 20] if pos >= 0 else "", re.I)
        if m:
            nome = normalizar_razao_social(m.group(1))
        resultado.append({"cnpj": cnpj_limpar(c), "razao_social": nome, "papel": "REQUERENTE" if req and not terc else ("TERCEIRO" if terc else "INDEFINIDO")})
    for d in destinatarios or []:
        if (d.get("polo") or "").upper() in ("A", "ATIVO") and d.get("nome"):
            resultado.append({"cnpj": None, "razao_social": normalizar_razao_social(d["nome"]), "papel": "REQUERENTE_POLO_ATIVO"})
    return resultado


def extrair_administrador(texto):
    m = re.search(r"nomeio\s+(?:como\s+)?administrador(?:a)?\s+judicial\s*[:,]?\s*(?:(?:a|o)\s+)?([A-ZÀ-Ü][\wÀ-ü .&'-]{3,120}?)(?:[,.;]|\s+inscrit|\s+CNPJ|\s+que)",
                  texto or "", re.I)
    return m.group(1).strip() if m else None


def analisar_publicacao(pub, numero_cnj_esperado=None):
    ato, termos = detectar_ato(pub.get("texto"))
    cnj_pub = cnj_formatar(pub.get("numero_cnj") or "")
    vinculada = not numero_cnj_esperado or cnj_pub == numero_cnj_esperado
    return {
        "ato": ato if vinculada else None,
        "termos": termos,
        "vinculada": vinculada,
        "nivel": "B" if vinculada else "D",  # publicação oficial inequívoca vinculada ao CNJ
        "requerentes": extrair_requerentes(pub.get("texto"), pub.get("destinatarios")),
        "administrador_judicial": extrair_administrador(pub.get("texto")),
        "resumo": _resumo(ato, termos),
    }


def _resumo(ato, termos):
    rotulos = {
        "DEFERIMENTO": "Publicação oficial com deferimento do processamento da recuperação judicial",
        "INDEFERIMENTO": "Publicação oficial com indeferimento do processamento",
        "CONVOLACAO": "Publicação oficial com convolação ou decreto de falência",
        "TUTELA_ANTECEDENTE": "Publicação oficial de tutela cautelar antecedente preparatória",
        "EDITAL_CREDORES": "Edital ou relação de credores publicado",
        "DISTRIBUICAO": "Publicação oficial referente a pedido de recuperação judicial",
        "EXTRAJUDICIAL": "Publicação oficial referente a recuperação extrajudicial",
        "MERA_MENCAO": "Publicação apenas menciona recuperação judicial",
    }
    base = rotulos.get(ato, "Publicação sem ato recuperacional identificado")
    return base + (f" (termos: {', '.join(termos[:3])})" if termos else "")
