#!/usr/bin/env python3
"""
Cofre Aberto MS — Página própria de cada empresa: /empresa/<raiz do CNPJ>/

Junta, pela raiz do CNPJ (8 primeiros dígitos, agrupa as filiais), tudo o que a
empresa recebeu de dinheiro público de MS no ano:
  - notas fiscais pagas por vereadores, deputados e senadores de MS (cota/verba)
  - pagamentos da Prefeitura de Campo Grande, contratos e licitações vencidas
  - pagamentos do Governo do Estado
  - emendas parlamentares recebidas

Gera uma página por empresa relevante (paga por parlamentar, com contrato ou
licitação na Prefeitura, ou que recebeu valores altos do Estado ou de emendas),
o índice /empresa/, dados/empresas_index.json (raiz → endereço, usado pelo
painel) e acrescenta as páginas ao sitemap.xml.

Roda depois de gerar_paginas_parlamentares.py (que reescreve o sitemap).
"""

import json, re, sys
from collections import Counter
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).parent))
from gerar_analises import cnpj_valido, fmt_cnpj, limpa_nome, parlamentares  # noqa: E402
from gerar_paginas_parlamentares import (ANO, CSS, DADOS, HOJE, ROOT, RODAPE, SITE, brl, cabecalho, compacto,  # noqa: E402
                                         data_br, e, escreve_se_mudou, milhar)

PASTA = ROOT / "empresa"
CSS_EXTRA = """
.busca{width:100%;padding:10px 14px;margin:6px 0 16px;border:1px solid var(--border);border-radius:9px;background:var(--surface-2);color:var(--ink);font-size:.9rem}
.lst{width:100%}.lst td:first-child a{color:var(--ink);font-weight:600}
.citar{overflow-wrap:anywhere}
.tags span{display:inline-block;font-size:.68rem;border:1px solid var(--border);border-radius:999px;padding:1px 7px;margin:2px 3px 0 0;color:var(--ink-soft)}
"""


def carregar(nome):
    try:
        return json.load(open(DADOS / nome, encoding="utf-8"))
    except Exception:
        return {}


def digitos(t):
    return re.sub(r"\D", "", str(t or ""))


def empresa(mapa, d, nome):
    e_ = mapa.setdefault(d[:8], {"raiz": d[:8], "cnpjs": set(), "nomes": Counter(), "parl": {}, "pref": {"total": 0.0, "notas": 0, "orgaos": Counter()},
                                 "contratos": [], "licitacoes": [], "gov": {"pago": 0.0, "empenhado": 0.0}, "emendas": {"valor": 0.0, "autores": Counter()}})
    e_["cnpjs"].add(d)
    n = limpa_nome(nome)
    if n:
        e_["nomes"][n] += 1
    return e_


