#!/usr/bin/env python3
"""
Cofre Aberto MS — Auditoria automática: sinais de atenção nas contas públicas

Cruza as notas dos parlamentares de MS, as despesas, contratos e licitações da
Prefeitura de Campo Grande e o cadastro das empresas na Receita Federal
(dados/cnpj_cache.json, coletar_cnpj.py) e aponta padrões que costumam aparecer
em irregularidades. Um sinal NÃO é acusação: é um critério objetivo que merece
um olhar humano — muitos têm explicação legal. Cada sinal traz a regra que o
disparou, os números e os links para conferir na fonte.

Testes (os de muitos falsos positivos — Lei de Benford, valor redondo mensal —
ficaram de fora depois do teste com os dados de nov/2026):
  mei_acima_limite      MEI que recebeu de órgãos públicos mais que o limite anual
                        de faturamento do MEI (R$ 81 mil em 2026)
  situacao_irregular    empresa baixada, inapta, suspensa ou nula que recebeu depois disso
  socio_parlamentar     sócio da empresa com o mesmo nome completo do parlamentar que a pagou
  socios_licitacao      empresas com sócio em comum vencendo a mesma licitação
  empresa_nova          empresa aberta até 6 meses antes do 1º pagamento, com valor alto
  atividade_incompativel nenhuma atividade da empresa (principal ou secundária) combina
                        com o tipo de despesa
  cliente_unico         notas em sequência quase contínua para um só gabinete, e a
                        empresa não recebe de nenhum outro órgão que o site cobre
  capital_baixo         capital social muito baixo para o volume recebido
  gasto_acima_colegas   gasto mensal numa categoria muito acima dos colegas do mesmo cargo
  socio_doador          sócio da empresa (nome + 6 dígitos do CPF) doou para a campanha do
                        parlamentar que hoje paga a empresa com a cota/verba (TSE)
  fornecedor_campanha   empresa contratada pela campanha que depois passou a receber da cota
  servidor_socio_pagador sócio é servidor ativo do Governo de MS (nome + CPF parcial), que paga a empresa
  servidor_socio        sócio é servidor público ativo (Estado, ALEMS ou Câmara CG) e a empresa
                        recebe de parlamentar ou da Prefeitura
  endereco_comum        empresas diferentes, pagas pelo mesmo parlamentar ou vencedoras da mesma
                        licitação, com o mesmo endereço ou telefone na Receita
  dispensa_acima_limite um mesmo processo de dispensa somando mais que o limite legal
                        (exclui aluguel de imóvel, bancos e concessionárias, que têm
                        outra base legal)

Gera dados/auditoria.json (guarda "vistoEm" de cada sinal, para o boletim).
"""

import hashlib, json, re, statistics, unicodedata
from datetime import date, datetime, timedelta

from gerar_analises import ANO, DADOS, carregar, cnpj_valido, limpa_nome, salvar

HOJE = date.today()
LIMITE_MEI = 81000.0
LIM_DISPENSA, LIM_DISPENSA_OBRA = 65492.11, 130984.20  # Decreto 12.807/2025, desde 1º/1/2026
NIVEL = {"mei_acima_limite": "forte", "situacao_irregular": "forte", "socio_parlamentar": "forte",
         "socios_licitacao": "médio", "dispensa_acima_limite": "forte", "empresa_nova": "médio",
         "atividade_incompativel": "médio", "cliente_unico": "médio", "capital_baixo": "médio",
         "gasto_acima_colegas": "médio", "socio_doador": "forte", "fornecedor_campanha": "médio",
         "servidor_socio_pagador": "forte", "servidor_socio": "médio", "endereco_comum": "médio"}
ROTULO = {"mei_acima_limite": "MEI acima do limite de faturamento", "situacao_irregular": "Empresa com CNPJ irregular",
          "socio_parlamentar": "Parlamentar é sócio", "socios_licitacao": "Sócios em comum na mesma licitação",
          "dispensa_acima_limite": "Possível fracionamento de dispensa", "empresa_nova": "Empresa recém-aberta",
          "atividade_incompativel": "Atividade não combina com o serviço", "cliente_unico": "Fornecedor de um cliente só",
          "capital_baixo": "Capital social muito baixo", "gasto_acima_colegas": "Gasto muito acima dos colegas",
          "socio_doador": "Sócio doou para a campanha", "fornecedor_campanha": "Fornecedor da campanha pago pela cota",
          "servidor_socio_pagador": "Sócio é servidor do órgão que paga", "servidor_socio": "Sócio é servidor público",
          "endereco_comum": "Endereço ou telefone em comum"}

# naturezas jurídicas de empresa privada (associações, fundos, órgãos e consórcios públicos não têm capital social)
EMPRESARIAL = re.compile(r"Limitada|Empres[aá]rio|EIRELI|Unipessoal|Sociedade Simples|An[oô]nima Fechada", re.I)

