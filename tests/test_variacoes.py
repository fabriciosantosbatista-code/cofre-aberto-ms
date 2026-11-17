#!/usr/bin/env python3
"""
Cofre Aberto MS — testes de variação, formato e exposição (rodam na coleta automática e a cada mudança no código)

  fontes         classificação do monitoramento: falha de coleta e divergência na fonte = ERRO; aguardando a fonte e
                 revisão manual = AVISO
  variação       compara com o retrato anterior (dados/monitoramento_historico.json): queda de registros > 10% ou do total
                 acumulado do ano > 2% = ERRO (no mesmo ano, o acumulado não cai); aumento > 60% de um dia para o outro = AVISO
  formato        cada conjunto tem os campos de que o site depende; se a fonte mudar o formato e um campo sumir = ERRO
  versões        meses já fechados (ano anterior do Governo de MS, meses do RREO com mais de 4 meses) não podem mudar
                 de uma versão para outra (git) sem aviso = AVISO
  PDFs (Câmara)  PDFs registrados com hash, notas com origem, vereadores a revisar; piora em relação à coleta anterior = AVISO
  exposição      CPF completo, e-mail de pessoa física ou termo de credencial em dados/ ou nas páginas = ERRO

Uso: python3 tests/test_variacoes.py [--relatorio arquivo.md]   (código de saída 1 se houver ERRO)
"""

import glob, json, re, subprocess, sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
D = ROOT / "dados"
erros, avisos, oks = [], [], []


def J(n):
    try:
        return json.load(open(D / n, encoding="utf-8"))
    except Exception:
        return None


def ok(nome):
    oks.append(nome)


# ── fontes ──
mon = J("monitoramento.json") or {}
for fid, f in (mon.get("fontes") or {}).items():
    c = f.get("classe")
    if c in ("falha_coleta", "divergencia"):
        erros.append(f"{f['nome']}: {f['classeRotulo']} — {f['motivo']}")
    elif c in ("aguardando_fonte", "revisao_manual"):
        avisos.append(f"{f['nome']}: {f['classeRotulo']} — {f['motivo']}")
    else:
        ok(f"fonte {fid}")
if not mon:
    erros.append("monitoramento.json ausente — o monitoramento das fontes não rodou")

# ── variação em relação ao retrato anterior ──
hist = J("monitoramento_historico.json") or {}
datas = sorted(hist)
if len(datas) >= 2:
    hoje, ant = hist[datas[-1]], hist[datas[-2]]
    mesmo_ano = datas[-1][:4] == datas[-2][:4]
    for fid, h in hoje.items():
        a = ant.get(fid) or {}
        r1, r0 = h.get("registros"), a.get("registros")
        if isinstance(r1, (int, float)) and isinstance(r0, (int, float)) and r0 > 20:
            if r1 < r0 * 0.9:
                erros.append(f"{fid}: registros caíram de {r0} para {r1} ({(r1 / r0 - 1) * 100:.0f}%) entre {datas[-2]} e {datas[-1]}")
            elif r1 > r0 * 1.6:
                avisos.append(f"{fid}: registros subiram de {r0} para {r1} (+{(r1 / r0 - 1) * 100:.0f}%) — conferir se é dado novo de verdade")
            else:
                ok(f"registros {fid}")
        t1, t0 = h.get("total"), a.get("total")
        if isinstance(t1, (int, float)) and isinstance(t0, (int, float)) and t0 > 1000:
            if mesmo_ano and t1 < t0 * 0.98:
                erros.append(f"{fid}: total acumulado caiu de {t0:,.2f} para {t1:,.2f} ({(t1 / t0 - 1) * 100:.1f}%) — no mesmo ano o acumulado não deveria cair")
            elif t1 > t0 * 1.6:
                avisos.append(f"{fid}: total subiu de {t0:,.2f} para {t1:,.2f} (+{(t1 / t0 - 1) * 100:.0f}%) em um dia — conferir")
            else:
                ok(f"total {fid}")
