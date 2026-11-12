#!/usr/bin/env python3
"""
Cofre Aberto MS — Página de cada município de MS: /municipio/<slug>/

Junta, para cada um dos 79 municípios:
  - emendas parlamentares pagas no ano (dados/emendas_municipios.json): total,
    de quem (com link para a página do parlamentar de MS), por tipo e quem recebeu
  - Emendas Pix (transferências especiais) desde 2020, ano a ano, e os autores
  - transferências da União no ano (dados/presidencia.json → ms.municipio)

Gera /municipio/<slug>/index.html, o índice /municipio/, dados/municipios_index.json
e acrescenta ao sitemap.xml. Roda depois de gerar_paginas_orgaos.py.
"""

import json, re, unicodedata

from gerar_paginas_parlamentares import (ANO, DADOS, HOJE, ROOT, RODAPE, SITE, brl, cabecalho, compacto, data_br, e,  # noqa: E402
                                         escreve_se_mudou, milhar)

PASTA = ROOT / "municipio"
CSS_EXTRA = """
.lst td:first-child a{color:var(--ink);font-weight:600}
.busca{width:100%;padding:10px 14px;margin:6px 0 16px;border:1px solid var(--border);border-radius:9px;background:var(--surface-2);color:var(--ink);font-size:.9rem}
.barras{display:flex;flex-direction:column;gap:8px;margin:10px 0 4px}
.barra{display:grid;grid-template-columns:minmax(90px,200px) 1fr auto;gap:10px;align-items:center;font-size:.84rem}
.barra .t{height:8px;border-radius:4px;background:var(--surface-2);overflow:hidden}
.barra .f{height:100%;border-radius:4px;background:linear-gradient(90deg,#c98500,#f5c842)}
.barra .v{font-variant-numeric:tabular-nums;white-space:nowrap}
.citar{overflow-wrap:anywhere}
"""


def carregar(nome):
    try:
        return json.load(open(DADOS / nome, encoding="utf-8"))
    except Exception:
        return {}