def coletar():
    mapa = {}
    paginas = carregar("paginas_index.json")
    for grupo, aba, rotulo, v, notas in parlamentares():
        for n in notas:
            d = digitos(n.get("cnpj"))
            if not cnpj_valido(d) or not n.get("valor"):
                continue
            x = empresa(mapa, d, n.get("fornecedor"))
            p = x["parl"].setdefault(f"{grupo}|{v['nome']}", {"nome": v["nome"], "rotulo": rotulo, "partido": v.get("partido"),
                                                            "aba": aba, "url": paginas.get(f"{grupo}|{v['nome']}"),
                                                            "total": 0.0, "notas": 0, "ultima": ""})
            p["total"] += float(n["valor"])
            p["notas"] += 1
            p["ultima"] = max(p["ultima"], str(n.get("data") or ""))
    pref = carregar("prefeitura.json")
    if pref.get("ano") == ANO:
        for d0 in pref.get("despesas", []):
            d = digitos(d0.get("cnpj"))
            if cnpj_valido(d) and d0.get("valor"):
                x = empresa(mapa, d, d0.get("fornecedor"))
                x["pref"]["total"] += d0["valor"]
                x["pref"]["notas"] += 1
                x["pref"]["orgaos"][d0.get("orgao") or "—"] += d0["valor"]
    ct = carregar("prefeitura_contratos.json")
    if ct.get("ano") == ANO:
        for c in ct.get("contratos", []):
            d = digitos(c.get("cnpj"))
            if cnpj_valido(d):
                empresa(mapa, d, c["fornecedor"])["contratos"].append(c)
        for l in ct.get("licitacoes", []):
            for v in l.get("vencedores", []):
                d = digitos(v.get("cnpj"))
                if cnpj_valido(d):
                    empresa(mapa, d, v["nome"])["licitacoes"].append(l)
    gov = carregar("governo_ms_credores.json")
    if gov.get("ano") == ANO:
        for c in gov.get("credores", []):
            d = digitos(c[0])
            if cnpj_valido(d) and (len(c) < 5 or c[4] == "fornecedor"):
                x = empresa(mapa, d, c[1])
                x["gov"]["pago"] += c[2] or 0
                x["gov"]["empenhado"] += c[3] or 0
    em = carregar("emendas_municipios.json")
    if em.get("ano") == ANO:
        for f in em.get("favorecidos", []):
            d = digitos(f.get("doc"))
            if cnpj_valido(d) and not re.search(r"MUNIC|FUNDO|ESTADO|SECRETARIA|PREFEITURA", f.get("nome", "").upper()):
                x = empresa(mapa, d, f["nome"])
                x["emendas"]["valor"] += f["valor"]
                for a in f.get("autores", []):
                    x["emendas"]["autores"][a["autor"]] += a["valor"]
    return mapa


def relevante(x):
    parl = sum(p["total"] for p in x["parl"].values())
    fontes = sum(bool(v) for v in (parl, x["pref"]["total"], x["contratos"], x["licitacoes"], x["gov"]["pago"], x["emendas"]["valor"]))
    return (parl >= 1000 and (fontes >= 2 or parl >= 5000 or len(x["parl"]) >= 2)) or x["contratos"] or x["licitacoes"] \
        or x["gov"]["pago"] >= 1_000_000 or x["emendas"]["valor"] >= 100_000 or (fontes >= 2 and x["pref"]["total"] >= 50_000)


def resumo(x):
    parl = sum(p["total"] for p in x["parl"].values())
    return {"parl": parl, "pref": x["pref"]["total"], "contratos": sum(c["valor"] for c in x["contratos"] if c.get("compra")),
            "gov": x["gov"]["pago"], "emendas": x["emendas"]["valor"]}