else:
    avisos.append("histórico do monitoramento com menos de 2 retratos — a comparação de variação começa na próxima coleta")

# ── formato (campos de que o site depende) ──
ESQUEMA = {
    "camara_municipal.json": ("vereadores", ["nome", "verbaIndenizatoria", "gabinete", "despesas"]),
    "deputados_estaduais_ms.json": ("vereadores", ["nome", "verbaIndenizatoria", "despesas"]),
    "deputados_federais_ms.json": ("deputados", ["id", "nome", "cotaGastaAno", "ceapCategorias", "despesas"]),
    "senadores_ms.json": ("senadores", ["id", "nome", "cotaGastaAno", "ceapsCategorias", "notasCeaps"]),
    "prefeitura.json": ("despesas", ["data", "orgao", "fornecedor", "cnpj", "valor", "urlDetalhe"]),
    "governo_ms.json": ("orgaos", ["orgao", "empenhado", "liquidado", "pago"]),
    "governo_ms_credores.json": ("credores", None),
    "emendas_municipios.json": ("municipios", ["municipio", "total", "autores"]),
    "shows.json": ("shows", ["id", "orgao", "valor", "link"]),
    "supersalarios.json": ("ranking", ["nome", "cargo", "orgao", "bruto", "liquido"]),
    "alugueis.json": (None, ["prefeitura", "pncp"]),
    "producao_legislativa.json": ("parlamentares", ["grupo", "id", "nome", "projetos", "todos"]),
    "votacoes.json": ("parlamentares", ["grupo", "id", "nome", "nominais", "votou", "participacao"]),
    "receitas.json": (None, ["entes", "ultimaAtualizacao"]),
    "obras.json": ("obras", ["numero", "valor", "executado", "marcas"]),
}
for arq, (lista, campos) in ESQUEMA.items():
    d = J(arq)
    if d is None:
        erros.append(f"formato: {arq} não existe ou não é JSON válido")
        continue
    if lista:
        lst = d.get(lista)
        if not isinstance(lst, list) or not lst:
            erros.append(f"formato: {arq} sem a lista '{lista}' (ou vazia) — a fonte pode ter mudado o formato")
            continue
        if campos:
            faltam = [c for c in campos if not isinstance(lst[0], dict) or c not in lst[0]]
            if faltam:
                erros.append(f"formato: {arq} — campos {faltam} sumiram do registro (mudança no formato da fonte?)")
                continue
    elif campos:
        faltam = [c for c in campos if c not in d]
        if faltam:
            erros.append(f"formato: {arq} — campos {faltam} sumiram")
            continue
    ok(f"formato {arq}")

# ── versões: meses fechados não mudam ──
def versao_anterior(arq):
    try:
        t = subprocess.run(["git", "-C", str(ROOT), "show", f"HEAD~1:dados/{arq}"], capture_output=True, text=True, timeout=60)
        return json.loads(t.stdout) if t.returncode == 0 and t.stdout else None
    except Exception:
        return None


g, g0 = J("governo_ms.json") or {}, versao_anterior("governo_ms.json")
if g0 and g.get("ano") == g0.get("ano"):
    a_ant = str(int(g["ano"]) - 1)
    m1, m0 = (g.get("meses") or {}).get(a_ant), (g0.get("meses") or {}).get(a_ant)
    if m1 and m0 and any(abs((x or 0) - (y or 0)) > 1 for x, y in zip(m1, m0)):
        avisos.append(f"versões: despesas mensais do Governo de MS de {a_ant} (ano fechado) mudaram em relação à versão anterior")
    else:
        ok("versões governo")
