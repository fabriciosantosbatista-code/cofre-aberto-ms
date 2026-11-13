#!/usr/bin/env python3
"""
Cofre Aberto MS — páginas estáticas por tema e de perguntas frequentes (para o Google)

O painel (cofre-aberto-ms.html) é uma página só, com abas; o que fica dentro das
abas quase não aparece nas buscas. Este script gera páginas próprias, com título
no formato em que as pessoas pesquisam e números atualizados a cada coleta:

  temas      /governo-ms/, /prefeitura-campo-grande/, /supersalarios-ms/,
             /auditoria/, /emendas-parlamentares-ms/, /cartao-corporativo-presidente/,
             /salario-ministros-stf/
  perguntas  /perguntas/<pergunta>/ (quanto ganha o governador, um vereador de CG,
             um deputado..., o que é a cota parlamentar, Emendas Pix, teto) com
             marcação FAQPage, e o índice /perguntas/

Tudo vem dos arquivos de dados/ já coletados. Acrescenta as URLs ao sitemap.xml.
"""

import json, re, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from gerar_paginas_parlamentares import (ANO, DADOS, HOJE, ROOT, RODAPE, SITE, brl, cabecalho, compacto, data_br, e,  # noqa: E402
                                         escreve_se_mudou, milhar)
from gerar_paginas_municipios import CSS_EXTRA, barras, tabela  # noqa: E402

CSS_TEMA = CSS_EXTRA + """
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:10px;margin:14px 0 18px}
.kpi{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:12px 14px}
.kpi b{display:block;font-family:"Sora",sans-serif;font-size:1.25rem;color:var(--ink)}.kpi span{font-size:.76rem;color:var(--ink-soft)}
.resposta{font-size:1.02rem;line-height:1.7;background:var(--surface);border:1px solid var(--border);border-left:3px solid #f5c842;border-radius:10px;padding:14px 16px;margin:12px 0 18px}
.relacionadas{columns:2 260px;font-size:.9rem;line-height:2}.relacionadas a{color:var(--ink)}
.btn-painel{display:inline-block;margin:6px 0 4px;padding:9px 16px;border-radius:999px;background:#f5c842;color:#14120a;font-weight:600;text-decoration:none;font-size:.86rem}
"""
TEMAS, PERGUNTAS = [], []  # (url, título curto) para o sitemap e os links entre as páginas


def carregar(nome):
    try:
        return json.load(open(DADOS / nome, encoding="utf-8"))
    except Exception:
        return {}


def barras_n(itens):
    """barras com contagem (não valor em reais)"""
    mx = max((v for _, v in itens), default=0) or 1
    return "<div class='barras'>" + "".join(
        f"<div class='barra'><span>{e(n)}</span><div class='t'><div class='f' style='width:{v / mx * 100:.1f}%'></div></div>"
        f"<span class='v'>{milhar(v)}</span></div>" for n, v in itens) + "</div>"


def url_parl(grupo, nome):
    return (carregar("paginas_index.json") or {}).get(f"{grupo}|{nome}")


def kpis(itens):
    return "<div class='kpis'>" + "".join(f"<div class='kpi'><b>{v}</b><span>{e(r)}</span></div>" for v, r in itens) + "</div>"


def painel(aba, texto="Ver tudo no painel"):
    return f"<a class='btn-painel' href='/cofre-aberto-ms.html#aba={aba}'>{e(texto)} →</a>"


def links_relacionados(atual):
    itens = [(u, t) for u, t in TEMAS + PERGUNTAS if u != atual]
    return "<h2>Veja também</h2><div class='relacionadas'>" + "".join(f"<div><a href='{u}'>{e(t)}</a></div>" for u, t in itens) + "</div>"


def pagina(url, titulo, descricao, h1, corpo, jsonld=None, migalha=None):
    ld = jsonld or {"@context": "https://schema.org", "@type": "WebPage", "name": h1, "url": SITE + url,
                    "dateModified": HOJE.isoformat(), "inLanguage": "pt-BR"}
    trilha = f"<a href='/'>Início</a> / {migalha + ' / ' if migalha else ''}{e(h1)}"
    html = cabecalho(titulo, descricao, url, None, ld, tipo="article").replace("</style>", CSS_TEMA + "</style>", 1)
    html += f"""<p class="breadcrumb">{trilha}</p>
<article><h1>{e(h1)}</h1>
<p class="cargo" style="margin-bottom:6px">Atualizado em {data_br(HOJE.isoformat())} com dados de fontes oficiais.</p>
{corpo}
{{RELACIONADAS}}
</article>""" + RODAPE
    return html


def faq_ld(url, perguntas):
    return {"@context": "https://schema.org", "@type": "FAQPage", "url": SITE + url, "dateModified": HOJE.isoformat(),
            "mainEntity": [{"@type": "Question", "name": p, "acceptedAnswer": {"@type": "Answer", "text": r}} for p, r in perguntas]}


def link_empresa(nome, url):
    return f"<a href='{url}'>{e(nome)}</a>" if url else e(nome)


