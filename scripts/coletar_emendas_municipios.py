#!/usr/bin/env python3
"""
Cofre Aberto MS — Emendas parlamentares: para onde o dinheiro foi em MS

Fonte: Portal da Transparência do Governo Federal (CGU), arquivo completo de
emendas parlamentares, tabela "por favorecido" — cada pagamento de emenda com
quem recebeu (prefeitura, entidade ou empresa), o município e o mês.
Download público, sem chave:
  https://portaldatransparencia.gov.br/download-de-dados/emendas-parlamentares/UNICO

A API que o site já usava (dados/emendas_ms.json) registra a maior parte das
emendas como "MÚLTIPLO" — este arquivo mostra o município de verdade.

Gera dados/emendas_municipios.json com, para o ano de referência (mês do pagamento):
  municipios   quanto cada município de MS recebeu, de quais autores e quem recebeu
  autores      cada autor de emenda que mandou dinheiro para MS (os 11 atuais de
               MS marcados), com a divisão por município e os favorecidos
  favorecidos  as entidades e empresas de MS que mais receberam (para as páginas
               de empresa e as Conexões)

Uso:  python3 scripts/coletar_emendas_municipios.py [caminho_do_zip]
"""

import csv, io, json, re, sys, unicodedata, zipfile
from datetime import datetime
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent))
from ano_ref import ano_referencia  # noqa: E402

ROOT = Path(__file__).parent.parent
DADOS = ROOT / "dados"
SAIDA = DADOS / "emendas_municipios.json"
URL = "https://portaldatransparencia.gov.br/download-de-dados/emendas-parlamentares/UNICO"
ANO = ano_referencia()


def norm(t):
    t = unicodedata.normalize("NFD", str(t or "")).encode("ascii", "ignore").decode().upper()
    return re.sub(r"\s+", " ", t).strip()


def valor(t):
    try:
        return float(str(t).replace(".", "").replace(",", "."))
    except ValueError:
        return 0.0


def titulo(t):
    """'CAMPO GRANDE' → 'Campo Grande' (preposições minúsculas)."""
    out = []
    for i, p in enumerate(str(t or "").lower().split()):
        out.append(p if i and p in ("de", "da", "do", "das", "dos", "e") else p[:1].upper() + p[1:])
    return " ".join(out)


def parlamentares_atuais():
    atuais = {}
    for arq, chave, cargo in (("deputados_federais_ms.json", "deputados", "Deputado(a) federal"),
                              ("senadores_ms.json", "senadores", "Senador(a)")):
        try:
            for p in json.load(open(DADOS / arq, encoding="utf-8")).get(chave, []):
                atuais[norm(p["nome"])] = {"nome": p["nome"], "cargo": cargo, "partido": p.get("partido"),
                                           "grupo": "federal" if chave == "deputados" else "senador"}
        except Exception:
            pass
    return atuais


def baixar(caminho=None):
    if caminho:
        return zipfile.ZipFile(caminho)
    r = requests.get(URL, timeout=600, headers={"User-Agent": "Mozilla/5.0 (CofreAbertoMS)"})
    r.raise_for_status()
    return zipfile.ZipFile(io.BytesIO(r.content))