# tipo de despesa → começos de CNAE (classe) compatíveis
CNAE_OK = [
    (r"combust|lubrific", ["4731", "4732", "4681", "4930", "4789"]),
    (r"passage|a[eé]re|bilhete", ["511", "791", "4929", "5229"]),
    (r"hosped", ["551", "559", "791"]),
    (r"aliment|refei", ["561", "562", "472", "471", "107", "108", "109"]),
    (r"locomo|loca[çc][aã]o de ve|locação ou fretamento|frete|transporte|ve[ií]culo|t[aá]xi", ["771", "492", "493", "501", "511", "791", "4731", "452", "4930", "4923", "4929", "551", "561"]),
    (r"divulga|publicid|propaganda|m[ií]dia|marketing|impress|gr[aá]fic|redes sociais|comunica", ["731", "732", "181", "182", "58", "59", "60", "631", "639", "741", "742", "749", "90", "62", "70", "82", "4761", "4789"]),
    (r"consult|assessor|pesquis|trabalhos t[eé]cnicos|jur[ií]dic|advoc|cont[aá]b|parecer", ["69", "70", "71", "72", "73", "74", "78", "82", "85", "62", "63", "64", "66", "94", "9001", "9002"]),
    (r"telefon|internet|telecom", ["61", "4752", "4753", "62", "63"]),
    (r"seguran", ["80"]),
    (r"fotograf|filmag|v[ií]deo|cobertura", ["742", "591", "592", "731", "90"]),
    (r"software|sistema|inform[aá]tica|assinatura|postal|correio|tv a cabo", ["62", "63", "58", "53", "61", "77", "4751", "951"]),
    (r"im[oó]ve|escrit[oó]rio|aluguel|condom[ií]n|limpeza|conserva|energia|[aá]gua", ["68", "81", "43", "35", "36", "41", "47", "46", "95", "80", "77", "82", "64"]),
]


def dig(t):
    return re.sub(r"\D", "", str(t or ""))


def norm(t):
    return re.sub(r"\s+", " ", unicodedata.normalize("NFD", str(t or "")).encode("ascii", "ignore").decode().upper()).strip()


def brl(v):
    return "R$ " + f"{float(v or 0):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def data_br(iso):
    return f"{iso[8:10]}/{iso[5:7]}/{iso[:4]}" if iso and len(iso) >= 10 else (iso or "—")


def notas_parlamentares():
    pags = carregar("paginas_index.json") or {}
    out = []
    def add(grupo, rotulo, aba, v, n, cnpj, nf, cat):
        out.append({"p": v["nome"], "nomeCompleto": v.get("nomeCompleto") or v.get("nome"), "grupo": grupo, "rotulo": rotulo,
                    "aba": aba, "url": pags.get(f"{grupo}|{v['nome']}"), "forn": limpa_nome(n.get("fornecedor")),
                    "cnpj": dig(cnpj), "valor": float(n.get("valor") or 0), "nf": nf, "data": n.get("data"), "cat": cat or ""})
    for v in carregar("camara_municipal.json").get("vereadores", []):
        for n in v.get("despesas") or []:
            nf = n.get("nf") or (re.search(r"N[ºo°]?\.?\s*(\d{1,7})\s*/?U?\b", n.get("descricao") or "") or [None, None])[1]
            add("vereador", "Vereador(a) CG", "camara", v, n, n.get("cnpj"), nf, n.get("descricao") or n.get("ato"))
    for v in carregar("deputados_estaduais_ms.json").get("vereadores", []):
        for n in v.get("despesas") or []:
            add("estadual", "Dep. estadual", "deputados-estaduais", v, n, n.get("cnpj"), n.get("nf"), n.get("categoria"))
    for v in carregar("deputados_federais_ms.json").get("deputados", []):
        for n in v.get("despesas") or []:
            add("federal", "Dep. federal", "deputados", v, n, n.get("cnpjCpfFornecedor"), n.get("doc") or n.get("numDocumento"), n.get("categoria"))
    for v in carregar("senadores_ms.json").get("senadores", []):
        for n in v.get("notasCeaps") or []:
            add("senador", "Senador(a)", "senadores", v, n, n.get("cnpjCpf"), n.get("doc"), n.get("categoria"))
    return out


