#!/usr/bin/env python3
"""
Cofre Aberto MS — a reserva do GitHub nunca publica sem coleta (estrutura do workflow, sem rede)

25/11/2026: o cancelamento da reserva deu erro 500 na API do GitHub; o job "decidir" falhou e a etapa de publicação
rodou sem coleta nenhuma (refez conferências sobre os dados antigos). Agora: 5 tentativas de cancelamento; a saída
coletar=false pula coletas, publicação e verificação; sem cancelar, a execução termina em falha (não em sucesso vazio)
e o vigia não conta essa falha como coleta.
Uso: python3 tests/test_reserva_coleta.py   (código 1 se algum teste falhar)
"""
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
oks, erros = [], []
check = lambda c, m: (oks if c else erros).append(m)
wf = yaml.safe_load(open(ROOT / ".github/workflows/atualizar.yml", encoding="utf-8"))
J = wf["jobs"]
d = J["decidir"]
check("coletar" in (d.get("outputs") or {}), "decidir publica a saída 'coletar'")
passo = next(p for p in d["steps"] if p.get("id") == "reserva")
run = passo["run"]
check("for t in range(5)" in run and "gh\", \"run\", \"cancel\"" in run and "check=True" not in run, "cancelamento com 5 tentativas, sem derrubar o job na 1ª falha")
check("coletar=false" in run and "sys.exit(1)" in run, "sem cancelar: coletar=false e a execução termina em falha")
coletores = [n for n, j in J.items() if n.startswith("coletar_")]
check(len(coletores) == 10 and all("needs.decidir.outputs.coletar != 'false'" in str(J[n].get("if")) for n in coletores),
      f"os {len(coletores)} coletores pulam com coletar=false")
check("decidir" in J["commit_e_push"]["needs"] and "needs.decidir.outputs.coletar != 'false'" in J["commit_e_push"]["if"],
      "a publicação pula com coletar=false")
check("needs.commit_e_push.result != 'skipped'" in J["verificar"]["if"], "a verificação pula se a publicação pulou")
vig = (ROOT / ".github/workflows/vigia-coleta.yml").read_text(encoding="utf-8")
check("def nao_coletou" in vig and "not nao_coletou(r)" in vig, "o vigia não conta como coleta a reserva que pulou as coletas")
for e in erros:
    print("❌", e)
print(f"✅ {len(oks)} checagens OK · ❌ {len(erros)} erros")
sys.exit(1 if erros else 0)
