#!/usr/bin/env python3
"""Cofre Aberto MS — limite de requisições da API da CGU (scripts/limite_cgu.py), com relógio simulado.
Uso: python3 tests/test_limite_cgu.py   (código 1 se algum teste falhar)"""
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import limite_cgu as L  # noqa: E402

oks, erros = [], []
check = lambda c, m: (oks if c else erros).append(m)

check(L.limite_por_minuto(datetime(2026, 11, 19, 14)) == 300, "6h–23h59 (limite 400): no máximo 300 por minuto")
check(L.limite_por_minuto(datetime(2026, 11, 19, 3)) == 300, "0h–5h59 (limite 700): no máximo 300 por minuto também")
check(L.limite_por_minuto(datetime(2026, 11, 19, 23, 59)) == 300, "23h59: 300")

for hora, lim in ((14, 300), (2, 300)):
    t = [0.0]
    L._feitas.clear()
    rel = lambda: t[0]
    dorme = lambda s: t.__setitem__(0, t[0] + s)
    instantes = []
    for _ in range(2000):
        L.esperar_vez(datetime(2026, 11, 19, hora), relogio=rel, dormir=dorme)
        instantes.append(t[0])
        t[0] += 0.01
    pior = max(sum(1 for x in instantes if a <= x < a + 60) for a in instantes)
    check(pior <= lim, f"{hora}h: em qualquer janela de 60 s, no máximo {lim} requisições (pior caso: {pior})")
    check(pior >= lim - 5, f"{hora}h: usa o limite (não fica muito abaixo dele): {pior}")

check(L.espera_429("12") == 12 and L.espera_429("9999") == 300, "429: respeita o Retry-After (até 5 min)")
check(all(30 <= L.espera_429(None) <= 60 for _ in range(50)), "429 sem Retry-After: espera 30–60 s")
import os
os.environ.pop("PORTAL_TRANSPARENCIA_API_KEY", None)
check(L.chave() is None, "sem chave no ambiente → None")
os.environ["PORTAL_TRANSPARENCIA_API_KEY"] = " b \n"
check(L.chave() == "b", "lê PORTAL_TRANSPARENCIA_API_KEY (sem espaços nem quebra de linha)")

print(f"✅ {len(oks)} checagens OK · ❌ {len(erros)} erros")
for e in erros:
    print("❌", e)
sys.exit(1 if erros else 0)
