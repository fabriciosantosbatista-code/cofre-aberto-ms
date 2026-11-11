#!/usr/bin/env python3
"""
Cofre Aberto MS — Governo do Estado de Mato Grosso do Sul

Fonte: Portal da Transparência do Estado (www.transparencia.ms.gov.br). O portal
é uma página AngularJS que busca os dados numa API pública (gw.sgi.ms.gov.br)
com um token anônimo que o próprio site entrega a qualquer visitante em
/Auth/Token (vale 5 minutos — pegamos um novo a cada chamada).

Gera dados/governo_ms.json com:
  totais        empenhado, liquidado e pago no ano (todas as unidades gestoras)
  meses         valor pago por mês no ano e no ano anterior (gráfico de evolução)
  orgaos        empenhado/liquidado/pago por órgão (unidade gestora)
  credores      os 1.000 fornecedores que mais receberam no ano + os 100 maiores
                credores de folha, repasses a órgãos públicos e bancos (tipo)
  diarias       diárias pagas: total, por mês da viagem, por órgão e os 200
                maiores beneficiários (o portal publica o CPF já mascarado)
  primeiroEscalao  remuneração dos agentes políticos (governador, vice e
                secretários com esse vínculo) no último mês da folha e a soma
                do ano

Uso:  python3 scripts/coletar_governo_ms.py
"""

import base64, csv, io, json, re, sys, time
from datetime import date, datetime
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent))
from ano_ref import ano_referencia  # noqa: E402

ROOT = Path(__file__).parent.parent
SAIDA = ROOT / "dados" / "governo_ms.json"
CREDORES = ROOT / "dados" / "governo_ms_credores.json"  # [cnpj/cpf, nome, pago, empenhado, tipo]
PORTAL = "https://www.transparencia.ms.gov.br"
API = "https://gw.sgi.ms.gov.br"
DESPESAS = "/d0146/transpdespesas/v1"
DIARIAS = "/d0128/transpdiarias/v1"
FOLHA = "/d0125/transpfolhadepagamento/v1"
UA = {"User-Agent": "Mozilla/5.0 (CofreAbertoMS; +https://cofreabertoms.com.br)"}
MESES = ["janeiro", "fevereiro", "marco", "abril", "maio", "junho", "julho",
         "agosto", "setembro", "outubro", "novembro", "dezembro"]

ANO = ano_referencia()
HOJE = date.today()
sess = requests.Session()
sess.headers.update(UA)


def token():
    r = sess.get(PORTAL + "/Auth/Token", timeout=30)
    r.raise_for_status()
    return r.text.strip().strip('"')


def api(rota, params, timeout=180, tentativas=3):
    erro = None
    for t in range(tentativas):
        try:
            r = sess.get(API + rota, params=params, timeout=timeout,
                         headers={"Authorization": "Bearer " + token()})
            j = r.json()
            st = j.get("status")
            cod = st.get("code", r.status_code) if isinstance(st, dict) else (st or r.status_code)
            if cod == 200:
                return j
            erro = f"{cod} {st.get('message') if isinstance(st, dict) else (j.get('errors') or j.get('title'))}"
            if 400 <= int(cod) < 500 and cod != 429:
                break  # erro de parâmetro: repetir não adianta
        except Exception as e:  # rede, JSON inválido
            erro = str(e)
        time.sleep(5 * (t + 1))
    raise RuntimeError(f"{rota}: {erro}")


def br(d):
    # a API interpreta dd/mm como mm/dd (cultura en-US); ISO não tem ambiguidade
    return d.isoformat()


def fim_do_mes(ano, mes):
    if ano == HOJE.year and mes == HOJE.month:
        return HOJE
    prox = date(ano + (mes == 12), mes % 12 + 1, 1)
    return date.fromordinal(prox.toordinal() - 1)


def limpa(t):
    return re.sub(r"\s+", " ", (t or "")).strip()


def ultimo_mes(ano):
    return 12 if ano < HOJE.year else HOJE.month


# ── Credores: separa fornecedores de folha, repasses e bancos ────────
PUBLICO_RE = re.compile(r"\b(GOVERNO|SECRETARIA|SEC\.? ?DE ESTADO|FUNDO|FUNDACAO ESTADUAL|TRIBUNAL|DEFENSORIA|MINISTERIO PUBLICO|"
                        r"PROCURADORIA|PREFEITURA|MUNICIPIO|CAMARA MUNICIPAL|ASSEMBLEIA|AGENCIA DE PREVIDENCIA|INSS|"
                        r"INSTITUTO NACIONAL DO SEGURO|RECEITA FEDERAL|COAFI|DETRAN|UNIVERSIDADE ESTADUAL|"
                        r"SISTEMA DE PROTECAO SOCIAL|TJ/MS|TC/MS|INATIVOS|PENSIONISTAS)\b")