def main():
    print(f"🏛️  Emendas parlamentares por município — MS {ANO}")
    try:
        z = baixar(sys.argv[1] if len(sys.argv) > 1 else None)
        nome = next(n for n in z.namelist() if n.endswith("_PorFavorecido.csv"))
    except Exception as e:
        print(f"❌ download/arquivo: {e} — arquivo anterior mantido")
        sys.exit(1)
    atuais = parlamentares_atuais()

    municipios, autores, favorecidos = {}, {}, {}
    total_ms, linhas, ultimo_mes = 0.0, 0, ""
    with z.open(nome) as f:
        r = csv.reader(io.TextIOWrapper(f, encoding="latin-1", newline=""), delimiter=";")
        cab = next(r)
        ix = {c: i for i, c in enumerate(cab)}
        for row in r:
            anomes = row[ix["Ano/Mês"]]
            if not anomes.startswith(str(ANO)):
                continue
            autor = row[ix["Nome do Autor da Emenda"]].strip()
            uf = row[ix["UF Favorecido"]].strip()
            k_autor = norm(autor)
            eh_atual = k_autor in atuais
            if uf != "MS" and not eh_atual:
                continue
            v = valor(row[ix["Valor Recebido"]])
            if not v:
                continue
            linhas += 1
            ultimo_mes = max(ultimo_mes, anomes)
            mun = titulo(row[ix["Município Favorecido"]]) or "—"
            doc = re.sub(r"\D", "", row[ix["Código do Favorecido"]])
            fav = re.sub(r"\s+", " ", row[ix["Favorecido"]]).strip()
            natureza = row[ix["Natureza Jurídica"]].strip()
            tipo_emenda = row[ix["Tipo de Emenda"]].strip()
            tipo_emenda = ("Emenda Pix (transferência especial)" if "Especiais" in tipo_emenda
                           else "Bancada" if "Bancada" in tipo_emenda
                           else "Comissão" if "Comiss" in tipo_emenda
                           else "Individual (finalidade definida)" if "Individual" in tipo_emenda else tipo_emenda)
            info = atuais.get(k_autor)
            a = autores.setdefault(k_autor, {"autor": info["nome"] if info else titulo(autor), "atual": bool(info),
                                             "cargo": info["cargo"] if info else None,
                                             "partido": info["partido"] if info else None,
                                             "grupo": info["grupo"] if info else None,
                                             "totalMS": 0.0, "totalBR": 0.0, "municipios": {}, "favorecidos": {},
                                             "tipos": {}, "foraDeMS": {}})
            a["totalBR"] += v
            if uf != "MS":
                a["foraDeMS"][uf or "—"] = a["foraDeMS"].get(uf or "—", 0) + v
                continue
            total_ms += v
            a["totalMS"] += v
            a["municipios"][mun] = a["municipios"].get(mun, 0) + v
            a["tipos"][tipo_emenda] = a["tipos"].get(tipo_emenda, 0) + v
            kf = doc or fav
            af = a["favorecidos"].setdefault(kf, {"nome": fav, "doc": doc, "municipio": mun, "valor": 0.0})
            af["valor"] += v

            m = municipios.setdefault(mun, {"municipio": mun, "total": 0.0, "autores": {}, "favorecidos": {}, "tipos": {}})
            m["total"] += v
            m["autores"][a["autor"]] = m["autores"].get(a["autor"], 0) + v
            m["tipos"][tipo_emenda] = m["tipos"].get(tipo_emenda, 0) + v
            mf = m["favorecidos"].setdefault(kf, {"nome": fav, "doc": doc, "natureza": natureza, "valor": 0.0})
            mf["valor"] += v

            g = favorecidos.setdefault(kf, {"nome": fav, "doc": doc, "natureza": natureza, "municipio": mun,
                                            "valor": 0.0, "autores": {}})
            g["valor"] += v
            g["autores"][a["autor"]] = g["autores"].get(a["autor"], 0) + v

    if not linhas:
        print("❌ nenhum pagamento de emenda para MS no ano — arquivo anterior mantido")
        sys.exit(1)

    def top(d, n=None, campo="valor"):
        lst = sorted(d.values(), key=lambda x: -x[campo])
        for x in lst:
            x[campo] = round(x[campo], 2)
        return lst[:n] if n else lst

    def pares(d, chave, n=None):
        lst = [{chave: k, "valor": round(v, 2)} for k, v in sorted(d.items(), key=lambda kv: -kv[1])]
        return lst[:n] if n else lst

    lista_m = []
    for m in municipios.values():
        lista_m.append({"municipio": m["municipio"], "total": round(m["total"], 2),
                        "autores": [{**x, "atual": norm(x["autor"]) in atuais} for x in pares(m["autores"], "autor")],
                        "tipos": pares(m["tipos"], "tipo"), "favorecidos": top(m["favorecidos"], 15)})
    lista_m.sort(key=lambda m: -m["total"])

    lista_a = []
    for a in autores.values():
        if a["totalMS"] <= 0:
            continue
        lista_a.append({**{k: a[k] for k in ("autor", "atual", "cargo", "partido", "grupo")},
                        "totalMS": round(a["totalMS"], 2), "totalBR": round(a["totalBR"], 2),
                        "municipios": pares(a["municipios"], "municipio"), "tipos": pares(a["tipos"], "tipo"),
                        "favorecidos": top(a["favorecidos"], 20), "foraDeMS": pares(a["foraDeMS"], "uf")})
    lista_a.sort(key=lambda a: (not a["atual"], -a["totalMS"]))

    fav = top(favorecidos, 400)
    for f in fav:
        f["autores"] = pares(f["autores"], "autor")

    out = {"ano": ANO, "ultimaAtualizacao": datetime.now().isoformat(timespec="seconds"), "fonte": URL,
           "mesMaisRecente": f"{ultimo_mes[4:]}/{ultimo_mes[:4]}" if ultimo_mes else None,
           "totalMS": round(total_ms, 2), "pagamentos": linhas, "totalMunicipios": len(lista_m),
           "municipios": lista_m, "autores": lista_a, "favorecidos": fav}
    SAIDA.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    atuais_ms = sum(a["totalMS"] for a in lista_a if a["atual"])
    print(f"  {linhas} pagamentos · R$ {total_ms:,.2f} recebidos em MS ({len(lista_m)} municípios) · "
          f"parlamentares atuais de MS: R$ {atuais_ms:,.2f} · último mês {out['mesMaisRecente']}")
    print(f"✅ {SAIDA.relative_to(ROOT)} ({SAIDA.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
