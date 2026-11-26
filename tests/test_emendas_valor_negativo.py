#!/usr/bin/env python3
"""
Cofre Aberto MS — emendas: estorno da CGU vem como "- 2.664,31" (sinal, espaço, valor) (casos simulados, sem rede)

Em 21/11/2026 a conferência das emendas parou com "could not convert string to float: '- 2664.31'" e ficou 3 coletas
sem conferir; a coleta lia o mesmo texto como 0. As duas agora leem o estorno como valor negativo.
Uso: python3 tests/test_emendas_valor_negativo.py   (código 1 se algum teste falhar)
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import coletar_emendas_municipios as cem  # noqa: E402
import validar_fontes as vf  # noqa: E402

oks, erros = [], []
check = lambda c, m: (oks if c else erros).append(m)
for f, nome in ((vf.valor_brl, "conferência"), (cem.valor, "coleta")):
    check(f("- 2.664,31") == -2664.31, f"{nome}: estorno com espaço depois do sinal")
    check(f("-2.664,31") == -2664.31, f"{nome}: estorno sem espaço")
    check(f("1.400.000,00") == 1400000.0, f"{nome}: valor com milhar")
    check(f("700,00") == 700.0, f"{nome}: valor simples")
check(vf.valor_brl(16856.95) == 16856.95 and vf.valor_brl(None) == 0.0, "conferência: número da API e vazio")

for m in oks:
    print("✓", m)
for m in erros:
    print("✗", m)
print(f"{len(oks)} ok, {len(erros)} falha(s)")
sys.exit(1 if erros else 0)
