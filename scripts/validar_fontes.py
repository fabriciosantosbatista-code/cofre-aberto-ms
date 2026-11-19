#!/usr/bin/env python3
"""
Cofre Aberto MS — conferência dos dados do site direto na fonte oficial (independente da coleta)

Cada conferência consulta a fonte oficial de novo, por um caminho próprio, e compara com o que o site publica.
Só a fonte que passa aqui pode ser chamada de "verificada na fonte". Somas internas fechando (tests/) é outra coisa:
é consistência matemática, não prova de que o número é o da fonte.

  governo-ms           portal do Estado (consulta anônima): pago e empenhado do ano
  deputados-estaduais  portal da ALEMS (/ceap/data): total de cada um dos 25 deputados
  senadores            Senado (adm-dadosabertos despesas_ceaps): total de cada senador de MS
  deputados            API da Câmara: total de cada deputado federal de MS (valor líquido com o sinal corrigido)
  arrecadacao          Tesouro/Siconfi RREO Anexo 3: ICMS do Estado, todos os meses da série
  supersalarios        órgão por órgão: TJMS e TRT24 (DadosJusBr), 39 órgãos do Governo (folha filtrada por órgão), TCE-MS
                       servidores (portal do TCE); mais 100 contracheques do Governo sorteados por dia
  shows                PNCP: todas as contratações de show, valor homologado/estimado de cada uma
  alugueis             PNCP: todas as contratações de aluguel, valor homologado/estimado de cada uma
  votacoes             API da Câmara (/votacoes/{id}/votos): todas as votações nominais do ano, o voto de cada deputado de MS
  producao             Câmara (/proposicoes com filtro de tipo) e Senado (/processo): nº de projetos de cada parlamentar de MS
  judiciario           DadosJusBr (contracheques do TJMS enviados ao CNJ): nº de magistrados e soma do subsídio do mês
  entidades            cadastro CNPJ (minhareceita.org, serviço diferente do usado na coleta): todas as entidades —
                       data de abertura, município e situação cadastral

Tolerância: diferença até R$ 1 por item, ou explicada por atualização da fonte depois da coleta (a fonte mudou entre
a coleta e a conferência — registrada como "mudou na fonte", não como divergência).
Grava dados/validacao_fontes.json. Uma fonte fora do ar fica "indisponível" (nunca "confere").
"""

import json, os, random, re, sys, time, unicodedata
from datetime import date, datetime
from pathlib import Path

import re as _re
PASSAGEM = _re.compile(r"SIGEPA|PASSAGE[MN]S? A[EÉ]REA - RPA", _re.I)  # na API da Câmara só estas não vêm com o sinal invertido (o reembolso de passagem vem)

import requests

sys.path.insert(0, str(Path(__file__).parent))
DADOS = Path(__file__).parent.parent / "dados"
SAIDA = DADOS / "validacao_fontes.json"
HISTORICO = DADOS / "icp_verificacoes.jsonl"  # histórico PERMANENTE: uma linha por conferência, só acrescenta (nunca reescreve)
H = {"User-Agent": "Mozilla/5.0 (CofreAbertoMS; +https://cofreabertoms.com.br)", "Accept": "application/json"}
from zoneinfo import ZoneInfo
FUSO = ZoneInfo("America/Campo_Grande")  # todos os horários do ICP no horário de Campo Grande (o robô e as execuções manuais)
AGORA = datetime.now(FUSO).strftime("%Y-%m-%dT%H:%M:%S")


import hashlib as _hl


# campos que a conferência compara com a fonte, por base: se algum deles mudar no site, a conferência anterior deixa de valer
CAMPOS_CONFERIDOS = {"shows": ("id", "valor"), "alugueis": ("id", "valor"),
                     "entidades": ("cnpj", "abertura", "aberturaFilial", "municipio", "situacao")}


