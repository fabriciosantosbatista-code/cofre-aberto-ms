#!/usr/bin/env python3
"""
Cofre Aberto MS — páginas de cachê por artista (/cache/<artista>/), a partir de dados/shows.json (PNCP)

Pedido de 28/11/2026 (SEO, Search Console: buscas como "cachê chitãozinho e xororó"). Uma página por artista que:
  - recebeu R$ 500 mil ou mais no ano (soma das contratações em MS), OU
  - tem 10 ou mais contratações em MS no ano, OU
  - aparece nas buscas do Search Console (config/cache_buscas.json).
Cada página: total pago por órgãos de MS no ano, a lista de contratações (órgão, cidade, data, evento, valor) com o link
de cada uma no PNCP. Texto neutro: o valor é o do contrato publicado; não é acusação.

Uso: python3 scripts/gerar_paginas_cache.py              (gera todas, o índice /cache/ e acrescenta ao sitemap)
     python3 scripts/gerar_paginas_cache.py --previa DIR artista1 artista2   (só as páginas pedidas, em DIR)
"""
import json, re, sys, unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from gerar_paginas_temas import (ANO, ROOT, SITE, brl, data_br, e, escreve_se_mudou, faq_ld, kpis, milhar, pagina,  # noqa: E402
                                 tabela)

MINIMO_CONTRATOS, TOTAL_MINIMO = 10, 500000  # 1º lote (28/11/2026): 55 páginas; em 26/12 vemos quais tiveram impressões


