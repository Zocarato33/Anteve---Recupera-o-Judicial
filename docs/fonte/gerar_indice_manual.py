"""Gera anteve/static/manual/indice.json a partir do markdown do manual e das páginas do PDF.
Uso: python docs/fonte/gerar_indice_manual.py docs/fonte/manual.md docs/fonte/manual.pag.json"""
import json
import re
import sys

md, pags = open(sys.argv[1], encoding="utf-8").read(), json.load(open(sys.argv[2], encoding="utf-8"))


def limpar(t):
    t = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", t)
    t = re.sub(r"\*\*|`", "", t).replace("\\", "")
    linhas = []
    for l in t.split("\n"):
        l = l.strip()
        if not l or re.match(r"^\|\s*-{3}", l):
            continue
        if l.startswith("|"):  # linha de tabela vira frase: "célula: célula; ..."
            cel = [c.strip() for c in l.strip("|").split("|")]
            l = cel[0] + ": " + "; ".join(c for c in cel[1:] if c)
        linhas.append(re.sub(r"^(\d+\.|-)\s+", "", l))
    return "\n".join(linhas)


itens, secao, atual = [], None, None
for bloco in re.split(r"(?m)^(?=#{2,3} )", md):
    cab = bloco.split("\n", 1)
    titulo, corpo = cab[0].lstrip("# ").strip(), (cab[1] if len(cab) > 1 else "")
    if bloco.startswith("## "):
        secao = titulo
        numero = titulo.split(".")[0]
        if limpar(corpo).strip():
            itens.append({"item": numero, "titulo": titulo.split(". ", 1)[-1], "secao": secao, "pagina": pags.get(titulo), "texto": limpar(corpo)})
    elif bloco.startswith("### ") and secao:
        m = re.match(r"^(\d+(?:\.\d+)+)\s+(.*)$", titulo)
        numero, nome = (m.group(1), m.group(2)) if m else (secao.split(".")[0], titulo)
        itens.append({"item": numero, "titulo": nome, "secao": secao, "pagina": pags.get(titulo), "texto": limpar(corpo)})
json.dump({"documento": "Antevê: Manual do Usuário", "versao": "1.0", "itens": itens},
          open("anteve/static/manual/indice.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(len(itens), "itens;", sum(1 for i in itens if i["pagina"] is None), "sem página")
