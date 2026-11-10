#!/usr/bin/env python3
"""
Cofre Aberto MS — histórico de um ano fechado (padrão: 2025)

Gera dados/historico_<ano>.json com o gasto MENSAL de cada parlamentar de MS
no ano informado, a partir das mesmas fontes oficiais usadas na coleta diária:

  - Deputados federais de MS — arquivo completo da Câmara (camara.leg.br/cotas)
  - Senadores de MS          — API de dados abertos do Senado (despesas_ceaps)
  - Deputados estaduais      — Portal da Transparência da ALEMS (/ceap/data + /ceap/notas)

Ano fechado não muda, então basta rodar uma vez (ou de novo se a fonte
corrigir algo):   python3 scripts/gerar_historico.py 2025

A Câmara Municipal de CG não entra: a verba indenizatória de anos anteriores
só existe em PDFs escaneados, sem a mesma qualidade de leitura.
"""

import json, re, sys, time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent))
import coletar_dados as cd  # reaproveita downloads/parsers da coleta diária

ANO = int(sys.argv[1]) if len(sys.argv) > 1 else 2025
DADOS = cd.DADOS


def mensal_vazio():
    return [0.0] * 12


def normaliza_nome(n):
    return re.sub(r"^Dep\.?\s*", "", n or "", flags=re.I).strip()


def federais_ms():
    bulk = cd.carregar_ceap_bulk(ANO) or {}
    atuais = json.load(open(DADOS / "deputados_federais_ms.json", encoding="utf-8"))["deputados"]
    saida = {}
    for d in atuais:
        m = mensal_vazio()
        for n in (bulk.get(d["id"]) or {}).get("despesas", []):
            if n.get("mes"):
                m[n["mes"] - 1] += n["valor"] or 0
        saida[str(d["id"])] = {"nome": d["nome"], "mensal": [round(x, 2) for x in m]}
    return saida


def senadores_ms():
    notas = cd.carregar_notas_ceaps_senado(ANO) or {}
    atuais = json.load(open(DADOS / "senadores_ms.json", encoding="utf-8"))["senadores"]
    saida = {}
    for s in atuais:
        m = mensal_vazio()
        for n in notas.get(s["id"], []):
            if n.get("mes"):
                m[int(n["mes"]) - 1] += n["valor"] or 0
        saida[str(s["id"])] = {"nome": s["nome"], "mensal": [round(x, 2) for x in m]}
    return saida


def estaduais():
    base = "https://transparencia2.al.ms.gov.br/ceap"
    h = {**cd.HEADERS, "Accept": "application/json"}
    linhas, pagina = [], 1
    while True:
        r = requests.get(f"{base}/data", params={"ano": ANO, "page": pagina, "perPage": 50}, headers=h, timeout=60)
        r.raise_for_status()
        pag = r.json()
        linhas.extend(pag.get("rows", []))
        if len(linhas) >= pag.get("total", len(linhas)) or not pag.get("rows"):
            break
        pagina += 1
    cd.log(f"  ALEMS {ANO}: {len(linhas)} deputados com gastos")
    saida = {}
    for i, linha in enumerate(linhas):
        nome = normaliza_nome(linha.get("deputado"))
        token = linha.get("detalheToken")
        if not token:
            continue
        m, pagina = mensal_vazio(), 1
        while True:
            r = requests.get(f"{base}/notas", params={"ano": ANO, "token": token, "page": pagina, "perPage": 50},
                             headers=h, timeout=60)
            r.raise_for_status()
            pag = r.json()
            for n in pag.get("rows", []):
                try:
                    mes = int(str(n.get("mes") or "").strip()[:2])
                except ValueError:
                    data = cd._alems_parse_data(n.get("emissao", ""))
                    mes = int(data[5:7]) if re.match(r"\d{4}-\d{2}", data or "") else None
                if mes and 1 <= mes <= 12:
                    m[mes - 1] += cd._alems_parse_valor(n.get("valor"))
            if not pag.get("hasMore"):
                break
            pagina += 1
            time.sleep(0.2)
        saida[nome] = {"nome": nome, "mensal": [round(x, 2) for x in m]}
        cd.log(f"  [{i + 1}/{len(linhas)}] {nome}: R$ {sum(m):,.2f}")
    return saida


if __name__ == "__main__":
    cd.log(f"Gerando histórico de {ANO}...")
    dados = {"ano": ANO, "geradoEm": cd.hoje,
             "fontes": {"federais": f"camara.leg.br/cotas/Ano-{ANO}.csv.zip",
                        "senadores": f"adm.senado.gov.br/adm-dadosabertos/api/v1/senadores/despesas_ceaps/{ANO}",
                        "estaduais": f"transparencia2.al.ms.gov.br/ceap (ano={ANO})"}}
    for chave, func in (("federaisMS", federais_ms), ("senadoresMS", senadores_ms), ("estaduais", estaduais)):
        try:
            dados[chave] = func()
            cd.log(f"✅ {chave}: {len(dados[chave])} parlamentares, R$ "
                   f"{sum(sum(x['mensal']) for x in dados[chave].values()):,.2f}")
        except Exception as e:
            cd.log(f"⚠️ {chave}: {e}")
    with open(DADOS / f"historico_{ANO}.json", "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, separators=(",", ":"))
    cd.log(f"✅ historico_{ANO}.json salvo")