def slug(t):
    t = unicodedata.normalize("NFD", str(t or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", t).strip("-")


def buscas():
    try:
        return [slug(b) for b in json.load(open(ROOT / "config" / "cache_buscas.json", encoding="utf-8"))["artistas"]]
    except Exception:
        return []


def agrupar(shows):
    grupos = {}
    for s in shows:
        if s.get("chaveArtista") and s.get("tipo") == "show" and (s.get("valor") or 0) > 0:
            grupos.setdefault(s["chaveArtista"], []).append(s)
    return grupos


def selecionar(shows):
    grupos = agrupar(shows)
    procurados = set(buscas())
    return {k: l for k, l in grupos.items()
            if sum(x["valor"] for x in l) >= TOTAL_MINIMO or len(l) >= MINIMO_CONTRATOS or slug(k) in procurados}


def nome_exibido(chave, lst):
    """Nome como na busca (config/cache_buscas.json) ou o mais comum na fonte; nome todo em maiúsculas vira "Título"."""
    try:
        for b in json.load(open(ROOT / "config" / "cache_buscas.json", encoding="utf-8"))["artistas"]:
            if slug(b) == slug(chave):
                return b
    except Exception:
        pass
    nomes = [x["artista"] for x in lst]
    # o mais comum; empate: o com acento (grafia correta), depois a ordem alfabética (o mesmo nome em todas as coletas)
    nome = max(sorted(set(nomes)), key=lambda n: (nomes.count(n), sum(not c.isascii() for c in n)))
    return " ".join(w if len(w) <= 2 and w.lower() in ("e", "&") else w.capitalize() for w in nome.lower().split()) if nome.isupper() else nome


def fonte(x):
    return f"<a href='{e(x['link'])}' target='_blank' rel='noopener'>PNCP ↗</a>" if x.get("link") else "—"


def quem_pagou(lst):
    return "prefeituras" if all(x.get("esfera") == "M" for x in lst) else "órgãos públicos"


def pagina_artista(chave, lst, ano):
    nome = nome_exibido(chave, lst)
    lst = sorted(lst, key=lambda x: x.get("dataShow") or x.get("publicado") or "")
    total, orgaos = sum(x["valor"] for x in lst), len({x["orgao"] for x in lst})
    url = f"/cache/{slug(chave)}/"
    quem = quem_pagou(lst)
    r = (f"Em {ano}, {quem} de Mato Grosso do Sul pagaram {brl(total)} em {milhar(len(lst))} "
         f"{'contratação' if len(lst) == 1 else 'contratações'} de {nome}, segundo os contratos publicados no PNCP.")
    corpo = f"<div class='resposta'>{e(r)}</div>"
    corpo += kpis([(brl(total), f"pagos em {ano}"), (milhar(len(lst)), "contratações"), (milhar(orgaos), "órgãos contratantes"),
                   (brl(max(x['valor'] for x in lst)), "maior valor")])
    corpo += f"<h2>Contratações de {e(nome)} em MS em {ano}</h2>" + tabela(["Data do show", "Órgão e cidade", "Evento", "#Valor", "Fonte"], [
        f"<tr><td>{data_br(x.get('dataShow') or x.get('publicado'))}</td><td>{e(x['orgao'])}<br><small>{e(x.get('cidade') or x.get('cidadeOrgao') or '')}</small></td>"
        f"<td>{e(x.get('evento') or '—')}</td><td class='num'>{brl(x['valor'])}</td>"
        f"<td>{fonte(x)}</td></tr>"
        for x in lst])
    corpo += ("<p>Os valores são os dos contratos publicados no Portal Nacional de Contratações Públicas (PNCP), contratações por "
              "inexigibilidade de profissional do setor artístico (Lei 14.133/2021, art. 74, II). O valor de cada contrato pode incluir "
              "estrutura, transporte e hospedagem, conforme o que foi contratado.</p>"
              "<p><a href='/shows-pagos-com-dinheiro-publico-ms/'>Veja todos os shows pagos com dinheiro público em MS →</a></p>")
    titulo = f"Cachê de {nome} em MS: {brl(total)} pagos por {quem} em {ano} | Cofre Aberto MS"
    desc = (f"{nome}: {brl(total)} pagos por {quem} de MS em {ano}, em {milhar(len(lst))} "
            f"{'contratação' if len(lst) == 1 else 'contratações'}. Veja órgão, cidade, data, valor e o contrato no PNCP.")
    pergunta = f"Quanto custa o cachê de {nome} em MS?"
    return url, pagina(url, titulo, desc, f"Cachê de {nome} em MS em {ano}", corpo, faq_ld(url, [(pergunta, r)]),
                       migalha="<a href='/cache/'>Cachês</a>"), (nome, total, len(lst))


def main():
    d = json.load(open(ROOT / "dados" / "shows.json", encoding="utf-8"))
    ano = d.get("ano", ANO)
    sel = selecionar(d.get("shows") or [])
    grupos = agrupar(d.get("shows") or [])
    # página criada nunca é removida (28/11/2026): quem saiu do critério continua no ar, atualizado, e no sitemap;
    # só não entra no destaque do índice. Sem nenhum contrato nos dados de hoje, a página fica como está.
    existentes = {p.name for p in (ROOT / "cache").glob("*") if p.is_dir()} if (ROOT / "cache").exists() else set()
    mantidas = {k: l for k, l in grupos.items() if slug(k) in existentes and k not in sel}
    if "--previa" in sys.argv:
        i = sys.argv.index("--previa")
        destino, pedidos = Path(sys.argv[i + 1]), [slug(a) for a in sys.argv[i + 2:]]
        for k, lst in sel.items():
            if slug(k) in pedidos:
                url, html, _ = pagina_artista(k, lst, ano)
                (destino / f"{slug(k)}.html").write_text(html.replace("{RELACIONADAS}", ""), encoding="utf-8")
                print(f"✅ prévia: {destino / (slug(k) + '.html')}")
        return
    paginas, linhas, outras, indice = [], [], [], {}
    for k, lst in list(sel.items()) + list(mantidas.items()):
        url, html, info = pagina_artista(k, lst, ano)
        paginas.append((url, html.replace("{RELACIONADAS}", "")))
        (linhas if k in sel else outras).append((url, *info))
        indice[k] = url
    sem_dados = sorted(existentes - {slug(k) for k in indice})
    for sl in sem_dados:  # página antiga sem contrato nos dados de hoje: continua no ar e no sitemap, sem mudar
        paginas.append((f"/cache/{sl}/", None))
    linhas.sort(key=lambda t: -t[2])
    outras.sort(key=lambda t: t[1])
    idx = (f"<p>Quanto órgãos públicos de MS pagaram a cada artista em {ano}, com o link de cada contrato no PNCP. Entram os artistas com "
           f"{brl(TOTAL_MINIMO)} ou mais pagos no ano, {MINIMO_CONTRATOS} ou mais contratações, ou que são procurados na busca.</p>"
           + tabela(["Artista", "#Contratações", "#Total pago"], [
               f"<tr><td><a href='{u}'>{e(n)}</a></td><td class='num'>{milhar(c)}</td><td class='num'>{brl(t)}</td></tr>" for u, n, t, c in linhas]))
    if outras:
        idx += ("<h2>Outros artistas com página</h2><p class='aviso'>" + " · ".join(f"<a href='{u}'>{e(n)}</a>" for u, n, *_ in outras) + "</p>")
    paginas.append(("/cache/", pagina("/cache/", f"Cachês de artistas pagos por órgãos de MS em {ano} | Cofre Aberto MS",
                                      f"Cachês de {milhar(len(linhas))} artistas contratados por prefeituras e órgãos de MS em {ano}, com o contrato de cada show no PNCP.",
                                      f"Cachês de artistas pagos em MS em {ano}", idx).replace("{RELACIONADAS}", "")))
    mudou = sum(escreve_se_mudou(ROOT / u.strip("/") / "index.html", h) or 0 for u, h in paginas if h)
    # chave do artista → página, para os links da lista de shows e das páginas de município
    escreve_se_mudou(ROOT / "dados" / "cache_index.json", json.dumps(indice, ensure_ascii=False, indent=0, sort_keys=True))
    sm = ROOT / "sitemap.xml"
    txt = re.sub(rf"  <url><loc>{re.escape(SITE)}/cache/.*?</url>\n", "", sm.read_text(encoding="utf-8"))
    novos = [f"  <url><loc>{SITE}{u}</loc><changefreq>weekly</changefreq><priority>0.6</priority></url>" for u, _ in paginas]
    escreve_se_mudou(sm, txt.replace("</urlset>", "\n".join(novos) + "\n</urlset>"))
    print(f"✅ {len(linhas)} páginas de cachê em destaque + {len(outras) + len(sem_dados)} mantidas fora do critério + índice /cache/ "
          f"({mudou} alteradas) + sitemap")


if __name__ == "__main__":
    main()
