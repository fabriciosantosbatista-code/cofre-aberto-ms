#!/usr/bin/env python3
"""
Cofre Aberto MS — checagem automática da folha de Supersalários (todos os contracheques do mês)

Lê a folha completa gravada pela coleta (folha_completa/folha_supersalarios.jsonl.gz — fora do Git, sem CPF; não vira artefato público)
e aplica, a cada contracheque e a cada órgão:

  duplicidade    a mesma matrícula duas vezes no mesmo órgão e mês (sem matrícula na fonte: nome + cargo + lotação)
  rubricas       bruto = salário-base + soma das rubricas (só onde a fonte publica as rubricas: TJMS, TRT24, membros do TCE)
  líquido        líquido = bruto − descontos (tolerância R$ 0,05). No Governo do Estado a folha não publica os descontos
                 (são calculados como bruto − líquido): ali a checagem só detecta líquido maior que o bruto
  faixa          valor negativo, ou bruto acima de R$ 500.000 no mês
  estorno x teto com valor negativo (estorno), refaz bruto e líquido sem ele: alerta se cruzar o teto em qualquer sentido
  variação       quantidade de pessoas e total bruto do órgão variando mais de 15% em relação ao mês anterior registrado
  total externo  total bruto do órgão contra uma fonte independente, tolerância 10% — TJMS e TRT24 no resumo do
                 DadosJusBr. Governo do Estado: não aplicada (a API pública do Estado não expõe a despesa por elemento
                 3.1.90.xx por mês). MPMS: fora da base

Saídas:
  dados/verificacao/alertas_AAAA-MM.csv      só o que deu problema (um arquivo por mês de competência)
  dados/verificacao/checagem_AAAA-MM.json    resumo: por órgão, quais checagens foram aplicadas e quantos alertas
  dados/verificacao/checagem_ultima.json     o mesmo resumo da checagem mais recente (lido pelo site)
  dados/verificacao/totais_orgaos.json       pessoas e total bruto por órgão e mês (base da variação mês a mês)

Uso: python3 scripts/verificacao/checagem_automatica.py [--folha ARQUIVO] [--saida PASTA]
"""

import collections, csv, gzip, json, sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
SAIDA = ROOT / "dados" / "verificacao"
TOL, VARIACAO, TETO_ABSURDO, TOL_EXTERNO = 0.05, 0.15, 500_000, 0.10
FOLHA = ROOT / "folha_completa" / "folha_supersalarios.jsonl.gz"
TETO = 46366.19  # subsídio de ministro do STF (o mesmo da aba Supersalários)


def arg(nome, padrao):
    return sys.argv[sys.argv.index(nome) + 1] if nome in sys.argv else padrao


def unidade(p):
    """Órgão para as checagens: cada órgão do Governo separado (pela sigla); os demais pelo órgão da fonte."""
    return f"Governo MS — {p['orgaoSigla']}" if p.get("orgaoId") == "governo" and p.get("orgaoSigla") else p.get("orgao") or p.get("orgaoId")


def mes_iso(m):
    mm, aa = (m or "00/0000").split("/")
    return f"{aa}-{mm}"


def externo_dadosjusbr(oid, mes):
    """Total bruto (base + outras remunerações) do resumo mensal do DadosJusBr — independente do pacote de contracheques."""
    import requests
    mm, aa = mes.split("/")
    try:
        d = requests.get(f"https://api.dadosjusbr.org/v2/dados/{oid}/{int(aa)}/{int(mm)}", timeout=60).json()
        s = (d.get("sumarios") or {}).get("membros_ativos") or {}
        return round(((s.get("remuneracao_base") or {}).get("total") or 0) + ((s.get("outras_remuneracoes") or {}).get("total") or 0), 2)
    except Exception:
        return None


