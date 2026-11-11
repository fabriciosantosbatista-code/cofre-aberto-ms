#!/usr/bin/env python3
"""
Cofre Aberto MS — Pontos de atenção nos contratos e licitações da Prefeitura de CG

Lê dados/prefeitura_contratos.json (coletar_contratos_cg.py) e as notas dos
parlamentares e marca, sem julgar, o que merece um olhar:

  contrato_grande      contrato de compra/serviço/obra de R$ 1 mi ou mais iniciado
                       nos últimos 45 dias
  sem_licitacao        dispensa ou inexigibilidade (contratação sem disputa) de
                       R$ 500 mil ou mais nos últimos 60 dias
  muitas_vitorias      empresa que já venceu 5 ou mais licitações no ano
  conexao_parlamentar  empresa com contrato na Prefeitura que também recebeu de
                       vereador, deputado ou senador de MS (cota/verba)
  vigencia_longa       contrato com vigência de mais de 5 anos

Nada disso indica irregularidade: são critérios objetivos para facilitar a
apuração. Cada alerta guarda a data em que apareceu pela primeira vez
("vistoEm"), para o feed RSS mostrar só o que é novo.

Gera dados/alertas_contratos.json e dados/feeds/contratos-cg.xml.
"""

import hashlib, json, re
from email.utils import format_datetime
from datetime import date, datetime, timedelta

from gerar_analises import ANO, DADOS, PAINEL, brl, carregar, cnpj_valido, parlamentares, rss, salvar

HOJE = date.today()
LIMITE_GRANDE = 1_000_000
LIMITE_SEM_LICITACAO = 500_000
VITORIAS = 5
ROTULO = {"contrato_grande": "Contrato grande recente", "sem_licitacao": "Sem licitação",
          "muitas_vitorias": "Muitas licitações vencidas", "conexao_parlamentar": "Também pago por parlamentar",
          "vigencia_longa": "Vigência longa"}


def dias_atras(iso):
    try:
        return (HOJE - date.fromisoformat(str(iso)[:10])).days
    except ValueError:
        return None


def ident(*partes):
    return hashlib.sha1("|".join(str(p) for p in partes).encode()).hexdigest()[:12]


def pagadores_parlamentares():
    """raiz do CNPJ → {nome do parlamentar: (rótulo, aba, total)}"""
    out = {}
    for grupo, aba, rotulo, v, notas in parlamentares():
        for n in notas:
            d = re.sub(r"\D", "", str(n.get("cnpj") or ""))
            if not cnpj_valido(d) or not n.get("valor"):
                continue
            p = out.setdefault(d[:8], {}).setdefault(v["nome"], [rotulo, aba, 0.0])
            p[2] += float(n["valor"])
    return out


