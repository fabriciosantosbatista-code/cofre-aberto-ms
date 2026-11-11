#!/usr/bin/env python3
"""
Cofre Aberto MS — Servidores da Assembleia Legislativa (ALEMS)

Fontes:
  consulta de servidores   transparencia2.al.ms.gov.br/consulta-servidores
                           (matrícula, nome, cargo e símbolo de cada servidor)
  tabela de salários       transparencia.al.ms.gov.br → Recursos Humanos →
                           Tabelas de Salários Servidores (PDF do ano)

O que a ALEMS NÃO publica: a lotação (em qual gabinete cada servidor trabalha)
e a remuneração individual. Por isso o site mostra quantos assessores de
gabinete parlamentar existem, em que níveis, e o vencimento-base de cada nível
pela tabela oficial — sem gratificações e vantagens pessoais, que a ALEMS não
detalha por servidor.

Gera dados/alems_servidores.json.  Uso:  python3 scripts/coletar_servidores_alems.py
"""

import io, json, re, sys
from datetime import datetime
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent))
from ano_ref import ano_referencia  # noqa: E402

ROOT = Path(__file__).parent.parent
SAIDA = ROOT / "dados" / "alems_servidores.json"
CONSULTA = "https://transparencia2.al.ms.gov.br/consulta-servidores"
DOCS = "https://www.transparencia.al.ms.gov.br/pages/index.php/gerdocumento"
TABELAS = DOCS + "/1994"  # Recursos Humanos → Tabelas de Salários Servidores (uma pasta por ano)
ANO = ano_referencia()
UA = {"User-Agent": "Mozilla/5.0 (CofreAbertoMS; +https://cofreabertoms.com.br)"}
# grupos de cargos em comissão (a tabela traz um valor por símbolo)
COMISSAO = ("PLSEC", "PLCH", "PLAS", "PLDS", "PLAI", "PLAP", "PLIN", "PLTP", "FCL")
GRUPOS = {"PLAP": "Assessor de gabinete parlamentar", "PLAI": "Assessor intermediário", "PLTP": "Apoio técnico parlamentar",
          "PLAS": "Assessoramento superior", "PLCH": "Chefia / coordenação", "PLDS": "Direção superior",
          "PLSEC": "Secretário", "PLIN": "Segurança externa (função de confiança)", "ANLS": "Analista legislativo (concursado)",
          "TCLS": "Técnico legislativo (concursado)", "PLSA": "Nível elementar (concursado)", "PLSI": "Nível elementar (concursado)",
          "FCL": "Função de confiança legislativa"}


def servidores():
    s = requests.Session()
    s.headers.update(UA)
    linhas, pagina, total = [], 1, None
    while total is None or len(linhas) < total:
        r = s.get(CONSULTA + "/data", params={"page": pagina, "perPage": 50, "sort": "nome", "dir": "asc"}, timeout=60)
        r.raise_for_status()
        j = r.json()
        total = j["total"]
        if not j["rows"]:
            break
        linhas += j["rows"]
        pagina += 1
        if pagina > 200:
            break
    atualizado = None
    try:
        m = re.search(r"Atualizado até:\s*(\d{2}/\d{2}/\d{4})", s.get(CONSULTA, timeout=60).text)
        atualizado = m.group(1) if m else None
    except Exception:
        pass
    return linhas, total, atualizado


def simb(t):
    return re.sub(r"\s+", "", t).upper()


def tabela_salarios():
    """{símbolo: vencimento} dos cargos em comissão, do PDF do ano de referência."""
    import pypdf
    s = requests.Session()
    s.headers.update(UA)
    pasta = s.get(TABELAS, timeout=60).text
    # a pasta lista um link por ano: <a href="5313">...2026
    anos = re.findall(r'href="(\d+)"[^>]*>\s*(?:&nbsp;|\s)*(\d{4})', pasta) or \
        list(zip(re.findall(r'href="(\d+)"', pasta), re.findall(r'>(\d{4})&nbsp;', pasta)))
    alvo = next((i for i, a in anos if a == str(ANO)), None) or (anos[-1][0] if anos else None)
    if not alvo:
        raise RuntimeError("pasta das tabelas de salário sem links por ano")
    doc = s.get(f"{DOCS}/{alvo}", timeout=60).text
    pdfs = re.findall(r'href="(https?://[^"]+/uploads/[a-f0-9]+\.pdf)"', doc)
    if not pdfs:
        raise RuntimeError("PDF da tabela de salários não encontrado")
    r = s.get(pdfs[0], timeout=120)
    r.raise_for_status()
    txt = "\n".join(p.extract_text() or "" for p in pypdf.PdfReader(io.BytesIO(r.content)).pages)
    lei = re.search(r"atualizada de acordo com a\s+Lei n[ºo°]\s*([\d.]+)\s+de\s+(\d+ de \w+ de \d{4})", txt)
    tab = {}
    for seg in re.split(r"S[ÍI]MBOLO", txt)[1:]:
        seg = re.split(r"TABELA [IVX]+", seg)[0]
        sims = [simb(m) for m in re.findall(r"\b[A-Z]{3,5} ?\.\d{2}\.\d{1,2}\b", seg)]
        sims = [x for x in sims if x.split(".")[0] in COMISSAO]
        vals = [float(v.replace(".", "").replace(",", ".")) for v in re.findall(r"\b\d{1,3}(?:\.\d{3})*,\d{2}\b", seg)]
        for k, v in zip(sims, vals):
            tab.setdefault(k, v)
    # conferência: o último nível de assessor de gabinete é sempre o maior
    plap = [tab.get(f"PLAP.06.{i}") for i in range(1, 21)]
    if None in plap or plap != sorted(plap):
        raise RuntimeError("tabela de salários lida fora de ordem — não usada")
    return tab, pdfs[0], (f"Lei nº {lei.group(1)}, de {lei.group(2)}" if lei else None)


