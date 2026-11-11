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
  Tribunal de Contas (TCE-MS)  API do Portal da Transparência do TCE
      (servidores: remuneração + outros pagamentos) e exportação em PDF da
      página "Membros" (conselheiros e procuradores de contas, com cada rubrica).
  Comparação  resumo do mês mais recente de todos os Tribunais de Justiça do
      país no DadosJusBr (média por magistrado).

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
    siglas = {}
    try:
        for o in requests.get(folha + "/orgaos", params={"anoexercicio": ANO}, timeout=60,
                              headers={**UA, "Authorization": "Bearer " + tok()}).json().get("data") or []:
            nome = re.sub(r"\s*\([^)]*\)\s*$", "", (o.get("descricao") or "")).strip()
            if o.get("id") and nome:
                siglas.setdefault(o["id"].strip(), nome)
    except Exception as e:
        print(f"  ⚠️ nomes dos órgãos: {e}")
    print(f"  Governo do Estado: {len(pessoas)} registros na folha de {mes:02d}/{ANO}")
    return pessoas, f"{mes:02d}/{ANO}", siglas


# ── Tribunal de Contas (TCE-MS) ───────────────────────────────────────
TCE = "https://sip-barramento.tce.ms.gov.br/barramento/api/Transparencia/GestaoPessoas"


def tce_lista(ep, a, m):
    out, p = [], 0
    while True:
        j = requests.get(f"{TCE}/{ep}", params={"ano": a, "mes": m, "pageNumber": p, "pageSize": 200}, headers=UA, timeout=120).json()
        out += j.get("items") or []
        p += 1
        if p >= (j.get("totalPages") or 0):
            return out


def tce_membros(a, m):
    """Conselheiros, conselheiros substitutos e procuradores de contas: a página "Membros"
    do portal só publica o contracheque detalhado (Tabela de Remuneração Unificada, TRU)
    na exportação em PDF — uma coluna por rubrica, inclusive o abate-teto."""
    import pypdf
    r = requests.get(f"{TCE}/Servidores/Exportar", params={"ano": a, "mes": m, "tipo": 2, "vinculo": 2, "tipoConteudo": 1},
                     headers=UA, timeout=120)
    r.raise_for_status()
    txt = "\n".join(p.extract_text() or "" for p in pypdf.PdfReader(io.BytesIO(r.content)).pages)
    fim = txt.find("Margem consign")
    cab = txt[:fim]
    codigos = re.findall(r"TRU-(\d{4}) - ", cab)
    nomes = [re.sub(r"\s+", " ", x).strip() for x in re.split(r"TRU-\d{4} - ", cab)[1:]]
    nomes[-1] = nomes[-1].split("Margem")[0].strip()
    rubrica = dict(zip(codigos, nomes))
    n = len(codigos) + 5
    corpo = txt[fim:]
    corpo = corpo[corpo.find("(teto)") + 6:]
    num = r"-?\d+(?:,\d+)?"
    pat = re.compile(r"(Ativo|Inativo|Aposentado|Licenciado|Afastado)\s+(\d{2}/\d{4})\s+((?:" + num + r"\s+){" + str(n - 1) + r"}" + num + r")")
    pos, pessoas = 0, []
    for mt in pat.finditer(corpo):
        antes = re.sub(r"\s+", " ", corpo[pos:mt.start()]).strip()
        pos = mt.end()
        cab_p = re.match(r"(\d+) (.+?) (\d{1,2} de \w{3}\.? de \d{4}) \d{2}:\d{2} (.+)$", antes)
        if not cab_p:
            continue
        vals = dict(zip(codigos, (float(v.replace(",", ".")) for v in mt.group(3).split())))
        cargo_lot = cab_p.group(4)
        cargo = next((c for c in ("Conselheiro do Tribunal de Contas MS", "Conselheiro Substituto", "Procurador-Geral do Ministério Público de Contas",
                                  "Procurador do Ministério Público de Contas") if cargo_lot.startswith(c)), cargo_lot[:40])
        ganhos = {c: v for c, v in vals.items() if c[0] in "12348" and v}
        base = vals.get("1001", 0)
        bruto = sum(ganhos.values())
        desc = sum(v for c, v in vals.items() if c[0] == "9")
        pessoas.append({"nome": cab_p.group(2).title(), "cargo": cargo, "lotacao": cargo_lot[len(cargo):].strip().title(),
                        "orgao": "TCE-MS — Tribunal de Contas (membros)", "orgaoId": "tce", "poder": "Controle externo",
                        "situacao": mt.group(1), "mes": mt.group(2), "base": round(base, 2), "outras": round(bruto - base, 2),
                        "bruto": round(bruto, 2), "descontos": round(desc, 2), "liquido": round(bruto - desc, 2),
                        "abateTeto": round(vals.get("9001", 0), 2),
                        "itens": sorted(({"item": rubrica[c], "valor": round(v, 2)} for c, v in ganhos.items() if c != "1001"),
                                        key=lambda x: -x["valor"])})
    return pessoas


