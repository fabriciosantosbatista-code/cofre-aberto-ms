#!/usr/bin/env python3
"""
Cofre Aberto MS — ICP, metodologia 2.0: cobertura da conferência, nível de evidência e nota

Funções puras (sem ler arquivos), usadas por scripts/gerar_icp.py e testadas em tests/test_icp_metodologia.py.
A documentação completa, com exemplos, está em ICP_DOCUMENTACAO.md.

PRINCÍPIO: uma base com poucos registros conferidos não pode transmitir a mesma confiança de uma base integralmente
verificada. Por isso a precisão (P) deixa de ser "confere = 100" e passa a ser o que a amostra permite afirmar:

  P = 100 × (1 − limite superior de 95% da taxa de divergência) × fator do resultado × fator da idade

O limite superior vem da distribuição hipergeométrica exata (amostra sem reposição de uma base finita): é a maior
proporção de unidades divergentes na base que ainda tornaria plausível (probabilidade ≥ 5%) observar só d divergências
em n unidades conferidas. Com a base inteira conferida (n = N) o limite é d/N; com 8 de 206 e nenhuma divergência, é ~31%
(ou seja: nada garante que a base inteira esteja certa). Sem o tamanho da base (N desconhecido), usa-se o limite binomial
de Clopper–Pearson, que supõe base infinita (mais conservador), e a cobertura fica "não calculada".
"""

import math
import re

VERSAO = "2.0"
DESDE = "2026-11-18"
PESOS = {"P": 30, "A": 20, "I": 20, "T": 10, "R": 10, "F": 10}
EVIDENCIA = ("P", "I")         # dimensões de evidência: sem evidência valem 0 (não saem da conta)
PROPRIEDADE = ("A", "T", "R", "F")  # dimensões de propriedade: sem medição, saem da conta e as outras dividem os 50 pontos
TETO = {"divergencia": 40, "falha_coleta": 50, "integracao_instavel": 50, "revisao_manual": 70}
CONFIANCA = 0.95
VALIDADE_DIAS = 30            # conferência mais velha que isto não conta
VALIDADE_PLENA_DIAS = 8       # até 8 dias vale inteira; de 8 a 30, × 0,8 (regra da metodologia 1.0, mantida)
CATEGORIAS_TESTE = {          # o que um conjunto de testes de integridade deveria cobrir
    "estrutura": r"arquivo|campos?|formato|existe|tem cidade|vazi|lista|JSON|sem lixo|esquema",
    "totais": r"soma|total|=",
    "contagem": r"\bn[ºo°]\b|número de|quantidade|contagem|registros|conta(?:m|gem)",
    "duplicidade": r"repetid|duplic|únic|iguais",
    "faixa": r"negativ|zero|impossív|futur|\bdata|teto|numéric|fora do|valor|limite|vazio|recente|dias",
}
N_CATEGORIAS = len(CATEGORIAS_TESTE)


# ───────────────────────── estatística da amostra ─────────────────────────
def _lncomb(a, b):
    if b < 0 or b > a:
        return float("-inf")
    return math.lgamma(a + 1) - math.lgamma(b + 1) - math.lgamma(a - b + 1)


def _hiper_cdf(d, N, D, n):
    """P(X ≤ d) para X ~ Hipergeométrica(N, D divergentes, n sorteados)."""
    base = _lncomb(N, n)
    return sum(math.exp(_lncomb(D, k) + _lncomb(N - D, n - k) - base) for k in range(0, min(d, n, D) + 1))


def _binom_cdf(d, n, p):
    return sum(math.comb(n, k) * p ** k * (1 - p) ** (n - k) for k in range(0, d + 1))


