#!/usr/bin/env python3
"""
Cofre Aberto MS — análises derivadas das notas fiscais (roda ao fim da coleta)

Gera, a partir dos JSONs já coletados:

1. dados/conexoes_fornecedores.json
   Empresas (CNPJ válido, agrupado pela raiz de 8 dígitos) que receberam de
   DOIS OU MAIS pagadores públicos de MS: vereadores de CG, deputados
   estaduais, deputados federais, senadores e a Prefeitura de CG.
   Só pessoa jurídica: CPFs (pessoas físicas) e CNPJs com dígito verificador
   inválido (erros de leitura de PDF) ficam de fora — LGPD e precisão.
   Enquadramento: "conexões" (quem paga o mesmo fornecedor), NUNCA
   "suspeita": um fornecedor comum é, na maioria das vezes, normal
   (companhia aérea, posto, telefonia, gráfica).

2. dados/evolucao_mensal.json
   Gasto mês a mês de cada parlamentar em 2026 e, quando existe
   (dados/historico_2025.json), no mesmo mês de 2025.

3. dados/feeds/*.xml (RSS 2.0) + dados/feeds/index.json
   Um feed por parlamentar de MS com as notas fiscais mais recentes, e um
   feed geral — para o público "seguir" um político num leitor de RSS ou
   receber por e-mail via serviço de RSS→e-mail.
"""

import hashlib, json, re, unicodedata
from datetime import date, datetime
from email.utils import format_datetime
from pathlib import Path
from xml.sax.saxutils import escape

ROOT = Path(__file__).parent.parent
DADOS = ROOT / "dados"
SITE = "https://cofreabertoms.com.br"
PAINEL = f"{SITE}/cofre-aberto-ms.html"
import sys as _sys
_sys.path.insert(0, str(Path(__file__).parent))
from ano_ref import ano_referencia
ANO = ano_referencia()  # vira em 1º de fevereiro (scripts/ano_ref.py)
MESES_ABREV = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]


def carregar(nome):
    try:
        return json.load(open(DADOS / nome, encoding="utf-8"))
    except Exception:
        return {}


def salvar(nome, data):
    path = DADOS / nome
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    print(f"✅ {nome} ({path.stat().st_size // 1024} KB)")