def slug(t):
    t = unicodedata.normalize("NFD", t or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", t).strip("-")


def chave(t):
    return re.sub(r"[^A-Z]", "", unicodedata.normalize("NFD", t or "").encode("ascii", "ignore").decode().upper())


def tabela(cab, linhas):
    th = "".join(f"<th{' class=num' if c.startswith('#') else ''}>{e(c.lstrip('#'))}</th>" for c in cab)
    return f"<div class='tabela-wrap'><table><thead><tr>{th}</tr></thead><tbody>{''.join(linhas)}</tbody></table></div>"


def barras(itens):
    mx = max((v for _, v in itens), default=0) or 1
    return "<div class='barras'>" + "".join(
        f"<div class='barra'><span>{e(n)}</span><div class='t'><div class='f' style='width:{v / mx * 100:.1f}%'></div></div>"
        f"<span class='v'>{compacto(v)}</span></div>" for n, v in itens) + "</div>"


def main():
    em = carregar("emendas_municipios.json")
    if not em.get("municipios"):
        print("⚠️ emendas_municipios.json vazio — páginas de municípios não geradas")
        return
    pags = carregar("paginas_index.json") or {}
    por_nome = {}
    for k, url in pags.items():
        por_nome.setdefault(chave(k.split("|", 1)[1]), url)
    pix = (em.get("pix") or {}).get("porAno") or {}
    pix_mun = {}
    for a, d in pix.items():
        for m in d.get("municipios", []):
            pix_mun.setdefault(chave(m["municipio"]), {})[a] = m
    uniao = {chave(m["nome"]): m["valor"] for m in ((carregar("presidencia.json").get("ms") or {}).get("municipio") or [])}
    uniao_ano = (carregar("presidencia.json").get("ms") or {}).get("ate")
    ano_em = em.get("ano", ANO)

    def autor_link(a):
        url = por_nome.get(chave(a["autor"])) if a.get("atual") else None
        return f"<a href='{url}'>{e(a['autor'])}</a>" if url else e(a["autor"])

    paginas = []
    for m in em["municipios"]:
        nome = m["municipio"]
        if nome in ("—", ""):
            continue
        sl = slug(nome)
        url = f"/municipio/{sl}/"
        pm = pix_mun.get(chave(nome), {})
        pix_total = sum(x["valor"] for x in pm.values())
        tu = uniao.get(chave(nome))
        itens = [(brl(m["total"]), f"em emendas parlamentares pagas em {ano_em}"),
                 (milhar(len(m["autores"])), "autores de emenda"),
                 (brl(pix_total), f"em Emendas Pix desde {min(pm) if pm else 2020}")]
        if tu:
            itens.append((brl(tu), f"transferidos pela União em {ANO}" + (f" (até {uniao_ano})" if uniao_ano else "")))
        grid = "<div class='resumo-grid'>" + "".join(f"<div class='resumo-item'><div class='resumo-val'>{e(v)}</div><div class='resumo-label'>{e(l)}</div></div>" for v, l in itens) + "</div>"
        blocos = [grid, "<p class='aviso'>Emenda paga não indica irregularidade: o site só reúne o que o Portal da Transparência do Governo Federal publica. "
                        "O valor é o do mês do pagamento — inclui emendas de anos anteriores pagas agora.</p>"]
        blocos.append(f"<h2>De quem vieram as emendas em {ano_em}</h2>" + tabela(["Autor", "#Valor"], [
            f"<tr><td class='f'>{autor_link(a)}{' <small>parlamentar atual de MS</small>' if a.get('atual') else ''}</td><td class='num'>{brl(a['valor'])}</td></tr>"
            for a in m["autores"][:40]]))
        if m.get("tipos"):
            blocos.append("<h2>Por tipo de emenda</h2>" + barras([(t["tipo"], t["valor"]) for t in m["tipos"]]))
        if m.get("favorecidos"):
            blocos.append("<h2>Quem recebeu o dinheiro</h2><p>Prefeitura, fundos, hospitais e entidades do município que receberam os pagamentos.</p>" + tabela(
                ["Favorecido", "#Valor"], [
                    f"<tr><td class='f'>{e(f['nome'])}<small>{e(f.get('natureza') or '')}</small></td><td class='num'>{brl(f['valor'])}</td></tr>"
                    for f in m["favorecidos"][:20]]))
        if pm:
            anos = sorted(pm)
            blocos.append(f"<h2>Emendas Pix (transferências especiais)</h2><p>Dinheiro que cai direto no caixa da prefeitura, sem convênio. "
                          f"{brl(pix_total)} de {anos[0]} a {anos[-1]}.</p>" + barras([(a + (' (até agora)' if a == str(HOJE.year) else ''), pm[a]["valor"]) for a in anos]))
            ult = pm[anos[-1]]
            blocos.append(f"<h3 style='font-size:.95rem;margin-top:14px'>Quem mandou Emenda Pix em {anos[-1]}</h3>" + tabela(["Autor", "#Valor"], [
                f"<tr><td class='f'>{autor_link(a)}</td><td class='num'>{brl(a['valor'])}</td></tr>" for a in ult["autores"][:20]]))
        resumo = (f"{nome} recebeu {compacto(m['total'])} em emendas parlamentares pagas em {ano_em}, de {len(m['autores'])} autores"
                  + (f", e {compacto(pix_total)} em Emendas Pix desde {min(pm)}" if pm else "") + ".")
        titulo = f"{nome} (MS): emendas parlamentares e Emendas Pix em {ano_em} | Cofre Aberto MS"
        jsonld = {"@context": "https://schema.org", "@type": "City", "name": f"{nome} (MS)", "url": SITE + url,
                  "containedInPlace": {"@type": "State", "name": "Mato Grosso do Sul"}}
        corpo = f"""<p class="breadcrumb"><a href="/">Início</a> / <a href="/municipio/">Municípios</a> / {e(nome)}</p>
<article><h1>{e(nome)}</h1>
<p class="cargo" style="margin-bottom:16px">{e(resumo)}</p>
{''.join(blocos)}
<div class="acoes" style="margin-top:18px"><a class="btn prim" href="/cofre-aberto-ms.html#aba=emendas&p={e(nome)}">Ver no painel</a>
<a class="btn" href="/dados/csv/emendas_municipios.csv" download>Baixar planilha (CSV)</a></div>
<h2>Como citar</h2>
<div class="citar">COFRE ABERTO MS. <i>{e(nome)} — emendas parlamentares em {ano_em}</i>. Fonte dos dados: Portal da Transparência do Governo Federal (CGU). Compilados em {data_br(HOJE.isoformat())}. Disponível em: {SITE}{url}.</div>
</article>"""
        html = cabecalho(titulo, resumo[:300], url, None, jsonld, tipo="website").replace("</style>", CSS_EXTRA + "</style>", 1) + corpo + RODAPE
        paginas.append({"slug": sl, "nome": nome, "total": m["total"], "pix": pix_total, "uniao": tu or 0, "autores": len(m["autores"]), "html": html})

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
    linhas = "".join(f"<tr data-n='{e(chave(p['nome']).lower())}'><td><a href='/municipio/{p['slug']}/'>{e(p['nome'])}</a></td><td class='num'>{brl(p['total'])}</td>"
                     f"<td class='num'>{brl(p['pix'])}</td><td class='num'>{brl(p['uniao']) if p['uniao'] else '—'}</td></tr>"
                     for p in sorted(paginas, key=lambda p: -p["total"]))
    idx = cabecalho(f"Municípios de MS — emendas parlamentares e Emendas Pix {ano_em} | Cofre Aberto MS",
                    f"Os {len(paginas)} municípios de Mato Grosso do Sul: quanto cada um recebeu de emendas parlamentares, de quem, Emendas Pix e transferências da União.",
                    "/municipio/", None, {"@context": "https://schema.org", "@type": "CollectionPage", "name": "Municípios de MS", "url": SITE + "/municipio/"},
                    tipo="website").replace("</style>", CSS_EXTRA + "</style>", 1) + f"""<p class="breadcrumb"><a href="/">Início</a> / Municípios</p>
<article><h1>Municípios de MS</h1><p class="cargo" style="margin-bottom:12px">{len(paginas)} municípios: emendas parlamentares pagas em {ano_em}, Emendas Pix desde 2020
e transferências da União em {ANO}. Clique no nome para ver de quem veio o dinheiro e quem recebeu.</p>
<input class="busca" id="busca-mun" type="search" placeholder="buscar município…" oninput="var q=this.value.normalize('NFD').replace(/[\\u0300-\\u036f]/g,'').toLowerCase().replace(/[^a-z]/g,'');document.querySelectorAll('#lst-mun tbody tr').forEach(function(t){{t.style.display=t.dataset.n.indexOf(q)>-1?'':'none'}})">
<div class="tabela-wrap"><table class="lst" id="lst-mun"><thead><tr><th>Município</th><th class="num">Emendas {ano_em}</th><th class="num">Emendas Pix (desde 2020)</th><th class="num">União {ANO}</th></tr></thead><tbody>{linhas}</tbody></table></div>
</article>""" + RODAPE
    escreve_se_mudou(PASTA / "index.html", idx)
    sm = ROOT / "sitemap.xml"
    if sm.exists():
        txt = re.sub(r"  <url><loc>[^<]*/municipio/[^<]*</loc>.*?</url>\n", "", sm.read_text(encoding="utf-8"))
        novos = [f"  <url><loc>{SITE}/municipio/{x}</loc><lastmod>{HOJE.isoformat()}</lastmod><changefreq>weekly</changefreq><priority>0.6</priority></url>"
                 for x in [""] + [p["slug"] + "/" for p in paginas]]
        escreve_se_mudou(sm, txt.replace("</urlset>", "\n".join(novos) + "\n</urlset>"))
    escreve_se_mudou(DADOS / "municipios_index.json", json.dumps({p["nome"]: f"/municipio/{p['slug']}/" for p in paginas},
                                                                 ensure_ascii=False, separators=(",", ":")))
    print(f"✅ {len(paginas)} páginas de municípios ({mudou} alteradas) + índice /municipio/ + sitemap")


if __name__ == "__main__":
    main()