def limite_superior(N, n, d, conf=CONFIANCA):
    """Limite superior (unilateral, conf) da proporção de unidades divergentes na base.
    N = unidades na base (None = desconhecido), n = unidades conferidas (distintas), d = divergentes entre elas."""
    if not n or n <= 0:
        return 1.0
    alfa = 1 - conf
    if N:
        N, n = int(N), min(int(n), int(N))
        if n >= N:
            return d / N
        lo, hi = d, N - (n - d)  # D possível
        while lo < hi:  # maior D com P(X ≤ d) ≥ alfa (a função decresce com D)
            m = (lo + hi + 1) // 2
            if _hiper_cdf(d, N, m, n) >= alfa:
                lo = m
            else:
                hi = m - 1
        return lo / N
    if d >= n:
        return 1.0
    lo, hi = d / n, 1.0
    for _ in range(60):  # Clopper–Pearson: p com P(X ≤ d) = alfa
        m = (lo + hi) / 2
        if _binom_cdf(d, n, m) > alfa:
            lo = m
        else:
            hi = m
    return hi


# ───────────────────────── cobertura e nível de evidência ─────────────────────────
COMPATIVEL = ("confere", "mudou_na_fonte")


JANELA_DESDE = "2026-11-19"  # conferência acumulada em janela móvel de 30 dias, com hash do registro (vigência)


def _ids_validos(h, hashes_atuais):
    """Ids de uma conferência registro a registro que ainda valem: com hashes atuais da base, só os registros que existem
    hoje e não mudaram desde a conferência (hash igual). Conferência sem hash gravado não prova que o registro está igual:
    com hashes atuais disponíveis, não conta."""
    ids = set(h.get("idsConferidos") or [])
    if hashes_atuais is None:
        return ids
    hs = h.get("hashes")
    if not hs:
        return set()
    return {i for i, x in hs.items() if hashes_atuais.get(i) == x}


def cobertura(historico, agora, registros_base_atual=None, hashes_atuais=None):
    """historico: conferências da base (dicts do icp_verificacoes.jsonl), qualquer ordem. Devolve a cobertura da conferência
    vigente (a mais recente dos últimos 30 dias). Unidades repetidas não contam duas vezes: na conferência registro a registro,
    a cobertura é a UNIÃO das unidades distintas conferidas nos últimos 30 dias (a amostra de cada dia é outra).
    hashes_atuais ({id: hash} do registro hoje): um registro só conta se não mudou desde a conferência (janela móvel de 30
    dias com hash, desde JANELA_DESDE); registro novo só conta depois de sorteado e conferido."""
    validas = [h for h in historico if h.get("resultado") in COMPATIVEL + ("diverge",) and _idade(h, agora) is not None
               and _idade(h, agora) <= VALIDADE_DIAS]
    if not validas:
        return None
    v = max(validas, key=lambda h: h["em"])
    gran = v.get("granularidade")
    N = v.get("unidadesBase")
    if gran is None:  # conferência da metodologia 1.0 (não registrava a cobertura)
        n = len({str(c.get("item")) for c in v.get("comparados") or []}) or v.get("conferidos") or 0
        return {"versaoRegistro": "1.0", "granularidade": None, "unidade": None, "unidadesBase": None, "unidadesConferidas": n,
                "registrosBase": registros_base_atual, "registrosAbrangidos": None, "percentual": None, "calculavel": False,
                "divergentes": len(v.get("divergentes") or []), "resultado": v["resultado"], "em": v["em"], "metodo": v.get("metodo"),
                "fonteUrl": v.get("fonteUrl"), "selecao": None, "responsavel": None, "idade": _idade(v, agora)}
    ids = _ids_validos(v, hashes_atuais) if gran == "registro" else set(v.get("idsConferidos") or [])
    if gran == "registro":
        for h in validas:
            # só conferências da mesma unidade: se a unidade mudou (ex.: de "campo" para "entidade"), os ids não se somam
            if h.get("granularidade") == "registro" and h.get("resultado") in COMPATIVEL and h.get("unidade") == v.get("unidade"):
                ids |= _ids_validos(h, hashes_atuais)
    if gran == "registro" and hashes_atuais is not None:
        n = min(len(ids), N) if N else len(ids)  # com hash: só o que ainda vale (pode ser 0)
    else:
        n = min(len(ids) or v.get("unidadesConferidas") or 0, N) if N else (len(ids) or v.get("unidadesConferidas") or 0)
    rb = v.get("registrosBase") if v.get("registrosBase") is not None else registros_base_atual
    # desde 19/11/2026: registro só conta como conferido se foi comparado UM A UM com a fonte. Na conferência por unidade
    # ou por total, o que a unidade (órgão, parlamentar) abrange vira "coberto por totais conferidos", indicador à parte.
    if gran == "registro":
        ra, por_totais = n, 0
    else:
        ra = v.get("registrosConferidosUmAUm") or 0
        por_totais = v.get("registrosPorTotais", v.get("registrosAbrangidos"))
    if rb is not None:
        ra = min(ra, rb)
        por_totais = min(por_totais, rb) if por_totais is not None else None
    pct = round(100 * ra / rb, 2) if rb else None
    return {"versaoRegistro": v.get("metodologia") or "2.0", "granularidade": gran, "unidade": v.get("unidade"), "unidadesBase": N,
            "unidadesConferidas": n, "registrosBase": rb, "registrosAbrangidos": ra, "percentual": pct,
            "registrosPorTotais": por_totais, "percentualPorTotais": round(100 * por_totais / rb, 2) if (rb and por_totais is not None) else None,
            "calculavel": bool(N) and rb is not None and ra is not None,
            "divergentes": len(v.get("divergentes") or []), "resultado": v["resultado"], "em": v["em"], "metodo": v.get("metodo"),
            "fonteUrl": v.get("fonteUrl"), "selecao": v.get("selecao"), "responsavel": v.get("responsavel"), "idade": _idade(v, agora)}


