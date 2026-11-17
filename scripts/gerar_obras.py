#!/usr/bin/env python3
"""
Cofre Aberto MS — obras atrasadas e paradas do Governo do Estado de MS

A partir dos contratos de obras do Portal da Transparência do Estado (dados/governo_ms_contratos.json, coletado por
coletar_contratos_governo.py), classifica cada obra ainda não concluída:

  vencida      o prazo atual (já com os aditivos) terminou há mais de 30 dias e a obra não chegou a 90% executada
  lenta        dentro do prazo, mas o % executado está 50 pontos ou mais atrás do tempo já decorrido
  paralisada   teve dias de paralisação registrados no contrato
  dobrada      os dias aditados passam do prazo inicial (o prazo mais que dobrou)

O "% executado" e as datas são os que o Estado publica; o portal não diz se a obra está parada HOJE, só quantos
dias ela ficou paralisada no total.

Gera dados/obras.json.
"""

import json
from datetime import date, datetime
from pathlib import Path

DADOS = Path(__file__).parent.parent / "dados"
HOJE = date.today()
ABERTAS = {"Em Execução", "Em Aberto", "Expirado"}


def obras_prefeitura():
    """Contratos de obra da Prefeitura de Campo Grande (portal de contratos: situação, vigência, aditivos e valor pago).
    A Prefeitura não publica o % executado; os sinais usam o que ela publica:
      paralisada   o próprio portal marca o contrato como PARALISADO
      vencida      a vigência terminou há mais de 30 dias, o contrato não foi encerrado e menos de 90% do valor foi pago
      dobrada      o valor total, com aditivos, é o dobro ou mais do valor original
      aditivos     5 ou mais termos aditivos"""
    try:
        a = json.load(open(DADOS / "prefeitura_aditivos.json", encoding="utf-8"))
    except Exception:
        return None
    out = []
    for reg, v in (a.get("contratos") or {}).items():
        if "OBRA" not in (v.get("tipo") or "").upper():
            continue
        vt, vc, pg = v.get("valorTotal") or 0, v.get("valorContrato") or 0, v.get("pago") or 0
        fim = date.fromisoformat(v["fim"]) if v.get("fim") else None
        sit = (v.get("situacao") or "").upper()
        n_ad = len(v.get("aditivos") or [])
        marcas = []
        if sit == "PARALISADO":
            marcas.append("paralisada")
        if fim and (HOJE - fim).days > 30 and vt and pg < 0.9 * vt and "ENCERRADO" not in sit:
            marcas.append("vencida")
        if vc and vt >= 2 * vc:
            marcas.append("dobrada")
        if n_ad >= 5:
            marcas.append("aditivos")
        out.append({"registro": reg, "processo": v.get("processo"), "orgao": v.get("orgao"), "fornecedor": v.get("fornecedor"),
                    "objeto": (v.get("objeto") or "")[:300], "situacao": sit.title(), "inicio": v.get("inicio"), "fim": v.get("fim"),
                    "valorOriginal": round(vc, 2), "valorTotal": round(vt, 2), "pago": round(pg, 2), "aditivos": n_ad,
                    "pctPago": round(pg / vt * 100, 1) if vt else None, "diasVencida": (HOJE - fim).days if fim and fim < HOJE else 0,
                    "marcas": marcas, "link": f"https://sig-transparencia.campogrande.ms.gov.br/contratos/detalhe/{reg}"})
    out.sort(key=lambda o: (not o["marcas"], -(o["valorTotal"] or 0)))
    resumo = {m: {"obras": sum(1 for o in out if m in o["marcas"]), "valor": round(sum(o["valorTotal"] for o in out if m in o["marcas"]), 2)}
              for m in ("paralisada", "vencida", "dobrada", "aditivos")}
    com = [o for o in out if o["marcas"]]
    return {"coleta": a.get("ultimaAtualizacao"), "fonte": "Portal da Transparência da Prefeitura de Campo Grande — contratos (situação, vigência, aditivos e pagamentos)",
            "total": {"obras": len(out), "valor": round(sum(o["valorTotal"] for o in out), 2)},
            "comProblema": {"obras": len(com), "valor": round(sum(o["valorTotal"] for o in com), 2)}, "resumo": resumo, "obras": out}


