#!/usr/bin/env python3
"""
Cofre Aberto MS — Câmara CG: o mês de cada página dos PDFs (sem rede)

Regressão: de 12/11 a 19/11/2026 um dicionário de abreviações ("jan", "fev"...) sobrescrevia o dos nomes completos e
nenhum mês escrito por extenso era reconhecido — 55 PDFs liam 0 mês. Aqui, os rótulos como aparecem nos PDFs.

Uso: python3 tests/test_camara_cg_mes.py   (código 1 se algum teste falhar)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import coletar_verba_camara_cg as c  # noqa: E402

oks, erros = [], []
CASOS = [  # (texto da página, mês esperado)
    ("Vereador (a): Mês:\nDR. LIVIO > Janeiro/2026\nDespesa", "01"),
    ("Vereador (a): Mês:\nFlávio Cabo Almi Janeiro 2026\nD", "01"),
    ("Vereador (a): Mês:\nJean Ferreira JANEIRO\nDespesas Valor (R$)", "01"),
    ("Vereador (a): JOSÉ CLARO DOS SANTOS NETO Mês: JANEIRO//2026\nDespe", "01"),
    ("Mês: Março de 2026", "03"), ("Mês e ano: setembro/2026", "09"), ("Mês: 11/2026", "11"),
    ("Mês: Dezembro", "12"),
    ("Lei nº 1.234, de janeiro de 2019 — sem rótulo de mês", None),  # sem 'Mês:' não vale (rodapé/legislação)
]
for texto, esperado in CASOS:
    mes, ano = c.extrai_mes_ano_confiavel(c.normaliza_texto(texto))
    (oks if mes == esperado else erros).append(f"{texto[:45]!r} → {mes} (esperado {esperado})")
(oks if len(c.MESES_NUM) > 12 and c.MESES_NUM.get("janeiro") == "01" else erros).append("MESES_NUM tem os nomes completos")
(oks if c.MESES_ABREV_NUM.get("jan") == "01" else erros).append("abreviações em dicionário próprio")

for e in erros:
    print("❌", e)
print(f"✅ {len(oks)} checagens OK · ❌ {len(erros)} erros")
sys.exit(1 if erros else 0)