def _idade(h, agora):
    try:
        from datetime import datetime
        return (agora - datetime.fromisoformat(h["em"][:19])).days
    except Exception:
        return None


INTERVALO_REFORCO_H = 20  # "dias diferentes" de verdade: datas diferentes e pelo menos 20 h entre a 1ª e a última conferência


def _intervalo_horas(hs):
    from datetime import datetime
    ts = sorted(datetime.fromisoformat(h["em"][:19]) for h in hs)
    return (ts[-1] - ts[0]).total_seconds() / 3600


def abrangente(cob):
    """Todas as unidades da base conferidas, com pelo menos 2 unidades (um único total geral não localiza erros que se compensam)."""
    return bool(cob and cob["calculavel"] and cob["unidadesBase"] and cob["unidadesConferidas"] >= cob["unidadesBase"]
                and cob["unidadesBase"] >= 2 and cob["granularidade"] in ("registro", "unidade"))


def nivel(cob, integridade_ok, historico, agora):
    """0 sem evidência · 1 integridade interna · 2 conferência parcial (amostra ou recorte) · 3 conferência abrangente ·
    4 conferência abrangente reforçada (repetida: ≥ 3 conferências abrangentes compatíveis em ≥ 2 dias diferentes, com pelo
    menos 20 horas entre a primeira e a última, nos últimos 30 dias, com as evidências — itens comparados e endereço da
    fonte — gravadas). As 20 horas evitam que duas conferências feitas com 1 hora de diferença, gravadas em fusos
    diferentes ou perto da meia-noite, pareçam "dias diferentes"."""
    if cob and cob["resultado"] in COMPATIVEL:
        if abrangente(cob):
            reforco = [h for h in historico if h.get("resultado") in COMPATIVEL and h.get("granularidade") in ("registro", "unidade")
                       and h.get("unidadesBase") and (h.get("unidadesConferidas") or 0) >= h["unidadesBase"] >= 2
                       and h.get("comparados") and h.get("fonteUrl") and _idade(h, agora) is not None and _idade(h, agora) <= VALIDADE_DIAS]
            if len(reforco) >= 3 and len({h["em"][:10] for h in reforco}) >= 2 and _intervalo_horas(reforco) >= INTERVALO_REFORCO_H:
                return 4
            return 3
        return 2
    if cob and cob["resultado"] == "diverge":
        return 2 if not abrangente(cob) else 3  # a evidência existe (e aponta divergência): o status fica vermelho
    return 1 if integridade_ok else 0


