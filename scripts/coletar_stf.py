#!/usr/bin/env python3
"""
Cofre Aberto MS — Supremo Tribunal Federal

  remuneracao  contracheque de cada ministro, mês a mês desde jan/2025:
               subsídio, outras verbas (férias, 13º, auxílios, indenizações,
               exercícios anteriores), descontos e líquido, item por item.
               Fonte: DadosJusBr (Transparência Brasil), que coleta os dados
               publicados pelo próprio STF.
  pessoal      despesa com pessoal do STF (ativos, inativos e pensionistas)
               a cada quadrimestre, do Relatório de Gestão Fiscal (LRF), e a
               mesma conta para os outros tribunais superiores (STJ, TST, TSE,
               STM). Fonte: Tesouro Nacional — SICONFI (API pública).

O portal de transparência do STF (diárias, passagens, contratos) recusa
acessos de fora do Brasil, então esses itens não entram.

Cache por mês/quadrimestre em dados/stf_cache.json; gera dados/stf.json.
"""

import csv, io, json, re, sys, time, zipfile
from datetime import date, datetime
from pathlib import Path

import requests

DADOS = Path(__file__).parent.parent / "dados"
CACHE = DADOS / "stf_cache.json"
SAIDA = DADOS / "stf.json"
DJ = "https://api.dadosjusbr.org/v2/dados"
RGF = "https://apidatalake.tesouro.gov.br/ords/siconfi/tt/rgf"
UA = {"User-Agent": "Mozilla/5.0 (CofreAbertoMS; +https://cofreabertoms.com.br)"}
HOJE = date.today()
SUPERIORES = ["Supremo Tribunal Federal", "Superior Tribunal de Justiça", "Tribunal Superior do Trabalho",
              "Tribunal Superior Eleitoral", "Superior Tribunal Militar"]
CONTAS = {"DespesaComPessoalBruta": "bruta", "DespesaComPessoalAtivoBruta": "ativos",
          "DespesaComPessoalInativoEPensionistasBruta": "inativos", "DespesaComPessoalTotal": "dtp"}


def num(t):
    try:
        return float(str(t).replace(".", "").replace(",", "."))
    except ValueError:
        return 0.0


def get(url, params=None, tent=4, timeout=90):
    for t in range(tent):
        try:
            r = requests.get(url, params=params, headers=UA, timeout=timeout)
            if r.status_code == 200:
                return r
        except requests.RequestException:
            pass
        time.sleep(3 * (t + 1))
    return None


def mes_stf(a, m):
    r = get(f"{DJ}/stf/{a}/{m}")
    if not r:
        return None
    d = r.json()
    url = (d.get("pacote_de_dados") or {}).get("url")
    if not url:
        return None
    z = zipfile.ZipFile(io.BytesIO(get(url, timeout=180).content))
    ler = lambda n: list(csv.DictReader(io.TextIOWrapper(z.open(n), encoding="utf-8"), delimiter=";"))
    pessoas = {}
    for c in ler("contracheque.csv"):
        if "MINISTR" not in (c.get("funcao") or "").upper():
            continue
        pessoas[c["id_contracheque"]] = {"nome": c["nome"].strip().title(), "base": round(num(c["salario"]), 2),
                                         "outras": round(num(c["beneficios"]), 2), "descontos": round(abs(num(c["descontos"])), 2),
                                         "liquido": round(num(c["remuneracao"]), 2), "itens": {}}
    for r_ in ler("remuneracao.csv"):
        p = pessoas.get(r_["id_contracheque"])
        v = num(r_["valor"])
        if p and v:
            k = f"{r_['tipo']}|{re.sub(r'\\s+', ' ', r_['item']).strip()}"
            p["itens"][k] = round(p["itens"].get(k, 0) + v, 2)
    return {"mes": f"{a}-{m:02d}", "ministros": list(pessoas.values())}


