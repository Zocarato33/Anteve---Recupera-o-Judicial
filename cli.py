"""Linha de comando do Antevê.

  python -m anteve.cli iniciar --nome "Admin" --papel admin
  python -m anteve.cli coletar --tribunais tjsp,tjrj
  python -m anteve.cli reconciliar --dias 30
  python -m anteve.cli tpu
  python -m anteve.cli servir --porta 8000
"""
import argparse
import json
import os

from .config import CONFIG
from .db import DB


def main():
    ap = argparse.ArgumentParser(prog="anteve")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("iniciar", help="cria o banco e um usuário com token")
    s.add_argument("--nome", default="Administrador")
    s.add_argument("--papel", default="admin", choices=["admin", "analista", "comercial", "leitor"])
    s = sub.add_parser("coletar", help="ciclo incremental (DataJud + diário)")
    s.add_argument("--tribunais", default=None)
    s.add_argument("--dias-iniciais", type=int, default=30)
    s = sub.add_parser("reconciliar", help="reconciliação por data de ajuizamento")
    s.add_argument("--tribunais", default=None)
    s.add_argument("--dias", type=int, default=CONFIG.reconciliacao_diaria_dias)
    sub.add_parser("tpu", help="sincroniza o dicionário TPU com o SGT/CNJ")
    s = sub.add_parser("servir", help="sobe API, painel e agendador")
    s.add_argument("--porta", type=int, default=8000)
    s.add_argument("--host", default="0.0.0.0")
    a = ap.parse_args()

    db = DB(CONFIG.db_path)
    from . import orchestrator, tpu
    tpu.carregar(db)
    trib = [t.strip().lower() for t in a.tribunais.split(",")] if getattr(a, "tribunais", None) else CONFIG.tribunais

    if a.cmd == "iniciar":
        token = db.criar_usuario(a.nome, a.papel)
        print(f"Usuário {a.nome} ({a.papel}) criado. Guarde o token, ele não será exibido novamente:\n{token}")
    elif a.cmd == "coletar":
        res = [orchestrator.coletar_tribunal(db, t, inicio_inicial_dias=a.dias_iniciais) for t in trib]
        res.append({"diario": orchestrator.enriquecer_com_diario(db)})
        print(json.dumps(res, ensure_ascii=False, indent=1))
    elif a.cmd == "reconciliar":
        print(json.dumps([orchestrator.coletar_tribunal(db, t, modo="reconciliacao", dias=a.dias) for t in trib], ensure_ascii=False, indent=1))
    elif a.cmd == "tpu":
        print(json.dumps(tpu.sincronizar(db), ensure_ascii=False, indent=1))
    elif a.cmd == "servir":
        import uvicorn
        os.environ.setdefault("ANTEVE_AGENDADOR", "1")
        uvicorn.run("anteve.api:app", host=a.host, port=a.porta)


if __name__ == "__main__":
    main()
