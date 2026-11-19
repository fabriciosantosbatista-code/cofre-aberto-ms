#!/usr/bin/env python3
"""
Cofre Aberto MS — transferências da União para MS no ano (por tipo, ministério e município)

Fonte: Portal da Transparência do Governo Federal (CGU), arquivo mensal de transferências
(download-de-dados/transferencias/AAAAMM, sem chave). Alimenta as páginas de município (/municipio/)
e o CSV dados/csv/uniao_transferencias_ms.csv.

Cache por mês em dados/transferencias_uniao_ms_cache.json (os 3 meses mais recentes são relidos a cada coleta);
gera dados/transferencias_uniao_ms.json.
Uso: python3 scripts/coletar_transferencias_uniao_ms.py
"""

import csv, io, json, sys, time, zipfile
from datetime import date, datetime
from pathlib import Path

import requests

DADOS = Path(__file__).parent.parent / "dados"
CACHE = DADOS / "transferencias_uniao_ms_cache.json"
SAIDA = DADOS / "transferencias_uniao_ms.json"
PORTAL = "https://portaldatransparencia.gov.br/download-de-dados/{}"
UA = {"User-Agent": "Mozilla/5.0 (CofreAbertoMS; +https://cofreabertoms.com.br)"}
HOJE = date.today()
ANO = HOJE.year
csv.field_size_limit(10**7)


def num(t):
    try:
        return float(str(t).replace(".", "").replace(",", "."))
    except ValueError:
        return 0.0



def zip_local(caminho):
    """Baixa um zip pequeno inteiro (CPGF, orçamento, transferências)."""
    for t in range(3):
        try:
            r = requests.get(PORTAL.format(caminho), headers=UA, timeout=300)
            if r.status_code == 200 and r.content[:2] == b"PK":
                z = zipfile.ZipFile(io.BytesIO(r.content))
                if z.testzip() is None:
                    return z
            elif r.status_code in (403, 404):
                return None  # mês ainda não publicado
        except (requests.RequestException, zipfile.BadZipFile):
            pass
        time.sleep(5 * (t + 1))
    return None



def linhas(z, filtro=None):
    nome = next(n for n in z.namelist() if filtro is None or filtro in n)
    return csv.DictReader(io.TextIOWrapper(z.open(nome), encoding="latin1"), delimiter=";")



def meses(ini, fim):
    a, m = ini
    while (a, m) <= fim:
        yield a, m
        a, m = (a + 1, 1) if m == 12 else (a, m + 1)



def transferencias_ms(cache):
    tc = cache.setdefault("transferencias", {})
    for a, m in meses((ANO, 1), (ANO, HOJE.month)):
        k = f"{a}{m:02d}"
        if k in tc and (a, m) < ((HOJE.year * 12 + HOJE.month - 3) // 12, (HOJE.year * 12 + HOJE.month - 3) % 12 + 1):
            continue
        z = zip_local(f"transferencias/{k}")
        if z is None:
            continue
        tipo, orgao, mun = {}, {}, {}
        for x in linhas(z):
            if x["UF"] != "MS":
                continue
            v = num(x["VALOR TRANSFERIDO"])
            tipo[x["TIPO TRANSFERÊNCIA"]] = tipo.get(x["TIPO TRANSFERÊNCIA"], 0) + v
            o = x["NOME ÓRGÃO"] if x["NOME ÓRGÃO"] != "Sem informação" else "Transferências constitucionais (FPE, FPM e outras)"
            orgao[o] = orgao.get(o, 0) + v
            nm = (x["NOME MUNICÍPIO"] or "").strip().title() or ("Governo do Estado" if "Estadual" in x["TIPO FAVORECIDO"] else "Outros favorecidos")
            mun[nm] = mun.get(nm, 0) + v
        tc[k] = {"tipo": tipo, "orgao": orgao, "municipio": mun}
        print(f"  transferências {k}: R$ {sum(tipo.values()):,.0f} para MS")
    agg = {"tipo": {}, "orgao": {}, "municipio": {}}
    for k, v in tc.items():
        if k.startswith(str(ANO)):
            for c in agg:
                for n, val in v[c].items():
                    agg[c][n] = agg[c].get(n, 0) + val
    ult = max((k for k in tc if k.startswith(str(ANO))), default=None)
    return {"ano": ANO, "ate": f"{ult[4:]}/{ult[:4]}" if ult else None, "total": round(sum(agg["tipo"].values()), 2),
            **{c: [{"nome": n, "valor": round(v, 2)} for n, v in sorted(agg[c].items(), key=lambda kv: -kv[1]) if v]
               for c in agg}}



def main():
    try:
        cache = json.load(open(CACHE, encoding="utf-8"))
    except Exception:
        cache = {}
    try:
        anterior = json.load(open(SAIDA, encoding="utf-8"))
    except Exception:
        anterior = {}
    try:
        ms = transferencias_ms(cache)
    except Exception as e:
        print(f"  ⚠️ transferências: {e} — mantido o anterior")
        if not anterior:
            return 1
        return 0
    finally:
        CACHE.write_text(json.dumps(cache, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    saida = {"ultimaAtualizacao": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
             "fonte": "Portal da Transparência do Governo Federal (CGU) — transferências (dados abertos)", **ms}
    SAIDA.write_text(json.dumps(saida, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"✅ transferencias_uniao_ms.json — R$ {saida['total']:,.0f} para MS em {ANO} (até {saida['ate']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
