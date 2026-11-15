#!/usr/bin/env python3
"""
Cofre Aberto MS — shows e outras contratações artísticas pagas com dinheiro público em MS

Fonte: Portal Nacional de Contratações Públicas (PNCP, pncp.gov.br/api). Desde a Lei 14.133/2021, toda
contratação de artista por inexigibilidade (art. 74, II — "profissional do setor artístico") é publicada lá,
com o objeto (artista, evento, data e local, quando o órgão escreve), o valor e a empresa contratada.

Para cada contratação do ano em MS (Governo do Estado e prefeituras, câmaras e fundos municipais):
  órgão, cidade, objeto, valor (homologado; se ainda não houver, o estimado), empresa contratada (resultado do
  item), e o que dá para ler do texto: artista, evento, data do show e cidade do show.
População das cidades: Tesouro Nacional (Siconfi, cadastro de entes) — para o gasto por habitante.

A Prefeitura de Campo Grande não publica essas contratações no PNCP; o que ela paga a empresas de eventos
aparece na aba Prefeitura.

Gera dados/shows.json; cache em dados/shows_cache.json (contratação já lida não muda; as dos últimos 45 dias
são relidas para pegar o valor homologado e a empresa).
"""

import json, re, sys, time, unicodedata
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from pathlib import Path

import requests

DADOS = Path(__file__).parent.parent / "dados"
SAIDA, CACHE = DADOS / "shows.json", DADOS / "shows_cache.json"
API = "https://pncp.gov.br/api"
ENTES = "https://apidatalake.tesouro.gov.br/ords/siconfi/tt/entes"
H = {"User-Agent": "Mozilla/5.0 (CofreAbertoMS; +https://cofreabertoms.com.br)"}
HOJE = date.today()
ANO = HOJE.year
T0 = time.monotonic()
LIMITE = 11 * 60
MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"]

SHOW = re.compile(r"show|apresenta[cç][aã]o|cantor|cantora|dupla|banda|\bdj\b|m[uú]sic|orquestra|espet[aá]culo|teatr|dan[cç]a|coral|"
                  r"grupo|artista|violeir|sanfon|forr[oó]|samba|pagode|rodeio|festival|festa", re.I)
NAO_SHOW = re.compile(r"estatueta|escultura|quadros?\b|obra de arte|pintura|parecerista|oficina|curso|livro|exposi[cç][aã]o de obras", re.I)


def get(url, params=None, tent=4):
    for t in range(tent):
        if time.monotonic() - T0 > LIMITE + 120:
            return None
        try:
            r = requests.get(url, params=params, headers=H, timeout=60)
            if r.status_code == 200:
                return r.json()
            if r.status_code in (204, 404):
                return None
        except (requests.RequestException, ValueError):
            pass
        time.sleep(2 * (t + 1))
    return None


def sem_acento(t):
    return "".join(c for c in unicodedata.normalize("NFD", t or "") if unicodedata.category(c) != "Mn")


def limpa(t):
    return re.sub(r"\s+", " ", (t or "").replace("\r", " ").replace("\n", " ")).strip()


# ------------------------------------------------------------------ leitura do texto
_PARA = (r"(?=\s*(?:,|;|\.|\*|•|–|-\s|\(|“|\"|$)|\s+(?:para|no|na|nos|nas|durante|em|com|a\s+ser|que|dia|data|evento|previst[oa]|"
         r"realizad[oa]|apresenta[cç][aã]o|show|de\s+renome|pela|pelo|junto|acompanhad[oa])\b)")
_ART = [
    r"(?:apresentad[oa]|realizad[oa])\s+pel[oa]s?\s+(?:cantor[a]?|dupla(?:\s+sertaneja)?|banda|grupo|dj|artista)?\s*[“\"']([^”\"']{2,60})[”\"']",
    r"(?:dupla(?:\s+sertaneja)?(?:\s+de\s+renome\s+nacional)?|cantor[a]?|cantores|banda|grupo|\bdj\b|m[uú]sico|violeiro|artista|sanfoneiro)\s*[“\"']([^”\"']{2,60})[”\"']",
    r"(?:dupla(?:\s+sertaneja)?(?:\s+de\s+renome\s+nacional)?|cantor[a]?|cantores|banda|grupo|\bdj\b|m[uú]sico|violeiro|sanfoneiro)\s+([A-ZÀ-Ú0-9][^,;\.\*•\(\)“”\"]{1,60}?)" + _PARA,
    r"show\s+(?:musical|art[ií]stico)?\s*(?:com|do|da|de)\s+(?:o|a|os|as)?\s*([A-ZÀ-Ú][^,;\.\*•\(\)“”\"]{1,60}?)" + _PARA,
    r"artista[s]?\s*:?\s*(?:contrata[cç][aã]o\s+(?:d[oa]s?\s+)?(?:cantor[a]?|dupla|banda|grupo)?\s*)?([A-ZÀ-Ú][^,;\.\*•\(\)“”\"]{1,60}?)" + _PARA,
]
_RUIM = re.compile(r"^(empresa|contrata|presta|servi|show|apresenta|para|um|uma|01|1\b|o |a |de |do |da |renome|nacional|evento|municipal|munic|"
                   r"fundamenta|teatral|dura[cç][aã]o|durante|previst|m[ií]nimo|musical|art[ií]stic|local|exclusiv|represent|inexig|profission)", re.I)


