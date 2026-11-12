#!/usr/bin/env python3
"""
Cofre Aberto MS — Aditivos dos contratos da Prefeitura de Campo Grande

Lista os contratos de compras, serviços e obras com início desde 2021 que ainda
estão ativos (SIG-Transparência, /contratos/consulta), e lê a página de detalhe
de cada um (/contratos/detalhe/{registro}): valor original, valor total, órgão
gestor, processo, modalidade e a lista de aditivos com o valor de cada um.

O portal não diz o tipo do aditivo. Um aditivo do MESMO valor do contrato
original (±2%) é tratado como prorrogação de serviço contínuo (renovação por
mais um período, que a lei permite e que não conta no limite de acréscimo);
os demais, como acréscimo de valor — que a Lei 14.133/2021 (art. 125) limita a
25% do valor inicial (50% em reforma).

Guarda cache por contrato (reconsulta a cada 7 dias) em dados/prefeitura_aditivos.json.
Uso: python3 scripts/coletar_aditivos_cg.py [limite_de_paginas]
"""

import html, json, re, sys, time
from datetime import date, datetime, timedelta
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent))
from coletar_contratos_cg import BASE, consulta  # noqa: E402

DADOS = Path(__file__).parent.parent / "dados"
ARQ = DADOS / "prefeitura_aditivos.json"
UA = {"User-Agent": "Mozilla/5.0 (CofreAbertoMS; transparencia publica)"}
NAO_COMPRA = {"DIVIDA", "DEMANDA JUDICIAL", "CONVÊNIO", "CONVENIO", "TERMO DE COLABORAÇÃO", "TERMO DE FOMENTO"}
ATIVOS = {"ATIVO", "PARALISADO", "ENCERRADO PENDENTE", "VENCIDO"}


def num(t):
    try:
        return float(str(t).replace("R$", "").replace(".", "").replace(",", ".").strip())
    except ValueError:
        return None


def iso(br):
    m = re.match(r"(\d{2})/(\d{2})/(\d{4})", br or "")
    return f"{m[3]}-{m[2]}-{m[1]}" if m else None


def campo(t, nome, prox):
    m = re.search(re.escape(nome) + r"\s+(.*?)\s+(?:" + "|".join(re.escape(p) for p in prox) + r")", t)
    return m.group(1).strip() if m else None


def detalhe(reg):
    s = requests.get(f"{BASE}/contratos/detalhe/{reg}", headers=UA, timeout=60).text
    s = re.sub(r"<!--.*?-->", "", s, flags=re.S)  # o portal deixa um "dump" de depuração de outro contrato num comentário
    t = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s)))
    i = t.find("Registro Cadastral")
    if i < 0:
        return None
    t = t[i:]
    adit = []
    m = re.search(r"Aditivos Número do Aditivo Valor do Aditivo (.*?)(?:Documentos Relacionados|Voltar|$)", t)
    if m:
        adit = [num(v) for _, v in re.findall(r"(\d+) (R\$ [\d.,]+)", m.group(1))]
    return {"processo": campo(t, "Processo", ["Licitação"]), "orgao": campo(t, "Órgão Gestor", ["Objeto"]),
            "modalidade": campo(t, "Modalidade da Licitação", ["Tipo da Contratação"]),
            "valorContrato": num(campo(t, "Valor do Contrato", ["Valor Total"])),
            "valorTotal": num(campo(t, "Valor Total", ["Valor Empenhado"])),
            "pago": num(campo(t, "Valor Pago", ["Quantidade de Aditivos", "Valor a Executar"])),
            "aditivos": [a for a in adit if a is not None], "consultadoEm": date.today().isoformat()}


def main():
    limite = int(sys.argv[1]) if len(sys.argv) > 1 else 5000
    try:
        cache = json.load(open(ARQ, encoding="utf-8")).get("contratos", {})
    except Exception:
        cache = {}
    hoje = date.today()
    brutos = consulta("/contratos/consulta", {"orderColumn": "contratos.data_inicio", "orderDirection": "DESC",
                                              "periodo-inicio": f"{hoje.year - 5}-01-01", "periodo-fim": hoje.isoformat()})
    alvo = [x for x in brutos if (x.get("descr_situacao") or "").strip() in ATIVOS and (x.get("descr_tipo") or "").strip().upper() not in NAO_COMPRA
            and (num(x.get("total_contrato")) or 0) >= 200000]
    pend = [x for x in alvo if str(x["registro_cadastral"]) not in cache or
            hoje - date.fromisoformat(cache[str(x["registro_cadastral"])].get("consultadoEm", "2000-01-01")) > timedelta(days=7)][:limite]
    print(f"🔎 aditivos: {len(brutos)} contratos desde {hoje.year - 5}, {len(alvo)} ativos de R$ 200 mil+, {len(pend)} para consultar")
    falhas = 0

    def um(x):
        for t in range(2):
            try:
                return x, detalhe(x["registro_cadastral"])
            except Exception:
                time.sleep(3)
        return x, None

    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(3) as ex:
        res = list(ex.map(um, pend))
    for i, (x, d) in enumerate(res):
        if d:
            d.update({"fornecedor": re.sub(r"\s+", " ", x.get("fornecedor") or "").strip(), "objeto": re.sub(r"\s+", " ", x.get("objeto") or "").strip()[:300],
                      "tipo": (x.get("descr_tipo") or "").strip(), "inicio": iso(x.get("data_inicio")), "fim": iso(x.get("data_fim")),
                      "situacao": (x.get("descr_situacao") or "").strip()})
            cache[str(x["registro_cadastral"])] = d
        else:
            falhas += 1
    validos = {str(x["registro_cadastral"]) for x in alvo}
    cache = {k: v for k, v in cache.items() if k in validos}
    ARQ.write_text(json.dumps({"ultimaAtualizacao": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
                               "fonte": "SIG-Transparência da Prefeitura de Campo Grande — detalhe de cada contrato",
                               "contratos": cache}, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"✅ prefeitura_aditivos.json — {len(cache)} contratos ({falhas} falhas); "
          f"{sum(1 for v in cache.values() if v.get('aditivos'))} com aditivos")


if __name__ == "__main__":
    main()
