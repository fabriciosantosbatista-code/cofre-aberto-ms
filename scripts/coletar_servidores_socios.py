#!/usr/bin/env python3
"""
Cofre Aberto MS — Servidores do Governo do Estado que são sócios de empresas pagas com dinheiro público

Baixa a folha de pagamento do Estado (Portal da Transparência de MS, token
anônimo /Auth/Token) e cruza com o quadro de sócios das empresas
(dados/cnpj_cache.json, coletar_cnpj.py). O cruzamento exige o MESMO NOME e os
MESMOS 6 DÍGITOS DO MEIO DO CPF — os dois portais publicam o CPF mascarado no
mesmo trecho (***.123.456-** na folha, ***123456** na Receita) —, o que
praticamente elimina homônimos.

Só entram servidores ativos (aposentados e pensionistas podem ser sócios
livremente). Gera dados/servidores_socios.json, usado por gerar_auditoria.py.
"""

import json, re, sys, time, unicodedata
from datetime import date, datetime
from pathlib import Path

import requests

ROOT = Path(__file__).parent.parent
DADOS = ROOT / "dados"
UA = {"User-Agent": "Mozilla/5.0 (CofreAbertoMS; +https://cofreabertoms.com.br)"}
FOLHA = "https://gw.sgi.ms.gov.br/d0125/transpfolhadepagamento/v1"
ANO = date.today().year


def norm(t):
    return re.sub(r"\s+", " ", unicodedata.normalize("NFD", str(t or "")).encode("ascii", "ignore").decode().upper()).strip()


def token():
    return requests.get("https://www.transparencia.ms.gov.br/Auth/Token", headers=UA, timeout=30).text.strip().strip('"')


def folha_estado():
    ex = requests.get(FOLHA + "/exercicios", headers={**UA, "Authorization": "Bearer " + token()}, timeout=60).json()["data"]
    meses = ["janeiro", "fevereiro", "marco", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"]
    flags = next((e for e in ex if e["anoCompetencia"] == ANO), None) or {}
    mes = max((i + 1 for i, n in enumerate(meses) if flags.get(n)), default=None)
    if not mes:
        raise RuntimeError("folha do ano ainda não publicada")
    linhas, pagina = [], 1
    while True:
        for t in range(3):
            try:
                j = requests.get(FOLHA + "/servidores", timeout=600, headers={**UA, "Authorization": "Bearer " + token()},
                                 params={"anoexercicio": ANO, "mescompetencia": mes, "tipoFolha": 1, "pageno": pagina,
                                         "pagesize": 20000, "exportarcsv": "false"}).json()
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
    return linhas, f"{mes:02d}/{ANO}"


def main():
    cad = json.load(open(DADOS / "cnpj_cache.json", encoding="utf-8"))
    socios = {}
    for c, info in cad.items():
        for s in info.get("socios") or []:
            if s.get("cpf") and len(s["cpf"]) == 6 and s.get("nome"):
                socios.setdefault((norm(s["nome"]), s["cpf"]), []).append((c, info.get("razao"), s.get("qualificacao"), s.get("entrada")))
    linhas, mes = folha_estado()
    nomes_org = {}
    try:  # sigla do órgão (como vem na folha) → nome completo, para comparar com o órgão que pagou a empresa
        for o in requests.get(FOLHA + "/orgaos", params={"anoexercicio": ANO}, timeout=60,
                              headers={**UA, "Authorization": "Bearer " + token()}).json().get("data") or []:
            if o.get("id") and o.get("descricao"):
                nomes_org.setdefault(o["id"].strip(), re.sub(r"\s*\([^)]*\)\s*$", "", o["descricao"]).strip())
    except Exception as e:
        print(f"  ⚠️ nomes dos órgãos: {e}")
    achados = []
    for x in linhas:
        sit = (x.get("situacao") or "").upper()
        if sit.startswith("INATIVO") or "PENSION" in sit:
            continue
        cpf = re.sub(r"\D", "", x.get("cpf") or "")
        for c, razao, qual, entrada in socios.get((norm(x.get("nome")), cpf), []):
            achados.append({"nome": re.sub(r"\s+", " ", x.get("nome") or "").strip().title(), "orgao": (x.get("orgao") or "").strip(),
                            "orgaoNome": nomes_org.get((x.get("orgao") or "").strip()),
                            "cargo": (x.get("cargo") or "").strip().capitalize(), "vinculo": (x.get("vinculo") or "").strip().capitalize(),
                            "situacao": sit.capitalize(), "admissao": x.get("dataAdmissao"), "cnpj": c, "empresa": razao,
                            "qualificacao": qual, "entradaSociedade": entrada})
    if len(linhas) < 50000:
        print(f"❌ folha do Estado com só {len(linhas)} registros — arquivo mantido")
        sys.exit(1)
    (DADOS / "servidores_socios.json").write_text(json.dumps({
        "ultimaAtualizacao": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"), "mesFolha": mes, "registrosFolha": len(linhas),
        "sociosComCpf": len(socios), "achados": achados}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"✅ servidores_socios.json — folha {mes} ({len(linhas)} registros) × {len(socios)} sócios: {len(achados)} servidores ativos sócios")


if __name__ == "__main__":
    main()
