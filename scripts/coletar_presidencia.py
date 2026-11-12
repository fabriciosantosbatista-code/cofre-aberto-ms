#!/usr/bin/env python3
"""
Cofre Aberto MS — Presidência da República e Governo Federal em MS

Tudo do Portal da Transparência do Governo Federal (CGU), arquivos de dados
abertos (download-de-dados, sem chave):

  cartao        cartão de pagamento (CPGF) da Presidência e da Vice-Presidência,
                mês a mês desde 2013 (primeiro ano publicado), com a parte sigilosa
                separada, agrupado por presidente
  viagens       viagens a serviço (diárias e passagens) da Presidência e dos
                ministros de Estado, no mandato atual
  orcamento     orçamento e despesa da Presidência da República no mandato atual
                (por ano, órgão e ação)
  remuneracao   presidente e vice (subsídio fixado em decreto legislativo) e
                ministros de Estado (folha SIAPE: bruto, abate-teto, jetons, líquido)
  ms            transferências da União para MS no ano: por tipo, ministério e município

Cache por mês/ano em dados/presidencia_cache.json; gera dados/presidencia.json.
Uso: python3 scripts/coletar_presidencia.py [--rapido]   (--rapido: não baixa viagens)
"""

import csv, io, json, re, sys, time, zipfile
from datetime import date, datetime
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent))
from coletar_tse import ArquivoRemoto  # noqa: E402  (zip remoto lido por Range)

DADOS = Path(__file__).parent.parent / "dados"
CACHE = DADOS / "presidencia_cache.json"
SAIDA = DADOS / "presidencia.json"
PORTAL = "https://portaldatransparencia.gov.br/download-de-dados/{}"
CDN = "https://dadosabertos-download.cgu.gov.br/PortalDaTransparencia/saida/{}"
UA = {"User-Agent": "Mozilla/5.0 (CofreAbertoMS; +https://cofreabertoms.com.br)"}
HOJE = date.today()
ANO = HOJE.year
MANDATO = 2023  # início do mandato atual
csv.field_size_limit(10**7)

# Quem presidia em cada mês do extrato (Dilma foi afastada em 12/05/2016: maio em diante conta para Temer)
PRESIDENTES = [("Dilma Rousseff", "2013-01", "2016-04"), ("Michel Temer", "2016-05", "2018-12"),
               ("Jair Bolsonaro", "2019-01", "2022-12"), ("Luiz Inácio Lula da Silva", "2023-01", "2099-12")]
# Subsídio do presidente, do vice e dos ministros: Decreto Legislativo 172/2022 (valores a partir de cada data)
SUBSIDIO = [("2023-01-01", 39293.32), ("2023-04-01", 41650.92), ("2024-02-01", 44008.52), ("2025-02-01", 46366.19)]
ORGAOS_PR = {"Presidência da República", "Gabinete da Vice-Presidência da República"}


def num(t):
    try:
        return float(str(t).replace(".", "").replace(",", "."))
    except ValueError:
        return 0.0


def presidente(mes):
    return next((p for p, a, b in PRESIDENTES if a <= mes <= b), "—")


def zip_local(caminho):
    """Baixa um zip pequeno inteiro (CPGF, orçamento, transferências)."""
    for t in range(3):
        try:
            r = requests.get(PORTAL.format(caminho), headers=UA, timeout=300)
            if r.status_code == 200 and r.content[:2] == b"PK":
                z = zipfile.ZipFile(io.BytesIO(r.content))
                if z.testzip() is None:
                    return z
            elif r.status_code in (403, 404):
                return None  # mês ainda não publicado
        except (requests.RequestException, zipfile.BadZipFile):
            pass
        time.sleep(5 * (t + 1))
    return None


def zip_remoto(caminho):
    """Zip grande (viagens, servidores): lido por Range, só o arquivo que interessa."""
    r = requests.head(PORTAL.format(caminho), headers=UA, timeout=60, allow_redirects=False)
    url = r.headers.get("location") or PORTAL.format(caminho)
    return zipfile.ZipFile(io.BufferedReader(ArquivoRemoto(url), buffer_size=1 << 22))