def diarias_declaradas():
    """A consulta de diárias da ALEMS exporta CSV por ano; em meses sem diária ela
    escreve "Não houve despesa com a concessão de diárias nesse período"."""
    out = {}
    for ano in range(ANO - 3, ANO + 1):
        r = requests.get("https://transparencia2.al.ms.gov.br/consulta-diarias/exportar-csv", params={"ano": ano},
                         headers=UA, timeout=90)
        r.raise_for_status()
        linhas = r.content.decode("utf-8-sig", "replace").splitlines()
        sem = sum("Não houve" in l for l in linhas)
        valores = [float(v.replace(".", "").replace(",", ".")) for l in linhas if "Não houve" not in l
                   for v in re.findall(r"\b\d{1,3}(?:\.\d{3})*,\d{2}\b", l)]
        out[str(ano)] = {"mesesSemDiarias": sem, "linhas": len(linhas), "totalEncontrado": round(sum(valores), 2)}
    return out


def main():
    print("🏛️  Servidores da ALEMS")
    try:
        linhas, total, atualizado = servidores()
    except Exception as e:
        print(f"❌ consulta de servidores: {e} — arquivo anterior mantido")
        sys.exit(1)
    if total and len(linhas) < 0.9 * total:
        print(f"❌ só {len(linhas)} de {total} servidores — arquivo anterior mantido")
        sys.exit(1)
    try:
        tab, url_tab, lei = tabela_salarios()
        print(f"  tabela de salários: {len(tab)} símbolos ({lei})")
    except Exception as e:
        print(f"  ⚠️ tabela de salários: {e}")
        try:
            ant = json.load(open(SAIDA, encoding="utf-8"))
            tab, url_tab, lei = ant.get("tabelaSalarios") or {}, ant.get("fonteTabela"), ant.get("leiTabela")
        except Exception:
            tab, url_tab, lei = {}, None, None

    lista, grupos, niveis = [], {}, {}
    for x in linhas:
        s = simb(x.get("simbolo") or "")
        g = s.split(".")[0]
        venc = tab.get(s)
        lista.append({"matricula": x.get("matricula"), "nome": re.sub(r"\s+", " ", x.get("nome") or "").strip(),
                      "cargo": re.sub(r"\s+", " ", x.get("cargo") or "").strip(), "simbolo": s, "vencimento": venc})
        gr = grupos.setdefault(g, {"grupo": g, "descricao": GRUPOS.get(g, g), "quantidade": 0, "vencimentos": 0.0,
                                   "comissionado": g in COMISSAO})
        gr["quantidade"] += 1
        gr["vencimentos"] += venc or 0
        if g == "PLAP":
            n = niveis.setdefault(s, {"simbolo": s, "cargo": lista[-1]["cargo"], "vencimento": venc, "quantidade": 0})
            n["quantidade"] += 1
    for g in grupos.values():
        g["vencimentos"] = round(g["vencimentos"], 2)
    deputados = 24
    plap = grupos.get("PLAP", {}).get("quantidade", 0)
    out = {"ano": ANO, "ultimaAtualizacao": datetime.now().isoformat(timespec="seconds"),
           "fonte": CONSULTA, "fonteTabela": url_tab, "leiTabela": lei, "atualizadoNaFonte": atualizado,
           "total": len(lista), "comissionados": sum(g["quantidade"] for g in grupos.values() if g["comissionado"]),
           "assessoresGabinete": plap, "deputados": deputados, "mediaPorGabinete": round(plap / deputados, 1),
           "vencimentosComissionadosMes": round(sum(g["vencimentos"] for g in grupos.values() if g["comissionado"]), 2),
           "grupos": sorted(grupos.values(), key=lambda g: -g["quantidade"]),
           "niveisGabinete": sorted(niveis.values(), key=lambda n: int(n["simbolo"].split(".")[-1])),
           "tabelaSalarios": tab, "servidores": lista}
    try:
        out["diarias"] = diarias_declaradas()
        out["fonteDiarias"] = "https://transparencia2.al.ms.gov.br/consulta-diarias"
        print("  diárias declaradas: " + ", ".join(f"{a}: {d['mesesSemDiarias']} meses sem diárias" for a, d in out["diarias"].items()))
    except Exception as e:
        print(f"  ⚠️ consulta de diárias: {e}")
    SAIDA.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"  {len(lista)} servidores · {plap} assessores de gabinete (~{out['mediaPorGabinete']} por deputado) · "
          f"vencimento-base dos comissionados R$ {out['vencimentosComissionadosMes']:,.2f}/mês")
    print(f"✅ {SAIDA.relative_to(ROOT)} ({SAIDA.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