# ---------------------------------------------------------------- temas
def tema_governo():
    g, gc = carregar("governo_ms.json"), carregar("governo_ms_contratos.json")
    if not g.get("totais"):
        return None
    t, ano = g["totais"], g.get("ano", ANO)
    pe = (g.get("primeiroEscalao") or {}).get("pessoas") or []
    gov = next((p for p in pe if p["cargo"] == "GOVERNADOR"), None)
    forn = sorted((c for c in g.get("credores", []) if c.get("tipo") == "fornecedor"), key=lambda c: -(c.get("pago") or 0))[:15]
    corpo = kpis([(compacto(t["pago"]), f"pagos pelo Governo de MS em {ano}"), (compacto(t["empenhado"]), "empenhados (comprometidos)"),
                  (milhar(g.get("totalCredores") or len(g.get("credores", []))), "credores que receberam"),
                  (milhar(len(gc.get("contratos") or [])), f"contratos celebrados em {gc.get('ano', ANO)}")])
    corpo += (f"<p>Em {ano}, o Governo do Estado de Mato Grosso do Sul pagou <strong>{brl(t['pago'])}</strong>, segundo o Portal da Transparência do Estado. "
              f"A maior parte vai para previdência, educação, saúde e segurança; abaixo, os órgãos que mais pagaram e as empresas que mais receberam.</p>")
    corpo += "<h2>Órgãos que mais pagaram</h2>" + barras([(o["orgao"].title(), o.get("pago") or 0) for o in g.get("orgaos", [])[:12]])
    corpo += "<h2>Empresas e fornecedores que mais receberam</h2>" + tabela(["Fornecedor", "CNPJ", "#Pago no ano"], [
        f"<tr><td>{e(c['credor'])}</td><td>{e(c.get('cnpj') or '')}</td><td class='num'>{brl(c.get('pago'))}</td></tr>" for c in forn])
    if gc.get("contratos"):
        corpo += f"<h2>Maiores contratos celebrados em {gc.get('ano', ANO)}</h2>" + tabela(["Contrato", "Órgão", "#Valor"], [
            f"<tr><td>{e(c['fornecedor'])}<br><small>nº {e(c.get('numero') or '')} · {e(c.get('modalidade') or '')}</small></td><td>{e(c.get('orgao') or '')}</td>"
            f"<td class='num'>{brl(c['valor'])}</td></tr>" for c in gc["contratos"][:12]])
    if gov:
        corpo += (f"<h2>Salário do governador e do secretariado</h2><p>O governador {e(gov['nome'].title())} recebeu <strong>{brl(gov['bruto'])}</strong> brutos "
                  f"({brl(gov['liquido'])} líquidos) em {e(g['primeiroEscalao'].get('competencia', ''))}. "
                  f"<a href='/perguntas/quanto-ganha-o-governador-de-ms/'>Veja quanto ganham o governador, o vice e os secretários →</a></p>")
    corpo += "<p>" + painel("governo-ms", "Despesas, contratos, obras e licitações do Governo no painel") + "</p>"
    corpo += f"<p class='aviso'>Fonte: Portal da Transparência do Estado de MS ({e(g.get('fonte') or 'transparencia.ms.gov.br')}).</p>"
    return ("/governo-ms/", f"Gastos do Governo de MS em {ano}: órgãos, empresas e contratos | Cofre Aberto MS",
            f"Quanto o Governo de Mato Grosso do Sul pagou em {ano} ({compacto(t['pago'])}), quais órgãos mais gastaram, as empresas que mais receberam e os maiores contratos.",
            f"Gastos do Governo de MS em {ano}", corpo)


def tema_prefeitura():
    p, pc = carregar("prefeitura.json"), carregar("prefeitura_contratos.json")
    if not p.get("totalDespesas"):
        return None
    ano = p.get("ano", ANO)
    secs = sorted((p.get("porSecretaria") or {}).items(), key=lambda kv: -kv[1])[:12]
    corpo = kpis([(compacto(p["totalDespesas"]), f"pagos pela Prefeitura em {ano}"), (milhar(p.get("totalNotasFiscais") or 0), "empenhos com fornecedor"),
                  (milhar(len(pc.get("contratos") or [])), "contratos no portal"), (milhar(len(pc.get("licitacoes") or [])), "licitações")])
    ult = p.get("ultimoEmpenho")
    corpo += (f"<p>A Prefeitura de Campo Grande pagou <strong>{brl(p['totalDespesas'])}</strong> em {ano}, segundo o SIG-Transparência do município."
              + (f" O empenho mais recente publicado é de <strong>{data_br(ult)}</strong> — a Prefeitura publica com atraso." if ult else "") + "</p>")
    corpo += "<h2>Secretarias que mais gastaram</h2>" + barras([(n, v) for n, v in secs])
    if pc.get("fornecedores"):
        corpo += "<h2>Empresas com mais contratos</h2>" + tabela(["Empresa", "#Contratos", "#Valor dos contratos"], [
            f"<tr><td>{e(f['nome'])}</td><td class='num'>{f.get('contratos')}</td><td class='num'>{brl(f.get('valorContratos'))}</td></tr>"
            for f in sorted(pc["fornecedores"], key=lambda f: -(f.get("valorContratos") or 0))[:15]])
    ct = [c for c in pc.get("contratos", []) if str(c.get("compra")) in ("True", "true") or c.get("compra") is True]
    if ct:
        corpo += "<h2>Maiores contratos de compras e serviços</h2>" + tabela(["Contrato", "Início", "#Valor"], [
            f"<tr><td>{e(c['fornecedor'])}<br><small>{e((c.get('objeto') or '')[:140])}</small></td><td>{data_br(c.get('inicio'))}</td><td class='num'>{brl(c['valor'])}</td></tr>"
            for c in sorted(ct, key=lambda c: -float(c['valor'] or 0))[:12]])
    corpo += "<p>" + painel("prefeitura", "Empenhos, fornecedores e secretarias no painel") + " " + painel("contratos-cg", "Contratos, licitações e aditivos") + "</p>"
    return ("/prefeitura-campo-grande/", f"Gastos e contratos da Prefeitura de Campo Grande {ano} | Cofre Aberto MS",
            f"Quanto a Prefeitura de Campo Grande gastou em {ano} ({compacto(p['totalDespesas'])}), por secretaria, as empresas com mais contratos e os maiores contratos.",
            f"Gastos e contratos da Prefeitura de Campo Grande em {ano}", corpo)


