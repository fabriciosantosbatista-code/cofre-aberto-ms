#!/usr/bin/env python3
"""
Cofre Aberto MS — publicação do site com 2ª tentativa (estrutura do workflow, sem rede)

25/11/2026: o GitHub às vezes não encontra o pacote do site recém-enviado ("No artifacts named github-pages");
4 publicações seguidas falharam e as mudanças não entraram no ar. A publicação tenta de novo depois de 1 minuto.
Uso: python3 tests/test_publicacao_site.py   (código 1 se algum teste falhar)
"""
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
oks, erros = [], []
check = lambda c, m: (oks if c else erros).append(m)
w = yaml.safe_load(open(ROOT / ".github/workflows/publicar-site.yml", encoding="utf-8"))
j = w["jobs"]["publicar"]
passos = {p.get("id") or p.get("name"): p for p in j["steps"]}
d1, d2 = passos.get("deploy") or {}, passos.get("deploy2") or {}
check(d1.get("uses", "").startswith("actions/deploy-pages") and d1.get("continue-on-error") is True, "1ª tentativa não derruba o job")
check(d2.get("uses", "").startswith("actions/deploy-pages") and d2.get("if") == "steps.deploy.outcome == 'failure'", "2ª tentativa só se a 1ª falhar")
espera = next((p for p in j["steps"] if "sleep 60" in str(p.get("run"))), None)
check(espera is not None and espera.get("if") == "steps.deploy.outcome == 'failure'", "espera de 1 minuto antes da 2ª tentativa")
check("deploy2.outputs.page_url" in j["environment"]["url"], "endereço do site vem da tentativa que deu certo")
check("continue-on-error" not in d2, "se a 2ª também falhar, o job falha (o GitHub avisa)")
for e in erros:
    print("❌", e)
print(f"✅ {len(oks)} checagens OK · ❌ {len(erros)} erros")
sys.exit(1 if erros else 0)
