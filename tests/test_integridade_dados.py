#!/usr/bin/env python3
"""
Cofre Aberto MS — teste de integridade dos dados publicados (dados/*.json)

Refaz as contas a partir dos registros individuais e compara com os totais que o site mostra. Não acessa a internet,
não altera nada. Uso:  python3 tests/test_integridade_dados.py   (sai com código 1 se algum ERRO for encontrado)

Níveis:  ERRO = número exibido que não fecha com os registros, valor impossível ou dado pessoal exposto
         AVISO = algo que merece olhar humano (atraso de fonte, valor muito fora do padrão)
"""

import glob, json, math, re, sys
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path

D = Path(__file__).resolve().parent.parent / "dados"
HOJE = date.today()
erros, avisos, oks = [], [], []
TOL = 0.011  # meio centavo para cima/baixo por arredondamento, em reais


def J(nome):
    try:
        return json.load(open(D / nome, encoding="utf-8"))
    except FileNotFoundError:
        avisos.append(f"{nome}: arquivo não existe")
        return {}


def igual(a, b, tol=None):
    tol = tol if tol is not None else max(TOL, 0.0001 * max(abs(a or 0), abs(b or 0)) * 0)  # exato até o centavo
    return abs((a or 0) - (b or 0)) <= max(tol, TOL)


def checa(nome, cond, msg_erro, nivel="erro"):
    if cond:
        oks.append(nome)
    else:
        (erros if nivel == "erro" else avisos).append(f"{nome}: {msg_erro}")


def soma(xs):
    return round(sum(x or 0 for x in xs), 2)


# ───────────────────────── 1. arquivos válidos e sem lixo ─────────────────────────
for f in sorted(glob.glob(str(D / "**" / "*.json"), recursive=True)):
    n = f.split("/dados/")[-1]
    try:
        t = open(f, encoding="utf-8").read()
        json.loads(t)
    except Exception as e:
        erros.append(f"{n}: JSON inválido ({e})")
        continue
    if "cache" in n:
        continue
    if re.search(r'(?<![\w])(NaN|Infinity)(?![\w])', t):
        erros.append(f"{n}: contém NaN/Infinity")
    if re.search(r'(?<![\d*.])\d{3}\.\d{3}\.\d{3}-\d{2}(?!\d)', t):
        erros.append(f"{n}: CPF completo publicado")
oks.append("JSON válidos")

# ───────────────────────── 2. Câmara de Campo Grande ─────────────────────────
cm = J("camara_municipal.json")
if cm:
    ano = cm.get("ano")
    V = cm["vereadores"]
    r = cm["resumo"]
    checa("CG: nº de vereadores", r["totalVereadores"] == len(V), f"resumo {r['totalVereadores']} x lista {len(V)}")
    checa("CG: verba paga = soma dos vereadores", igual(r[f"totalVerbaIndenizatoriaPaga{ano}"], soma(v["verbaIndenizatoria"].get(f"gastoPago{ano}") for v in V), 1),
          f"resumo {r[f'totalVerbaIndenizatoriaPaga{ano}']} x soma {soma(v['verbaIndenizatoria'].get(f'gastoPago{ano}') for v in V)}")
    checa("CG: cota anual = soma das cotas", igual(r["totalVerbaIndenizatoriaAnual"], soma(v["verbaIndenizatoria"].get(f"cotaAnual{ano}") for v in V), 1),
          f"{r['totalVerbaIndenizatoriaAnual']} x {soma(v['verbaIndenizatoria'].get(f'cotaAnual{ano}') for v in V)}")
    checa("CG: funcionários de gabinete = soma", r["totalFuncionariosGabinetes"] == sum((v.get("gabinete") or {}).get("numFuncionarios") or 0 for v in V),
          f"{r['totalFuncionariosGabinetes']} x {sum((v.get('gabinete') or {}).get('numFuncionarios') or 0 for v in V)}")
    for v in V:
        vi = v["verbaIndenizatoria"]
        g27, g28, gp = vi.get(f"gastoAto027_{ano}") or 0, vi.get(f"gastoAto028_{ano}") or 0, vi.get(f"gastoPago{ano}") or 0
        checa(f"CG {v['nome']}: ato 27 + ato 28 = pago", igual(g27 + g28, gp), f"{g27} + {g28} ≠ {gp}")
        m27, m28 = soma((vi.get("mesesAto027") or {}).values()), soma((vi.get("mesesAto028") or {}).values())
        if vi.get("mesesAto027") or vi.get("mesesAto028"):
            checa(f"CG {v['nome']}: meses somam o pago", igual(m27 + m28, gp, 1), f"meses {m27 + m28} x pago {gp}")
        cota = vi.get(f"cotaAnual{ano}") or 0
        if cota:
            checa(f"CG {v['nome']}: % usado", abs((vi.get("percentualUsado") or 0) - gp / cota * 100) < 0.11, f"{vi.get('percentualUsado')} x {gp / cota * 100:.2f}")
            checa(f"CG {v['nome']}: pago ≤ cota", gp <= cota + TOL, f"pago {gp} > cota {cota}")
        eq = (v.get("gabinete") or {}).get("equipe") or []
        if eq:
            checa(f"CG {v['nome']}: equipe x nº de funcionários", len(eq) == (v["gabinete"].get("numFuncionarios") or len(eq)),
                  f"lista {len(eq)} x número {v['gabinete'].get('numFuncionarios')}", "aviso")