def tema_supersalarios():
    ss = carregar("supersalarios.json")
    if not ss.get("teto"):
        return None
    rk = sorted(ss.get("ranking") or [], key=lambda p: -(p.get("liquido") or 0))[:25]
    corpo = kpis([(brl(ss["teto"]), "teto constitucional (subsídio do STF)"), (milhar(ss.get("liquidoAcimaTeto") or 0), "pessoas com líquido acima do teto"),
                  (milhar(ss.get("acimaTeto") or 0), "com bruto acima do teto"), (milhar(ss.get("totalPessoas") or 0), "contracheques analisados")])
    corpo += ("<p>O teto do funcionalismo é o subsídio de ministro do STF. Mesmo assim, verbas indenizatórias e outros "
              "\"penduricalhos\" fazem muita gente receber mais. Abaixo, os maiores contracheques líquidos do último mês publicado em MS.</p>")
    corpo += "<h2>Maiores contracheques líquidos</h2>" + tabela(["Nome", "Cargo e órgão", "#Líquido"], [
        f"<tr><td>{e(p['nome'])}</td><td>{e(p.get('cargo') or '')}<br><small>{e(p.get('orgao') or '')} · {e(p.get('mes') or '')}</small></td>"
        f"<td class='num'>{brl(p.get('liquido'))}</td></tr>" for p in rk])
    corpo += "<h2>Por órgão</h2>" + tabela(["Órgão", "#Pessoas", "#Líquido acima do teto", "#Maior líquido"], [
        f"<tr><td>{e(o['orgao'])}<br><small>{e(o.get('mes') or '')}</small></td><td class='num'>{milhar(o.get('pessoas') or 0)}</td>"
        f"<td class='num'>{milhar(o.get('liquidoAcimaTeto') or 0)}</td><td class='num'>{brl(o.get('maiorLiquido'))}</td></tr>" for o in ss.get("orgaos", [])])
    corpo += "<p>" + painel("supersalarios", "Ranking completo e cada penduricalho no painel") + "</p>"
    corpo += "<p class='aviso'>Valores do próprio contracheque publicado pelos órgãos. Receber acima do teto pode ter base legal (verbas indenizatórias, atrasados) — o site mostra os números, não acusa ninguém.</p>"
    return ("/supersalarios-ms/", f"Supersalários em MS {ANO}: quem recebe acima do teto | Cofre Aberto MS",
            f"{milhar(ss.get('liquidoAcimaTeto') or 0)} pessoas receberam líquido acima do teto de {brl(ss['teto'])} em MS: nomes, cargos, órgãos e penduricalhos.",
            f"Supersalários em MS: quem recebe acima do teto", corpo)


def tema_auditoria():
    au = carregar("auditoria.json")
    if not au.get("sinais"):
        return None
    regras, res = au.get("regras") or {}, au.get("resumo") or {}
    fortes = [s for s in au["sinais"] if s.get("nivel") == "forte"][:30]
    corpo = kpis([(milhar(len(au["sinais"])), "sinais de atenção"), (milhar(sum(1 for s in au["sinais"] if s.get("nivel") == "forte")), "de nível forte"),
                  (milhar(au.get("empresasConsultadas") or 0), "empresas checadas na Receita"), (milhar(len(regras)), "testes automáticos")])
    corpo += ("<p>A Auditoria cruza notas fiscais, contratos e pagamentos com a Receita Federal, o TSE, a folha do Estado e as sanções da CGU, "
              "e aponta padrões atípicos. <strong>Sinal de atenção não é acusação</strong> — muitos têm explicação legal.</p>")
    corpo += "<h2>Sinais por teste</h2>" + barras_n([(regras.get(k, k), v) for k, v in sorted(res.items(), key=lambda kv: -kv[1]) if v])
    corpo += "<h2>Sinais de nível forte</h2>" + "".join(
        f"<div class='dest'><b>{link_empresa(s['titulo'], s.get('paginaEmpresa'))}</b><small>{e(s.get('rotulo') or '')} · {e((s.get('descricao') or '')[:220])}</small></div>"
        for s in fortes)
    corpo += "<p>" + painel("auditoria", "Todos os sinais, com evidências, no painel") + " <a href='/metodologia.html'>Como os testes funcionam</a></p>"
    return ("/auditoria/", "Auditoria automática dos gastos públicos de MS: sinais de atenção | Cofre Aberto MS",
            f"{milhar(len(au['sinais']))} sinais de atenção em empresas que recebem dinheiro público em MS: sócio servidor, empresa punida, doador de campanha, aditivos acima do limite.",
            "Auditoria automática: sinais de atenção nos gastos públicos de MS", corpo)


def tema_emendas():
    em = carregar("emendas_municipios.json")
    if not em.get("totalMS"):
        return None
    ano = em.get("ano", ANO)
    aut = sorted(em.get("autores") or [], key=lambda a: -(a.get("totalMS") or 0))[:20]
    mun = sorted(em.get("municipios") or [], key=lambda m: -(m.get("total") or 0))[:15]
    mi = carregar("municipios_index.json") or {}
    pix = ((em.get("pix") or {}).get("anos") or {}).get(str(ano)) or 0
    corpo = kpis([(compacto(em["totalMS"]), f"em emendas pagas em MS em {ano}"), (compacto(pix), f"em Emendas Pix em {ano}"),
                  (milhar(em.get("totalMunicipios") or 0), "municípios que receberam"), (milhar(em.get("pagamentos") or 0), "pagamentos")])
    corpo += "<h2>Parlamentares que mais destinaram emendas a MS</h2>" + barras([(f"{a['autor']} ({a.get('cargo') or ''})", a.get("totalMS") or 0) for a in aut])
    if mun:
        corpo += "<h2>Municípios que mais receberam</h2>" + tabela(["Município", "#Emendas pagas"], [
            f"<tr><td>{link_empresa(m['municipio'], mi.get(m['municipio']))}</td><td class='num'>{brl(m.get('total'))}</td></tr>"
            for m in mun if m.get("municipio")])
    corpo += "<p><a class='btn-painel' href='/municipio/'>Ver as emendas de cada município →</a> " + painel("emendas", "Emendas no painel") + "</p>"
    return ("/emendas-parlamentares-ms/", f"Emendas parlamentares em MS {ano}: quem mandou e quem recebeu | Cofre Aberto MS",
            f"{compacto(em['totalMS'])} em emendas parlamentares pagas em MS em {ano}: quais deputados e senadores destinaram, os municípios que mais receberam e as Emendas Pix.",
            f"Emendas parlamentares em MS em {ano}", corpo)


def tema_presidencia():
    pr = carregar("presidencia.json")
    pp = (pr.get("cartao") or {}).get("porPresidente") or []
    if not pp:
        return None
    at = pp[-1]
    corpo = kpis([(compacto(at["total"]), f"no cartão corporativo de {at['presidente'].split()[0]} ({at['meses']} meses)"),
                  (compacto(at["mediaMensal"]), "média por mês"), (f"{at['sigiloso'] / at['total'] * 100:.0f}%".replace(".", ","), "dos gastos são sigilosos")])
    corpo += "<h2>Cartão corporativo da Presidência por presidente</h2>" + tabela(["Presidente", "Período", "#Total", "#Média mensal", "#Sigiloso"], [
        f"<tr><td>{e(p['presidente'])}</td><td>{p['de'][5:]}/{p['de'][:4]} a {p['ate'][5:]}/{p['ate'][:4]}</td><td class='num'>{brl(p['total'])}</td>"
        f"<td class='num'>{brl(p['mediaMensal'])}</td><td class='num'>{brl(p['sigiloso'])}</td></tr>" for p in pp])
    corpo += "<p>Os valores incluem as despesas da Secretaria de Administração (residências e viagens do presidente), da ABIN e do GSI pagas com o cartão de pagamento do governo federal.</p>"
    corpo += "<p>" + painel("presidencia", "Cartão, viagens, ministros e orçamento no painel") + "</p>"
    return ("/cartao-corporativo-presidente/", "Cartão corporativo do presidente: quanto cada um gastou desde 2013 | Cofre Aberto MS",
            f"Quanto a Presidência gastou no cartão corporativo com cada presidente desde 2013. {at['presidente']}: {compacto(at['total'])} em {at['meses']} meses.",
            "Cartão corporativo do presidente: quanto cada um gastou", corpo)


