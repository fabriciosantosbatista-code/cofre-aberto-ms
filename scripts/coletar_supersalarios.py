#!/usr/bin/env python3
"""
Cofre Aberto MS — Supersalários: as maiores remunerações e os "penduricalhos" de MS

Fontes:
  Judiciário (TJMS, TRT24, TRE-MS)  DadosJusBr (api.dadosjusbr.org), projeto da
      Transparência Brasil que coleta os contracheques enviados pelos tribunais ao
      CNJ e classifica cada rubrica em remuneração base (R/B), outras remunerações
      e benefícios (R/O) e descontos (D). Pacote de dados do mês mais recente
      (um contracheque por magistrado, com cada item) + resumos mensais desde
      janeiro do ano anterior.
  Governo do Estado de MS  folha de pagamento do Portal da Transparência do
      Estado (gw.sgi.ms.gov.br), todos os vínculos, ativos e inativos.

Teto de referência: subsídio de ministro do STF (Lei 14.520/2023), R$ 46.366,19
desde fev/2025. Verbas indenizatórias ficam fora do teto por lei; "acima do teto"
aqui é só a comparação do bruto com esse valor, não uma afirmação de ilegalidade.

Gera dados/supersalarios.json.  Uso:  python3 scripts/coletar_supersalarios.py
"""

import csv, io, json, re, sys, time, zipfile
from datetime import date, datetime
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent))
from ano_ref import ano_referencia  # noqa: E402

ROOT = Path(__file__).parent.parent
SAIDA = ROOT / "dados" / "supersalarios.json"
ANO = ano_referencia()
HOJE = date.today()
TETO = 46366.19
TETO_FONTE = "Subsídio de ministro do STF — Lei nº 14.520/2023, em vigor desde fev/2025"
UA = {"User-Agent": "Mozilla/5.0 (CofreAbertoMS; +https://cofreabertoms.com.br)"}
DJ = "https://api.dadosjusbr.org/v2/dados"
TRIBUNAIS = {"tjms": "TJMS — Tribunal de Justiça", "trt24": "TRT24 — Justiça do Trabalho",
             "trems": "TRE-MS — Justiça Eleitoral"}
RANKING = 600  # pessoas no ranking nominal (todas as fontes)


def num(t):
    try:
        return float(str(t).replace(",", "."))
    except ValueError:
        return 0.0


def meses_para_tras(n):
    a, m = HOJE.year, HOJE.month
    for _ in range(n):
        yield a, m
        m -= 1
        if m == 0:
            a, m = a - 1, 12


def dj_mes(orgao, a, m):
    r = requests.get(f"{DJ}/{orgao}/{a}/{m}", headers=UA, timeout=60)
    if r.status_code != 200:
        return None
    d = r.json()
    return d if d.get("sumarios") and (d.get("pacote_de_dados") or {}).get("url") else None


# ── Judiciário (DadosJusBr) ──────────────────────────────────────────
def tribunal(orgao, rotulo):
    ultimo = None
    for a, m in meses_para_tras(8):
        ultimo = dj_mes(orgao, a, m)
        if ultimo:
            break
    if not ultimo:
        raise RuntimeError("nenhum mês com dados nos últimos 8")
    a, m = ultimo["ano"], ultimo["mes"]
    z = zipfile.ZipFile(io.BytesIO(requests.get(ultimo["pacote_de_dados"]["url"], headers=UA, timeout=120).content))
    ler = lambda n: list(csv.DictReader(io.TextIOWrapper(z.open(n), encoding="utf-8"), delimiter=";"))
    pessoas = {}
    for c in ler("contracheque.csv"):
        base, outras = num(c["salario"]), num(c["beneficios"])
        pessoas[c["id_contracheque"]] = {
            "nome": c["nome"].strip().title(), "cargo": c["funcao"].strip().capitalize(), "lotacao": c["local_trabalho"].strip().title(),
            "orgao": rotulo, "orgaoId": orgao, "poder": "Judiciário", "situacao": "Ativo",
            "mes": f"{m:02d}/{a}", "base": round(base, 2), "outras": round(outras, 2), "bruto": round(base + outras, 2),
            "descontos": round(abs(num(c["descontos"])), 2), "liquido": round(num(c["remuneracao"]), 2), "itens": {}}
    tipos = {}
    for r in ler("remuneracao.csv"):
        if r["tipo"] != "R/O" or not num(r["valor"]):
            continue
        p = pessoas.get(r["id_contracheque"])
        item = re.sub(r"\s+", " ", r["item"]).strip()
        v = num(r["valor"])
        if p:
            p["itens"][item] = round(p["itens"].get(item, 0) + v, 2)
        t = tipos.setdefault(item, {"item": item, "categoria": r["categoria"], "valor": 0.0, "pessoas": 0})
        t["valor"] += v
        t["pessoas"] += 1
    for p in pessoas.values():
        p["itens"] = sorted(({"item": k, "valor": v} for k, v in p["itens"].items()), key=lambda x: -x["valor"])
    # resumos mensais (evolução): base x outras, desde janeiro do ano anterior
    serie = []
    for aa in (ANO - 1, ANO):
        for mm in range(1, 13):
            if (aa, mm) > (HOJE.year, HOJE.month):
                break
            try:
                d = dj_mes(orgao, aa, mm)
            except Exception:
                d = None
            if not d:
                continue
            s = d["sumarios"].get("membros_ativos") or {}
            serie.append({"mes": f"{mm:02d}/{aa}", "pessoas": s.get("quantidade"),
                          "base": round((s.get("remuneracao_base") or {}).get("total") or 0, 2),
                          "outras": round((s.get("outras_remuneracoes") or {}).get("total") or 0, 2)})
            time.sleep(0.2)
    print(f"  {rotulo}: {len(pessoas)} contracheques de {m:02d}/{a}, {len(serie)} meses de histórico")
    return list(pessoas.values()), sorted(tipos.values(), key=lambda t: -t["valor"]), serie, f"{m:02d}/{a}"