# ───────────────────────── 3. Assembleia (ALEMS) ─────────────────────────
de = J("deputados_estaduais_ms.json")
if de:
    ano = de.get("ano")
    V = de["vereadores"]
    r = de["resumo"]
    checa("ALEMS: nº de deputados", r["totalDeputados"] == len(V), f"{r['totalDeputados']} x {len(V)}")
    checa("ALEMS: verba paga = soma", igual(r[f"totalVerbaIndenizatoriaPaga{ano}"], soma(v["verbaIndenizatoria"].get(f"gastoPago{ano}") for v in V), 1),
          f"{r[f'totalVerbaIndenizatoriaPaga{ano}']} x {soma(v['verbaIndenizatoria'].get(f'gastoPago{ano}') for v in V)}")
    for v in V:
        vi = v["verbaIndenizatoria"]
        gp = vi.get(f"gastoPago{ano}") or 0
        ds = v.get("despesas") or []
        if ds:
            checa(f"ALEMS {v['nome']}: notas somam o pago", igual(soma(d.get("valor") for d in ds), gp, 1), f"notas {soma(d.get('valor') for d in ds)} x pago {gp}")
            checa(f"ALEMS {v['nome']}: nº de notas", (v.get("totalNotasFiscais") or len(ds)) == len(ds), f"{v.get('totalNotasFiscais')} x {len(ds)}", "aviso")
        cota = vi.get(f"cotaAnual{ano}") or 0
        if cota:
            checa(f"ALEMS {v['nome']}: % usado", abs((vi.get("percentualUsado") or 0) - gp / cota * 100) < 0.11, f"{vi.get('percentualUsado')} x {gp / cota * 100:.2f}")

# ───────────────────────── 4. Deputados federais e senadores de MS ─────────────────────────
for arq, chave, campo_cat in (("deputados_federais_ms.json", "deputados", "ceapCategorias"), ("senadores_ms.json", "senadores", "ceapsCategorias")):
    d = J(arq)
    for p in d.get(chave) or []:
        tot = p.get("cotaGastaAno") or 0
        ds = (p.get("notasCeaps") if arq.startswith("senadores") else p.get("despesas")) or []  # senadores: "despesas" é um resumo antigo
        cats = p.get(campo_cat) or []
        if cats:
            checa(f"{arq} {p['nome']}: categorias somam o total", igual(soma(c["valor"] for c in cats), tot, 1), f"cats {soma(c['valor'] for c in cats)} x total {tot}")
        if ds:
            checa(f"{arq} {p['nome']}: notas somam o total", igual(soma(x.get("valor") for x in ds), tot, 1), f"notas {soma(x.get('valor') for x in ds)} x total {tot}")
            checa(f"{arq} {p['nome']}: nº de notas", (p.get("totalNotasFiscais") or 0) == len(ds), f"{p.get('totalNotasFiscais')} x {len(ds)}")
            dup = [k for k, c in Counter((x.get("data"), x.get("fornecedor"), x.get("valor"), x.get("doc")) for x in ds).items() if c > 1]
            checa(f"{arq} {p['nome']}: notas repetidas", len(dup) <= 2, f"{len(dup)} grupos iguais (data, fornecedor, valor, nº doc), ex. {dup[:1]}", "aviso")
        if arq.startswith("deputados_federais"):
            checa(f"{arq} {p['nome']}: passagens SIGEPA incluídas", any("SIGEPA" in c["categoria"] for c in cats), "sem categoria PASSAGEM AÉREA - SIGEPA", "aviso")

