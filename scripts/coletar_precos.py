#!/usr/bin/env python3
"""
Cofre Aberto MS — preço unitário pago pelo mesmo item em órgãos diferentes de MS

Fonte: Portal Nacional de Contratações Públicas (PNCP). Para as compras do ano em MS (pregão eletrônico e presencial e
dispensa, Governo do Estado, prefeituras, câmaras e demais órgãos) cujo objeto cita algum item da cesta, lê os itens e,
dos itens da cesta, o resultado homologado: quanto foi pago por unidade e quem venceu.

Cesta (itens comuns, com unidade comparável):
  gasolina comum (litro) · óleo diesel S10 (litro) · etanol (litro) · gás de cozinha GLP 13 kg (botijão/recarga)
  · água mineral em galão de 20 litros · papel A4 (resma de 500 folhas) · café torrado e moído (kg) · açúcar cristal (kg)

Preço por unidade comparável: o valor unitário homologado, convertido para kg quando a embalagem informa o peso
(ex.: café 500 g → preço × 2). Itens sem unidade clara ficam de fora.

Gera dados/precos.json; cache em dados/precos_cache.json.
"""

import json, re, statistics, sys, time, unicodedata
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from pathlib import Path

import requests

DADOS = Path(__file__).parent.parent / "dados"
SAIDA, CACHE = DADOS / "precos.json", DADOS / "precos_cache.json"
API = "https://pncp.gov.br/api"
H = {"User-Agent": "Mozilla/5.0 (CofreAbertoMS; +https://cofreabertoms.com.br)"}
HOJE = date.today()
ANO = HOJE.year
T0 = time.monotonic()
LIMITE = 14 * 60


def sa(t):
    return "".join(c for c in unicodedata.normalize("NFD", (t or "").lower()) if unicodedata.category(c) != "Mn")


# produto: (regex no objeto da compra, regex na descrição do item, regex que exclui, unidade, função de normalização)
def por_kg(desc, unid, preco):
    m = re.search(r"(\d+(?:[.,]\d+)?)[\s-]*(kg|quilo|g|gr|gramas)", unid.replace("quilograma", "kg")) or re.search(r"(\d+(?:[.,]\d+)?)\s*(kg|quilo|g|gr|gramas)\b", desc)
    if not m:
        return preco if re.search(r"\bkg\b|quilo", unid) else None
    q = float(m.group(1).replace(",", "."))
    q = q if m.group(2) in ("kg", "quilo") else q / 1000
    if q > 50:  # "Emb 1000 g" já tratado; número alto sem unidade de peso clara: não converte
        return None
    return preco / q if q else None


def por_litro(desc, unid, preco):
    return preco if re.search(r"\blitro|\blt\b|^l$|\bl\b|litros", unid) else None


def por_unid(desc, unid, preco):
    return preco


CESTA = {
    "gasolina": ("Gasolina comum", "litro", r"combust|gasolina", r"gasolina\s*(comum|c\b|tipo c)", r"aditivada|premium|podium|aviac", por_litro),
    "diesel": ("Óleo diesel S10", "litro", r"combust|diesel", r"diesel.{0,15}s[\s-]?10", r"arla|lubrific|motor 2t|gerenciamento|cartao|administra|frota", por_litro),
    "etanol": ("Etanol", "litro", r"combust|etanol|alcool", r"etanol|alcool (etilico )?hidratado comb", r"gel|70|46|limpeza|aditivad|gerenciamento|cartao|frota", por_litro),
    "glp": ("Gás de cozinha (botijão 13 kg)", "botijão", r"gas|glp", r"(glp|gas liquefeito|gas de cozinha).{0,40}13\s*kg|13\s*kg.{0,40}(glp|gas)", r"vasilhame|casco|botijao vazio|45\s*kg|20\s*kg|p-?45|regulador|mangueira|\bkit\b|registro|abracadeira", por_unid),
    "agua20": ("Água mineral (galão 20 litros)", "galão", r"agua", r"agua mineral.{0,40}20\s*(l|litros)", r"vasilhame|casco|garrafao vazio|500\s*ml|1,5|copo", por_unid),
    "papelA4": ("Papel A4 (resma de 500 folhas)", "resma", r"papel|expediente|escritorio", r"papel.{0,30}a4", r"fotogr|adesiv|vergê|verge|cartao|colorido|reciclad|couche|180\s*g|100 folhas|250 folhas", None),
    "cafe": ("Café torrado e moído (kg)", "kg", r"cafe|genero|aliment|copa|cozinha", r"cafe.{0,25}(torrado|moido|po)", r"capsul|soluvel|filtro|garrafa|maquina|xicara", por_kg),
    "acucar": ("Açúcar cristal (kg)", "kg", r"acucar|genero|aliment|copa|cozinha", r"acucar.{0,15}cristal", r"refinado|mascavo|demerara|sache|confeit", por_kg),
}
OBJETO_ALGUM = re.compile("|".join(v[2] for v in CESTA.values()), re.I)


