#!/usr/bin/env python3
"""
Cofre Aberto MS — Boletim semanal automático: /boletim/<ano>-s<semana>/

Roda todo dia (depois das análises) e mantém a página da semana corrente
(semana ISO, segunda a domingo). Quando a semana acaba, a página fica como
está e a próxima começa. Conteúdo:

  - notas fiscais de parlamentares de MS que apareceram nas fontes na semana
    (a data de emissão é mais antiga: conta quando a nota foi publicada)
  - quem mais lançou gastos na semana
  - pontos de atenção novos nos contratos da Prefeitura
  - contratos iniciados na semana
  - quanto cresceram os totais pagos (Governo do Estado, Prefeitura, emendas)

Estado em dados/boletim_estado.json: a data em que cada nota foi vista pela
primeira vez e um retrato dos totais no começo de cada semana. Na primeira
execução tudo vira "já visto" (não inunda o boletim com o ano inteiro).

Gera também /boletim/ (índice), dados/feeds/boletim.xml e o texto pronto para
WhatsApp de cada semana.
"""

import hashlib, json, re
from datetime import date, datetime, timedelta
from email.utils import format_datetime
from urllib.parse import quote

from gerar_analises import ANO, DADOS, ROOT, brl, carregar, limpa_nome, parlamentares, rss, salvar
from gerar_paginas_parlamentares import SITE, RODAPE, cabecalho, compacto, data_br, e, escreve_se_mudou, milhar

HOJE = date.today()
PASTA = ROOT / "boletim"
ESTADO = "boletim_estado.json"
MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"]


def semana_de(d):
    a, s, _ = d.isocalendar()
    return f"{a}-s{s:02d}"


def inicio_semana(d):
    return d - timedelta(days=d.weekday())


def id_nota(grupo, nome, n):
    k = "|".join(str(x) for x in (grupo, nome, n.get("data"), limpa_nome(n.get("fornecedor")), n.get("valor"), n.get("doc")))
    return hashlib.sha1(k.encode()).hexdigest()[:12]


def totais_atuais():
    gov = carregar("governo_ms.json")
    pref = carregar("prefeitura.json")
    em = carregar("emendas_municipios.json")
    ct = carregar("prefeitura_contratos.json")

    return {"governoPago": (gov.get("totais") or {}).get("pago") if gov.get("ano") == ANO else None,
            "prefeituraPago": pref.get("totalDespesas") if pref.get("ano") == ANO else None,
            "emendasMS": em.get("totalMS") if em.get("ano") == ANO else None,
            "contratosCompras": (ct.get("resumo") or {}).get("valorCompras") if ct.get("ano") == ANO else None,
            "supersalariosLiquido": carregar("supersalarios.json").get("liquidoAcimaTeto")}


def frase_periodo(ini, fim):
    if ini.month == fim.month:
        return f"{ini.day} a {fim.day} de {MESES[fim.month - 1]} de {fim.year}"
    return f"{ini.day} de {MESES[ini.month - 1]} a {fim.day} de {MESES[fim.month - 1]} de {fim.year}"


CSS_EXTRA = """
.dest{border:1px solid var(--border);border-radius:12px;padding:14px 16px;background:var(--surface);margin:10px 0}
.dest b{color:var(--ink)}.dest small{display:block;color:var(--ink-caption);font-size:.74rem;margin-top:4px}
.zaptxt{white-space:pre-wrap;font-family:ui-monospace,Menlo,monospace;font-size:.78rem;background:var(--surface-2);border:1px solid var(--border);border-radius:8px;padding:12px;color:var(--ink);overflow-wrap:anywhere}
.semanas a{display:block;padding:10px 0;border-bottom:1px solid var(--border);color:var(--ink)}.semanas span{color:var(--ink-caption);font-size:.8rem}
"""