def artista(txt):
    for p in _ART:
        for m in re.finditer(p, txt, re.I):
            a = limpa(m.group(1)).strip(" -–:*•\"'“”")
            a = re.sub(r"\s+(e\s+banda|e\s+seus?\s+\w+)$", "", a, flags=re.I) if len(a) > 40 else a
            if 2 <= len(a) <= 50 and not _RUIM.match(a) and not re.search(r"\d{2}/\d{2}|R\$", a):
                return a
    return None


def chave_artista(a):
    a = sem_acento(a or "").lower()
    a = re.sub(r"\b(dupla|cantor|cantora|banda|grupo|dj|sertaneja|e banda|show)\b", " ", a)
    a = a.replace("&", " e ")
    return re.sub(r"[^a-z0-9]+", " ", a).strip()


def evento(txt):
    for p in (r"evento\s*:?\s*[“\"']([^”\"']{3,90})[”\"']", r"(?:durante|na|no|para\s+(?:a|o))\s+(\d+[ªº°]?\s*(?:edi[cç][aã]o\s+d[oa]\s+)?(?:festa|festival|expo|rodeio|carnaval|anivers[aá]rio|encontro|feira)[^,;\.\*•]{2,70})",
              r"((?:festa|festival|expo|rodeio|carnaval|anivers[aá]rio de|marcha para jesus|encontro)\b[^,;\.\*•]{2,60})"):
        m = re.search(p, txt, re.I)
        if m:
            ev = re.split(r"[”\"]|\s+(?:no|nos|na|nas)\s+dia|\s+com\s+a\s+realiza|\s+a\s+ser|\s+que\s+", limpa(m.group(1)), flags=re.I)[0]
            return ev.strip(" -–:*•\"'“”")[:90] or None
    return None


