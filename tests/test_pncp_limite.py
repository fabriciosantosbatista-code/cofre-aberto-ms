#!/usr/bin/env python3
"""Cofre Aberto MS — limite adaptativo de consultas simultâneas ao PNCP (scripts/pncp_limite.py), sem rede.
Uso: python3 tests/test_pncp_limite.py   (código 1 se algum teste falhar)"""
import sys, threading, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import pncp_limite as pl  # noqa: E402

oks, erros = [], []
check = lambda c, m: (oks if c else erros).append(m)

t = [0.0]
L = pl.Limite(relogio=lambda: t[0])
check(L.atual == 3, "começa com 3 consultas simultâneas")
L.entrar(); L.sair(429)
check(L.atual == 2 and L.n429 == 1, "primeiro 429 → 2")
L.entrar(); L.sair(429)
check(L.atual == 1, "segundo 429 → 1")
L.entrar(); L.sair(429)
check(L.atual == 1 and L.n429 == 3, "nunca abaixo de 1")
t[0] += 299
L.entrar(); L.sair(200)
check(L.atual == 1, "menos de 5 min sem 429 → não sobe")
t[0] += 2
L.entrar(); L.sair(200)
check(L.atual == 2, "5 min sem 429 → sobe uma")
t[0] += 100
L.entrar(); L.sair(200)
check(L.atual == 2, "sobe uma de cada vez (espera mais 5 min)")
t[0] += 300
L.entrar(); L.sair(200)
t[0] += 300
L.entrar(); L.sair(200)
check(L.atual == 3, "no máximo 3")

# concorrência real: com o limite em 2, nunca há mais de 2 consultas ao mesmo tempo
L2 = pl.Limite()
L2.atual = 2
ativos, pico, trava = [0], [0], threading.Lock()
def tarefa():
    L2.entrar()
    with trava:
        ativos[0] += 1
        pico[0] = max(pico[0], ativos[0])
    time.sleep(0.02)
    with trava:
        ativos[0] -= 1
    L2.sair(200)
ths = [threading.Thread(target=tarefa) for _ in range(12)]
[x.start() for x in ths]
[x.join() for x in ths]
check(pico[0] == 2, f"8+ threads, limite 2 → no máximo 2 consultas ao mesmo tempo (pico {pico[0]})")

class R:
    def __init__(self, ra): self.headers = {"Retry-After": ra} if ra else {}
check(pl.espera_429(R("17")) == 17 and pl.espera_429(R("999")) == 300, "Retry-After respeitado (até 5 min)")
check(all(30 <= pl.espera_429(R(None)) <= 60 for _ in range(30)), "sem Retry-After: 30–60 s")
check("429" in pl.resumo() and "espera total" in pl.resumo() and "duração" in pl.resumo(), "resumo do log: 429, espera total e duração")

print(f"✅ {len(oks)} checagens OK · ❌ {len(erros)} erros")
for e in erros:
    print("❌", e)
sys.exit(1 if erros else 0)