def pagina(x, nome):
    r = resumo(x)
    raiz = x["raiz"]
    cnpjs = sorted(x["cnpjs"])
    url = f"/empresa/{raiz}/"
    fontes = []
    if x["parl"]:
        fontes.append(f"{len(x['parl'])} parlamentar(es) de MS")
    if r["pref"] or x["contratos"]:
        fontes.append("Prefeitura de Campo Grande")
    if r["gov"]:
        fontes.append("Governo do Estado")
    if r["emendas"]:
        fontes.append("emendas parlamentares")
    total = r["parl"] + r["pref"] + r["gov"] + r["emendas"]
    titulo = f"{nome} (CNPJ {fmt_cnpj(cnpjs[0])[:10]}): quanto recebeu do poder público em MS | Cofre Aberto MS"
    desc = (f"{nome} recebeu {compacto(total)} em {ANO} de " + ", ".join(fontes)
            + ". Veja notas fiscais, contratos, licitações e quem pagou, com links para as fontes oficiais.")
    jsonld = {"@context": "https://schema.org", "@type": "Organization", "name": nome, "taxID": fmt_cnpj(cnpjs[0]),
              "url": SITE + url, "subjectOf": {"@type": "Dataset", "name": f"Pagamentos públicos a {nome} em {ANO}",
                                               "url": SITE + url, "creator": {"@type": "Organization", "name": "Cofre Aberto MS"}}}
    itens = []
    if r["parl"]:
        itens.append((brl(r["parl"]), f"de parlamentares de MS ({milhar(sum(p['notas'] for p in x['parl'].values()))} nota{'s' if sum(p['notas'] for p in x['parl'].values()) > 1 else ''})"))
    if r["pref"]:
        itens.append((brl(r["pref"]), f"pagos pela Prefeitura de CG ({x['pref']['notas']} empenho{'s' if x['pref']['notas'] > 1 else ''})"))
    if x["contratos"]:
        itens.append((brl(r["contratos"]), f"em {len(x['contratos'])} contrato(s) com a Prefeitura"))
    if x["licitacoes"]:
        itens.append((milhar(len(x["licitacoes"])), "licitações vencidas na Prefeitura"))
    if r["gov"]:
        itens.append((brl(r["gov"]), "pagos pelo Governo do Estado"))
    if r["emendas"]:
        itens.append((brl(r["emendas"]), "recebidos de emendas parlamentares"))
    grid = "<div class='resumo-grid'>" + "".join(f"<div class='resumo-item'><div class='resumo-val'>{e(v)}</div><div class='resumo-label'>{e(l)}</div></div>" for v, l in itens) + "</div>"
    receita = " · ".join(f"<a href='https://solucoes.receita.fazenda.gov.br/Servicos/cnpjreva/Cnpjreva_Solicitacao.asp?cnpj={c}' target='_blank' rel='noopener'>{fmt_cnpj(c)}</a>" for c in cnpjs[:8])
    if len(cnpjs) > 8:
        receita += f" e mais {len(cnpjs) - 8} filiais"
    corpo = [f"""<p class="breadcrumb"><a href="/">Início</a> / <a href="/empresa/">Empresas</a> / {e(nome)}</p>
<article><h1>{e(nome)}</h1>
<p class="cargo">CNPJ {receita}</p>
<p class="cargo" style="margin-bottom:16px;font-size:.8rem">Os links abrem o comprovante na Receita Federal com o número já preenchido.</p>
{grid}
<p class="aviso">Receber de órgãos públicos ou de vários parlamentares <b>não indica irregularidade</b>: esta página só junta o que já está publicado nas fontes oficiais, para facilitar a consulta. Valores de {ANO}, atualizados todos os dias.</p>
<div class="acoes"><a class="btn prim" href="/cofre-aberto-ms.html#aba=conexoes&p={cnpjs[0]}">Ver nas Conexões do painel</a>
<a class="btn" href="/dados/csv/conexoes_fornecedores.csv" download>Baixar planilha (CSV)</a></div>"""]

    if x["parl"]:
        def nome_link(p):
            return f"<a href='{p['url']}'>{e(p['nome'])}</a>" if p["url"] else e(p["nome"])
        linhas = "".join(
            f"<tr><td class='f'>{nome_link(p)}"
            f"<small>{e(p['rotulo'])}{' · ' + e(p['partido']) if p['partido'] else ''}</small></td>"
            f"<td class='num'>{p['notas']}</td><td>{data_br(p['ultima'])}</td><td class='num'>{brl(p['total'])}</td></tr>"
            for p in sorted(x["parl"].values(), key=lambda p: -p["total"]))
        corpo.append(f"""<h2>Parlamentares que pagaram esta empresa</h2>
<p>Notas fiscais da cota parlamentar ou da verba indenizatória lançadas em {ANO}. Clique no nome para ver cada nota.</p>
<div class="tabela-wrap"><table><thead><tr><th>Parlamentar</th><th class="num">Notas</th><th>Última nota</th><th class="num">Valor</th></tr></thead><tbody>{linhas}</tbody></table></div>""")

    if r["pref"]:
        org = "".join(f"<tr><td class='f'>{e(o)}</td><td class='num'>{brl(v)}</td></tr>" for o, v in x["pref"]["orgaos"].most_common(8))
        corpo.append(f"""<h2>Prefeitura de Campo Grande — pagamentos</h2>
<p>{brl(r['pref'])} pagos em {x['pref']['notas']} empenho{'s' if x['pref']['notas'] > 1 else ''} em {ANO}, por órgão:</p>
<div class="tabela-wrap"><table><thead><tr><th>Órgão</th><th class="num">Pago</th></tr></thead><tbody>{org}</tbody></table></div>
<p style="margin-top:10px"><a href="/cofre-aberto-ms.html#aba=prefeitura&p={quote(nome)}">Ver os empenhos no painel →</a></p>""")

    if x["contratos"]:
        lin = "".join(f"<tr><td>{data_br(c['inicio'])}</td><td class='f'>{e(c['tipo'].capitalize())}<small>{e(c['objeto'][:220])}</small></td>"
                      f"<td>{data_br(c['fim'])}</td><td class='num'>{brl(c['valor'])}</td></tr>"
                      for c in sorted(x["contratos"], key=lambda c: -c["valor"]))
        corpo.append(f"""<h2>Contratos com a Prefeitura de Campo Grande</h2>
<div class="tabela-wrap"><table><thead><tr><th>Início</th><th>Objeto</th><th>Vigência até</th><th class="num">Valor</th></tr></thead><tbody>{lin}</tbody></table></div>""")

    if x["licitacoes"]:
        lin = "".join(f"<tr><td>{data_br(l['data'])}</td><td class='f'>{e(l['modalidade'])} nº {e(l['numero'])}<small>{e(l['objeto'][:220])}</small></td>"
                      f"<td>{e(l['status'])}</td><td class='num'>{brl(l['valorEstimado']) if l.get('valorEstimado') else '—'}</td></tr>"
                      for l in sorted(x["licitacoes"], key=lambda l: l["data"] or "", reverse=True)[:60])
        corpo.append(f"""<h2>Licitações vencidas na Prefeitura</h2>
<p>O valor estimado é o da licitação inteira; o portal não divide entre as empresas vencedoras.</p>
<div class="tabela-wrap"><table><thead><tr><th>Data</th><th>Licitação</th><th>Situação</th><th class="num">Valor estimado</th></tr></thead><tbody>{lin}</tbody></table></div>""")

    if r["gov"]:
        corpo.append(f"""<h2>Governo do Estado de MS</h2>
<p>{brl(r['gov'])} pagos em {ANO} (inclui restos a pagar de anos anteriores) e {brl(x['gov']['empenhado'])} empenhados no ano,
segundo o Portal da Transparência do Estado. <a href="/cofre-aberto-ms.html#aba=governo-ms">Ver no painel →</a></p>""")

    if r["emendas"]:
        aut = ", ".join(f"{e(a)} ({brl(v)})" for a, v in x["emendas"]["autores"].most_common(8))
        corpo.append(f"""<h2>Emendas parlamentares</h2>
<p>{brl(r['emendas'])} recebidos em {ANO} por emendas de: {aut}.</p>""")

    corpo.append(f"""<h2>Como citar</h2>
<div class="citar">COFRE ABERTO MS. <i>{e(nome)} — pagamentos públicos em {ANO}</i>. Dados das fontes oficiais compilados em {data_br(HOJE.isoformat())}. Disponível em: {SITE}{url}.</div>
</article>""")
    return cabecalho(titulo, desc, url, None, jsonld, tipo="website").replace("</style>", CSS_EXTRA + "</style>", 1) + "\n".join(corpo) + RODAPE