# ───────────────────────── 5. Prefeitura de Campo Grande ─────────────────────────
pf = J("prefeitura.json")
if pf:
    ds = pf["despesas"]
    checa("Prefeitura: total pago = soma das despesas", igual(pf["totalDespesas"], soma(r["valor"] for r in ds), 1), f"{pf['totalDespesas']} x {soma(r['valor'] for r in ds)}")
    checa("Prefeitura: nº de linhas", pf.get("totalNotasFiscais") == len(ds), f"{pf.get('totalNotasFiscais')} x {len(ds)}", "aviso")
    por = {}
    for r in ds:
        por[r["orgao"]] = por.get(r["orgao"], 0) + r["valor"]
    for o, v in (pf.get("porSecretaria") or {}).items():
        checa(f"Prefeitura: total da secretaria {o[:40]}", igual(v, por.get(o, 0), 1), f"{v} x {round(por.get(o, 0), 2)}")
    neg = [r for r in ds if r["valor"] < 0]
    checa("Prefeitura: sem pagamento negativo", not neg, f"{len(neg)} negativos")
    acima = [r for r in ds if (r.get("empenhado") or 0) and r["valor"] > r["empenhado"] + 0.01]
    checa("Prefeitura: pago ≤ empenhado na linha", len(acima) == 0, f"{len(acima)} linhas com pago maior que o empenhado, ex. {acima[:1]}", "aviso")
    checa("Prefeitura: pago ≤ liquidado ≤ empenhado (total)", pf["totalDespesas"] <= (pf.get("totalLiquidado") or 1e30) + 1 <= (pf.get("totalEmpenhado") or 1e30) + 2,
          f"pago {pf['totalDespesas']} liquidado {pf.get('totalLiquidado')} empenhado {pf.get('totalEmpenhado')}")
    dup = [k for k, c in Counter((r.get("urlDetalhe"), r.get("valor"), r.get("data")) for r in ds if r.get("urlDetalhe")).items() if c > 1]
    checa("Prefeitura: empenho repetido", not dup, f"{len(dup)} empenhos aparecem mais de uma vez com o mesmo valor e data, ex. {dup[:1]}", "aviso")
    ult = pf.get("ultimoEmpenho")
    if ult:
        dias = (HOJE - date.fromisoformat(ult)).days
        checa("Prefeitura: empenho recente", dias <= 45, f"último empenho publicado há {dias} dias ({ult})", "aviso")

# ───────────────────────── 6. Governo de MS ─────────────────────────
g = J("governo_ms.json")
if g:
    t = g["totais"]
    O = g["orgaos"]
    for k in ("empenhado", "liquidado", "pago"):
        checa(f"Governo MS: {k} total = soma dos órgãos", igual(t[k], soma(o[k] for o in O), 1), f"{t[k]} x {soma(o[k] for o in O)}")
    checa("Governo MS: pago ≤ liquidado ≤ empenhado", t["pago"] <= t["liquidado"] + 1 <= t["empenhado"] + 2, str(t))
    for o in O:
        if not (o["pago"] <= o["liquidado"] + 1 <= o["empenhado"] + 2):
            avisos.append(f"Governo MS: órgão {o['orgao']} com pago/liquidado/empenhado fora de ordem: {o['pago']} / {o['liquidado']} / {o['empenhado']}")
    ano = str(g.get("ano"))
    meses = (g.get("meses") or {}).get(ano) or []
    if meses:
        checa("Governo MS: meses do ano somam o pago", igual(soma(meses), t["pago"], 1000), f"meses {soma(meses)} x pago {t['pago']} (dif {soma(meses) - t['pago']:,.2f})", "aviso")
    gc = J("governo_ms_credores.json")
    cr = gc.get("credores") or []
    if cr:
        checa("Governo MS: credores somam o pago", abs(soma(c[2] for c in cr) - t["pago"]) / t["pago"] < 0.02,
              f"credores {soma(c[2] for c in cr):,.2f} x pago {t['pago']:,.2f}", "aviso")