def papel_resma(desc, unid, preco):
    if re.search(r"resma|\brm\b|\brs\b", unid) or re.search(r"resma", desc):
        if re.search(r"caixa|cx|\bc/\s*10|10 resmas", unid):
            return preco / 10
        return preco
    if re.search(r"caixa|cx", unid) and re.search(r"10 resmas|5000 folhas|5\.000 folhas", desc):
        return preco / 10
    return None


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


def itens_da_compra(c):
    """[{produto, descricao, unidade, quantidade, preco, precoUnidade, fornecedor, cnpjFornecedor}] dos itens da cesta."""
    base = f"{API}/pncp/v1/orgaos/{c['cnpj']}/compras/{c['ano']}/{c['seq']}"
    itens, p = [], 1
    while time.monotonic() - T0 < LIMITE:
        d = get(f"{base}/itens", {"pagina": p, "tamanhoPagina": 500})
        if not d:
            break
        itens += d
        if len(d) < 500:
            break
        p += 1
    out = []
    for it in itens:
        desc = sa(it.get("descricao"))
        unid = sa(it.get("unidadeMedida"))
        for k, (nome, un, _, rx, nao, fn) in CESTA.items():
            if not re.search(rx, desc) or re.search(nao, desc):
                continue
            if not it.get("temResultado"):
                break
            for r in get(f"{base}/itens/{it['numeroItem']}/resultados") or []:
                pu = r.get("valorUnitarioHomologado") or 0
                if not pu:
                    continue
                f = papel_resma if k == "papelA4" else fn
                pn = f(desc, unid, pu)
                if pn:
                    out.append({"produto": k, "descricao": (it.get("descricao") or "")[:160], "unidade": it.get("unidadeMedida"),
                                "quantidade": r.get("quantidadeHomologada") or it.get("quantidade"), "preco": round(pu, 4), "precoUnidade": round(pn, 4),
                                "fornecedor": (r.get("nomeRazaoSocialFornecedor") or "").strip(), "cnpjFornecedor": r.get("niFornecedor")})
            break
    return out