def slug(txt):
    t = unicodedata.normalize("NFD", txt or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", t).strip("-")


def cnpj_valido(d):
    if len(d) != 14 or len(set(d)) == 1:
        return False
    def dv(base, pesos):
        s = sum(int(a) * b for a, b in zip(base, pesos)) % 11
        return "0" if s < 2 else str(11 - s)
    p1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    return d[12] == dv(d[:12], p1) and d[13] == dv(d[:13], [6] + p1)


def limpa_nome(t):
    # leitura de PDF da Câmara CG às vezes deixa "/26 " ou "“+ —" no início do nome
    t = re.sub(r"^[^\w/]*", "", (t or "").strip())
    t = re.sub(r"^/\d+\s+", "", t)
    return re.sub(r"^[^\w]+", "", t).strip()


def fmt_cnpj(d):
    return f"{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:]}"


# ------------------------------------------------------------------
# Parlamentares de MS: (grupo, aba do painel, rótulo, nome, notas normalizadas)
# ------------------------------------------------------------------
def parlamentares():
    out = []
    for v in carregar("camara_municipal.json").get("vereadores", []):
        out.append(("vereador", "camara", "Vereador(a) CG", v, [
            {"data": d.get("data"), "fornecedor": d.get("fornecedor"), "cnpj": d.get("cnpj"),
             "valor": d.get("valor"), "categoria": d.get("descricao") or d.get("ato"), "doc": d.get("nf")}
            for d in v.get("despesas") or []]))
    for v in carregar("deputados_estaduais_ms.json").get("vereadores", []):
        out.append(("estadual", "deputados-estaduais", "Dep. estadual", v, [
            {"data": d.get("data"), "fornecedor": d.get("fornecedor"), "cnpj": d.get("cnpj"),
             "valor": d.get("valor"), "categoria": d.get("categoria"), "doc": d.get("nf"),
             "url": d.get("urlPdf"), "mes": d.get("mes")}
            for d in v.get("despesas") or []]))
    for v in carregar("deputados_federais_ms.json").get("deputados", []):
        out.append(("federal", "deputados", "Dep. federal MS", v, [
            {"data": d.get("data"), "fornecedor": d.get("fornecedor"), "cnpj": d.get("cnpjCpfFornecedor"),
             "valor": d.get("valor"), "categoria": d.get("categoria"), "doc": d.get("doc"),
             "url": d.get("urlNotaFiscal"), "mes": d.get("mes")}
            for d in v.get("despesas") or []]))
    for v in carregar("senadores_ms.json").get("senadores", []):
        out.append(("senador", "senadores", "Senador(a) MS", v, [
            {"data": d.get("data"), "fornecedor": d.get("fornecedor"), "cnpj": d.get("cnpjCpf"),
             "valor": d.get("valor"), "categoria": d.get("categoria"), "doc": d.get("doc"), "mes": d.get("mes")}
            for d in v.get("notasCeaps") or []]))
    return out


# ------------------------------------------------------------------
# 1. Conexões entre fornecedores
# ------------------------------------------------------------------
def gerar_conexoes(lista):
    empresas = {}

    def registra(cnpj_txt, fornecedor, valor, pagador_chave, pagador_info):
        d = re.sub(r"\D", "", str(cnpj_txt or ""))
        if not cnpj_valido(d) or not valor:
            return
        e = empresas.setdefault(d[:8], {"raiz": d[:8], "cnpjs": set(), "nomes": {}, "pagadores": {}})
        e["cnpjs"].add(d)
        nome = limpa_nome(fornecedor)
        if nome:
            e["nomes"][nome] = e["nomes"].get(nome, 0) + 1
        p = e["pagadores"].setdefault(pagador_chave, {**pagador_info, "total": 0.0, "notas": 0})
        p["total"] += float(valor)
        p["notas"] += 1

    for grupo, aba, rotulo, v, notas in lista:
        info = {"tipo": grupo, "rotulo": rotulo, "nome": v["nome"], "aba": aba, "partido": v.get("partido")}
        for n in notas:
            registra(n["cnpj"], n["fornecedor"], n["valor"], f"{grupo}:{v['nome']}", info)
    for d in carregar("prefeitura.json").get("despesas", []):
        registra(d.get("cnpj"), d.get("fornecedor"), d.get("valor"), "prefeitura",
                 {"tipo": "prefeitura", "rotulo": "Prefeitura de CG", "nome": "Prefeitura de Campo Grande",
                  "aba": "prefeitura"})
    gov = carregar("governo_ms_credores.json")
    if gov.get("ano") == ANO:  # [cnpj, nome, pago, empenhado] — um registro por credor no ano
        for c in gov.get("credores", []):
            registra(c[0], c[1], c[2], "governo",
                     {"tipo": "governo", "rotulo": "Governo do Estado", "nome": "Governo do Estado de MS",
                      "aba": "governo-ms"})

    conexoes = []
    for e in empresas.values():
        # Prefeitura e Governo pagam milhares de empresas: só entra quem também
        # recebeu de algum parlamentar (é isso que a aba investiga)
        if len(e["pagadores"]) < 2 or all(p["tipo"] in ("prefeitura", "governo") for p in e["pagadores"].values()):
            continue
        pag = sorted(e["pagadores"].values(), key=lambda p: -p["total"])
        for p in pag:
            p["total"] = round(p["total"], 2)
        conexoes.append({
            "raiz": e["raiz"],
            "nome": max(e["nomes"].items(), key=lambda x: x[1])[0] if e["nomes"] else "—",
            "cnpjs": [fmt_cnpj(c) for c in sorted(e["cnpjs"])],
            "numPagadores": len(pag),
            "tipos": sorted({p["tipo"] for p in pag}),
            "total": round(sum(p["total"] for p in pag), 2),
            "notas": sum(p["notas"] for p in pag),
            "pagadores": pag,
        })
    conexoes.sort(key=lambda c: (-c["numPagadores"], -c["total"]))
    salvar("conexoes_fornecedores.json", {
        "ultimaAtualizacao": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "ano": ANO,
        "nota": ("Empresas que receberam de dois ou mais pagadores públicos de MS em "
                 f"{ANO}. Um fornecedor em comum NÃO indica irregularidade — companhias "
                 "aéreas, postos, telefonia e gráficas atendem muitos gabinetes. Só pessoa "
                 "jurídica com CNPJ válido; filiais agrupadas pela raiz do CNPJ."),
        "totalEmpresas": len(conexoes),
        "conexoes": conexoes,
    })
    return conexoes


# ------------------------------------------------------------------
# 2. Evolução mensal 2026 x 2025
# ------------------------------------------------------------------
def gerar_evolucao(lista):
    hist = carregar(f"historico_{ANO - 1}.json")
    hist_cg = carregar(f"historico_{ANO - 1}_camara_cg.json").get("vereadoresCG") or {}
    chave_hist = {"federal": "federaisMS", "senador": "senadoresMS", "estadual": "estaduais"}
    grupos = {}
    for grupo, aba, rotulo, v, notas in lista:
        m = [0.0] * 12
        if grupo == "vereador":
            vi = v.get("verbaIndenizatoria") or {}
            for campo in ("mesesAto027", "mesesAto028"):
                for ab, val in (vi.get(campo) or {}).items():
                    if ab in MESES_ABREV:
                        m[MESES_ABREV.index(ab)] += float(val or 0)
        else:
            # mês de competência (todas as fontes trazem, dentro do ano da cota);
            # a data de emissão só é usada se faltar — uma nota emitida em dez/2025
            # pode ser despesa de jan/2026
            for n in notas:
                mes = n.get("mes")
                try:
                    mes = int(str(mes)) if mes not in (None, "") else int(str(n.get("data") or "")[5:7])
                except ValueError:
                    continue
                if 1 <= mes <= 12:
                    m[mes - 1] += float(n.get("valor") or 0)
        anterior = None
        if grupo == "vereador" and v["nome"] in hist_cg:
            anterior = hist_cg[v["nome"]]["mensal"]
        elif grupo in chave_hist:
            h = hist.get(chave_hist[grupo]) or {}
            reg = h.get(str(v.get("id"))) or h.get(v["nome"])
            if reg:
                anterior = reg["mensal"]
        grupos.setdefault(grupo, []).append({
            "nome": v["nome"], "partido": v.get("partido"), "aba": aba, "rotulo": rotulo,
            "m": [round(x, 2) for x in m],
            "mAnterior": anterior,
            "cotaAnual": (v.get("verbaIndenizatoria") or {}).get(f"cotaAnual{ANO}"),
        })
    salvar("evolucao_mensal.json", {
        "ultimaAtualizacao": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "ano": ANO, "anoAnterior": ANO - 1,
        "mesAtual": date.today().month,
        # último mês já fechado do ano de referência (dez se o ano já virou no calendário)
        "mesFechado": 12 if ANO < date.today().year else max(1, date.today().month - 1),
        "nota": ("Valores por mês de competência da despesa. Deputados federais e senadores: "
                 "notas da CEAP/CEAPS; deputados estaduais: CEAP da ALEMS; vereadores de CG: "
                 "verba indenizatória declarada (Atos 027/028), sem histórico de anos anteriores."),
        "grupos": grupos,
    })


# ------------------------------------------------------------------
# 3. Feeds RSS
# ------------------------------------------------------------------
def rss(titulo, link, descricao, itens):
    agora = format_datetime(datetime.now().astimezone())
    xml = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom"><channel>',
           f"<title>{escape(titulo)}</title>", f"<link>{escape(link)}</link>",
           f"<description>{escape(descricao)}</description>", "<language>pt-BR</language>",
           f"<lastBuildDate>{agora}</lastBuildDate>", "<ttl>720</ttl>"]
    for it in itens:
        xml += ["<item>", f"<title>{escape(it['titulo'])}</title>", f"<link>{escape(it['link'])}</link>",
                f'<guid isPermaLink="false">{it["guid"]}</guid>', f"<pubDate>{it['data']}</pubDate>",
                f"<description>{escape(it['descricao'])}</description>", "</item>"]
    xml.append("</channel></rss>")
    return "\n".join(xml) + "\n"