def main():
    estado = carregar(ESTADO) or {}
    primeira = not estado.get("vistas")
    vistas = estado.get("vistas") or {}
    retratos = estado.get("retratos") or {}
    sem = semana_de(HOJE)
    ini = inicio_semana(HOJE)
    fim = ini + timedelta(days=6)

    # --- notas: registra a data em que cada uma apareceu ---
    paginas = carregar("paginas_index.json") or {}
    atuais, novas = set(), []
    for grupo, aba, rotulo, v, notas in parlamentares():
        for n in notas:
            i = id_nota(grupo, v["nome"], n)
            atuais.add(i)
            if i not in vistas:
                vistas[i] = (ini - timedelta(days=1)).isoformat() if primeira else HOJE.isoformat()
            if vistas[i] >= ini.isoformat():
                novas.append({"grupo": grupo, "aba": aba, "rotulo": rotulo, "nome": v["nome"], "partido": v.get("partido"),
                              "url": paginas.get(f"{grupo}|{v['nome']}"), **n})
    vistas = {k: d for k, d in vistas.items() if k in atuais}  # notas que sumiram da fonte saem do estado

    # --- retrato dos totais no começo da semana (o primeiro dia em que o boletim rodou nela) ---
    agora = totais_atuais()
    retratos.setdefault(sem, agora)
    base = retratos[sem]
    retratos = {k: v for k, v in sorted(retratos.items())[-60:]}

    # --- conteúdo ---
    por_parl = {}
    for n in novas:
        k = (n["grupo"], n["nome"])
        p = por_parl.setdefault(k, {"nome": n["nome"], "rotulo": n["rotulo"], "partido": n["partido"], "url": n["url"],
                                    "aba": n["aba"], "total": 0.0, "notas": 0})
        p["total"] += float(n.get("valor") or 0)
        p["notas"] += 1
    ranking = sorted(por_parl.values(), key=lambda p: -p["total"])
    total_novas = sum(p["total"] for p in ranking)
    maiores = sorted(novas, key=lambda n: -float(n.get("valor") or 0))[:10]

    # contratos e alertas também contam pela data em que apareceram (o início do contrato é anterior à publicação)
    def novos_desde(chave_estado, itens, ident):
        vistos = estado.get(chave_estado)
        base_vazia = vistos is None
        vistos = vistos or {}
        atuais_ids, out = set(), []
        for x in itens:
            i = ident(x)
            atuais_ids.add(i)
            if i not in vistos:
                vistos[i] = (ini - timedelta(days=1)).isoformat() if base_vazia else HOJE.isoformat()
            if vistos[i] >= ini.isoformat():
                out.append(x)
        estado[chave_estado] = {k: v for k, v in vistos.items() if k in atuais_ids}
        return out

    al = carregar("alertas_contratos.json")
    alertas = novos_desde("alertasVistos", al.get("alertas", []) if al.get("ano") == ANO else [], lambda a: a["id"])
    au = carregar("auditoria.json")
    sinais = novos_desde("sinaisVistos", au.get("sinais", []) if au.get("ano") == ANO else [], lambda s_: s_["id"])
    ct = carregar("prefeitura_contratos.json")
    # cada contrato é reconhecido pelo nº de registro da Prefeitura, que não muda; antes era um hash com o valor,
    # e um contrato antigo que teve o valor alterado aparecia como "novo" (ex.: registro 206679, janeiro, valor revisto em 12/11)
    def hash_antigo(c):
        return hashlib.sha1(f"{c['fornecedor']}|{c['inicio']}|{c['valor']}|{c['objeto'][:80]}".encode()).hexdigest()[:12]

    def id_contrato(c):
        return f"r{c['registro']}" if c.get("registro") else hash_antigo(c)

    cv = estado.get("contratosVistos") or {}
    if cv and not any(k.startswith("r") and k[1:].isdigit() for k in cv):  # migra o estado para o nº de registro, mantendo as datas
        base = min(cv.values())
        estado["contratosVistos"] = {id_contrato(c): cv.get(hash_antigo(c), base) for c in ct.get("contratos", []) if c.get("compra")}
    contratos = sorted(novos_desde("contratosVistos", [c for c in ct.get("contratos", []) if c.get("compra")] if ct.get("ano") == ANO else [],
                                   id_contrato),
                       key=lambda c: -c["valor"])
    salvar(ESTADO, {"atualizado": HOJE.isoformat(), "vistas": vistas, "retratos": retratos,
                    "alertasVistos": estado["alertasVistos"], "contratosVistos": estado["contratosVistos"],
                    "sinaisVistos": estado.get("sinaisVistos", {})})

    deltas = []
    for chave, rotulo, aba in (("governoPago", "pagos pelo Governo do Estado", "governo-ms"),
                               ("prefeituraPago", "pagos pela Prefeitura de Campo Grande", "prefeitura"),
                               ("emendasMS", "de emendas parlamentares pagos em MS", "emendas"),
                               ("contratosCompras", "em contratos novos da Prefeitura", "contratos-cg")):
        a, b = agora.get(chave), base.get(chave)
        if a is not None and b is not None and a - b > 1:
            deltas.append((a - b, rotulo, aba, a))

    periodo = frase_periodo(ini, fim)
    url = f"/boletim/{sem}/"
    titulo = f"Boletim Cofre Aberto MS — semana de {periodo}"
    linhas_zap = [f"*Cofre Aberto MS — semana de {periodo}*", ""]
    if ranking:
        linhas_zap.append(f"🧾 {milhar(len(novas))} notas fiscais novas de parlamentares de MS, somando {compacto(total_novas)}.")
        linhas_zap.append(f"   Quem mais lançou: {ranking[0]['nome']} ({compacto(ranking[0]['total'])}).")
    for dv, rot, aba, _ in deltas:
        linhas_zap.append(f"💰 +{compacto(dv)} {rot} na semana.")
    if contratos:
        c = contratos[0]
        linhas_zap.append(f"📑 {len(contratos)} contrato(s) novo(s) publicado(s) pela Prefeitura de CG; o maior: {c['fornecedor']} ({compacto(c['valor'])}).")
    if alertas:
        linhas_zap.append(f"⚠️ {len(alertas)} ponto(s) de atenção novo(s) nos contratos da Prefeitura.")
    if sinais:
        linhas_zap.append(f"🔎 {len(sinais)} sinal(is) novo(s) na Auditoria automática (padrões atípicos, não acusações).")
    # supersalários: retrato atual e variação contra a semana anterior
    ss = carregar("supersalarios.json")
    ss_ok = ss.get("ano") == ANO and ss.get("liquidoAcimaTeto") is not None
    sem_ant = sorted(k for k in retratos if k < sem)
    ss_ant = (retratos.get(sem_ant[-1]) or {}).get("supersalariosLiquido") if sem_ant else None
    if ss_ok:
        var = ""
        if ss_ant is not None and ss_ant != ss["liquidoAcimaTeto"]:
            dif = ss["liquidoAcimaTeto"] - ss_ant
            var = f" ({'+' if dif > 0 else ''}{dif} em relação à semana passada)"
        linhas_zap.append(f"💸 {milhar(ss['liquidoAcimaTeto'])} pessoas receberam líquido acima do teto (R$ 46,4 mil) no último mês publicado{var}.")
    if len(linhas_zap) == 2:
        linhas_zap.append("Semana sem novidades nas fontes oficiais até agora.")
    linhas_zap += ["", f"Veja tudo, com as fontes oficiais: {SITE}{url}"]
    texto_zap = "\n".join(linhas_zap)
    desc = " ".join(l for l in linhas_zap[2:-2] if l.strip())[:300] or f"O que mudou nos gastos públicos de MS na semana de {periodo}."

    blocos = []
    if ranking:
        def nome_link(p):
            return f"<a href='{p['url']}'>{e(p['nome'])}</a>" if p["url"] else e(p["nome"])
        lin = "".join(
            f"<tr><td class='f'>{nome_link(p)}"
            f"<small>{e(p['rotulo'])}{' · ' + e(p['partido']) if p['partido'] else ''}</small></td><td class='num'>{p['notas']}</td>"
            f"<td class='num'>{brl(p['total'])}</td></tr>" for p in ranking[:20])
        top = "".join(
            f"<tr><td>{data_br(n.get('data'))}</td><td class='f'>{e(limpa_nome(n.get('fornecedor')) or '—')}<small>{e(n['nome'])} · {e(n['rotulo'])}"
            f"{' · ' + e((n.get('categoria') or '')[:60]) if n.get('categoria') else ''}</small></td><td class='num'>{brl(n.get('valor'))}</td></tr>"
            for n in maiores)
        blocos.append(f"""<h2>Notas fiscais novas de parlamentares</h2>
<p><strong>{milhar(len(novas))}</strong> notas fiscais de vereadores de Campo Grande, deputados e senadores de MS apareceram nas fontes oficiais nesta semana,
somando <strong>{brl(total_novas)}</strong>. A data de cada nota é a de emissão — as casas legislativas publicam com semanas de atraso.</p>
<div class="tabela-wrap"><table><thead><tr><th>Quem lançou</th><th class="num">Notas</th><th class="num">Valor</th></tr></thead><tbody>{lin}</tbody></table></div>
<h2 style="font-size:1rem">As maiores notas da semana</h2>
<div class="tabela-wrap"><table><thead><tr><th>Data</th><th>Fornecedor</th><th class="num">Valor</th></tr></thead><tbody>{top}</tbody></table></div>""")
    if deltas:
        blocos.append("<h2>Quanto saiu dos cofres na semana</h2>" + "".join(
            f"<div class='dest'><b>+{brl(dv)}</b> {e(rot)}<small>Total no ano: {brl(tot)} · <a href='/cofre-aberto-ms.html#aba={aba}'>ver no painel</a></small></div>"
            for dv, rot, aba, tot in deltas))
    if contratos:
        lin = "".join(f"<tr><td>{data_br(c['inicio'])}</td><td class='f'>{e(c['fornecedor'])}<small>{e(c['objeto'][:160])}</small></td>"
                      f"<td class='num'>{brl(c['valor'])}</td></tr>" for c in contratos[:15])
        blocos.append(f"""<h2>Contratos novos na semana — Prefeitura de Campo Grande</h2>
<p>Contratos que apareceram no portal da Prefeitura nesta semana (a data de início costuma ser anterior à publicação).</p>
<div class="tabela-wrap"><table><thead><tr><th>Início</th><th>Fornecedor e objeto</th><th class="num">Valor</th></tr></thead><tbody>{lin}</tbody></table></div>""")
    if alertas:
        blocos.append("<h2>Pontos de atenção novos</h2><p class='aviso'>Critérios objetivos para facilitar a apuração. <strong>Nenhum deles indica irregularidade.</strong></p>" + "".join(
            f"<div class='dest'><b>{e(a['titulo'])}</b><small>{e(a['rotulo'])} · {e(a['descricao'][:240])}</small></div>" for a in alertas[:15]))
    if sinais:
        blocos.append("<h2>Auditoria: sinais de atenção novos</h2><p class='aviso'>Padrões atípicos encontrados pelos testes automáticos. "
                      "<strong>Sinal de atenção não é acusação</strong> — muitos têm explicação legal.</p>" + "".join(
            f"<div class='dest'><b>{e(s_['titulo'])}</b><small>{e(s_['rotulo'])} (nível {e(s_['nivel'])}) · {e(s_['descricao'][:240])} "
            f"<a href='/cofre-aberto-ms.html#aba=auditoria&sinal={s_['id']}'>ver →</a></small></div>" for s_ in sinais[:15]))
    if ss_ok:
        top = sorted(ss.get("ranking", []), key=lambda p: -p.get("liquido", 0))[:5]
        orgs = "".join(f"<tr><td class='f'>{e(o['orgao'])}<small>{e(o['mes'])}</small></td><td class='num'>{milhar(o.get('liquidoAcimaTeto', 0))}</td>"
                       f"<td class='num'>{milhar(o['pessoas'])}</td></tr>" for o in ss.get("orgaos", []) if o.get("liquidoAcimaTeto"))
        lin = "".join(f"<tr><td class='f'>{e(p['nome'])}<small>{e(p['cargo'])} · {e(p['orgao'])} · {e(p['mes'])}</small></td>"
                      f"<td class='num'>{brl(p['liquido'])}</td></tr>" for p in top)
        var_txt = ""
        if ss_ant is not None and ss_ant != ss["liquidoAcimaTeto"]:
            var_txt = f" Na semana passada eram {milhar(ss_ant)}."
        blocos.append(f"""<h2>Supersalários</h2>
<p><strong>{milhar(ss['liquidoAcimaTeto'])}</strong> pessoas receberam no último mês publicado um líquido acima do teto constitucional
({brl(ss['teto'])}), mesmo depois de imposto, previdência e corte do teto.{var_txt} Acima do teto não é sinônimo de irregular:
verbas indenizatórias ficam fora do teto por lei.</p>
<div class="tabela-wrap"><table><thead><tr><th>Órgão</th><th class="num">Líquido acima do teto</th><th class="num">Pessoas</th></tr></thead><tbody>{orgs}</tbody></table></div>
<h2 style="font-size:1rem">Os maiores líquidos</h2>
<div class="tabela-wrap"><table><thead><tr><th>Nome</th><th class="num">Líquido</th></tr></thead><tbody>{lin}</tbody></table></div>
<p style="margin-top:10px"><a href="/cofre-aberto-ms.html#aba=supersalarios">Ver o ranking completo e os penduricalhos →</a></p>""")
    if not blocos:
        blocos.append("<p class='aviso'>Nenhuma novidade nas fontes oficiais nesta semana até agora. O boletim é atualizado todos os dias.</p>")

    zap = "https://wa.me/?text=" + quote(texto_zap)
    jsonld = {"@context": "https://schema.org", "@type": "NewsArticle", "headline": titulo, "datePublished": ini.isoformat(),
              "dateModified": HOJE.isoformat(), "url": SITE + url, "inLanguage": "pt-BR",
              "publisher": {"@type": "Organization", "name": "Cofre Aberto MS", "url": SITE}}
    em_andamento = HOJE <= fim
    corpo = f"""<p class="breadcrumb"><a href="/">Início</a> / <a href="/boletim/">Boletim semanal</a> / {e(periodo)}</p>
<article><h1>O que mudou nos gastos públicos de MS</h1>
<p class="cargo" style="margin-bottom:16px">Semana de {e(periodo)}{" · em andamento, atualizado todos os dias" if em_andamento else ""} · gerado automaticamente a partir das fontes oficiais em {data_br(HOJE.isoformat())}</p>
<div class="acoes"><a class="btn zap" href="{zap}" target="_blank" rel="noopener">💬 Compartilhar no WhatsApp</a>
<a class="btn" href="/dados/feeds/boletim.xml">🔔 Receber por RSS</a><a class="btn" href="/cofre-aberto-ms.html">Abrir o painel</a></div>
{''.join(blocos)}
<h2>Texto pronto para compartilhar</h2>
<div class="zaptxt" id="zaptxt">{e(texto_zap)}</div>
<div class="acoes" style="margin-top:8px"><button class="btn" type="button" onclick="navigator.clipboard.writeText(document.getElementById('zaptxt').innerText).then(()=>this.textContent='✅ Copiado')">📋 Copiar texto</button></div>
<p style="margin-top:18px;font-size:.78rem">Os números vêm das mesmas fontes do painel — <a href="/metodologia.html">veja a metodologia</a>. Notas e contratos são contados na semana em que apareceram nas fontes.</p>
</article>"""
    html = cabecalho(titulo, desc, url, None, jsonld, tipo="article").replace("</style>", CSS_EXTRA + "</style>", 1) + corpo + RODAPE
    PASTA.mkdir(exist_ok=True)
    escreve_se_mudou(PASTA / sem / "index.html", html)
    resumo_sem = {"semana": sem, "periodo": periodo, "inicio": ini.isoformat(), "url": url, "notas": len(novas),
                  "valorNotas": round(total_novas, 2), "contratos": len(contratos), "alertas": len(alertas),
                  "sinais": len(sinais), "texto": texto_zap, "atualizado": HOJE.isoformat()}
    escreve_se_mudou(PASTA / sem / "resumo.json", json.dumps(resumo_sem, ensure_ascii=False, indent=1))

    # --- índice, feed e sitemap ---
    semanas = []
    for d in sorted(PASTA.iterdir(), reverse=True):
        r = d / "resumo.json"
        if d.is_dir() and r.exists():
            semanas.append(json.loads(r.read_text(encoding="utf-8")))
    def item_semana(s):
        extra = f" · {s['contratos']} contrato(s)" if s["contratos"] else ""
        return (f"<a href='{s['url']}'>Semana de {e(s['periodo'])}<br><span>{milhar(s['notas'])} notas novas · "
                f"{compacto(s['valorNotas'])}{extra}</span></a>")
    lista = "".join(item_semana(s) for s in semanas)
    idx = cabecalho(f"Boletim semanal — gastos públicos de MS | Cofre Aberto MS",
                    "Toda semana, o que mudou nos gastos de vereadores, deputados, senadores, Prefeitura de Campo Grande e Governo de MS.",
                    "/boletim/", None, {"@context": "https://schema.org", "@type": "CollectionPage", "name": "Boletim semanal", "url": SITE + "/boletim/"},
                    tipo="website").replace("</style>", CSS_EXTRA + "</style>", 1) + f"""<p class="breadcrumb"><a href="/">Início</a> / Boletim semanal</p>
<article><h1>Boletim semanal</h1>
<p class="cargo" style="margin-bottom:16px">Toda semana, o que apareceu de novo nas fontes oficiais: notas fiscais de parlamentares, contratos e pagamentos da Prefeitura de Campo Grande, do Governo do Estado e emendas.
<a href="/dados/feeds/boletim.xml">Assine por RSS</a>.</p>
<div class="semanas">{lista}</div></article>""" + RODAPE
    escreve_se_mudou(PASTA / "index.html", idx)
    itens = [{"titulo": f"Semana de {s['periodo']}", "link": SITE + s["url"], "guid": s["semana"],
              "data": format_datetime(datetime.fromisoformat(s["atualizado"]).replace(hour=20).astimezone()),
              "descricao": s["texto"]} for s in semanas[:20]]
    (DADOS / "feeds").mkdir(parents=True, exist_ok=True)
    escreve_se_mudou(DADOS / "feeds" / "boletim.xml", rss("Cofre Aberto MS — boletim semanal", SITE + "/boletim/",
                                                       "O que mudou nos gastos públicos de MS, toda semana", itens))
    sm = ROOT / "sitemap.xml"
    if sm.exists():
        txt = re.sub(r"  <url><loc>[^<]*/boletim/[^<]*</loc>.*?</url>\n", "", sm.read_text(encoding="utf-8"))
        novos = [f"  <url><loc>{SITE}/boletim/</loc><lastmod>{HOJE.isoformat()}</lastmod><changefreq>daily</changefreq><priority>0.7</priority></url>"]
        novos += [f"  <url><loc>{SITE}{s['url']}</loc><lastmod>{s['atualizado']}</lastmod><changefreq>weekly</changefreq><priority>0.6</priority></url>" for s in semanas]
        escreve_se_mudou(sm, txt.replace("</urlset>", "\n".join(novos) + "\n</urlset>"))
    print(f"✅ boletim {sem}: {len(novas)} notas novas ({brl(total_novas)}), {len(contratos)} contratos, {len(alertas)} alertas, "
          f"{len(deltas)} totais com variação" + (" — primeira execução: notas existentes marcadas como já vistas" if primeira else ""))


if __name__ == "__main__":
    main()