def linhas(z, filtro=None):
    nome = next(n for n in z.namelist() if filtro is None or filtro in n)
    return csv.DictReader(io.TextIOWrapper(z.open(nome), encoding="latin1"), delimiter=";")


def meses(ini, fim):
    a, m = ini
    while (a, m) <= fim:
        yield a, m
        a, m = (a + 1, 1) if m == 12 else (a, m + 1)


# ── Cartão corporativo ────────────────────────────────────────────────
def cartao(cache):
    c = cache.setdefault("cartao", {})
    recentes = {f"{a}{m:02d}" for a, m in meses(((HOJE.year * 12 + HOJE.month - 5) // 12, (HOJE.year * 12 + HOJE.month - 5) % 12 + 1), (ANO, HOJE.month))}
    for a, m in meses((2013, 1), (ANO, HOJE.month)):
        k = f"{a}{m:02d}"
        if k in c and k not in recentes:
            continue
        z = zip_local(f"cpgf/{k}")
        if z is None:
            continue
        mes = {"pr": 0.0, "prSig": 0.0, "vice": 0.0, "viceSig": 0.0, "n": 0, "favorecidos": {}, "unidades": {}}
        for x in linhas(z):
            if x["CÓDIGO ÓRGÃO SUPERIOR"] != "20000" or x["NOME ÓRGÃO"] not in ORGAOS_PR:
                continue
            v = num(x["VALOR TRANSAÇÃO"])
            sig = "sigilo" in (x["TRANSAÇÃO"] or "").lower() or (x["NOME FAVORECIDO"] or "").lower() == "sigiloso"
            pre = "vice" if "Vice" in x["NOME ÓRGÃO"] else "pr"
            mes[pre] += v
            if sig:
                mes[pre + "Sig"] += v
            else:
                f = re.sub(r"\s+", " ", x["NOME FAVORECIDO"] or "").strip()
                if f and f not in ("NAO SE APLICA", "SEM INFORMACAO"):
                    fv = mes["favorecidos"].setdefault(f, [0.0, 0, x["CNPJ OU CPF FAVORECIDO"]])
                    fv[0] += v
                    fv[1] += 1
                else:
                    t = (x["TRANSAÇÃO"] or "").split(" - ")[0].title()  # saques e compras sem favorecido
                    fv = mes["favorecidos"].setdefault(f"({t})", [0.0, 0, ""])
                    fv[0] += v
                    fv[1] += 1
            u = x["NOME UNIDADE GESTORA"].strip()
            mes["unidades"][u] = round(mes["unidades"].get(u, 0) + v, 2)
            mes["n"] += 1
        for k2 in ("pr", "prSig", "vice", "viceSig"):
            mes[k2] = round(mes[k2], 2)
        mes["favorecidos"] = {f: [round(v[0], 2), v[1], v[2]] for f, v in sorted(mes["favorecidos"].items(), key=lambda kv: -kv[1][0])[:40]}
        c[k] = mes
        print(f"  cartão {k}: PR {mes['pr']:,.0f} (sigiloso {mes['prSig']:,.0f}) · vice {mes['vice']:,.0f}")
    serie = [{"mes": f"{k[:4]}-{k[4:]}", "presidente": presidente(f"{k[:4]}-{k[4:]}"), **{x: v[x] for x in ("pr", "prSig", "vice", "viceSig")}}
             for k, v in sorted(c.items())]
    por_pres = []
    for p, a, b in PRESIDENTES:
        lst = [s for s in serie if s["presidente"] == p]
        if not lst:
            continue
        tot, sig = sum(s["pr"] for s in lst), sum(s["prSig"] for s in lst)
        fav = {}
        for k, v in c.items():
            if presidente(f"{k[:4]}-{k[4:]}") == p:
                for f, (val, n, doc) in v["favorecidos"].items():
                    x = fav.setdefault(f, [0.0, 0, doc])
                    x[0] += val
                    x[1] += n
        por_pres.append({"presidente": p, "de": lst[0]["mes"], "ate": lst[-1]["mes"], "meses": len(lst), "total": round(tot, 2),
                         "sigiloso": round(sig, 2), "mediaMensal": round(tot / len(lst), 2),
                         "vice": round(sum(s["vice"] for s in lst), 2), "viceSigiloso": round(sum(s["viceSig"] for s in lst), 2),
                         "favorecidos": [{"nome": f, "valor": round(v[0], 2), "transacoes": v[1], "doc": v[2]}
                                         for f, v in sorted(fav.items(), key=lambda kv: -kv[1][0])[:25]]})
    return {"serie": serie, "porPresidente": por_pres}


# ── Viagens (mandato atual) ───────────────────────────────────────────
def viagens(cache, rapido):
    vc = cache.setdefault("viagens", {})
    for a in range(MANDATO, ANO + 1):
        if str(a) in vc and vc[str(a)].get("ministros") and (a < ANO or rapido):
            continue
        try:
            z = zip_remoto(f"viagens/{a}")
        except Exception as e:
            print(f"  ⚠️ viagens {a}: {e}")
            continue
        pr, mins, dest = {}, {}, {}
        tot = {"viagens": 0, "diarias": 0.0, "passagens": 0.0, "outros": 0.0}
        for x in linhas(z, "Viagem.csv"):
            org = x["Nome órgão solicitante"]
            cargo = f"{x.get('Cargo') or ''} {x.get('Descrição Função') or ''} {x.get('Função') or ''}".upper()
            # ministros de Estado vêm com a função CNE-0001 (cargo de natureza especial); o texto do cargo fica vazio
            ministro = "MINISTRO DE ESTADO" in cargo or "MINISTRA DE ESTADO" in cargo or "CNE-0001" in cargo or "NATUREZA ESPECIAL" in cargo
            if org not in ORGAOS_PR and not ministro:
                continue
            d, p_, o = num(x["Valor diárias"]), num(x["Valor passagens"]), num(x["Valor outros gastos"]) - num(x["Valor devolução"])
            chave = (x["Nome"].strip().title(), (x.get("Cargo") or x.get("Descrição Função") or "").strip().capitalize())
            alvo = mins if ministro else pr
            v = alvo.setdefault("|".join(chave), {"nome": chave[0], "cargo": chave[1], "orgao": (x.get("Nome do órgão superior") or x.get("Nome órgão superior") or "").strip(),
                                                  "viagens": 0, "diarias": 0.0, "passagens": 0.0, "outros": 0.0, "destinos": {}})
            v["viagens"] += 1
            v["diarias"] += d
            v["passagens"] += p_
            v["outros"] += o
            for de in re.split(r"[,;]", x.get("Destinos") or ""):
                de = de.strip()
                if de:
                    v["destinos"][de] = v["destinos"].get(de, 0) + 1
                    if not ministro:
                        dest[de] = dest.get(de, 0) + 1
            if not ministro:
                tot["viagens"] += 1
                tot["diarias"] += d
                tot["passagens"] += p_
                tot["outros"] += o
        def enxuga(dic, n):
            out = []
            for v in sorted(dic.values(), key=lambda v: -(v["diarias"] + v["passagens"] + v["outros"]))[:n]:
                v["total"] = round(v["diarias"] + v["passagens"] + v["outros"], 2)
                for k in ("diarias", "passagens", "outros"):
                    v[k] = round(v[k], 2)
                v["destinos"] = [d for d, _ in sorted(v["destinos"].items(), key=lambda kv: -kv[1])[:4]]
                out.append(v)
            return out
        vc[str(a)] = {"presidencia": {k: round(v, 2) if isinstance(v, float) else v for k, v in tot.items()},
                      "pessoasPresidencia": len(pr), "viajantesPresidencia": enxuga(pr, 40), "ministros": enxuga(mins, 80),
                      "destinos": [{"destino": d, "viagens": n} for d, n in sorted(dest.items(), key=lambda kv: -kv[1])[:20]]}
        print(f"  viagens {a}: Presidência {tot['viagens']} viagens · {len(mins)} ministros")
    return vc


# ── Orçamento da Presidência (mandato atual) ──────────────────────────
def orcamento():
    out = []
    for a in range(MANDATO, ANO + 1):
        z = zip_local(f"orcamento-despesa/{a}")
        if z is None:
            continue
        por_org, por_acao, por_elem = {}, {}, {}
        tot = {"inicial": 0.0, "atualizado": 0.0, "empenhado": 0.0, "realizado": 0.0}
        fin = {"empenhado": 0.0, "realizado": 0.0, "acoes": {}}
        for x in linhas(z):
            if x["CÓDIGO ÓRGÃO SUPERIOR"] != "20000":
                continue
            v = {k: num(x[f"ORÇAMENTO {c} (R$)"]) for k, c in (("inicial", "INICIAL"), ("atualizado", "ATUALIZADO"),
                                                                ("empenhado", "EMPENHADO"), ("realizado", "REALIZADO"))}
            # inversões financeiras (empréstimos de fundos geridos pela Presidência desde 2025) não são gasto de funcionamento
            if "INVERS" in (x["NOME GRUPO DE DESPESA"] or "").upper() or "AMORTIZA" in (x["NOME GRUPO DE DESPESA"] or "").upper():
                fin["empenhado"] += v["empenhado"]
                fin["realizado"] += v["realizado"]
                a_ = x["NOME AÇÃO"].strip().capitalize()
                fin["acoes"][a_] = fin["acoes"].get(a_, 0) + v["realizado"]
                continue
            for k in tot:
                tot[k] += v[k]
            for dic, chave in ((por_org, x["NOME ÓRGÃO SUBORDINADO"]), (por_acao, f"{x['NOME AÇÃO'].strip().capitalize()}|{x['NOME ÓRGÃO SUBORDINADO']}"),
                               (por_elem, x["NOME ELEMENTO DE DESPESA"].strip())):
                d = dic.setdefault(chave, {"empenhado": 0.0, "realizado": 0.0})
                d["empenhado"] += v["empenhado"]
                d["realizado"] += v["realizado"]
        r = lambda dic, n: [{"nome": k.split("|")[0], **({"orgao": k.split("|")[1]} if "|" in k else {}),
                             "empenhado": round(v["empenhado"], 2), "realizado": round(v["realizado"], 2)}
                            for k, v in sorted(dic.items(), key=lambda kv: -kv[1]["realizado"])[:n] if v["empenhado"] or v["realizado"]]
        out.append({"ano": a, **{k: round(v, 2) for k, v in tot.items()}, "orgaos": r(por_org, 10), "acoes": r(por_acao, 25), "elementos": r(por_elem, 15),
                    "financeiro": {"empenhado": round(fin["empenhado"], 2), "realizado": round(fin["realizado"], 2),
                                   "acoes": [{"nome": k, "realizado": round(v, 2)} for k, v in sorted(fin["acoes"].items(), key=lambda kv: -kv[1]) if v][:5]}})
        print(f"  orçamento {a}: realizado R$ {tot['realizado']:,.0f}")
    return out


# ── Remuneração ───────────────────────────────────────────────────────
def remuneracao():
    for k in range(0, 4):
        a, m = divmod(HOJE.year * 12 + HOJE.month - 1 - k, 12)
        m += 1
        try:
            z = zip_remoto(f"servidores/{a}{m:02d}_Servidores_SIAPE")
        except Exception:
            continue
        ids = {}
        for x in linhas(z, "Cadastro.csv"):
            if "MINISTRO DE ESTADO" in (x.get("DESCRICAO_CARGO") or "").upper():
                ids[x["Id_SERVIDOR_PORTAL"]] = {"nome": x["NOME"].strip().title(), "orgao": (x.get("ORG_EXERCICIO") or "").strip(),
                                                "desde": x.get("DATA_INGRESSO_CARGOFUNCAO")}
        mins = []
        for x in linhas(z, "Remuneracao.csv"):
            i = ids.get(x["Id_SERVIDOR_PORTAL"])
            if not i:
                continue
            g = lambda c: num(x.get(c) or 0)
            mins.append({**i, "bruto": g("REMUNERAÇÃO BÁSICA BRUTA (R$)"), "abateTeto": g("ABATE-TETO (R$)"),
                         "eventuais": g("OUTRAS REMUNERAÇÕES EVENTUAIS (R$)"), "ferias": g("FÉRIAS (R$)"),
                         "natalina": g("GRATIFICAÇÃO NATALINA (R$)"), "liquido": g("REMUNERAÇÃO APÓS DEDUÇÕES OBRIGATÓRIAS (R$)"),
                         "indenizatorias": g("TOTAL DE VERBAS INDENIZATÓRIAS (R$)(*)")})
        if mins:
            print(f"  remuneração {m:02d}/{a}: {len(mins)} ministros")
            return {"mes": f"{m:02d}/{a}", "ministros": sorted(mins, key=lambda x: -(x["bruto"] + x["eventuais"]))}
    return None


# ── Transferências da União para MS ───────────────────────────────────
def transferencias_ms(cache):
    tc = cache.setdefault("transferencias", {})
    for a, m in meses((ANO, 1), (ANO, HOJE.month)):
        k = f"{a}{m:02d}"
        if k in tc and (a, m) < ((HOJE.year * 12 + HOJE.month - 3) // 12, (HOJE.year * 12 + HOJE.month - 3) % 12 + 1):
            continue
        z = zip_local(f"transferencias/{k}")
        if z is None:
            continue
        tipo, orgao, mun = {}, {}, {}
        for x in linhas(z):
            if x["UF"] != "MS":
                continue
            v = num(x["VALOR TRANSFERIDO"])
            tipo[x["TIPO TRANSFERÊNCIA"]] = tipo.get(x["TIPO TRANSFERÊNCIA"], 0) + v
            o = x["NOME ÓRGÃO"] if x["NOME ÓRGÃO"] != "Sem informação" else "Transferências constitucionais (FPE, FPM e outras)"
            orgao[o] = orgao.get(o, 0) + v
            nm = (x["NOME MUNICÍPIO"] or "").strip().title() or ("Governo do Estado" if "Estadual" in x["TIPO FAVORECIDO"] else "Outros favorecidos")
            mun[nm] = mun.get(nm, 0) + v
        tc[k] = {"tipo": tipo, "orgao": orgao, "municipio": mun}
        print(f"  transferências {k}: R$ {sum(tipo.values()):,.0f} para MS")
    soma = lambda campo: {}
    agg = {"tipo": {}, "orgao": {}, "municipio": {}}
    for k, v in tc.items():
        if k.startswith(str(ANO)):
            for c in agg:
                for n, val in v[c].items():
                    agg[c][n] = agg[c].get(n, 0) + val
    ult = max((k for k in tc if k.startswith(str(ANO))), default=None)
    return {"ano": ANO, "ate": f"{ult[4:]}/{ult[:4]}" if ult else None, "total": round(sum(agg["tipo"].values()), 2),
            **{c: [{"nome": n, "valor": round(v, 2)} for n, v in sorted(agg[c].items(), key=lambda kv: -kv[1]) if v]
               for c in agg}}


def main():
    rapido = "--rapido" in sys.argv
    try:
        cache = json.load(open(CACHE, encoding="utf-8"))
    except Exception:
        cache = {}
    anterior = {}
    try:
        anterior = json.load(open(SAIDA, encoding="utf-8"))
    except Exception:
        pass
    saida = {"ultimaAtualizacao": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
             "fonte": "Portal da Transparência do Governo Federal (CGU) — dados abertos",
             "subsidio": [{"desde": d, "valor": v} for d, v in SUBSIDIO]}
    for nome, f in (("cartao", lambda: cartao(cache)), ("viagens", lambda: viagens(cache, rapido)), ("orcamento", orcamento),
                    ("remuneracao", remuneracao), ("ms", lambda: transferencias_ms(cache))):
        try:
            saida[nome] = f()
        except Exception as e:
            print(f"  ⚠️ {nome}: {e} — mantido o anterior")
            saida[nome] = anterior.get(nome)
        CACHE.write_text(json.dumps(cache, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    SAIDA.write_text(json.dumps(saida, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"✅ presidencia.json ({SAIDA.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
