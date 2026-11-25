#!/usr/bin/env python3
"""
Cofre Aberto MS — Prefeitura: órgão dos empenhos da UGE 0505F (SEMADI) pela página de cada empenho (sem rede)

Decisão de 25/11/2026: a exportação do SIG lança como "Secretaria Municipal de Gestão" os empenhos da 0505F, que
empenha folha e despesas de várias secretarias. O site usa a unidade gestora da página do empenho; erro na página vai
para "Órgão não confirmado (SEMADI)", nunca de volta para Gestão; o que ainda não foi lido fica "em confirmação".
Uma leitura por empenho, guardada no cache dos valores pagos (checkpoint entre coletas).
Uso: python3 tests/test_prefeitura_semadi.py   (código 1 se algum teste falhar)
"""
import json, sys, tempfile
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import coletar_dados as cd  # noqa: E402

oks, erros = [], []
check = lambda c, m: (oks if c else erros).append(m)
cd.log = lambda *_: None
cd.PREF_PAGOS_CACHE = Path(tempfile.mkdtemp()) / "cache.json"


def linha(num, uge="0505F", valor=1000.0, ug="Secretaria Municipal de Administração e Inovação - SEMADI"):
    return {"ano": 2026, "uge": uge, "num": num, "orgao": "SECRETARIA MUNICIPAL DE GESTÃO", "nomeunidadegestora": ug,
            "total_empenhado": f"{valor:.2f}", "total_pago": f"{valor / 2:.2f}"}


L = [linha(1, valor=56600000), linha(2, valor=19000000), linha(3, valor=500), linha(4, valor=300),
     linha(9, uge="1035S", ug="Fundo Municipal de Saude - FMS")]
PAGINA = {"2026/0505F/1": ({"o": "Secretaria Municipal de Educação - SEMED", "og": "SECRETARIA MUNICIPAL DE EDUCAÇÃO", "e": 56600000.0, "l": 1, "p": 1, "d": "x"}, None),
          "2026/0505F/2": (None, "HTTP 500"),
          "2026/0505F/3": ({"o": "Secretaria Municipal de Administração e Inovação - SEMADI", "og": "SECRETARIA MUNICIPAL DE GESTÃO"}, None)}
lidos = []


def ler(k):
    lidos.append(k)
    return PAGINA.get(k, (None, "HTTP 500"))


cache = {"2026/0505F/1": {"e": 1.0, "l": 1.0, "p": 0.5, "d": "2026-11-20"}}
n = cd._pref_orgao_central(L, cache, max_paginas=3, hilos=1, ler=ler)
check(lidos == ["2026/0505F/1", "2026/0505F/2", "2026/0505F/3"], f"lê só a 0505F, os de maior valor primeiro, até o limite da coleta: {lidos}")
check("2026/1035S/9" not in lidos, "empenho de outra unidade não é lido")
check(n == 2 and cache["2026/0505F/1"]["o"] == "Secretaria Municipal de Educação - SEMED", "órgão da página guardado no cache")
check(cache["2026/0505F/2"].get("oErro") == "HTTP 500" and cache["2026/0505F/2"].get("oTentativas") == 1, "erro 500 registrado no cache")
check(json.loads(cd.PREF_PAGOS_CACHE.read_text())["2026/0505F/1"]["o"].startswith("Secretaria Municipal de Educação"), "checkpoint: cache gravado")

cont = {}
org = {x["num"]: cd._pref_orgao_da_linha(x, cache, cont) for x in L}
check(org[1] == "Secretaria Municipal de Educação - SEMED", f"empenho confirmado vai para o órgão da página: {org[1]}")
check(org[2] == cd.PREF_NAO_CONFIRMADO, f"erro na página → '{cd.PREF_NAO_CONFIRMADO}', nunca Gestão: {org[2]}")
check(org[3] == "Secretaria Municipal de Administração e Inovação - SEMADI", "empenho que é mesmo da SEMADI continua na SEMADI")
check(org[4] == cd.PREF_A_CONFIRMAR, f"ainda não lido (fila da próxima coleta) → '{cd.PREF_A_CONFIRMAR}'")
check(org[9] == "Fundo Municipal de Saude - FMS", "outras unidades: unidade gestora da exportação, como antes")
check(not any("GESTÃO" in o.upper() for o in org.values()), "nenhum empenho volta para 'Secretaria Municipal de Gestão'")
r = cd._pref_resumo_central(cont)
check(r["empenhos"] == 4 and r["confirmados"] == 2 and r["naoConfirmados"] == 1 and r["emConfirmacao"] == 1 and r["pctConfirmados"] == 50.0,
      f"resumo para o gráfico (X% confirmados): {r}")
check(r["nota"] == ("a exportação do SIG classifica como Secretaria Municipal de Gestão os empenhos da unidade 0505F (SEMADI), que empenha "
                    "folha e despesas de várias secretarias; o Cofre Aberto MS usa o órgão indicado na página de cada empenho"), "nota combinada")

# 2ª coleta: só o que falta; erro 500 só é tentado de novo depois de 7 dias (no máximo 3 vezes)
lidos.clear()
cd._pref_orgao_central(L, cache, max_paginas=10, hilos=1, ler=ler)
check(lidos == ["2026/0505F/4"], f"2ª coleta lê só o que faltava (o erro de hoje não é repetido): {lidos}")
cache["2026/0505F/2"]["oTent"] = (date.today() - timedelta(days=8)).isoformat()
lidos.clear()
cd._pref_orgao_central(L, cache, max_paginas=10, hilos=1, ler=ler)
check("2026/0505F/2" in lidos and cache["2026/0505F/2"]["oTentativas"] == 2, "erro de 8 dias atrás: nova tentativa")
cache["2026/0505F/2"].update({"oTent": "2020-01-01", "oTentativas": 3})
lidos.clear()
cd._pref_orgao_central(L, cache, max_paginas=10, hilos=1, ler=ler)
check("2026/0505F/2" not in lidos, "3 tentativas com erro: para de tentar (fica 'não confirmado')")

# a atualização dos valores pagos mescla no cache e não apaga o órgão confirmado
src = Path(ROOT / "scripts" / "coletar_dados.py").read_text(encoding="utf-8")
check("cache[k] = {**(cache.get(k) or {}), **v}" in src, "valores pagos: mescla no cache (não apaga o órgão da SEMADI)")
html = (ROOT / "cofre-aberto-ms.html").read_text(encoding="utf-8")
check("Classificação por órgão em atualização" in html and 'id="pref-central-nota"' in html, "gráfico: nota e andamento da confirmação")

for e in erros:
    print("❌", e)
print(f"✅ {len(oks)} checagens OK · ❌ {len(erros)} erros")
sys.exit(1 if erros else 0)
