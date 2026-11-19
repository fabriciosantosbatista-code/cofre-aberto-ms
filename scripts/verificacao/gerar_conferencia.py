#!/usr/bin/env python3
"""
Cofre Aberto MS — lista para conferência manual dos supersalários no contracheque original

Lê a folha completa (folha_completa/folha_supersalarios.jsonl.gz, fora do Git, sem CPF; não vira artefato público) e gera
dados/verificacao/conferencia_manual.csv com três grupos (coluna "grupo"):

  supersalario   todos os contracheques com LÍQUIDO acima do teto, do maior excedente para o menor;
                 "prioridade" = S nos 30 maiores e nos 3 maiores de cada órgão (por onde começar)
  intermediario  100 sorteados entre os que têm bruto acima do teto mas líquido abaixo (estima quantos também passam)
  amostra        100 sorteados entre os que têm bruto abaixo do teto
Sorteio aleatório simples estratificado por órgão, proporcional ao tamanho de cada órgão no grupo, semente fixa 42
(reproduzível: a mesma folha gera a mesma lista).

Colunas: grupo, prioridade, nome, orgao, mes, bruto, total_remuneratorio, total_indenizatorio, teto_aplicado, excedente,
link_contracheque_original, conferido (S = confere com o contracheque, N = erro; vazio = não conferido), observacao.
Nenhuma fonte tem endereço por pessoa: o link leva à consulta da fonte original e a observação diz os filtros.
Se o CSV já existe, "conferido" e "observacao" preenchidos são mantidos para o mesmo contracheque.

Uso: python3 scripts/verificacao/gerar_conferencia.py [--folha ARQUIVO] [--semente 42]
"""

import csv, gzip, json, random, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts" / "verificacao"))
from checagem_automatica import FOLHA, arg, mes_iso, unidade  # noqa: E402

SAIDA = ROOT / "dados" / "verificacao" / "conferencia_manual.csv"
TETO = 46366.19
COLUNAS = ["grupo", "prioridade", "nome", "orgao", "mes", "bruto", "total_remuneratorio", "total_indenizatorio", "teto_aplicado",
           "excedente", "link_contracheque_original", "conferido", "observacao"]


def fonte_original(p):
    """(link, observação) para chegar ao contracheque na fonte original."""
    oid, mes, nome = p.get("orgaoId"), p.get("mes") or "", p.get("nome") or ""
    iso = mes_iso(mes)
    if oid in ("tjms", "trt24", "trems"):
        trib = {"tjms": "TJMS", "trt24": "TRT24", "trems": "TRE-MS"}[oid]
        return (f"https://dadosjusbr.org/orgao/{oid}/{iso[:4]}/{int(iso[5:])}",
                f"Contracheque enviado pelo {trib} ao CNJ (Anexo VIII, {mes}): baixar a planilha do mês no DadosJusBr ou no portal "
                f"de transparência do {trib} e buscar \"{nome}\"")
    if oid == "governo":
        return ("https://www.transparencia.ms.gov.br/",
                f"Portal da Transparência MS › Pessoal › Folha de pagamento · competência {mes} · órgão {p.get('orgaoSigla')} · "
                f"buscar \"{nome}\"" + (f" (matrícula {p['matricula']})" if p.get("matricula") else ""))
    if oid == "tce":
        membro = "membros" in (p.get("orgao") or "")
        return (f"https://transparencia.tce.ms.gov.br/gestao-pessoas/{'membros' if membro else 'rendimentos'}",
                f"Portal do TCE-MS › Gestão de pessoas › {'Membros (PDF com o contracheque detalhado)' if membro else 'Rendimentos'} · "
                f"ano {iso[:4]}, mês {int(iso[5:])} · buscar \"{nome}\"" + (f" (matrícula {p['matricula']})" if p.get("matricula") else ""))
    if oid == "camara-cg":
        return ("http://45.225.6.93:8079/transparencia/",
                f"Portal da Câmara de Campo Grande (Fiorilli) › Pessoal › Folha de pagamento · {mes} · buscar \"{nome}\"")
    return ("", "fonte sem consulta conhecida")


