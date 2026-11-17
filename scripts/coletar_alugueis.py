#!/usr/bin/env python3
"""
Cofre Aberto MS — aluguel de imóveis pagos com dinheiro público em MS, e quem é o dono

  Prefeitura de CG   pagamentos do ano nas categorias "10 - Locação de imóveis" (pessoa jurídica) e "15 - Locação de imóveis"
                     (pessoa física), dados/prefeitura.json — por locador, por órgão, com o link de cada empenho
  Estado e interior  contratações de aluguel de imóvel publicadas no PNCP pelos órgãos de MS no ano: inexigibilidade do
                     art. 74, V da Lei 14.133 (amparo 17) ou dispensa/inexigibilidade cujo objeto é locação de imóvel. O
                     locador sai do resultado homologado da compra.

Ligação política (pelo nome e pelos 6 dígitos do meio do CPF, como o TSE publica):
  - locador pessoa física que doou para campanha de político de MS (dados/tse_campanhas.json)
  - sócio da empresa locadora (cadastro da Receita, dados/cnpj_cache.json) que doou para campanha
  - sinais da auditoria do site sobre a empresa locadora (dados/auditoria.json)
O CPF do locador pessoa física não é publicado, só o nome. Ligação é sinal de atenção, não prova de irregularidade:
alugar imóvel de doador é permitido, mas merece explicação sobre preço e escolha do imóvel.

Gera dados/alugueis.json; cache das compras do PNCP em dados/alugueis_cache.json.
"""

import json, re, time, unicodedata
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from pathlib import Path

import requests

DADOS = Path(__file__).parent.parent / "dados"
SAIDA, CACHE = DADOS / "alugueis.json", DADOS / "alugueis_cache.json"
API = "https://pncp.gov.br/api"
H = {"User-Agent": "Mozilla/5.0 (CofreAbertoMS; +https://cofreabertoms.com.br)"}
HOJE = date.today()
ANO = HOJE.year
T0 = time.monotonic()
LIMITE = 12 * 60
LOCACAO = re.compile(r"loca[cç][aã]o.{0,60}(im[oó]ve|pr[eé]dio|sala|galp[aã]o|casa|edif[ií]cio|espa[cç]o f[ií]sico|terreno)|aluguel.{0,30}(im[oó]ve|pr[eé]dio|sala|casa|galp)", re.I)
NAO = re.compile(r"ve[ií]culo|m[aá]quina|equipamento|software|caminh|[oô]nibus|tenda|palco|banheiro qu[ií]mico|container|cont[eê]iner", re.I)


def sa(t):
    return re.sub(r"\s+", " ", "".join(c for c in unicodedata.normalize("NFD", (t or "").upper()) if unicodedata.category(c) != "Mn")).strip()


def dig(t):
    return re.sub(r"\D", "", str(t or ""))


def carregar(nome):
    try:
        return json.load(open(DADOS / nome, encoding="utf-8"))
    except Exception:
        return {}


def get(url, params=None, tent=4):
    for t in range(tent):
        if time.monotonic() - T0 > LIMITE + 60:
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


def cpf_doc(doc):
    """CPF (11 dígitos) de um documento que pode vir com zeros à esquerda até 14; o CPF mascarado (***.123.456-**)
    volta como "000" + os 6 dígitos do meio + "00", o que basta para o cruzamento (cpf6)."""
    if re.fullmatch(r"\*{3}\.\d{3}\.\d{3}-\*{2}", str(doc or "").strip()):
        return "000" + dig(doc) + "00"
    d = dig(doc)
    if len(d) == 14 and d.startswith("000"):
        return d[3:]
    return d if len(d) == 11 else None


def cpf6(cpf):
    return cpf[3:9] if cpf and len(cpf) == 11 else None


# ── ligação política ──
def indice_doadores():
    """(nome normalizado, cpf6) → [políticos que receberam], pelo TSE."""
    idx = {}
    for chave, p in (carregar("tse_campanhas.json").get("parlamentares") or {}).items():
        quem = (p.get("urna") or chave.split("|")[-1]).title()
        cargo = p.get("cargo") or ""
        for nome_n, (nome, valor, c6, anos) in (p.get("doadores") or {}).items():
            idx.setdefault((sa(nome_n), c6), []).append({"politico": quem, "cargo": cargo, "valor": valor, "anos": anos})
    return idx


def vinculos_pf(nome, cpf, doadores):
    out = []
    for d in doadores.get((sa(nome), cpf6(cpf)), []):
        out.append({"tipo": "doador", "texto": f"doou {brl(d['valor'])} para a campanha de {d['politico']} ({d['cargo'].lower()}, {', '.join(map(str, d['anos']))})"})
    return out