def tema_stf():
    st = carregar("stf.json")
    u = ((st.get("remuneracao") or {}).get("ultimoMes")) or {}
    if not u.get("ministros"):
        return None
    mes = f"{u['mes'][5:]}/{u['mes'][:4]}"
    corpo = kpis([(brl(st.get("subsidio")), "subsídio de ministro do STF (teto)"), (milhar(len(u["ministros"])), f"ministros no contracheque de {mes}"),
                  (brl(max(m['base'] + m['outras'] for m in u['ministros'])), f"maior bruto em {mes}")])
    corpo += f"<h2>Contracheque de cada ministro em {mes}</h2>" + tabela(["Ministro(a)", "#Subsídio e vantagens", "#Outras verbas", "#Líquido"], [
        f"<tr><td>{e(m['nome'])}</td><td class='num'>{brl(m['base'])}</td><td class='num'>{brl(m['outras'])}</td><td class='num'>{brl(m['liquido'])}</td></tr>"
        for m in u["ministros"]])
    corpo += "<p>" + painel("stf", "Série mês a mês e despesa com pessoal no painel") + "</p>"
    return ("/salario-ministros-stf/", f"Quanto ganham os ministros do STF: contracheque de {mes} | Cofre Aberto MS",
            f"Salário dos ministros do Supremo: subsídio de {brl(st.get('subsidio'))} e o contracheque de cada um em {mes}, com outras verbas e líquido.",
            "Quanto ganham os ministros do STF", corpo)


# ---------------------------------------------------------------- termômetro da transparência
def _fim_mes(mm_aaaa):
    """'09/2026' ou '2026-09' → último dia do mês (date)"""
    import calendar
    from datetime import date
    m = re.match(r"(\d{2})/(\d{4})$", mm_aaaa or "") or re.match(r"(\d{4})-(\d{2})$", mm_aaaa or "")
    if not m:
        return None
    a, mes = (int(m[2]), int(m[1])) if "/" in mm_aaaa else (int(m[1]), int(m[2]))
    return date(a, mes, calendar.monthrange(a, mes)[1])


def termometro():
    """Quanto tempo cada órgão leva para publicar: dias desde o dado mais recente publicado x prazo esperado."""
    from datetime import date
    hoje = HOJE if isinstance(HOJE, date) else date.today()
    MES = {"jan": "01", "fev": "02", "mar": "03", "abr": "04", "mai": "05", "jun": "06", "jul": "07", "ago": "08", "set": "09", "out": "10", "nov": "11", "dez": "12"}
    linhas = []

    def add(orgao, dado, ultimo, prazo, base, obs=""):
        if ultimo is None:
            linhas.append({"orgao": orgao, "dado": dado, "ultimo": None, "dias": None, "prazo": prazo, "base": base, "nivel": "fora", "obs": obs})
            return
        dias = (hoje - ultimo).days
        nivel = "ok" if dias <= prazo else ("atencao" if dias <= 2 * prazo else "ruim")
        linhas.append({"orgao": orgao, "dado": dado, "ultimo": ultimo.isoformat(), "dias": dias, "prazo": prazo, "base": base, "nivel": nivel, "obs": obs})

    iso = lambda t: date.fromisoformat(t[:10]) if t and re.match(r"\d{4}-\d{2}-\d{2}", t) else None
    maxdata = lambda notas: max((iso(n.get("data")) for n in notas if iso(n.get("data"))), default=None)
    rt = "LC 131/2009: despesas em tempo real (até o 1º dia útil seguinte)"
    mensal = "dado mensal: até 45 dias depois do fim do mês"
    p = carregar("prefeitura.json")
    add("Prefeitura de Campo Grande", "despesas (empenhos)", iso(p.get("ultimoEmpenho")), 3, rt)
    g = carregar("governo_ms.json")
    add("Governo do Estado de MS", "despesas", iso(g.get("ultimaAtualizacao")), 3, rt)
    cg = carregar("camara_municipal.json")
    meses = [MES[m] for v in cg.get("vereadores", []) for a in ("mesesAto027", "mesesAto028") for m in ((v.get("verbaIndenizatoria") or {}).get(a) or {}) if m in MES]
    add("Câmara Municipal de Campo Grande", "verba indenizatória dos vereadores", _fim_mes(f"{max(meses)}/{ANO}") if meses else None, 45, mensal)
    est = carregar("deputados_estaduais_ms.json")
    add("Assembleia Legislativa (ALEMS)", "notas da verba indenizatória", maxdata([n for d in est.get("vereadores", []) for n in d.get("despesas") or []]), 45, mensal)
    fed = carregar("deputados_federais_ms.json")
    add("Câmara dos Deputados", "notas da cota parlamentar (CEAP)", maxdata([n for d in fed.get("deputados", []) for n in d.get("despesas") or []]), 45,
        "a Câmara aceita notas até 90 dias depois da despesa", "o atraso aqui é dos deputados, que apresentam as notas depois")
    sen = carregar("senadores_ms.json")
    add("Senado Federal", "notas da cota parlamentar (CEAPS)", maxdata([n for x in sen.get("senadores", []) for n in x.get("notasCeaps") or []]), 45,
        "o Senado aceita notas até 90 dias depois da despesa", "o atraso aqui é dos senadores, que apresentam as notas depois")
    # folhas: a data do próprio portal do órgão quando o site lê de lá (TRT24, TRE-MS); o resto vem da folha dos supersalários
    proprios = {"TRT24": ("TRT24 — Justiça do Trabalho", "trt24_magistrados.json"), "TRE": ("TRE-MS — Justiça Eleitoral", "tre_ms_magistrados.json")}
    for sigla, (nome, arq) in proprios.items():
        m_ = carregar(arq)
        if m_.get("mesReferencia"):
            add(nome, "folha dos magistrados", _fim_mes(m_["mesReferencia"]), 45, mensal)
    for o in carregar("supersalarios.json").get("orgaos", []):
        if o["orgao"].startswith(tuple(proprios)):
            continue
        via = "lida via DadosJusBr, que pode ter atraso próprio" if "DadosJusBr" in (o.get("fonte") or "") else ""
        add(o["orgao"].replace(" (60 maiores)", ""), "folha de pagamento", _fim_mes(o.get("mes")), 45, mensal, via)
    pr = carregar("presidencia.json")
    ser = (pr.get("cartao") or {}).get("serie") or []
    if ser:
        add("Presidência da República (CGU)", "cartão corporativo", _fim_mes(ser[-1]["mes"]), 45, mensal,
            "a CGU publica o cartão com cerca de um mês de atraso")
    import glob
    for f in sorted(glob.glob(str(DADOS / "camaras" / "*.json"))):
        c = json.load(open(f, encoding="utf-8"))
        nome = f"Câmara Municipal de {c.get('cidade')}"
        col = iso(c.get("ultimaAtualizacao"))
        if not c.get("temDadosFinanceiros"):
            linhas.append({"orgao": nome, "dado": "despesas e diárias", "ultimo": None, "dias": None, "prazo": 3, "base": rt, "nivel": "fora",
                           "obs": "o portal não publica dados financeiros em formato aberto"})
        elif col and (hoje - col).days > 7:
            linhas.append({"orgao": nome, "dado": "despesas e diárias", "ultimo": col.isoformat(), "dias": (hoje - col).days, "prazo": 3, "base": rt,
                           "nivel": "fora", "obs": f"o portal não responde desde {data_br(col.isoformat())}"})
        else:
            linhas.append({"orgao": nome, "dado": "despesas e diárias", "ultimo": col.isoformat() if col else None, "dias": 0, "prazo": 3, "base": rt,
                           "nivel": "ok", "obs": "portal no ar e atualizado"})
    ordem = {"fora": 0, "ruim": 1, "atencao": 2, "ok": 3}
    linhas.sort(key=lambda x: (ordem[x["nivel"]], -(x["dias"] or 0)))
    escreve_se_mudou(DADOS / "termometro.json", json.dumps({"geradoEm": HOJE.isoformat(), "orgaos": linhas}, ensure_ascii=False, indent=1))
    return linhas