def main():
    try:
        g = json.load(open(DADOS / "governo_ms_contratos.json", encoding="utf-8"))
    except Exception as e:
        print(f"⚠️ sem contratos do Estado: {e}")
        return
    # a mesma obra pode vir com dois órgãos (ex.: AGESUL executa e FUNDERSUL financia): uma linha, os dois nomes
    unicas = {}
    for o in g.get("obras") or []:
        k = (o.get("numero"), o.get("processo"), o.get("cnpj"))
        if k in unicas:
            if o.get("orgao") and o["orgao"] not in unicas[k]["orgao"].split(" / "):
                unicas[k]["orgao"] += " / " + o["orgao"]
            continue
        unicas[k] = {**o, "orgao": o.get("orgao") or "—"}
    obras = []
    for o in unicas.values():
        ini = date.fromisoformat(o["inicio"]) if o.get("inicio") else None
        fim = date.fromisoformat(o["fim"]) if o.get("fim") else None
        ex = float(o.get("executado") or 0)
        prazo, adit, par = float(o.get("prazoInicial") or 0), float(o.get("diasAditados") or 0), float(o.get("diasParalisados") or 0)
        aberta = o.get("situacao") in ABERTAS and ex < 100
        tempo = None
        if ini and fim and fim > ini:
            tempo = round(min(1, max(0, (HOJE - ini).days / (fim - ini).days)) * 100, 1)
        marcas = []
        if aberta:
            if fim and (HOJE - fim).days > 30 and ex < 90:
                marcas.append("vencida")
            elif tempo is not None and fim and fim >= HOJE and (fim - ini).days > 60 and tempo - ex >= 50:
                marcas.append("lenta")
            if par > 0:
                marcas.append("paralisada")
            if prazo and adit > prazo:
                marcas.append("dobrada")
        obras.append({**{c: o.get(c) for c in ("numero", "processo", "orgao", "fornecedor", "cnpj", "objeto", "valor", "situacao", "inicio", "fim", "municipios")},
                      "prazoInicial": prazo, "diasAditados": adit, "diasParalisados": par, "executado": ex, "tempoDecorrido": tempo,
                      "diasVencida": (HOJE - fim).days if fim and fim < HOJE and aberta else 0, "aberta": aberta, "marcas": marcas})
    abertas = [o for o in obras if o["aberta"]]
    probl = [o for o in abertas if o["marcas"]]

    def soma(lst):
        return {"obras": len(lst), "valor": round(sum(o["valor"] or 0 for o in lst), 2)}

    def agrupa(campo):
        out = {}
        for o in probl:
            chaves = [m.strip() for m in (o[campo] or "—").split(",")] if campo == "municipios" else \
                (o[campo] or "—").split(" / ") if campo == "orgao" else [o[campo] or "—"]
            for k in chaves:
                a = out.setdefault(k, {"nome": k, "obras": 0, "valor": 0.0, "vencidas": 0, "paralisadas": 0})
                a["obras"] += 1
                a["valor"] += o["valor"] or 0
                a["vencidas"] += "vencida" in o["marcas"]
                a["paralisadas"] += "paralisada" in o["marcas"]
        return sorted(({**a, "valor": round(a["valor"], 2)} for a in out.values()), key=lambda a: (-a["obras"], -a["valor"]))

    pref = obras_prefeitura()
    (DADOS / "obras.json").write_text(json.dumps({
        "geradoEm": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"), "coleta": g.get("ultimaAtualizacao"),
        "fonte": "Portal da Transparência do Estado de MS — contratos de obras (transpcontrato/ContratosEkronos)",
        "total": soma(obras), "abertas": soma(abertas),
        "resumo": {m: soma([o for o in abertas if m in o["marcas"]]) for m in ("vencida", "lenta", "paralisada", "dobrada")},
        "comProblema": soma(probl),
        "porEmpresa": agrupa("fornecedor")[:60], "porOrgao": agrupa("orgao"), "porCidade": agrupa("municipios")[:60],
        "obras": sorted(abertas, key=lambda o: (not o["marcas"], -(o["valor"] or 0))), "prefeitura": pref}, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    r = {m: sum(1 for o in abertas if m in o["marcas"]) for m in ("vencida", "lenta", "paralisada", "dobrada")}
    print(f"✅ obras.json — {len(obras)} obras, {len(abertas)} em andamento, {len(probl)} com sinal: {r}")


if __name__ == "__main__":
    main()