BANCO_RE = re.compile(r"\b(BANCO|BANK|CAIXA ECONOMICA|BB\b|BIRD|BNDES|DIVIDA)")


def tipo_credor(doc, nome):
    """fornecedor | folha (folha, aposentadorias, dívida: códigos 'PF.' do portal) | publico | financeiro"""
    import unicodedata
    n = unicodedata.normalize("NFD", nome.upper()).encode("ascii", "ignore").decode()
    if str(doc).startswith("PF."):
        return "folha"
    if BANCO_RE.search(n):
        return "financeiro"
    if PUBLICO_RE.search(n):
        return "publico"
    return "fornecedor"


def credores_painel(credores):
    """Os 1.000 maiores fornecedores + os 100 maiores dos outros tipos (já ordenados por pago)."""
    forn = [c for c in credores if c["tipo"] == "fornecedor"][:1000]
    outros = [c for c in credores if c["tipo"] != "fornecedor"][:100]
    return sorted(forn + outros, key=lambda c: -c["pago"])


# ── Despesas ──────────────────────────────────────────────────────────
def despesas_periodo(metodo, ini, fim, pagesize):
    j = api(DESPESAS + "/" + metodo, {"anoconsulta": ini.year, "dataInicio": br(ini), "dataFim": br(fim),
                                      "pageno": 1, "pagesize": pagesize, "exportarcsv": "false"})
    return j["data"][0]


def coletar_despesas():
    ini, fim = date(ANO, 1, 1), min(HOJE, date(ANO, 12, 31))
    por_orgao = despesas_periodo("despesapordataorgaos", ini, fim, 1000)
    totais = {"empenhado": por_orgao["totalEmpenhado"], "liquidado": por_orgao["totalLiquidado"],
              "pago": por_orgao["totalPago"]}
    orgaos = sorted(({"codigo": o.get("codigo"), "orgao": limpa(o["orgao"]), "empenhado": o["empenhado"],
                      "liquidado": o["liquidado"], "pago": o["pago"]} for o in por_orgao["despesas"]),
                    key=lambda o: -o["pago"])
    print(f"  órgãos: {len(orgaos)} — pago R$ {totais['pago']:,.2f}")

    cred = despesas_periodo("despesapordatacredores", ini, fim, 40000)
    credores = [{"cnpj": c["cpfCnpj"], "credor": limpa(c["credor"]), "empenhado": c["empenhado"],
                 "liquidado": c["liquidado"], "pago": c["pago"],
                 "tipo": tipo_credor(c["cpfCnpj"], limpa(c["credor"]))} for c in cred["despesas"]]
    credores.sort(key=lambda c: -c["pago"])
    print(f"  credores: {len(credores)}")

    meses = {}
    for ano in (ANO - 1, ANO):
        serie = []
        for m in range(1, ultimo_mes(ano) + 1):
            try:
                d = despesas_periodo("despesapordataorgaos", date(ano, m, 1), fim_do_mes(ano, m), 1)
                serie.append(round(d["totalPago"], 2))
            except Exception as e:
                print(f"  ⚠️ mês {m}/{ano}: {e}")
                serie.append(None)
        meses[str(ano)] = serie
    return totais, orgaos, credores, meses


# ── Diárias ───────────────────────────────────────────────────────────
def valor_br(t):
    t = (t or "").replace("R$", "").replace(".", "").replace(",", ".").strip().strip('"')
    try:
        return float(t)
    except ValueError:
        return 0.0


