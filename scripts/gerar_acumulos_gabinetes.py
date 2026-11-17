#!/usr/bin/env python3
"""
Cofre Aberto MS — quem trabalha num gabinete da Câmara de Campo Grande e aparece em outra folha pública

Cruza, pelo nome completo, cada servidor dos gabinetes (dados/camara_municipal.json, gabinete.equipe) com:
  Estado de MS   o cruzamento da folha de ativos do Estado (dados/servidores_socios.json, "acumulos")
  ALEMS          a folha da Assembleia Legislativa (dados/alems_servidores.json)

As folhas da Câmara e da ALEMS não publicam CPF: só entram nomes de 3+ palavras que aparecem uma única vez em cada folha
(reduz homônimos). Bolsas (atleta, estudo) não são cargo e ficam de fora. Policial ou servidor cedido à Câmara é
cessão, não acúmulo — o site mostra o vínculo e avisa. É sinal de atenção, não acusação: a Constituição (art. 37, XVI)
permite alguns acúmulos e a cessão é legal.

Grava em cada servidor da equipe o campo "outroVinculo": [{orgao, cargo, vinculo, cessao}].
"""

import json, re, unicodedata
from collections import Counter
from pathlib import Path

DADOS = Path(__file__).parent.parent / "dados"


def norm(t):
    return re.sub(r"\s+", " ", "".join(c for c in unicodedata.normalize("NFD", (t or "").upper()) if unicodedata.category(c) != "Mn")).strip()


def carregar(nome):
    try:
        return json.load(open(DADOS / nome, encoding="utf-8"))
    except Exception:
        return {}


def main():
    cm = carregar("camara_municipal.json")
    if not cm.get("vereadores"):
        print("⚠️ sem camara_municipal.json")
        return
    alems = carregar("alems_servidores.json").get("servidores") or []
    n_alems = Counter(norm(s.get("nome")) for s in alems)
    alems_por = {norm(s.get("nome")): s for s in alems}
    estado = {}
    for x in carregar("servidores_socios.json").get("acumulos") or []:
        if "Câmara" in (x.get("outroOrgao") or ""):
            estado[norm(x["nome"])] = x
    todos = [x for v in cm["vereadores"] for x in (v.get("gabinete") or {}).get("equipe") or []]
    n_cam = Counter(norm(x.get("nome")) for x in todos)
    marcados = 0
    for x in todos:
        k = norm(x.get("nome"))
        x.pop("outroVinculo", None)
        if len(k.split()) < 3 or n_cam[k] != 1:
            continue
        out = []
        e_ = estado.get(k)
        if e_ and not re.search(r"BOLSA", (e_.get("estadoCargo") or "").upper()) and not re.search(r"BOLSIST|ESTAGI", (e_.get("estadoVinculo") or "").upper()):
            pol = re.search(r"SARGENT|SOLDAD|CABO|OFICIA|SUBTENENTE|POLIC|BOMBEIR", (e_.get("estadoCargo") or "").upper())
            out.append({"orgao": f"Governo de MS — {e_.get('estadoOrgao')}", "cargo": e_.get("estadoCargo"), "vinculo": e_.get("estadoVinculo"),
                        "cessao": bool(pol or re.search(r"CEDID", (x.get("cargo") or "").upper()))})
        if n_alems[k] == 1:
            s = alems_por[k]
            out.append({"orgao": "ALEMS (Assembleia Legislativa)", "cargo": (s.get("cargo") or "").capitalize(), "vinculo": "Comissionado",
                        "cessao": False})
        if out:
            x["outroVinculo"] = out
            marcados += 1
    (DADOS / "camara_municipal.json").write_text(json.dumps(cm, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✅ gabinetes da Câmara de CG: {marcados} de {len(todos)} servidores aparecem em outra folha pública (Estado/ALEMS)")


if __name__ == "__main__":
    main()