def tce():
    for a, m in meses_para_tras(5):
        rem = tce_lista("Remuneracao", a, m)
        if rem:
            break
    else:
        raise RuntimeError("nenhuma folha nos últimos 5 meses")
    outros = {x["matricula"]: x for x in tce_lista("OutroPagamento", a, m)}
    pessoas = []
    for x in rem:
        o = outros.get(x["matricula"], {})
        base, ev = x.get("totalVencimentosRemuneracao") or 0, o.get("totalVencimentoOutrosPagamentos") or 0
        pessoas.append({"nome": re.sub(r"\s+", " ", x["nome"]).strip().title(), "cargo": re.sub(r"\s+", " ", x.get("cargoDescr") or "").strip(),
                        "lotacao": (x.get("lotacaoDescr") or "").strip().title(), "orgao": "TCE-MS — Tribunal de Contas (servidores)",
                        "orgaoId": "tce", "poder": "Controle externo", "situacao": (x.get("vinculo") or "").capitalize(),
                        "mes": f"{m:02d}/{a}", "base": round(base, 2), "outras": round(ev, 2), "bruto": round(base + ev, 2),
                        "descontos": round((x.get("totalDescontoRemuneracao") or 0) + (o.get("totalDescontoOutrosPagamentos") or 0), 2),
                        "liquido": round((x.get("totalCalculadoRemuneracao") or 0) + (o.get("totalCalculadoOutrosPagamentos") or 0), 2), "itens": []})
    try:
        membros = tce_membros(a, m)
    except Exception as e:
        print(f"  ⚠️ TCE-MS membros: {e}")
        membros = []
    print(f"  TCE-MS: {len(pessoas)} servidores e {len(membros)} membros em {m:02d}/{a}")
    return pessoas, membros, f"{m:02d}/{a}"


