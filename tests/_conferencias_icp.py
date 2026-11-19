"""Cofre Aberto MS — conferências por base que completam os 5 tipos de teste do ICP (estrutura, totais, contagem,
duplicidade, faixa). Chamado por tests/test_integridade_dados.py.

Cada conferência testa uma regra que vale nos dados de verdade (registros únicos, valores não negativos, datas que não
estão no futuro, partes que não passam do todo, totais que batem com a soma). O nome de cada conferência começa pelo id
da base, para o ICP atribuí-la (tests/_bases.py). Regras que podem variar legitimamente na fonte são "aviso", não "erro".
"""
import collections, glob, json
from datetime import date
from pathlib import Path


def rodar(D: Path, checa, igual, soma):
    H = date.today().isoformat()

    def J(n):
        try:
            return json.load(open(D / n, encoding="utf-8"))
        except FileNotFoundError:
            return None

    def repetidos(xs):
        return [k for k, c in collections.Counter(xs).items() if c > 1]

    def num(x):
        return isinstance(x, (int, float)) and not isinstance(x, bool)

    def campos(lista, obrig):
        return [i for i, x in enumerate(lista) if any(x.get(c) in (None, "") for c in obrig)]

    def futuras(datas):
        return [d for d in datas if d and str(d)[:10] > H]

    # ── Câmara de Campo Grande ──
    cm = J("camara_municipal.json")
    if cm:
        vs, ano = cm.get("vereadores") or [], cm.get("ano")
        r = repetidos([v.get("id") for v in vs]) + repetidos([v.get("nome") for v in vs])
        checa("camara: nenhum vereador repetido (id e nome únicos)", not r, f"repetidos: {r[:3]}")
        neg = [v["nome"] for v in vs if (v.get("verbaIndenizatoria") or {}).get(f"gastoPago{ano}", 0) < 0]
        checa("camara: nenhuma verba paga negativa", not neg, f"negativas: {neg[:3]}")
        desp = [d for v in vs for d in v.get("despesas") or []]
        f = futuras(d.get("data") for d in desp)
        checa("camara: nenhuma nota com data no futuro", not f, f"{len(f)} notas com data futura")
        acima = [v["nome"] for v in vs if (v.get("verbaIndenizatoria") or {}).get(f"gastoPago{ano}", 0) > (v.get("verbaIndenizatoria") or {}).get(f"cotaAnual{ano}", float("inf")) + 0.01]
        checa("camara: verba paga não passa do limite anual da cota", not acima, f"acima do limite: {acima[:3]}", nivel="aviso")

    # ── Assembleia (deputados estaduais) ──
    de = J("deputados_estaduais_ms.json")
    if de:
        vs = de.get("vereadores") or []
        r = repetidos([v.get("nome") for v in vs])
        checa("deputados-estaduais: nenhum deputado repetido (nome único)", not r, f"repetidos: {r[:3]}")
        neg = [v["nome"] for v in vs for k, x in (v.get("verbaIndenizatoria") or {}).items() if num(x) and x < 0]
        checa("deputados-estaduais: nenhum valor de verba negativo", not neg, f"negativos: {neg[:3]}")
        desp = [d for v in vs for d in v.get("despesas") or []]
        f = futuras(d.get("data") for d in desp)
        checa("deputados-estaduais: nenhuma despesa com data no futuro", not f, f"{len(f)} despesas com data futura")

    # ── Senadores de MS ──
    se = J("senadores_ms.json")
    if se:
        ss = se.get("senadores") or []
        neg = [s["nome"] for s in ss if (s.get("cotaGastaAno") or 0) < 0]
        checa("senadores: nenhuma cota gasta negativa", not neg, f"negativas: {neg}")
        checa("senadores: 3 senadores de MS, sem repetidos", len(ss) == 3 and not repetidos([s.get("nome") for s in ss]), f"{len(ss)} senadores")

    # ── Contratos e licitações da Prefeitura ──
    pc = J("prefeitura_contratos.json")
    if pc:
        cs = pc.get("contratos") or []
        sem = campos(cs, ("objeto", "fornecedor", "valor", "registro"))
        checa("contratos-cg: todo contrato tem campos obrigatórios (objeto, fornecedor, valor, registro)", not sem, f"{len(sem)} contratos sem campo")
        r = repetidos([c.get("registro") for c in cs])
        checa("contratos-cg: nenhum contrato repetido (registro único)", not r, f"repetidos: {r[:3]}")
        neg = [c.get("registro") for c in cs if num(c.get("valor")) and c["valor"] < 0]
        checa("contratos-cg: nenhum valor de contrato negativo", not neg, f"negativos: {neg[:3]}")
        inv = [c.get("registro") for c in cs if c.get("inicio") and c.get("fim") and str(c["fim"])[:10] < str(c["inicio"])[:10]]
        checa("contratos-cg: nenhum contrato com fim antes do início (datas)", not inv, f"{len(inv)} contratos", nivel="aviso")
        res = pc.get("resumo") or {}
        checa("contratos-cg: total do resumo = soma dos contratos", igual(soma(c.get("valor") for c in cs), (res.get("valorCompras") or 0) + (res.get("valorNaoCompras") or 0)),
              f"{soma(c.get('valor') for c in cs)} x {(res.get('valorCompras') or 0) + (res.get('valorNaoCompras') or 0)}")

    # ── Governo do Estado ──
    g = J("governo_ms.json")
    if g:
        os_ = g.get("orgaos") or []
        r = repetidos([o.get("codigo") for o in os_])
        checa("governo-ms: nenhum órgão repetido (código único)", not r, f"repetidos: {r[:3]}")
        r = repetidos([c.get("cnpj") for c in g.get("credores") or []])
        checa("governo-ms: nenhum credor repetido (CNPJ/CPF único)", not r, f"{len(r)} repetidos")
        neg = [o["orgao"] for o in os_ if min(o.get("empenhado") or 0, o.get("liquidado") or 0, o.get("pago") or 0) < 0]
        checa("governo-ms: nenhum valor negativo por órgão", not neg, f"negativos: {neg[:3]}")
        fora = [o["orgao"] for o in os_ if (o.get("pago") or 0) > (o.get("liquidado") or 0) + 0.01 or (o.get("liquidado") or 0) > (o.get("empenhado") or 0) + 0.01]
        checa("governo-ms: por órgão, pago ≤ liquidado ≤ empenhado (limite das fases da despesa)", not fora, f"fora da ordem: {fora[:3]}")

    # ── Emendas ──
    em = J("emendas_municipios.json")
    if em:
        ms = em.get("municipios") or []
        r = repetidos([m.get("municipio") for m in ms])
        checa("emendas: nenhum município repetido", not r, f"repetidos: {r[:3]}")
        r = repetidos([a.get("autor") for a in em.get("autores") or []])
        checa("emendas: nenhum autor repetido", not r, f"repetidos: {r[:3]}")
        neg = [m["municipio"] for m in ms if (m.get("total") or 0) < 0]
        checa("emendas: nenhum total de município negativo", not neg, f"negativos: {neg[:3]}")
        checa("emendas: nº de municípios ≤ 79 (municípios de MS)", len(ms) <= 79, f"{len(ms)} municípios")

    # ── Supersalários ──
    sp = J("supersalarios.json")
    if sp:
        os_ = (sp.get("orgaos") or []) + (sp.get("orgaosGoverno") or [])
        r = repetidos([(o.get("orgao"), o.get("mes")) for o in os_])
        checa("supersalarios: nenhum órgão repetido no mesmo mês", not r, f"repetidos: {r[:3]}")
        fora = [o["orgao"] for o in os_ if (o.get("acimaTeto") or 0) > (o.get("pessoas") or 0)]
        checa("supersalarios: pessoas acima do teto ≤ pessoas do órgão", not fora, f"fora: {fora[:3]}")

    # ── Arrecadação (Siconfi) ──
    rc = J("receitas.json")
    if rc:
        for ente, partes in (("estado", ("icms", "ipva", "itcd", "irrf")), ("cg", ("iptu", "iss", "itbi", "irrf"))):
            e = (rc.get("entes") or {}).get(ente) or {}
            ms = e.get("meses") or {}
            sem = [k for k, x in ms.items() if any(c not in x for c in ("impostos", "correntes"))]
            checa(f"arrecadacao {ente}: todo mês tem os campos impostos e correntes", not sem, f"meses sem campo: {sem[:3]}")
            neg = [k for k, x in ms.items() if any(num(v) and v < 0 for v in x.values())]
            checa(f"arrecadacao {ente}: nenhuma receita negativa", not neg, f"meses: {neg[:3]}")
            fora = [k for k, x in ms.items() if num(x.get("impostos")) and num(x.get("correntes")) and x["impostos"] > x["correntes"] + 1]
            checa(f"arrecadacao {ente}: impostos ≤ receitas correntes (parte não passa do total)", not fora, f"meses: {fora[:3]}")
            fora = [k for k, x in ms.items() if num(x.get("impostos")) and soma(x.get(c) for c in partes) > x["impostos"] + 1]
            checa(f"arrecadacao {ente}: soma dos impostos próprios listados ≤ total de impostos", not fora, f"meses: {fora[:3]}", nivel="aviso")
            checa(f"arrecadacao {ente}: último mês informado = mês mais recente da série (contagem de meses)", not ms or e.get("ultimoMes") == max(ms), f"{e.get('ultimoMes')} x {max(ms) if ms else None}")
            checa(f"arrecadacao {ente}: nenhum mês no futuro", not [k for k in ms if k > H[:7]], "mês futuro na série")

    # ── Aluguéis ──
    al = J("alugueis.json")
    if al:
        pn = (al.get("pncp") or {}).get("lista") or []
        r = repetidos([x.get("id") for x in pn])
        checa("alugueis: nenhuma contratação PNCP repetida (nº de controle único)", not r, f"repetidas: {r[:3]}")
        neg = [x.get("id") for x in pn if (x.get("valor") or 0) < 0]
        checa("alugueis: nenhum valor negativo (PNCP)", not neg, f"negativos: {neg[:3]}")
        f = futuras(x.get("data") for x in pn)
        checa("alugueis: nenhuma contratação com data no futuro", not f, f"{len(f)} com data futura")
        pf = (al.get("prefeitura") or {}).get("lista") or []
        r = repetidos([(x.get("doc"), x.get("nome")) for x in pf])
        checa("alugueis: nenhum locador da Prefeitura repetido", not r, f"{len(r)} repetidos")
        neg = [x.get("nome") for x in pf if (x.get("valor") or 0) < 0]
        checa("alugueis: nenhum valor pago a locador negativo", not neg, f"{len(neg)} negativos")

    # ── Produção legislativa ──
    pl = J("producao_legislativa.json")
    if pl:
        ps = pl.get("parlamentares") or []
        r = repetidos([(p.get("grupo"), p.get("id")) for p in ps])
        checa("producao: nenhum parlamentar repetido", not r, f"repetidos: {r[:3]}")
        neg = [p["nome"] for p in ps if any(num(p.get(k)) and p[k] < 0 for k in ("proposicoes", "requerimentos", "outras", "projetos", "leis"))]
        checa("producao: nenhuma contagem negativa", not neg, f"negativas: {neg[:3]}")
        fora = [p["nome"] for p in ps if (p.get("leis") or 0) > (p.get("projetos") or 0)]
        checa("producao: leis aprovadas ≤ projetos apresentados (limite)", not fora, f"fora: {fora[:3]}")

    # ── Votações ──
    vt = J("votacoes.json")
    if vt:
        ps = vt.get("parlamentares") or []
        r = repetidos([(p.get("grupo"), p.get("id")) for p in ps])
        checa("votacoes: nenhum parlamentar repetido", not r, f"repetidos: {r[:3]}")
        fora = [p["nome"] for p in ps if (p.get("votou") or 0) + (p.get("ausente") or 0) > (p.get("nominais") or 0)]
        checa("votacoes: votou + ausente ≤ total de votações nominais (limite)", not fora, f"fora: {fora[:3]}")
        dif = [p["nome"] for p in ps if p.get("nominais") and p.get("participacao") is not None and abs(100 * p["votou"] / p["nominais"] - p["participacao"]) > 0.051]
        checa("votacoes: participação = votou ÷ total de votações (×100)", not dif, f"diferem: {dif[:3]}")
        qv = ((vt.get("quadroCamara") or {}).get("votacoes") or [])
        r = repetidos([x.get("id") for x in qv])
        checa("votacoes: nenhuma votação da Câmara repetida (id único)", not r, f"repetidas: {r[:3]}")
        f = futuras(x.get("data") for x in qv + ((vt.get("quadroSenado") or {}).get("votacoes") or []))
        checa("votacoes: nenhuma votação com data no futuro", not f, f"{len(f)} com data futura")

    # ── Obras ──
    ob = J("obras.json")
    if ob:
        r = repetidos([(x.get("numero"), x.get("orgao"), x.get("processo")) for x in ob.get("obras") or []])
        checa("obras: nenhuma obra do Estado repetida (nº, órgão e processo únicos)", not r, f"{len(r)} repetidas")
        r = repetidos([x.get("registro") for x in (ob.get("prefeitura") or {}).get("obras") or []])
        checa("obras: nenhuma obra da Prefeitura repetida (registro único)", not r, f"{len(r)} repetidas")

    # ── Publicidade ──
    pu = J("publicidade.json")
    if pu:
        ag, pg = pu.get("agencias") or [], pu.get("pagamentosPrefeitura") or []
        sem = campos(ag, ("cnpj", "nome")) + campos(pg, ("data", "fornecedor", "valor"))
        checa("publicidade: toda agência e todo pagamento têm os campos obrigatórios", not sem, f"{len(sem)} registros sem campo")
        r = repetidos([x.get("cnpj") for x in ag])
        checa("publicidade: nenhuma agência repetida (CNPJ único)", not r, f"repetidas: {r[:3]}")
        neg = [x.get("fornecedor") for x in pg if (x.get("valor") or 0) < 0] + [x.get("nome") for x in ag if (x.get("estado") or 0) < 0]
        checa("publicidade: nenhum valor negativo", not neg, f"negativos: {neg[:3]}")
        f = futuras(x.get("data") for x in pg)
        checa("publicidade: nenhum pagamento com data no futuro", not f, f"{len(f)} com data futura")

    # ── Entidades ──
    en = J("entidades.json")
    if en:
        es = en.get("entidades") or []
        sem = campos(es, ("cnpj", "nome", "area"))
        checa("entidades: campos obrigatórios em toda entidade (CNPJ, nome e área)", not sem, f"{len(sem)} sem campo")
        r = repetidos([x.get("cnpj") for x in es])
        checa("entidades: nenhuma entidade repetida (CNPJ único)", not r, f"{len(r)} repetidas")
        f = futuras(x.get("abertura") for x in es)
        neg = [x.get("cnpj") for x in es if num(x.get("idadeAnos")) and x["idadeAnos"] < 0]
        checa("entidades: nenhuma data de abertura no futuro nem idade negativa", not f and not neg, f"{len(f)} futuras, {len(neg)} negativas")

    # ── Câmaras do interior ──
    rep = []
    for f in sorted(glob.glob(str(D / "camaras" / "*.json"))):
        try:
            c = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        r = repetidos([v.get("nome") for v in c.get("vereadores") or []])
        if r:
            rep.append((Path(f).stem, r[:2]))
    checa("camaras-ms: nenhum vereador repetido na mesma câmara", not rep, f"repetidos: {rep[:3]}")

    # ── Judiciário (TJMS) ──
    tj = J("tjms_magistrados.json")
    if tj:
        ms, res = tj.get("magistrados") or [], tj.get("resumo") or {}
        sem = campos(ms, ("nome", "cargo", "remuneracaoBruta"))
        checa("judiciario: campos obrigatórios em todo magistrado (nome, cargo e remuneração bruta)", not sem, f"{len(sem)} sem campo")
        checa("judiciario: total da folha bruta = soma dos magistrados", igual(soma(m.get("remuneracaoBruta") for m in ms), res.get("totalFolhaMensalBruta")),
              f"{soma(m.get('remuneracaoBruta') for m in ms)} x {res.get('totalFolhaMensalBruta')}")
        r = repetidos([(m.get("nome"), m.get("lotacao")) for m in ms])
        checa("judiciario: nenhum magistrado repetido", not r, f"{len(r)} repetidos")
        neg = [m.get("cargo") for m in ms if (m.get("remuneracaoBruta") or 0) < 0]
        checa("judiciario: nenhuma remuneração bruta negativa", not neg, f"{len(neg)} negativas")

    # ── Eleições (TSE) ──
    el = J("eleicoes.json")
    if el:
        ei, at = el.get("eleitos2026") or [], el.get("atuais") or []
        sem = campos(ei + at, ("chave", "nome", "cargo"))
        checa("eleicoes: campos obrigatórios em todo candidato (chave, nome e cargo)", not sem, f"{len(sem)} sem campo")
        r = repetidos([x.get("chave") for x in ei]) + repetidos([x.get("chave") for x in at])
        checa("eleicoes: nenhum candidato repetido (chave única)", not r, f"repetidos: {r[:3]}")
        neg = [x["nome"] for x in ei + at for p in x.get("patrimonio") or [] if (p.get("patrimonio") or 0) < 0]
        checa("eleicoes: nenhum patrimônio declarado negativo", not neg, f"negativos: {neg[:3]}")
        fora = [x["nome"] for x in ei if num(x.get("receitas")) and soma(d.get("valor") for d in x.get("doadores") or []) > x["receitas"] + 0.01]
        checa("eleicoes: soma dos maiores doadores ≤ total arrecadado na campanha", not fora, f"fora: {fora[:3]}")

    # ── Sinais de atenção (auditoria) ──
    au = J("auditoria.json")
    if au:
        sn = au.get("sinais") or []
        sem = campos(sn, ("id", "teste", "nivel", "titulo"))
        checa("auditoria: todo sinal tem id, teste, nível e título", not sem, f"{len(sem)} sem campo")
        r = repetidos([x.get("id") for x in sn])
        checa("auditoria: nenhum sinal repetido (id único)", not r, f"{len(r)} repetidos")
        cont = collections.Counter(x.get("teste") for x in sn)
        dif = {k: (v, cont.get(k, 0)) for k, v in (au.get("resumo") or {}).items() if v != cont.get(k, 0)}
        checa("auditoria: total por regra no resumo = sinais da regra", not dif, f"diferem: {list(dif.items())[:3]}")
        fora = [x.get("id") for x in sn if x.get("nivel") not in ("forte", "médio")]
        checa("auditoria: nível de todo sinal é 'forte' ou 'médio' (valores permitidos)", not fora, f"{len(fora)} fora")
        desc = set(cont) - set(au.get("regras") or {})
        checa("auditoria: toda regra usada está na lista de regras", not desc, f"desconhecidas: {sorted(desc)[:3]}")

