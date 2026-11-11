#!/usr/bin/env python3
"""
Cofre Aberto MS — Página própria de cada órgão: /orgao/<sigla>/

Junta o que o site já coleta sobre cada órgão público de MS:
  - Judiciário (TJMS, TRT24) e TCE-MS: remunerações, quantos recebem acima do
    teto, penduricalhos item por item, evolução mensal e os maiores salários
  - Câmara Municipal de Campo Grande: maiores salários da folha
  - cada órgão do Governo do Estado (secretarias, polícias, autarquias):
    folha (média, acima do teto, maiores salários), diárias de viagem, membros
    do primeiro escalão e despesas pagas no ano

Gera /orgao/<slug>/index.html, o índice /orgao/ e acrescenta ao sitemap.xml.
Roda depois de gerar_paginas_empresas.py (que mexe no sitemap).
"""

import json, re, unicodedata
from pathlib import Path

from gerar_paginas_parlamentares import (ANO, DADOS, HOJE, ROOT, RODAPE, SITE, brl, cabecalho, compacto, data_br, e,  # noqa: E402
                                         escreve_se_mudou, milhar)

PASTA = ROOT / "orgao"
CSS_EXTRA = """
.lst td:first-child a{color:var(--ink);font-weight:600}
.busca{width:100%;padding:10px 14px;margin:6px 0 16px;border:1px solid var(--border);border-radius:9px;background:var(--surface-2);color:var(--ink);font-size:.9rem}
.citar{overflow-wrap:anywhere}
"""
NOMES = {"tjms": "Tribunal de Justiça de Mato Grosso do Sul (TJMS)", "trt24": "Tribunal Regional do Trabalho da 24ª Região (TRT24)",
         "tce": "Tribunal de Contas do Estado de Mato Grosso do Sul (TCE-MS)", "camara-cg": "Câmara Municipal de Campo Grande"}


def carregar(nome):
    try:
        return json.load(open(DADOS / nome, encoding="utf-8"))
    except Exception:
        return {}


