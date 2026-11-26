#!/usr/bin/env python3
"""
Cofre Aberto MS — deputados federais: só MS (decisão de 26/11/2026, como o "Foco em MS" de 18/11)

- coleta: arquivo anual da Câmara filtrado por UF=MS (inclui suplentes de MS que exerceram no ano); sem coleta nacional;
- removidos: dados nacionais (deputados_federais_brasil.json/csv, ceap_federal/<UF>.json fora MS), aba escondida
  "Dep. Federais Brasil", linha da Metodologia e catálogo do painel;
- endereços antigos de outros estados: página curta, noindex, fora do sitemap, com o link da página na Câmara;
- páginas dos deputados de MS: total e notas iguais aos do painel (deputados_federais_ms.json).
Uso: python3 tests/test_foco_ms_deputados.py   (código 1 se algum teste falhar)
"""
import json, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
oks, erros = [], []
check = lambda c, m: (oks if c else erros).append(m)
D = ROOT / "dados"

check(not (D / "deputados_federais_brasil.json").exists() and not (D / "csv" / "deputados_federais_brasil.csv").exists(),
      "sem o dataset 'Deputados federais — Brasil' (JSON e CSV)")
uf = sorted(p.name for p in (D / "ceap_federal").glob("*.json"))
check(uf == ["MS.json"], f"dados/ceap_federal: só MS.json ({uf})")
for arq in ("cofre-aberto-ms.html", "index.html", "metodologia.html"):
    t = (ROOT / arq).read_text(encoding="utf-8")
    check("deputados_federais_brasil" not in t and "carregarDeputadosBrasil" not in t, f"{arq}: sem dados nem aba de deputados do Brasil")
src = (ROOT / "scripts" / "coletar_dados.py").read_text(encoding="utf-8")
check("def coletar_dep_federais_brasil" not in src and "coletar_dep_federais_brasil()\n" not in src.split("saiu em 26/11/2026")[-1],
      "coleta nacional de deputados removida")
check('(row.get("sgUF") or "").strip().upper() != "MS"' in src, "arquivo anual da Câmara filtrado por UF=MS")
check("suplente de MS que exerceu mandato no ano" in src, "suplentes de MS que exerceram no ano entram na lista")

ms = json.load(open(D / "deputados_federais_ms.json", encoding="utf-8"))["deputados"]
idx = json.load(open(D / "paginas_index.json", encoding="utf-8"))
fed = {k: v for k, v in idx.items() if k.startswith("federal|")}
check(len(fed) == len(ms), f"páginas de deputados federais = deputados de MS ({len(fed)} × {len(ms)})")
br = lambda v: f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
for d in ms:
    url = fed.get(f"federal|{d['nome']}")
    h = (ROOT / url.strip("/") / "index.html").read_text(encoding="utf-8") if url else ""
    check(f"gastou R$ {br(d['cotaGastaAno'])} de CEAP" in h and f"em {d['totalNotasFiscais']} notas fiscais" in h,
          f"{d['nome']}: página com o mesmo total e nº de notas do painel")

outros = json.load(open(ROOT / "config" / "deputados_federais_outros_estados.json", encoding="utf-8"))["paginas"]
smap = (ROOT / "sitemap.xml").read_text(encoding="utf-8")
check(len(outros) == 505, f"505 endereços antigos de outros estados ({len(outros)})")
ruins = []
for o in outros:
    f = ROOT / "deputado-federal" / o["slug"] / "index.html"
    h = f.read_text(encoding="utf-8") if f.exists() else ""
    if not ('name="robots" content="noindex' in h and f"https://www.camara.leg.br/deputados/{o['id']}" in h
            and "acompanha apenas os parlamentares de Mato Grosso do Sul" in h) or f"/deputado-federal/{o['slug']}/" in smap:
        ruins.append(o["slug"])
check(not ruins, f"endereços antigos: página curta noindex, com o link da Câmara e fora do sitemap ({len(ruins)} com problema: {ruins[:3]})")

for e in erros:
    print("❌", e)
print(f"✅ {len(oks)} checagens OK · ❌ {len(erros)} erros")
sys.exit(1 if erros else 0)
