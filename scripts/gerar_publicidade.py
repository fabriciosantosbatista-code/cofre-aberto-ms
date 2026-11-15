#!/usr/bin/env python3
"""
Cofre Aberto MS — gasto com publicidade e propaganda do Governo de MS e da Prefeitura de Campo Grande

  Prefeitura de CG  despesas pagas na categoria "88 - Serviços de publicidade e propaganda" (dados/prefeitura.json):
                    por agência, por órgão e por mês, com o link de cada empenho
  Governo de MS     o que o Estado pagou no ano a agências de publicidade, propaganda e marketing (dados/governo_ms_credores.json),
                    identificadas pelo nome na Receita e pelas agências que a Prefeitura paga na categoria de publicidade;
                    contratos dessas agências (dados/governo_ms_contratos.json) e, quando o robô já leu, quais órgãos pagaram
                    (pagadores)

O portal do Estado não separa a despesa por tipo (natureza) na consulta pública por credor: o valor é tudo o que a agência
recebeu do Estado no ano — na prática, publicidade, já que é o serviço dessas empresas.

Gera dados/publicidade.json.
"""

import json, re
from datetime import datetime
from pathlib import Path

DADOS = Path(__file__).parent.parent / "dados"
AGENCIA = re.compile(r"PUBLICID|PROPAGAND|MARKETING|COMUNICA[CÇ][AÃ]O (INTEGRADA|E MARKETING|& MARKETING|E PLANEJAMENTO|ESTRAT)|"
                     r"COMUNICA[CÇ][OÕ]ES? LTDA|\bCOMUNICA[CÇ][AÃ]O LTDA", re.I)
NAO = re.compile(r"TELECOMUNICA|TELEF|EMBRATEL|CLARO S|TELEFONICA|AG[EÊ]NCIA (NACIONAL|ESTADUAL|DE DES|MUNICIPAL)|SECRETARIA|"
                 r"FUNDO|INSTITUTO|UNIVERSIDADE|EMPRESA BRASIL DE COMUNICA|TURISMO|EVENTOS|CAPACITA", re.I)
CAT_PREF = "88 - SERVIÇOS DE PUBLICIDADE E PROPAGANDA"
MESES = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]


def carregar(nome):
    try:
        return json.load(open(DADOS / nome, encoding="utf-8"))
    except Exception:
        return {}


def dig(t):
    return re.sub(r"\D", "", str(t or ""))