def main():
    ct = carregar("prefeitura_contratos.json")
    if not ct or ct.get("ano") != ANO:
        print("⚠️ prefeitura_contratos.json ausente ou de outro ano — alertas não gerados")
        return
    anterior = {a["id"]: a for a in (carregar("alertas_contratos.json") or {}).get("alertas", [])}
    par = pagadores_parlamentares()
    alertas = []

    def add(tipo, chave, titulo, descricao, valor, data_evento, empresa=None, cnpj=None, link=None):
        i = ident(tipo, *chave)
        alertas.append({"id": i, "tipo": tipo, "rotulo": ROTULO[tipo], "titulo": titulo, "descricao": descricao,
                        "valor": round(valor or 0, 2), "data": data_evento, "empresa": empresa, "cnpj": cnpj,
                        "link": link or "#aba=contratos-cg",
                        "vistoEm": anterior.get(i, {}).get("vistoEm") or HOJE.isoformat()})

    for c in ct.get("contratos", []):
        if not c.get("compra"):
            continue
        d = dias_atras(c.get("inicio"))
        busca = f"#aba=contratos-cg&p={c['cnpj'] or c['fornecedor']}"
        if d is not None and 0 <= d <= 45 and c["valor"] >= LIMITE_GRANDE:
            add("contrato_grande", (c["fornecedor"], c["inicio"], c["valor"]),
                f"{c['fornecedor']}: contrato de {brl(c['valor'])}",
                f"{c['tipo'].capitalize()} iniciado em {c['inicio'][8:10]}/{c['inicio'][5:7]}: {c['objeto'][:220]}",
                c["valor"], c["inicio"], c["fornecedor"], c["cnpj"], busca)
        try:
            anos = (date.fromisoformat(c["fim"]) - date.fromisoformat(c["inicio"])).days / 365.25
        except (TypeError, ValueError):
            anos = 0
        if anos > 5:
            add("vigencia_longa", (c["fornecedor"], c["inicio"], c["fim"]),
                f"{c['fornecedor']}: contrato de {anos:.0f} anos",
                f"Vigência de {c['inicio'][8:10]}/{c['inicio'][5:7]}/{c['inicio'][:4]} a {c['fim'][8:10]}/{c['fim'][5:7]}/{c['fim'][:4]}"
                f", {brl(c['valor'])}: {c['objeto'][:200]}", c["valor"], c["inicio"], c["fornecedor"], c["cnpj"], busca)

    for l in ct.get("licitacoes", []):
        mod = (l.get("modalidade") or "").lower()
        d = dias_atras(l.get("data"))
        if ("dispensa" in mod or "inexig" in mod) and d is not None and 0 <= d <= 60 \
                and (l.get("valorEstimado") or 0) >= LIMITE_SEM_LICITACAO:
            venc = ", ".join(v["nome"] for v in l["vencedores"][:3]) or "vencedor ainda não publicado"
            add("sem_licitacao", (l["processo"], l["numero"]),
                f"{l['modalidade']} de {brl(l['valorEstimado'])}",
                f"{l['objeto'][:220]} — {venc}. Processo {l['processo']}.",
                l["valorEstimado"], l["data"], (l["vencedores"][0]["nome"] if l["vencedores"] else None),
                (l["vencedores"][0]["cnpj"] if l["vencedores"] else None), f"#aba=contratos-cg&p={l['processo']}")

    for f in ct.get("fornecedores", []):
        if f.get("licitacoesVencidas", 0) >= VITORIAS:
            add("muitas_vitorias", (f["cnpj"] or f["nome"],),
                f"{f['nome']}: {f['licitacoesVencidas']} licitações vencidas em {ANO}",
                f"{f['contratos']} contrato(s) somando {brl(f['valorContratos'])} no ano.",
                f["valorContratos"], None, f["nome"], f["cnpj"], f"#aba=contratos-cg&p={f['cnpj'] or f['nome']}")
        d = re.sub(r"\D", "", f.get("cnpj") or "")
        if len(d) == 14 and d[:8] in par and f.get("contratos"):
            quem = sorted(par[d[:8]].items(), key=lambda kv: -kv[1][2])
            nomes = ", ".join(f"{n} ({r}, {brl(t)})" for n, (r, a, t) in quem[:3])
            add("conexao_parlamentar", (d[:8],),
                f"{f['nome']}: contrato na Prefeitura e notas de parlamentar",
                f"{f['contratos']} contrato(s), {brl(f['valorContratos'])}. Também recebeu de: {nomes}"
                + (f" e mais {len(quem) - 3}" if len(quem) > 3 else "") + ".",
                f["valorContratos"], None, f["nome"], d, f"#aba=conexoes&p={d}")

    alertas.sort(key=lambda a: (a["vistoEm"], a["data"] or "", a["valor"]), reverse=True)
    resumo = {t: sum(1 for a in alertas if a["tipo"] == t) for t in ROTULO}
    salvar("alertas_contratos.json", {
        "ano": ANO, "ultimaAtualizacao": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "criterios": {"contrato_grande": f"contrato de {brl(LIMITE_GRANDE)} ou mais iniciado nos últimos 45 dias",
                      "sem_licitacao": f"dispensa ou inexigibilidade de {brl(LIMITE_SEM_LICITACAO)} ou mais nos últimos 60 dias",
                      "muitas_vitorias": f"empresa com {VITORIAS} ou mais licitações vencidas no ano",
                      "conexao_parlamentar": "empresa com contrato que também recebeu de vereador, deputado ou senador de MS",
                      "vigencia_longa": "contrato com vigência acima de 5 anos"},
        "nota": "Pontos de atenção por critérios objetivos. Nenhum deles indica irregularidade.",
        "resumo": resumo, "alertas": alertas})

    itens = []
    for a in alertas[:60]:
        dt = datetime.fromisoformat(a["vistoEm"]).replace(hour=12).astimezone()
        itens.append({"titulo": f"[{a['rotulo']}] {a['titulo']}", "link": PAINEL + a["link"], "guid": a["id"],
                      "data": format_datetime(dt), "descricao": a["descricao"]})
    (DADOS / "feeds").mkdir(parents=True, exist_ok=True)
    (DADOS / "feeds" / "contratos-cg.xml").write_text(rss(
        "Cofre Aberto MS — contratos e licitações da Prefeitura de CG", PAINEL + "#aba=contratos-cg",
        "Contratos grandes, contratações sem licitação e empresas que também recebem de parlamentares", itens),
        encoding="utf-8")
    print(f"✅ alertas_contratos.json — {len(alertas)} alertas: " + ", ".join(f"{k} {v}" for k, v in resumo.items()))


if __name__ == "__main__":
    main()
