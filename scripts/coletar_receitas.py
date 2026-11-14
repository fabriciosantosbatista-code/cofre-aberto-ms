#!/usr/bin/env python3
"""
Cofre Aberto MS — arrecadação do Governo de MS e da Prefeitura de Campo Grande (Arrecadômetro)

Fonte: Tesouro Nacional, Siconfi (apidatalake.tesouro.gov.br), RREO Anexo 3 — Receita Corrente Líquida. Cada
relatório bimestral traz os 12 últimos meses, item por item (ICMS, IPVA, ITCD, IPTU, ISS, ITBI, FPE, FPM...).
O Estado e a Prefeitura publicam o relatório até 30 dias depois do fim de cada bimestre.

O valor "ao vivo" do site é uma ESTIMATIVA: o último total oficial (até o último mês publicado) mais o ritmo
médio dos últimos 12 meses desde então. Os valores por mês são os oficiais.

Gera dados/receitas.json.
"""

import json, sys, time
from datetime import date, datetime
from pathlib import Path

import requests

DADOS = Path(__file__).parent.parent / "dados"
SAIDA = DADOS / "receitas.json"
API = "https://apidatalake.tesouro.gov.br/ords/siconfi/tt/rreo"
H = {"User-Agent": "Mozilla/5.0 (CofreAbertoMS; +https://cofreabertoms.com.br)"}
ANO = date.today().year

ENTES = {
    "estado": {"id": 50, "esfera": "E", "nome": "Governo do Estado de MS",
               "itens": {"impostos": "Impostos, Taxas e Contribuições de Melhoria", "icms": "ICMS", "ipva": "IPVA", "itcd": "ITCD",
                         "irrf": "IRRF", "fpe": "Cota-Parte do FPE", "correntes": "RECEITAS CORRENTES (I)",
                         "rcl": "RECEITA CORRENTE LÍQUIDA (III) = (I - II)"}},
    "cg": {"id": 5002704, "esfera": "M", "nome": "Prefeitura de Campo Grande",
           "itens": {"impostos": "Impostos, Taxas e Contribuições de Melhoria", "iptu": "IPTU", "iss": "ISS", "itbi": "ITBI",
                     "irrf": "IRRF", "fpm": "Cota-Parte do FPM", "icms": "Cota-Parte do ICMS", "ipva": "Cota-Parte do IPVA",
                     "correntes": "RECEITAS CORRENTES (I)", "rcl": "RECEITA CORRENTE LÍQUIDA (III) = (I - II)"}},
}


def rreo(ente, ano, periodo):
    for t in range(4):
        try:
            r = requests.get(API, params={"an_exercicio": ano, "nr_periodo": periodo, "co_tipo_demonstrativo": "RREO",
                                          "no_anexo": "RREO-Anexo 03", "co_esfera": ente["esfera"], "id_ente": ente["id"]},
                             headers=H, timeout=90)
            if r.status_code == 200:
                return r.json().get("items") or []
        except (requests.RequestException, ValueError):
            pass
        time.sleep(3 * (t + 1))
    return None


def meses_do_relatorio(itens, ente, ano, periodo):
    """{AAAA-MM: {chave: valor}} a partir das colunas <MR>, <MR-1> ... <MR-11> (MR = último mês do bimestre)."""
    fim = 2 * periodo
    out, previsao = {}, {}
    for chave, conta in ente["itens"].items():
        for x in itens:
            if x.get("conta") != conta or x.get("rotulo") not in (None, "Padrão"):
                continue
            col = x.get("coluna") or ""
            v = round(float(x.get("valor") or 0), 2)
            if col.startswith("PREVISÃO"):
                previsao[chave] = v
            elif col.startswith("<MR"):
                k = int(col[4:-1] or 0) if col != "<MR>" else 0
                m = fim - k
                a = ano
                while m <= 0:
                    m += 12
                    a -= 1
                out.setdefault(f"{a}-{m:02d}", {})[chave] = v
    return out, previsao


def coletar(ente):
    meses, previsao, ultimo = {}, {}, None
    # ano anterior completo (6º bimestre) e o relatório mais recente do ano atual
    for ano in (ANO - 1, ANO):
        for per in range(6, 0, -1):
            it = rreo(ente, ano, per)
            if it is None:
                raise RuntimeError(f"Siconfi sem resposta ({ente['nome']}, {ano}/{per})")
            if not it:
                continue
            m, p = meses_do_relatorio(it, ente, ano, per)
            meses.update(m)  # o relatório mais novo sobrescreve meses repetidos (valores revisados)
            if ano == ANO:
                previsao, ultimo = p, f"{ANO}-{2 * per:02d}"
            elif ultimo is None:
                ultimo = f"{ano}-{2 * per:02d}"
            break
    return {"nome": ente["nome"], "ultimoMes": ultimo, "previsaoAno": previsao,
            "meses": {k: meses[k] for k in sorted(meses) if k <= (ultimo or "")}}


def main():
    anterior = {}
    try:
        anterior = json.load(open(SAIDA, encoding="utf-8"))
    except Exception:
        pass
    out = {}
    for chave, ente in ENTES.items():
        try:
            out[chave] = coletar(ente)
            u = out[chave]["ultimoMes"]
            print(f"  {ente['nome']}: meses até {u}, impostos no último mês R$ {out[chave]['meses'].get(u, {}).get('impostos', 0):,.0f}")
        except Exception as e:
            print(f"  ⚠️ {ente['nome']}: {e} — mantido o anterior")
            if (anterior.get("entes") or {}).get(chave):
                out[chave] = anterior["entes"][chave]
    if not out:
        print("❌ sem dados de arrecadação — arquivo mantido")
        sys.exit(1)
    SAIDA.write_text(json.dumps({
        "ano": ANO, "ultimaAtualizacao": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "fonte": "Tesouro Nacional — Siconfi, Relatório Resumido da Execução Orçamentária (RREO), Anexo 3",
        "fonteUrl": "https://siconfi.tesouro.gov.br/",
        "entes": out}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"✅ receitas.json — {', '.join(f'{k} até {v['ultimoMes']}' for k, v in out.items())}")


if __name__ == "__main__":
    main()