def main():
    global SAIDA
    SAIDA = Path(arg("--saida", SAIDA))
    arq = Path(arg("--folha", FOLHA))
    if not arq.exists():
        print(f"ℹ️ folha completa não encontrada ({arq}) — checagem não feita")
        return 0
    folha = [json.loads(l) for l in gzip.open(arq, "rt", encoding="utf-8") if l.strip()]
    if any("cpf" in {k.lower() for k in p} for p in folha):
        print("❌ a folha completa tem campo de CPF — não deveria; checagem interrompida (o artefato não é enviado)")
        return 1
    sys.path.insert(0, str(ROOT / "tests"))
    from test_cpf import achar  # detector independente de CPF do projeto
    achados = achar(gzip.open(arq, "rt", encoding="utf-8").read(), "json")
    if achados:
        print(f"❌ o detector achou {len(achados)} CPF(s) completo(s) na folha — checagem interrompida (o artefato não é enviado)")
        return 1
    alertas, aplicadas = [], collections.defaultdict(set)

    def alerta(tipo, p, detalhe, valor=None):
        alertas.append({"tipo": tipo, "orgao": unidade(p) if isinstance(p, dict) else p, "mes": p.get("mes") if isinstance(p, dict) else None,
                        "nome": p.get("nome") if isinstance(p, dict) else "", "matricula": p.get("matricula") if isinstance(p, dict) else "",
                        "detalhe": detalhe, "valor": valor})

    grupos = collections.defaultdict(list)
    for p in folha:
        grupos[(unidade(p), p.get("mes"))].append(p)
    for (org, mes), ps in grupos.items():
        oid = ps[0].get("orgaoId")
        # duplicidade
        aplicadas[org].add("duplicidade")
        chave = (lambda p: ("matrícula", p["matricula"])) if all(p.get("matricula") for p in ps) else \
                (lambda p: ("nome+cargo+lotação", (p.get("nome"), p.get("cargo"), p.get("lotacao"))))
        cont = collections.Counter(chave(p) for p in ps)
        for p in ps:
            if cont[chave(p)] > 1:
                alerta("duplicidade", p, f"{chave(p)[0]} repetida no mesmo mês ({cont[chave(p)]} vezes)")
        for p in ps:
            # rubricas (só onde há)
            if p.get("itens"):
                aplicadas[org].add("rubricas")
                soma = round((p.get("base") or 0) + sum(i.get("valor") or 0 for i in p["itens"]), 2)
                if abs(soma - (p.get("bruto") or 0)) > TOL:
                    alerta("rubricas", p, f"bruto {p['bruto']} ≠ base + rubricas {soma}", round(p["bruto"] - soma, 2))
            # líquido
            aplicadas[org].add("liquido" if oid != "governo" else "liquido_maior_que_bruto")
            if oid == "governo":
                if (p.get("liquido") or 0) > (p.get("bruto") or 0) + TOL:
                    alerta("liquido", p, f"líquido {p['liquido']} maior que o bruto {p['bruto']}", round(p["liquido"] - p["bruto"], 2))
            elif abs((p.get("bruto") or 0) - (p.get("descontos") or 0) - (p.get("liquido") or 0)) > TOL:
                alerta("liquido", p, f"líquido {p['liquido']} ≠ bruto {p['bruto']} − descontos {p['descontos']}",
                       round(p["bruto"] - p["descontos"] - p["liquido"], 2))
            # faixa
            aplicadas[org].add("faixa")
            neg = [k for k in ("base", "outras", "bruto", "descontos", "liquido") if (p.get(k) or 0) < 0]
            if neg:
                alerta("faixa", p, f"valor negativo em {', '.join(neg)}", min(p.get(k) or 0 for k in neg))
            if neg:  # estorno: refaz bruto e líquido SEM ele e vê se cruza o teto (lista dos 2.450 pelo bruto, dos 421 pelo líquido)
                aplicadas[org].add("estorno_x_teto")
                e = -sum(min(0, p.get(k) or 0) for k in ("base", "outras"))
                for rot, antes in (("bruto", p.get("bruto") or 0), ("líquido", p.get("liquido") or 0)):
                    if (antes > TETO) != (antes + e > TETO):
                        alerta("estorno_cruza_teto", p, f"sem o estorno de {e:.2f}, o {rot} ({antes:.2f} → {antes + e:.2f}) "
                               f"{'passa' if antes + e > TETO else 'deixa de passar'} do teto", round(antes + e, 2))
            if (p.get("bruto") or 0) > TETO_ABSURDO:
                alerta("faixa", p, f"bruto acima de R$ {TETO_ABSURDO:,.0f} no mês".replace(",", "."), p["bruto"])

    # variação mês a mês (pessoas e total bruto por órgão)
    hist_arq = SAIDA / "totais_orgaos.json"
    try:
        hist = json.load(open(hist_arq, encoding="utf-8"))
    except Exception:
        hist = {}
    for (org, mes), ps in grupos.items():
        aplicadas[org].add("variacao")
        atual = {"pessoas": len(ps), "bruto": round(sum(p.get("bruto") or 0 for p in ps), 2)}
        meses = hist.setdefault(org, {})
        anteriores = sorted(m for m in meses if m < mes_iso(mes))
        if anteriores:
            ant = meses[anteriores[-1]]
            for k, rot in (("pessoas", "quantidade de pessoas"), ("bruto", "total bruto")):
                if ant.get(k) and abs(atual[k] - ant[k]) / ant[k] > VARIACAO:
                    alerta("variacao", {"orgao": org, "mes": mes, "nome": "", "matricula": "", "orgaoId": ps[0].get("orgaoId")},
                           f"{rot} variou {100 * (atual[k] - ant[k]) / ant[k]:+.1f}% em relação a {anteriores[-1]} ({ant[k]} → {atual[k]})", atual[k])
        meses[mes_iso(mes)] = atual

    # total contra fonte externa (DadosJusBr) — só o Judiciário
    externos = {}
    for (org, mes), ps in grupos.items():
        oid = ps[0].get("orgaoId")
        if oid in ("tjms", "trt24", "trems"):
            aplicadas[org].add("total_externo")
            ext = externo_dadosjusbr(oid, mes)
            tot = round(sum((p.get("bruto") or 0) + (p.get("diarias") or 0) for p in ps), 2)  # o DadosJusBr inclui diárias
            externos[org] = {"site": tot, "fonte": ext, "fonteUrl": f"https://dadosjusbr.org/orgao/{oid}/{mes_iso(mes)[:4]}/{int(mes_iso(mes)[5:])}"}
            if ext is None:
                externos[org]["resultado"] = "fonte indisponível"
            elif ext and abs(tot - ext) / ext > TOL_EXTERNO:
                externos[org]["resultado"] = "diverge"
                alerta("total_externo", {"orgao": org, "mes": mes, "nome": "", "matricula": "", "orgaoId": oid},
                       f"total bruto {tot} difere mais de 10% do resumo do DadosJusBr ({ext})", round(tot - ext, 2))
            else:
                externos[org]["resultado"] = "confere"

    SAIDA.mkdir(parents=True, exist_ok=True)
    meses_comp = sorted({mes_iso(p.get("mes")) for p in folha})
    for m in meses_comp:
        do_mes = [a for a in alertas if a["mes"] and mes_iso(a["mes"]) == m]
        with open(SAIDA / f"alertas_{m}.csv", "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["tipo", "orgao", "mes", "nome", "matricula", "detalhe", "valor"])
            w.writeheader()
            w.writerows(do_mes)
    resumo = {"geradoEm": datetime.now().isoformat(timespec="seconds"), "contracheques": len(folha), "orgaos": len(aplicadas),
              "mesesCompetencia": meses_comp, "alertas": len(alertas), "porTipo": dict(collections.Counter(a["tipo"] for a in alertas)),
              "naoAplicadas": {"total_externo do Governo do Estado": "a API pública do Estado não expõe a despesa por elemento 3.1.90.xx por mês",
                               "rubricas fora do Judiciário e dos membros do TCE-MS": "a fonte publica só totais",
                               "líquido = bruto − descontos no Governo do Estado": "a folha não publica os descontos; só se detecta líquido maior que o bruto"},
              "porOrgao": {org: {"checagens": sorted(aplicadas[org]), "alertas": sum(1 for a in alertas if a["orgao"] == org),
                                 **({"totalExterno": externos[org]} if org in externos else {})} for org in sorted(aplicadas)}}
    for m in meses_comp:
        (SAIDA / f"checagem_{m}.json").write_text(json.dumps(resumo, ensure_ascii=False, indent=1), encoding="utf-8")
    (SAIDA / "checagem_ultima.json").write_text(json.dumps(resumo, ensure_ascii=False, indent=1), encoding="utf-8")  # lida pelo site
    hist_arq.write_text(json.dumps(hist, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    print(f"✅ checagem automática: {len(folha):,} contracheques, {len(aplicadas)} órgãos, {len(alertas)} alerta(s) {dict(resumo['porTipo'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
