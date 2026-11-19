#!/usr/bin/env python3
"""Câmara CG — escolhe e renderiza as páginas para leitura no repositório PRIVADO (workflow leitura-camara-cg.yml).

Lê o diagnóstico da dupla extração (diag_camara_cg.json: as duas leituras de cada página em que os extratores
discordam) e os dados da coleta, e monta a pasta leitura_privada/ — que só vai para o repositório privado:
  paginas/<pdf>_p<n>.png   imagem da página (pode ter CPF impresso: nunca vai para o repositório público)
  diag.json                as duas leituras e o texto de cada página escolhida
  notas_pendentes.json     notas não resolvidas dessas páginas (vereador, mês, data, valor, CNPJ, motivo)
  resumo.json              contagens (inclui a análise das notas "ainda sem dupla extração")
O log mostra só contagens.
MODO=amostra: ~N páginas com discordância, de PDFs e vereadores diferentes. MODO=restantes: todas as pendentes.
"""
import collections, json, os, random, subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "leitura_privada"
PDFS = ROOT / "pdfs_camara_cg"
modo, n = os.environ.get("MODO", "amostra"), int(os.environ.get("N") or 30)

diag = json.load(open(ROOT / "diag_camara_cg.json", encoding="utf-8")) if (ROOT / "diag_camara_cg.json").exists() else []
cm = json.load(open(ROOT / "dados/camara_municipal.json", encoding="utf-8"))

pend, sem_dupla = [], collections.Counter()
hoje = {p.stem for p in PDFS.glob("*.pdf")}
for v in cm["vereadores"]:
    for d in v.get("despesas") or []:
        st = d.get("statusLeitura") or {}
        if st.get("status") == "confere":
            continue
        o = d.get("origem") or {}
        motivos = st.get("motivos") or []
        if any("ainda sem dupla" in str(m) for m in motivos):
            sem_dupla["sem origem (PDF e página) registrada" if not o.get("pdf") else
                      "PDF de origem não está entre os baixados hoje (não publicado mais ou mudou)" if o["pdf"] not in hoje else
                      "PDF de origem baixado hoje, mas a nota não foi reproduzida na releitura"] += 1
        pend.append({"vereador": v["nome"], "data": d.get("data"), "valor": d.get("valor"), "cnpj": d.get("cnpj"),
                     "fornecedor": d.get("fornecedor"), "documento": d.get("nf"), "ato": d.get("ato"),
                     "pdf": o.get("pdf"), "pagina": o.get("pagina"), "motivos": motivos})

disc = [x for x in diag if x.get("resultado") == "discordam" and x.get("pdf")]
if modo == "amostra":  # rodízio por vereador: 1 página de cada, PDFs diferentes, até N
    rnd = random.Random(20261119)
    por_ver = collections.defaultdict(list)
    for x in disc:
        por_ver[x["vereador"]].append(x)
    for l in por_ver.values():
        rnd.shuffle(l)
    escolhidas, usados = [], set()
    while len(escolhidas) < n and any(por_ver.values()):
        for ver in sorted(por_ver):
            l = por_ver[ver]
            while l:
                x = l.pop()
                if (x["pdf"], x["pagina"]) not in usados:
                    escolhidas.append(x); usados.add((x["pdf"], x["pagina"])); break
            if len(escolhidas) >= n:
                break
    paginas = [(x["pdf"], x["pagina"]) for x in escolhidas]
    sel_diag = escolhidas
else:
    paginas = sorted({(p["pdf"], p["pagina"]) for p in pend if p["pdf"] and p["pagina"]} | {(x["pdf"], x["pagina"]) for x in disc})
    sel_diag = [x for x in disc if (x["pdf"], x["pagina"]) in set(paginas)]

(OUT / "paginas").mkdir(parents=True, exist_ok=True)
ok = 0
for pdf, pg in paginas:
    f = PDFS / f"{pdf}.pdf"
    if f.exists():
        r = subprocess.run(["pdftoppm", "-f", str(pg), "-l", str(pg), "-r", "150", "-gray", "-png", "-singlefile", str(f),
                            str(OUT / "paginas" / f"{pdf}_p{pg}")], capture_output=True)
        ok += r.returncode == 0
sp = set(paginas)
json.dump(sel_diag, open(OUT / "diag.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
json.dump([p for p in pend if (p["pdf"], p["pagina"]) in sp], open(OUT / "notas_pendentes.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
resumo = {"modo": modo, "paginasEscolhidas": len(paginas), "paginasRenderizadas": ok, "paginasComDiscordancia": len(disc),
          "vereadoresNaEscolha": len({x.get("vereador") for x in sel_diag}), "pdfsNaEscolha": len({p for p, _ in paginas}),
          "notasPendentes": len(pend), "semDuplaExtracao": dict(sem_dupla),
          "statusNotas": (json.load(open(ROOT / "dados/camara_cg_revisao.json", encoding="utf-8")).get("resumo") or {}).get("statusNotas")}
json.dump(resumo, open(OUT / "resumo.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(json.dumps(resumo, ensure_ascii=False))