def vinculos_pj(cnpj, cad, doadores, sinais):
    out = []
    for s in (cad.get(cnpj) or {}).get("socios") or []:
        for d in doadores.get((sa(s.get("nome")), s.get("cpf")), []):
            out.append({"tipo": "socio_doador", "texto": f"o sócio ou dirigente {s['nome'].title()} doou {brl(d['valor'])} para a campanha de {d['politico']} ({d['cargo'].lower()}, {', '.join(map(str, d['anos']))})"})
    for r in sinais.get(cnpj, []):
        out.append({"tipo": "auditoria", "texto": f"sinal da auditoria: {r}"})
    return out


def brl(v):
    return "R$ " + f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


# ── PNCP ──
def listar(ini, fim, mod):
    out, p = [], 1
    while True:
        d = get(f"{API}/consulta/v1/contratacoes/publicacao", {"dataInicial": ini.strftime("%Y%m%d"), "dataFinal": fim.strftime("%Y%m%d"),
                                                               "codigoModalidadeContratacao": mod, "uf": "MS", "pagina": p, "tamanhoPagina": 50})
        if not d:
            break
        out += d.get("data") or []
        if p >= (d.get("totalPaginas") or 1):
            break
        p += 1
    return out


def locador(c):
    base = f"{API}/pncp/v1/orgaos/{c['cnpj']}/compras/{c['ano']}/{c['seq']}"
    its = get(f"{base}/itens", {"pagina": 1, "tamanhoPagina": 20}) or []
    for it in its[:3]:
        for r in get(f"{base}/itens/{it['numeroItem']}/resultados") or []:
            if r.get("niFornecedor"):
                return {"nome": (r.get("nomeRazaoSocialFornecedor") or "").strip(), "doc": dig(r.get("niFornecedor")),
                        "valor": r.get("valorTotalHomologado")}
    return {}


def pncp(cache):
    meses, ini = [], date(ANO, 1, 1)
    while ini <= HOJE:
        fim = min(HOJE, date(ini.year + (ini.month == 12), ini.month % 12 + 1, 1) - timedelta(days=1))
        meses.append((ini, fim))
        ini = fim + timedelta(days=1)
    lidos = []
    with ThreadPoolExecutor(4) as ex:
        for r in ex.map(lambda a: listar(*a), [(i, f, m) for i, f in meses for m in (8, 9)]):
            lidos += r
    alvo = {}
    for x in lidos:
        amp = (x.get("amparoLegal") or {}).get("codigo")
        obj = x.get("objetoCompra") or ""
        if not (amp == 17 or (LOCACAO.search(obj) and not NAO.search(obj))):
            continue
        o, u = x.get("orgaoEntidade") or {}, x.get("unidadeOrgao") or {}
        k = x["numeroControlePNCP"]
        alvo[k] = {"id": k, "cnpj": o.get("cnpj"), "orgao": (o.get("razaoSocial") or "").strip(), "esfera": o.get("esferaId"),
                   "cidade": u.get("municipioNome"), "ano": x.get("anoCompra"), "seq": x.get("sequencialCompra"),
                   "objeto": re.sub(r"\s+", " ", obj).strip()[:400], "data": (x.get("dataPublicacaoPncp") or "")[:10],
                   "valor": x.get("valorTotalHomologado") or x.get("valorTotalEstimado") or 0, "homologado": bool(x.get("valorTotalHomologado")),
                   "amparo": (x.get("amparoLegal") or {}).get("nome"),
                   "link": f"https://pncp.gov.br/app/editais/{o.get('cnpj')}/{x.get('anoCompra')}/{x.get('sequencialCompra')}"}
    pend = [c for k, c in alvo.items() if k not in cache or (not cache[k].get("locador") and cache[k].get("lido") != HOJE.isoformat())]
    print(f"  PNCP: {len(lidos)} dispensas e inexigibilidades em MS; {len(alvo)} de aluguel de imóvel; {len(pend)} para ler o locador")

    def ler(c):
        return c, (locador(c) if time.monotonic() - T0 < LIMITE else None)
    with ThreadPoolExecutor(5) as ex:
        for c, loc in ex.map(ler, pend):
            if loc is not None:
                cache[c["id"]] = {"locador": loc, "lido": HOJE.isoformat()}
    return [{**c, "locador": (cache.get(k) or {}).get("locador") or {}} for k, c in alvo.items()]


