"""Gera a prévia estática do painel com dados reais (somente metadados públicos).
Uso: python -m anteve.snapshot saida.html"""
import json
import os
import sys

os.environ["ANTEVE_AGENDADOR"] = "0"
from . import api  # noqa: E402
from .normalize import agora, iso  # noqa: E402

LEITOR = {"id": 0, "nome": "prévia", "papel": "admin"}


def gerar(saida):
    procs = []
    for camada in ("rj", "outros"):
        procs += api.listar(status=None, tipo=None, uf=None, tribunal=None, idade=None, prioridade=None, q=None,
                            camada=camada, limite=2000, u=LEITOR)
    detalhados = []
    for p in procs:
        d = api._proc_publico(api.db.um("SELECT * FROM processos WHERE id=?", (p["id"],)), detalhado=True)
        d.pop("ia", None)
        for e in d["evidencias"]:
            e.pop("documento", None)
        detalhados.append(d)
    snap = {
        "gerado_em": iso(agora()),
        "processos": detalhados,
        "revisoes": api.revisoes(status="PENDENTE", fila=None, u=LEITOR),
        "alertas": api.alertas(u=LEITOR)[:150],
        "fontes": api.fontes(u=LEITOR),
        "metricas": api.metricas(u=LEITOR),
        "preventivo": [],
        "catalogo": api.catalogo(u=LEITOR),
    }
    html = open(os.path.join(os.path.dirname(__file__), "static", "index.html"), encoding="utf-8").read()
    dados = json.dumps(snap, ensure_ascii=False, default=str).replace("</", "<\\/").replace("\ufffd", "")
    html = html.replace("<script>\n(function(){", f"<script>window.ANTEVE_SNAPSHOT={dados};</script>\n<script>\n(function(){{", 1)
    open(saida, "w", encoding="utf-8").write(html)
    return len(detalhados), os.path.getsize(saida)


if __name__ == "__main__":
    print(gerar(sys.argv[1] if len(sys.argv) > 1 else "anteve_previa.html"))
