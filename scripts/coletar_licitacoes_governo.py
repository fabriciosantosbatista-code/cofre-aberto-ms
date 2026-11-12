#!/usr/bin/env python3
"""
Cofre Aberto MS — Licitações do Governo do Estado: vencedores e preços (PNCP)

O Portal Nacional de Contratações Públicas (pncp.gov.br, API pública) recebe
de todos os órgãos as compras (licitações, dispensas e inexigibilidades) com
cada item: quantidade, preço estimado e, depois da homologação, o fornecedor
vencedor e o preço homologado.

Para o ano corrente, lista as compras publicadas em MS por órgãos da esfera
estadual (Executivo, Assembleia, Judiciário, MP, TCE, Defensoria) e, nas já
homologadas, lê os itens e os resultados: quem venceu, por quanto, e se o
preço homologado passou do estimado.

Guarda cache por compra (resultado homologado não muda) em
dados/licitacoes_governo_cache.json; gera dados/governo_ms_licitacoes.json.
Uso: python3 scripts/coletar_licitacoes_governo.py [limite_de_compras_novas]
"""

import json, sys, time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from pathlib import Path

import requests

DADOS = Path(__file__).parent.parent / "dados"
CACHE = DADOS / "licitacoes_governo_cache.json"
SAIDA = DADOS / "governo_ms_licitacoes.json"
API = "https://pncp.gov.br/api"
UA = {"User-Agent": "Mozilla/5.0 (CofreAbertoMS; +https://cofreabertoms.com.br)"}
HOJE = date.today()
ANO = HOJE.year
MODALIDADES = {4: "Concorrência eletrônica", 5: "Concorrência presencial", 6: "Pregão eletrônico", 7: "Pregão presencial",
               8: "Dispensa", 9: "Inexigibilidade", 12: "Credenciamento"}


def get(url, params=None, tent=4):
    for t in range(tent):
        try:
            r = requests.get(url, params=params, headers=UA, timeout=60)
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
        for x in d.get("data") or []:
            o = x.get("orgaoEntidade") or {}
            if o.get("esferaId") != "E":
                continue
            out.append({"id": x["numeroControlePNCP"], "cnpjOrgao": o.get("cnpj"), "orgao": o.get("razaoSocial"), "poder": o.get("poderId"),
                        "unidade": (x.get("unidadeOrgao") or {}).get("nomeUnidade"), "ano": x.get("anoCompra"), "seq": x.get("sequencialCompra"),
                        "modalidade": MODALIDADES.get(mod, x.get("modalidadeNome")), "numero": x.get("numeroCompra"), "processo": x.get("processo"),
                        "objeto": (x.get("objetoCompra") or "").strip()[:400], "situacao": x.get("situacaoCompraNome"),
                        "data": (x.get("dataPublicacaoPncp") or "")[:10], "estimado": x.get("valorTotalEstimado"),
                        "homologado": x.get("valorTotalHomologado"), "srp": x.get("srp")})
        if not d.get("paginasRestantes"):
            break
        p += 1
    return out


def resultados(c):
    base = f"{API}/pncp/v1/orgaos/{c['cnpjOrgao']}/compras/{c['ano']}/{c['seq']}"
    itens, p = [], 1
    while True:
        d = get(f"{base}/itens", {"pagina": p, "tamanhoPagina": 500})
        if not d:
            break
        itens += d
        if len(d) < 500:
            break
        p += 1
    venc, acima, n_res = {}, [], 0
    for it in itens:
        if not it.get("temResultado"):
            continue
        for r in get(f"{base}/itens/{it['numeroItem']}/resultados") or []:
            n_res += 1
            doc = r.get("niFornecedor") or ""
            v = venc.setdefault(doc, {"cnpj": doc, "nome": (r.get("nomeRazaoSocialFornecedor") or "").strip(), "valor": 0.0, "itens": 0})
            v["valor"] += r.get("valorTotalHomologado") or 0
            v["itens"] += 1
            est, hom = it.get("valorUnitarioEstimado") or 0, r.get("valorUnitarioHomologado") or 0
            if est and hom > est * 1.001 and (hom - est) * (r.get("quantidadeHomologada") or it.get("quantidade") or 0) >= 1000:
                acima.append({"item": it["numeroItem"], "descricao": (it.get("descricao") or "")[:160], "fornecedor": v["nome"], "cnpj": doc,
                              "estimado": est, "homologado": hom, "quantidade": r.get("quantidadeHomologada") or it.get("quantidade")})
    return {"itens": len(itens), "resultados": n_res,
            "vencedores": sorted(({**v, "valor": round(v["valor"], 2)} for v in venc.values()), key=lambda v: -v["valor"]),
            "acimaEstimado": acima[:20], "lidoEm": HOJE.isoformat()}


