#!/usr/bin/env python3
"""
Cofre Aberto MS — atualiza os números das páginas estáticas a partir dos JSONs

O painel (cofre-aberto-ms.html) lê os JSONs ao vivo, mas a capa (index.html)
e as páginas de SEO (vereadores-campo-grande.html, deputados-estaduais-ms.html,
senadores-ms.html) têm os números escritos no HTML — de propósito, para o
Google indexar texto. Até nov/2026 eles eram editados à mão e ficaram parados
em julho. Este script roda no fim da coleta diária (GitHub Actions) e
reescreve só os trechos de números/tabelas, sem mexer no resto do HTML.
"""

import json, re
from datetime import date
import sys as _sys
from pathlib import Path
_sys.path.insert(0, str(Path(__file__).parent))
from ano_ref import ano_referencia
ANO = ano_referencia()

ROOT = Path(__file__).parent.parent
DADOS = ROOT / "dados"
MESES = ["Jan", "Fev", "Mar", "Abr", "Mai", "Jun", "Jul", "Ago", "Set", "Out", "Nov", "Dez"]


def carregar(nome):
    try:
        return json.load(open(DADOS / nome, encoding="utf-8"))
    except Exception:
        return {}


def brl(v):
    s = f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {s}"


def milhar(n):
    return f"{n:,}".replace(",", ".")


def compacto_mi(v):
    return f"R$ {v / 1e6:,.1f}mi".replace(",", "X").replace(".", ",").replace("X", ".") if v < 1e8 \
        else f"R$ {round(v / 1e6):,}mi".replace(",", ".")


def troca(html, padrao, novo, nome, flags=re.S):
    html2, n = re.subn(padrao, novo, html, count=1, flags=flags)
    if not n:
        print(f"  ⚠️ trecho não encontrado: {nome}")
    return html2


def tabela(linhas):
    return "\n".join("      <tr>\n" + "\n".join(f"        {c}" for c in l) + "\n      </tr>" for l in linhas)


def resumo_grid(itens):
    return "\n".join(f'      <div class="resumo-item"><div class="resumo-val">{v}</div>'
                     f'<div class="resumo-label">{r}</div></div>' for v, r in itens)


_IDX = None
def link_nome(grupo, nome):
    """<td class="nome"> com link para a página própria (se existir)."""
    global _IDX
    if _IDX is None:
        _IDX = carregar("paginas_index.json")
    url = _IDX.get(f"{grupo}|{nome}")
    return f'<td class="nome"><a href="{url}" style="color:inherit;text-decoration:underline;text-decoration-color:var(--border)">{nome}</a></td>' if url else f'<td class="nome">{nome}</td>'


MESES_EXTENSO = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto",
                 "setembro", "outubro", "novembro", "dezembro"]


def valor_curto(v):
    """R$ 4,1 bi / R$ 323,5 mi / R$ 5,7 mi / R$ 214,5 mil — para o kit de imprensa."""
    v = float(v or 0)
    for lim, suf in ((1e9, "bi"), (1e6, "mi"), (1e3, "mil")):
        if v >= lim:
            return f"R$ {v / lim:,.1f} {suf}".replace(",", "X").replace(".", ",").replace("X", ".")
    return brl(v)


def troca_auto(html, nome, novo):
    """Substitui o conteúdo entre <!-- auto:nome --> e <!-- /auto:nome -->."""
    padrao = rf"(<!-- auto:{nome} -->).*?(<!-- /auto:{nome} -->)"
    if not re.search(padrao, html, re.S):
        print(f"  ⚠️ marcador auto:{nome} não encontrado")
        return html
    return re.sub(padrao, lambda m: m.group(1) + novo + m.group(2), html, count=1, flags=re.S)