def main():
    cad = carregar("cnpj_cache.json") or {}
    notas = notas_parlamentares()
    emp_idx = carregar("empresas_index.json") or {}
    anterior = {s["id"]: s for s in (carregar("auditoria.json") or {}).get("sinais", [])}
    sinais = []

    def add(teste, chave, titulo, descricao, valor, evid, quem=None, cnpj=None, link=None):
        i = hashlib.sha1(("|".join([teste] + [str(c) for c in chave])).encode()).hexdigest()[:12]
        c = dig(cnpj)
        sinais.append({"id": i, "teste": teste, "rotulo": ROTULO[teste], "nivel": NIVEL[teste], "titulo": titulo,
                       "descricao": descricao, "valor": round(valor or 0, 2), "evidencias": evid, "quem": quem,
                       "cnpj": c or None, "empresa": (cad.get(c) or {}).get("razao") if c else None,
                       "paginaEmpresa": f"/empresa/{c[:8]}/" if c and c[:8] in emp_idx else None, "link": link,
                       "vistoEm": anterior.get(i, {}).get("vistoEm") or HOJE.isoformat()})

    # recebimentos por empresa (CNPJ completo) e por pagador
    por_cnpj = {}
    for n in notas:
        if len(n["cnpj"]) == 14 and cnpj_valido(n["cnpj"]):
            e = por_cnpj.setdefault(n["cnpj"], {"total": 0.0, "pagadores": {}, "primeira": None, "notas": []})
            e["total"] += n["valor"]
            pg = e["pagadores"].setdefault(n["p"], {"total": 0.0, "n": n})
            pg["total"] += n["valor"]
            e["primeira"] = min(filter(None, [e["primeira"], n["data"]]), default=None)
            e["notas"].append(n)
    pref = carregar("prefeitura.json")
    pref_raiz, pref_cnpj, pref_emp = {}, {}, {}
    for x in pref.get("despesas", []) if pref.get("ano") == ANO else []:
        c = dig(x.get("cnpj"))
        if len(c) == 14:
            pref_raiz[c[:8]] = pref_raiz.get(c[:8], 0) + (x.get("valor") or 0)
            pref_cnpj[c] = pref_cnpj.get(c, 0) + (x.get("valor") or 0)
            pref_emp.setdefault(c, []).append(x)
    gov_raiz, gov_cnpj = {}, {}
    for c in (carregar("governo_ms_credores.json") or {}).get("credores", []):
        d = dig(c[0])
        if len(d) == 14:
            gov_raiz[d[:8]] = gov_raiz.get(d[:8], 0) + (c[2] or 0)
            if len(c) > 4 and c[4] == "fornecedor":
                gov_cnpj[d] = gov_cnpj.get(d, 0) + (c[2] or 0)
    ct = carregar("prefeitura_contratos.json")
    contratos = ct.get("contratos", []) if ct.get("ano") == ANO else []
    licit = ct.get("licitacoes", []) if ct.get("ano") == ANO else []
    ctr_cnpj = {}
    for c in contratos:
        d = dig(c.get("cnpj"))
        if len(d) == 14 and c.get("compra"):
            ctr_cnpj[d] = ctr_cnpj.get(d, 0) + c["valor"]

    def total_publico(c):
        return por_cnpj.get(c, {}).get("total", 0) + pref_cnpj.get(c, 0)

    # ── MEI acima do limite, situação irregular, capital baixo, empresa nova ──
    for c, info in cad.items():
        if info.get("naoEncontrado"):
            continue
        rec_parl = por_cnpj.get(c, {}).get("total", 0)
        rec_pref = pref_cnpj.get(c, 0)
        rec_gov = gov_cnpj.get(c, 0)
        rec = rec_parl + rec_pref + rec_gov
        nome = info.get("razao") or c
        quem_lst = sorted(por_cnpj.get(c, {}).get("pagadores", {}).items(), key=lambda kv: -kv[1]["total"])
        quem = ", ".join([f"{p} ({brl(v['total'])})" for p, v in quem_lst[:3]] + ([f"Prefeitura de CG ({brl(rec_pref)})"] if rec_pref else [])
                         + ([f"Governo de MS ({brl(rec_gov)})"] if rec_gov else []))
        # quem pagou mais, para o placar
        maior = max([(v["total"], p) for p, v in quem_lst] + [(rec_pref, "Prefeitura de CG"), (rec_gov, "Governo de MS")])[1]
        if info.get("mei") and rec > LIMITE_MEI:
            add("mei_acima_limite", (c,), f"{nome}: MEI recebeu {brl(rec)} de órgãos públicos em {ANO}",
                f"A empresa está registrada como MEI, cujo limite de faturamento em {ANO} é {brl(LIMITE_MEI)} por ano — só os pagamentos "
                f"públicos que o site acompanha já passam disso. Quem pagou: {quem}.",
                rec, [f"Opção pelo MEI: sim (Receita Federal, consulta em {data_br(info.get('consultadoEm'))})",
                      f"Recebido de parlamentares: {brl(rec_parl)}", f"Recebido da Prefeitura de CG: {brl(rec_pref)}",
                      f"Pago pelo Governo de MS: {brl(rec_gov)}"], maior, c)
        sit = (info.get("situacao") or "").upper()
        dt = info.get("dataSituacao") or ""
        if sit and sit != "ATIVA" and rec > 0 and dt:
            # só conta o que foi emitido/empenhado DEPOIS da data da situação (nota fiscal de CNPJ baixado ou inapto)
            depois = [(n["data"], n["valor"], n["p"]) for n in por_cnpj.get(c, {}).get("notas", []) if (n.get("data") or "") >= dt]
            depois += [(x["data"], x.get("empenhado") or x.get("valor") or 0, "Prefeitura de CG") for x in pref_emp.get(c, []) if (x.get("data") or "") >= dt]
            v = sum(d_[1] for d_ in depois)
            if v >= 1000:
                st = {"BAIXADA": "baixado", "INAPTA": "inapto", "SUSPENSA": "suspenso", "NULA": "nulo"}.get(sit, sit.lower())
                pag = {}
                for d_ in depois:
                    pag[d_[2]] = pag.get(d_[2], 0) + d_[1]
                pq = sorted(pag.items(), key=lambda kv: -kv[1])
                add("situacao_irregular", (c,), f"{nome}: CNPJ {st} desde {data_br(dt)} e com pagamentos depois disso",
                    f"A Receita registra o CNPJ como {sit.lower()} ({(info.get('motivoSituacao') or 'motivo não informado').lower()}) "
                    f"desde {data_br(dt)}. Depois dessa data, há {len(depois)} nota(s) ou empenho(s) somando {brl(v)}: "
                    + ", ".join(f"{p} ({brl(x)})" for p, x in pq[:3]) + ". A nota pode ser de serviço prestado antes, ou a situação "
                    f"pode ter sido regularizada depois da consulta.",
                    v, [f"Situação cadastral: {sit} desde {data_br(dt)} (consulta em {data_br(info.get('consultadoEm'))})"]
                    + [f"{data_br(d_[0])}: {brl(d_[1])} — {d_[2]}" for d_ in sorted(depois)[:5]], pq[0][0], c)
            elif rec_gov >= 1000 and dt < f"{ANO}-01-01":
                # o Governo só publica o total pago no ano; a situação é anterior a todo o ano
                st = {"BAIXADA": "baixado", "INAPTA": "inapto", "SUSPENSA": "suspenso", "NULA": "nulo"}.get(sit, sit.lower())
                add("situacao_irregular", (c, "gov"), f"{nome}: CNPJ {st} desde {data_br(dt)} e pago pelo Governo de MS em {ANO}",
                    f"A Receita registra o CNPJ como {sit.lower()} ({(info.get('motivoSituacao') or 'motivo não informado').lower()}) "
                    f"desde {data_br(dt)}, e o Governo do Estado pagou {brl(rec_gov)} à empresa em {ANO}. Pode ser pagamento de "
                    f"restos a pagar por serviço prestado antes da baixa — o portal estadual não mostra a data de cada nota.",
                    rec_gov, [f"Situação cadastral: {sit} desde {data_br(dt)} (consulta em {data_br(info.get('consultadoEm'))})",
                              f"Pago pelo Governo de MS em {ANO}: {brl(rec_gov)}"], "Governo de MS", c, "#aba=governo-ms")
        cap = info.get("capital")
        if cap is not None and cap <= 10000 and rec >= 300000 and EMPRESARIAL.search(info.get("natureza") or ""):
            add("capital_baixo", (c,), f"{nome}: capital social de {brl(cap)} e {brl(rec)} recebidos",
                f"Empresa com capital social de {brl(cap)} recebeu {brl(rec)} de órgãos públicos em {ANO}. Capital baixo é comum em "
                f"prestadoras de serviço, mas destoa do volume. Quem pagou: {quem}.", rec,
                [f"Capital social: {brl(cap)}", f"Porte: {info.get('porte') or '—'}"], maior, c)
        ab = info.get("abertura")
        if ab:
            for p, pg in quem_lst:
                prim = min(n["data"] for n in por_cnpj[c]["notas"] if n["p"] == p and n.get("data")) if any(n.get("data") for n in por_cnpj[c]["notas"] if n["p"] == p) else None
                if prim and pg["total"] >= 30000:
                    dias = (date.fromisoformat(prim[:10]) - date.fromisoformat(ab)).days
                    if 0 <= dias <= 180:
                        add("empresa_nova", (c, p), f"{nome}: aberta {dias} dias antes do 1º pagamento de {p}",
                            f"A empresa foi aberta em {data_br(ab)} e recebeu a primeira nota de {p} em {data_br(prim)}; "
                            f"somou {brl(pg['total'])} em {ANO}.", pg["total"],
                            [f"Abertura: {data_br(ab)}", f"Primeira nota: {data_br(prim)}", f"Atividade principal: {info.get('cnaeDesc') or '—'}"], p, c)
            for x in contratos:
                if dig(x.get("cnpj")) == c and x.get("compra") and x["valor"] >= 500000 and x.get("inicio"):
                    dias = (date.fromisoformat(x["inicio"]) - date.fromisoformat(ab)).days
                    if 0 <= dias <= 365:
                        add("empresa_nova", (c, x["inicio"], x["valor"]), f"{nome}: contrato de {brl(x['valor'])} com empresa aberta {dias} dias antes",
                            f"A empresa foi aberta em {data_br(ab)} e assinou contrato com a Prefeitura de Campo Grande em {data_br(x['inicio'])}: {x['objeto'][:180]}.",
                            x["valor"], [f"Abertura: {data_br(ab)}", f"Início do contrato: {data_br(x['inicio'])}"], "Prefeitura de CG", c, "#aba=contratos-cg")
            if rec_gov >= 1_000_000 and ab >= f"{ANO - 1}-01-01":
                add("empresa_nova", (c, "gov"), f"{nome}: aberta em {data_br(ab)} e já recebeu {brl(rec_gov)} do Governo de MS",
                    f"A empresa foi aberta em {data_br(ab)} e recebeu {brl(rec_gov)} do Governo do Estado em {ANO}. "
                    f"Empresa nova com contrato grande pode ser legítima, mas vale conferir a experiência exigida na licitação.",
                    rec_gov, [f"Abertura: {data_br(ab)}", f"Atividade principal: {info.get('cnaeDesc') or '—'}",
                              f"Capital social: {brl(info.get('capital'))}"], "Governo de MS", c, "#aba=governo-ms")

    # ── Campanhas (TSE): sócio = parlamentar, sócio doador e fornecedor da campanha ──
    tse = (carregar("tse_campanhas.json") or {}).get("parlamentares", {})
    grupo_de = {}
    for n in notas:
        grupo_de[n["p"]] = n["grupo"]
    camp = {}  # nome do parlamentar no site → dados de campanha
    for k, d in tse.items():
        camp[k.split("|", 1)[1]] = d

    def mesma_pessoa(nome_socio, cpf_socio, nome, cpf):
        """Mesmo nome e, se os dois lados têm, os mesmos 6 dígitos do meio do CPF."""
        if norm(nome_socio) != norm(nome):
            return False
        if cpf_socio and cpf:
            return cpf_socio == cpf
        return len(norm(nome).split()) >= 3

    def pagos_por(c):
        """Quem pagou a empresa: {pagador: valor}."""
        out = {p: v["total"] for p, v in por_cnpj.get(c, {}).get("pagadores", {}).items()}
        if pref_cnpj.get(c):
            out["Prefeitura de CG"] = pref_cnpj[c]
        if gov_cnpj.get(c):
            out["Governo de MS"] = gov_cnpj[c]
        return out

    parl_pessoas = []  # (nome no site, nome civil, cpf6)
    vistos_p = set()
    for n in notas:
        if n["p"] in vistos_p:
            continue
        vistos_p.add(n["p"])
        d = camp.get(n["p"]) or {}
        parl_pessoas.append((n["p"], d.get("nomeCompleto") or n["nomeCompleto"], d.get("cpf6")))
    for c, info in cad.items():
        socios = info.get("socios") or []
        if not socios or not EMPRESARIAL.search(info.get("natureza") or ""):  # fundações e associações têm outra regra
            continue
        pg = pagos_por(c)
        if not pg:
            continue
        for p, civil, cpf in parl_pessoas:
            for q in socios:
                if not mesma_pessoa(q.get("nome"), q.get("cpf"), civil, cpf):
                    continue
                # pela cota, pela Prefeitura ou pelo Estado: empresa de quem tem mandato recebendo dinheiro público
                conf = "nome completo e os 6 dígitos do meio do CPF iguais aos do registro de candidatura no TSE" if (q.get("cpf") and cpf) \
                    else "mesmo nome completo (pode ser homônimo: a Receita não mostrou o CPF parcial)"
                add("socio_parlamentar", (c, p), f"{info.get('razao') or c}: {p} aparece como sócio(a)",
                    f"O quadro de sócios na Receita tem {q['nome']} ({q.get('qualificacao') or 'sócio'}) — {conf}. A empresa recebeu: "
                    + ", ".join(f"{k} ({brl(v)})" for k, v in sorted(pg.items(), key=lambda kv: -kv[1])[:4])
                    + ". A lei proíbe que parlamentar seja dono de empresa que tenha contrato com o poder público ou que receba da própria cota.",
                    sum(pg.values()), [f"Sócio: {q['nome']} — {q.get('qualificacao') or ''}, desde {data_br(q.get('entrada'))}",
                                       f"Parlamentar: {p} ({civil})"], p if p in pg else max(pg, key=pg.get), c)
                break

    for p, d in camp.items():
        doad = d.get("doadores") or {}
        forn = d.get("fornecedores") or {}
        for c, e in por_cnpj.items():
            pg = e["pagadores"].get(p)
            if not pg or pg["total"] < 1000:
                continue
            info = cad.get(c) or {}
            for q in info.get("socios") or []:
                dd = doad.get(norm(q.get("nome")))
                if dd and mesma_pessoa(q["nome"], q.get("cpf"), dd[0], dd[2] if len(dd) > 2 else None):
                    conf = "nome e 6 dígitos do meio do CPF iguais" if q.get("cpf") and len(dd) > 2 and dd[2] else "mesmo nome completo"
                    add("socio_doador", (c, p, norm(q["nome"])), f"{info.get('razao') or c}: sócio doou {brl(dd[1])} à campanha de {p}",
                        f"{q['nome']} ({q.get('qualificacao') or 'sócio'}) doou {brl(dd[1])} para a campanha de {p} em {d['ano']} ({conf}, "
                        f"segundo o TSE e a Receita). Depois, {p} pagou {brl(pg['total'])} à empresa com a cota/verba em {ANO}. "
                        f"Doar e depois prestar serviço não é proibido, mas é um conflito de interesse que merece transparência.",
                        pg["total"], [f"Doação em {d['ano']}: {brl(dd[1])} (TSE — prestação de contas)",
                                      f"Pago pela cota/verba em {ANO}: {brl(pg['total'])}", f"Sócio desde {data_br(q.get('entrada'))}"],
                        p, c, pg["n"]["url"])
            fc = forn.get(c) or next((v for k, v in forn.items() if k[:8] == c[:8]), None)
            # só serviços de confiança pessoal (advocacia, contabilidade, marketing, consultoria, comunicação) de quem atende
            # no máximo 2 parlamentares — posto, locadora, gráfica e rede social atendem todo mundo, na campanha e fora dela
            cnaes = [info.get("cnae") or ""]
            pessoal = any(cn.startswith(x) for cn in cnaes for x in ("69", "70", "73", "74", "59", "82", "62", "90", "94"))
            if fc and pg["total"] >= 10000 and pessoal and len(e["pagadores"]) <= 2:
                add("fornecedor_campanha", (c, p), f"{info.get('razao') or fc[0]}: trabalhou na campanha de {p} e hoje recebe da cota",
                    f"A campanha de {p} em {d['ano']} contratou a empresa por {brl(fc[1])} ({fc[2].strip().lower() or 'despesa'}); em {ANO} o "
                    f"mandato pagou {brl(pg['total'])} a ela com a cota/verba. É comum manter a mesma agência ou gráfica, mas a cota "
                    f"não pode pagar dívida nem serviço de campanha.",
                    pg["total"], [f"Contratada pela campanha ({d['ano']}): {brl(fc[1])}", f"Pago pela cota/verba em {ANO}: {brl(pg['total'])}"],
                    p, c, pg["n"]["url"])

    # ── Sócio é servidor público ──
    ss = carregar("servidores_socios.json") or {}
    por_emp = {}
    for x in ss.get("achados", []):
        if EMPRESARIAL.search((cad.get(x["cnpj"]) or {}).get("natureza") or ""):  # federações, conselhos e associações ficam de fora
            por_emp.setdefault(x["cnpj"], []).append(x)
    for c, lst in por_emp.items():
        pg = pagos_por(c)
        if not pg or sum(pg.values()) < 5000:
            continue
        orgs = sorted({x["orgao"] for x in lst})
        quem_s = "; ".join(f"{x['nome']} ({x['cargo'].lower()}, {x['orgao']})" for x in lst[:6]) + (f" e mais {len(lst) - 6}" if len(lst) > 6 else "")
        emp = lst[0].get("empresa") or c
        plural = len(lst) > 1
        if "Governo de MS" in pg:
            add("servidor_socio_pagador", (c,), f"{emp}: {len(lst)} sócio(s) {'são servidores ativos' if plural else 'é servidor(a) ativo(a)'} do Governo de MS",
                f"Na folha do Estado de {ss.get('mesFolha')} {'estão' if plural else 'está'}, com o mesmo nome e os mesmos 6 dígitos do meio do CPF "
                f"do quadro de sócios: {quem_s}. O Governo pagou {brl(pg['Governo de MS'])} à empresa em {ANO}. A Lei 14.133/2021 (art. 9º) proíbe "
                f"contratar empresa de servidor do órgão contratante; o portal não mostra qual secretaria pagou — se for outro órgão, pode ser legal.",
                pg["Governo de MS"], [f"Órgãos dos servidores: {', '.join(orgs)}"] + [f"{x['nome']}: {x.get('qualificacao') or 'sócio'} desde {data_br(x.get('entradaSociedade'))}" for x in lst[:5]],
                "Governo de MS", c, "#aba=governo-ms")
        else:
            add("servidor_socio", (c,), f"{emp}: {len(lst)} sócio(s) {'são servidores ativos' if plural else 'é servidor(a) ativo(a)'} do Governo de MS",
                f"Na folha do Estado {'estão' if plural else 'está'}, com o mesmo nome e os mesmos 6 dígitos do meio do CPF: {quem_s}. A empresa recebeu: "
                + ", ".join(f"{k} ({brl(v)})" for k, v in pg.items()) + ". Servidor pode ser sócio cotista, mas em geral não pode administrar a empresa.",
                sum(pg.values()), [f"Órgãos: {', '.join(orgs)}"], max(pg, key=pg.get), c)
    # ALEMS e Câmara CG: só o nome é publicado (sem CPF) — exige nome com 3+ palavras, único na folha, e pagamento da própria casa
    for arq, chave, grupo_pag, casa in (("alems_servidores.json", None, "estadual", "ALEMS"), ("camara_municipal.json", "servidoresNomes", "vereador", "Câmara de CG")):
        j = carregar(arq) or {}
        lst = [(x["nome"], x.get("cargo")) for x in j.get("servidores", [])] if chave is None else \
              [(x[0], x[1]) for x in (j.get(chave) or {}).get("lista", [])]
        cont = {}
        for nm, _ in lst:
            cont[norm(nm)] = cont.get(norm(nm), 0) + 1
        idx = {norm(nm): cg for nm, cg in lst if cont[norm(nm)] == 1 and len(norm(nm).split()) >= 3}
        for c, e in por_cnpj.items():
            pag = {p: v["total"] for p, v in e["pagadores"].items() if grupo_de.get(p) == grupo_pag}
            if not pag or sum(pag.values()) < 5000:
                continue
            for q in (cad.get(c) or {}).get("socios") or []:
                cg = idx.get(norm(q.get("nome")))
                if cg is not None:
                    add("servidor_socio", (c, casa, norm(q["nome"])), f"{cad[c].get('razao') or c}: sócio(a) com o nome de um(a) servidor(a) da {casa}",
                        f"{q['nome']} ({q.get('qualificacao') or 'sócio'}) tem o mesmo nome de um(a) servidor(a) da {casa} ({(cg or 'cargo não informado').lower()}), "
                        f"e a empresa recebeu da verba de: " + ", ".join(f"{p} ({brl(v)})" for p, v in sorted(pag.items(), key=lambda kv: -kv[1])[:3])
                        + f". A {casa} não publica o CPF dos servidores, então pode ser homônimo.",
                        sum(pag.values()), [f"Servidor(a) da {casa}: {q['nome']} — {cg or '—'}"], max(pag, key=pag.get), c)

    # ── Endereço ou telefone em comum (mesmo pagador ou mesma licitação) ──
    por_end, por_tel = {}, {}
    for c, info in cad.items():
        if info.get("naoEncontrado") or not EMPRESARIAL.search(info.get("natureza") or ""):
            continue
        if info.get("endereco") and re.search(r"\d", info["endereco"]) and info.get("cep"):
            por_end.setdefault(norm(info["endereco"]) + "|" + info["cep"], set()).add(c[:8])
        for t in info.get("telefones") or []:
            por_tel.setdefault(t, set()).add(c[:8])
    raiz_cnpj = {}
    for c in cad:
        raiz_cnpj.setdefault(c[:8], c)

    def ligacoes(a, b):
        ia, ib = cad.get(a) or {}, cad.get(b) or {}
        out = []
        ka = norm(ia.get("endereco")) + "|" + str(ia.get("cep"))
        if ia.get("endereco") and ka == norm(ib.get("endereco")) + "|" + str(ib.get("cep")) and 2 <= len(por_end.get(ka, ())) <= 4:
            out.append(f"mesmo endereço ({ia['endereco']}, CEP {ia['cep']})")
        for t in set(ia.get("telefones") or []) & set(ib.get("telefones") or []):
            if 2 <= len(por_tel.get(t, ())) <= 4:
                out.append(f"mesmo telefone ({t[:2]}) {t[2:]}")
        return out

    for p in {n["p"] for n in notas}:
        emp = sorted({c for c, e in por_cnpj.items() if p in e["pagadores"] and c in cad})
        for i in range(len(emp)):
            for j in range(i + 1, len(emp)):
                a, b = emp[i], emp[j]
                if a[:8] == b[:8]:
                    continue
                lig = ligacoes(a, b)
                if lig:
                    va, vb = por_cnpj[a]["pagadores"][p]["total"], por_cnpj[b]["pagadores"][p]["total"]
                    if va + vb < 5000:
                        continue
                    add("endereco_comum", (p, a, b), f"{cad[a].get('razao')} e {cad[b].get('razao')}: {lig[0].split(' (')[0]}, mesmo pagador",
                        f"As duas empresas receberam de {p} ({brl(va)} e {brl(vb)}) e têm {' e '.join(lig)} na Receita. Pode ser o mesmo "
                        f"escritório de contabilidade ou um prédio comercial; também pode indicar empresas do mesmo grupo.",
                        va + vb, [f"{cad[a].get('razao')}: sócios {', '.join(q['nome'] for q in cad[a].get('socios', [])[:3]) or '—'}",
                                  f"{cad[b].get('razao')}: sócios {', '.join(q['nome'] for q in cad[b].get('socios', [])[:3]) or '—'}"], p, a)
    for l in licit:
        if re.search(r"chamada|credenciamento|inexig|dispensa", l.get("modalidade") or "", re.I):
            continue
        venc = sorted({dig(w.get("cnpj")) for w in l.get("vencedores", []) if len(dig(w.get("cnpj"))) == 14})
        for i in range(len(venc)):
            for j in range(i + 1, len(venc)):
                a, b = venc[i], venc[j]
                if a[:8] == b[:8]:
                    continue
                lig = ligacoes(a, b)
                if lig:
                    add("endereco_comum", (l["processo"], a, b), f"{l['modalidade']} nº {l['numero']}: vencedoras com {lig[0].split(' (')[0]}",
                        f"{cad[a].get('razao')} e {cad[b].get('razao')} venceram a mesma licitação ({l['objeto'][:140]}) e têm {' e '.join(lig)} "
                        f"na Receita. Em licitação por lotes, empresas do mesmo grupo podem vencer itens diferentes.",
                        l.get("valorEstimado") or 0, [f"Processo {l['processo']}", f"Data: {data_br(l['data'])}"], "Prefeitura de CG", a,
                        "#aba=contratos-cg&p=" + l["processo"])

    # ── Sócios em comum entre vencedoras da mesma licitação ──
    for l in licit:
        if re.search(r"chamada|credenciamento|inexig|dispensa", l.get("modalidade") or "", re.I):
            continue  # sem disputa entre os vencedores (cada um recebe a sua cota) — sócio em comum não simula concorrência
        venc = [w for w in l.get("vencedores", []) if len(dig(w.get("cnpj"))) == 14]
        for i in range(len(venc)):
            for j in range(i + 1, len(venc)):
                a, b = dig(venc[i]["cnpj"]), dig(venc[j]["cnpj"])
                if a[:8] == b[:8]:
                    continue
                sa = {(norm(s["nome"]), s.get("cpf")) for s in (cad.get(a) or {}).get("socios", []) if s.get("nome")}
                sb = {(norm(s["nome"]), s.get("cpf")) for s in (cad.get(b) or {}).get("socios", []) if s.get("nome")}
                comum = {x[0] for x in sa & sb}
                if comum:
                    add("socios_licitacao", (l["processo"], l["numero"], a, b), f"{l['modalidade']} nº {l['numero']}: vencedoras com sócio em comum",
                        f"{venc[i]['nome']} e {venc[j]['nome']} venceram a mesma licitação ({l['objeto'][:160]}) e têm em comum o(s) sócio(s) "
                        f"{', '.join(sorted(comum))}. Empresas do mesmo dono numa disputa podem simular concorrência.",
                        l.get("valorEstimado") or 0, [f"Processo {l['processo']}", f"Data: {data_br(l['data'])}", f"Situação: {l['status']}"],
                        "Prefeitura de CG", a, "#aba=contratos-cg&p=" + l["processo"])

    # ── Atividade incompatível ──
    agr = {}
    for n in notas:
        if len(n["cnpj"]) == 14 and n["cnpj"] in cad and not cad[n["cnpj"]].get("naoEncontrado"):
            k = (n["p"], n["cnpj"])
            a = agr.setdefault(k, {"total": 0.0, "cats": {}, "n": n})
            a["total"] += n["valor"]
            a["cats"][n["cat"]] = a["cats"].get(n["cat"], 0) + n["valor"]
    for (p, c), a in agr.items():
        if a["total"] < 15000:
            continue
        cat = max(a["cats"].items(), key=lambda kv: kv[1])[0]
        regras = [pref_ok for padrao, pref_ok in CNAE_OK if re.search(padrao, cat, re.I)]
        if not regras:
            continue
        ok = [x for r in regras for x in r]
        info = cad[c]
        cnaes = [info.get("cnae") or ""] + (info.get("cnaesSec") or [])
        if not any(cn.startswith(o) for cn in cnaes if cn for o in ok):
            add("atividade_incompativel", (c, p), f"{info.get('razao') or c}: atividade registrada não inclui o serviço cobrado",
                f"{p} pagou {brl(a['total'])} por \"{cat[:90]}\", mas nenhuma das {len([x for x in cnaes if x])} atividades da empresa "
                f"na Receita corresponde a esse tipo de serviço. A principal é: {info.get('cnaeDesc') or '—'}.",
                a["total"], [f"Atividade principal: {info.get('cnae')} — {info.get('cnaeDesc')}",
                             f"Atividades secundárias: {len(info.get('cnaesSec') or [])}"], p, c, a["n"]["url"])

    # ── Fornecedor de um cliente só (notas em sequência + não recebe de mais ninguém) ──
    grupos = {}
    for n in notas:
        num = dig(n["nf"])
        if len(n["cnpj"]) == 14 and num and 0 < len(num) <= 7:
            grupos.setdefault((n["p"], n["cnpj"]), []).append((int(num), n))
    for (p, c), lst in grupos.items():
        nums = sorted({x for x, _ in lst})
        if len(nums) < 6:
            continue
        faixa = nums[-1] - nums[0] + 1
        meses = len({(n.get("data") or "")[:7] for _, n in lst})
        outros = [q for q in por_cnpj.get(c, {}).get("pagadores", {}) if q != p]
        tot = sum(n["valor"] for _, n in lst)
        if len(nums) / faixa >= 0.6 and meses >= 4 and not outros and not pref_raiz.get(c[:8]) and not gov_raiz.get(c[:8]) and tot >= 30000:
            info = cad.get(c) or {}
            add("cliente_unico", (c, p), f"{info.get('razao') or lst[0][1]['forn']}: notas nº {nums[0]} a {nums[-1]} quase todas para {p}",
                f"Das {faixa} notas numeradas de {nums[0]} a {nums[-1]}, {len(nums)} ({len(nums) / faixa:.0%}) foram para {p}, em {meses} meses — "
                f"a empresa parece emitir notas quase só para esse gabinete, e não recebe de nenhum outro órgão que o site acompanha. "
                f"É comum em advogados e consultores exclusivos; a data de abertura e os sócios ajudam a separar o normal do suspeito.",
                tot, [f"Abertura: {data_br(info.get('abertura'))}" if info.get("abertura") else "Cadastro na Receita ainda não consultado",
                      f"Atividade principal: {info.get('cnaeDesc') or '—'}",
                      f"Sócios: {', '.join(s['nome'] for s in info.get('socios', [])[:3]) or '—'}"], p, c, lst[0][1]["url"])

    # ── Gasto mensal por categoria muito acima dos colegas ──
    for alvo, nome_cat in (("loca", "locação de veículos"), ("divulga", "divulgação"), ("consult", "consultorias e assessorias"), ("combust", "combustíveis")):
        for g in ("estadual", "federal", "vereador", "senador"):
            soma, meses = {}, {}
            for n in notas:
                if n["grupo"] == g and alvo in n["cat"].lower():
                    soma[n["p"]] = soma.get(n["p"], 0) + n["valor"]
                    meses.setdefault(n["p"], set()).add((n.get("data") or "")[:7])
            med = {p: soma[p] / len(meses[p]) for p in soma if len(meses[p]) >= 3}
            if len(med) < 5:
                continue
            md = statistics.median(med.values())
            for p, m in med.items():
                if md and m > 2.5 * md:
                    add("gasto_acima_colegas", (p, alvo), f"{p}: {nome_cat} {m / md:.1f}× a mediana dos colegas",
                        f"Média de {brl(m)} por mês em {nome_cat}, contra a mediana de {brl(md)} dos {len(med)} colegas do mesmo cargo "
                        f"com esse gasto. Não indica irregularidade por si — pode refletir o tamanho do estado, a agenda ou o tipo de mandato.",
                        soma[p], [f"Total no ano: {brl(soma[p])}", f"Meses com gasto: {len(meses[p])}"], p)

    # ── Dispensa acima do limite legal no mesmo processo (Prefeitura) ──
    proc = {}
    for x in pref.get("despesas", []) if pref.get("ano") == ANO else []:
        if "DISPENSA" in str(x.get("modalidade") or "").upper() and x.get("processo"):
            cat = str(x.get("categoria") or "").upper()
            if re.search(r"LOCA[ÇC][AÃ]O DE IM[OÓ]VE|BANC[AÁ]RI|ENERGIA|[ÁA]GUA E ESGOTO|TELEFON|CORREIO|POSTA", cat):
                continue  # aluguel de imóvel, bancos e concessionárias têm outra base legal para contratar sem licitação
            p_ = proc.setdefault(x["processo"], {"empenhado": 0.0, "pago": 0.0, "n": 0, "forn": {}, "orgao": x["orgao"], "cat": x["categoria"], "url": x.get("urlDetalhe")})
            p_.setdefault("maior", 0.0)
            p_["maior"] = max(p_["maior"], x.get("empenhado") or 0)
            p_["empenhado"] += x.get("empenhado") or 0
            p_["pago"] += x.get("valor") or 0
            p_["n"] += 1
            p_["forn"][x["fornecedor"]] = dig(x.get("cnpj"))
    for pr, p_ in proc.items():
        lim = LIM_DISPENSA_OBRA if re.search(r"OBRA|ENGENHAR", str(p_["cat"]).upper()) else LIM_DISPENSA
        ano_proc = re.search(r"/\s*(\d{4})", pr)
        # padrão de fracionamento: 3+ empenhos, cada um abaixo do limite, somando acima dele, num processo
        # aberto sob o limite atual (2025-26). Um empenho único acima do limite costuma ser emergência ou
        # outra hipótese legal — não entra.
        if p_["empenhado"] > lim and p_["n"] >= 3 and p_["maior"] <= lim and ano_proc and int(ano_proc[1]) >= ANO - 1:
            f0 = next(iter(p_["forn"]))
            add("dispensa_acima_limite", (pr,), f"Processo {pr}: {p_['n']} empenhos por dispensa somando {brl(p_['empenhado'])}",
                f"{p_['orgao']} — {p_['cat']}. Fornecedor(es): {', '.join(list(p_['forn'])[:3])}. Cada empenho ficou abaixo do limite da "
                f"dispensa pelo valor ({brl(lim)} em {ANO}), mas juntos passam dele — o padrão que a lei chama de fracionamento "
                f"(Decreto 12.807/2025). Pode haver outra base legal (emergência, por exemplo), que só o processo mostra — "
                f"vale pedi-lo pela Lei de Acesso à Informação.",
                p_["empenhado"], [f"Empenhado: {brl(p_['empenhado'])}", f"Pago: {brl(p_['pago'])}", f"Empenhos: {p_['n']}"],
                "Prefeitura de CG", p_["forn"][f0], p_["url"])

    ordem = {"forte": 0, "médio": 1}
    sinais.sort(key=lambda s: (ordem[s["nivel"]], -s["valor"]))
    por_quem = {}
    for s in sinais:
        q = s.get("quem") or "—"
        d = por_quem.setdefault(q, {"quem": q, "fortes": 0, "medios": 0, "valor": 0.0})
        d["fortes" if s["nivel"] == "forte" else "medios"] += 1
        d["valor"] += s["valor"]
    salvar("auditoria.json", {
        "ano": ANO, "ultimaAtualizacao": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "empresasConsultadas": sum(1 for v in cad.values() if not v.get("naoEncontrado")),
        "regras": {t: ROTULO[t] for t in ROTULO},
        "resumo": {t: sum(1 for s in sinais if s["teste"] == t) for t in ROTULO},
        "porQuem": sorted(({**v, "valor": round(v["valor"], 2)} for v in por_quem.values()), key=lambda v: (-v["fortes"], -v["medios"])),
        "sinais": sinais})
    print(f"✅ auditoria.json — {len(sinais)} sinais ({sum(1 for s in sinais if s['nivel'] == 'forte')} fortes): "
          + ", ".join(f"{t} {n}" for t, n in {t: sum(1 for s in sinais if s['teste'] == t) for t in ROTULO}.items() if n))


if __name__ == "__main__":
    main()
