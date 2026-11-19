#!/usr/bin/env python3
"""Cofre Aberto MS — o teto está definido (config/teto.json) para todo mês de contracheque publicado em Supersalários.
Uso: python3 tests/test_teto.py   (código 1 se algum mês ficar sem teto)"""
import json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts" / "verificacao"))
sys.path.insert(0, str(ROOT / "scripts"))
import conferencia_supersalarios as cs  # noqa: E402

oks, erros = [], []
check = lambda c, m: (oks if c else erros).append(m)
vs = cs.tetos()
check(all(v.get("valor") and v.get("desde") and v.get("lei") for v in vs), "toda versão do teto tem valor, data de início e lei")
check([v["desde"] for v in vs] == sorted(v["desde"] for v in vs), "versões em ordem de data")
check(cs.teto_do_mes("01/2025", vs)["valor"] == 44008.52 and cs.teto_do_mes("02/2025", vs)["valor"] == 46366.19, "o teto muda no mês certo (fev/2025)")
ss = json.load(open(ROOT / "dados" / "supersalarios.json", encoding="utf-8"))
meses = {o.get("mes") for o in (ss.get("orgaos") or []) + (ss.get("orgaosGoverno") or []) + (ss.get("ranking") or []) if o.get("mes")}
sem = sorted(m for m in meses if cs.teto_do_mes(m, vs) is None)
check(not sem, f"todos os {len(meses)} meses publicados têm teto definido" + (f" — faltam: {sem}" if sem else ""))
check(abs(cs.teto_do_mes(ss["ranking"][0]["mes"], vs)["valor"] - ss["teto"]) < 0.01 if ss.get("ranking") else True, "o teto da página = o teto do mês em config/teto.json")
print(f"✅ {len(oks)} checagens OK · ❌ {len(erros)} erros")
for e in erros:
    print("❌", e)
sys.exit(1 if erros else 0)
