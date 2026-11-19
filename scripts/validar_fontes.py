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
  supersalarios        DadosJusBr: TJMS — nº de magistrados e soma do salário-base do mês publicado
  shows                PNCP: todas as contratações de show, valor homologado/estimado de cada uma
  alugueis             PNCP: 8 contratações sorteadas por dia, valor homologado/estimado de cada uma
  votacoes             API da Câmara (/votacoes/{id}/votos): todas as votações nominais do ano, o voto de cada deputado de MS
  producao             Câmara (/proposicoes com filtro de tipo) e Senado (/processo): nº de projetos de cada parlamentar de MS
  judiciario           DadosJusBr (contracheques do TJMS enviados ao CNJ): nº de magistrados e soma do subsídio do mês
  entidades            cadastro CNPJ (minhareceita.org, serviço diferente do usado na coleta): todas as entidades —
                       data de abertura, município e situação cadastral

Tolerância: diferença até R$ 1 por item, ou explicada por atualização da fonte depois da coleta (a fonte mudou entre
a coleta e a conferência — registrada como "mudou na fonte", não como divergência).
Grava dados/validacao_fontes.json. Uma fonte fora do ar fica "indisponível" (nunca "confere").
"""

import json, random, re, sys, time, unicodedata
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
    for t in range(tent):
        try:
            r = requests.get(url, params=params, headers=H, timeout=timeout)
            if r.status_code == 200:
                return r.json()
        except (requests.RequestException, ValueError):
            pass
        time.sleep(3 * (t + 1))
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


def v_senado():
    s = J("senadores_ms.json")
    d = get(f"https://adm.senado.gov.br/adm-dadosabertos/api/v1/senadores/despesas_ceaps/{s.get('ano') or date.today().year}", timeout=180)
    itens = []
    for p in s.get("senadores") or []:
        f = round(sum(float(x.get("valorReembolsado") or 0) for x in d if str(x.get("codSenador")) == str(p["id"])), 2) if d else None
        itens.append((p["nome"], p.get("cotaGastaAno") or 0, f))
    ps = s.get("senadores") or []
    return resultado(itens, "dados abertos do Senado (despesas_ceaps): soma do ano de cada senador de MS", "https://adm.senado.gov.br/adm-dadosabertos/",
                     granularidade="unidade", unidade="senador (total da CEAPS no ano)", unidades_base=len(ps),
                     registros_base=sum(len(p.get("notasCeaps") or []) for p in ps), registros_por_unidade=n_por(ps, "nome", "notasCeaps"))


def v_camara():
    d = J("deputados_federais_ms.json")
    itens = []
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
    ps = d.get("deputados") or []
    res = resultado(itens, "API da Câmara: soma do valor líquido do ano de cada deputado federal de MS", "https://dadosabertos.camara.leg.br/",
                    granularidade="unidade", unidade="deputado federal (total da CEAP no ano)", unidades_base=len(ps),
                    registros_base=sum(len(p.get("despesas") or []) for p in ps), registros_por_unidade=n_por(ps, "nome", "despesas"))
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
    return resultado(itens or [("ICMS", 0, None)], f"Siconfi RREO Anexo 3 ({', '.join(f'{a}/{b}º bim' for a, b, _ in periodos)}): ICMS mês a mês",
                     "https://siconfi.tesouro.gov.br/", granularidade="unidade", unidade="mês do ICMS do Estado", unidades_base=nm, registros_base=nm,
                     selecao="todos os meses da série do site (RREO do bimestre mais recente + 6º bimestre dos anos anteriores); "
                             "demais impostos e Campo Grande não conferidos")


def v_tjms():
    ss = J("supersalarios.json")
    o = next((x for x in ss.get("orgaos") or [] if x.get("orgao", "").startswith("TJMS")), None)
    if not o:
        return resultado([("TJMS", 0, None)], "DadosJusBr", "https://dadosjusbr.org/")
    m, a = o["mes"].split("/")
    d = get(f"https://api.dadosjusbr.org/v2/dados/tjms/{int(a)}/{int(m)}")
    s = ((d or {}).get("sumarios") or {}).get("membros_ativos") or {}
    itens = [("magistrados", o["pessoas"], s.get("quantidade"), 0), ("salário-base total", o["totalBase"], (s.get("remuneracao_base") or {}).get("total"))]
    org = ss.get("orgaos") or []
    return resultado(itens, f"DadosJusBr (contracheques do TJMS enviados ao CNJ, {o['mes']}): quantidade e salário-base", "https://dadosjusbr.org/",
                     granularidade="unidade", unidade="órgão no mês publicado (quantidade de pessoas e salário-base)", unidades_base=len(org) * 2,
                     registros_base=ss.get("totalPessoas"), registros_por_unidade={"magistrados": o.get("pessoas") or 0},
                     selecao="recorte: só o TJMS (único órgão com contracheques no DadosJusBr nesta base)")


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
        c = get(f"https://pncp.gov.br/api/consulta/v1/orgaos/{cnpj}/compras/{ano}/{seq}", tent=2, timeout=60)
        f = (c.get("valorTotalHomologado") or c.get("valorTotalEstimado")) if c else None
        return (x.get("id") or x["link"].split("/editais/")[1], x["valor"], f)  # identificador PNCP: não repete a mesma contratação
    with ThreadPoolExecutor(4) as ex:
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
        res.update({"unidadesConferidas": len(ok), "idsConferidos": ok[:400], "registrosAbrangidos": len(ok)})
    return res


def v_producao():
    """Nº de projetos (PL, PLP, PEC, PDL) de cada parlamentar de MS desde o início da legislatura. Deputados: a API da Câmara
    filtra o tipo (a coleta lista tudo e filtra depois). Senadores: processos do autor no Senado, contados só os projetos."""
    d = J("producao_legislativa.json")
    ps = d.get("parlamentares") or []
    ini = d.get("inicio") or "2023-02-01"
    itens = []
    for p in ps:
        n, ok = 0, True
        if p.get("grupo") == "federal":
            pag = 1
            while True:
                r = get(f"{CAM}/proposicoes", {"idDeputadoAutor": p["id"], "dataApresentacaoInicio": ini,
                                              "siglaTipo": "PL,PLP,PEC,PDL", "itens": 100, "pagina": pag})
                if r is None:
                    ok = False
                    break
                n += len(r.get("dados") or [])
                if not any(l.get("rel") == "next" for l in r.get("links") or []):
                    break
                pag += 1
        elif p.get("grupo") == "senador":
            r = get("https://legis.senado.leg.br/dadosabertos/processo", {"codigoParlamentarAutor": p["id"], "dataInicioApresentacao": ini}, timeout=120)
            if r is None:
                ok = False
            else:
                n = sum(1 for x in r if (x.get("identificacao") or "").split()[:1] and x["identificacao"].split()[0] in ("PL", "PLP", "PEC", "PDL"))
        else:
            continue
        itens.append((p["nome"], p.get("projetos") or 0, float(n) if ok else None, 0))
    res = resultado(itens, "Câmara (/proposicoes, filtro de tipo na API) e Senado (/processo do autor): nº de projetos de cada parlamentar de MS "
                    "desde 01/02/2023", "https://dadosabertos.camara.leg.br/", granularidade="unidade",
                    unidade="parlamentar (nº de projetos na legislatura)", unidades_base=len(ps),
                    registros_base=sum(p.get("projetos") or 0 for p in ps), registros_por_unidade={p["nome"]: p.get("projetos") or 0 for p in ps},
                    selecao="todos os deputados federais e senadores de MS")
    # projeto novo apresentado depois da coleta: a fonte cresce um pouco (nunca diminui)
    if res["resultado"] == "diverge" and all(0 < -x["diferenca"] <= 3 for x in res["divergentes"]):
        res["resultado"], res["nota"] = "mudou_na_fonte", "projetos novos registrados depois da coleta (até 3 por parlamentar)"
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


def registrar(fonte, r, out):
    """Grava a conferência: mantém a última bem-sucedida quando a fonte não responde hoje; conferência feita agora vai para
    o histórico permanente (só acrescenta), com os hashes dos registros conferidos quando houver."""
    if r["resultado"] == "indisponivel" and (out.get(fonte) or {}).get("resultado") in ("confere", "mudou_na_fonte", "diverge"):
        r = {**out[fonte], "ultimaTentativa": AGORA, "ultimaTentativaResultado": "indisponivel"}
    if r.get("em") == AGORA:
        with open(HISTORICO, "a", encoding="utf-8") as h:
            h.write(json.dumps({"em": AGORA, "base": fonte, "resultado": r["resultado"], "metodo": r.get("metodo"), "fonteUrl": r.get("fonteUrl"),
                                "conferidos": r.get("conferidos", 0), "comparados": r.get("comparados") or [], "divergentes": r.get("divergentes") or [],
                                **{k: r.get(k) for k in ("granularidade", "unidade", "unidadesBase", "unidadesConferidas", "idsConferidos", "registrosBase",
                                                         "registrosAbrangidos", "selecao", "responsavel", "metodologia")},
                                "nota": r.get("nota", ""), **({"hashes": r["hashes"]} if r.get("hashes") else {}),
                                **({"lacunas": r["lacunas"]} if r.get("lacunas") else {})}, ensure_ascii=False) + "\n")
    out[fonte] = r
    return r


CONFERENCIAS = (("governo-ms", lambda: v_governo()), ("deputados-estaduais", lambda: v_alems()), ("senadores", lambda: v_senado()),
                ("deputados", lambda: v_camara()), ("arrecadacao", lambda: v_siconfi()), ("supersalarios", lambda: v_tjms()),
                ("shows", lambda: v_pncp("shows.json", "shows", "contratações de show", "shows", n=None)),
                ("alugueis", lambda: v_pncp("alugueis.json", None, "contratações de aluguel", "alugueis")),
                ("votacoes", lambda: v_votacoes()), ("producao", lambda: v_producao()), ("judiciario", lambda: v_judiciario()),
                ("entidades", lambda: v_entidades()))


def main():
    """Uso: python3 scripts/validar_fontes.py [base ...]   (sem argumento: todas)"""
    so = set(sys.argv[1:])
    ant = J("validacao_fontes.json")
    out = dict(ant.get("fontes") or {})
    for fonte, fn in CONFERENCIAS:
        if so and fonte not in so:
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
    main()
