#!/usr/bin/env python3
"""
Cofre Aberto MS — resumo da conferência manual dos supersalários

Lê dados/verificacao/conferencia_manual.csv depois de preenchida a coluna "conferido"
(S = confere com o contracheque original · N = erro · vazio = ainda não conferido) e grava
dados/verificacao/resumo_conferencia.json com:
  - por grupo e por órgão: total, conferidos, com erro, pendentes
  - para os grupos sorteados ("intermediario" e "amostra"): taxa de erro observada e limite superior com 95% de
    confiança pelo método exato de Clopper–Pearson (unilateral; 0 erros em 100 → ≈ 2,95%)

Uso: python3 scripts/verificacao/resumo_conferencia.py
"""

import collections, csv, json, sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
CSV = ROOT / "dados" / "verificacao" / "conferencia_manual.csv"
SAIDA = ROOT / "dados" / "verificacao" / "resumo_conferencia.json"
CONF = 0.95


def binom_cdf(k, n, p):
    from math import comb
    return sum(comb(n, i) * p ** i * (1 - p) ** (n - i) for i in range(k + 1))


def clopper_pearson_sup(erros, n, conf=CONF):
    """Limite superior unilateral exato: o p tal que P(X ≤ erros | n, p) = 1 − conf."""
    if n <= 0:
        return None
    if erros >= n:
        return 1.0
    lo, hi, alfa = erros / n, 1.0, 1 - conf
    for _ in range(80):
        m = (lo + hi) / 2
        if binom_cdf(erros, n, m) > alfa:
            lo = m
        else:
            hi = m
    return hi


def contar(linhas):
    v = [(x.get("conferido") or "").strip().upper() for x in linhas]
    return {"total": len(linhas), "conferidos": sum(1 for c in v if c in ("S", "N")), "comErro": sum(1 for c in v if c == "N"),
            "pendentes": sum(1 for c in v if c not in ("S", "N"))}


def main():
    global CSV, SAIDA
    a = lambda n, d: Path(sys.argv[sys.argv.index(n) + 1]) if n in sys.argv else d
    CSV, SAIDA = a("--csv", CSV), a("--saida", SAIDA)
    if not CSV.exists():
        print(f"❌ {CSV} não existe — rode gerar_conferencia.py antes")
        return 1
    with open(CSV, encoding="utf-8") as f:
        linhas = list(csv.DictReader(f))
    grupos = collections.defaultdict(list)
    for x in linhas:
        grupos[x["grupo"]].append(x)
    out = {"geradoEm": datetime.now().isoformat(timespec="seconds"), "confianca": CONF, "metodo": "Clopper–Pearson exato, unilateral",
           "legenda": {"S": "confere com o contracheque original", "N": "erro (não confere)", "": "não conferido"}, "grupos": {}}
    for g, ls in grupos.items():
        r = contar(ls)
        r["prioritarios"] = contar([x for x in ls if x.get("prioridade") == "S"]) if g == "supersalario" else None
        if g in ("intermediario", "amostra"):
            n, e = r["conferidos"], r["comErro"]
            r["taxaErroObservada"] = round(e / n, 4) if n else None
            sup = clopper_pearson_sup(e, n)
            r["limiteSuperior95"] = round(sup, 4) if sup is not None else None
        por = collections.defaultdict(list)
        for x in ls:
            por[x["orgao"]].append(x)
        r["porOrgao"] = {o: contar(v) for o, v in sorted(por.items())}
        out["grupos"][g] = r
    meses = sorted({x["mes"] for x in linhas})
    out["mes"] = meses[-1] if meses else None
    out["orgaosNaFolha"] = len({x["orgao"] for x in linhas})
    SAIDA.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    for g, r in out["grupos"].items():
        extra = f" · taxa de erro {r['taxaErroObservada']:.1%} (limite 95%: {r['limiteSuperior95']:.1%})" if r.get("limiteSuperior95") is not None else ""
        print(f"  {g}: {r['conferidos']} de {r['total']} conferidos, {r['comErro']} com erro{extra}")
    print(f"✅ {SAIDA}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