def tema_termometro():
    ls = termometro()
    if not ls:
        return None
    rot = {"ok": ("🟢", "Em dia"), "atencao": ("🟡", "Atrasado"), "ruim": ("🔴", "Muito atrasado"), "fora": ("⚫", "Fora do ar ou não publica")}
    cont = {k: sum(1 for x in ls if x["nivel"] == k) for k in rot}
    obs = lambda x: f"<br><small>{e(x['obs'])}</small>" if x.get("obs") else ""
    corpo = kpis([(f"{rot[k][0]} {cont[k]}", rot[k][1]) for k in ("ok", "atencao", "ruim", "fora")])
    corpo += ("<p>Quanto tempo cada órgão leva para publicar seus gastos. A lei exige que as despesas sejam publicadas <strong>em tempo real</strong> "
              "(Lei Complementar 131/2009: até o primeiro dia útil seguinte); folhas de pagamento e notas de verba são mensais. "
              "O termômetro mostra há quantos dias está o dado mais recente que cada órgão publicou, medido pela coleta automática do site.</p>")
    corpo += tabela(["Órgão", "O que publica", "Último dado", "#Dias", "Situação"], [
        f"<tr><td><b>{e(x['orgao'])}</b>{obs(x)}</td><td>{e(x['dado'])}<br><small>{e(x['base'])}</small></td>"
        f"<td>{data_br(x['ultimo']) if x['ultimo'] else '—'}</td><td class='num'>{x['dias'] if x['dias'] is not None else '—'}</td>"
        f"<td>{rot[x['nivel']][0]} {rot[x['nivel']][1]}</td></tr>" for x in ls])
    corpo += ("<p class='aviso'>🟢 dentro do prazo · 🟡 até o dobro do prazo · 🔴 mais que o dobro · ⚫ portal fora do ar ou sem dados abertos. "
              "Atraso de publicação é falta de transparência, não prova de irregularidade. Se um órgão publicou e o site não captou, "
              "<a href='/metodologia.html'>avise-nos</a>.</p>")
    return ("/termometro-da-transparencia/", f"Termômetro da transparência: quem publica os gastos em dia em MS | Cofre Aberto MS",
            f"Quanto tempo cada órgão de MS leva para publicar seus gastos: {cont['ok']} em dia, {cont['atencao'] + cont['ruim']} atrasados e {cont['fora']} fora do ar ou sem dados abertos.",
            "Termômetro da transparência", corpo)


COR_VOTO = {"SIM": "#2dd4a0", "NÃO": "#ff7a7a", "NAO": "#ff7a7a", "ABSTENÇÃO": "#f5c842", "OBSTRUÇÃO": "#f5c842", "VOTOU": "#8b95aa"}


def celula_voto(v):
    c = COR_VOTO.get((v or "").upper())
    return f"<td style='text-align:center;white-space:nowrap'>{f'<b style=color:{c}>{e(v)}</b>' if c else f'<small>{e(v or chr(8212))}</small>'}</td>"


def assunto(v):
    res = {1: "aprovado", 0: "rejeitado"}.get(v.get("aprovacao")) if v.get("aprovacao") is not None else (v.get("resultado") or "").lower()
    return (f"<b>{e(v.get('proposicao') or '')}</b> {e(v.get('ementa') or '')}"
            f"<br><small>{e(v.get('descricao') or '')}{' · ' + e(res) if res and res not in (v.get('descricao') or '').lower() else ''}</small>")