def slug(t):
    t = unicodedata.normalize("NFD", t or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", t).strip("-")


def norm(t):
    t = unicodedata.normalize("NFD", t or "").encode("ascii", "ignore").decode().upper()
    return re.sub(r"[^A-Z ]", " ", re.sub(r"\([^)]*\)", " ", t)).split()


def grade(itens):
    return "<div class='resumo-grid'>" + "".join(
        f"<div class='resumo-item'><div class='resumo-val'>{e(v)}</div><div class='resumo-label'>{e(l)}</div></div>" for v, l in itens) + "</div>"


def tabela(cab, linhas):
    th = "".join(f"<th{' class=num' if c.startswith('#') else ''}>{e(c.lstrip('#'))}</th>" for c in cab)
    return f"<div class='tabela-wrap'><table><thead><tr>{th}</tr></thead><tbody>{''.join(linhas)}</tbody></table></div>"


def bloco_salarios(o, pessoas, teto, nota=""):
    lin = [f"<tr><td class='f'>{e(p['nome'])}<small>{e(p.get('cargo') or '')}{' · ' + e(p['situacao']) if p.get('situacao') and p['situacao'] != 'Ativo' else ''}</small></td>"
           f"<td class='num'>{brl(p['bruto'])}</td><td class='num'>{brl(p['liquido'])}</td></tr>" for p in pessoas]
    return (f"<h2>Remunerações</h2><p>Folha de <strong>{e(o['mes'])}</strong>: {milhar(o['pessoas'])} pessoas, média bruta de "
            f"<strong>{brl(o['mediaBruta'])}</strong>. <strong>{milhar(o.get('liquidoAcimaTeto', 0))}</strong> receberam líquido acima do teto "
            f"constitucional ({brl(teto)}) e {milhar(o['acimaTeto'])} tiveram bruto acima dele.{nota}</p>"
            + (f"<h2 style='font-size:1rem'>Maiores remunerações do mês</h2>" + tabela(["Nome", "#Bruto", "#Líquido"], lin) if lin else "")
            + "<p class='aviso' style='margin-top:12px'>Acima do teto não é sinônimo de irregular: verbas indenizatórias (auxílios, diárias, "
              "indenização de férias) ficam fora do teto por lei, e pagamentos atrasados podem inflar um único mês.</p>")


def bloco_pendur(p):
    itens = [i for i in p["itens"] if i["valor"] > 0][:15]
    if not itens:
        return ""
    mx = itens[0]["valor"]
    return ("<h2>Penduricalhos, item por item</h2><p>O que foi pago além da remuneração base em " + e(p["mes"]) + ".</p><div class='bars'>" + "".join(
        f"<div class='bar'><span>{e(i['item'])} · {i['pessoas']} pessoas</span><b>{brl(i['valor'])}</b><div class='t'><i style='width:{i['valor'] / mx * 100:.1f}%'></i></div></div>"
        for i in itens) + "</div>")


def bloco_evol(ev):
    ms = ev.get("meses") or []
    if not ms:
        return ""
    return ("<h2>Mês a mês: base x outras remunerações</h2>" + tabela(["Mês", "#Pessoas", "#Remuneração base", "#Outras remunerações"],
            [f"<tr><td>{e(m['mes'])}</td><td class='num'>{m['pessoas']}</td><td class='num'>{brl(m['base'])}</td><td class='num'>{brl(m['outras'])}</td></tr>" for m in ms]))


def pagina(sl, nome, sigla, blocos, resumo_txt, fonte):
    url = f"/orgao/{sl}/"
    titulo = f"{nome}: salários, penduricalhos e gastos em {ANO} | Cofre Aberto MS"
    jsonld = {"@context": "https://schema.org", "@type": "GovernmentOrganization", "name": nome, "url": SITE + url,
              "areaServed": "Mato Grosso do Sul"}
    corpo = f"""<p class="breadcrumb"><a href="/">Início</a> / <a href="/orgao/">Órgãos</a> / {e(sigla)}</p>
<article><h1>{e(nome)}</h1>
<p class="cargo" style="margin-bottom:16px">{e(resumo_txt)}</p>
{''.join(blocos)}
<div class="acoes" style="margin-top:18px"><a class="btn prim" href="/cofre-aberto-ms.html#aba=supersalarios">Supersalários no painel</a>
<a class="btn" href="/dados/csv/supersalarios_ranking.csv" download>Baixar planilha (CSV)</a></div>
<h2>Como citar</h2>
<div class="citar">COFRE ABERTO MS. <i>{e(nome)} — remunerações e gastos em {ANO}</i>. Fonte dos dados: {e(fonte)}. Compilados em {data_br(HOJE.isoformat())}. Disponível em: {SITE}{url}.</div>
</article>"""
    return cabecalho(titulo, resumo_txt[:300], url, None, jsonld, tipo="website").replace("</style>", CSS_EXTRA + "</style>", 1) + corpo + RODAPE


def main():
    ss = carregar("supersalarios.json")
    if ss.get("ano") != ANO:
        print("⚠️ supersalarios.json ausente ou de outro ano — páginas de órgão não geradas")
        return
    teto = ss["teto"]
    gov = carregar("governo_ms.json")
    paginas = []

    # Judiciário e TCE
    for oid, chave_res in (("tjms", "TJMS"), ("trt24", "TRT24"), ("tce", "TCE-MS")):
        res = [o for o in ss.get("orgaos", []) if o["orgao"].startswith(chave_res)]
        if not res:
            continue
        gente = sorted((p for p in ss.get("ranking", []) if p.get("orgaoId") == oid), key=lambda p: -p["bruto"])[:25]
        blocos = []
        for o in res:
            sub = [p for p in gente if p["orgao"] == o["orgao"]] if oid == "tce" else gente
            blocos.append((f"<h2 style='font-size:1.05rem'>{e(o['orgao'].split(' — ')[-1].capitalize())}</h2>" if oid == "tce" else "")
                          + bloco_salarios(o, sub[:20], teto))
        p = (ss.get("penduricalhos") or {}).get(oid)
        if p:
            blocos.append(bloco_pendur(p))
        ev = (ss.get("evolucao") or {}).get(oid)
        if ev:
            blocos.append(bloco_evol(ev))
        comp = next((x for x in ss.get("comparacaoTJs", []) if x["orgao"] == "TJMS"), None) if oid == "tjms" else None
        if comp:
            blocos.insert(0, f"<p class='aviso'>Com média bruta de <strong>{brl(comp['mediaBruta'])}</strong> por magistrado ({e(comp['mes'])}), o TJMS tem a "
                             f"<strong>{comp['posicao']}ª maior remuneração média</strong> entre {len(ss['comparacaoTJs'])} tribunais de justiça estaduais com dados no DadosJusBr.</p>")
        o0 = res[0]
        resumo_txt = (f"{milhar(sum(o['pessoas'] for o in res))} contracheques analisados; {milhar(sum(o.get('liquidoAcimaTeto', 0) for o in res))} "
                      f"com líquido acima do teto em {o0['mes']}.")
        fonte = "DadosJusBr / Transparência Brasil (contracheques enviados ao CNJ)" if oid != "tce" else "Portal da Transparência do TCE-MS"
        paginas.append({"slug": oid if oid != "tce" else "tce-ms", "nome": NOMES[oid], "sigla": chave_res,
                        "html": pagina(oid if oid != "tce" else "tce-ms", NOMES[oid], chave_res, blocos, resumo_txt, fonte),
                        "pessoas": sum(o["pessoas"] for o in res), "acima": sum(o.get("liquidoAcimaTeto", 0) for o in res),
                        "media": o0["mediaBruta"], "grupo": "Judiciário e controle"})

    # Câmara de Campo Grande
    cg = [o for o in ss.get("orgaos", []) if o["orgao"].startswith("Câmara Municipal")]
    if cg:
        gente = sorted((p for p in ss.get("ranking", []) if p.get("orgaoId") == "camara-cg"), key=lambda p: -p["bruto"])[:20]
        o = cg[0]
        paginas.append({"slug": "camara-campo-grande", "nome": NOMES["camara-cg"], "sigla": "Câmara CG",
                        "html": pagina("camara-campo-grande", NOMES["camara-cg"], "Câmara CG", [bloco_salarios(o, gente, teto, " Só os 60 maiores salários da folha entram na conta.")],
                                       f"Maiores salários da folha de {o['mes']}.", "Portal da Transparência da Câmara Municipal de Campo Grande"),
                        "pessoas": o["pessoas"], "acima": o.get("liquidoAcimaTeto", 0), "media": o["mediaBruta"], "grupo": "Legislativo"})

    # Órgãos do Governo do Estado
    diar = {d["orgao"]: d for d in ((gov.get("diarias") or {}).get("porOrgao") or [])}
    diar_pessoas = (gov.get("diarias") or {}).get("maiores") or []
    escalao = ((gov.get("primeiroEscalao") or {}).get("pessoas")) or []
    nomes_gov = ss.get("siglasGoverno") or {}
    despesas = {" ".join(norm(o["orgao"])): o for o in gov.get("orgaos", [])}
    for o in ss.get("orgaosGoverno", []):
        sigla = o.get("sigla") or o["orgao"].replace("Governo MS — ", "")
        if o["pessoas"] < 20:
            continue
        nome = nomes_gov.get(sigla) or f"{sigla} — Governo do Estado de MS"
        blocos = [bloco_salarios(o, o.get("maiores", []), teto, " A folha do Estado não separa o corte do teto: quando os descontos são altos, parte do bruto foi cortada.")]
        esc = [p for p in escalao if p["orgao"] == sigla and p.get("ativo")]
        if esc:
            blocos.insert(0, "<h2>Primeiro escalão</h2>" + tabela(["Nome", "#Bruto no mês", "#Líquido"], [
                f"<tr><td class='f'>{e(p['nome'])}<small>{e(p['cargo'])}</small></td><td class='num'>{brl(p['bruto'])}</td><td class='num'>{brl(p['liquido'])}</td></tr>" for p in esc]))
        d = diar.get(sigla)
        if d and d["valor"]:
            top = [p for p in diar_pessoas if p["orgao"] == sigla][:10]
            blocos.append(f"<h2>Diárias de viagem</h2><p><strong>{brl(d['valor'])}</strong> em {milhar(d['trechos'])} trechos de viagem pagos em {ANO}.</p>"
                          + (tabela(["Quem recebeu", "#Trechos", "#Valor"], [f"<tr><td class='f'>{e(p['nome'])}<small>{e(p['cargo'])}</small></td><td class='num'>{p['trechos']}</td><td class='num'>{brl(p['valor'])}</td></tr>" for p in top]) if top else ""))
        desp = despesas.get(" ".join(norm(nome))) if nome else None
        if desp:
            blocos.append(f"<h2>Despesas</h2><p>{brl(desp['pago'])} pagos em {ANO}, com {brl(desp['empenhado'])} empenhados, segundo o Portal da Transparência do Estado. "
                          f"<a href='/cofre-aberto-ms.html#aba=governo-ms'>Ver no painel →</a></p>")
        sl = "governo-" + slug(sigla)
        paginas.append({"slug": sl, "nome": nome, "sigla": sigla, "pessoas": o["pessoas"], "acima": o.get("liquidoAcimaTeto", 0),
                        "media": o["mediaBruta"], "grupo": "Governo do Estado",
                        "html": pagina(sl, nome, sigla, blocos, f"{milhar(o['pessoas'])} pessoas na folha de {o['mes']}, média bruta de {brl(o['mediaBruta'])}.",
                                       "Portal da Transparência do Estado de MS")})

    PASTA.mkdir(exist_ok=True)
    validos, mudou = set(), 0
    for p in paginas:
        c = PASTA / p["slug"] / "index.html"
        validos.add(c.parent)
        mudou += escreve_se_mudou(c, p["html"])
    for d in PASTA.iterdir():
        if d.is_dir() and d not in validos:
            for f in d.iterdir():
                f.unlink()
            d.rmdir()
    grupos = {}
    for p in paginas:
        grupos.setdefault(p["grupo"], []).append(p)
    corpo_lista = ""
    for g in ("Judiciário e controle", "Legislativo", "Governo do Estado"):
        lst = sorted(grupos.get(g, []), key=lambda p: (-p["acima"], -p["media"]))
        if lst:
            corpo_lista += f"<h2>{e(g)}</h2>" + "<div class='tabela-wrap'><table class='lst'><thead><tr><th>Órgão</th><th class='num'>Pessoas</th><th class='num'>Média bruta</th><th class='num'>Líquido acima do teto</th></tr></thead><tbody>" + "".join(
                f"<tr><td><a href='/orgao/{p['slug']}/'>{e(p['sigla'])}</a><small style='display:block;color:var(--ink-caption);font-size:.74rem'>{e(p['nome'])}</small></td>"
                f"<td class='num'>{milhar(p['pessoas'])}</td><td class='num'>{brl(p['media'])}</td><td class='num'>{milhar(p['acima'])}</td></tr>" for p in lst) + "</tbody></table></div>"
    idx = cabecalho(f"Órgãos públicos de MS — salários e gastos {ANO} | Cofre Aberto MS",
                    f"{len(paginas)} órgãos de MS com remunerações, penduricalhos, diárias e despesas: Judiciário, TCE, Câmara de Campo Grande e secretarias do Estado.",
                    "/orgao/", None, {"@context": "https://schema.org", "@type": "CollectionPage", "name": "Órgãos", "url": SITE + "/orgao/"},
                    tipo="website").replace("</style>", CSS_EXTRA + "</style>", 1) + f"""<p class="breadcrumb"><a href="/">Início</a> / Órgãos</p>
<article><h1>Órgãos</h1><p class="cargo" style="margin-bottom:12px">{len(paginas)} órgãos públicos de MS com salários, quem recebe acima do teto, penduricalhos, diárias e despesas.</p>
{corpo_lista}</article>""" + RODAPE
    escreve_se_mudou(PASTA / "index.html", idx)
    sm = ROOT / "sitemap.xml"
    if sm.exists():
        txt = re.sub(r"  <url><loc>[^<]*/orgao/[^<]*</loc>.*?</url>\n", "", sm.read_text(encoding="utf-8"))
        novos = [f"  <url><loc>{SITE}/orgao/{x}</loc><lastmod>{HOJE.isoformat()}</lastmod><changefreq>weekly</changefreq><priority>0.6</priority></url>"
                 for x in [""] + [p["slug"] + "/" for p in paginas]]
        escreve_se_mudou(sm, txt.replace("</urlset>", "\n".join(novos) + "\n</urlset>"))
    escreve_se_mudou(DADOS / "orgaos_index.json", json.dumps({p["sigla"]: {"url": f"/orgao/{p['slug']}/", "nome": p["nome"]} for p in paginas},
                                                             ensure_ascii=False, separators=(",", ":")))
    print(f"✅ {len(paginas)} páginas de órgãos ({mudou} alteradas) + índice /orgao/ + sitemap")


if __name__ == "__main__":
    main()