def atualizar_kit_imprensa(cg, est, fed, sen, pref, emendas, mags, status, cx, camaras_n):
    p = ROOT / "press.html"
    if not p.exists():
        return
    html = p.read_text(encoding="utf-8")
    vereadores, deps_est = cg.get("vereadores", []), est.get("vereadores", [])
    deps_fed, senadores = fed.get("deputados", []), sen.get("senadores", [])
    vi = lambda v: v.get("verbaIndenizatoria") or {}
    verba_cg = sum(vi(v).get(f"gastoPago{ANO}") or 0 for v in vereadores)
    ceap_est = sum(vi(d).get(f"gastoPago{ANO}") or 0 for d in deps_est)
    ceap_fed = sum(d.get("cotaGastaAno") or 0 for d in deps_fed)
    ceaps_sen = sum(s.get("cotaGastaAno") or 0 for s in senadores)
    n_notas = (sum(v.get("totalNotasFiscais") or 0 for v in vereadores) + sum(len(d.get("despesas") or []) for d in deps_est)
               + sum(len(d.get("despesas") or []) for d in deps_fed) + sum(len(s.get("notasCeaps") or []) for s in senadores)
               + (pref.get("totalNotasFiscais") or 0))
    folha_cg = (cg.get("resumo") or {}).get("totalGastoPessoalMensal") or 0
    func_cg = (cg.get("resumo") or {}).get("totalFuncionariosGabinetes") or 0
    ref_pessoal = cg.get("referenciaPessoal") or ""
    emendas_tot = emendas.get("totalGeralPago") or 0
    pref_tot = pref.get("totalDespesas") or 0
    folha_jud = sum((m.get("resumo") or {}).get("totalFolhaMensalBrutaAtivos") or 0 for m in mags)
    ativos = sum((m.get("resumo") or {}).get("totalAtivos") or 0 for m in mags if "TRE" not in str(m.get("fonte", "")))  # juízes eleitorais = juízes do TJMS
    gov = carregar("governo_ms.json")
    gov_tot = ((gov.get("totais") or {}).get("pago") or 0) if gov.get("ano") == ANO else 0
    ss = carregar("supersalarios.json")
    au = carregar("auditoria.json")
    total_cat = gov_tot + pref_tot + verba_cg + ceap_est + ceap_fed + ceaps_sen + emendas_tot

    data_ref = (status.get("ultimaAtualizacao") or date.today().isoformat())[:10]
    a, m, d = data_ref.split("-")
    html = troca_auto(html, "data", f'<p class="nota">Última atualização: {int(d)} de {MESES_EXTENSO[int(m) - 1]} de {a} '
                                    f'(números recalculados automaticamente a cada coleta diária)</p>')
    html = troca_auto(html, "cobertura", f"""<ul>
      <li>{len(vereadores)} vereadores da Câmara Municipal de Campo Grande</li>
      <li>{len(deps_est)} deputados estaduais da Assembleia Legislativa de MS (ALEMS)</li>
      <li>{len(deps_fed)} deputados federais de Mato Grosso do Sul</li>
      <li>{len(senadores)} senadores de Mato Grosso do Sul</li>
      <li>Governo do Estado de MS (despesas, contratos, obras, licitações, diárias e folha) e Prefeitura Municipal de Campo Grande (despesas, contratos e aditivos)</li>
      <li>{ativos} magistrados ativos do TJMS e do TRT24 (os juízes eleitorais do TRE-MS são juízes do TJMS)</li>
      <li>Supersalários: as maiores remunerações do poder público em MS, com nome e penduricalhos</li>
      <li>Auditoria automática: {len(au.get("regras") or {})} testes que cruzam notas e contratos com a Receita Federal, o TSE, a folha do Estado e as sanções da CGU</li>
      <li>Brasil: Presidência da República (cartão corporativo desde 2013, viagens, despesas, salários), STF (contracheques dos ministros), 513 deputados federais e 81 senadores</li>
      <li>Câmaras municipais de {camaras_n} cidades do interior de MS.</li>
    </ul>""")
    linhas = [
        (milhar(n_notas), "Notas fiscais e empenhos individuais catalogados (fornecedor, CNPJ e valor)"),
        (valor_curto(total_cat) + "+", f"Total de gastos públicos catalogados em {ANO} (Governo do Estado, Prefeitura de CG, verba indenizatória, CEAP estadual e federal, CEAPS, emendas parlamentares)"),
        *([(valor_curto(gov_tot), f"Pagos pelo Governo do Estado de MS em {ANO}")] if gov_tot else []),
        (valor_curto(pref_tot), f"Pagos pela Prefeitura de Campo Grande em {ANO}, em {milhar(pref.get('totalNotasFiscais') or 0)} empenhos"),
        (valor_curto(verba_cg), f"Verba indenizatória paga aos {len(vereadores)} vereadores de Campo Grande em {ANO}"),
        (valor_curto(ceap_est), f"CEAP paga aos {len(deps_est)} deputados estaduais de MS em {ANO}"),
        (valor_curto(ceap_fed), f"CEAP dos {len(deps_fed)} deputados federais de MS em {ANO}"),
        (valor_curto(ceaps_sen), f"CEAPS dos {len(senadores)} senadores de MS em {ANO}"),
        (valor_curto(emendas_tot), f"Emendas parlamentares pagas em Mato Grosso do Sul em {ANO}"),
        (valor_curto(folha_cg) + "/mês", f"Folha de pessoal dos {len(vereadores)} gabinetes da Câmara de Campo Grande ({milhar(func_cg)} funcionários, {ref_pessoal})"),
        (valor_curto(folha_jud) + "/mês", f"Folha bruta dos {ativos} magistrados ativos de MS (TJMS e TRT24, com a gratificação eleitoral do TRE-MS)"),
    ]
    if cx:
        linhas.append((milhar(cx), "Empresas pagas por mais de um político de MS ou também pela Prefeitura (aba Conexões)"))
    if ss.get("liquidoAcimaTeto"):
        linhas.append((milhar(ss["liquidoAcimaTeto"]), f"Pessoas com líquido acima do teto constitucional no último mês publicado (aba Supersalários)"))
    if au.get("sinais"):
        linhas.append((milhar(len(au["sinais"])), f"Sinais de atenção da Auditoria automática ({sum(1 for x in au['sinais'] if x['nivel'] == 'forte')} de nível forte)"))
    linhas.append(("100%", "Dos dados vêm de fontes oficiais — estimativas são sempre marcadas (ver Metodologia)"))
    tabela = "\n".join(f'      <tr><td class="valor">{v}</td><td class="desc">{t}</td></tr>' for v, t in linhas)
    html = troca_auto(html, "numeros", '<table class="numeros">\n' + tabela + "\n    </table>")

    # pauta: uso da cota (do maior ao menor), com nomes
    uso = sorted(((vi(v).get(f"gastoPago{ANO}") or 0) / (vi(v).get(f"cotaAnual{ANO}") or 300000) * 100, v["nome"]) for v in vereadores)
    if uso:
        (pmin, nmin), (pmax, nmax) = uso[0], uso[-1]
        html = troca_auto(html, "pauta-verba",
            f'<li><strong>"Quem mais e quem menos gastou a verba indenizatória em {ANO}"</strong> — entre os {len(vereadores)} vereadores '
            f'de Campo Grande, o uso da cota anual de R$ 300 mil por gabinete vai de {pmin:.0f}% ({nmin}) a {pmax:.0f}% ({nmax}). '
            f'Bom gancho para pedir explicação aos gabinetes nos dois extremos — o painel mostra mês a mês e nota a nota.</li>')
    if folha_cg:
        media = func_cg / len(vereadores) if vereadores else 0
        html = troca_auto(html, "pauta-folha",
            f'<li><strong>"{valor_curto(folha_cg)} por mês: o custo da folha de pessoal dos gabinetes da Câmara de Campo Grande"</strong> '
            f'— com {milhar(func_cg)} funcionários distribuídos entre {len(vereadores)} gabinetes ({ref_pessoal}), uma média de '
            f'{media:.1f}'.replace(".", ",") + ' funcionários por vereador. Bom gancho para comparar com outras capitais de porte semelhante.</li>')
    if emendas_tot:
        html = troca_auto(html, "pauta-emendas",
            f'<li><strong>"Emendas parlamentares somam {valor_curto(emendas_tot)} em MS neste ano"</strong> — matéria sobre para onde vai '
            f'o dinheiro das emendas de deputados e senadores sul-mato-grossenses, com o ranking por parlamentar disponível no painel.</li>')
    p.write_text(html, encoding="utf-8")
    md = press_md(html)
    if md:
        (ROOT / "PRESS.md").write_text(md, encoding="utf-8")
    print(f"✅ press.html + PRESS.md — {milhar(n_notas)} notas, total {valor_curto(total_cat)}")



