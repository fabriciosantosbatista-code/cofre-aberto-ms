#!/usr/bin/env python3
"""
Cofre Aberto MS — atividade recente (faixa "atualizado" e "gastos novos da semana")

Guarda em dados/notas_vistas.json o dia em que cada nota fiscal dos parlamentares
de MS (vereadores de CG, deputados estaduais, deputados federais e senadores)
apareceu pela primeira vez nos nossos dados. A partir disso gera
dados/atividade.json com:
  - quando os dados foram atualizados e quantos registros o site tem;
  - quantas notas entraram hoje e nos últimos 7 dias;
  - quem lançou mais notas novas na semana (quantidade e valor).

Na primeira execução (sem notas_vistas.json) reconstrói essas datas pelo
histórico do git dos últimos 14 dias; sem histórico, marca tudo como antigo
(nada aparece como novo até a próxima coleta trazer notas de fato novas).
"""

import json, subprocess
from datetime import date, datetime, timedelta
from pathlib import Path

RAIZ = Path(__file__).parent.parent
DADOS = RAIZ / "dados"
VISTAS = DADOS / "notas_vistas.json"
SAIDA = DADOS / "atividade.json"
HOJE = date.today().isoformat()
FONTES = {"camara_municipal.json": ("vereador", "vereadores", "despesas"),
          "deputados_estaduais_ms.json": ("estadual", "vereadores", "despesas"),
          "deputados_federais_ms.json": ("federal", "deputados", "despesas"),
          "senadores_ms.json": ("senador", "senadores", "notasCeaps")}


def carregar(nome):
    try:
        return json.load(open(DADOS / nome, encoding="utf-8"))
    except Exception:
        return {}


def notas(arquivos):
    """{chave: nota} para os quatro arquivos; arquivos = {nome: conteúdo json}."""
    out = {}
    for nome, (grupo, lista, campo) in FONTES.items():
        for p in (arquivos.get(nome) or {}).get(lista, []):
            for n in p.get(campo) or []:
                try:
                    valor = round(float(n.get("valor") or 0), 2)
                except (TypeError, ValueError):
                    continue
                doc = str(n.get("nf") or n.get("doc") or n.get("documento") or "").strip()
                k = f"{grupo}|{p['nome']}|{n.get('data') or ''}|{valor:.2f}|{doc}|{(n.get('fornecedor') or '').strip()[:40]}"
                out[k] = {"grupo": grupo, "nome": p["nome"], "partido": p.get("partido"), "valor": valor, "data": (n.get("data") or "")[:10]}
    return out


# Dias em que notas entraram no site por mudança NOSSA no coletor, não por publicação da fonte. Essas notas contam
# como antigas ("antes"). 10 e 11/11/2026: o leitor de PDFs da Câmara de CG passou a ler os PDFs grandes por
# inteiro (commit 36a0f5f) e a reconhecer mais meses e totais (commit d6ccdd8) — ~260 notas de jun–set apareceram.
REPROCESSAMENTOS = {("vereador", "2026-11-10"), ("vereador", "2026-11-11")}


def carga_inicial(novas, vistas, atuais):
    """Quando um parlamentar ganha de uma vez mais de 30 notas e elas são mais de 60% das dele, é carga
    do ano inteiro (fonte nova ou formato novo), não gasto novo: essas notas ficam como "antes"."""
    tot, nov = {}, {}
    for k in atuais:
        q = tuple(k.split("|")[:2])
        tot[q] = tot.get(q, 0) + 1
    for k in novas:
        q = tuple(k.split("|")[:2])
        nov[q] = nov.get(q, 0) + 1
    em_massa = {q for q, n in nov.items() if n > 30 and n > 0.6 * tot[q]}
    return {k for k in novas if tuple(k.split("|")[:2]) in em_massa}


