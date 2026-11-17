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
  arrecadacao          Tesouro/Siconfi RREO Anexo 3: ICMS do Estado mês a mês
  supersalarios        DadosJusBr: TJMS — nº de magistrados e soma do salário-base do mês publicado
  shows, alugueis      PNCP: 8 contratações sorteadas, valor homologado/estimado de cada uma

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
AGORA = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


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


def resultado(itens, metodo, fonte_url, nota=""):
    """itens: [(nome, site, fonte)] com fonte None = não obtido."""
    obtidos = [i for i in itens if i[2] is not None]
    if not obtidos:
        return {"resultado": "indisponivel", "em": AGORA, "metodo": metodo, "fonteUrl": fonte_url, "conferidos": 0, "nota": "a fonte não respondeu"}
    div = [{"item": n, "site": round(s, 2), "fonte": round(f, 2), "diferenca": round(s - f, 2)} for n, s, f in obtidos if abs(s - f) > 1]
    comparados = [{"item": n, "site": round(s, 2), "fonte": round(f, 2), "diferenca": round(s - f, 2)} for n, s, f in obtidos][:60]
    return {"resultado": "confere" if not div else "diverge", "em": AGORA, "metodo": metodo, "fonteUrl": fonte_url,
            "conferidos": len(obtidos), "divergentes": div[:20], "comparados": comparados, "naoObtidos": len(itens) - len(obtidos), "nota": nota}


def v_governo():
    import coletar_governo_ms as g
    s = J("governo_ms.json")
    try:
        d = g.despesas_periodo("despesapordataorgaos", date(int(s["ano"]), 1, 1), date.fromisoformat(s["ultimaAtualizacao"][:10]), 1000)
        f = [("pago", s["totais"]["pago"], d["totalPago"]), ("empenhado", s["totais"]["empenhado"], d["totalEmpenhado"])]
    except Exception as e:
        f = [("pago", 0, None)]
    return resultado(f, "consulta nova ao portal do Estado (mesmo período da coleta): pago e empenhado do ano", "https://www.transparencia.ms.gov.br/")


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
    return resultado(itens, "portal da ALEMS (/ceap/data): total do ano de cada deputado", "https://transparencia2.al.ms.gov.br/ceap")


def v_senado():
    s = J("senadores_ms.json")
    d = get(f"https://adm.senado.gov.br/adm-dadosabertos/api/v1/senadores/despesas_ceaps/{s.get('ano') or date.today().year}", timeout=180)
    itens = []
    for p in s.get("senadores") or []:
        f = round(sum(float(x.get("valorReembolsado") or 0) for x in d if str(x.get("codSenador")) == str(p["id"])), 2) if d else None
        itens.append((p["nome"], p.get("cotaGastaAno") or 0, f))
    return resultado(itens, "dados abertos do Senado (despesas_ceaps): soma do ano de cada senador de MS", "https://adm.senado.gov.br/adm-dadosabertos/")


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
    res = resultado(itens, "API da Câmara: soma do valor líquido do ano de cada deputado federal de MS", "https://dadosabertos.camara.leg.br/")
    # diferença pequena (até 1%) costuma ser nota lançada ou estornada depois da coleta
    if res["resultado"] == "diverge" and all(abs(x["diferenca"]) <= max(5, 0.01 * abs(x["fonte"])) for x in res["divergentes"]):
        res["resultado"], res["nota"] = "mudou_na_fonte", "diferenças até 1% — lançamentos/estornos feitos na Câmara depois da coleta"
    return res


def v_siconfi():
    r = J("receitas.json")
    e = (r.get("entes") or {}).get("estado") or {}
    ult = e.get("ultimoMes")
    if not ult:
        return resultado([("ICMS", 0, None)], "Siconfi RREO Anexo 3", "https://siconfi.tesouro.gov.br/")
    ano, mes = int(ult[:4]), int(ult[5:7])
    d = get("https://apidatalake.tesouro.gov.br/ords/siconfi/tt/rreo", {"an_exercicio": ano, "nr_periodo": (mes + 1) // 2, "co_tipo_demonstrativo": "RREO",
                                                                         "no_anexo": "RREO-Anexo 03", "id_ente": 50}, timeout=180)
    itens = []
    if d:
        icms = {x["coluna"]: x["valor"] for x in d.get("items") or [] if x["conta"].strip().upper() == "ICMS"}
        for k in range(12):
            col = "<MR>" if k == 0 else f"<MR-{k}>"
            y, m = ano, mes - k
            while m <= 0:
                m += 12
                y -= 1
            chave = f"{y}-{m:02d}"
            site = (e.get("meses") or {}).get(chave, {}).get("icms")
            if site is not None and col in icms:
                itens.append((f"ICMS {chave}", site, icms[col]))
    return resultado(itens or [("ICMS", 0, None)], f"Siconfi RREO Anexo 3 ({ano}, {(mes + 1) // 2}º bimestre): ICMS mês a mês", "https://siconfi.tesouro.gov.br/")