def indenizatorio(p):
    """Soma das rubricas classificadas como indenização (só no Judiciário, pelo DadosJusBr); None quando a fonte não separa."""
    if p.get("orgaoId") in ("tjms", "trt24", "trems") and p.get("itens"):
        return round(sum(i["valor"] for i in p["itens"] if (i.get("categoria") or "").startswith("indeniza")), 2)
    return None


def sorteio(pessoas, n, semente):
    """Amostra aleatória simples estratificada por órgão, alocação proporcional (maiores restos), sem reposição."""
    if len(pessoas) <= n:
        return list(pessoas)
    rng = random.Random(semente)
    por = {}
    for p in sorted(pessoas, key=lambda p: (unidade(p), p.get("matricula") or "", p.get("nome") or "")):
        por.setdefault(unidade(p), []).append(p)
    cota = {o: n * len(v) / len(pessoas) for o, v in por.items()}
    alvo = {o: int(c) for o, c in cota.items()}
    for o in sorted(cota, key=lambda o: -(cota[o] - alvo[o]))[: n - sum(alvo.values())]:
        alvo[o] += 1
    out = []
    for o in sorted(por):
        out += rng.sample(por[o], alvo[o])
    return out


def linha(p, grupo, prioridade=""):
    ind = indenizatorio(p)
    link, obs = fonte_original(p)
    exc = (p["liquido"] if grupo == "supersalario" else p["bruto"]) - TETO
    return {"grupo": grupo, "prioridade": prioridade, "nome": p.get("nome"), "orgao": unidade(p), "mes": p.get("mes"),
            "bruto": f"{p['bruto']:.2f}", "total_remuneratorio": "" if ind is None else f"{p['bruto'] - ind:.2f}",
            "total_indenizatorio": "" if ind is None else f"{ind:.2f}", "teto_aplicado": f"{TETO:.2f}", "excedente": f"{max(0, exc):.2f}",
            "link_contracheque_original": link, "conferido": "", "observacao": obs}


def main():
    global SAIDA
    SAIDA = Path(arg("--saida", SAIDA))
    arq, semente = Path(arg("--folha", FOLHA)), int(arg("--semente", 42))
    if not arq.exists():
        print(f"❌ folha completa não encontrada ({arq}) — baixe o artefato folha-supersalarios do robô")
        return 1
    folha = [json.loads(l) for l in gzip.open(arq, "rt", encoding="utf-8") if l.strip()]
    sup = sorted((p for p in folha if p["liquido"] > TETO), key=lambda p: -(p["liquido"] - TETO))
    inter = [p for p in folha if p["bruto"] > TETO and p["liquido"] <= TETO]
    abaixo = [p for p in folha if p["bruto"] <= TETO]
    prio = {id(p) for p in sup[:30]}
    por = {}
    for p in sup:
        por.setdefault(unidade(p), []).append(p)
    for v in por.values():
        prio |= {id(p) for p in v[:3]}
    linhas = [linha(p, "supersalario", "S" if id(p) in prio else "N") for p in sup]
    linhas += [linha(p, "intermediario") for p in sorted(sorteio(inter, 100, semente), key=lambda p: -p["bruto"])]
    linhas += [linha(p, "amostra") for p in sorted(sorteio(abaixo, 100, semente), key=lambda p: -p["bruto"])]
    # mantém o que já foi conferido (mesmo grupo, nome, órgão e mês)
    chave = lambda x: (x["grupo"], x["nome"], x["orgao"], x["mes"])
    antes = {}
    if SAIDA.exists():
        with open(SAIDA, encoding="utf-8") as f:
            antes = {chave(x): x for x in csv.DictReader(f)}
    mantidas = 0
    for x in linhas:
        a = antes.get(chave(x))
        if a and (a.get("conferido") or "").strip():
            x["conferido"], x["observacao"] = a["conferido"].strip().upper(), a.get("observacao") or x["observacao"]
            mantidas += 1
    SAIDA.parent.mkdir(parents=True, exist_ok=True)
    with open(SAIDA, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUNAS)
        w.writeheader()
        w.writerows(linhas)
    print(f"✅ {SAIDA}: {len(sup)} supersalários ({len(prio)} prioritários), "
          f"{min(100, len(inter))} intermediários (de {len(inter)}), {min(100, len(abaixo))} da amostra (de {len(abaixo):,}) · "
          f"{mantidas} conferência(s) já preenchida(s) mantida(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
