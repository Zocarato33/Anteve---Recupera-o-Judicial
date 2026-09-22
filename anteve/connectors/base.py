"""Cliente HTTP comum: backoff exponencial com jitter, respeito a Retry-After e
distinção explícita entre "fonte indisponível" e "nenhum resultado" (seção 8.2)."""
import random
import time

import requests

from ..config import CONFIG


class FonteIndisponivel(Exception):
    """A fonte falhou. Ausência de resposta NUNCA deve ser lida como ausência de processo."""


class MudancaDeEsquema(Exception):
    """O formato de retorno mudou. O conector deve ser interrompido e a equipe alertada."""


def requisitar(metodo, url, tentativas=5, base=1.5, teto=60, **kw):
    kw.setdefault("timeout", 60)
    headers = kw.pop("headers", {}) or {}
    headers.setdefault("User-Agent", CONFIG.user_agent)
    ultimo = None
    for n in range(tentativas):
        try:
            r = requests.request(metodo, url, headers=headers, **kw)
        except requests.RequestException as exc:
            ultimo = f"erro de rede: {exc}"
        else:
            if r.status_code == 429 or r.status_code >= 500:
                ultimo = f"HTTP {r.status_code}"
                espera = r.headers.get("Retry-After")
                if espera and espera.isdigit():
                    time.sleep(min(int(espera), teto))
                    continue
            elif r.status_code in (401, 403):
                raise FonteIndisponivel(f"acesso negado (HTTP {r.status_code}); verificar chave, termos ou bloqueio geográfico")
            else:
                return r
        # backoff exponencial com jitter completo
        time.sleep(random.uniform(0, min(teto, base * (2 ** n))))
    raise FonteIndisponivel(ultimo or "falha desconhecida")
