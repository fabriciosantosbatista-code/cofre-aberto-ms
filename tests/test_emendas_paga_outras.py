#!/usr/bin/env python3
"""
Cofre Aberto MS — Emendas: documento que paga outras despesas além da emenda (28/11/2026; simulado, sem rede)

A API da CGU só traz o valor TOTAL da ordem bancária, não a parte da emenda. Regra num sentido só: documento maior que o
pagamento do site e sem a parte da emenda na observação → "não verificado"; site maior que o documento → divergência.
Casos: as 3 divergências da conferência de 28/11/2026 (valores reais da API) e os casos de controle.
Uso: python3 tests/test_emendas_paga_outras.py   (código 1 se algum teste falhar)
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import limite_cgu  # noqa: E402
import validar_fontes as vf  # noqa: E402

oks, erros = [], []
check = lambda c, m: (oks if c else erros).append(m)
E1, E2 = "202543670019", "202643180009"
VB, MOD, DEN, FIC = "30521824000178", "32352772000189", "11319557000378", "99888777000166"
pags = [{"emenda": E1, "doc": DEN, "favorecido": "DENTECK LTDA", "mes": "02/2026", "valor": 3900.0},
        {"emenda": E2, "doc": VB, "favorecido": "VBTUR", "mes": "07/2026", "valor": 8333.32},
        {"emenda": E2, "doc": MOD, "favorecido": "MODERNA", "mes": "08/2026", "valor": 15000.0},
        {"emenda": E2, "doc": VB, "favorecido": "VBTUR", "mes": "11/2026", "valor": 8333.32},      # bate
        {"emenda": E2, "doc": FIC, "favorecido": "FICTICIA", "mes": "10/2026", "valor": 9000.0},   # site maior → diverge
        {"emenda": E2, "doc": FIC, "favorecido": "FICTICIA", "mes": "09/2026", "valor": 1000.0}]   # parte na obs, API maior → diverge
docs = {E1: [("D1", "12/02/2026", DEN, "5.507,77", "LIQUIDACAO NF 189270-189271 DENTECK LTDA 2025NE1288-1291")],
        E2: [("D2", "21/07/2026", VB, "62.136,81", "FRETAMENTO DE VANS (EMENDA Nº 202643180009 - CAMILA JARA)"),
             ("D3", "28/08/2026", MOD, "27.346,85", "FRETAMENTO DE ONIBUS (EMENDA Nº 202643180009 - CAMILA JARA)"),
             ("D4", "05/11/2026", VB, "8.333,32", "FRETAMENTO DE VANS (EMENDA Nº 202643180009 - CAMILA JARA)"),
             ("D5", "10/10/2026", FIC, "5.000,00", "SERVICO (EMENDA Nº 202643180009)"),
             ("D6", "10/09/2026", FIC, "4.000,00", "R$ 1.500,00 EMENDA 202643180009 E R$ 2.500,00 EMENDA 202614510010")]}
det = {c: {"data": d, "codigoFavorecido": f, "ufFavorecido": "MS", "valor": v, "observacao": o} for l in docs.values() for c, d, f, v, o in l}


def cgu(caminho, params=None):
    if caminho.startswith("emendas/documentos/"):
        e = caminho.rsplit("/", 1)[1]
        return [{"codigoDocumento": c, "fase": "Pagamento", "data": d} for c, d, *_ in docs[e]] if params["pagina"] == 1 else []
    return det[caminho.rsplit("/", 1)[1]]


vf._cgu = cgu
vf.J = lambda n: {"ano": 2026, "pagamentosMS": pags} if n == "emendas_municipios.json" else {}
vf.ja_conferidos_na_janela = lambda base, dias=30: {}
vf.com_hashes = lambda res, base, ok: res
limite_cgu.chave = lambda: "x"
r = vf.v_emendas(n_emendas=5)
m = r.get("motivosRegistros") or {}
k = lambda e, d, mes: f"{e}|{d}|{mes}"
div = {d["item"] for d in r.get("divergentes") or []}
for e_, d_, mes, nome in ((E1, DEN, "02/2026", "Denteck 02/2026"), (E2, VB, "07/2026", "VBTur 07/2026"), (E2, MOD, "08/2026", "Moderna 08/2026")):
    check(m.get(k(e_, d_, mes)) == vf.PAGA_OUTRAS and k(e_, d_, mes) not in div, f"{nome}: não verificado (documento paga outras despesas)")
check(k(E2, VB, "11/2026") not in div and k(E2, VB, "11/2026") not in m, "VBTur 11/2026: documento igual ao site — confere")
check(k(E2, FIC, "10/2026") in div, "site maior que o documento inteiro: continua divergência")
check(k(E2, FIC, "09/2026") in div, "observação informa a parte e ela difere: continua divergência")
print(f"resultado: {r['resultado']} · divergentes: {sorted(div)}")
for x in oks:
    print("✓", x)
for x in erros:
    print("✗", x)
print(f"{len(oks)} ok, {len(erros)} falha(s)")
sys.exit(1 if erros else 0)