# ── Comparação com os Tribunais de Justiça dos outros estados (DadosJusBr) ──
def comparacao_tjs():
    orgs = requests.get("https://api.dadosjusbr.org/v2/orgaos", headers=UA, timeout=60).json()
    tjs = [o for o in orgs if o.get("entidade") == "Tribunal" and o.get("jurisdicao") == "Estadual"]
    out = []
    for o in tjs:
        for a, m in meses_para_tras(6):
            try:
                d = dj_mes(o["id_orgao"], a, m)
            except Exception:
                d = None
            if d:
                s = d["sumarios"].get("membros_ativos") or {}
                q = s.get("quantidade") or 0
                base = (s.get("remuneracao_base") or {}).get("total") or 0
                outras = (s.get("outras_remuneracoes") or {}).get("total") or 0
                if q and base > 0:
                    out.append({"orgao": o["id_orgao"].upper(), "nome": o["nome"], "uf": o.get("uf"), "mes": f"{m:02d}/{a}",
                                "magistrados": q, "mediaBase": round(base / q, 2), "mediaOutras": round(outras / q, 2),
                                "mediaBruta": round((base + outras) / q, 2),
                                "mediaLiquida": round((s.get("remuneracoes") or {}).get("media") or 0, 2)})
                break
            time.sleep(0.15)
    out.sort(key=lambda x: -x["mediaBruta"])
    for i, x in enumerate(out):
        x["posicao"] = i + 1
    print(f"  comparação: {len(out)} tribunais de justiça com dados")
    return out


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
        gov, mes_gov, siglas_gov = governo()
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
        orgaos_gov = []
        for k, v in por.items():
            o = resumo_orgao(f"Governo MS — {k}", v, mes_gov, fonte)
            o["sigla"] = k
            o["maiores"] = [{c: x[c] for c in ("nome", "cargo", "situacao", "base", "outras", "bruto", "liquido")}
                            for x in sorted(v, key=lambda x: -x["bruto"])[:15]]
            orgaos_gov.append(o)
        orgaos_gov.sort(key=lambda o: (-o["acimaTeto"], -o["mediaBruta"]))
    except Exception as e:
        falhas.append(f"Governo do Estado: {e}")
        print(f"  ⚠️ Governo do Estado: {e}")
        todos += [p for p in anterior.get("ranking", []) if p.get("orgaoId") == "governo"]
        orgaos += [o for o in anterior.get("orgaos", []) if o["orgao"].startswith("Governo do Estado")]
        orgaos_gov = anterior.get("orgaosGoverno", [])
        siglas_gov = anterior.get("siglasGoverno", {})
    try:
        serv_tce, membros_tce, mes_tce = tce()
        todos += serv_tce + membros_tce
        fonte = "Portal da Transparência do TCE-MS"
        if membros_tce:
            orgaos.append(resumo_orgao("TCE-MS — conselheiros e procuradores de contas", membros_tce, mes_tce, fonte + " (membros, contracheque detalhado)"))
            pend = {}
            for p in membros_tce:
                for i in p["itens"]:
                    t = pend.setdefault(i["item"], {"item": i["item"], "categoria": "rubrica da TRU", "valor": 0.0, "pessoas": 0})
                    t["valor"] += i["valor"]
                    t["pessoas"] += 1
            penduricalhos["tce"] = {"orgao": "TCE-MS — membros", "mes": mes_tce,
                                    "itens": sorted(({**t, "valor": round(t["valor"], 2)} for t in pend.values()), key=lambda t: -t["valor"])}
        orgaos.append(resumo_orgao("TCE-MS — servidores", serv_tce, mes_tce, fonte))
    except Exception as e:
        falhas.append(f"TCE-MS: {e}")
        print(f"  ⚠️ TCE-MS: {e}")
        todos += [p for p in anterior.get("ranking", []) if p.get("orgaoId") == "tce"]
        orgaos += [o for o in anterior.get("orgaos", []) if o["orgao"].startswith("TCE-MS")]
        if "tce" in (anterior.get("penduricalhos") or {}):
            penduricalhos["tce"] = anterior["penduricalhos"]["tce"]
    try:
        cg = json.load(open(ROOT / "dados" / "camara_municipal.json", encoding="utf-8")).get("maioresSalarios") or {}
        lista_cg = [{**x, "orgao": "Câmara Municipal de Campo Grande", "orgaoId": "camara-cg", "poder": "Legislativo municipal",
                     "situacao": "Ativo", "mes": cg["referencia"], "base": x["bruto"], "outras": 0.0, "itens": []}
                    for x in cg.get("lista", []) if x.get("bruto")]
        if lista_cg:
            todos += lista_cg
            o = resumo_orgao("Câmara Municipal de Campo Grande (60 maiores)", lista_cg, cg["referencia"],
                             "Portal da Transparência da Câmara (folha Fiorilli)")
            o["totalServidores"] = cg.get("servidores")
            orgaos.append(o)
    except Exception as e:
        print(f"  ⚠️ Câmara CG: {e}")
    try:
        comp = comparacao_tjs()
    except Exception as e:
        print(f"  ⚠️ comparação com outros TJs: {e}")
        comp = anterior.get("comparacaoTJs", [])
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
           "fontes": {"judiciario": "https://dadosjusbr.org/", "governo": "https://www.transparencia.ms.gov.br/",
                      "tce": "https://transparencia.tce.ms.gov.br/"},
           "totalPessoas": len(todos), "acimaTeto": len(acima), "valorAcimaTeto": round(sum(p["bruto"] - TETO for p in acima), 2),
           "liquidoAcimaTeto": sum(1 for p in todos if p["liquido"] > TETO), "avisos": avisos,
           "orgaos": orgaos, "orgaosGoverno": orgaos_gov, "siglasGoverno": siglas_gov,
           "penduricalhos": penduricalhos, "evolucao": evolucao, "comparacaoTJs": comp, "ranking": ranking, "falhas": falhas}
    SAIDA.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"  {len(todos):,} pessoas · {len(acima):,} com bruto acima do teto (R$ {out['valorAcimaTeto']:,.2f} acima no mês)")
    print(f"✅ {SAIDA.relative_to(ROOT)} ({SAIDA.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
