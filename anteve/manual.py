"""Manual do usuário: download e busca de dúvidas dentro do documento.

A busca por palavras-chave funciona sempre e aponta item e página do PDF. Com ANTHROPIC_API_KEY,
o Claude redige a resposta usando apenas os itens encontrados, e cada item citado precisa existir
no índice; qualquer falha da IA volta para o resultado por palavras-chave."""
import json
import math
import os
import re

from .config import CONFIG
from .normalize import chave_texto

PASTA = os.path.join(os.path.dirname(__file__), "static", "manual")
ARQUIVOS = {"docx": ("Anteve_Manual_do_Usuario.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
            "pdf": ("Anteve_Manual_do_Usuario.pdf", "application/pdf")}

_PARADAS = set("""a o as os um uma uns umas de da do das dos em na no nas nos por para pra com sem e ou que se ao aos
como qual quais quando onde porque pois isso esse essa este esta eu voce meu minha seu sua ser estar tem ter fazer faco
consigo posso pode preciso sistema tela antevê anteve nao sim mais muito ja ele ela eles elas lhe me mim
significa significado quer dizer diferenca entre quero gostaria saber duvida ajuda""".split())

# Palavras que as pessoas usam na dúvida e que o manual escreve de outro jeito
_SINONIMOS = {"esqueci": ["senha", "gerar"], "baixar": ["exportar", "planilha"], "download": ["exportar", "planilha"],
              "excel": ["planilha", "csv"], "logar": ["entrar", "login"], "entrar": ["login", "acesso"],
              "cadastrar": ["incluir"], "criar": ["incluir"], "apagar": ["excluir"], "remover": ["excluir"],
              "deletar": ["excluir"], "empresa": ["cnpj"], "advogado": ["partes", "oab"], "caiu": ["sessao", "login"],
              "deslogou": ["sessao", "login"], "email": ["canais", "preferencias"], "notificacao": ["alertas", "preferencias"],
              "atualizar": ["coleta"], "dados": ["coleta", "fontes"], "risco": ["preventivo", "score"]}


def _raiz(p):
    return p[:6] if len(p) > 6 else p


def _termos(texto):
    palavras = [w for w in re.findall(r"[a-z0-9]+", chave_texto(texto or "")) if len(w) >= 3 and w not in _PARADAS]
    extra = [s for w in palavras for s in _SINONIMOS.get(w, [])]
    return list(dict.fromkeys(_raiz(w) for w in palavras + extra))


_INDICE = None


def indice():
    global _INDICE
    if _INDICE is None:
        with open(os.path.join(PASTA, "indice.json"), encoding="utf-8") as f:
            _INDICE = json.load(f)
        for it in _INDICE["itens"]:
            it["_titulo"] = [_raiz(w) for w in re.findall(r"[a-z0-9]+", chave_texto(it["titulo"] + " " + it["secao"]))]
            it["_texto"] = [_raiz(w) for w in re.findall(r"[a-z0-9]+", chave_texto(it["texto"]))]
    return _INDICE


def secoes():
    vistos = []
    for it in indice()["itens"]:
        if it["secao"] not in vistos:
            vistos.append(it["secao"])
    return vistos


def _publico(it):
    return {k: it[k] for k in ("item", "titulo", "secao", "pagina", "texto")}


def _trecho(texto, termos, limite=2):
    frases = [f.strip() for f in re.split(r"(?<=[.:;])\s+|\n", texto) if f.strip()]
    pontuadas = sorted(((sum(1 for w in re.findall(r"[a-z0-9]+", chave_texto(f)) if _raiz(w) in termos), -i, f)
                        for i, f in enumerate(frases)), reverse=True)
    escolhidas = sorted([p for p in pontuadas[:limite] if p[0] > 0], key=lambda p: -p[1])
    pontuar = lambda f: f if f[-1] in ".:;?!" else f + "."
    return " ".join(pontuar(p[2]) for p in escolhidas) or (frases[0] if frases else "")


def buscar(pergunta, secao=None, limite=5):
    termos = _termos(pergunta)
    itens = [it for it in indice()["itens"] if not secao or it["secao"] == secao]
    if not termos:
        return {"termos": [], "resultados": [dict(_publico(it), trecho=_trecho(it["texto"], set()), relevancia=0) for it in itens[:limite]] if secao else []}
    n = len(indice()["itens"])
    df = {t: sum(1 for it in indice()["itens"] if t in it["_titulo"] or t in it["_texto"]) for t in termos}
    pontos = []
    for it in itens:
        s = 0.0
        for t in termos:
            tf = it["_texto"].count(t) + 3 * it["_titulo"].count(t)
            if tf:
                s += (1 + math.log(tf)) * math.log(1 + n / (df[t] or 1))
        cobertura = sum(1 for t in termos if t in it["_titulo"] or t in it["_texto"]) / len(termos)
        if s:
            pontos.append((s * (0.5 + cobertura), it))
    pontos.sort(key=lambda p: -p[0])
    maximo = pontos[0][0] if pontos else 1
    return {"termos": termos, "resultados": [dict(_publico(it), trecho=_trecho(it["texto"], set(termos)),
                                                 relevancia=round(100 * s / maximo)) for s, it in pontos[:limite]]}


_SISTEMA = """Você responde dúvidas de usuários do Antevê, um sistema de monitoramento de recuperações judiciais, \
usando apenas os trechos do Manual do Usuário fornecidos. Responda em português do Brasil, em até 6 frases curtas, \
com passos numerados quando a dúvida for "como fazer". Não use emojis nem travessões. Se os trechos não respondem \
à dúvida, diga isso em uma frase e sugira o item mais próximo. Termine com uma linha no formato exato \
"ITENS: <números dos itens usados, separados por vírgula>"."""


def responder(pergunta, secao=None):
    base = buscar(pergunta, secao)
    base["ia"] = None
    if not CONFIG.anthropic_api_key or not base["resultados"] or not (pergunta or "").strip():
        return base
    contexto = "\n\n".join(f"[Item {r['item']} | {r['titulo']} | página {r['pagina']}]\n{r['texto']}" for r in base["resultados"][:4])
    try:
        import anthropic
        cliente = anthropic.Anthropic(api_key=CONFIG.anthropic_api_key, timeout=25.0, max_retries=1)
        resp = cliente.beta.messages.create(
            model=CONFIG.modelo_manual, max_tokens=2000, system=_SISTEMA,
            betas=["server-side-fallback-2026-07-01"], extra_body={"fallbacks": "default"},
            output_config={"effort": "low"},
            messages=[{"role": "user", "content": f"<manual>\n{contexto}\n</manual>\n\nDúvida: {pergunta.strip()[:600]}"}])
    except Exception as exc:  # a busca por palavras-chave continua valendo
        base["ia_erro"] = type(exc).__name__
        return base
    if resp.stop_reason == "refusal":
        return base
    texto = "".join(b.text for b in resp.content if b.type == "text").strip()
    m = re.search(r"ITENS:\s*([0-9., ]+)\s*$", texto)
    corpo = texto[:m.start()].strip() if m else texto
    validos = {r["item"]: r for r in base["resultados"]}
    citados = [validos[c.strip()] for c in (m.group(1).split(",") if m else []) if c.strip() in validos]
    if corpo:
        base["ia"] = {"resposta": corpo, "citacoes": [{"item": c["item"], "titulo": c["titulo"], "pagina": c["pagina"]} for c in citados]}
    return base