# ───────────────────────── 7. Emendas ─────────────────────────
em = J("emendas_municipios.json")
if em:
    checa("Emendas: total = soma dos municípios", igual(em["totalMS"], soma(m["total"] for m in em["municipios"]), 1),
          f"{em['totalMS']} x {soma(m['total'] for m in em['municipios'])}")
    for a in em.get("autores") or []:
        sm = soma(x["valor"] for x in a.get("municipios") or [])
        if a.get("municipios"):
            checa(f"Emendas {a['autor']}: municípios somam o total MS", igual(sm, a["totalMS"], 1), f"{sm} x {a['totalMS']}", "aviso")
        st = soma(x["valor"] for x in a.get("tipos") or [])
        if a.get("tipos"):
            checa(f"Emendas {a['autor']}: tipos somam o total MS", igual(st, a["totalMS"], 1), f"{st} x {a['totalMS']}", "aviso")

# ───────────────────────── 8. Shows, obras, publicidade, entidades, aluguéis ─────────────────────────
sh = J("shows.json")
if sh:
    S = sh["shows"]
    checa("Shows: valor total = soma", igual(sh["valorShows"], soma(x["valor"] for x in S), 1), f"{sh['valorShows']} x {soma(x['valor'] for x in S)}")
    checa("Shows: quantidade", sh["totalShows"] == len(S), f"{sh['totalShows']} x {len(S)}")
    checa("Shows: ranking soma o total", igual(soma(r["valor"] for r in sh["ranking"]), sh["valorShows"], 1), f"{soma(r['valor'] for r in sh['ranking'])} x {sh['valorShows']}")
    checa("Shows: sem contratação repetida", len({x["id"] for x in S}) == len(S), "ids repetidos")
ob = J("obras.json")
if ob:
    A = ob["obras"]
    checa("Obras: em andamento = lista", ob["abertas"]["obras"] == len(A), f"{ob['abertas']['obras']} x {len(A)}")
    checa("Obras: valor em andamento", igual(ob["abertas"]["valor"], soma(o["valor"] for o in A), 1), f"{ob['abertas']['valor']} x {soma(o['valor'] for o in A)}")
    for m, r in ob["resumo"].items():
        lst = [o for o in A if m in o["marcas"]]
        checa(f"Obras: resumo {m}", r["obras"] == len(lst) and igual(r["valor"], soma(o["valor"] for o in lst), 1), f"{r} x {len(lst)} / {soma(o['valor'] for o in lst)}")
    bad = [o for o in A if not (0 <= (o.get("executado") or 0) <= 100.0001)]
    checa("Obras: % executado entre 0 e 100", not bad, f"{len(bad)} fora")
    pr = ob.get("prefeitura") or {}
    if pr:
        checa("Obras Prefeitura: total", pr["total"]["obras"] == len(pr["obras"]) and igual(pr["total"]["valor"], soma(o["valorTotal"] for o in pr["obras"]), 1), str(pr["total"]))
pb = J("publicidade.json")
if pb:
    checa("Publicidade: Estado = soma das agências", igual(pb["estado"]["total"], soma(a["estado"] for a in pb["agencias"]), 1), f"{pb['estado']['total']} x {soma(a['estado'] for a in pb['agencias'])}")
    checa("Publicidade: Prefeitura = soma dos meses", igual(pb["prefeitura"]["total"], soma(m["valor"] for m in pb["prefeitura"]["porMes"]), 1), "meses não fecham")
    checa("Publicidade: Prefeitura = soma das agências", igual(pb["prefeitura"]["total"], soma(a["prefeitura"] for a in pb["agencias"]), 1), f"{pb['prefeitura']['total']} x {soma(a['prefeitura'] for a in pb['agencias'])}")
