#!/usr/bin/env python3
"""
Cofre Aberto MS — Diárias de viagem: comparação entre os órgãos de MS

Junta o que cada órgão publica de diárias no ano, a partir dos arquivos que as
coletas já gravam:
  Governo do Estado     governo_ms.json (diárias do Portal da Transparência)
  Prefeitura de CG      prefeitura.json (despesas com elemento "Diárias")
  Câmara Municipal CG   camara_municipal.json → "diarias" (endpoint do Fiorilli)
  Assembleia (ALEMS)    alems_servidores.json → "diarias" (consulta de diárias)
  Câmaras do interior   dados/camaras/*.json (diárias dos vereadores)

Para cada órgão diz também a situação: publica diárias, declara zero, ou não
publica nada. Gera dados/diarias_comparacao.json (aba Governo MS do painel).
"""

import json
from datetime import datetime

from gerar_analises import ANO, DADOS, carregar, salvar


def milhar(n):
    return f"{int(n or 0):,}".replace(",", ".")


def main():
    orgaos = []
    gov = carregar("governo_ms.json")
    di = gov.get("diarias") if gov.get("ano") == ANO else None
    if di:
        orgaos.append({"orgao": "Governo do Estado de MS", "total": di["total"], "situacao": "publica", "aba": "governo-ms",
                       "detalhe": f"{milhar(di.get('trechos', 0))} trechos de viagem, {milhar(di.get('beneficiarios', 0))} beneficiários",
                       "fonte": "Portal da Transparência do Estado"})

    pref = carregar("prefeitura.json")
    if pref.get("ano") == ANO:
        tot, n, por = 0.0, 0, {}
        for d in pref.get("despesas", []):
            if "DIÁRIA" in (d.get("categoria") or "").upper() or "DIARIA" in (d.get("categoria") or "").upper():
                tot += d.get("valor") or 0
                n += 1
                por[d.get("orgao") or "—"] = por.get(d.get("orgao") or "—", 0) + (d.get("valor") or 0)
        top = max(por.items(), key=lambda kv: kv[1])[0] if por else None
        orgaos.append({"orgao": "Prefeitura de Campo Grande", "total": round(tot, 2), "situacao": "publica" if n else "zero",
                       "aba": "prefeitura", "fonte": "SIG-Transparência (despesas com elemento Diárias)",
                       "detalhe": f"{n} empenhos de diárias" + (f"; maior gasto: {top}" if top else "")})

    cg = carregar("camara_municipal.json").get("diarias")
    if cg and cg.get("ano") == ANO:
        orgaos.append({"orgao": "Câmara Municipal de Campo Grande", "total": cg["total"],
                       "situacao": "publica" if cg["registros"] else "nao_publica", "aba": "camara",
                       "fonte": "Portal da Transparência da Câmara (Fiorilli)",
                       "detalhe": (f"{cg['registros']} diárias pagas" if cg["registros"] else
                                   "o portal da Câmara não traz nenhuma diária no ano (consulta de diárias vazia)")})

    al = carregar("alems_servidores.json").get("diarias") or {}
    if str(ANO) in al:
        d = al[str(ANO)]
        anos_zero = [a for a, x in sorted(al.items()) if x["mesesSemDiarias"] >= 11 and not x["totalEncontrado"]]
        orgaos.append({"orgao": "Assembleia Legislativa (ALEMS)", "total": d["totalEncontrado"],
                       "situacao": "zero" if not d["totalEncontrado"] else "publica", "aba": "deputados-estaduais",
                       "fonte": "Consulta de diárias da ALEMS",
                       "detalhe": (f"declara que não houve diárias em nenhum mês de {', '.join(anos_zero)}; as viagens dos deputados "
                                   "são pagas pela cota parlamentar (CEAP)") if not d["totalEncontrado"] else f"{d['mesesSemDiarias']} meses sem diárias"})

    tot, cidades, com = 0.0, 0, 0
    for f in sorted((DADOS / "camaras").glob("*.json")):
        j = carregar(f"camaras/{f.name}")
        if not j:
            continue
        cidades += 1
        v = sum(x.get(f"totalDiarias{ANO}") or 0 for x in j.get("vereadores", []))
        tot += v
        com += v > 0
    if cidades:
        orgaos.append({"orgao": "Câmaras municipais do interior", "total": round(tot, 2), "situacao": "publica" if com else "zero",
                       "aba": "camaras-ms", "fonte": "Portais Fiorilli/SAPL das câmaras",
                       "detalhe": f"diárias de vereadores em {com} de {cidades} câmaras com dados"})

    orgaos.sort(key=lambda o: -(o["total"] or 0))
    salvar("diarias_comparacao.json", {"ano": ANO, "ultimaAtualizacao": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
                                       "nota": "Valores pagos no ano segundo o que cada órgão publica. Deputados federais e senadores não recebem diárias: as viagens entram na cota parlamentar.",
                                       "orgaos": orgaos})
    print("✅ diarias_comparacao.json — " + ", ".join(f"{o['orgao']}: R$ {o['total']:,.0f} ({o['situacao']})" for o in orgaos))


if __name__ == "__main__":
    main()