def diarias_do_mes(mes):
    """O export CSV traz cada beneficiário seguido dos trechos (com o valor).
    Atenção: o filtro de mês do portal não é exclusivo — a consulta de janeiro
    traz viagens do ano todo e as de meses seguidos se sobrepõem. Por isso os
    trechos de todas as consultas são juntados sem repetição e agrupados pelo
    mês da data de saída da viagem."""
    j = api(DIARIAS + "/beneficiarios", {"anoconsulta": ANO, "mesconsulta": mes, "pageno": 1,
                                         "pagesize": 5000, "exportarcsv": "true"}, timeout=600)
    txt = base64.b64decode(j["data"][0]["base64"]).decode("utf-8-sig", "replace")
    viagens, atual, em_trechos = [], None, False
    for linha in csv.reader(io.StringIO(txt), delimiter=";"):
        if not linha or not any(c.strip() for c in linha):
            em_trechos = False
            continue
        if linha[0] == "Órgão":
            continue
        if linha[0] == "Nome Cidade Origem":
            em_trechos = True
            continue
        if em_trechos and atual and len(linha) >= 6:
            viagens.append({**atual, "origem": limpa(linha[0]), "destino": limpa(linha[1]),
                            "saida": linha[3][:8], "chegada": linha[4][:8], "valor": valor_br(linha[5])})
        elif len(linha) >= 7 and not em_trechos:
            atual = {"orgao": limpa(linha[0]), "cpf": linha[1].strip(), "nome": limpa(linha[2]),
                     "cargo": limpa(linha[3]), "tipo": limpa(linha[4]), "ob": linha[6].strip()}
    return viagens


def coletar_diarias():
    unicos, consultas_ok = {}, 0
    for m in range(1, ultimo_mes(ANO) + 1):
        try:
            v = diarias_do_mes(m)
        except Exception as e:
            print(f"  ⚠️ diárias (consulta {m}/{ANO}): {e}")
            continue
        consultas_ok += 1
        novos = 0
        for x in v:
            k = (x["ob"], x["nome"], x["cpf"], x["origem"], x["destino"], x["saida"], x["chegada"], x["valor"])
            if k not in unicos:
                unicos[k] = x
                novos += 1
        print(f"  diárias (consulta {m:02d}/{ANO}): {len(v)} trechos, {novos} novos")
    if not unicos:
        return None
    meses = [{"valor": 0.0, "trechos": 0} for _ in range(12)]
    por_orgao, pessoas, total, fora = {}, {}, 0.0, 0
    for x in unicos.values():
        s = x["saida"]  # dd/mm/aa
        mes = int(s[3:5]) - 1 if re.match(r"\d\d/\d\d/\d\d", s) else None
        if mes is None or 2000 + int(s[6:8]) != ANO:
            fora += 1  # viagem de outro ano paga neste (entra no total, não no mês)
        else:
            meses[mes]["valor"] += x["valor"]
            meses[mes]["trechos"] += 1
        total += x["valor"]
        o = por_orgao.setdefault(x["orgao"], {"orgao": x["orgao"], "valor": 0.0, "trechos": 0})
        o["valor"] += x["valor"]
        o["trechos"] += 1
        k = (x["nome"], x["cpf"], x["orgao"])
        p = pessoas.setdefault(k, {"nome": x["nome"], "cpf": x["cpf"], "orgao": x["orgao"], "cargo": x["cargo"],
                                   "tipo": x["tipo"], "valor": 0.0, "trechos": 0, "destinos": {}})
        p["valor"] += x["valor"]
        p["trechos"] += 1
        p["destinos"][x["destino"]] = p["destinos"].get(x["destino"], 0) + 1
    for m in meses:
        m["valor"] = round(m["valor"], 2)
    for o in por_orgao.values():
        o["valor"] = round(o["valor"], 2)
    top = sorted(pessoas.values(), key=lambda p: -p["valor"])[:200]
    for p in top:
        p["valor"] = round(p["valor"], 2)
        p["destinos"] = [d for d, _ in sorted(p["destinos"].items(), key=lambda kv: -kv[1])[:5]]
    print(f"  diárias: {len(unicos)} trechos únicos, R$ {total:,.2f} ({fora} de viagens fora do ano)")
    return {"total": round(total, 2), "trechos": len(unicos), "meses": meses[:ultimo_mes(ANO)],
            "consultas": consultas_ok, "consultasPrevistas": ultimo_mes(ANO), "trechosForaDoAno": fora,
            "beneficiarios": len(pessoas), "porOrgao": sorted(por_orgao.values(), key=lambda o: -o["valor"]),
            "maiores": top}


# ── Primeiro escalão (agentes políticos) ─────────────────────────────
def folha_agentes(mes):
    j = api(FOLHA + "/servidores", {"anoexercicio": ANO, "mescompetencia": mes, "vinculo": "AGENTE POLITICO",
                                    "tipoFolha": 1, "pageno": 1, "pagesize": 500, "exportarcsv": "false"})
    return j.get("data") or []


