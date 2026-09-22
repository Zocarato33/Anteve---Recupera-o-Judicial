"""Ponto de entrada da função Python no Vercel. Todas as rotas (painel e API) passam por aqui."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from anteve.api import app  # noqa: E402,F401
