#!/usr/bin/env python3
"""
Cofre Aberto MS — preço unitário pago pelo mesmo item em órgãos diferentes de MS

Fonte: Portal Nacional de Contratações Públicas (PNCP). Para as compras do ano em MS (pregão eletrônico e presencial e
dispensa, Governo do Estado, prefeituras, câmaras e demais órgãos) cujo objeto cita algum item da cesta, lê os itens e,
dos itens da cesta, o resultado homologado: quanto foi pago por unidade e quem venceu.

Cesta (itens comuns, com unidade comparável):
  gasolina comum (litro) · óleo diesel S10 (litro) · etanol (litro) · gás de cozinha GLP 13 kg (botijão/recarga)
  · água mineral em galão de 20 litros · papel A4 (resma de 500 folhas) · café torrado e moído (kg) · açúcar cristal (kg)
  merenda: arroz, feijão, leite UHT, óleo de soja, carne moída, coxa e sobrecoxa · saúde: dipirona e paracetamol 500 mg
  (comprimido), soro fisiológico 500 ml, luva de procedimento (caixa com 100), seringa 5 ml · limpeza: água sanitária (litro),
  detergente (500 ml), copo descartável 200 ml (pacote com 100) · obras: cimento (saco de 50 kg)

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


def _litros(t):
    """volume em litros escrito no texto: '900 ml', '1 litro', '2l', '5 lts'"""
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*(ml|mililitros|l|lt|lts|litro|litros)\b", t)
    if not m:
        return None
    q = float(m.group(1).replace(",", "."))
    q = q / 1000 if m.group(2) in ("ml", "mililitros") else q
    return q if 0.05 <= q <= 20 else None


def volume(ref):
    """preço por embalagem de `ref` litros (1 = por litro): usa o volume da unidade ou da descrição."""
    def f(desc, unid, preco):
        q = _litros(unid) or (None if re.search(r"caixa|\bcx\b|fardo|pacote|\bpct\b|\bfd\b", unid) else _litros(desc))
        if not q and re.search(r"\blitro|\blt\b|^l$|\bl\b|litros", unid):
            q = 1
        return preco / q * ref if q else None
    return f


def por_unidade_avulsa(desc, unid, preco):
    """comprimido, bolsa, seringa, saco: só quando a unidade é a peça (não caixa nem pacote)"""
    return None if re.search(r"caixa|\bcx\b|pacote|\bpct\b|blister|cartela|fardo|frasco com|\bc/\s*\d", unid) else preco


def luva_caixa(desc, unid, preco):
    if re.search(r"caixa|\bcx\b", unid) and re.search(r"\b100\b", desc + " " + unid):
        return preco
    if re.search(r"\bpar\b|pares", unid):
        return preco * 50
    return None


def copo_pacote(desc, unid, preco):
    if re.search(r"pacote|\bpct\b|\bpc\b|\bpt\b", unid) and re.search(r"\b100\b", desc + " " + unid):
        return preco
    if re.search(r"caixa|\bcx\b", unid) and re.search(r"2\.?500", desc + " " + unid):
        return preco / 25
    return None


CESTA = {
    "gasolina": ("Gasolina comum", "litro", r"combust|gasolina", r"gasolina\s*(comum|c\b|tipo c)", r"aditivada|premium|podium|aviac", por_litro),
    "diesel": ("Óleo diesel S10", "litro", r"combust|diesel", r"diesel.{0,15}s[\s-]?10", r"arla|lubrific|motor 2t|gerenciamento|cartao|administra|frota", por_litro),
    "etanol": ("Etanol", "litro", r"combust|etanol|alcool", r"etanol|alcool (etilico )?hidratado comb", r"gel|70|46|limpeza|aditivad|gerenciamento|cartao|frota", por_litro),
    "glp": ("Gás de cozinha (botijão 13 kg)", "botijão", r"gas|glp", r"(glp|gas liquefeito|gas de cozinha).{0,40}13\s*kg|13\s*kg.{0,40}(glp|gas)", r"vasilhame|casco|botijao vazio|45\s*kg|20\s*kg|p-?45|regulador|mangueira|\bkit\b|registro|abracadeira", por_unid),
    "agua20": ("Água mineral (galão 20 litros)", "galão", r"agua", r"agua mineral.{0,40}20\s*(l|litros)", r"vasilhame|casco|garrafao vazio|500\s*ml|1,5|copo", por_unid),
    "papelA4": ("Papel A4 (resma de 500 folhas)", "resma", r"papel|expediente|escritorio", r"papel.{0,30}a4", r"fotogr|adesiv|vergê|verge|cartao|colorido|reciclad|couche|180\s*g|100 folhas|250 folhas", None),
    "cafe": ("Café torrado e moído (kg)", "kg", r"cafe|genero|aliment|copa|cozinha", r"cafe.{0,25}(torrado|moido|po)", r"capsul|soluvel|filtro|garrafa|maquina|xicara", por_kg),
    "acucar": ("Açúcar cristal (kg)", "kg", r"acucar|genero|aliment|copa|cozinha", r"acucar.{0,15}cristal", r"refinado|mascavo|demerara|sache|confeit", por_kg),
    # merenda e copa
    "arroz": ("Arroz branco tipo 1 (kg)", "kg", r"arroz|genero|aliment|merenda", r"^[\W\d]*arroz\b.{0,40}(tipo\s*1|branco|agulh|polido)", r"integral|parboiliz|arboreo|farinha|biscoito|doce|pronto|cozido|flocos|creme", por_kg),
    "feijao": ("Feijão carioca (kg)", "kg", r"feijao|genero|aliment|merenda", r"^[\W\d]*feijao.{0,20}carioc", r"enlatad|cozido|pronto|feijoada|farinha", por_kg),
    "leite": ("Leite UHT integral (litro)", "litro", r"leite|genero|aliment|merenda", r"^[\W\d]*leite.{0,40}(uht|longa vida).{0,40}integral|^\W*leite.{0,20}integral.{0,40}(uht|longa vida)", r"\bpo\b|condensad|ferment|achocolat|soja|lactose|creme|desnatad|semidesnatad|cabra", volume(1)),
    "oleo": ("Óleo de soja (litro)", "litro", r"oleo|genero|aliment|merenda", r"^[\W\d]*oleo.{0,20}soja", r"lubrific|motor|hidraul|diesel|composto|spray", volume(1)),
    "carne": ("Carne bovina moída (kg)", "kg", r"carne|genero|aliment|merenda|acougue|proteina", r"carne.{0,30}(bovina)?.{0,20}moida", r"frango|suina|peixe|soja|enlatad|hamburg|almondeg", por_kg),
    "frango": ("Frango, coxa e sobrecoxa (kg)", "kg", r"frango|genero|aliment|merenda|acougue|proteina", r"coxa.{0,6}(e|/|com).{0,6}sobrecoxa", r"empanad|temperad|defumad|desossad|file|assad", por_kg),
    # saúde
    "dipirona": ("Dipirona 500 mg (comprimido)", "comprimido", r"medicament|farmac|dipirona", r"dipirona.{0,40}500\s*mg.{0,60}(comp|\bcp\b|cpr)", r"gota|solu|injet|ampola|\bml\b|xarope|supositor|1\s*g\b", por_unidade_avulsa),
    "paracetamol": ("Paracetamol 500 mg (comprimido)", "comprimido", r"medicament|farmac|paracetamol", r"paracetamol.{0,40}500\s*mg.{0,60}(comp|\bcp\b|cpr)", r"gota|solu|injet|\bml\b|xarope|codeina|cafeina|750|associad", por_unidade_avulsa),
    "soro": ("Soro fisiológico 0,9% (bolsa 500 ml)", "bolsa", r"medicament|farmac|hospitalar|soro|solu", r"(cloreto de sodio|soro fisiolog).{0,40}0[,.]9.{0,60}500\s*ml|500\s*ml.{0,60}(cloreto de sodio|soro fisiolog).{0,40}0[,.]9", r"\b250\b|\b100\s*ml|1000|ampola|\b10\s*ml|nasal|spray|20%|glicos|ringer", por_unidade_avulsa),
    "luva": ("Luva de procedimento (caixa com 100)", "caixa", r"luva|hospitalar|medic|enfermag|odontolog|epi|protecao", r"luva.{0,40}procediment", r"estéril|esteril|cirurg|nitril|vinil|plastic|domestic|latex natural sem po.{0,5}esteril", luva_caixa),
    "seringa": ("Seringa descartável 5 ml (unidade)", "unidade", r"seringa|hospitalar|medic|enfermag", r"seringa.{0,40}\b5\s*ml", r"insulina|\b10\s*ml|\b20\s*ml|\b1\s*ml|\b3\s*ml|\b60\s*ml|vidro|carpule|odontol", por_unidade_avulsa),
    # limpeza
    "sanitaria": ("Água sanitária (litro)", "litro", r"limpeza|higien|sanitaria|saneantes", r"agua sanitaria", r"gel|perfum|tablete|pastilha", volume(1)),
    "detergente": ("Detergente líquido (500 ml)", "frasco 500 ml", r"limpeza|higien|detergente|saneantes", r"^[\W\d]*detergente.{0,40}(liquido|neutro|lava.?louc)", r"enzimat|industrial|automotiv|clorad|desincrust|maquina|alcalin|\bpo\b|gel|concentrad", volume(0.5)),
    "copo": ("Copo descartável 200 ml (pacote com 100)", "pacote", r"descart|copa|cozinha|limpeza|higien|copo", r"copo.{0,20}descart.{0,60}(200|180)\s*ml", r"papel|\bcafe\b|\b50\s*ml|\b80\s*ml|biodegrad|tampa|\b300\s*ml|\b500\s*ml|acrilic", copo_pacote),
    # obras
    "cimento": ("Cimento (saco de 50 kg)", "saco", r"cimento|construc|alvenar|pedreir|obra|reforma", r"^[\W\d]*cimento.{0,60}50\s*kg", r"cola|branco|argamassa|cimentici|refratar|aditivo|cal\b|telha|bloco|tubo", por_unidade_avulsa),
}
VERSAO_CESTA = 2  # sobe quando entram itens novos: as compras já lidas são relidas
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
    pend = [c for k, c in alvo.items() if k not in cache] + [c for k, c in alvo.items() if k in cache and (cache[k].get("v") or 1) < VERSAO_CESTA]
    print(f"  PNCP: {len(lidos)} compras em MS em {ANO}; {len(alvo)} com objeto da cesta; {len(pend)} para ler")

    def ler(c):
        return c, (itens_da_compra(c) if time.monotonic() - T0 < LIMITE else None)

    with ThreadPoolExecutor(5) as ex:
        for c, its in ex.map(ler, pend):
            if its is not None:
                cache[c["id"]] = {**c, "itens": its, "v": VERSAO_CESTA}
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
