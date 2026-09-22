"""Normalizador: padroniza CNJ, CNPJ (inclusive alfanumérico), datas, nomes e textos."""
import hashlib
import json
import re
import unicodedata
from datetime import datetime, timedelta, timezone

TZ_BR = timezone(timedelta(hours=-3))

# ---------------------------------------------------------------- CNJ
_CNJ_RE = re.compile(r"(\d{7})-?(\d{2})\.?(\d{4})\.?(\d)\.?(\d{2})\.?(\d{4})")


def cnj_digitos(valor):
    return re.sub(r"\D", "", valor or "")


def cnj_dv(nnnnnnn, aaaa, j, tr, oooo):
    """Dígito verificador conforme Resolução CNJ 65/2008 (módulo 97)."""
    base = int(f"{nnnnnnn}{aaaa}{j}{tr}{oooo}00")
    return 98 - (base % 97)


def cnj_valido(valor):
    d = cnj_digitos(valor)
    if len(d) != 20:
        return False
    n, dd, a, j, tr, o = d[:7], d[7:9], d[9:13], d[13], d[14:16], d[16:20]
    return cnj_dv(n, a, j, tr, o) == int(dd)


def cnj_formatar(valor):
    d = cnj_digitos(valor)
    if len(d) != 20:
        return None
    return f"{d[:7]}-{d[7:9]}.{d[9:13]}.{d[13]}.{d[14:16]}.{d[16:20]}"


def extrair_cnjs(texto):
    achados = []
    for m in _CNJ_RE.finditer(texto or ""):
        f = cnj_formatar("".join(m.groups()))
        if f and cnj_valido(f) and f not in achados:
            achados.append(f)
    return achados


# ---------------------------------------------------------------- CNPJ
# Suporta o CNPJ alfanumérico (IN RFB 2.229/2024): 12 posições [0-9A-Z] + 2 DV numéricos.
_CNPJ_TXT_RE = re.compile(r"\b([0-9A-Z]{2}\.?[0-9A-Z]{3}\.?[0-9A-Z]{3}/?[0-9A-Z]{4}-?\d{2})\b")


def cnpj_limpar(valor):
    return re.sub(r"[^0-9A-Za-z]", "", valor or "").upper()


def _cnpj_calc_dv(base):
    def dv(parcial, pesos):
        soma = sum((ord(c) - 48) * p for c, p in zip(parcial, pesos))
        r = soma % 11
        return "0" if r < 2 else str(11 - r)
    d1 = dv(base, [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2])
    d2 = dv(base + d1, [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2])
    return d1 + d2


def cnpj_valido(valor):
    c = cnpj_limpar(valor)
    if len(c) != 14 or not re.fullmatch(r"[0-9A-Z]{12}\d{2}", c):
        return False
    if len(set(c)) == 1:
        return False
    return _cnpj_calc_dv(c[:12]) == c[12:]


def cnpj_raiz(valor):
    c = cnpj_limpar(valor)
    return c[:8] if len(c) == 14 else None


def cnpj_formatar(valor):
    c = cnpj_limpar(valor)
    if len(c) != 14:
        return None
    return f"{c[:2]}.{c[2:5]}.{c[5:8]}/{c[8:12]}-{c[12:]}"


def extrair_cnpjs(texto):
    achados = []
    for m in _CNPJ_TXT_RE.finditer((texto or "").upper()):
        c = cnpj_limpar(m.group(1))
        if cnpj_valido(c) and c not in achados:
            achados.append(c)
    return achados


# ---------------------------------------------------------------- Datas
def parse_data(valor):
    """Aceita os formatos observados no DataJud: yyyyMMddHHmmss, ISO com ou sem Z, data simples.
    Datas sem fuso são tratadas como horário de Brasília."""
    if valor is None or valor == "":
        return None
    if isinstance(valor, datetime):
        return valor if valor.tzinfo else valor.replace(tzinfo=TZ_BR)
    s = str(valor).strip()
    try:
        if re.fullmatch(r"\d{14}", s):
            return datetime.strptime(s, "%Y%m%d%H%M%S").replace(tzinfo=TZ_BR)
        if re.fullmatch(r"\d{8}", s):
            return datetime.strptime(s, "%Y%m%d").replace(tzinfo=TZ_BR)
        s2 = s.replace("Z", "+00:00")
        dt = datetime.fromisoformat(s2)
        return dt if dt.tzinfo else dt.replace(tzinfo=TZ_BR)
    except ValueError:
        return None


def iso(dt):
    return dt.astimezone(TZ_BR).isoformat(timespec="seconds") if dt else None


def agora():
    return datetime.now(TZ_BR)


def datajud_compacto(dt):
    """Formato exigido pelo filtro de dataAjuizamento do DataJud (validado em 22/09/2026)."""
    return dt.astimezone(TZ_BR).strftime("%Y%m%d%H%M%S")


# ---------------------------------------------------------------- Textos
def sem_acento(texto):
    return "".join(c for c in unicodedata.normalize("NFD", texto or "") if unicodedata.category(c) != "Mn")


def chave_texto(texto):
    return re.sub(r"\s+", " ", sem_acento(texto).lower()).strip()


def normalizar_razao_social(nome):
    n = re.sub(r"\s+", " ", (nome or "").strip()).upper()
    n = re.sub(r"\s*[-,]?\s*(EM RECUPERA[CÇ][AÃ]O JUDICIAL|EM RECUPERACAO JUDICIAL)\s*$", "", n)
    return n or None


def hash_obj(obj):
    bruto = obj if isinstance(obj, str) else json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(bruto.encode("utf-8")).hexdigest()