def main():
    cache = carregar("alugueis_cache.json")
    cad = carregar("cnpj_cache.json")
    doadores = indice_doadores()
    sinais = {}
    for s in carregar("auditoria.json").get("sinais") or []:
        if s.get("cnpj") and s.get("rotulo"):
            sinais.setdefault(dig(s["cnpj"]), set()).add(s["rotulo"])
    sinais = {k: sorted(v) for k, v in sinais.items()}
    paginas = carregar("empresas_index.json") or {}

    def identifica(nome, doc):
        cpf = cpf_doc(doc)
        if cpf:
            return {"nome": re.sub(r"\s+", " ", nome or "").strip().title(), "tipo": "PF", "doc": None, "pagina": None,
                    "vinculos": vinculos_pf(nome, cpf, doadores)}
        d = dig(doc)
        return {"nome": re.sub(r"\s+", " ", nome or "").strip(), "tipo": "PJ", "doc": d or None,
                "pagina": f"/empresa/{d[:8]}/" if d[:8] in paginas else None, "vinculos": vinculos_pj(d, cad, doadores, sinais) if d else []}

    # Prefeitura de CG
    pref = carregar("prefeitura.json")
    pag = [r for r in pref.get("despesas") or [] if re.search(r"LOCA[CÇ][AÃ]O DE IM[OÓ]VEIS", (r.get("categoria") or "").upper())]
    loc = {}
    for r in pag:
        k = dig(r.get("cnpj")) or r.get("fornecedor")
        a = loc.get(k)
        if not a:
            a = loc[k] = {**identifica(r.get("fornecedor"), r.get("cnpj")), "valor": 0.0, "orgaos": {}, "pagamentos": []}
        v = float(r.get("valor") or 0)
        a["valor"] += v
        a["orgaos"][r.get("orgao") or "—"] = a["orgaos"].get(r.get("orgao") or "—", 0) + v
        a["pagamentos"].append({"data": r.get("data"), "orgao": r.get("orgao"), "valor": round(v, 2), "url": r.get("urlDetalhe")})
    lista_pref = []
    for a in loc.values():
        a["valor"] = round(a["valor"], 2)
        a["orgaos"] = sorted(([o, round(v, 2)] for o, v in a["orgaos"].items()), key=lambda t: -t[1])
        a["pagamentos"].sort(key=lambda p: p["data"] or "", reverse=True)
        lista_pref.append(a)
    lista_pref.sort(key=lambda a: -a["valor"])
    por_orgao = {}
    for r in pag:
        por_orgao[r.get("orgao") or "—"] = por_orgao.get(r.get("orgao") or "—", 0) + float(r.get("valor") or 0)
    datas = sorted(r.get("data") for r in pag if r.get("data"))

    # Estado e interior (PNCP)
    contr = pncp(cache)
    CACHE.write_text(json.dumps(cache, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    for c in contr:
        l = c.pop("locador") or {}
        c["locador"] = identifica(l.get("nome"), l.get("doc")) if l.get("nome") else None
    contr.sort(key=lambda c: -(c["valor"] or 0))
    est = [c for c in contr if c["esfera"] == "E"]
    mun = [c for c in contr if c["esfera"] == "M"]
    por_cidade = {}
    for c in mun:
        a = por_cidade.setdefault(c["cidade"] or "—", {"cidade": c["cidade"] or "—", "contratos": 0, "valor": 0.0})
        a["contratos"] += 1
        a["valor"] += c["valor"] or 0
    com_vinc = [a for a in lista_pref if a["vinculos"]] + [c for c in contr if c["locador"] and c["locador"]["vinculos"]]

    SAIDA.write_text(json.dumps({
        "ano": ANO, "ultimaAtualizacao": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "prefeitura": {"total": round(sum(a["valor"] for a in lista_pref), 2), "pagamentos": len(pag), "locadores": len(lista_pref),
                       "ate": datas[-1] if datas else None, "coleta": pref.get("ultimaAtualizacao"),
                       "fonte": "SIG-Transparência da Prefeitura de Campo Grande — despesas nas categorias de locação de imóveis",
                       "porOrgao": sorted(([o, round(v, 2)] for o, v in por_orgao.items()), key=lambda t: -t[1]), "lista": lista_pref},
        "pncp": {"fonte": "Portal Nacional de Contratações Públicas (PNCP) — dispensas e inexigibilidades de aluguel de imóvel de órgãos de MS",
                 "fonteUrl": "https://pncp.gov.br/", "total": round(sum(c["valor"] or 0 for c in contr), 2), "contratacoes": len(contr),
                 "estado": {"total": round(sum(c["valor"] or 0 for c in est), 2), "contratacoes": len(est)},
                 "municipios": {"total": round(sum(c["valor"] or 0 for c in mun), 2), "contratacoes": len(mun)},
                 "porCidade": sorted(({**a, "valor": round(a["valor"], 2)} for a in por_cidade.values()), key=lambda a: -a["valor"]),
                 "lista": contr},
        "comVinculo": len(com_vinc)}, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"✅ alugueis.json — Prefeitura de CG {brl(sum(a['valor'] for a in lista_pref))} a {len(lista_pref)} locadores; "
          f"PNCP {len(contr)} contratações ({brl(sum(c['valor'] or 0 for c in contr))}); {len(com_vinc)} com ligação política ou sinal")


if __name__ == "__main__":
    main()