en = J("entidades.json")
if en:
    E = en["entidades"]
    checa("Entidades: total = soma", igual(en["total"], soma(e["total"] for e in E), 1), f"{en['total']} x {soma(e['total'] for e in E)}")
    for k in ("estado", "prefeitura", "emendas"):
        checa(f"Entidades: {k}", igual(en[k], soma(e[k] for e in E), 1), f"{en[k]} x {soma(e[k] for e in E)}")
    checa("Entidades: quantidade", en["quantidade"] == len(E), f"{en['quantidade']} x {len(E)}")
    checa("Entidades: áreas somam o total", igual(soma(a["valor"] for a in en["areas"]), en["total"], 1), "áreas não fecham")
    bad = [e for e in E if not igual(e["total"], e["estado"] + e["prefeitura"] + e["emendas"], 0.02)]
    checa("Entidades: total de cada uma = Estado + Prefeitura + emendas", not bad, f"{len(bad)} entidades")
al = J("alugueis.json")
if al:
    P = al["pncp"]
    checa("Aluguéis: PNCP total", igual(P["total"], soma(c["valor"] for c in P["lista"]), 1) and P["contratacoes"] == len(P["lista"]), "não fecha")
    checa("Aluguéis: Estado + municípios ≤ total", P["estado"]["total"] + P["municipios"]["total"] <= P["total"] + 1, "esferas passam do total")
    F = al["prefeitura"]
    checa("Aluguéis: Prefeitura total = soma dos locadores", igual(F["total"], soma(a["valor"] for a in F["lista"]), 1), f"{F['total']} x {soma(a['valor'] for a in F['lista'])}")
    checa("Aluguéis: cada locador = soma dos pagamentos", all(igual(a["valor"], soma(p["valor"] for p in a["pagamentos"]), 0.05) for a in F["lista"]), "pagamentos não fecham")
    pfv = [x for x in F["lista"] if x.get("tipo") == "PF" and x.get("doc")] + [c["locador"] for c in P["lista"] if c.get("locador") and c["locador"].get("tipo") == "PF" and c["locador"].get("doc")]
    checa("Aluguéis: CPF de pessoa física não publicado", not pfv, f"{len(pfv)} com documento")

# ───────────────────────── 9. Supersalários, produção, votações, benefícios ─────────────────────────
ss = J("supersalarios.json")
if ss:
    R = ss["ranking"]
    checa("Supersalários: soma acima do teto por órgão = total", igual(soma(o.get("valorAcimaTeto") for o in ss["orgaos"]), ss["valorAcimaTeto"], 10),
          f"{soma(o.get('valorAcimaTeto') for o in ss['orgaos'])} x {ss['valorAcimaTeto']}", "aviso")
    checa("Supersalários: pessoas acima por órgão = total", sum(o.get("acimaTeto") or 0 for o in ss["orgaos"]) == ss["acimaTeto"],
          f"{sum(o.get('acimaTeto') or 0 for o in ss['orgaos'])} x {ss['acimaTeto']}", "aviso")
    bad = [x for x in R if not igual(x["bruto"] - ss["teto"], x.get("acimaTeto"), 0.05)]
    checa("Supersalários: 'acima do teto' = bruto − teto", not bad, f"{len(bad)} linhas, ex. {[(x['cargo'], x['bruto'], x.get('acimaTeto')) for x in bad[:2]]}", "aviso")
    bad = [x for x in R if x.get("bruto") and not igual(x["bruto"], (x.get("base") or 0) + (x.get("outras") or 0), 1)]
    checa("Supersalários: bruto = base + outras verbas", not bad, f"{len(bad)} linhas", "aviso")
    sem_base = [x for x in R[:20] if not x.get("base")]
    checa("Supersalários: topo do ranking com salário-base", len(sem_base) <= 3,
          f"{len(sem_base)} dos 20 primeiros sem salário-base (rescisão/indenização?), ex. {[(x['cargo'], x['orgaoSigla'], x['bruto']) for x in sem_base[:3]]}", "aviso")