def coletar_primeiro_escalao():
    ex = api(FOLHA + "/exercicios", {})
    flags = next((e for e in ex["data"] if e["anoCompetencia"] == ANO), None)
    if not flags:
        return None
    meses_ok = [i + 1 for i, m in enumerate(MESES) if flags.get(m)]
    if not meses_ok:
        return None
    soma, ultimo = {}, []
    for m in meses_ok:
        try:
            lista = folha_agentes(m)
        except Exception as e:
            print(f"  ⚠️ folha {m}/{ANO}: {e}")
            continue
        for x in lista:
            k = (x["nome"], x["cpf"])
            soma[k] = soma.get(k, 0) + (x.get("remuneracaoFixa") or 0) + (x.get("remuneracoesEventuais") or 0)
        if m == meses_ok[-1]:
            ultimo = lista
    pessoas = []
    for x in ultimo:
        cargo = limpa(x["cargo"])
        pessoas.append({"nome": limpa(x["nome"]), "orgao": limpa(x["orgao"]),
                        "cargo": cargo.replace("ADMINISTRAÇÃO SUPERIOR DIRETA - CCA-SEC", "Secretário(a) / dirigente")
                                      .replace("ADMINISTRAÇÃO SUPERIOR DIRETA", "Administração superior"),
                        "situacao": limpa(x["situacao"]).title(),
                        "ativo": x["situacao"].strip().upper() == "ATIVO",
                        "bruto": round((x.get("remuneracaoFixa") or 0) + (x.get("remuneracoesEventuais") or 0), 2),
                        "fixa": x.get("remuneracaoFixa"), "eventuais": x.get("remuneracoesEventuais"),
                        "liquido": x.get("remuneracaoAposDeducoes"), "admissao": x.get("dataAdmissao"),
                        "somaAno": round(soma.get((x["nome"], x["cpf"]), 0), 2)})
    ordem = {"GOVERNADOR": 0, "VICE-GOVERNADOR": 1}
    pessoas.sort(key=lambda p: (not p["ativo"], ordem.get(p["cargo"], 2), -p["bruto"]))
    return {"competencia": f"{meses_ok[-1]:02d}/{ANO}", "mesesNoAno": len(meses_ok), "pessoas": pessoas}


def main():
    try:
        anterior = json.load(open(SAIDA, encoding="utf-8"))
    except Exception:
        anterior = {}
    mesmo_ano = anterior.get("ano") == ANO
    print(f"🏛️  Governo do Estado de MS — {ANO}")
    out = {"ano": ANO, "fonte": PORTAL, "fonteApi": API,
           "ultimaAtualizacao": datetime.now().isoformat(timespec="seconds")}
    ok = 0
    try:
        out["totais"], out["orgaos"], out["credores"], out["meses"] = coletar_despesas()
        out["totalCredores"] = len(out["credores"])
        # lista completa (enxuta) para as Conexões e a planilha; o painel usa só os 1.000 maiores
        CREDORES.write_text(json.dumps({"ano": ANO, "ultimaAtualizacao": out["ultimaAtualizacao"], "credores": [
            [c["cnpj"], c["credor"], round(c["pago"], 2), round(c["empenhado"], 2), c["tipo"]] for c in out["credores"]
            if c["pago"] or c["empenhado"]]}, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        out["credoresPorTipo"] = {t: round(sum(c["pago"] for c in out["credores"] if c["tipo"] == t), 2)
                                  for t in ("fornecedor", "folha", "publico", "financeiro")}
        out["totalFornecedores"] = sum(1 for c in out["credores"] if c["tipo"] == "fornecedor")
        out["credores"] = credores_painel(out["credores"])
        ok += 1
    except Exception as e:
        print(f"  ❌ despesas: {e}")
        if mesmo_ano:
            for k in ("totais", "orgaos", "credores", "totalCredores", "meses", "credoresPorTipo", "totalFornecedores"):
                if k in anterior:
                    out[k] = anterior[k]
    for chave, func in (("diarias", coletar_diarias), ("primeiroEscalao", coletar_primeiro_escalao)):
        try:
            v = func()
            if v:
                out[chave] = v
                ok += 1
            elif mesmo_ano and chave in anterior:
                out[chave] = anterior[chave]
        except Exception as e:
            print(f"  ❌ {chave}: {e}")
            if mesmo_ano and chave in anterior:
                out[chave] = anterior[chave]
    if ok == 0:
        print("❌ nada coletado — arquivo anterior mantido")
        sys.exit(1)
    di = out.get("diarias") or {}
    if ok < 3 or di.get("consultas", 0) < di.get("consultasPrevistas", 0):
        out["coletaParcial"] = True
    SAIDA.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"✅ {SAIDA.relative_to(ROOT)} ({SAIDA.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