def hash_registro(x, base=None):
    """Hash curto dos campos conferidos do registro (todos, se a base não tiver lista)."""
    campos = CAMPOS_CONFERIDOS.get(base)
    y = {k: x.get(k) for k in campos} if campos else x
    return _hl.sha1(json.dumps(y, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:12]


def registros_por_id(base):
    """{id: registro} das bases conferidas registro a registro (o id é o mesmo usado na conferência)."""
    if base == "shows":
        return {str(x.get("id")): x for x in J("shows.json").get("shows") or [] if x.get("id")}
    if base == "alugueis":
        return {str(x.get("id")): x for x in (J("alugueis.json").get("pncp") or {}).get("lista") or [] if x.get("id")}
    if base == "entidades":
        return {str(x.get("cnpj")): x for x in J("entidades.json").get("entidades") or [] if x.get("cnpj")}
    return None


def hashes_atuais(base):
    regs = registros_por_id(base)
    return None if regs is None else {i: hash_registro(x, base) for i, x in regs.items()}


def J(n):
    try:
        return json.load(open(DADOS / n, encoding="utf-8"))
    except Exception:
        return {}


def get(url, params=None, tent=3, timeout=90):
    """JSON da fonte ou None. 429 e 5xx: espera 30–60 s (ou Retry-After) antes de tentar de novo; outro erro: 3, 6… s."""
    for t in range(tent):
        espera = 3 * (t + 1)
        try:
            r = requests.get(url, params=params, headers=H, timeout=timeout)
            if r.status_code == 200:
                return r.json()
            if r.status_code == 429 or r.status_code >= 500:
                ra = r.headers.get("Retry-After")
                espera = int(ra) if (ra or "").isdigit() else random.uniform(30, 60)
        except (requests.RequestException, ValueError):
            pass
        if t < tent - 1:
            time.sleep(espera)
    return None


def norm(t):
    return re.sub(r"[^A-Z ]", "", "".join(c for c in unicodedata.normalize("NFD", (t or "").upper()) if unicodedata.category(c) != "Mn")).replace("DEP ", "").strip()


def brl(t):
    return float(str(t).replace("R$", "").replace(".", "").replace(",", ".").strip())


METODOLOGIA = "ICP 2.0"
RESPONSAVEL = "validar_fontes.py — conferência automática do robô diário (consulta própria à fonte, independente da coleta)"


def resultado(itens, metodo, fonte_url, nota="", granularidade="registro", unidade="registro", unidades_base=None,
              registros_base=None, registros_por_unidade=None, selecao="todas as unidades publicadas"):
    """itens: [(nome, site, fonte)] ou [(nome, site, fonte, tolerância)] com fonte None = não obtido. Tolerância padrão R$ 1
    (valores em reais); contagens usam tolerância 0 — uma pessoa ou um projeto a mais é diferença.
    Cobertura (metodologia ICP 2.0):
      granularidade  registro (um a um) · unidade (total de cada parlamentar/órgão/mês) · total (um único total da base)
      unidades_base  quantas unidades a base tem (None = desconhecido → cobertura não calculada)
      registros_base quantos registros a base tem; registros_por_unidade: {unidade: nº de registros} para saber quantos
                     registros entram nos totais conferidos"""
    obtidos = [i for i in itens if i[2] is not None]
    cob = {"granularidade": granularidade, "unidade": unidade, "unidadesBase": unidades_base, "registrosBase": registros_base,
           "selecao": selecao, "responsavel": RESPONSAVEL, "metodologia": METODOLOGIA}
    if not obtidos:
        return {"resultado": "indisponivel", "em": AGORA, "metodo": metodo, "fonteUrl": fonte_url, "conferidos": 0, "nota": "a fonte não respondeu", **cob}
    tol = lambda i: i[3] if len(i) > 3 else 1
    div = [{"item": i[0], "site": round(i[1], 2), "fonte": round(i[2], 2), "diferenca": round(i[1] - i[2], 2)} for i in obtidos if abs(i[1] - i[2]) > tol(i)]
    comparados = [{"item": i[0], "site": round(i[1], 2), "fonte": round(i[2], 2), "diferenca": round(i[1] - i[2], 2)} for i in obtidos][:120]
    ids = sorted({str(i[0]) for i in obtidos})  # sem repetição: o mesmo item conferido duas vezes conta uma
    if granularidade == "total":
        abr = registros_base
    elif registros_por_unidade is not None:
        abr = sum(registros_por_unidade.get(i, 0) for i in ids)
    else:
        abr = len(ids)
    return {"resultado": "confere" if not div else "diverge", "em": AGORA, "metodo": metodo, "fonteUrl": fonte_url,
            "conferidos": len(obtidos), "divergentes": div[:20], "comparados": comparados, "naoObtidos": len(itens) - len(obtidos), "nota": nota,
            **cob, "unidadesConferidas": len(ids), "idsConferidos": ids if granularidade == "registro" else ids[:400], "registrosAbrangidos": abr}


def n_por(lista, chave, sub):
    return {str(p.get(chave)): len(p.get(sub) or []) for p in lista}


def v_governo():
    import coletar_governo_ms as g
    s = J("governo_ms.json")
    orgaos = s.get("orgaos") or []
    try:
        d = g.despesas_periodo("despesapordataorgaos", date(int(s["ano"]), 1, 1), date.fromisoformat(s["ultimaAtualizacao"][:10]), 1000)
        fonte = {str(o.get("codigo")): o.get("pago") for o in d.get("despesas") or []}
        f = [(f"{o.get('codigo')} {o['orgao'][:50]}", o["pago"], fonte.get(str(o.get("codigo")))) for o in orgaos]
        f += [("TOTAL pago", s["totais"]["pago"], d["totalPago"]), ("TOTAL empenhado", s["totais"]["empenhado"], d["totalEmpenhado"])]
    except Exception:
        f = [("pago", 0, None)]
    n_cred = len(J("governo_ms_credores.json").get("credores") or []) or None  # todos os credores do ano (governo_ms.json só traz os maiores)
    return resultado(f, "consulta nova ao portal do Estado (mesmo período da coleta): valor pago de cada órgão e totais do ano", "https://www.transparencia.ms.gov.br/",
                     granularidade="unidade", unidade="órgão (total pago no ano)", unidades_base=len(orgaos) + 2, registros_base=n_cred,
                     registros_por_unidade={"TOTAL pago": n_cred}, selecao="todos os órgãos publicados + totais do ano")


def v_alems():
    de = J("deputados_estaduais_ms.json")
    rows = []
    for p in (1, 2):
        d = get("https://transparencia2.al.ms.gov.br/ceap/data", {"ano": de.get("ano"), "page": p, "perPage": 50})
        if not d:
            break
        rows += d.get("rows") or []
        if len(d.get("rows") or []) < 50:
            break
    of = {norm(x["deputado"]): brl(x["total"]) for x in rows}
    itens = []
    for v in de.get("vereadores") or []:
        k = norm(v["nome"])
        o = of.get(k)
        if o is None:
            cand = [x for x in of if k.split()[-1] in x]
            o = of.get(cand[0]) if len(cand) == 1 else None
        itens.append((v["nome"], v["verbaIndenizatoria"].get(f"gastoPago{de.get('ano')}") or 0, o))
    vs = de.get("vereadores") or []
    return resultado(itens, "portal da ALEMS (/ceap/data): total do ano de cada deputado", "https://transparencia2.al.ms.gov.br/ceap",
                     granularidade="unidade", unidade="deputado estadual (total da CEAP no ano)", unidades_base=len(vs),
                     registros_base=sum(len(v.get("despesas") or []) for v in vs), registros_por_unidade=n_por(vs, "nome", "despesas"))


def _dig(t):
    return re.sub(r"\D", "", str(t or ""))


def casar(site, fonte, chave_s, chave_f, valor_s, valor_f):
    """Compara registro a registro, usando só o que a fonte já devolveu. Agrupa pela chave (documento, CNPJ, data…);
    numa chave presente nos dois lados, compara o conjunto de valores (ordenado): igual (R$ 1) → todos os registros dela
    contam como comparados um a um; diferente → divergência. Chave só no site = não achado na fonte (não conta, não diverge).
    Devolve (n_casados, divergencias[(chave, valores_site, valores_fonte)], n_nao_achados)."""
    import collections
    gs, gf = collections.defaultdict(list), collections.defaultdict(list)
    for x in site:
        gs[chave_s(x)].append(round(abs(valor_s(x) or 0), 2))
    for x in fonte:
        gf[chave_f(x)].append(round(abs(valor_f(x) or 0), 2))
    ok, div, nao = 0, [], 0
    for k, vs in gs.items():
        if k not in gf:
            nao += len(vs)
            continue
        a, b = sorted(vs), sorted(gf[k])
        if len(a) == len(b) and all(abs(x - y) <= 1 for x, y in zip(a, b)):
            ok += len(vs)
        else:
            div.append((k, a, b))
    return ok, div, nao


def _janela_unidades(base, digests_hoje, digest_atual):
    """Unidades (parlamentares) cujos registros foram todos comparados um a um num dia dos últimos 30 e não mudaram desde
    então (hash da unidade igual): {unidade: n}. As de hoje entram direto."""
    vale = {u: d["n"] for u, d in digests_hoje.items()}
    limite = (datetime.fromisoformat(AGORA) - __import__("datetime").timedelta(days=30)).isoformat()
    try:
        for l in open(HISTORICO, encoding="utf-8"):
            h = json.loads(l)
            if h.get("base") == base and h.get("em", "") >= limite and h.get("resultado") in ("confere", "mudou_na_fonte"):
                for u, d in (h.get("digestsUmAUm") or {}).items():
                    if u not in vale and d.get("hash") == digest_atual.get(u):
                        vale[u] = d["n"]
    except FileNotFoundError:
        pass
    return vale


def _hash_lista(xs, campos):
    return _hl.sha1(json.dumps(sorted(json.dumps([x.get(c) for c in campos], ensure_ascii=False) for x in xs)).encode()).hexdigest()[:16]


def _um_a_um(res, base, por_unidade, campos):
    """Grava no resultado os registros comparados um a um (com janela de 30 dias por hash da unidade) e mostra as
    divergências registro a registro. por_unidade: {unidade: (registros do site, n_casados, divergencias, n_nao_achados)}."""
    digests, digest_atual, divs, nao = {}, {}, [], 0
    for u, (regs, n_ok, dv, na) in por_unidade.items():
        digest_atual[u] = _hash_lista(regs, campos)
        if regs and n_ok == len(regs):
            digests[u] = {"n": n_ok, "hash": digest_atual[u]}
        divs += [{"item": f"{u} · {k}", "site": sum(a), "fonte": sum(b), "diferenca": round(sum(a) - sum(b), 2), "registro": True} for k, a, b in dv]
        nao += na
    vale = _janela_unidades(base, digests, digest_atual)
    casados_hoje = sum(x[1] for x in por_unidade.values())
    n = sum(vale.values()) + sum(x[1] for u, x in por_unidade.items() if u not in vale)
    res["registrosPorTotais"] = res.get("registrosAbrangidos")
    res["registrosConferidosUmAUm"] = min(n, res.get("registrosBase") or n)
    res["digestsUmAUm"] = digests
    res["naoAchadosNaFonte"] = nao
    res["casadosHoje"] = casados_hoje
    if divs:
        res["divergentesRegistros"] = divs[:50]
        if res["resultado"] in ("confere", "mudou_na_fonte"):
            res["resultado"] = "diverge"
            res["divergentes"] = (res.get("divergentes") or []) + divs[:20]
    return res


def v_senado():
    s = J("senadores_ms.json")
    d = get(f"https://adm.senado.gov.br/adm-dadosabertos/api/v1/senadores/despesas_ceaps/{s.get('ano') or date.today().year}", timeout=180)
    itens = []
    for p in s.get("senadores") or []:
        f = round(sum(float(x.get("valorReembolsado") or 0) for x in d if str(x.get("codSenador")) == str(p["id"])), 2) if d else None
        itens.append((p["nome"], p.get("cotaGastaAno") or 0, f))
    ps = s.get("senadores") or []
    res = resultado(itens, "dados abertos do Senado (despesas_ceaps): soma do ano de cada senador de MS e cada reembolso", "https://adm.senado.gov.br/adm-dadosabertos/",
                    granularidade="unidade", unidade="senador (total da CEAPS no ano)", unidades_base=len(ps),
                    registros_base=sum(len(p.get("notasCeaps") or []) for p in ps), registros_por_unidade=n_por(ps, "nome", "notasCeaps"))
    if d and res["resultado"] != "indisponivel":  # cada reembolso, com a lista que já veio
        por = {}
        for p in ps:
            fonte = [x for x in d if str(x.get("codSenador")) == str(p["id"])]
            ok, dv, na = casar(p.get("notasCeaps") or [], fonte, lambda x: (_dig(x.get("cnpjCpf")), str(x.get("doc") or "").strip(), str(x.get("data"))[:10]),
                               lambda x: (_dig(x.get("cpfCnpj")), str(x.get("documento") or "").strip(), str(x.get("data"))[:10]),
                               lambda x: x.get("valor"), lambda x: x.get("valorReembolsado"))
            por[p["nome"]] = (p.get("notasCeaps") or [], ok, dv, na)
        _um_a_um(res, "senadores", por, ("cnpjCpf", "doc", "data", "valor"))
    return res


def v_camara():
    d = J("deputados_federais_ms.json")
    itens, por_notas = [], {}
    for p in d.get("deputados") or []:
        todos, pag, ok = [], 1, True
        while True:
            r = get(f"https://dadosabertos.camara.leg.br/api/v2/deputados/{p['id']}/despesas", {"ano": d.get("ano"), "itens": 100, "pagina": pag})
            if r is None:
                ok = False
                break
            todos += r.get("dados") or []
            if not any(l.get("rel") == "next" for l in r.get("links") or []):
                break
            pag += 1
        # a inversão do sinal é detectada sobre todas as despesas do deputado (uma página só de passagens engana)
        comuns = [x for x in todos if not PASSAGEM.search(x.get("tipoDespesa") or "") and float(x.get("valorDocumento") or 0) > 0]
        inv = bool(comuns) and sum(1 for x in comuns if float(x.get("valorLiquido") or 0) < 0) > len(comuns) / 2
        tot = sum((float(x.get("valorLiquido") or 0) if PASSAGEM.search(x.get("tipoDespesa") or "") else (-1 if inv else 1) * float(x.get("valorLiquido") or 0)) for x in todos)
        itens.append((p["nome"], p.get("cotaGastaAno") or 0, round(tot, 2) if ok else None))
        if ok:  # cada nota, com a lista que já veio
            n_ok, dv, na = casar(p.get("despesas") or [], todos,
                                 lambda x: (_dig(x.get("cnpjCpfFornecedor")), str(x.get("doc") or "").strip(), str(x.get("data"))[:10]),
                                 lambda x: (_dig(x.get("cnpjCpfFornecedor")), str(x.get("numDocumento") or "").strip(), str(x.get("dataDocumento"))[:10]),
                                 lambda x: x.get("valor"), lambda x: x.get("valorLiquido"))
            por_notas[p["nome"]] = (p.get("despesas") or [], n_ok, dv, na)
    ps = d.get("deputados") or []
    res = resultado(itens, "API da Câmara: soma do valor líquido do ano de cada deputado federal de MS e cada nota", "https://dadosabertos.camara.leg.br/",
                    granularidade="unidade", unidade="deputado federal (total da CEAP no ano)", unidades_base=len(ps),
                    registros_base=sum(len(p.get("despesas") or []) for p in ps), registros_por_unidade=n_por(ps, "nome", "despesas"))
    if por_notas and res["resultado"] != "indisponivel":
        _um_a_um(res, "deputados", por_notas, ("cnpjCpfFornecedor", "doc", "data", "valor"))
    # diferença pequena (até 1%) costuma ser nota lançada ou estornada depois da coleta
    if res["resultado"] == "diverge" and all(abs(x["diferenca"]) <= max(5, 0.01 * abs(x["fonte"])) for x in res["divergentes"]):
        res["resultado"], res["nota"] = "mudou_na_fonte", "diferenças até 1% — lançamentos/estornos feitos na Câmara depois da coleta"
    return res


def v_siconfi():
    """ICMS do Estado mês a mês no Siconfi (RREO Anexo 3). Cada RREO traz os 12 meses até o bimestre; para cobrir a série
    inteira do site, consulta o bimestre mais recente e o 6º bimestre de cada ano anterior que a série tem."""
    r = J("receitas.json")
    e = (r.get("entes") or {}).get("estado") or {}
    ult, meses = e.get("ultimoMes"), e.get("meses") or {}
    if not ult:
        return resultado([("ICMS", 0, None)], "Siconfi RREO Anexo 3", "https://siconfi.tesouro.gov.br/")
    ano, mes = int(ult[:4]), int(ult[5:7])
    periodos = [(ano, (mes + 1) // 2, mes)] + [(a, 6, 12) for a in sorted({int(k[:4]) for k in meses}) if a < ano]
    fonte = {}
    for a, bim, mfim in periodos:
        d = get("https://apidatalake.tesouro.gov.br/ords/siconfi/tt/rreo", {"an_exercicio": a, "nr_periodo": bim, "co_tipo_demonstrativo": "RREO",
                                                                             "no_anexo": "RREO-Anexo 03", "id_ente": 50}, timeout=180)
        if not d:
            continue
        icms = {x["coluna"]: x["valor"] for x in d.get("items") or [] if x["conta"].strip().upper() == "ICMS"}
        for k in range(12):
            col = "<MR>" if k == 0 else f"<MR-{k}>"
            y, m_ = a, mfim - k
            while m_ <= 0:
                m_ += 12
                y -= 1
            if col in icms:
                fonte.setdefault(f"{y}-{m_:02d}", icms[col])  # o RREO mais recente vence (vem primeiro)
    itens = [(f"ICMS {k}", meses[k].get("icms"), fonte.get(k)) for k in sorted(meses) if meses[k].get("icms") is not None]
    nm = len(meses)
    res = resultado(itens or [("ICMS", 0, None)], f"Siconfi RREO Anexo 3 ({', '.join(f'{a}/{b}º bim' for a, b, _ in periodos)}): ICMS mês a mês",
                     "https://siconfi.tesouro.gov.br/", granularidade="unidade", unidade="mês do ICMS do Estado", unidades_base=nm, registros_base=nm,
                     selecao="todos os meses da série do site (RREO do bimestre mais recente + 6º bimestre dos anos anteriores); "
                             "demais impostos e Campo Grande não conferidos")
    if res["resultado"] != "indisponivel":  # cada mês é um registro da base, comparado um a um
        div = {x["item"] for x in res.get("divergentes") or []}
        res["registrosConferidosUmAUm"] = sum(1 for i in itens if i[2] is not None and i[0] not in div)
        res["registrosPorTotais"] = 0
    return res


FOLHA_GOV = "https://gw.sgi.ms.gov.br/d0125/transpfolhadepagamento/v1/servidores"
TCE_PESSOAS = "https://sip-barramento.tce.ms.gov.br/barramento/api/Transparencia/GestaoPessoas"


# órgãos que a API não aceita como filtro (404), mas que vêm dentro do filtro do órgão-pai (verificado em 19/11/2026:
# as quantidades batem com a folha completa)
ORGAO_PAI = {"PMMS": "SEJUSP", "DGPC": "SEJUSP", "CBMMS": "SEJUSP", "GOVERNADORIA": "SEGOV"}


def _folha_filtro(filtro, mes):
    """Consulta nova à folha do Estado com o filtro de órgão (a coleta lê a folha inteira de uma vez): todos os registros
    devolvidos (o filtro do órgão-pai traz também os órgãos dele), "sem_filtro" (404) ou None."""
    import coletar_governo_ms as g
    mm, aa = mes.split("/")
    out, pag = [], 1
    while True:
        try:  # rede caiu nesta consulta: o órgão fica "não obtido" (nunca derruba a conferência inteira)
            r = g.requisitar(FOLHA_GOV, {"anoexercicio": int(aa), "mescompetencia": int(mm), "tipoFolha": 1, "orgao": filtro,
                                         "pageno": pag, "pagesize": 20000, "exportarcsv": "false"}, 600)
            j = r.json()
        except Exception:
            return None
        if (j.get("status") or {}).get("code") == 404 or r.status_code == 404:
            return "sem_filtro"
        if r.status_code != 200 or (j.get("status") or {}).get("code") != 200:
            return None
        out += j.get("data") or []
        if len(j.get("data") or []) < 20000:
            return out
        pag += 1


def _amostra_governo(folha, n=100):
    """Amostra estratificada por órgão (semente = data) de contracheques do Governo, cada um consultado de novo pelo nome
    dentro do órgão: remuneração fixa, eventuais e valor após deduções da mesma matrícula. Devolve (itens, hashes)."""
    import coletar_governo_ms as g
    from concurrent.futures import ThreadPoolExecutor
    gov = [p for p in folha if p.get("orgaoId") == "governo" and p.get("matricula")]
    if not gov:
        return [], {}
    random.seed(date.today().toordinal())
    por = {}
    for p in sorted(gov, key=lambda p: (p.get("orgaoSigla") or "", p["matricula"])):
        por.setdefault(p.get("orgaoSigla"), []).append(p)
    cota = {o: n * len(v) / len(gov) for o, v in por.items()}
    alvo = {o: int(c) for o, c in cota.items()}
    for o in sorted(cota, key=lambda o: -(cota[o] - alvo[o]))[: n - sum(alvo.values())]:
        alvo[o] += 1
    escolhidos = [x for o in sorted(por) for x in random.sample(por[o], alvo[o])]

    def consulta(p):
        try:
            return _consulta(p)
        except Exception:  # rede: o contracheque fica "não obtido"
            return p, None

    def _consulta(p):
        mm, aa = p["mes"].split("/")
        prm = {"anoexercicio": int(aa), "mescompetencia": int(mm), "tipoFolha": 1, "nome": p["nome"].upper(), "pageno": 1, "pagesize": 50,
               "exportarcsv": "false"}
        if p["orgaoSigla"] not in ORGAO_PAI:  # PMMS, DGPC, CBMMS e Governadoria: a API não aceita o órgão como filtro → só o nome
            prm["orgao"] = p["orgaoSigla"]
        r = g.requisitar(FOLHA_GOV, prm, 120)
        try:
            d = [x for x in r.json().get("data") or [] if str(x.get("matricula")) == str(p["matricula"])]
        except ValueError:
            d = None
        return p, (d[0] if d else None) if d is not None else None
    itens, hashes = [], {}
    with ThreadPoolExecutor(4) as ex:  # no máximo 4 consultas ao mesmo tempo no gateway do Estado
        for p, x in ex.map(consulta, escolhidos):
            k = f"{p['orgaoSigla']}:{p['matricula']}"
            fonte = None if x is None else round((x.get("remuneracaoFixa") or 0) + (x.get("remuneracoesEventuais") or 0), 2)
            itens.append((f"contracheque {k}: bruto", p["bruto"], fonte))
            itens.append((f"contracheque {k}: líquido", p["liquido"], None if x is None else round(x.get("remuneracaoAposDeducoes") or 0, 2)))
            if x is not None and abs(fonte - p["bruto"]) <= 1 and abs((x.get("remuneracaoAposDeducoes") or 0) - p["liquido"]) <= 1:
                hashes[k] = hash_registro({"m": p["matricula"], "b": p["bruto"], "l": p["liquido"]})
    return itens, hashes


def _hash_orgao(f_gov, sigla):
    """Hash de todos os contracheques do órgão na folha (matrícula, bruto, líquido), em ordem: muda se qualquer um mudar."""
    linhas = sorted((m, round(p["bruto"], 2), round(p["liquido"], 2)) for (sg, m), p in f_gov.items() if sg == sigla)
    return _hl.sha1(json.dumps(linhas).encode()).hexdigest()[:16]


def _contracheques_conferidos(hoje, f_gov=None, digests_hoje=None):
    """Contracheques comparados um a um que ainda valem: os de hoje; os das amostras dos últimos 30 dias cujo hash é igual
    ao do contracheque na folha atual; e os órgãos inteiros comparados nos últimos 30 dias cujo hash de órgão não mudou."""
    f_gov = f_gov or {}
    validos = set(hoje)
    atual = {f"{sg}:{m}": hash_registro({"m": m, "b": p["bruto"], "l": p["liquido"]}) for (sg, m), p in f_gov.items()}
    limite = (datetime.fromisoformat(AGORA) - __import__("datetime").timedelta(days=30)).isoformat()
    try:
        for l in open(HISTORICO, encoding="utf-8"):
            h = json.loads(l)
            if h.get("base") != "supersalarios" or h.get("em", "") < limite or h.get("resultado") not in ("confere", "mudou_na_fonte"):
                continue
            validos |= {k for k, x in ((h.get("amostraContracheques") or {}).get("hashes") or {}).items() if atual.get(k) == x}
            for org, dg in (h.get("digestsUmAUm") or {}).items():
                sg = org.replace("Governo MS — ", "")
                if (digests_hoje or {}).get(org) is None and dg.get("hash") == _hash_orgao(f_gov, sg):
                    validos |= {f"{s_}:{m}" for (s_, m) in f_gov if s_ == sg}
    except FileNotFoundError:
        pass
    return {k for k in validos if k in atual or k.startswith("TCE:")}


def rgf_executivo(ss):
    """Segundo nível, FONTE INDEPENDENTE (Tesouro Nacional — Siconfi, RGF Anexo 1 do Poder Executivo de MS): a média mensal
    dos últimos 12 meses do RGF mais recente contra a folha do mês no site, para ativos (vencimentos, vantagens e outras
    despesas variáveis) e para aposentados e pensionistas (aposentadorias, reserva e reformas + pensões). Agregado,
    tolerância de 10%, diferença em % visível. Não conta registro conferido. O RGF anual inclui 13º e férias: a média
    mensal tende a ficar acima de um mês comum."""
    org = {o["orgao"]: o for o in ss.get("orgaos") or []}
    at, ina = org.get("Governo do Estado — ativos"), org.get("Governo do Estado — aposentados e pensionistas")
    if not at or not ina:
        return None
    ano = int(at["mes"].split("/")[1])
    d, per = None, None
    for a_, q in ((ano, 3), (ano, 2), (ano, 1), (ano - 1, 3)):
        d = get("https://apidatalake.tesouro.gov.br/ords/siconfi/tt/rgf", {"an_exercicio": a_, "in_periodicidade": "Q", "nr_periodo": q,
                "co_tipo_demonstrativo": "RGF", "no_anexo": "RGF-Anexo 01", "co_esfera": "E", "co_poder": "E", "id_ente": 50}, timeout=120)
        if d and d.get("items"):
            per = f"{q}º quadrimestre de {a_}"
            break
    if not per:
        return {"resultado": "indisponivel", "em": AGORA, "fonte": "Tesouro Nacional — Siconfi, RGF Anexo 1 (Poder Executivo de MS)"}
    tot = {x["conta"].strip(): x["valor"] for x in d["items"] if x["coluna"].startswith("TOTAL (ÚLTIMOS 12 MESES)")}
    venc = tot.get("Vencimentos, Vantagens e Outras Despesas Variáveis")
    inat = (tot.get("Aposentadorias, Reserva e Reformas") or 0) + (tot.get("Pensões") or 0)
    linhas = []
    for rot, site, rgf in (("ativos", (at.get("totalBase") or 0) + (at.get("totalOutras") or 0), venc),
                           ("aposentados e pensionistas", (ina.get("totalBase") or 0) + (ina.get("totalOutras") or 0), inat)):
        if not rgf:
            continue
        media = rgf / 12
        dif = 100 * (site - media) / media
        linhas.append({"grupo": rot, "site": round(site, 2), "rgfMediaMensal": round(media, 2), "diferencaPct": round(dif, 1),
                       "resultado": "confere" if abs(dif) <= 10 else "diverge"})
    return {"resultado": "confere" if linhas and all(l["resultado"] == "confere" for l in linhas) else "diverge" if linhas else "indisponivel",
            "em": AGORA, "periodo": per, "mesFolha": at["mes"], "tolerancia": 10, "linhas": linhas, "agregado": True,
            "fonte": "Tesouro Nacional — Siconfi, RGF Anexo 1 (Poder Executivo de MS)", "fonteUrl": "https://siconfi.tesouro.gov.br/",
            "nota": "fonte independente, só no agregado do Poder Executivo; não conta contracheque conferido"}


def v_tjms():
    """Supersalários na fonte, órgão por órgão, no mês publicado:
      TJMS e TRT24  DadosJusBr (contracheques enviados ao CNJ): nº de magistrados e soma do salário-base
      Governo       39 órgãos — consulta nova à folha do Estado filtrada por órgão: nº de pessoas e total bruto
      TCE-MS        servidores — consulta nova ao portal do TCE: nº de pessoas, salário-base e outras verbas
    mais uma amostra estratificada diária de 100 contracheques do Governo (semente = data), um a um.
    Não conferidos: TCE-MS conselheiros e procuradores (só PDF) e Câmara de CG (60 maiores)."""
    from concurrent.futures import ThreadPoolExecutor
    ss = J("supersalarios.json")
    org = (ss.get("orgaos") or []) + (ss.get("orgaosGoverno") or [])
    unidades = [o for o in org if not o["orgao"].startswith("Governo do Estado")]  # as 2 linhas de resumo não são órgãos
    itens, por = [], {}
    for oid, pref in (("tjms", "TJMS"), ("trt24", "TRT24")):
        o = next((x for x in ss.get("orgaos") or [] if x.get("orgao", "").startswith(pref)), None)
        if not o:
            continue
        m, a = o["mes"].split("/")
        d = get(f"https://api.dadosjusbr.org/v2/dados/{oid}/{int(a)}/{int(m)}")
        s = ((d or {}).get("sumarios") or {}).get("membros_ativos") or {}
        itens += [(f"{pref}: magistrados", o["pessoas"], s.get("quantidade"), 0),
                  (f"{pref}: salário-base total", o["totalBase"], (s.get("remuneracao_base") or {}).get("total"))]
        por[o["orgao"]] = (o.get("pessoas") or 0, s.get("quantidade") is not None)
    gov = ss.get("orgaosGoverno") or []
    # folha completa (artefato privado da coleta): cada matrícula que a fonte devolver é comparada um a um
    folha = []
    try:
        import gzip
        arq = Path(__file__).parent.parent / "folha_completa" / "folha_supersalarios.jsonl.gz"
        if arq.exists():
            folha = [json.loads(l) for l in gzip.open(arq, "rt", encoding="utf-8") if l.strip()]
    except Exception as e:
        print(f"  ⚠️ folha completa: {type(e).__name__}: {e}")
    f_gov = {(p.get("orgaoSigla"), str(p.get("matricula"))): p for p in folha if p.get("orgaoId") == "governo" and p.get("matricula")}
    f_tce = {str(p.get("matricula")): p for p in folha if p.get("orgaoId") == "tce" and "servidores" in (p.get("orgao") or "") and p.get("matricula")}
    casados, digests, so_na_fonte = set(), {}, 0

    def compara(chave, p, campos, rotulo):
        """campos: [(nome, valor no site, valor na fonte)]; bate tudo (R$ 1) → comparado um a um; senão vira divergência."""
        ruins = [(c, a, b) for c, a, b in campos if abs((a or 0) - (b or 0)) > 1]
        if not ruins:
            casados.add(chave)
        for c, a, b in ruins:
            itens.append((f"contracheque {rotulo}: {c}", round(a or 0, 2), round(b or 0, 2)))

    # uma consulta por filtro: o órgão-pai (SEJUSP, SEGOV) traz também os órgãos dele
    filtros = sorted({ORGAO_PAI.get(o["sigla"], o["sigla"]) for o in gov})
    mes_gov = gov[0]["mes"] if gov else None
    with ThreadPoolExecutor(4) as ex:  # no máximo 4 consultas ao mesmo tempo no gateway do Estado
        respostas = dict(zip(filtros, ex.map(lambda f: _folha_filtro(f, mes_gov), filtros)))
    if True:
        sem_filtro = []
        for o in gov:
            r_ = respostas.get(ORGAO_PAI.get(o["sigla"], o["sigla"]))
            lst = r_ if not isinstance(r_, list) else [x for x in r_ if (x.get("orgao") or "").strip() == o["sigla"]]
            if lst == "sem_filtro":
                sem_filtro.append(o["sigla"])
                lst = None
            fonte_n = None if lst is None else len(lst)
            fonte_b = None if lst is None else round(sum((x.get("remuneracaoFixa") or 0) + (x.get("remuneracoesEventuais") or 0) for x in lst), 2)
            if lst and f_gov:
                antes = len(casados)
                for x in lst:
                    k = (o["sigla"], str(x.get("matricula")))
                    p_ = f_gov.get(k)
                    if not p_:
                        so_na_fonte += 1
                        continue
                    compara(f"{k[0]}:{k[1]}", p_, [("bruto", p_["bruto"], (x.get("remuneracaoFixa") or 0) + (x.get("remuneracoesEventuais") or 0)),
                                                  ("eventuais", p_.get("outras"), x.get("remuneracoesEventuais")),
                                                  ("líquido", p_["liquido"], x.get("remuneracaoAposDeducoes"))], f"{k[0]}:{k[1]}")
                if len(casados) - antes == o["pessoas"]:  # órgão inteiro bateu: guarda o resumo (hash) para a janela de 30 dias
                    digests[o["orgao"]] = {"n": o["pessoas"], "hash": _hash_orgao(f_gov, o["sigla"])}
            itens += [(f"{o['orgao']}: pessoas", o["pessoas"], fonte_n, 0),
                      (f"{o['orgao']}: total bruto", round((o.get("totalBase") or 0) + (o.get("totalOutras") or 0), 2), fonte_b)]
            por[o["orgao"]] = (o.get("pessoas") or 0, lst is not None)
    t = next((x for x in ss.get("orgaos") or [] if x.get("orgao") == "TCE-MS — servidores"), None)
    if t:
        m, a = t["mes"].split("/")

        def lista(ep):
            out, pg = [], 0
            while True:
                r = get(f"{TCE_PESSOAS}/{ep}", {"ano": int(a), "mes": int(m), "pageNumber": pg, "pageSize": 500}, timeout=120)
                if r is None:
                    return None
                out += r.get("items") or []
                pg += 1
                if pg >= (r.get("totalPages") or 0):
                    return out
        rem, op = lista("Remuneracao"), lista("OutroPagamento")
        mats = {x.get("matricula") for x in rem or []}
        itens += [("TCE-MS servidores: pessoas", t["pessoas"], None if rem is None else len(rem), 0),
                  ("TCE-MS servidores: salário-base total", t["totalBase"], None if rem is None else round(sum(x.get("totalVencimentosRemuneracao") or 0 for x in rem), 2)),
                  ("TCE-MS servidores: outras verbas", t["totalOutras"], None if rem is None or op is None else
                   round(sum(x.get("totalVencimentoOutrosPagamentos") or 0 for x in op if x.get("matricula") in mats), 2))]
        por[t["orgao"]] = (t.get("pessoas") or 0, rem is not None)
        if rem and f_tce:
            outros = {x.get("matricula"): x for x in op or []}
            for x in rem:
                p_ = f_tce.get(str(x.get("matricula")))
                if not p_:
                    so_na_fonte += 1
                    continue
                o_ = outros.get(x.get("matricula")) or {}
                compara(f"TCE:{x.get('matricula')}", p_, [("salário-base", p_["base"], x.get("totalVencimentosRemuneracao")),
                                                        ("outras verbas", p_["outras"], o_.get("totalVencimentoOutrosPagamentos") if op is not None else p_["outras"]),
                                                        ("líquido", p_["liquido"], (x.get("totalCalculadoRemuneracao") or 0) + (o_.get("totalCalculadoOutrosPagamentos") or 0))],
                        f"TCE:{x.get('matricula')}")
    # amostra diária de contracheques (folha completa do artefato privado da coleta, quando disponível)
    hashes = {}
    try:
        if folha:
            am, hashes = _amostra_governo(folha)
            itens += am
    except Exception as e:
        print(f"  ⚠️ amostra de contracheques: {type(e).__name__}: {e}")
    if not itens:
        return resultado([("supersalários", 0, None)], "DadosJusBr, folha do Estado e portal do TCE-MS", "https://www.transparencia.ms.gov.br/")
    res = resultado(itens, "órgão por órgão no mês publicado: TJMS e TRT24 no DadosJusBr; os 39 órgãos do Governo numa consulta nova à folha do "
                    "Estado filtrada por órgão (pessoas e total bruto); TCE-MS (servidores) numa consulta nova ao portal do TCE; mais 100 "
                    "contracheques do Governo sorteados por dia (semente = data), um a um", "https://www.transparencia.ms.gov.br/",
                    granularidade="unidade", unidade="órgão no mês publicado (pessoas e totais da folha)", unidades_base=len(unidades),
                    registros_base=ss.get("totalPessoas"), selecao="todos os órgãos da folha (PMMS, DGPC e CBMMS pelo filtro do órgão-pai SEJUSP; "
                    "Governadoria pelo SEGOV), menos TCE-MS conselheiros e procuradores (contracheque só em PDF) e Câmara de CG (60 maiores); "
                    "amostra diária de 100 contracheques do Governo (os 4 órgãos sem filtro próprio buscados pelo nome)")
    if sem_filtro:
        res["nota"] = ((res.get("nota") or "") + f" Não conferidos: {', '.join(sem_filtro)} — a API do Estado não aceita esses órgãos como "
                       "filtro da folha (resposta 404), e somar a folha inteira seria repetir o caminho da coleta.").strip()
        res["semFiltro"] = sem_filtro
    if res["resultado"] in ("confere", "diverge", "mudou_na_fonte"):
        # unidades = órgãos cujo total foi conferido; registros = SÓ os contracheques comparados um a um (amostras diárias
        # dos últimos 30 dias cujo contracheque não mudou desde então — mesmo hash). Total que bate não conta registro.
        ok = [k for k, (_, obtido) in por.items() if obtido]
        um_a_um = _contracheques_conferidos(set(hashes) | casados, f_gov, digests)
        res.update({"unidadesConferidas": len(ok), "idsConferidos": ok, "registrosAbrangidos": len(um_a_um),
                    "totaisDeOrgaoConferidos": {"orgaos": len(ok), "contrachequesNessesOrgaos": sum(por[k][0] for k in ok)},
                    "registrosConferidosUmAUm": len(um_a_um), "registrosPorTotais": sum(por[k][0] for k in ok), "digestsUmAUm": digests,
                    "soNaFonte": so_na_fonte})
        res["amostraContracheques"] = {"sorteados": sum(1 for i in itens if str(i[0]).startswith("contracheque") and i[0].endswith("bruto")),
                                       "conferidos": len(hashes), "hashes": hashes}
    res["independencia"] = ("mesma fonte da coleta (folha do Estado, portal do TCE-MS e DadosJusBr), por outra consulta: confirma a leitura, "
                            "não é fonte independente")
    try:
        res["fonteIndependente"] = rgf_executivo(ss)
    except Exception as e:
        res["fonteIndependente"] = {"resultado": "indisponivel", "em": AGORA, "nota": f"erro: {type(e).__name__}"}
    return res


def com_hashes(res, base, ids_ok):
    """Grava o hash, no momento da conferência, de cada registro que bateu com a fonte (janela de 30 dias com hash)."""
    regs = registros_por_id(base) or {}
    res["hashes"] = {i: hash_registro(regs[i], base) for i in sorted(ids_ok) if i in regs}
    return res


def v_pncp(arquivo, chave_lista, rotulo, base, n=8):
    """PNCP: valor homologado (ou estimado) de cada contratação na consulta pública. n = tamanho da amostra sorteada
    (semente = data); n=None = todas as contratações da base."""
    from concurrent.futures import ThreadPoolExecutor
    d = J(arquivo)
    lst = d.get(chave_lista) if chave_lista else None
    if lst is None:
        lst = (d.get("pncp") or {}).get("lista") or []
    random.seed(date.today().toordinal())
    escolhidos = lst if n is None else random.sample(lst, min(n, len(lst)))  # amostra aleatória simples, sem reposição, semente = data

    def consulta(x):
        try:
            cnpj, ano, seq = x["link"].split("/editais/")[1].split("/")[:3]
        except Exception:
            return None
        c = get(f"https://pncp.gov.br/api/consulta/v1/orgaos/{cnpj}/compras/{ano}/{seq}", tent=3, timeout=60)
        f = (c.get("valorTotalHomologado") or c.get("valorTotalEstimado")) if c else None
        return (x.get("id") or x["link"].split("/editais/")[1], x["valor"], f)  # identificador PNCP: não repete a mesma contratação
    with ThreadPoolExecutor(3) as ex:  # o PNCP responde 429 com mais consultas ao mesmo tempo
        itens = [i for i in ex.map(consulta, escolhidos) if i]
    todas = n is None
    res = resultado(itens, f"PNCP: {'todas as ' + str(len(itens)) if todas else str(len(itens))} {rotulo}{'' if todas else ' sorteadas'}, valor de cada uma na consulta pública",
                    "https://pncp.gov.br/", granularidade="registro", unidade="contratação (nº de controle PNCP)", unidades_base=len(lst), registros_base=len(lst),
                    selecao="todas as contratações da base (reconsulta total)" if todas else f"amostra aleatória simples de {n} por dia, sem reposição (semente = data)")
    return com_hashes(res, base, {str(i[0]) for i in itens if i[2] is not None and abs(i[1] - i[2]) <= 1})


CAM = "https://dadosabertos.camara.leg.br/api/v2"


def v_votacoes():
    """Voto de cada deputado federal de MS em todas as votações nominais do ano. Cada voto é um item: 100 = igual ao site,
    0 = diferente (a tolerância da comparação é 1; 100 × 0 nunca passa como igual). A cobertura conta por votação."""
    d = J("votacoes.json")
    q = d.get("quadroCamara") or {}
    deps, vots = q.get("deputados") or {}, [v for v in q.get("votacoes") or [] if v.get("id")]
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(4) as ex:
        respostas = list(ex.map(lambda v: (v, get(f"{CAM}/votacoes/{v['id']}/votos")), vots))
    itens = []
    for v, r in respostas:
        fonte = None if r is None else {str(x["deputado_"]["id"]): x.get("tipoVoto") for x in r.get("dados") or []}
        for did, nome in deps.items():
            site = (v.get("votos") or {}).get(did) or "—"
            f = None if fonte is None else (fonte.get(did) or "—")
            itens.append((f"{v['id']} · {nome} ({site})", 100.0, None if f is None else (100.0 if f == site else 0.0)))
    res = resultado(itens, "API da Câmara (/votacoes/{id}/votos): todas as votações nominais do ano; item = voto de um deputado de MS "
                    "(100 = igual ao site, 0 = diferente)", "https://dadosabertos.camara.leg.br/",
                    granularidade="unidade", unidade="votação nominal da Câmara (o voto de cada deputado de MS)", unidades_base=len(vots),
                    registros_base=len(vots), selecao="todas as votações nominais da Câmara publicadas no site; todos os deputados de MS em cada uma")
    if res["resultado"] in ("confere", "diverge"):  # unidade e registro = votação (a base conta votações, não votos) com todos os votos obtidos
        ok = [v["id"] for v, r in respostas if r is not None]
        res.update({"unidadesConferidas": len(ok), "idsConferidos": ok[:400], "registrosAbrangidos": len(ok),
                    # cada votação conta como comparada um a um só se TODOS os votos de MS bateram com a fonte
                    "registrosConferidosUmAUm": len(ok) - len({str(x["item"]).split(" · ")[0] for x in res.get("divergentes") or []}),
                    "registrosPorTotais": 0})
    return res


def v_producao():
    """Nº de projetos (PL, PLP, PEC, PDL) de cada parlamentar de MS desde o início da legislatura. Deputados: a API da Câmara
    filtra o tipo (a coleta lista tudo e filtra depois). Senadores: processos do autor no Senado, contados só os projetos."""
    d = J("producao_legislativa.json")
    ps = d.get("parlamentares") or []
    ini = d.get("inicio") or "2023-02-01"
    itens, por = [], {}
    for p in ps:
        n, ok, lista = 0, True, []
        if p.get("grupo") == "federal":
            pag = 1
            while True:
                r = get(f"{CAM}/proposicoes", {"idDeputadoAutor": p["id"], "dataApresentacaoInicio": ini,
                                              "siglaTipo": "PL,PLP,PEC,PDL", "itens": 100, "pagina": pag})
                if r is None:
                    ok = False
                    break
                n += len(r.get("dados") or [])
                lista += [f"{x.get('siglaTipo')} {x.get('numero')}/{x.get('ano')}" for x in r.get("dados") or []]
                if not any(l.get("rel") == "next" for l in r.get("links") or []):
                    break
                pag += 1
        elif p.get("grupo") == "senador":
            r = get("https://legis.senado.leg.br/dadosabertos/processo", {"codigoParlamentarAutor": p["id"], "dataInicioApresentacao": ini}, timeout=120)
            if r is None:
                ok = False
            else:
                lista = [x["identificacao"].strip() for x in r if (x.get("identificacao") or "").split()[:1] and x["identificacao"].split()[0] in ("PL", "PLP", "PEC", "PDL")]
                n = len(lista)
        else:
            continue
        itens.append((p["nome"], p.get("projetos") or 0, float(n) if ok else None, 0))
        if ok:  # cada projeto (pela sigla), com a lista que já veio
            n_ok, dv, na = casar(p.get("todos") or [], [{"s": x} for x in lista], lambda x: str(x.get("sigla")).strip(), lambda x: x["s"],
                                 lambda x: 1, lambda x: 1)
            por[p["nome"]] = (p.get("todos") or [], n_ok, dv, na)
    res = resultado(itens, "Câmara (/proposicoes, filtro de tipo na API) e Senado (/processo do autor): nº de projetos de cada parlamentar de MS "
                    "desde 01/02/2023", "https://dadosabertos.camara.leg.br/", granularidade="unidade",
                    unidade="parlamentar (nº de projetos na legislatura)", unidades_base=len(ps),
                    registros_base=sum(p.get("projetos") or 0 for p in ps), registros_por_unidade={p["nome"]: p.get("projetos") or 0 for p in ps},
                    selecao="todos os deputados federais e senadores de MS")
    # projeto novo apresentado depois da coleta: a fonte cresce um pouco (nunca diminui)
    if res["resultado"] == "diverge" and all(0 < -x["diferenca"] <= 3 for x in res["divergentes"]):
        res["resultado"], res["nota"] = "mudou_na_fonte", "projetos novos registrados depois da coleta (até 3 por parlamentar)"
    if por and res["resultado"] != "indisponivel":
        _um_a_um(res, "producao", por, ("sigla",))
    return res


def v_judiciario():
    t = J("tjms_magistrados.json")
    ms = t.get("magistrados") or []
    try:
        m, a = (t.get("mesReferencia") or "").split("/")
    except ValueError:
        return resultado([("TJMS", 0, None)], "DadosJusBr", "https://dadosjusbr.org/")
    d = get(f"https://api.dadosjusbr.org/v2/dados/tjms/{int(a)}/{int(m)}")
    s = ((d or {}).get("sumarios") or {}).get("membros_ativos") or {}
    q, base = s.get("quantidade"), (s.get("remuneracao_base") or {}).get("total")
    itens = [("magistrados ativos", float(sum(1 for x in ms if x.get("situacao") == "ATIVO")), None if q is None else float(q), 0),
             ("soma do subsídio", round(sum(x.get("subsidio") or 0 for x in ms), 2), None if base is None else round(base, 2))]
    return resultado(itens, f"DadosJusBr (contracheques do TJMS enviados ao CNJ, {t.get('mesReferencia')}): nº de magistrados ativos e soma do subsídio",
                     "https://dadosjusbr.org/", granularidade="total", unidade="folha do mês (quantidade e subsídio)", unidades_base=2,
                     registros_base=len(ms), selecao="o mês publicado no site (TJMS; TRT24 e TRE-MS não conferidos)")


def v_entidades():
    """Todas as entidades no cadastro CNPJ (minhareceita.org — a coleta usa a BrasilAPI primeiro): abertura, município e situação."""
    from concurrent.futures import ThreadPoolExecutor
    import unicodedata as _u
    nz = lambda t: "".join(c for c in _u.normalize("NFD", (t or "").upper()) if _u.category(c) != "Mn").strip()
    es = J("entidades.json").get("entidades") or []
    with ThreadPoolExecutor(3) as ex:
        respostas = list(ex.map(lambda e: (e, get(f"https://minhareceita.org/{e['cnpj']}", tent=2, timeout=40)), es))
    itens, lacunas = [], []
    for e, r in respostas:
        if not e.get("abertura") and not e.get("situacao"):  # o site não tem o cadastro da entidade: não há o que comparar
            lacunas.append(e["cnpj"])
            itens.append((f"{e['cnpj']} · cadastro", 100.0, None))
            continue
        # filial: o site mostra em "abertura" a data da matriz (desde quando a entidade existe) e guarda a da filial à parte
        ab = e.get("aberturaFilial") if str(e.get("cnpj"))[8:12] != "0001" and e.get("aberturaFilial") else e.get("abertura")
        for campo, site, fonte in (("abertura", ab, (r or {}).get("data_inicio_atividade")),
                                   ("município", e.get("municipio"), (r or {}).get("municipio")),
                                   ("situação", e.get("situacao"), (r or {}).get("descricao_situacao_cadastral"))):
            f = None if r is None else (100.0 if nz(str(site or "")) == nz(str(fonte or "")) else 0.0)
            itens.append((f"{e['cnpj']} · {campo}", 100.0, f))
    res = resultado(itens, "cadastro CNPJ (minhareceita.org): todas as entidades; item = abertura, município ou situação cadastral "
                    "(100 = igual ao site, 0 = diferente)", "https://minhareceita.org/", granularidade="registro",
                    unidade="entidade (abertura, município e situação cadastral)", unidades_base=len(es), registros_base=len(es),
                    selecao="todas as entidades da base (reconsulta total)")
    if res["resultado"] in ("confere", "diverge", "mudou_na_fonte"):  # a unidade é a entidade (o CNPJ), não cada campo
        cnpjs = sorted({str(i[0]).split(" · ")[0] for i in itens if i[2] is not None})
        res.update({"unidadesConferidas": len(cnpjs), "idsConferidos": cnpjs, "registrosAbrangidos": len(cnpjs)})
        # vale como conferida só a entidade com os 3 campos iguais à fonte
        ruins = {str(i[0]).split(" · ")[0] for i in itens if i[2] is not None and i[2] != 100.0}
        com_hashes(res, "entidades", set(cnpjs) - ruins)
    if lacunas:  # não conferidas: lacuna do site (a coleta do cadastro não alcança a entidade), mostrada como pendência
        res["lacunas"] = lacunas
        res["nota"] = (res.get("nota") or "") + f" {len(lacunas)} entidade(s) sem dados cadastrais no site (a coleta do cadastro não as alcança): não conferidas."
    # a situação cadastral pode mudar entre a coleta e a conferência (ex.: baixa): só esse campo diferente = mudou na fonte
    if res["resultado"] == "diverge" and all(x["item"].endswith("situação") for x in res["divergentes"]):
        res["resultado"], res["nota"] = "mudou_na_fonte", "situação cadastral alterada na Receita depois da coleta"
    return res


def relatorio_fora_da_janela(so, motivo):
    """Conferência fora da janela da coleta: roda, mas grava só um relatório (não toca o histórico, o validacao_fontes.json
    nem a nota)."""
    RELATORIOS.mkdir(parents=True, exist_ok=True)
    print(f"ℹ️ fora da janela da coleta ({motivo}): só relatório, sem entrar no histórico nem na nota do ICP")
    rel = {"em": AGORA, "motivo": motivo, "aviso": "relatório de conferência fora da janela da coleta — não entra no ICP", "bases": {}}
    t0, prazo = time.monotonic(), int(os.environ.get("CONFERENCIA_PRAZO_MIN", "28")) * 60
    for fonte, fn in CONFERENCIAS:
        if (so and fonte not in so) or time.monotonic() - t0 > prazo:
            continue
        try:
            r = fn()
        except Exception as e:
            r = {"resultado": "indisponivel", "em": AGORA, "nota": f"erro na conferência: {type(e).__name__}"}
        r.pop("hashes", None)
        rel["bases"][fonte] = {k: r.get(k) for k in ("resultado", "metodo", "fonteUrl", "conferidos", "divergentes", "unidadesConferidas", "unidadesBase",
                                                     "registrosConferidosUmAUm", "registrosPorTotais", "registrosBase", "nota", "fonteIndependente")}
        print(f"  {fonte:20} {r['resultado']:15} {r.get('conferidos', 0)} itens (relatório)")
    arq = RELATORIOS / f"conferencia_{AGORA.replace(':', '')}.json"
    arq.write_text(json.dumps(rel, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"✅ relatório {arq.relative_to(DADOS.parent)} (não entra no ICP)")
    return 0


def registrar(fonte, r, out):
    """Grava a conferência: mantém a última bem-sucedida quando a fonte não responde hoje; conferência feita agora vai para
    o histórico permanente (só acrescenta), com os hashes dos registros conferidos quando houver."""
    if r["resultado"] == "indisponivel" and (out.get(fonte) or {}).get("resultado") in ("confere", "mudou_na_fonte", "diverge"):
        r = {**out[fonte], "ultimaTentativa": AGORA, "ultimaTentativaResultado": "indisponivel"}
    if r.get("em") == AGORA:
        r["coletaRunId"] = os.environ.get("GITHUB_RUN_ID")
        with open(HISTORICO, "a", encoding="utf-8") as h:
            h.write(json.dumps({"em": AGORA, "base": fonte, "resultado": r["resultado"], "metodo": r.get("metodo"), "fonteUrl": r.get("fonteUrl"),
                                "conferidos": r.get("conferidos", 0), "comparados": r.get("comparados") or [], "divergentes": r.get("divergentes") or [],
                                **{k: r.get(k) for k in ("granularidade", "unidade", "unidadesBase", "unidadesConferidas", "idsConferidos", "registrosBase",
                                                         "registrosAbrangidos", "selecao", "responsavel", "metodologia")},
                                "nota": r.get("nota", ""), "coletaRunId": r.get("coletaRunId"), **({"hashes": r["hashes"]} if r.get("hashes") else {}),
                                **({"lacunas": r["lacunas"]} if r.get("lacunas") else {}),
                                **({"amostraContracheques": r["amostraContracheques"]} if r.get("amostraContracheques") else {}),
                                **{k: r[k] for k in ("independencia", "totaisDeOrgaoConferidos", "registrosConferidosUmAUm", "registrosPorTotais", "semFiltro",
                                                     "digestsUmAUm", "soNaFonte", "naoAchadosNaFonte", "divergentesRegistros", "fonteIndependente") if r.get(k) is not None}},
                               ensure_ascii=False) + "\n")
    out[fonte] = r
    return r


CONFERENCIAS = (("governo-ms", lambda: v_governo()), ("deputados-estaduais", lambda: v_alems()), ("senadores", lambda: v_senado()),
                ("deputados", lambda: v_camara()), ("arrecadacao", lambda: v_siconfi()), ("supersalarios", lambda: v_tjms()),
                ("shows", lambda: v_pncp("shows.json", "shows", "contratações de show", "shows", n=None)),
                ("votacoes", lambda: v_votacoes()), ("producao", lambda: v_producao()), ("judiciario", lambda: v_judiciario()),
                ("entidades", lambda: v_entidades()),
                # por último: o PNCP limita as consultas (429) e as esperas podem consumir o prazo do passo
                ("alugueis", lambda: v_pncp("alugueis.json", None, "contratações de aluguel", "alugueis", n=None)))


JANELA_COLETA_H = 2  # a conferência só entra no ICP se rodar na mesma coleta e até 2 h depois do início dela
RELATORIOS = DADOS / "verificacao" / "relatorios"


def janela_coleta(agora_utc=None):
    """(vale, motivo). Vale só dentro do robô (agendado ou disparado pela aba Actions — o que importa é ser a mesma
    coleta, não quem disparou): mesmo ID de coleta (GITHUB_RUN_ID do workflow "Atualizar dados
    diariamente", o mesmo cujos artefatos trouxeram os dados) e até JANELA_COLETA_H horas depois do início da coleta
    (COLETA_INICIO). Motivo (19/11/2026): uma conferência manual do Governo MS rodou ~11 h depois da coleta, a fonte já
    tinha pagamentos lançados depois, e a divergência entrou no ICP sem indicar erro nos dados."""
    from datetime import timezone
    run, wf, ini = os.environ.get("GITHUB_RUN_ID"), os.environ.get("GITHUB_WORKFLOW") or "", os.environ.get("COLETA_INICIO")
    if not run:
        return False, "fora do robô diário (sem ID de coleta)"
    if "Atualizar dados" not in wf:
        return False, f"workflow \"{wf}\" não é o da coleta"
    if not ini:
        return False, f"coleta {run} sem horário de início registrado"
    try:
        t_ini = datetime.fromisoformat(ini.replace("Z", "+00:00"))
    except ValueError:
        return False, f"horário de início ilegível ({ini})"
    agora_utc = agora_utc or datetime.now(timezone.utc)
    h = (agora_utc - t_ini).total_seconds() / 3600
    if h > JANELA_COLETA_H or h < 0:
        return False, f"{h:.1f} h depois do início da coleta {run} (limite {JANELA_COLETA_H} h)"
    return True, f"coleta {run}, {h:.1f} h depois do início"


def main():
    """Uso: python3 scripts/validar_fontes.py [base ...]   (sem argumento: todas)
    Fora da janela da coleta (rodada manual, por exemplo), só gera um relatório em dados/verificacao/relatorios/ — não
    entra no histórico nem na nota."""
    so = set(sys.argv[1:])
    vale, motivo = janela_coleta()
    if not vale:
        return relatorio_fora_da_janela(so, motivo)
    ant = J("validacao_fontes.json")
    out = dict(ant.get("fontes") or {})
    t0, prazo = time.monotonic(), int(os.environ.get("CONFERENCIA_PRAZO_MIN", "28")) * 60  # o passo do workflow tem 35 min
    for fonte, fn in CONFERENCIAS:
        if so and fonte not in so:
            continue
        if time.monotonic() - t0 > prazo:  # sem tempo: fica a conferência anterior da base, marcada
            if out.get(fonte):
                out[fonte] = {**out[fonte], "ultimaTentativa": AGORA, "ultimaTentativaResultado": "não conferida nesta coleta (tempo esgotado)"}
            print(f"  {fonte:20} não conferida nesta coleta (tempo esgotado) — fica a conferência anterior")
            continue
        try:
            r = fn()
        except Exception as e:
            r = {"resultado": "indisponivel", "em": AGORA, "nota": f"erro na conferência: {type(e).__name__}"}
        r = registrar(fonte, r, out)
        print(f"  {fonte:20} {r['resultado']:15} {r.get('conferidos', 0)} itens  {r.get('nota', '')}")
    SAIDA.write_text(json.dumps({"geradoEm": AGORA, "fontes": out}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"✅ validacao_fontes.json — {sum(1 for r in out.values() if r['resultado'] in ('confere', 'mudou_na_fonte'))} fontes conferidas, "
          f"{sum(1 for r in out.values() if r['resultado'] == 'diverge')} com divergência, {sum(1 for r in out.values() if r['resultado'] == 'indisponivel')} indisponíveis")


if __name__ == "__main__":
    sys.exit(main() or 0)