def main():
    so_gerar = "--so-gerar" in sys.argv  # só refaz a saída a partir do cache, sem consultar o PNCP
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    limite = int(args[0]) if args else 100000
    try:
        cache = json.load(open(CACHE, encoding="utf-8"))
    except Exception:
        cache = {}
    meses, compras = cache.setdefault("meses", {}), cache.setdefault("compras", {})
    # listagem mês a mês (os dois últimos meses sempre de novo: chegam homologações), em paralelo
    tarefas = []
    for m in range(1, 0 if so_gerar else HOJE.month + 1):
        ini = date(ANO, m, 1)
        fim = min(HOJE, (date(ANO, m + 1, 1) if m < 12 else date(ANO + 1, 1, 1)) - timedelta(days=1))
        for mod in MODALIDADES:
            k = f"{ANO}{m:02d}-{mod}"
            if k in meses and m < HOJE.month - 1:
                continue
            tarefas.append((k, ini, fim, mod))
    with ThreadPoolExecutor(8) as ex:
        for (k, ini, fim, mod), lst in zip(tarefas, ex.map(lambda t: listar(t[1], t[2], t[3]), tarefas)):
            meses[k] = [c["id"] for c in lst]
            for c in lst:
                compras[c["id"]] = {**compras.get(c["id"], {}), **c}
    print(f"  listagem: {len(tarefas)} consultas, {len(compras)} compras estaduais no cache")
    CACHE.write_text(json.dumps(cache, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    # resultados das homologadas ainda não lidas (as maiores primeiro)
    pend = sorted((c for c in compras.values() if c.get("homologado") and (c.get("res") is None or c["res"].get("itens") == 0)),
                  key=lambda c: -(c.get("homologado") or 0))[:0 if so_gerar else limite]
    print(f"  resultados: {len(pend)} compras homologadas para ler")
    feitos = 0
    with ThreadPoolExecutor(6) as ex:
        for c, r in zip(pend, ex.map(resultados, pend)):
            compras[c["id"]]["res"] = r
            feitos += 1
            if feitos % 100 == 0:
                print(f"  {feitos}/{len(pend)}")
                CACHE.write_text(json.dumps(cache, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    CACHE.write_text(json.dumps(cache, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    lst = [c for c in compras.values() if str(c.get("ano")) == str(ANO) or (c.get("data") or "").startswith(str(ANO))]
    forn = {}
    for c in lst:
        for v in (c.get("res") or {}).get("vencedores", []):
            f = forn.setdefault(v["cnpj"], {"cnpj": v["cnpj"], "nome": v["nome"], "valor": 0.0, "compras": 0, "orgaos": set()})
            f["valor"] += v["valor"]
            f["compras"] += 1
            f["orgaos"].add(c.get("orgao") or "")
    todos = [{**a, "compra": c["id"], "orgao": c.get("orgao"), "objeto": c.get("objeto", "")[:160],
              "diferenca": round((a["homologado"] - a["estimado"]) * (a["quantidade"] or 0), 2)}
             for c in lst for a in (c.get("res") or {}).get("acimaEstimado", [])]
    # mais de 3x o estimado é quase sempre erro de cadastro no PNCP (vírgula, unidade, preço do lote no lugar do unitário)
    acima = [a for a in todos if a["homologado"] <= 3 * a["estimado"]]
    erros = [a for a in todos if a["homologado"] > 3 * a["estimado"]]
    por_mod = {}
    for c in lst:
        d = por_mod.setdefault(c["modalidade"], {"modalidade": c["modalidade"], "compras": 0, "estimado": 0.0, "homologado": 0.0})
        d["compras"] += 1
        d["estimado"] += c.get("estimado") or 0
        d["homologado"] += c.get("homologado") or 0
    SAIDA.write_text(json.dumps({
        "ano": ANO, "ultimaAtualizacao": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "fonte": "Portal Nacional de Contratações Públicas (PNCP) — órgãos da esfera estadual de MS",
        "total": len(lst), "homologadas": sum(1 for c in lst if c.get("homologado")),
        "comResultado": sum(1 for c in lst if (c.get("res") or {}).get("vencedores")),
        "modalidades": sorted(({**v, "estimado": round(v["estimado"], 2), "homologado": round(v["homologado"], 2)} for v in por_mod.values()),
                              key=lambda v: -v["estimado"]),
        "compras": sorted(({k: v for k, v in c.items() if k not in ("res", "cnpjOrgao", "seq")} |
                           {"vencedores": (c.get("res") or {}).get("vencedores", [])[:5],
                            "link": f"https://pncp.gov.br/app/editais/{c['cnpjOrgao']}/{c['ano']}/{c['seq']}"} for c in lst),
                          key=lambda c: -(c.get("homologado") or c.get("estimado") or 0)),
        "fornecedores": sorted(({**f, "valor": round(f["valor"], 2), "orgaos": sorted(f["orgaos"])[:5]} for f in forn.values()),
                               key=lambda f: -f["valor"])[:500],
        "acimaEstimado": sorted(acima, key=lambda a: -a["diferenca"])[:300],
        "provaveisErros": sorted(erros, key=lambda a: -a["diferenca"])[:50]}, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"✅ governo_ms_licitacoes.json — {len(lst)} compras, {len(forn)} fornecedores vencedores, {len(acima)} itens acima do estimado")


if __name__ == "__main__":
    main()