def indice(lista):
    url = "/empresa/"
    titulo = f"Empresas que recebem de políticos e governos de MS — {ANO} | Cofre Aberto MS"
    desc = f"{milhar(len(lista))} empresas pagas por parlamentares, pela Prefeitura de Campo Grande e pelo Governo de MS em {ANO}, com contratos e licitações."
    linhas = "".join(
        f"<tr><td><a href='/empresa/{x['raiz']}/'>{e(x['nome'])}</a><div class='tags'>{''.join(f'<span>{t}</span>' for t in x['tags'])}</div></td>"
        f"<td class='num'>{compacto(x['total'])}</td></tr>" for x in lista)
    corpo = f"""<p class="breadcrumb"><a href="/">Início</a> / Empresas</p>
<article><h1>Empresas</h1>
<p class="cargo" style="margin-bottom:6px">{milhar(len(lista))} empresas que receberam dinheiro público em MS em {ANO}: de vereadores, deputados e senadores, da Prefeitura de Campo Grande (pagamentos, contratos e licitações), do Governo do Estado e de emendas.</p>
<input class="busca" id="busca" type="search" placeholder="buscar empresa ou CNPJ…" aria-label="Buscar empresa"/>
<div class="tabela-wrap"><table class="lst" id="lst"><thead><tr><th>Empresa</th><th class="num">Total recebido</th></tr></thead><tbody>{linhas}</tbody></table></div>
</article>
<script>
(function(){{var b=document.getElementById("busca"),rs=[].slice.call(document.querySelectorAll("#lst tbody tr"));
b.addEventListener("input",function(){{var f=b.value.trim().toLowerCase(),d=f.replace(/\\D/g,"");
rs.forEach(function(r){{var a=r.querySelector("a");r.style.display=(!f||r.textContent.toLowerCase().indexOf(f)>=0||(d.length>=4&&a.getAttribute("href").indexOf(d.slice(0,8))>=0))?"":"none";}});}});}})();
</script>"""
    jsonld = {"@context": "https://schema.org", "@type": "CollectionPage", "name": titulo, "url": SITE + url}
    return cabecalho(titulo, desc, url, None, jsonld, tipo="website").replace("</style>", CSS_EXTRA + "</style>", 1) + corpo + RODAPE


