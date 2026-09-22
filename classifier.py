"""Classificador de IA (seção 7). Só é acionado quando já existe evidência estruturada
(textos oficiais coletados). A IA não navega e não completa lacunas por memória.
As regras posteriores ao modelo (7.1) são aplicadas sempre, independentemente da resposta."""
import json

import requests

from .config import CONFIG
from .normalize import agora, hash_obj, iso

VERSAO_PROMPT = "prompt-classificador-1.0"

CATEGORIAS = {
    "RJ_PEDIDO_NOVO", "RJ_TUTELA_ANTECEDENTE", "RJ_PROCESSAMENTO_DEFERIDO", "RJ_PROCESSAMENTO_INDEFERIDO",
    "RJ_PLANO_APRESENTADO", "RJ_CONCEDIDA", "RJ_FALENCIA", "RECUPERACAO_EXTRAJUDICIAL", "PEDIDO_FALENCIA",
    "SINAL_PREVENTIVO", "INCIDENTE_RELACIONADO", "MERA_MENCAO", "NAO_RELACIONADO", "REVISAO_MANUAL",
}

PROMPT = """FUNÇÃO
Você é um classificador jurídico de processos empresariais brasileiros. Analise somente os dados e documentos fornecidos. Sua tarefa é identificar pedidos e eventos de recuperação judicial e apontar sinais preventivos sem transformar indícios em fatos.

OBJETIVO
Classificar o registro em uma única categoria:
RJ_PEDIDO_NOVO | RJ_TUTELA_ANTECEDENTE | RJ_PROCESSAMENTO_DEFERIDO |
RJ_PROCESSAMENTO_INDEFERIDO | RJ_PLANO_APRESENTADO | RJ_CONCEDIDA |
RJ_FALENCIA | RECUPERACAO_EXTRAJUDICIAL | PEDIDO_FALENCIA |
SINAL_PREVENTIVO | INCIDENTE_RELACIONADO | MERA_MENCAO | NAO_RELACIONADO |
REVISAO_MANUAL.

REGRAS
1. Considere recuperação confirmada apenas com número processual e evidência oficial inequívoca.
2. Não classifique como novo pedido uma habilitação, impugnação, recurso, cumprimento ou processo individual relacionado.
3. Não confunda recuperação judicial com recuperação extrajudicial, falência, insolvência civil ou liquidação.
4. Diferencie a empresa requerente de credores, terceiros, sócios, administradores e empresas apenas mencionadas.
5. Use CNPJ como identificador prioritário. Se houver somente nome semelhante, solicite revisão manual.
6. Uma citação de lei ou jurisprudência não comprova que o processo é recuperacional.
7. Se classe e documento divergirem, descreva a divergência e retorne REVISAO_MANUAL.
8. Para evento preventivo, declare literalmente: "Recuperação judicial não confirmada".
9. Não invente CNPJ, datas, valores, partes, páginas, decisões ou links.
10. Toda conclusão deve apontar uma ou mais evidências fornecidas.

ENTRADA
<registro_normalizado>
{registro_normalizado}
</registro_normalizado>
<textos_e_documentos_publicos>
{textos_e_documentos_publicos}
</textos_e_documentos_publicos>
<dicionario_tpu_versionado>
{dicionario_tpu_versionado}
</dicionario_tpu_versionado>

SAÍDA
Retorne JSON válido, sem comentários e sem texto fora do JSON:
{{
  "classificacao": "",
  "confirmado": true,
  "empresa_requerente": [{{"razao_social":"","cnpj":"","confianca":0.0}}],
  "numero_cnj": "",
  "processo_principal": "",
  "data_evento": "",
  "estagio": "",
  "fundamentos": [""],
  "evidencias": [{{"fonte":"","documento":"","pagina":"","trecho_resumido":""}}],
  "divergencias": [""],
  "confianca": 0.0,
  "necessita_revisao_humana": true
}}"""


def montar_prompt(registro, documentos, tpu):
    return PROMPT.format(
        registro_normalizado=json.dumps(registro, ensure_ascii=False, indent=1),
        textos_e_documentos_publicos=json.dumps(documentos, ensure_ascii=False, indent=1),
        dicionario_tpu_versionado=json.dumps({"versao": tpu["versao"], "classes": tpu["tabelas"]["classes"]}, ensure_ascii=False))