def main():
    pref = carregar("prefeitura.json")
    pub = [r for r in pref.get("despesas") or [] if (r.get("categoria") or "").upper().startswith("88 - SERVI")]
    raiz_pref = {dig(r.get("cnpj"))[:8] for r in pub if dig(r.get("cnpj"))}

    ag = {}

    def agencia(cnpj, nome):
        k = dig(cnpj)[:8] or nome
        a = ag.setdefault(k, {"raiz": k, "cnpj": dig(cnpj), "nome": re.sub(r"\s+", " ", nome or "").strip(), "estado": 0.0,
                              "estadoEmpenhado": 0.0, "prefeitura": 0.0, "orgaosPrefeitura": {}, "orgaosEstado": [], "contratosEstado": []})
        return a

    # Prefeitura
    por_mes, por_orgao = {}, {}
    for r in pub:
        v = float(r.get("valor") or 0)
        a = agencia(r.get("cnpj"), r.get("fornecedor"))
        a["prefeitura"] += v
        a["orgaosPrefeitura"][r.get("orgao") or "—"] = a["orgaosPrefeitura"].get(r.get("orgao") or "—", 0) + v
        m = (r.get("data") or "")[:7]
        por_mes[m] = por_mes.get(m, 0) + v
        por_orgao[r.get("orgao") or "—"] = por_orgao.get(r.get("orgao") or "—", 0) + v

    # Governo do Estado
    cred = carregar("governo_ms_credores.json").get("credores") or []
    for c in cred:
        doc, nome, pago, emp = c[0], c[1], c[2] or 0, c[3] or 0
        if len(dig(doc)) != 14:
            continue
        if not ((AGENCIA.search(nome) and not NAO.search(nome)) or dig(doc)[:8] in raiz_pref):
            continue
        if not pago and not emp:
            continue
        a = agencia(doc, nome)
        a["estado"] += pago
        a["estadoEmpenhado"] += emp
    gc = carregar("governo_ms_contratos.json")
    pag = gc.get("pagadores") or {}
    for c in gc.get("contratos") or []:
        k = dig(c.get("cnpj"))[:8]
        if k in ag and ag[k]["estado"]:
            ag[k]["contratosEstado"].append({x: c.get(x) for x in ("orgao", "orgaoNome", "numero", "valor", "inicio", "fim", "modalidade")})
    for doc, lst in pag.items():
        k = dig(doc)[:8]
        if k in ag:
            orgs = {}
            for o, pago, emp, *_ in lst:
                orgs[o] = orgs.get(o, 0) + (pago or 0)
            ag[k]["orgaosEstado"] = sorted(([o, round(v, 2)] for o, v in orgs.items()), key=lambda t: -t[1])

    paginas = carregar("empresas_index.json") or {}
    lista = []
    for a in ag.values():
        a["pagina"] = f"/empresa/{a['raiz']}/" if a["raiz"] in paginas else None
        a["total"] = round(a["estado"] + a["prefeitura"], 2)
        if not a["total"]:
            continue
        a["estado"], a["prefeitura"], a["estadoEmpenhado"] = round(a["estado"], 2), round(a["prefeitura"], 2), round(a["estadoEmpenhado"], 2)
        a["orgaosPrefeitura"] = sorted(([o, round(v, 2)] for o, v in a["orgaosPrefeitura"].items()), key=lambda t: -t[1])
        lista.append(a)
    lista.sort(key=lambda a: -a["total"])
    ano = pref.get("ano") or datetime.now().year
    meses = [{"mes": f"{ano}-{i:02d}", "rotulo": MESES[i - 1], "valor": round(por_mes.get(f"{ano}-{i:02d}", 0), 2)} for i in range(1, 13)]
    datas = sorted(r.get("data") for r in pref.get("despesas") or [] if r.get("data"))
    (DADOS / "publicidade.json").write_text(json.dumps({
        "ano": ano, "geradoEm": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "estado": {"total": round(sum(a["estado"] for a in lista), 2), "agencias": sum(1 for a in lista if a["estado"]),
                   "coleta": carregar("governo_ms.json").get("ultimaAtualizacao"),
                   "fonte": "Portal da Transparência do Estado de MS — despesas por credor (pagamentos do ano)"},
        "prefeitura": {"total": round(sum(por_mes.values()), 2), "agencias": sum(1 for a in lista if a["prefeitura"]),
                       "pagamentos": len(pub), "ate": datas[-1] if datas else None, "coleta": pref.get("ultimaAtualizacao"),
                       "fonte": "SIG-Transparência da Prefeitura de Campo Grande — despesas da categoria 88 (publicidade e propaganda)",
                       "porMes": meses, "porOrgao": sorted(([o, round(v, 2)] for o, v in por_orgao.items()), key=lambda t: -t[1])},
        "agencias": lista,
        "pagamentosPrefeitura": sorted(({x: r.get(x) for x in ("data", "orgao", "fornecedor", "cnpj", "valor", "empenhado", "processo", "urlDetalhe")}
                                        for r in pub), key=lambda r: -(r["valor"] or 0))[:400]},
        ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"✅ publicidade.json — Estado R$ {sum(a['estado'] for a in lista):,.0f} ({sum(1 for a in lista if a['estado'])} agências), "
          f"Prefeitura R$ {sum(por_mes.values()):,.0f} ({len(pub)} pagamentos)")


if __name__ == "__main__":
    main()
