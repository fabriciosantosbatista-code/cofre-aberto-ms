#!/usr/bin/env python3
"""
Cofre Aberto MS — divergência na fonte registrada não deixa o "Testar site" vermelho (casos simulados, sem rede)

Regra (21/11/2026): divergência registrada na conferência (itens site × fonte + a mesma conferência no histórico
permanente do ICP) = AVISO no teste, e continua no site e no ICP; divergência sem registro = ERRO.
Uso: python3 tests/test_divergencia_registrada.py   (código 1 se algum teste falhar)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _bases import divergencia_registrada  # noqa: E402

oks, erros = [], []
check = lambda c, m: (oks if c else erros).append(m)

v = {"resultado": "diverge", "em": "2026-11-19T18:23:59", "divergentes": [{"item": "x|y|04/2026", "site": 10.0, "fonte": 5.0, "diferenca": 5.0}]}
hist = [{"base": "emendas", "em": "2026-11-19T18:23:59", "resultado": "diverge"}]
check(divergencia_registrada("emendas", {"validacao": v}, hist), "registrada: itens site × fonte + mesma conferência no histórico do ICP → aviso")
check(not divergencia_registrada("emendas", {"validacao": v}, []), "sem a linha no histórico do ICP → erro")
check(not divergencia_registrada("emendas", {"validacao": v}, [{"base": "emendas", "em": "2026-11-18T10:00:00", "resultado": "diverge"}]),
      "histórico com outra conferência (data diferente) → erro")
check(not divergencia_registrada("outra", {"validacao": v}, hist), "histórico de outra base → erro")
check(not divergencia_registrada("emendas", {"validacao": {**v, "divergentes": []}}, hist), "sem os itens divergentes → erro")
check(not divergencia_registrada("emendas", {"validacao": {**v, "divergentes": [{"item": "x"}]}}, hist), "item sem valor do site e da fonte → erro")
check(not divergencia_registrada("emendas", {}, hist), "sem conferência → erro")
check(not divergencia_registrada("emendas", {"validacao": {**v, "resultado": "confere"}}, hist), "conferência que não diverge não é 'divergência registrada'")

for e in erros:
    print("❌", e)
print(f"✅ {len(oks)} checagens OK · ❌ {len(erros)} erros")
sys.exit(1 if erros else 0)