def reconstruir():
    """Primeira data em que cada nota aparece no histórico do git (últimos 14 dias)."""
    vistas = {}
    try:
        log = subprocess.run(["git", "log", "--since=14 days ago", "--reverse", "--format=%H %cs", "--", *[f"dados/{f}" for f in FONTES]],
                             cwd=RAIZ, capture_output=True, text=True, check=True).stdout.split("\n")
    except Exception:
        return vistas
    primeiro = True
    for linha in filter(None, log):
        sha, dia = linha.split()
        arqs = {}
        for f in FONTES:
            try:
                arqs[f] = json.loads(subprocess.run(["git", "show", f"{sha}:dados/{f}"], cwd=RAIZ, capture_output=True, text=True, check=True).stdout)
            except Exception:
                arqs[f] = None
        if any(v is None for v in arqs.values()):
            continue
        atuais = notas(arqs)
        novas = [k for k in atuais if k not in vistas]
        massa = carga_inicial(novas, vistas, atuais)
        for k in novas:
            vistas[k] = "antes" if primeiro or k in massa else dia
        primeiro = False
    return vistas


def main():
    atuais = notas({f: carregar(f) for f in FONTES})
    try:
        vistas = json.load(open(VISTAS, encoding="utf-8"))
    except Exception:
        vistas = reconstruir() or {k: "antes" for k in atuais}
        print(f"  notas_vistas: reconstruído pelo histórico ({len(vistas)} notas)")
    novas_hoje = [k for k in atuais if k not in vistas]
    massa = carga_inicial(novas_hoje, vistas, atuais)
    if massa:
        print(f"  {len(massa)} notas tratadas como carga inicial, não como novas")
    vistas = {k: vistas.get(k) or ("antes" if k in massa else HOJE) for k in atuais}  # só as notas que existem hoje
    vistas = {k: "antes" if (k.split("|")[0], d) in REPROCESSAMENTOS else d for k, d in vistas.items()}
    VISTAS.write_text(json.dumps(vistas, ensure_ascii=False, separators=(",", ":"), sort_keys=True), encoding="utf-8")

    desde = (date.today() - timedelta(days=6)).isoformat()
    # só gasto recente: nota publicada na semana com data do gasto de até 60 dias atrás. Notas antigas que a casa
    # publica com atraso (ex.: a Câmara de CG soltando junho a setembro de uma vez) não viram "gastos novos".
    recente = (date.today() - timedelta(days=60)).isoformat()
    publicadas = [k for k, d in vistas.items() if d != "antes" and d >= desde]
    novas = [k for k in publicadas if (atuais[k].get("data") or "") >= recente]
    atrasadas = len(publicadas) - len(novas)
    hoje = [k for k in novas if vistas[k] == HOJE]
    urls = carregar("paginas_index.json")
    por = {}
    for k in novas:
        n = atuais[k]
        x = por.setdefault((n["grupo"], n["nome"]), {"grupo": n["grupo"], "nome": n["nome"], "partido": n["partido"], "notas": 0, "valor": 0.0,
                                                     "url": urls.get(f"{n['grupo']}|{n['nome']}")})
        x["notas"] += 1
        x["valor"] += n["valor"]
        if n.get("data"):
            x["de"] = min(x.get("de") or n["data"], n["data"])
            x["ate"] = max(x.get("ate") or n["data"], n["data"])
    ranking = sorted(({**x, "valor": round(x["valor"], 2)} for x in por.values()), key=lambda x: (-x["notas"], -x["valor"]))

    gc, gl, pc = carregar("governo_ms_contratos.json"), carregar("governo_ms_licitacoes.json"), carregar("prefeitura_contratos.json")
    pref = carregar("prefeitura.json")
    registros = {"notas": len(atuais),
                 "contratos": len(gc.get("contratos") or []) + len(gc.get("obras") or []) + len(pc.get("contratos") or []),
                 "licitacoes": len(gl.get("compras") or []) + len(pc.get("licitacoes") or []),
                 "despesas": len(pref.get("despesas") or []) + len(carregar("governo_ms_credores.json").get("credores") or [])}
    status = carregar("status.json")
    SAIDA.write_text(json.dumps({
        "geradoEm": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "ultimaAtualizacao": status.get("ultimaAtualizacao"),
        "registros": sum(registros.values()), "registrosPorTipo": registros,
        "notasHoje": len(hoje), "valorHoje": round(sum(atuais[k]["valor"] for k in hoje), 2),
        "notasSemana": len(novas), "valorSemana": round(sum(atuais[k]["valor"] for k in novas), 2),
        "desde": desde, "semana": ranking[:12], "atrasadasSemana": atrasadas, "limiteGasto": recente}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"✅ atividade.json — {len(hoje)} notas novas hoje, {len(novas)} na semana, {sum(registros.values())} registros")


if __name__ == "__main__":
    main()
