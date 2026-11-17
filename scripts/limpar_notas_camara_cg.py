#!/usr/bin/env python3
"""
Cofre Aberto MS — limpa o texto das notas da verba indenizatória dos vereadores de Campo Grande

As notas vêm de PDFs digitalizados da Câmara (lidos por OCR em coletar_verba_camara_cg.py), e o OCR deixa restos:
"/26 ROSENEIDE GOULART", "APN LOCACOES »", "“+ — NFOO617/U «| DIVULGAÇÃO ATIVIDADE PARLAMENTAR".

  fornecedor  quando o CNPJ está no cadastro da Receita (dados/cnpj_cache.json), usa a razão social oficial;
              senão, tira os restos do começo e do fim
  descricao   tira os pedaços de número de nota e os símbolos que o OCR inventa
  cnpj        formata 00.000.000/0000-00

O texto lido pelo OCR fica guardado em fornecedorOCR / descricaoOCR (nada se perde). Valores e datas não são mexidos.
Roda no fim da coleta, antes de gerar o painel e as páginas.
"""

import json, re, unicodedata
from pathlib import Path

DADOS = Path(__file__).parent.parent / "dados"


def dig(t):
    return re.sub(r"\D", "", str(t or ""))


GENERICAS = {"LTDA", "COMERCIO", "SERVICOS", "EIRELI", "EMPRESA", "BRASIL", "GRANDE", "CAMPO", "POSTO", "AUTO", "DISTRIBUIDORA", "COMUNICACAO", "PUBLICIDADE"}


def palavras(t):
    import unicodedata
    t = "".join(ch for ch in unicodedata.normalize("NFD", (t or "").upper()) if unicodedata.category(ch) != "Mn")
    return {w for w in re.findall(r"[A-Z]{4,}", t) if w not in GENERICAS}

def nome_confere(lido, razao, fantasia=None):
    """O nome lido no PDF tem alguma palavra do nome na Receita? Também aceita palavra grudada pelo OCR ("APNLOCACOES")."""
    oficiais = palavras(razao) | palavras(fantasia)
    if palavras(lido) & oficiais:
        return True
    comp = "".join(ch for ch in unicodedata.normalize("NFD", (lido or "").upper()) if unicodedata.category(ch) != "Mn")
    comp = re.sub(r"[^A-Z]", "", comp)
    return any(len(w) >= 5 and w in comp for w in oficiais)



def limpa_nome(t):
    t = re.sub(r"^[\W\d]*?(?:/\d{2}\s+)?", "", t or "")            # "/26 NOME"
    t = re.sub(r"[«»“”\"|_~^]+", " ", t)
    t = re.sub(r"\s+[A-Z]$", "", t.strip())                        # letra solta no fim ("... GOULART N")
    t = re.sub(r"\s+", " ", t).strip(" -—–.,;:/")
    return t


def limpa_desc(t):
    t = t or ""
    t = re.sub(r"N\s*F\s*[:.ºo°O0]*\s*[O0]*\d+\s*/\s*U\b", " ", t, flags=re.I)   # NF:00920/U, NFOO617/U
    t = re.sub(r"(?<!\w)/\s*U\b", " ", t)
    t = re.sub(r"[«»“”\"|+_~^]+", " ", t)
    t = re.sub(r"^[\W\d]+", "", t)
    t = re.sub(r"\s+", " ", t).strip(" -—–.,;:/")
    return t


def fmt_cnpj(t):
    d = dig(t)
    return f"{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:]}" if len(d) == 14 else (t or None)


def main():
    arq = DADOS / "camara_municipal.json"
    try:
        cm = json.load(open(arq, encoding="utf-8"))
    except Exception as e:
        print(f"⚠️ sem camara_municipal.json: {e}")
        return
    try:
        cad = json.load(open(DADOS / "cnpj_cache.json", encoding="utf-8"))
    except Exception:
        cad = {}
    n_nome = n_desc = n_rfb = 0
    for v in cm.get("vereadores") or []:
        for d in v.get("despesas") or []:
            f0 = d.get("fornecedorOCR") or d.get("fornecedor") or ""
            s0 = d.get("descricaoOCR") or d.get("descricao") or ""
            c = cad.get(dig(d.get("cnpj"))) or {}
            razao = c.get("razao")
            # só troca pela razão social se o nome lido no PDF tiver alguma palavra dela ou do nome fantasia —
            # se o OCR errou o CNPJ, não põe o nome de outra empresa na nota
            if razao and not nome_confere(f0, razao, c.get("fantasia")):
                razao = None
            f1 = re.sub(r"\s+", " ", razao).strip() if razao else limpa_nome(f0)
            s1 = limpa_desc(s0)
            if f1 and f1 != f0:
                d["fornecedorOCR"], d["fornecedor"] = f0, f1
                n_nome += 1
                n_rfb += bool(razao)
            if s1 and s1 != s0:
                d["descricaoOCR"], d["descricao"] = s0, s1
                n_desc += 1
            if d.get("cnpj"):
                d["cnpj"] = fmt_cnpj(d["cnpj"])
    arq.write_text(json.dumps(cm, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✅ notas da Câmara de CG: {n_nome} nomes de fornecedor corrigidos ({n_rfb} pela Receita) e {n_desc} descrições limpas")


if __name__ == "__main__":
    main()