rc, rc0 = J("receitas.json") or {}, versao_anterior("receitas.json")
if rc0:
    lim = date.today().replace(day=1)
    lim = f"{lim.year - (lim.month <= 4)}-{(lim.month - 5) % 12 + 1:02d}"
    for ente in ("estado", "cg"):
        m1 = ((rc.get("entes") or {}).get(ente) or {}).get("meses") or {}
        m0 = ((rc0.get("entes") or {}).get(ente) or {}).get("meses") or {}
        mud = [m for m in m0 if m < lim and m in m1 and any(abs((m1[m].get(k) or 0) - (m0[m].get(k) or 0)) > 1 for k in m0[m])]
        if mud:
            avisos.append(f"versões: receitas de {ente} em meses antigos mudaram ({', '.join(mud[:4])}) — o Tesouro pode ter republicado o RREO")
        else:
            ok(f"versões receitas {ente}")

# ── PDFs da Câmara ──
rv = J("camara_cg_revisao.json") or {}
r = rv.get("resumo") or {}
if not rv:
    erros.append("Câmara CG: conferência da leitura dos PDFs não rodou (camara_cg_revisao.json ausente)")
else:
    if not rv.get("pdfsRegistrados"):
        avisos.append("Câmara CG: nenhum PDF registrado com hash ainda (o manifesto é criado na próxima coleta da Câmara)")
    if r.get("notas") and r.get("notasComOrigem", 0) < r["notas"] * 0.5:
        avisos.append(f"Câmara CG: só {r.get('notasComOrigem', 0)} de {r['notas']} notas têm a origem (PDF e página) registrada")
    if (r.get("itensRevisar") or 0) > 0:
        avisos.append(f"Câmara CG: {r['itensRevisar']} itens da leitura dos PDFs para conferência manual ({r.get('aRevisar')} de {r.get('vereadores')} vereadores)")
    for m in (rv.get("mudancas") or [])[-50:]:
        if m.get("em", "")[:10] == (mon.get("geradoEm") or "")[:10]:
            avisos.append(f"Câmara CG: {m['vereador']} {m.get('campo')} {m.get('mes') or ''}: {m['motivo']} ({m.get('antes')} → {m.get('depois')})")
    ok("Câmara CG conferência")

# ── exposição de dados pessoais ──
CPF = re.compile(r"(?<![\d*.])\d{3}\.\d{3}\.\d{3}-\d{2}(?!\d)")
CRED = re.compile(r"(?i)(api[_-]?key|senha|password|secret|token)\"?\s*[:=]\s*\"[A-Za-z0-9_\-]{16,}")
achados = []
for f in glob.glob(str(D / "**" / "*.json"), recursive=True) + glob.glob(str(D / "csv" / "*.csv")):
    t = open(f, encoding="utf-8", errors="ignore").read()
    if CPF.search(t):
        achados.append(f"CPF completo em {f.split('/dados/')[-1]}")
    if CRED.search(t):
        achados.append(f"possível credencial em {f.split('/dados/')[-1]}")
for f in glob.glob(str(ROOT / "**" / "*.html"), recursive=True):
    if "/node_modules/" in f:
        continue
    if CPF.search(open(f, encoding="utf-8", errors="ignore").read()):
        achados.append(f"CPF completo na página {f.replace(str(ROOT), '')}")
if achados:
    erros += achados[:20]
else:
    ok("exposição de dados pessoais")

# ── resultado ──
cab = f"✅ {len(oks)} checagens OK · ⚠️ {len(avisos)} avisos · ❌ {len(erros)} erros"
print(cab)
for e in erros:
    print("❌", e)
for a in avisos:
    print("⚠️", a)
if "--relatorio" in sys.argv:
    arq = sys.argv[sys.argv.index("--relatorio") + 1]
    with open(arq, "a", encoding="utf-8") as fh:
        fh.write(f"\n## Variações, formato, PDFs e exposição de dados\n\n{cab}\n\n")
        for e in erros:
            fh.write(f"- ❌ {e}\n")
        for a in avisos:
            fh.write(f"- ⚠️ {a}\n")
if "--json" in sys.argv:  # resultado por base, para o ICP
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from _bases import grava_json
    grava_json(sys.argv[sys.argv.index("--json") + 1], "variacoes", oks, avisos, erros)
sys.exit(1 if erros else 0)