def data_show(txt):
    m = re.search(r"(\d{1,2})\s*(?:º|°)?\s+de\s+(" + "|".join(MESES) + r"|marco)\s+(?:de\s+)?(\d{4})", txt, re.I)
    if m:
        mes = [sem_acento(x) for x in MESES].index(sem_acento(m.group(2).lower())) + 1
        try:
            return date(int(m.group(3)), mes, int(m.group(1))).isoformat()
        except ValueError:
            return None
    m = re.search(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b", txt)
    if m:
        try:
            return date(int(m.group(3)), int(m.group(2)), int(m.group(1))).isoformat()
        except ValueError:
            return None
    return None


def cidade_show(txt, cidades):
    t = sem_acento(txt).lower()
    for m in re.finditer(r"(?:munic[ií]pio\s+de|cidade\s+de|em)\s+([a-z ]{3,30}?)\s*(?:/|-|–)\s*ms\b", t):
        c = cidades.get(m.group(1).strip())
        if c:
            return c
    for m in re.finditer(r"munic[ií]pio\s+de\s+([a-z ]{3,30})", t):
        nome = m.group(1).strip()
        for k, c in cidades.items():
            if nome.startswith(k):
                return c
    return None


# ------------------------------------------------------------------ coleta
def listar(ini, fim):
    out, p = [], 1
    while True:
        d = get(f"{API}/consulta/v1/contratacoes/publicacao", {"dataInicial": ini.strftime("%Y%m%d"), "dataFinal": fim.strftime("%Y%m%d"),
                                                               "codigoModalidadeContratacao": 9, "uf": "MS", "pagina": p, "tamanhoPagina": 50})
        if not d:
            break
        out += d.get("data") or []
        if p >= (d.get("totalPaginas") or 1):
            break
        p += 1
    return out


def contratos_orgao(cnpj, desde):
    """{numeroControlePNCP da compra: [empresa]} dos contratos que o órgão publicou desde a data (lista de contratos do PNCP)."""
    out, p = {}, 1
    while True:
        d = get(f"{API}/consulta/v1/contratos", {"dataInicial": desde.strftime("%Y%m%d"), "dataFinal": HOJE.strftime("%Y%m%d"),
                                                 "cnpjOrgao": cnpj, "pagina": p, "tamanhoPagina": 500})
        if d is None:
            return None if p == 1 else out
        for x in d.get("data") or []:
            k = x.get("numeroControlePncpCompra")
            if not k:
                continue
            e = out.setdefault(k, {})
            doc = x.get("niFornecedor") or ""
            v = e.setdefault(doc, {"cnpj": doc, "nome": limpa(x.get("nomeRazaoSocialFornecedor")), "valor": 0.0})
            v["valor"] += x.get("valorGlobal") or 0
        if p >= (d.get("totalPaginas") or 1):
            return out
        p += 1


def populacoes():
    d = get(ENTES) or {}
    out = {}
    for e in d.get("items") or []:
        if e.get("uf") == "MS" and e.get("esfera") == "M":
            out[sem_acento(e["ente"]).lower()] = {"nome": e["ente"], "populacao": e.get("populacao")}
    return out


def main():
    try:
        cache = json.load(open(CACHE, encoding="utf-8"))
    except Exception:
        cache = {}
    try:
        anterior = json.load(open(SAIDA, encoding="utf-8"))
    except Exception:
        anterior = {}
    pops = populacoes() or {k: v for k, v in (anterior.get("_populacoes") or {}).items()}
    cidades = {k: v["nome"] for k, v in pops.items()}

    # lista do ano, mês a mês (a API pede janelas curtas)
    meses = []
    ini = date(ANO, 1, 1)
    while ini <= HOJE:
        fim = min(HOJE, (date(ini.year + (ini.month == 12), ini.month % 12 + 1, 1) - timedelta(days=1)))
        meses.append((ini, fim))
        ini = fim + timedelta(days=1)
    lidos, falhou = [], False
    with ThreadPoolExecutor(4) as ex:
        for (a, b), r in zip(meses, ex.map(lambda m: listar(*m), meses)):
            lidos += r
    print(f"  PNCP: {len(lidos)} inexigibilidades em MS em {ANO}")
    if not lidos and cache:
        print("  ⚠️ PNCP sem resposta — mantido o anterior")
        falhou = True

    for x in lidos:
        if (x.get("amparoLegal") or {}).get("codigo") != 7:  # art. 74, II: profissional do setor artístico
            continue
        o = x.get("orgaoEntidade") or {}
        if o.get("esferaId") not in ("E", "M"):
            continue
        k = x["numeroControlePNCP"]
        u = x.get("unidadeOrgao") or {}
        antes = cache.get(k) or {}
        cache[k] = {**antes, "id": k, "cnpjOrgao": o.get("cnpj"), "orgao": limpa(o.get("razaoSocial")), "esfera": o.get("esferaId"),
                    "unidade": limpa(u.get("nomeUnidade")), "cidadeOrgao": u.get("municipioNome"), "ano": x.get("anoCompra"),
                    "seq": x.get("sequencialCompra"), "numero": x.get("numeroCompra"), "processo": x.get("processo"),
                    "objeto": limpa(x.get("objetoCompra"))[:600], "complemento": limpa(x.get("informacaoComplementar"))[:600],
                    "publicado": (x.get("dataPublicacaoPncp") or "")[:10], "situacao": x.get("situacaoCompraNome"),
                    "estimado": x.get("valorTotalEstimado"), "homologado": x.get("valorTotalHomologado"),
                    "link": f"https://pncp.gov.br/app/editais/{o.get('cnpj')}/{x.get('anoCompra')}/{x.get('sequencialCompra')}"}

    # empresa contratada: lista de contratos de cada órgão (uma consulta por órgão, não por show); relê os últimos 60 dias
    ate = cache.setdefault("_contratosAte", {})
    orgaos = sorted({c["cnpjOrgao"] for k, c in cache.items() if not k.startswith("_") and c.get("ano") == ANO})

    def ler(cnpj):
        desde = max(date(ANO, 1, 1), date.fromisoformat(ate[cnpj]) - timedelta(days=60)) if ate.get(cnpj, "")[:4] == str(ANO) else date(ANO, 1, 1)
        return cnpj, (contratos_orgao(cnpj, desde) if time.monotonic() - T0 < LIMITE else None)

    n_ok = 0
    with ThreadPoolExecutor(4) as ex:
        for cnpj, ct in ex.map(ler, orgaos):
            if ct is None:
                continue
            n_ok += 1
            ate[cnpj] = HOJE.isoformat()
            for k, emp in ct.items():
                if k in cache:
                    cache[k]["empresas"] = sorted(({**v, "valor": round(v["valor"], 2)} for v in emp.values()), key=lambda v: -v["valor"])
    print(f"  contratos: {n_ok} de {len(orgaos)} órgãos lidos")
    CACHE.write_text(json.dumps(cache, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    itens = []
    for k, c in cache.items():
        if k.startswith("_") or c.get("ano") != ANO:
            continue
        txt = f"{c['objeto']} {c.get('complemento') or ''}"
        valor = c.get("homologado") or c.get("estimado") or 0
        emp = (c.get("empresas") or [None])[0]
        if emp and emp.get("valor") and not c.get("homologado"):
            valor = emp["valor"]
        tipo = "show" if SHOW.search(txt) and not NAO_SHOW.search(c["objeto"]) else "outra"
        art = artista(txt) if tipo == "show" else None
        cid = cidade_show(txt, cidades) or c.get("cidadeOrgao")
        itens.append({"id": c["id"], "orgao": c["orgao"], "esfera": c["esfera"], "unidade": c["unidade"],
                      "cidadeOrgao": c.get("cidadeOrgao"), "cidade": cid, "tipo": tipo, "artista": art,
                      "chaveArtista": chave_artista(art) if art else None, "evento": evento(txt) if tipo == "show" else None,
                      "dataShow": data_show(txt), "publicado": c["publicado"], "valor": round(valor or 0, 2),
                      "homologado": bool(c.get("homologado") or (emp and emp.get("valor"))), "empresa": emp["nome"] if emp else None,
                      "cnpjEmpresa": emp["cnpj"] if emp else None, "objeto": c["objeto"][:400], "link": c["link"]})
    itens.sort(key=lambda x: -x["valor"])
    shows = [x for x in itens if x["tipo"] == "show"]

    # por órgão / cidade (cidade do órgão contratante; o Estado fica à parte)
    por = {}
    for x in shows:
        k = "Governo do Estado de MS" if x["esfera"] == "E" else (x["cidadeOrgao"] or x["orgao"])
        p = por.setdefault(k, {"nome": k, "esfera": x["esfera"], "shows": 0, "valor": 0.0, "orgaos": set()})
        p["shows"] += 1
        p["valor"] += x["valor"]
        p["orgaos"].add(x["orgao"])
    ranking = []
    for p in por.values():
        pop = (pops.get(sem_acento(p["nome"]).lower()) or {}).get("populacao") if p["esfera"] == "M" else None
        ranking.append({"nome": p["nome"], "esfera": p["esfera"], "shows": p["shows"], "valor": round(p["valor"], 2),
                        "orgaos": sorted(p["orgaos"]), "populacao": pop, "porHabitante": round(p["valor"] / pop, 2) if pop else None})
    ranking.sort(key=lambda r: -r["valor"])

    # o mesmo artista pago por mais de um órgão
    art = {}
    for x in shows:
        if x["chaveArtista"] and x["valor"] > 0:
            art.setdefault(x["chaveArtista"], []).append(x)
    repetidos = []
    for k, lst in art.items():
        if len({x["orgao"] for x in lst}) < 2:
            continue
        vals = sorted(x["valor"] for x in lst)
        med = vals[len(vals) // 2] if len(vals) % 2 else (vals[len(vals) // 2 - 1] + vals[len(vals) // 2]) / 2
        repetidos.append({"artista": max((x["artista"] for x in lst), key=lambda a: sum(1 for y in lst if y["artista"] == a)),
                          "chave": k, "contratacoes": len(lst), "total": round(sum(vals), 2), "menor": vals[0], "maior": vals[-1],
                          "mediana": round(med, 2),
                          "lista": [{"orgao": x["orgao"], "cidade": x["cidade"], "valor": x["valor"], "data": x["dataShow"] or x["publicado"],
                                     "evento": x["evento"], "link": x["link"]} for x in sorted(lst, key=lambda y: -y["valor"])]})
    repetidos.sort(key=lambda r: -r["total"])

    if falhou and anterior:
        print("❌ sem dados novos — arquivo mantido")
        sys.exit(1)
    SAIDA.write_text(json.dumps({
        "ano": ANO, "ultimaAtualizacao": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "fonte": "Portal Nacional de Contratações Públicas (PNCP) — inexigibilidades do art. 74, II da Lei 14.133/2021 (profissional do setor artístico) em MS",
        "fonteUrl": "https://pncp.gov.br/",
        "totalShows": len(shows), "valorShows": round(sum(x["valor"] for x in shows), 2),
        "outras": {"quantidade": len(itens) - len(shows), "valor": round(sum(x["valor"] for x in itens if x["tipo"] != "show"), 2)},
        "ranking": ranking, "artistasEmVariosOrgaos": repetidos, "shows": shows,
        "outrasContratacoes": [x for x in itens if x["tipo"] != "show"][:300],
        "_populacoes": pops}, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"✅ shows.json — {len(shows)} shows (R$ {sum(x['valor'] for x in shows):,.0f}), {len(ranking)} órgãos/cidades, "
          f"{sum(1 for x in shows if x['artista'])} com artista identificado, {len(repetidos)} artistas em mais de um órgão")


if __name__ == "__main__":
    main()