def validar_saida(texto, registro, documentos):
    """Regras posteriores ao modelo (7.1). Retorna (saida_ajustada | None, rejeicoes)."""
    rejeicoes = []
    bruto = (texto or "").strip()
    if bruto.startswith("```"):
        rejeicoes.append("resposta com texto fora do JSON (cerca de código)")
        return None, rejeicoes
    try:
        saida = json.loads(bruto)
    except ValueError:
        return None, ["resposta não é JSON válido"]
    if not isinstance(saida, dict):
        return None, ["resposta JSON não é objeto"]
    if saida.get("classificacao") not in CATEGORIAS:
        return None, [f"categoria fora da enumeração: {saida.get('classificacao')}"]
    niveis = {d.get("nivel") for d in documentos} | ({"B"} if registro.get("classe_codigo") else set())
    tem_cnj = bool(registro.get("numero_cnj")) and registro.get("cnj_valido", True)
    if saida.get("confirmado") and not (tem_cnj and niveis & {"A", "B"}):
        saida["confirmado"] = False
        rejeicoes.append("confirmado=true rejeitado: sem número CNJ e evidência de nível A ou B")
    # CNPJ só vale se aparecer literalmente nos textos fornecidos (regra 9: não inventar)
    corpus = json.dumps(documentos, ensure_ascii=False)
    from .normalize import cnpj_limpar, cnpj_valido
    corpus_limpo = "".join(ch for ch in corpus.upper() if ch.isalnum())
    empresas_validas = []
    for e in saida.get("empresa_requerente") or []:
        c = cnpj_limpar(e.get("cnpj"))
        if c and (not cnpj_valido(c) or c not in corpus_limpo):
            rejeicoes.append(f"CNPJ {e.get('cnpj')} não consta nos documentos ou é inválido: descartado")
            e["cnpj"] = ""
        empresas_validas.append(e)
    saida["empresa_requerente"] = empresas_validas
    tem_cnpj = any(e.get("cnpj") for e in empresas_validas)
    tem_doc = any(d.get("nivel") in ("A", "B") for d in documentos)
    conf = float(saida.get("confianca") or 0)
    if not tem_cnpj or not tem_doc:
        if conf > 0.70:
            rejeicoes.append("confiança limitada a 0,70: sem CNPJ ou documento oficial")
        conf = min(conf, 0.70)
    saida["confianca"] = round(conf, 2)
    if [d for d in saida.get("divergencias") or [] if d]:
        saida["necessita_revisao_humana"] = True
    if saida["classificacao"] == "SINAL_PREVENTIVO":
        fund = saida.get("fundamentos") or []
        if not any("Recuperação judicial não confirmada" in f for f in fund):
            fund.append("Recuperação judicial não confirmada")
        saida["fundamentos"] = fund
        saida["confirmado"] = False
    if not saida.get("evidencias"):
        saida["necessita_revisao_humana"] = True
        rejeicoes.append("conclusão sem evidência apontada: revisão humana obrigatória")
    return saida, rejeicoes


def classificar(db, processo_id, registro, documentos, tpu, chamador=None):
    """Executa o modelo e registra auditoria. `chamador` permite injetar um cliente (testes)."""
    if not documentos:
        return None  # sem evidência estruturada, a IA não é acionada
    prompt = montar_prompt(registro, documentos, tpu)
    h = hash_obj(prompt)
    if chamador is None:
        if not CONFIG.anthropic_api_key:
            return None
        chamador = _chamar_anthropic
    texto, uso = chamador(prompt)
    saida, rejeicoes = validar_saida(texto, registro, documentos)
    db.exec("INSERT INTO ia_execucoes(processo_id,modelo,versao_prompt,hash_entrada,tokens_entrada,tokens_saida,resposta,aceita,rejeicoes,ts)"
            " VALUES(?,?,?,?,?,?,?,?,?,?)",
            (processo_id, CONFIG.modelo_ia, VERSAO_PROMPT, h, uso.get("input_tokens"), uso.get("output_tokens"),
             texto, int(saida is not None), db.dump(rejeicoes), iso(agora())))
    return {"saida": saida, "rejeicoes": rejeicoes, "hash_entrada": h}


def _chamar_anthropic(prompt):
    r = requests.post("https://api.anthropic.com/v1/messages", timeout=120, headers={
        "x-api-key": CONFIG.anthropic_api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
        json={"model": CONFIG.modelo_ia, "max_tokens": 2000, "temperature": 0,
              "messages": [{"role": "user", "content": prompt}]})
    r.raise_for_status()
    d = r.json()
    texto = "".join(b.get("text", "") for b in d.get("content", []) if b.get("type") == "text")
    return texto, d.get("usage", {})