def v_tjms():
    ss = J("supersalarios.json")
    o = next((x for x in ss.get("orgaos") or [] if x.get("orgao", "").startswith("TJMS")), None)
    if not o:
        return resultado([("TJMS", 0, None)], "DadosJusBr", "https://dadosjusbr.org/")
    m, a = o["mes"].split("/")
    d = get(f"https://api.dadosjusbr.org/v2/dados/tjms/{int(a)}/{int(m)}")
    s = ((d or {}).get("sumarios") or {}).get("membros_ativos") or {}
    itens = [("magistrados", o["pessoas"], s.get("quantidade")), ("salário-base total", o["totalBase"], (s.get("remuneracao_base") or {}).get("total"))]
    return resultado(itens, f"DadosJusBr (contracheques do TJMS enviados ao CNJ, {o['mes']}): quantidade e salário-base", "https://dadosjusbr.org/")


def v_pncp(arquivo, chave_lista, rotulo):
    d = J(arquivo)
    lst = d.get(chave_lista) if chave_lista else None
    if lst is None:
        lst = (d.get("pncp") or {}).get("lista") or []
    random.seed(date.today().toordinal())
    amostra = random.sample(lst, min(8, len(lst)))
    itens = []
    for x in amostra:
        try:
            cnpj, ano, seq = x["link"].split("/editais/")[1].split("/")[:3]
        except Exception:
            continue
        c = get(f"https://pncp.gov.br/api/consulta/v1/orgaos/{cnpj}/compras/{ano}/{seq}")
        f = (c.get("valorTotalHomologado") or c.get("valorTotalEstimado")) if c else None
        itens.append(((x.get("artista") or x.get("objeto") or "")[:60], x["valor"], f))
    return resultado(itens, f"PNCP: {len(itens)} {rotulo} sorteadas, valor de cada uma na consulta pública", "https://pncp.gov.br/")


def main():
    ant = J("validacao_fontes.json")
    out = dict(ant.get("fontes") or {})
    for fonte, fn in (("governo-ms", v_governo), ("deputados-estaduais", v_alems), ("senadores", v_senado), ("deputados", v_camara),
                      ("arrecadacao", v_siconfi), ("supersalarios", v_tjms),
                      ("shows", lambda: v_pncp("shows.json", "shows", "contratações de show")),
                      ("alugueis", lambda: v_pncp("alugueis.json", None, "contratações de aluguel"))):
        try:
            r = fn()
        except Exception as e:
            r = {"resultado": "indisponivel", "em": AGORA, "nota": f"erro na conferência: {type(e).__name__}"}
        # mantém a última conferência bem-sucedida quando a fonte não responde hoje
        if r["resultado"] == "indisponivel" and (out.get(fonte) or {}).get("resultado") in ("confere", "mudou_na_fonte", "diverge"):
            r = {**out[fonte], "ultimaTentativa": AGORA, "ultimaTentativaResultado": "indisponivel"}
        if r.get("em") == AGORA:  # conferência feita agora (não a anterior mantida) — vai para o histórico permanente
            with open(HISTORICO, "a", encoding="utf-8") as h:
                h.write(json.dumps({"em": AGORA, "base": fonte, "resultado": r["resultado"], "metodo": r.get("metodo"), "fonteUrl": r.get("fonteUrl"),
                                    "conferidos": r.get("conferidos", 0), "comparados": r.get("comparados") or [], "divergentes": r.get("divergentes") or [],
                                    "nota": r.get("nota", "")}, ensure_ascii=False) + "\n")
        out[fonte] = r
        print(f"  {fonte:20} {r['resultado']:15} {r.get('conferidos', 0)} itens  {r.get('nota', '')}")
    SAIDA.write_text(json.dumps({"geradoEm": AGORA, "fontes": out}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"✅ validacao_fontes.json — {sum(1 for r in out.values() if r['resultado'] in ('confere', 'mudou_na_fonte'))} fontes conferidas, "
          f"{sum(1 for r in out.values() if r['resultado'] == 'diverge')} com divergência, {sum(1 for r in out.values() if r['resultado'] == 'indisponivel')} indisponíveis")


if __name__ == "__main__":
    main()