def main():
    mapa = coletar()
    escolhidas = []
    for x in mapa.values():
        if not relevante(x):
            continue
        nome = x["nomes"].most_common(1)[0][0] if x["nomes"] else fmt_cnpj(min(x["cnpjs"]))
        r = resumo(x)
        tags = []
        if x["parl"]:
            tags.append(f"{len(x['parl'])} parlamentar(es)")
        if r["pref"]:
            tags.append("Prefeitura")
        if x["contratos"]:
            tags.append(f"{len(x['contratos'])} contrato(s)")
        if x["licitacoes"]:
            tags.append(f"{len(x['licitacoes'])} licitação(ões)")
        if r["gov"]:
            tags.append("Governo MS")
        if r["emendas"]:
            tags.append("emendas")
        escolhidas.append({"raiz": x["raiz"], "nome": nome, "x": x, "tags": tags,
                           "total": r["parl"] + r["pref"] + r["gov"] + r["emendas"]})
    escolhidas.sort(key=lambda x: -x["total"])
    PASTA.mkdir(exist_ok=True)
    validos, mudou = set(), 0
    for x in escolhidas:
        caminho = PASTA / x["raiz"] / "index.html"
        validos.add(caminho.parent)
        mudou += escreve_se_mudou(caminho, pagina(x["x"], x["nome"]))
    for d in PASTA.iterdir():
        if d.is_dir() and d not in validos:
            for f in d.iterdir():
                f.unlink()
            d.rmdir()
    escreve_se_mudou(PASTA / "index.html", indice(escolhidas))
    escreve_se_mudou(DADOS / "empresas_index.json", json.dumps({x["raiz"]: x["nome"] for x in escolhidas},
                                                               ensure_ascii=False, separators=(",", ":")))
    # sitemap: tira as entradas antigas de /empresa/ e acrescenta as atuais
    sm = ROOT / "sitemap.xml"
    if sm.exists():
        txt = re.sub(r"  <url><loc>[^<]*/empresa/[^<]*</loc>.*?</url>\n", "", sm.read_text(encoding="utf-8"))
        hoje = HOJE.isoformat()
        novos = [f"  <url><loc>{SITE}/empresa/</loc><lastmod>{hoje}</lastmod><changefreq>daily</changefreq><priority>0.7</priority></url>"]
        novos += [f"  <url><loc>{SITE}/empresa/{x['raiz']}/</loc><lastmod>{hoje}</lastmod><changefreq>weekly</changefreq><priority>0.5</priority></url>"
                  for x in escolhidas]
        escreve_se_mudou(sm, txt.replace("</urlset>", "\n".join(novos) + "\n</urlset>"))
    print(f"✅ {len(escolhidas)} páginas de empresas ({mudou} alteradas) + índice /empresa/ + sitemap")


if __name__ == "__main__":
    main()