def brl(v):
    return "R$ " + f"{float(v or 0):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def gerar_feeds(lista):
    pasta = DADOS / "feeds"
    pasta.mkdir(parents=True, exist_ok=True)
    indice, geral = [], []
    for grupo, aba, rotulo, v, notas in lista:
        s = f"{grupo}-{slug(v['nome'])}"
        link = f"{PAINEL}#aba={aba}&p={v['nome'].replace(' ', '%20')}"
        itens = []
        for n in sorted(notas, key=lambda n: n.get("data") or "", reverse=True)[:40]:
            try:
                dt = datetime.fromisoformat(str(n.get("data"))[:10]).replace(hour=12).astimezone()
            except ValueError:
                continue
            guid = hashlib.sha1(f"{s}|{n.get('data')}|{n.get('valor')}|{n.get('doc')}|{n.get('fornecedor')}".encode()).hexdigest()
            item = {
                "titulo": f"{brl(n.get('valor'))} — {limpa_nome(n.get('fornecedor')) or 'fornecedor não informado'}",
                "link": n.get("url") or link,
                "guid": guid,
                "data": format_datetime(dt),
                "descricao": (f"{v['nome']} ({rotulo}) — {n.get('categoria') or 'despesa'}"
                              + (f" · doc. {n['doc']}" if n.get("doc") else "")
                              + f" · {dt.strftime('%d/%m/%Y')}. Ver no Cofre Aberto MS: {link}"),
                "_ord": str(n.get("data")),
            }
            itens.append(item)
            geral.append({**item, "titulo": f"{v['nome']}: {item['titulo']}"})
        (pasta / f"{s}.xml").write_text(rss(
            f"{v['nome']} ({rotulo}) — notas fiscais | Cofre Aberto MS", link,
            f"Novas notas fiscais de {v['nome']} ({rotulo}), coletadas automaticamente das fontes oficiais.",
            itens), encoding="utf-8")
        indice.append({"slug": s, "nome": v["nome"], "grupo": grupo, "aba": aba,
                       "feed": f"dados/feeds/{s}.xml"})
    geral.sort(key=lambda i: i["_ord"], reverse=True)
    (pasta / "todas.xml").write_text(rss(
        "Cofre Aberto MS — novas notas fiscais de políticos de MS", PAINEL,
        "Notas fiscais mais recentes de vereadores de Campo Grande, deputados estaduais, deputados federais e senadores de MS.",
        geral[:150]), encoding="utf-8")
    salvar("feeds/index.json", {"ultimaAtualizacao": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
                                "geral": "dados/feeds/todas.xml", "parlamentares": indice})
    print(f"✅ feeds RSS: {len(indice)} parlamentares + geral")


if __name__ == "__main__":
    lista = parlamentares()
    c = gerar_conexoes(lista)
    print(f"   {len(c)} empresas com 2+ pagadores")
    gerar_evolucao(lista)
    gerar_feeds(lista)