def main():
    try:
        cache = json.load(open(CACHE, encoding="utf-8"))
    except Exception:
        cache = {}
    if "--so-saida" in sys.argv:  # só remonta precos.json a partir do cache (sem consultar o PNCP)
        return montar(cache)
    meses, ini = [], date(ANO, 1, 1)
    while ini <= HOJE:
        fim = min(HOJE, date(ini.year + (ini.month == 12), ini.month % 12 + 1, 1) - timedelta(days=1))
        meses.append((ini, fim))
        ini = fim + timedelta(days=1)
    lidos = []
    with ThreadPoolExecutor(4) as ex:
        for r in ex.map(lambda a: listar(*a), [(i, f, m) for i, f in meses for m in (6, 7, 8)]):
            lidos += r
    alvo = {}
    for x in lidos:
        o = x.get("orgaoEntidade") or {}
        if not OBJETO_ALGUM.search(sa(x.get("objetoCompra"))) or not x.get("valorTotalHomologado"):
            continue
        k = x["numeroControlePNCP"]
        u = x.get("unidadeOrgao") or {}
        alvo[k] = {"id": k, "cnpj": o.get("cnpj"), "orgao": (o.get("razaoSocial") or "").strip(), "esfera": o.get("esferaId"),
                   "cidade": u.get("municipioNome"), "ano": x.get("anoCompra"), "seq": x.get("sequencialCompra"),
                   "modalidade": x.get("modalidadeNome"), "data": (x.get("dataPublicacaoPncp") or "")[:10],
                   "objeto": (x.get("objetoCompra") or "")[:240],
                   "link": f"https://pncp.gov.br/app/editais/{o.get('cnpj')}/{x.get('anoCompra')}/{x.get('sequencialCompra')}"}
    pend = [c for k, c in alvo.items() if k not in cache]
    print(f"  PNCP: {len(lidos)} compras em MS em {ANO}; {len(alvo)} com objeto da cesta; {len(pend)} para ler")

    def ler(c):
        return c, (itens_da_compra(c) if time.monotonic() - T0 < LIMITE else None)

    with ThreadPoolExecutor(5) as ex:
        for c, its in ex.map(ler, pend):
            if its is not None:
                cache[c["id"]] = {**c, "itens": its}
    if time.monotonic() - T0 > LIMITE:
        print("  ⚠️ tempo esgotado — o que faltou fica para a próxima coleta")
    CACHE.write_text(json.dumps(cache, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    montar(cache)


def montar(cache):
    produtos = {}
    for c in cache.values():
        if str(c.get("ano")) != str(ANO):
            continue
        for it in c.get("itens") or []:
            k = it["produto"]
            d_, u_ = sa(it.get("descricao")), sa(it.get("unidade"))
            if re.search(CESTA[k][4], d_):
                continue
            if CESTA[k][5] is por_kg and re.search(r"\d[\s-]*(kg|quilo|g\b|gr\b|gramas)", u_):  # peso na unidade (ex.: "Emb 2 Kg")
                it = {**it, "precoUnidade": round(por_kg(d_, u_, it["preco"]), 4)}
            produtos.setdefault(it["produto"], []).append({**it, "orgao": c["orgao"], "esfera": c["esfera"], "cidade": c["cidade"],
                                                           "data": c["data"], "modalidade": c["modalidade"], "link": c["link"]})
    saida = []
    for k, lst in produtos.items():
        nome, un = CESTA[k][0], CESTA[k][1]
        vals = sorted(x["precoUnidade"] for x in lst)
        if len(vals) < 3:
            continue
        med = statistics.median(vals)
        lst = [x for x in lst if med / 4 <= x["precoUnidade"] <= med * 4]  # descarta erro grosseiro de unidade
        vals = sorted(x["precoUnidade"] for x in lst)
        med = statistics.median(vals)
        for x in lst:
            x["vsMediana"] = round((x["precoUnidade"] / med - 1) * 100, 1)
        saida.append({"produto": k, "nome": nome, "unidade": un, "compras": len(lst), "mediana": round(med, 2), "menor": round(vals[0], 2),
                      "maior": round(vals[-1], 2), "orgaos": len({x["orgao"] for x in lst}),
                      "itens": sorted(lst, key=lambda x: -x["precoUnidade"])})
    saida.sort(key=lambda p: -p["compras"])
    SAIDA.write_text(json.dumps({"ano": ANO, "ultimaAtualizacao": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
                                 "fonte": "Portal Nacional de Contratações Públicas (PNCP) — itens e resultados homologados de compras de órgãos de MS",
                                 "fonteUrl": "https://pncp.gov.br/", "produtos": saida}, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"✅ precos.json — " + ", ".join(f"{p['nome']}: {p['compras']} preços, mediana R$ {p['mediana']}" for p in saida))


if __name__ == "__main__":
    main()