def remuneracao(cache):
    rc = cache.setdefault("remuneracao", {})
    for a in (2025, HOJE.year) if HOJE.year > 2025 else (2025,):
        for m in range(1, 13):
            k = f"{a}-{m:02d}"
            if (a, m) > (HOJE.year, HOJE.month):
                break
            if k in rc and (a, m) < (HOJE.year, HOJE.month - 3):
                continue
            try:
                d = mes_stf(a, m)
            except Exception as e:
                print(f"  ⚠️ STF {k}: {e}")
                d = None
            if d and d["ministros"]:
                rc[k] = d
                print(f"  STF {k}: {len(d['ministros'])} ministros")
            time.sleep(0.3)
    meses = sorted(rc)
    por = {}
    for k in meses:
        for p in rc[k]["ministros"]:
            x = por.setdefault(p["nome"], {"nome": p["nome"], "meses": 0, "base": 0.0, "outras": 0.0, "descontos": 0.0, "liquido": 0.0,
                                           "maiorBruto": 0.0, "maiorMes": None, "itens": {}, "serie": []})
            x["meses"] += 1
            for c in ("base", "outras", "descontos", "liquido"):
                x[c] += p[c]
            bruto = p["base"] + p["outras"]
            if bruto > x["maiorBruto"]:
                x["maiorBruto"], x["maiorMes"] = round(bruto, 2), k
            for it, v in p["itens"].items():
                if not it.startswith("D|"):
                    x["itens"][it.split("|", 1)[1]] = x["itens"].get(it.split("|", 1)[1], 0) + v
            x["serie"].append({"mes": k, "bruto": round(bruto, 2), "liquido": p["liquido"]})
    lst = []
    for x in por.values():
        for c in ("base", "outras", "descontos", "liquido"):
            x[c] = round(x[c], 2)
        x["itens"] = [{"item": k, "valor": round(v, 2)} for k, v in sorted(x["itens"].items(), key=lambda kv: -kv[1])]
        lst.append(x)
    ult = meses[-1] if meses else None
    return {"de": meses[0] if meses else None, "ate": ult,
            "ultimoMes": {"mes": ult, "ministros": sorted(rc[ult]["ministros"], key=lambda p: -(p["base"] + p["outras"]))} if ult else None,
            "ministros": sorted(lst, key=lambda x: -(x["base"] + x["outras"]))}


def pessoal(cache):
    pc = cache.setdefault("pessoal", {})
    for a in range(2023, HOJE.year + 1):
        for q in (1, 2, 3):
            k = f"{a}-Q{q}"
            if k in pc or (a, q * 4) >= (HOJE.year, HOJE.month):  # quadrimestre ainda não fechado/publicado
                continue
            rows, off = [], 0
            while True:
                r = get(RGF, {"an_exercicio": a, "in_periodicidade": "Q", "nr_periodo": q, "co_tipo_demonstrativo": "RGF",
                              "no_anexo": "RGF-Anexo 01", "co_esfera": "U", "co_poder": "J", "id_ente": 1, "offset": off})
                if not r:
                    break
                j = r.json()
                rows += j.get("items") or []
                if not j.get("hasMore"):
                    break
                off += len(j.get("items") or [])
            if not rows:
                continue
            out = {}
            for x in rows:
                if x["instituicao"] not in SUPERIORES or x["cod_conta"] not in CONTAS:
                    continue
                col = x["coluna"].upper()
                d = out.setdefault(x["instituicao"], {})
                if col.startswith("TOTAL (ÚLTIMOS 12 MESES)") or (x["cod_conta"] == "DespesaComPessoalTotal" and col == "VALOR"):
                    d[CONTAS[x["cod_conta"]]] = round(x["valor"], 2)
                elif x["cod_conta"] == "DespesaComPessoalTotal" and "%" in col:
                    d["pctRCL"] = x["valor"]
            if out:
                pc[k] = out
                print(f"  RGF {k}: {len(out)} tribunais superiores")
    serie = [{"periodo": k, "ano": int(k[:4]), "quadrimestre": int(k[-1]), **v.get("Supremo Tribunal Federal", {})}
             for k, v in sorted(pc.items()) if "Supremo Tribunal Federal" in v]
    ult = max(pc) if pc else None
    return {"serie": serie, "ultimo": ult,
            "comparacao": [{"tribunal": t, **pc[ult].get(t, {})} for t in SUPERIORES if ult and t in pc[ult]]}


def main():
    try:
        cache = json.load(open(CACHE, encoding="utf-8"))
    except Exception:
        cache = {}
    try:
        anterior = json.load(open(SAIDA, encoding="utf-8"))
    except Exception:
        anterior = {}
    out = {"ultimaAtualizacao": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"), "subsidio": 46366.19,
           "fontes": {"remuneracao": "DadosJusBr (Transparência Brasil) — contracheques publicados pelo STF",
                      "pessoal": "Tesouro Nacional — SICONFI, Relatório de Gestão Fiscal (Anexo 1, despesa com pessoal)"}}
    for nome, f in (("remuneracao", remuneracao), ("pessoal", pessoal)):
        try:
            out[nome] = f(cache)
        except Exception as e:
            print(f"  ⚠️ {nome}: {e} — mantido o anterior")
            out[nome] = anterior.get(nome)
        CACHE.write_text(json.dumps(cache, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    if not (out.get("remuneracao") or {}).get("ministros"):
        print("❌ sem contracheques do STF — arquivo mantido")
        sys.exit(1)
    SAIDA.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"✅ stf.json — {len(out['remuneracao']['ministros'])} ministros, {len((out.get('pessoal') or {}).get('serie') or [])} quadrimestres de despesa com pessoal")


if __name__ == "__main__":
    main()