def quadro_votos(q, chave, grupo, idx, titulo):
    """Tabela: cada votação nominal (assunto) × voto de cada parlamentar de MS. As 20 mais recentes abertas, o resto em 'ver todas'."""
    quem, vs = q.get(chave) or {}, q.get("votacoes") or []
    if not quem or not vs:
        return ""
    ids = list(quem)
    cab = "".join(f"<th style='text-align:center'>{link_empresa(quem[i].split()[0] if len(quem[i].split()[0]) > 3 else ' '.join(quem[i].split()[:2]), idx.get(grupo + '|' + quem[i]))}</th>" for i in ids)
    lin = lambda v: f"<tr><td>{data_br(v.get('data'))}</td><td style='min-width:260px'>{assunto(v)}</td>{''.join(celula_voto(v['votos'].get(i)) for i in ids)}</tr>"
    tab = lambda linhas: f"<div class='tabela-wrap'><table><thead><tr><th>Data</th><th>Assunto e o que foi votado</th>{cab}</tr></thead><tbody>{linhas}</tbody></table></div>"
    html = f"<h2>{e(titulo)}</h2><p>{len(vs)} votações nominais, da mais recente para a mais antiga. — = não votou.</p>" + tab("".join(lin(v) for v in vs[:20]))
    if len(vs) > 20:
        html += f"<details><summary>Ver todas as {len(vs)} votações</summary>{tab(''.join(lin(v) for v in vs[20:]))}</details>"
    return html


def tema_votacoes():
    d = carregar("votacoes.json")
    ps = [x for x in d.get("parlamentares", []) if x.get("nominais")]
    if not ps:
        return None
    ano, idx = d.get("ano", ANO), carregar("paginas_index.json") or {}
    casa = {"federal": "Deputado(a) federal", "senador": "Senador(a)"}
    corpo = ("<p>Quantas votações nominais do plenário cada deputado federal e senador de MS votou em " + str(ano) + ". A votação nominal é "
             "aquela em que o voto de cada parlamentar fica registrado; as simbólicas não registram quem votou. No Senado, \"presente sem voto\" "
             "é quem estava no plenário mas não votou (por exemplo, presidindo a sessão), e ausências justificadas são licença, missão ou atividade parlamentar.</p>")
    for g, titulo in (("federal", "Deputados federais de MS — Câmara"), ("senador", "Senadores de MS — Senado")):
        gs = sorted((x for x in ps if x["grupo"] == g), key=lambda x: -(x["participacao"] or 0))
        if not gs:
            continue
        corpo += f"<h2>{titulo} ({gs[0]['nominais']} votações nominais em {ano})</h2>" + tabela(
            ["Parlamentar", "#Votou", "#Não votou", "#Participação"] + (["#Presente sem voto", "#Ausência justificada"] if g == "senador" else []), [
                f"<tr><td>{link_empresa(x['nome'], idx.get(g + '|' + x['nome']))}</td><td class='num'>{x['votou']}</td>"
                f"<td class='num'>{x['nominais'] - x['votou']}</td><td class='num'><b>{str(x['participacao']).replace('.', ',')}%</b></td>"
                + (f"<td class='num'>{x.get('presenteSemVoto') or 0}</td><td class='num'>{x.get('justificadas') or 0}</td>" if g == "senador" else "") + "</tr>"
                for x in gs])
    corpo += quadro_votos(d.get("quadroCamara") or {}, "deputados", "federal", idx, "Como votou cada deputado federal de MS")
    corpo += quadro_votos(d.get("quadroSenado") or {}, "senadores", "senador", idx, "Como votou cada senador de MS")
    corpo += "<p>Em cada página de parlamentar estão todas as votações dele, com o assunto e o voto.</p>"
    corpo += f"<p class='aviso'>Fonte: {e(d.get('fonte') or '')}. Atualizado a cada coleta.</p>"
    return ("/presenca-votacoes-parlamentares-ms/", f"Presença nas votações: deputados federais e senadores de MS {ano} | Cofre Aberto MS",
            f"Quantas votações nominais cada deputado federal e senador de MS votou em {ano}, com o voto de cada um nas últimas votações.",
            f"Presença nas votações: deputados federais e senadores de MS em {ano}", corpo)


def tema_apoie():
    corpo = """<div class="resposta">O Cofre Aberto MS é independente: não tem dono político, não vende anúncio e não cobra pelos dados.
Ele funciona com o trabalho de quem acredita que o dinheiro público tem de ser visível para todos. Se o site é útil para você, ajude a mantê-lo.</div>
<h2>Faça um Pix</h2>
<style>.pix-valores{display:flex;flex-wrap:wrap;gap:8px;margin:8px 0 14px}.pix-valores button{background:var(--surface-2);color:var(--ink);border:1px solid var(--border);border-radius:999px;padding:8px 16px;font:600 .9rem Inter,sans-serif;cursor:pointer}
.pix-valores button.ativo{background:#f5c842;color:#14120a;border-color:#f5c842}.pix-corpo{display:flex;flex-wrap:wrap;gap:20px;align-items:flex-start}
#pix-qr{background:#fff;padding:10px;border-radius:12px;line-height:0}.pix-txt{flex:1;min-width:240px}
#pix-codigo{width:100%;box-sizing:border-box;background:var(--surface-2);color:var(--ink);border:1px solid var(--border);border-radius:10px;padding:10px;font:12px ui-monospace,Menlo,monospace;resize:none}
#pix-copiar{border:0;cursor:pointer}</style>
<div id="pix"></div>
<h2>Para onde vai o dinheiro</h2>
<ul><li>Domínio, hospedagem e serviços que o robô usa para coletar os dados todo dia.</li>
<li>Tempo para criar novos testes de fiscalização, novas fontes (municípios, saúde, educação) e corrigir erros.</li>
<li>Pedidos de informação (LAI) e checagens quando um dado não fecha.</li></ul>
<h2>Nosso compromisso</h2>
<ul><li><b>Os dados continuam abertos e gratuitos</b> para todos, apoiando ou não.</li></ul>
<p>Outras formas de ajudar: compartilhe o <a href="/boletim/">boletim semanal</a>, mande sugestões e correções pelo WhatsApp e indique o site para jornalistas.</p>
<script src="/vendor/qrcode-generator-1.4.4.js"></script>
<script src="/apoie-pix.js" defer></script>"""
    return ("/apoie/", "Apoie o Cofre Aberto MS — transparência independente | Cofre Aberto MS",
            "Ajude a manter o Cofre Aberto MS: um site independente que mostra o dinheiro público de Mato Grosso do Sul. Doe por Pix.",
            "Apoie o Cofre Aberto MS", corpo)