NOME_NIVEL = {0: "Sem evidência", 1: "Integridade interna", 2: "Conferência parcial", 3: "Conferência abrangente", 4: "Conferência abrangente reforçada"}


# ───────────────────────── dimensões ─────────────────────────
def dim_P(cob):
    """Precisão: o que a conferência permite afirmar sobre a base inteira. Sem conferência válida = None (vale 0 na nota)."""
    if not cob:
        return None
    N = cob["unidadesBase"] if cob["calculavel"] else None
    p_up = limite_superior(N, cob["unidadesConferidas"], cob["divergentes"])
    fator_res = 1.0 if cob["resultado"] == "confere" else 0.9 if cob["resultado"] == "mudou_na_fonte" else 1.0
    fator_idade = 1.0 if cob["idade"] <= VALIDADE_PLENA_DIAS else 0.8
    p = 100 * (1 - p_up) * fator_res * fator_idade
    if cob["resultado"] == "diverge":
        p = min(p, 40)
    return round(max(0.0, p), 1)


def categorias(itens):
    return {c for c, rx in CATEGORIAS_TESTE.items() if any(re.search(rx, x["texto"], re.I) for x in itens)}


def dim_I(itens):
    """Integridade: aprovação × profundidade (categorias de teste cobertas ÷ 5) − 2 por aviso (até 20).
    Sem nenhum teste da base = None (vale 0 na nota)."""
    ok = sum(1 for x in itens if x["nivel"] == "ok")
    er = sum(1 for x in itens if x["nivel"] == "erro")
    av = sum(1 for x in itens if x["nivel"] == "aviso")
    if ok + er == 0:
        return None, set()
    cats = categorias(itens)
    return round(max(0.0, 100 * ok / (ok + er) * len(cats) / N_CATEGORIAS - min(20, 2 * av)), 1), cats


def fracao_conferida(cob):
    """Fração da base comparada com a fonte: pelos registros quando o total é conhecido; senão pelas unidades; senão 0."""
    if not cob or cob["resultado"] not in COMPATIVEL + ("diverge",):
        return 0.0
    if cob.get("percentual") is not None:
        return min(1.0, cob["percentual"] / 100)
    if cob.get("unidadesBase"):
        return min(1.0, (cob.get("unidadesConferidas") or 0) / cob["unidadesBase"])
    return 0.0


def teto_cobertura(cob, nivel_):
    """Nível 2 (conferência parcial): nota ≤ 70 + 30 × fração conferida. Os 70 pontos são o máximo possível sem nenhuma
    conferência na fonte (todas as outras dimensões cheias); os 30 do peso da conferência só são ganhos na proporção da
    base efetivamente comparada com a fonte. Níveis 3 e 4 (base inteira conferida): sem teto de cobertura."""
    if nivel_ == 2:
        return 70 + 30 * fracao_conferida(cob)
    return None


def nota(dims, classe, cob=None, nivel_=None):
    """Nota 2.0 (0–100). P e I (evidência) entram sempre com o peso cheio — sem evidência valem 0. A, T, R e F
    (propriedades da base) dividem os 50 pontos restantes entre as que foram medidas. Tetos: divergência 40, falha de
    coleta 50, integração instável (F < 50: mais da metade das coletas recentes falhou) 50, revisão manual pendente 70,
    e o teto de cobertura (nível 2): 70 + 30 × fração da base conferida."""
    ev = sum(PESOS[k] * (dims.get(k) or 0) for k in EVIDENCIA)
    prop = {k: dims[k] for k in PROPRIEDADE if dims.get(k) is not None}
    if not prop:
        return None
    m = sum(PESOS[k] * v for k, v in prop.items()) / sum(PESOS[k] for k in prop)
    n = (ev + m * sum(PESOS[k] for k in PROPRIEDADE)) / 100
    tetos = []
    if classe in TETO:
        tetos.append(TETO[classe])
    if dims.get("F") is not None and dims["F"] < 50:
        tetos.append(TETO["integracao_instavel"])
    tc = teto_cobertura(cob, nivel_)
    if tc is not None:
        tetos.append(tc)
    return round(min([n] + tetos))
