import sys, json, pymupdf
pdf, indice, saida = sys.argv[1:4]
doc = pymupdf.open(pdf); itens = json.load(open(indice))
textos = [[l.strip() for l in p.get_text().split("\n")] for p in doc]
sumario = [i for i, t in enumerate(textos) if any("....." in l for l in t) or "Sumário" in t]
pags, pos = {}, (max(sumario) + 1 if sumario else 1)
for it in itens:
    for p in range(pos, len(textos)):
        if it["texto"] in textos[p]:
            pags[it["texto"]] = p + 1; pos = p; break
faltam = [it["texto"] for it in itens if it["texto"] not in pags]
json.dump(pags, open(saida, "w"), ensure_ascii=False, indent=1)
print("paginas:", len(doc), "| localizados:", len(pags), "/", len(itens), "| faltam:", faltam)