# ---------------------------------------------------------------- perguntas
def perguntas():
    out = []
    g, cg, est, fed, sen, ss, st, em = (carregar(n) for n in ("governo_ms.json", "camara_municipal.json", "deputados_estaduais_ms.json",
                                                               "deputados_federais_ms.json", "senadores_ms.json", "supersalarios.json", "stf.json",
                                                               "emendas_municipios.json"))
    pe = (g.get("primeiroEscalao") or {})
    pessoas = pe.get("pessoas") or []
    gov = next((p for p in pessoas if p["cargo"] == "GOVERNADOR"), None)
    vice = next((p for p in pessoas if p["cargo"] == "VICE-GOVERNADOR"), None)
    if gov:
        sec = [p for p in pessoas if p["cargo"] not in ("GOVERNADOR", "VICE-GOVERNADOR")]
        r = (f"O governador de Mato Grosso do Sul, {gov['nome'].title()}, recebeu {brl(gov['bruto'])} brutos e {brl(gov['liquido'])} líquidos "
             f"em {pe.get('competencia')}, segundo a folha de pagamento publicada pelo Governo do Estado. No ano, a soma já chega a {brl(gov.get('somaAno'))}.")
        corpo = f"<div class='resposta'>{e(r)}</div>"
        corpo += "<h2>Primeiro escalão do Governo de MS (governador, vice, secretários e ex-governadores)</h2>" + tabela(["Nome", "Cargo e órgão", "#Bruto", "#Líquido"], [
            f"<tr><td>{e(p['nome'].title())}</td><td>{e(p['cargo'])}<br><small>{e(p['orgao'])}</small></td><td class='num'>{brl(p['bruto'])}</td><td class='num'>{brl(p['liquido'])}</td></tr>"
            for p in pessoas])
        out.append(("quanto-ganha-o-governador-de-ms", "Quanto ganha o governador de MS?", r, corpo, "governo-ms",
                    f"Salário do governador de MS em {pe.get('competencia')}: {brl(gov['bruto'])} brutos. Veja também o vice e os secretários."))
    vs = cg.get("vereadores") or []
    if vs:
        sal = float(vs[0].get("salarioBase") or 0)
        cota = (vs[0].get("verbaIndenizatoria") or {}).get(f"cotaAnual{ANO}") or 0
        pessoal = sum((v.get("gabinete") or {}).get("gastoPessoalMensal") or 0 for v in vs) / len(vs)
        r = (f"Um vereador de Campo Grande recebe subsídio de {brl(sal)} por mês. Além disso, cada um tem até {brl(cota)} por ano de verba indenizatória "
             f"(combustível, divulgação, assessoria) e um gabinete que custa em média {brl(pessoal)} por mês em salários de assessores.")
        corpo = f"<div class='resposta'>{e(r)}</div><h2>Quanto cada vereador já usou da verba em {ANO}</h2>" + tabela(["Vereador", "#Verba usada no ano"], [
            f"<tr><td>{link_empresa(v['nome'], url_parl('vereador', v['nome']))} "
            f"<small>{e(v.get('partido') or '')}</small></td><td class='num'>{brl((v.get('verbaIndenizatoria') or {}).get(f'gastoPago{ANO}'))}</td></tr>"
            for v in sorted(vs, key=lambda v: -((v.get('verbaIndenizatoria') or {}).get(f'gastoPago{ANO}') or 0))])
        out.append(("quanto-ganha-um-vereador-de-campo-grande", "Quanto ganha um vereador de Campo Grande?", r, corpo, "camara",
                    f"Salário de vereador em Campo Grande: {brl(sal)} por mês, mais verba indenizatória de até {brl(cota)} por ano e o gabinete."))
    ds = est.get("vereadores") or []
    if ds:
        sal = float(ds[0].get("salarioBase") or 0)
        cota = (ds[0].get("verbaIndenizatoria") or {}).get(f"cotaAnual{ANO}") or 0
        r = (f"Um deputado estadual de Mato Grosso do Sul recebe subsídio de {brl(sal)} por mês. Cada um também pode usar até {brl(cota)} por ano "
             f"de verba indenizatória da Assembleia Legislativa (ALEMS) para despesas do mandato, com nota fiscal.")
        corpo = f"<div class='resposta'>{e(r)}</div><p><a href='/deputado-estadual/'>Veja quanto cada deputado estadual gastou →</a></p>"
        out.append(("quanto-ganha-um-deputado-estadual-de-ms", "Quanto ganha um deputado estadual de MS?", r, corpo, "deputados-estaduais",
                    f"Salário de deputado estadual em MS: {brl(sal)} por mês, mais verba indenizatória de até {brl(cota)} por ano."))
    dfs = fed.get("deputados") or []
    if dfs:
        sal = float(dfs[0].get("salarioBase") or 0)
        media = sum(d.get("cotaGastaAno") or 0 for d in dfs) / len(dfs)
        r = (f"Um deputado federal recebe salário de {brl(sal)} por mês. Além disso, tem a cota parlamentar (CEAP) para despesas do mandato; "
             f"os {len(dfs)} deputados federais de MS usaram em média {brl(media)} da cota em {ANO}.")
        corpo = f"<div class='resposta'>{e(r)}</div><p><a href='/deputado-federal/'>Veja quanto cada deputado federal gastou →</a></p>"
        out.append(("quanto-ganha-um-deputado-federal", "Quanto ganha um deputado federal?", r, corpo, "deputados",
                    f"Salário de deputado federal: {brl(sal)} por mês, mais a cota parlamentar. Quanto os deputados de MS gastaram em {ANO}."))
    if st.get("subsidio"):
        r = (f"Um ministro do Supremo Tribunal Federal recebe subsídio de {brl(st['subsidio'])} por mês, valor que também é o teto do funcionalismo público. "
             f"Com outras verbas (férias, abono, atrasados), o contracheque bruto pode passar disso.")
        corpo = f"<div class='resposta'>{e(r)}</div><p><a href='/salario-ministros-stf/'>Veja o contracheque de cada ministro →</a></p>"
        out.append(("quanto-ganha-um-ministro-do-stf", "Quanto ganha um ministro do STF?", r, corpo, "stf",
                    f"Salário de ministro do STF: {brl(st['subsidio'])} por mês (o teto constitucional). Veja o contracheque de cada um."))
        sens = sen.get("senadores") or []
        r = (f"Um senador recebe salário de {brl(st['subsidio'])} por mês, o mesmo valor do teto do funcionalismo. "
             f"Também tem a cota para despesas do mandato (CEAPS): os {len(sens)} senadores de MS já usaram "
             f"{brl(sum(float(s.get('cotaGastaAno') or 0) for s in sens))} em {ANO}.")
        corpo = f"<div class='resposta'>{e(r)}</div><p><a href='/senador/'>Veja quanto cada senador gastou →</a></p>"
        out.append(("quanto-ganha-um-senador", "Quanto ganha um senador?", r, corpo, "senadores",
                    f"Salário de senador: {brl(st['subsidio'])} por mês, mais a cota parlamentar. Quanto os senadores de MS gastaram em {ANO}."))
    if ss.get("teto"):
        r = (f"Supersalário é quando um servidor público recebe acima do teto constitucional, que é o subsídio de ministro do STF ({brl(ss['teto'])}). "
             f"Em MS, {milhar(ss.get('liquidoAcimaTeto') or 0)} pessoas receberam líquido acima do teto no último mês publicado, quase sempre por verbas "
             f"indenizatórias e outros \"penduricalhos\", que não entram no limite.")
        corpo = f"<div class='resposta'>{e(r)}</div><p><a href='/supersalarios-ms/'>Veja quem recebe acima do teto em MS →</a></p>"
        out.append(("o-que-e-supersalario-e-teto-constitucional", "O que é supersalário e qual é o teto do funcionalismo?", r, corpo, "supersalarios",
                    f"O teto é {brl(ss['teto'])}. Em MS, {milhar(ss.get('liquidoAcimaTeto') or 0)} pessoas receberam líquido acima dele."))
    r = ("A cota parlamentar é um valor mensal que deputados e senadores podem usar para pagar despesas do mandato — passagens, combustível, "
         "aluguel de escritório, divulgação, consultorias — com reembolso mediante nota fiscal. Na Câmara dos Deputados se chama CEAP, no Senado CEAPS, "
         "e nas Assembleias e Câmaras Municipais costuma se chamar verba indenizatória. Ela é separada do salário.")
    corpo = f"<div class='resposta'>{e(r)}</div><p>No Cofre Aberto MS cada nota fiscal aparece com fornecedor, CNPJ e valor: " \
            f"<a href='/vereador/'>vereadores de CG</a>, <a href='/deputado-estadual/'>deputados estaduais</a>, <a href='/deputado-federal/'>deputados federais</a> e <a href='/senador/'>senadores</a>.</p>"
    out.append(("o-que-e-a-cota-parlamentar", "O que é a cota parlamentar?", r, corpo, "deputados",
                "O que é a cota parlamentar (CEAP, CEAPS, verba indenizatória), para que serve e quanto os parlamentares de MS gastaram."))
    pix = ((em.get("pix") or {}).get("anos") or {}).get(str(em.get("ano", ANO))) or 0
    r = ("Emendas Pix (transferências especiais) são emendas parlamentares que mandam dinheiro direto para o caixa da prefeitura ou do Estado, "
         "sem convênio nem projeto definido antes. Por isso são mais rápidas e mais difíceis de fiscalizar."
         + (f" Em {em.get('ano', ANO)}, MS recebeu {brl(pix)} em Emendas Pix." if pix else ""))
    corpo = f"<div class='resposta'>{e(r)}</div><p><a href='/municipio/'>Veja quanto cada município de MS recebeu →</a></p>"
    out.append(("o-que-sao-emendas-pix", "O que são Emendas Pix?", r, corpo, "emendas",
                "O que são as Emendas Pix (transferências especiais), por que são difíceis de fiscalizar e quanto MS recebeu."))
    return out