# ── Governo do Estado (folha do Portal da Transparência) ─────────────
def governo():
    folha = "https://gw.sgi.ms.gov.br/d0125/transpfolhadepagamento/v1"
    tok = lambda: requests.get("https://www.transparencia.ms.gov.br/Auth/Token", headers=UA, timeout=30).text.strip().strip('"')
    ex = requests.get(folha + "/exercicios", headers={**UA, "Authorization": "Bearer " + tok()}, timeout=60).json()["data"]
    nomes = ["janeiro", "fevereiro", "marco", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"]
    flags = next((e for e in ex if e["anoCompetencia"] == ANO), None) or {}
    mes = max((i + 1 for i, n in enumerate(nomes) if flags.get(n)), default=None)
    if not mes:
        raise RuntimeError("folha do ano ainda não publicada")
    linhas, pagina = [], 1
    while True:
        for t in range(3):
            try:
                r = requests.get(folha + "/servidores", timeout=600, headers={**UA, "Authorization": "Bearer " + tok()},
                                 params={"anoexercicio": ANO, "mescompetencia": mes, "tipoFolha": 1, "pageno": pagina,
                                         "pagesize": 20000, "exportarcsv": "false"})
                j = r.json()
                if (j.get("status") or {}).get("code") == 200:
                    break
            except Exception as e:
                j = {"erro": str(e)}
            time.sleep(10 * (t + 1))
        else:
            raise RuntimeError(f"página {pagina} da folha: {j}")
        lote = j.get("data") or []
        linhas += lote
        if len(lote) < 20000:
            break
        pagina += 1
    pessoas = []
    for x in linhas:
        fixa, ev = x.get("remuneracaoFixa") or 0, x.get("remuneracoesEventuais") or 0
        pessoas.append({"nome": re.sub(r"\s+", " ", x.get("nome") or "").strip().title(), "cargo": (x.get("cargo") or "").strip().capitalize(),
                        "lotacao": (x.get("vinculo") or "").strip().capitalize(), "orgao": f"Governo MS — {(x.get('orgao') or '').strip()}",
                        "orgaoId": "governo", "orgaoSigla": (x.get("orgao") or "").strip(), "poder": "Executivo estadual",
                        "situacao": (x.get("situacao") or "").strip().capitalize(), "mes": f"{mes:02d}/{ANO}",
                        "base": round(fixa, 2), "outras": round(ev, 2), "bruto": round(fixa + ev, 2),
                        "descontos": round(max(0, fixa + ev - (x.get("remuneracaoAposDeducoes") or 0)), 2),
                        "liquido": round(x.get("remuneracaoAposDeducoes") or 0, 2), "itens": []})
    print(f"  Governo do Estado: {len(pessoas)} registros na folha de {mes:02d}/{ANO}")
    return pessoas, f"{mes:02d}/{ANO}"


def resumo_orgao(nome, lst, mes, fonte):
    br = [p["bruto"] for p in lst]
    acima = [p for p in lst if p["bruto"] > TETO]
    return {"orgao": nome, "mes": mes, "fonte": fonte, "pessoas": len(lst),
            "mediaBruta": round(sum(br) / len(br), 2) if br else 0, "maiorBruto": round(max(br), 2) if br else 0,
            "acimaTeto": len(acima), "valorAcimaTeto": round(sum(p["bruto"] - TETO for p in acima), 2),
            "liquidoAcimaTeto": sum(1 for p in lst if p["liquido"] > TETO),
            "maiorLiquido": round(max((p["liquido"] for p in lst), default=0), 2),
            "mediaLiquida": round(sum(p["liquido"] for p in lst) / len(lst), 2) if lst else 0,
            "totalBase": round(sum(p["base"] for p in lst), 2), "totalOutras": round(sum(p["outras"] for p in lst), 2)}


def main():
    print(f"💰 Supersalários — MS {ANO} (teto R$ {TETO:,.2f})")
    try:
        anterior = json.load(open(SAIDA, encoding="utf-8"))
    except Exception:
        anterior = {}
    todos, orgaos, penduricalhos, evolucao, falhas, avisos = [], [], {}, {}, [], []
    for oid, rot in TRIBUNAIS.items():
        try:
            pessoas, tipos, serie, mes = tribunal(oid, rot)
            if not any(p["bruto"] > 0 for p in pessoas):
                # ex.: TRE-MS — juízes eleitorais só recebem uma gratificação e o pacote do mês veio zerado
                avisos.append(f"{rot}: o DadosJusBr publicou {mes} com valores zerados; o órgão fica fora do ranking")
                print(f"  ⚠️ {rot}: valores zerados em {mes} — fora do ranking")
                continue
            todos += pessoas
            orgaos.append(resumo_orgao(rot, pessoas, mes, "DadosJusBr / Transparência Brasil (contracheques enviados ao CNJ)"))
            penduricalhos[oid] = {"orgao": rot, "mes": mes, "itens": [{**t, "valor": round(t["valor"], 2)} for t in tipos]}
            evolucao[oid] = {"orgao": rot, "meses": serie}
        except Exception as e:
            falhas.append(f"{rot}: {e}")
            print(f"  ⚠️ {rot}: {e}")
            for o in anterior.get("orgaos", []):
                if o["orgao"] == rot:
                    orgaos.append(o)
            todos += [p for p in anterior.get("ranking", []) if p.get("orgaoId") == oid]
            if oid in (anterior.get("penduricalhos") or {}):
                penduricalhos[oid] = anterior["penduricalhos"][oid]
                evolucao[oid] = anterior["evolucao"][oid]
    try:
        gov, mes_gov = governo()
        todos += gov
        ativos = [p for p in gov if p["situacao"].lower().startswith("ativo")]
        inativos = [p for p in gov if not p["situacao"].lower().startswith("ativo")]
        fonte = "Portal da Transparência do Estado de MS (folha de pagamento)"
        orgaos.append(resumo_orgao("Governo do Estado — ativos", ativos, mes_gov, fonte))
        orgaos.append(resumo_orgao("Governo do Estado — aposentados e pensionistas", inativos, mes_gov, fonte))
        # dentro do Executivo: por órgão (secretaria, polícia, PGE...), só os que têm alguém acima do teto
        por = {}
        for p in gov:
            por.setdefault(p["orgaoSigla"], []).append(p)
        orgaos_gov = sorted((resumo_orgao(f"Governo MS — {k}", v, mes_gov, fonte) for k, v in por.items()),
                            key=lambda o: (-o["acimaTeto"], -o["mediaBruta"]))
    except Exception as e:
        falhas.append(f"Governo do Estado: {e}")
        print(f"  ⚠️ Governo do Estado: {e}")
        todos += [p for p in anterior.get("ranking", []) if p.get("orgaoId") == "governo"]
        orgaos += [o for o in anterior.get("orgaos", []) if o["orgao"].startswith("Governo do Estado")]
        orgaos_gov = anterior.get("orgaosGoverno", [])
    if not todos:
        print("❌ nada coletado — arquivo anterior mantido")
        sys.exit(1)

    todos.sort(key=lambda p: -p["bruto"])
    ranking = todos[:RANKING]
    for p in ranking:
        p["acimaTeto"] = round(max(0, p["bruto"] - TETO), 2)
    acima = [p for p in todos if p["bruto"] > TETO]
    out = {"ano": ANO, "ultimaAtualizacao": datetime.now().isoformat(timespec="seconds"),
           "teto": TETO, "tetoFonte": TETO_FONTE,
           "fontes": {"judiciario": "https://dadosjusbr.org/", "governo": "https://www.transparencia.ms.gov.br/"},
           "totalPessoas": len(todos), "acimaTeto": len(acima), "valorAcimaTeto": round(sum(p["bruto"] - TETO for p in acima), 2),
           "liquidoAcimaTeto": sum(1 for p in todos if p["liquido"] > TETO), "avisos": avisos,
           "orgaos": orgaos, "orgaosGoverno": [o for o in orgaos_gov if o["acimaTeto"] > 0][:40],
           "penduricalhos": penduricalhos, "evolucao": evolucao, "ranking": ranking, "falhas": falhas}
    SAIDA.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"  {len(todos):,} pessoas · {len(acima):,} com bruto acima do teto (R$ {out['valorAcimaTeto']:,.2f} acima no mês)")
    print(f"✅ {SAIDA.relative_to(ROOT)} ({SAIDA.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