def press_md(html):
    """Gera o PRESS.md a partir do <article> do press.html (mesmo conteúdo, sem manter duas versões)."""
    import html as _h
    art = re.search(r"<article>(.*?)</article>", html, re.S)
    if not art:
        return None
    t = re.sub(r"<!--.*?-->", "", art.group(1), flags=re.S)

    def inline(x):
        x = re.sub(r"<(strong|b)>(.*?)</\1>", r"**\2**", x, flags=re.S)
        x = re.sub(r"<(em|i)>(.*?)</\1>", r"*\2*", x, flags=re.S)
        x = re.sub(r'<a [^>]*href="([^"]+)"[^>]*>(.*?)</a>', r"[\2](\1)", x, flags=re.S)
        x = re.sub(r"<[^>]+>", "", x)
        return re.sub(r"\s+", " ", _h.unescape(x)).strip()

    def tabela(m):
        linhas = re.findall(r"<tr>(.*?)</tr>", m.group(0), re.S)
        out = []
        if linhas and re.search(r'class="valor"', linhas[0]):
            out += ["| Número | O que é |", "|---|---|"]
        for i, l in enumerate(linhas):
            cels = [inline(c) for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", l, re.S)]
            if cels and re.search(r'class="valor"', l):
                cels[0] = f"**{cels[0]}**"
            out.append("| " + " | ".join(cels) + " |")
            if i == 0 and len(out) == 1:
                out.append("|" + "---|" * len(cels))
        return "\n" + "\n".join(out) + "\n"

    t = re.sub(r"<table.*?</table>", tabela, t, flags=re.S)
    t = re.sub(r"<h2[^>]*>(.*?)</h2>", lambda m: "\n## " + inline(m.group(1)) + "\n", t, flags=re.S)
    t = re.sub(r"<h3[^>]*>(.*?)</h3>", lambda m: "\n### " + inline(m.group(1)) + "\n", t, flags=re.S)
    def lista(m, ordenada):
        itens = re.findall(r"<li>(.*?)</li>", m.group(0), re.S)
        return "\n" + "\n".join((f"{i + 1}. " if ordenada else "- ") + inline(x) for i, x in enumerate(itens)) + "\n"
    t = re.sub(r"<ol>.*?</ol>", lambda m: lista(m, True), t, flags=re.S)
    t = re.sub(r"<ul>.*?</ul>", lambda m: lista(m, False), t, flags=re.S)
    t = re.sub(r"<p[^>]*>(.*?)</p>", lambda m: "\n" + inline(m.group(1)) + "\n", t, flags=re.S)
    t = re.sub(r"<[^>]+>", "", t)
    t = "\n".join(l.rstrip() for l in t.split("\n"))
    t = re.sub(r"\n{3,}", "\n\n", t).strip()
    data = re.search(r"Última atualização: ([^<(]+)", html)
    topo = "# Kit de Imprensa — Cofre Aberto MS\n\n"
    if data:
        topo += f"*Última atualização: {data.group(1).strip()} — gerado automaticamente a partir de press.html*\n\n"
    return topo + t + "\n"

def main():
    cg = carregar("camara_municipal.json")
    est = carregar("deputados_estaduais_ms.json")
    fed = carregar("deputados_federais_ms.json")
    sen = carregar("senadores_ms.json")
    senbr = carregar("senadores_brasil.json")
    emendas = carregar("emendas_ms.json")
    mags = [carregar(f) for f in ("trt24_magistrados.json", "tre_ms_magistrados.json", "tjms_magistrados.json")]
    status = carregar("status.json")

    vereadores = cg.get("vereadores", [])
    deps_est = est.get("vereadores", [])
    deps_fed = fed.get("deputados", [])
    senadores = sen.get("senadores", [])

    n_cg = sum(v.get("totalNotasFiscais") or len(v.get("despesas") or []) for v in vereadores)
    n_est = sum(len(d.get("despesas") or []) for d in deps_est)
    n_fed = sum(len(d.get("despesas") or []) or (d.get("totalNotasFiscais") or 0) for d in deps_fed)
    n_sen = sum(len(s.get("notasCeaps") or []) for s in senadores)
    n_total = n_cg + n_est + n_fed + n_sen
    ceap_est = (est.get("resumo") or {}).get(f"totalVerbaIndenizatoriaPaga{ANO}") or \
        sum((d.get("verbaIndenizatoria") or {}).get(f"gastoPago{ANO}") or 0 for d in deps_est)
    verba_cg = sum((v.get("verbaIndenizatoria") or {}).get(f"gastoPago{ANO}") or 0 for v in vereadores)
    ativos = sum((m.get("resumo") or {}).get("totalAtivos") or 0 for m in mags if "TRE" not in str(m.get("fonte", "")))  # juízes eleitorais = juízes do TJMS
    mes_fim = "Dez" if ANO < date.today().year else MESES[date.today().month - 1]
    periodo = f"Jan–{mes_fim}/{ANO}"

    # ---------------- index.html (capa) ----------------
    p = ROOT / "index.html"
    html = p.read_text(encoding="utf-8")

    def stat(html, rotulo, valor_txt, contagem=None):
        attr = f' data-count="{contagem}"' if contagem is not None else ""
        # rótulos com ano ("CEAP Estadual 2026") casam qualquer ano e são reescritos com o ano de referência
        padrao_rot = re.escape(rotulo).replace(str(ANO), r"\d{4}")
        html = re.sub(rf'(<(?:div|span) class="stat-label">){padrao_rot}<', rf"\g<1>{rotulo}<", html)
        return troca(html,
                     rf'(<(div|span) class="stat-val")[^>]*>[^<]*(</\2>\s*<(?:div|span) class="stat-label">{re.escape(rotulo)}<)',
                     rf'\1{attr}>{valor_txt}\3', f"capa: {rotulo}")

    n_parl = len(vereadores) + len(deps_est) + len(deps_fed) + len(senadores)
    html = stat(html, "Parlamentares de MS", n_parl, n_parl)
    html = stat(html, "Notas fiscais de parlamentares", milhar(n_total), n_total)
    html = re.sub(r'(<span data-auto="notas">)[^<]*(</span>)', rf"\g<1>{milhar(n_total)}\2", html)
    gov_p = (carregar("governo_ms.json").get("totais") or {}).get("pago")
    if gov_p:
        html = stat(html, "Pagos pelo Governo MS", valor_curto(gov_p))
    pref_p = carregar("prefeitura.json").get("totalDespesas")
    if pref_p:
        html = stat(html, "Pagos pela Prefeitura de CG", valor_curto(pref_p))
        html = re.sub(r'(<div class="aba-num">)[^<]+(</div>\s*<div class="aba-title">Despesas da Prefeitura)', rf"\g<1>{valor_curto(pref_p)}\2", html)
    em_ms = carregar("emendas_municipios.json").get("totalMS")
    if em_ms:
        html = stat(html, "Emendas recebidas em MS", valor_curto(em_ms))
    ss_liq = carregar("supersalarios.json").get("liquidoAcimaTeto")
    if ss_liq is not None:
        html = stat(html, "Líquido acima do teto", milhar(ss_liq), ss_liq)
        html = re.sub(r'(<div class="aba-num">)[^<]+(</div>\s*<div class="aba-title">Supersalários)', rf"\g<1>{milhar(ss_liq)}\2", html)
    n_ctr = (carregar("prefeitura_contratos.json").get("resumo") or {}).get("contratos")
    if n_ctr:
        html = stat(html, "Contratos da Prefeitura", milhar(n_ctr), n_ctr)
    n_emp_i = len(carregar("empresas_index.json") or {})
    if n_emp_i:
        html = stat(html, "Páginas de empresas", milhar(n_emp_i), n_emp_i)
    n_org = len(carregar("orgaos_index.json") or {})
    if n_org:
        html = stat(html, "Páginas de órgãos", milhar(n_org), n_org)
        html = re.sub(r'(<div class="aba-num">)\d+(</div>\s*<div class="aba-title">Páginas de órgãos)', rf"\g<1>{n_org}\2", html)
    html = re.sub(r"\d{1,3}(?:\.\d{3})* notas fiscais reais", f"{milhar(n_total)} notas fiscais reais", html)
    html = re.sub(r"<p>\d{1,3}(?:\.\d{3})* notas fiscais com fornecedor", f"<p>{milhar(n_total)} notas fiscais com fornecedor", html)
    html = re.sub(r"(pessoal dos gabinetes, )\d{1,3}(?:\.\d{3})*( notas fiscais)", rf"\g<1>{milhar(n_cg)}\2", html)
    html = re.sub(r"CEAP Jan–\w{3}/\d{4}, \d{1,3}(?:\.\d{3})*( notas fiscais)", f"CEAP {periodo}, {milhar(n_est)}\\1", html)
    html = re.sub(r"(CEAPS \d{4} com )\d{1,3}(?:\.\d{3})*( notas fiscais)", rf"\g<1>{milhar(n_sen)}\2", html)
    html = re.sub(r"(CEAP \d{4} com )\d{1,3}(?:\.\d{3})*( notas fiscais, fotos)", rf"\g<1>{milhar(n_fed)}\2", html)
    html = re.sub(r'(<div class="aba-num">)\d+(</div>\s*<div class="aba-title">Dep\. Estaduais)', rf"\g<1>{len(deps_est)}\2", html)
    if ativos:
        html = re.sub(r'(<div class="aba-num">)\d+(</div>\s*<div class="aba-title">Judiciário MS)', rf"\g<1>{ativos}\2", html)
    cx = carregar("conexoes_fornecedores.json").get("totalEmpresas")
    if cx:
        html = re.sub(r'(<div class="aba-num">)\d+(</div>\s*<div class="aba-title">Conexões entre fornecedores)', rf"\g<1>{cx}\2", html)
    gov_pago = (carregar("governo_ms.json").get("totais") or {}).get("pago")
    if gov_pago:
        gtxt = f"R$ {gov_pago / 1e9:.1f} bi".replace(".", ",")
        html = re.sub(r'(<div class="aba-num">)[^<]+(</div>\s*<div class="aba-title">Governo do Estado de MS)', rf"\g<1>{gtxt}\2", html)
    n_ct = (carregar("prefeitura_contratos.json").get("resumo") or {}).get("contratos")
    if n_ct:
        html = re.sub(r'(<div class="aba-num">)\d+(</div>\s*<div class="aba-title">Contratos e licitações)', rf"\g<1>{n_ct}\2", html)
    n_mun = carregar("emendas_municipios.json").get("totalMunicipios")
    if n_mun:
        html = re.sub(r'(<div class="aba-num">)\d+(</div>\s*<div class="aba-title">Emendas por município)', rf"\g<1>{n_mun}\2", html)
    n_emp = len(carregar("empresas_index.json") or {})
    if n_emp:
        html = re.sub(r'(<div class="aba-num">)[\d.]+(</div>\s*<div class="aba-title">Páginas de empresas)', rf"\g<1>{milhar(n_emp)}\2", html)
    nf = len(carregar("feeds/index.json").get("parlamentares") or [])
    if nf:
        html = re.sub(r'(<div class="aba-num">)\d+(</div>\s*<div class="aba-title">Siga um político)', rf"\g<1>{nf}\2", html)
    au = carregar("auditoria.json")
    if au.get("regras"):
        html = re.sub(r'(<div class="aba-num">)[^<]+(</div>\s*<div class="aba-title">Auditoria automática)', rf"\g<1>{len(au['regras'])} testes\2", html)
    stf = carregar("stf.json")
    n_stf = len((((stf.get("remuneracao") or {}).get("ultimoMes")) or {}).get("ministros") or [])
    if n_stf:
        html = re.sub(r'(<div class="aba-num">)[^<]+(</div>\s*<div class="aba-title">Supremo Tribunal Federal)', rf"\g<1>{n_stf} ministros\2", html)
    if status.get("ultimaAtualizacao"):
        a, m, d = status["ultimaAtualizacao"][:10].split("-")
        html = re.sub(r'(<time id="data-atualizacao">)[^<]*(</time>)', rf"\g<1>{d}/{m}/{a}\2", html)
    p.write_text(html, encoding="utf-8")
    print(f"✅ index.html — {milhar(n_total)} notas, {len(deps_est)} dep. estaduais, {ativos} magistrados")

    # ---------------- vereadores-campo-grande.html ----------------
    p = ROOT / "vereadores-campo-grande.html"
    if p.exists() and vereadores:
        html = p.read_text(encoding="utf-8")
        subsidio = (vereadores[0].get("salarioBase") or 26080.98)
        html = troca(html, r'(<div class="resumo-grid">\n).*?(\n    </div>)',
                     r"\g<1>" + resumo_grid([
                         (len(vereadores), "Vereadores"),
                         (brl(verba_cg), f"Verba indenizatória paga em {ANO}"),
                         (milhar(n_cg), "Notas fiscais coletadas"),
                         (brl(subsidio), "Subsídio mensal por vereador"),
                     ]).replace("\\", "\\\\") + r"\2", "vereadores: resumo")
        linhas = []
        for v in sorted(vereadores, key=lambda v: -((v.get("verbaIndenizatoria") or {}).get(f"gastoPago{ANO}") or 0)):
            vi = v.get("verbaIndenizatoria") or {}
            pago = vi.get(f"gastoPago{ANO}") or 0
            cota = vi.get(f"cotaAnual{ANO}") or 300000
            linhas.append([link_nome("vereador", v["nome"]), f"<td>{v.get('partido') or '—'}</td>",
                           f'<td class="num">{brl(pago)}</td>', f'<td class="num">{pago / cota * 100:.1f}%</td>',
                           f'<td class="num">{v.get("totalNotasFiscais") or 0}</td>'])
        html = troca(html, r"(<tbody>\n).*?(\n      </tbody>)", r"\g<1>" + tabela(linhas).replace("\\", "\\\\") + r"\2", "vereadores: tabela")
        p.write_text(html, encoding="utf-8")
        print("✅ vereadores-campo-grande.html")

    # ---------------- deputados-estaduais-ms.html ----------------
    p = ROOT / "deputados-estaduais-ms.html"
    if p.exists() and deps_est:
        html = p.read_text(encoding="utf-8")
        html = re.sub(r"\b\d+ deputados estaduais", f"{len(deps_est)} deputados estaduais", html)
        html = re.sub(r"Jan–\w{3}/\d{4}", periodo, html)
        html = re.sub(r"período de Jan a \w{3}/\d{4}", f"período de Jan a {mes_fim}/{ANO}", html)
        subsidio = next((d.get("salarioBase") for d in deps_est if d.get("salarioBase")), 34774.64)
        html = troca(html, r'(<div class="resumo-grid">\n).*?(\n    </div>)',
                     r"\g<1>" + resumo_grid([
                         (len(deps_est), "Deputados estaduais"),
                         (brl(ceap_est), f"CEAP paga em {periodo}"),
                         (milhar(n_est), "Notas fiscais coletadas"),
                         (brl(subsidio), "Subsídio mensal por deputado"),
                     ]).replace("\\", "\\\\") + r"\2", "dep. estaduais: resumo")
        linhas = [[link_nome("estadual", d["nome"]), f"<td>{d.get('partido') or '—'}</td>",
                   f'<td class="num">{len(d.get("despesas") or [])}</td>']
                  for d in sorted(deps_est, key=lambda d: -len(d.get("despesas") or []))]
        html = troca(html, r"(<tbody>\n).*?(\n      </tbody>)", r"\g<1>" + tabela(linhas).replace("\\", "\\\\") + r"\2", "dep. estaduais: tabela")
        p.write_text(html, encoding="utf-8")
        print("✅ deputados-estaduais-ms.html")

    # ---------------- senadores-ms.html ----------------
    p = ROOT / "senadores-ms.html"
    if p.exists() and senadores:
        html = p.read_text(encoding="utf-8")
        html = troca(html, r'(<div class="resumo-grid">\n).*?(\n    </div>)',
                     r"\g<1>" + resumo_grid([
                         (len(senadores), "Senadores de MS"),
                         (len(senbr.get("senadores") or []) or 81, "Senadores no Brasil"),
                         (brl(sum(s.get("cotaGastaAno") or 0 for s in senadores)), f"CEAPS gasta em {ANO} (MS)"),
                         (milhar(n_sen), "Notas fiscais coletadas"),
                     ]).replace("\\", "\\\\") + r"\2", "senadores: resumo")
        linhas = [[link_nome("senador", s["nome"]), f"<td>{s.get('partido') or '—'}</td>",
                   f'<td class="num">{brl(s.get("cotaGastaAno") or 0)}</td>',
                   f'<td class="num">{len(s.get("notasCeaps") or [])}</td>']
                  for s in sorted(senadores, key=lambda s: -(s.get("cotaGastaAno") or 0))]
        html = troca(html, r"(<tbody>\n).*?(\n      </tbody>)", r"\g<1>" + tabela(linhas).replace("\\", "\\\\") + r"\2", "senadores: tabela")
        p.write_text(html, encoding="utf-8")
        print("✅ senadores-ms.html")


def resumo_capa():
    """dados/resumo_capa.json — os poucos números da contracapa (aba Sobre), para ela abrir sem baixar os arquivos grandes."""
    cg, est, fed, sen = (carregar(n) for n in ("camara_municipal.json", "deputados_estaduais_ms.json", "deputados_federais_ms.json", "senadores_ms.json"))
    vi = lambda v: v.get("verbaIndenizatoria") or {}
    cotas = (sum(vi(v).get(f"gastoPago{ANO}") or 0 for v in cg.get("vereadores", []))
             + sum(vi(d).get(f"gastoPago{ANO}") or 0 for d in est.get("vereadores", []))
             + sum(d.get("cotaGastaAno") or 0 for d in fed.get("deputados", []))
             + sum(x.get("cotaGastaAno") or 0 for x in sen.get("senadores", [])))
    gov, pref, em = carregar("governo_ms.json"), carregar("prefeitura.json"), carregar("emendas_municipios.json")
    au, ss, gc = carregar("auditoria.json"), carregar("supersalarios.json"), carregar("governo_ms_contratos.json")
    gov_pago = ((gov.get("totais") or {}).get("pago") or 0) if gov.get("ano") == ANO else 0
    pref_pago = pref.get("totalDespesas") or sum(x.get("valor") or 0 for x in pref.get("despesas", []))
    tipos = {}
    for m in em.get("municipios", []):
        for t in m.get("tipos", []):
            tipos[t["tipo"]] = tipos.get(t["tipo"], 0) + t["valor"]
    n_parl = len(cg.get("vereadores", [])) + len(est.get("vereadores", [])) + len(fed.get("deputados", [])) + len(sen.get("senadores", []))
    n_notas = (sum(len(v.get("despesas") or []) for v in cg.get("vereadores", [])) + sum(len(d.get("despesas") or []) for d in est.get("vereadores", []))
               + sum(len(d.get("despesas") or []) for d in fed.get("deputados", [])) + sum(len(x.get("notasCeaps") or []) for x in sen.get("senadores", [])))
    out = {"ano": ANO, "atualizado": date.today().isoformat(),
           "dinheiro": [{"nome": "Governo do Estado de MS", "valor": round(gov_pago, 2), "aba": "governo-ms"},
                        {"nome": "Prefeitura de Campo Grande", "valor": round(pref_pago, 2), "aba": "prefeitura"},
                        {"nome": "Emendas parlamentares pagas em MS", "valor": round(em.get("totalMS") or 0, 2), "aba": "emendas"},
                        {"nome": "Cotas e verbas dos parlamentares de MS", "valor": round(cotas, 2), "aba": "deputados"}],
           "governoCredores": [{"nome": n, "valor": round(v or 0, 2)} for n, v in (
               ("Repasses a municípios, órgãos e previdência", (gov.get("credoresPorTipo") or {}).get("publico")),
               ("Fornecedores e prestadores de serviço", (gov.get("credoresPorTipo") or {}).get("fornecedor")),
               ("Folha, aposentadorias e pensões", (gov.get("credoresPorTipo") or {}).get("folha")),
               ("Bancos e dívida", (gov.get("credoresPorTipo") or {}).get("financeiro"))) if v],
           "emendasTipos": [{"nome": n, "valor": round(v, 2)} for n, v in sorted(tipos.items(), key=lambda kv: -kv[1]) if v],
           "kpis": {"parlamentares": n_parl, "notas": n_notas, "empresas": len(carregar("empresas_index.json") or {}),
                    "sinais": len(au.get("sinais") or []), "sinaisFortes": sum(1 for x in au.get("sinais") or [] if x.get("nivel") == "forte"),
                    "acimaTeto": ss.get("liquidoAcimaTeto"), "contratosEstado": len(gc.get("contratos") or []),
                    "fontes": len((carregar("status_fontes.json").get("fontes") or carregar("status_fontes.json")))}}
    (DADOS / "resumo_capa.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print("✅ resumo_capa.json")


if __name__ == "__main__":
    main()
    resumo_capa()
    atualizar_kit_imprensa(carregar("camara_municipal.json"), carregar("deputados_estaduais_ms.json"),
                           carregar("deputados_federais_ms.json"), carregar("senadores_ms.json"),
                           carregar("prefeitura.json"), carregar("emendas_ms.json"),
                           [carregar(f) for f in ("trt24_magistrados.json", "tre_ms_magistrados.json", "tjms_magistrados.json")],
                           carregar("status.json"), carregar("conexoes_fornecedores.json").get("totalEmpresas"),
                           len(list((DADOS / "camaras").glob("*.json"))))