def main():
    temas = [t for t in (tema_apoie(), tema_termometro(), tema_votacoes(), tema_governo(), tema_prefeitura(), tema_supersalarios(), tema_auditoria(), tema_emendas(), tema_presidencia(), tema_stf()) if t]
    pergs = perguntas()
    TEMAS[:] = [(u, h1) for u, _, _, h1, _ in temas]
    PERGUNTAS[:] = [(f"/perguntas/{s}/", p) for s, p, *_ in pergs]
    paginas = []
    for url, tit, desc, h1, corpo in temas:
        paginas.append((url, pagina(url, tit, desc, h1, corpo)))
    for s, p, r, corpo, aba, desc in pergs:
        url = f"/perguntas/{s}/"
        corpo += "<p>" + painel(aba) + "</p>"
        paginas.append((url, pagina(url, f"{p} ({ANO}) | Cofre Aberto MS", desc, p, corpo, faq_ld(url, [(p, r)]),
                                    migalha="<a href='/perguntas/'>Perguntas</a>")))
    idx_corpo = "<p>Respostas curtas, com números atualizados todo dia a partir de fontes oficiais.</p>" + "".join(
        f"<div class='dest'><b><a href='/perguntas/{s}/'>{e(p)}</a></b><small>{e(r[:200])}</small></div>" for s, p, r, *_ in pergs)
    paginas.append(("/perguntas/", pagina("/perguntas/", "Perguntas sobre salários e gastos públicos em MS | Cofre Aberto MS",
                                          "Quanto ganha o governador de MS, um vereador de Campo Grande, um deputado, um senador, um ministro do STF; o que é a cota parlamentar e as Emendas Pix.",
                                          "Perguntas frequentes sobre o dinheiro público em MS", idx_corpo,
                                          faq_ld("/perguntas/", [(p, r) for _, p, r, *_ in pergs]))))
    mudou = 0
    for url, html in paginas:
        html = html.replace("{RELACIONADAS}", links_relacionados(url))
        mudou += escreve_se_mudou(ROOT / url.strip("/") / "index.html", html) or 0
    sm = ROOT / "sitemap.xml"
    if sm.exists():
        urls = [u for u, _ in paginas]
        txt = sm.read_text(encoding="utf-8")
        for u in urls:
            txt = re.sub(rf"  <url><loc>{re.escape(SITE + u)}</loc>.*?</url>\n", "", txt)
        novos = [f"  <url><loc>{SITE}{u}</loc><lastmod>{HOJE.isoformat()}</lastmod><changefreq>daily</changefreq><priority>0.8</priority></url>" for u in urls]
        escreve_se_mudou(sm, txt.replace("</urlset>", "\n".join(novos) + "\n</urlset>"))
    print(f"✅ {len(temas)} páginas de tema + {len(pergs)} perguntas + índice /perguntas/ ({mudou} alteradas) + sitemap")


if __name__ == "__main__":
    main()
