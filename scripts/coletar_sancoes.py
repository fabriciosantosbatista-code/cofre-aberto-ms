#!/usr/bin/env python3
"""
Cofre Aberto MS — Empresas e pessoas punidas (CEIS e CNEP, da CGU)

Baixa do Portal da Transparência do Governo Federal os cadastros nacionais de
sanções — CEIS (empresas inidôneas e suspensas) e CNEP (empresas punidas pela
Lei Anticorrupção) — e guarda só o que interessa ao site:
  - sanções a empresas (CNPJ) que aparecem nas bases do site: notas dos
    parlamentares, despesas da Prefeitura de CG e credores do Governo de MS;
  - sanções a pessoas (CPF) que são sócias dessas empresas, pelo nome e pelos
    6 dígitos do meio do CPF (o trecho que a Receita publica no quadro de sócios).

Gera dados/sancoes.json, usado por gerar_auditoria.py.
"""

import csv, io, json, re, sys, unicodedata, zipfile
from datetime import date, datetime, timedelta
from pathlib import Path

import requests

ROOT = Path(__file__).parent.parent
DADOS = ROOT / "dados"
UA = {"User-Agent": "Mozilla/5.0 (CofreAbertoMS; +https://cofreabertoms.com.br)"}
URL = "https://portaldatransparencia.gov.br/download-de-dados/{}/{}"


def dig(t):
    return re.sub(r"\D", "", str(t or ""))


def norm(t):
    return re.sub(r"\s+", " ", unicodedata.normalize("NFD", str(t or "")).encode("ascii", "ignore").decode().upper()).strip()


def iso(br):
    m = re.match(r"(\d{2})/(\d{2})/(\d{4})", br or "")
    return f"{m[3]}-{m[2]}-{m[1]}" if m else None


def carregar(nome):
    try:
        return json.load(open(DADOS / nome, encoding="utf-8"))
    except Exception:
        return {}


def baixar(cadastro):
    """O arquivo do dia sai à noite: tenta hoje e volta até 10 dias."""
    for k in range(10):
        d = (date.today() - timedelta(days=k)).strftime("%Y%m%d")
        try:
            r = requests.get(URL.format(cadastro, d), headers=UA, timeout=180)
            if r.status_code == 200 and r.content[:2] == b"PK":
                z = zipfile.ZipFile(io.BytesIO(r.content))
                nome = z.namelist()[0]
                return list(csv.DictReader(io.TextIOWrapper(z.open(nome), encoding="latin1"), delimiter=";")), d
        except requests.RequestException:
            continue
    raise RuntimeError(f"{cadastro}: nenhum arquivo nos últimos 10 dias")


def universo():
    """Raízes de CNPJ que recebem dinheiro nas bases do site."""
    raizes = set(c[:8] for c in carregar("cnpj_cache.json"))
    for x in carregar("prefeitura.json").get("despesas", []):
        if len(dig(x.get("cnpj"))) == 14:
            raizes.add(dig(x["cnpj"])[:8])
    for c in carregar("governo_ms_credores.json").get("credores", []):
        if len(dig(c[0])) == 14:
            raizes.add(dig(c[0])[:8])
    return raizes


def main():
    raizes = universo()
    socios = {}
    for c, info in carregar("cnpj_cache.json").items():
        for q in info.get("socios") or []:
            if q.get("cpf") and q.get("nome"):
                socios.setdefault((norm(q["nome"]), q["cpf"]), []).append(c)
    empresas, pessoas, datas, linhas = [], [], {}, 0
    for cad in ("ceis", "cnep"):
        rows, d = baixar(cad)
        datas[cad.upper()] = d
        linhas += len(rows)
        for r in rows:
            doc = dig(r.get("CPF OU CNPJ DO SANCIONADO"))
            fim = iso(r.get("DATA FINAL SANÇÃO"))
            item = {"cadastro": cad.upper(), "categoria": (r.get("CATEGORIA DA SANÇÃO") or "").strip(),
                    "inicio": iso(r.get("DATA INÍCIO SANÇÃO")), "fim": fim,
                    "abrangencia": (r.get("ABRAGÊNCIA DA SANÇÃO") or r.get("ABRANGÊNCIA DA SANÇÃO") or "").strip(),
                    "orgao": (r.get("ÓRGÃO SANCIONADOR") or "").strip(), "uf": (r.get("UF ÓRGÃO SANCIONADOR") or "").strip(),
                    "esfera": (r.get("ESFERA ÓRGÃO SANCIONADOR") or "").strip(), "processo": (r.get("NÚMERO DO PROCESSO") or "").strip(),
                    "fundamento": (r.get("FUNDAMENTAÇÃO LEGAL") or "").strip()[:200]}
            if fim and fim < f"{date.today().year - 1}-01-01":
                continue  # já acabou antes do ano passado
            if len(doc) == 14 and doc[:8] in raizes:
                empresas.append({"cnpj": doc, "nome": (r.get("RAZÃO SOCIAL - CADASTRO RECEITA") or r.get("NOME DO SANCIONADO") or "").strip(), **item})
            elif len(doc) == 11:
                for c in socios.get((norm(r.get("NOME DO SANCIONADO")), doc[3:9]), []):
                    pessoas.append({"nome": (r.get("NOME DO SANCIONADO") or "").strip().title(), "cnpjEmpresa": c, **item})
    if linhas < 1000:
        print(f"❌ CEIS/CNEP com só {linhas} linhas — arquivo mantido")
        sys.exit(1)
    (DADOS / "sancoes.json").write_text(json.dumps({
        "ultimaAtualizacao": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"), "arquivos": datas, "linhasLidas": linhas,
        "fonte": "Portal da Transparência (CGU) — CEIS e CNEP", "empresas": empresas, "socios": pessoas},
        ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"✅ sancoes.json — {linhas} sanções lidas; {len(empresas)} de empresas pagas em MS, {len(pessoas)} de sócios dessas empresas")


if __name__ == "__main__":
    main()