pl = J("producao_legislativa.json")
for x in pl.get("parlamentares") or []:
    t = x.get("todos") or []
    checa(f"Produção {x['nome']}: lista = contagem", len(t) == x["projetos"] and sum(1 for i in t if i["principal"]) == x["projetosPrincipal"] and sum(1 for i in t if i["lei"]) == x["leis"],
          f"lista {len(t)}/{sum(1 for i in t if i['principal'])}/{sum(1 for i in t if i['lei'])} x {x['projetos']}/{x['projetosPrincipal']}/{x['leis']}")
vt = J("votacoes.json")
for x in vt.get("parlamentares") or []:
    if x.get("nominais"):
        checa(f"Votações {x['nome']}: participação", abs(x["participacao"] - x["votou"] / x["nominais"] * 100) < 0.11, f"{x['participacao']} x {x['votou'] / x['nominais'] * 100:.2f}")
bf = J("beneficios_fiscais.json")
if bf:
    E = bf["empresas"]
    checa("Benefícios: caso a caso = lista", bf["casoACaso"] == len(E), f"{bf['casoACaso']} x {len(E)}")
    checa("Benefícios: sócio doador", bf["comSocioDoador"] == sum(1 for e in E if e["sociosDoadores"]), "contagem")
    checa("Benefícios: setores somam", sum(n for _, n in bf["porSetor"]) == len(E), "setores não fecham")

# ───────────────────────── 10. Receitas (Impostômetro) e evolução ─────────────────────────
rc = J("receitas.json")
for ente, d in (rc.get("entes") or {}).items():
    for ano, v in (d.get("anos") or {}).items() if isinstance(d, dict) else []:
        if isinstance(v, dict):
            neg = {k: x for k, x in v.items() if isinstance(x, (int, float)) and x < 0}
            checa(f"Receitas {ente} {ano}: sem negativos", not neg, str(neg), "aviso")
ev = J("evolucao_mensal.json")
for grupo, lst in (ev.get("grupos") or {}).items():
    for p in lst:
        if len(p.get("m") or []) != 12:
            erros.append(f"Evolução {grupo} {p['nome']}: série com {len(p.get('m') or [])} meses")
fed = {p["nome"]: p for p in J("deputados_federais_ms.json").get("deputados") or []}
for p in (ev.get("grupos") or {}).get("federal") or []:
    if p["nome"] in fed and fed[p["nome"]].get("despesas"):
        ds = fed[p["nome"]]["despesas"]
        porm = [0.0] * 12
        for x in ds:
            m = x.get("mes") or (int(x["data"][5:7]) if x.get("data") else None)
            if m:
                porm[m - 1] += x["valor"] or 0
        checa(f"Evolução {p['nome']}: soma dos meses = CEAP do ano", igual(sum(p["m"]), sum(porm), 1), f"evolução {sum(p['m']):,.2f} x notas {sum(porm):,.2f}")

# ───────────────────────── 11. painel leve = dados completos ─────────────────────────
leve = D / "painel" / "camara_municipal.json"
if leve.exists() and cm:
    L = json.load(open(leve, encoding="utf-8"))
    vl = {v["nome"]: v for v in L.get("vereadores") or []}
    dif = [v["nome"] for v in cm["vereadores"] if v["nome"] in vl and not igual((vl[v["nome"]].get("verbaIndenizatoria") or {}).get(f"gastoPago{cm['ano']}"), v["verbaIndenizatoria"].get(f"gastoPago{cm['ano']}"))]
    checa("Painel leve da Câmara CG = dados completos", not dif, f"diferem: {dif[:3]}")

# ───────────────────────── resultado ─────────────────────────
print(f"✅ {len(oks)} conferências OK · ⚠️ {len(avisos)} avisos · ❌ {len(erros)} erros")
for e in erros:
    print("❌", e)
for a in avisos:
    print("⚠️", a)
sys.exit(1 if erros else 0)
