#!/usr/bin/env python3
"""
Cofre Aberto MS — versões leves dos dados para o painel (roda na coleta diária)

O painel baixava ~3,8 MB só para abrir (2,6 MB eram dos deputados estaduais,
mesmo para quem nunca abre essa aba) e 4,3 MB na aba Prefeitura — lento num
4G fraco e pesado para o celular processar. Este script gera, em dados/painel/:

  camara_municipal.json        vereadores sem as notas; fotos como arquivo
  notas_vereadores.json        notas de cada vereador (baixado ao abrir um)
  deputados_estaduais_ms.json  idem, deputados estaduais
  notas_estaduais.json
  deputados_federais_ms.json   idem, deputados federais de MS
  notas_federais_ms.json
  prefeitura.json              totais, órgãos, 1.000 maiores fornecedores e as
                               300 despesas mais recentes; o arquivo completo
                               (dados/prefeitura.json) só é baixado na busca,
                               ao abrir um fornecedor ou ao paginar além disso

Os arquivos completos em dados/ continuam sendo a fonte de verdade (usados
pelas páginas, planilhas e análises); estes são só cópias enxutas.
"""

import json, re, unicodedata
from pathlib import Path

ROOT = Path(__file__).parent.parent
DADOS = ROOT / "dados"
SAIDA = DADOS / "painel"


def carregar(nome):
    try:
        return json.load(open(DADOS / nome, encoding="utf-8"))
    except Exception:
        return None


def salvar(nome, data):
    SAIDA.mkdir(parents=True, exist_ok=True)
    txt = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    path = SAIDA / nome
    if not path.exists() or path.read_text(encoding="utf-8") != txt:
        path.write_text(txt, encoding="utf-8")
    return len(txt.encode("utf-8"))


def slug(t):
    t = unicodedata.normalize("NFD", t or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", t).strip("-")


def foto_leve(grupo, nome, foto):
    """Troca a foto em base64 pelo arquivo já gravado em fotos/p/ (gerar_paginas_parlamentares.py)."""
    if isinstance(foto, str) and foto.startswith("data:image"):
        for ext in ("jpg", "jpeg", "png", "webp"):
            arq = ROOT / "fotos" / "p" / f"{grupo}-{slug(nome)}.{ext}"
            if arq.exists():
                return f"fotos/p/{arq.name}"
    return foto


def separa_notas(arquivo, lista_chave, grupo, campo_notas="despesas"):
    d = carregar(arquivo)
    if not d:
        return None, None
    notas, lista = {}, []
    for p in d.get(lista_chave, []):
        p = dict(p)
        n = p.pop(campo_notas, None) or []
        notas[p["nome"]] = n
        p["totalNotasFiscais"] = p.get("totalNotasFiscais") or len(n)
        p["foto"] = foto_leve(grupo, p["nome"], p.get("foto"))
        lista.append(p)
    return {**d, lista_chave: lista, "notasSeparadas": True}, notas


def prefeitura_leve():
    d = carregar("prefeitura.json")
    if not d:
        return None
    desp = d.get("despesas", [])
    forn = {}
    for x in desp:
        k = x.get("fornecedor") or "—"
        f = forn.setdefault(k, {"fornecedor": k, "cnpj": x.get("cnpj"), "total": 0.0, "notas": 0})
        f["total"] += x.get("valor") or 0
        f["notas"] += 1
    ranking = sorted(forn.values(), key=lambda f: -f["total"])
    for f in ranking:
        f["total"] = round(f["total"], 2)
    leve = {k: v for k, v in d.items() if k != "despesas"}
    leve.update({"fornecedores": ranking[:1000], "totalFornecedores": len(ranking),
                 "despesasRecentes": desp[:300], "notasSeparadas": True})
    return leve


def main():
    tam = {}
    for arquivo, chave, grupo, nome_notas in (("camara_municipal.json", "vereadores", "vereador", "notas_vereadores.json"),
                                              ("deputados_estaduais_ms.json", "vereadores", "estadual", "notas_estaduais.json"),
                                              ("deputados_federais_ms.json", "deputados", "federal", "notas_federais_ms.json")):
        leve, notas = separa_notas(arquivo, chave, grupo)
        if leve is not None:
            tam[arquivo] = salvar(arquivo, leve)
            tam[nome_notas] = salvar(nome_notas, notas)
    p = prefeitura_leve()
    if p is not None:
        tam["prefeitura.json"] = salvar("prefeitura.json", p)
    print("✅ dados/painel/: " + ", ".join(f"{k} {v // 1024} KB" for k, v in tam.items()))


if __name__ == "__main__":
    main()
