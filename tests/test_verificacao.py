#!/usr/bin/env python3
"""
Cofre Aberto MS — testes do fluxo de conferência de Supersalários (scripts/verificacao/), com folha sintética

  checagem_automatica  duplicidade, rubricas, líquido, faixa, variação mês a mês; CPF na folha → para (código 1)
  gerar_conferencia    grupos supersalario / intermediario / amostra, prioridade, sorteio reproduzível (semente 42),
                       estratificado por órgão, e o que já foi conferido é mantido
  resumo_conferencia   contagens e Clopper–Pearson (0 erros em 100 → ≈ 2,95%)

Uso: python3 tests/test_verificacao.py   (código 1 se algum teste falhar)
"""
import csv, gzip, json, subprocess, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
V = ROOT / "scripts" / "verificacao"
sys.path.insert(0, str(V))
import resumo_conferencia as rc  # noqa: E402

oks, erros = [], []


def check(c, m):
    (oks if c else erros).append(m)


TETO = 46366.19


def pessoa(i, org, bruto, liquido, **kw):
    p = {"nome": f"Pessoa {i}", "matricula": str(1000 + i), "cargo": "Cargo", "lotacao": "L", "orgao": f"Governo MS — {org}", "orgaoId": "governo",
         "orgaoSigla": org, "situacao": "Ativo", "mes": "10/2026", "base": bruto, "outras": 0.0, "bruto": bruto,
         "descontos": round(max(0, bruto - liquido), 2), "liquido": liquido, "itens": []}
    p.update(kw)
    return p


def folha(pessoas, tmp, nome="folha.jsonl.gz"):
    arq = Path(tmp) / nome
    with gzip.open(arq, "wt", encoding="utf-8") as f:
        for p in pessoas:
            f.write(json.dumps(p, ensure_ascii=False) + "\n")
    return arq


def roda(script, *args):
    return subprocess.run([sys.executable, str(V / script), *map(str, args)], capture_output=True, text=True)


with tempfile.TemporaryDirectory() as tmp:
    saida = Path(tmp) / "saida"
    ps = [pessoa(i, "SEFAZ" if i % 2 else "SED", 5000 + i, 4000 + i) for i in range(300)]
    ps += [pessoa(900 + i, "SEFAZ", 90000 + i, 60000 + i) for i in range(40)]      # líquido acima do teto
    ps += [pessoa(950 + i, "SED", 60000 + i, 40000) for i in range(150)]           # bruto acima, líquido abaixo
    ps.append(pessoa(1, "SEFAZ", 5001, 4001))                                       # matrícula repetida
    ps.append(pessoa(7000, "SED", 600000, 400000))                                  # bruto > 500 mil
    ps.append(pessoa(7001, "SED", 3000, 2000, outras=-50.0))                        # valor negativo
    ps.append(pessoa(7002, "SED", 3000, 3500))                                      # líquido maior que o bruto (Governo)
    ps.append(pessoa(7004, "SED", 45000, 30000, outras=-2000.0))                    # sem o estorno, o bruto passaria do teto
    ps.append({**pessoa(7003, "X", 50000, 30000), "orgao": "TJMS — Tribunal de Justiça", "orgaoId": "tjms", "orgaoSigla": None,
               "matricula": None, "base": 30000, "itens": [{"item": "a", "valor": 10000}], "descontos": 20000})  # rubricas ≠ bruto
    arq = folha(ps, tmp)
    r = roda("checagem_automatica.py", "--folha", arq, "--saida", saida)
    al = list(csv.DictReader(open(saida / "alertas_2026-10.csv", encoding="utf-8"))) if (saida / "alertas_2026-10.csv").exists() else []
    tipos = {a["tipo"] for a in al}
    check(r.returncode == 0, f"checagem roda ({r.stdout.strip()[-120:]})")
    check(sum(1 for a in al if a["tipo"] == "duplicidade") == 2, "duplicidade: a matrícula repetida no mesmo órgão e mês gera alerta (as 2 linhas)")
    check(any(a["tipo"] == "faixa" and "500" in a["detalhe"] for a in al), "faixa: bruto acima de R$ 500 mil")
    check(any(a["tipo"] == "faixa" and "negativo" in a["detalhe"] for a in al), "faixa: valor negativo")
    check(any(a["tipo"] == "liquido" and "maior que o bruto" in a["detalhe"] for a in al), "Governo: líquido maior que o bruto")
    check(any(a["tipo"] == "rubricas" for a in al), "Judiciário: bruto diferente de base + rubricas")
    check(any(a["tipo"] == "estorno_cruza_teto" and "passa" in a["detalhe"] and "bruto" in a["detalhe"] for a in al),
          "estorno: sem ele o bruto cruzaria o teto → alerta")
    check(not any(a["tipo"] == "estorno_cruza_teto" and "7001" in (a["matricula"] or "") for a in al), "estorno pequeno que não cruza o teto: sem alerta")
    res = json.load(open(saida / "checagem_2026-10.json", encoding="utf-8"))
    check("rubricas" in res["porOrgao"]["TJMS — Tribunal de Justiça"]["checagens"] and "rubricas" not in res["porOrgao"]["Governo MS — SED"]["checagens"],
          "o JSON registra quais checagens foram aplicadas em cada órgão (rubricas só onde há)")
    check("total_externo do Governo do Estado" in res["naoAplicadas"], "o que não foi aplicado fica registrado com o motivo")
    # variação: mês seguinte com metade das pessoas da SEFAZ
    ps2 = [{**p, "mes": "11/2026"} for p in ps if not (p["orgaoSigla"] == "SEFAZ" and int(p["matricula"]) % 4 == 1)]
    roda("checagem_automatica.py", "--folha", folha(ps2, tmp, "f2.jsonl.gz"), "--saida", saida)
    al2 = list(csv.DictReader(open(saida / "alertas_2026-11.csv", encoding="utf-8")))
    check(any(a["tipo"] == "variacao" and "SEFAZ" in a["orgao"] for a in al2), "variação > 15% de pessoas no órgão em relação ao mês anterior")
    # CPF na folha → para
    r = roda("checagem_automatica.py", "--folha", folha([{**ps[0], "cpf": "x"}], tmp, "f3.jsonl.gz"), "--saida", saida)
    check(r.returncode == 1, "campo de CPF na folha → checagem para (o artefato não sobe)")
    d = [5, 2, 9, 9, 8, 2, 2, 4, 7]
    for n in (9, 10):
        d.append((sum(d[i] * (n + 1 - i) for i in range(n)) * 10) % 11 % 10)
    cpf = "".join(map(str, d))
    r = roda("checagem_automatica.py", "--folha", folha([{**ps[0], "nome": f"Fulano CPF {cpf[:3]}.{cpf[3:6]}.{cpf[6:9]}-{cpf[9:]}"}], tmp, "f4.jsonl.gz"), "--saida", saida)
    check(r.returncode == 1, "CPF completo no texto da folha → checagem para")

    # conferência manual
    csvp = Path(tmp) / "conf.csv"
    r = roda("gerar_conferencia.py", "--folha", arq, "--saida", csvp)
    ls = list(csv.DictReader(open(csvp, encoding="utf-8")))
    g = lambda n: [x for x in ls if x["grupo"] == n]
    sup = g("supersalario")
    check(len(sup) == 41 and all(float(x["excedente"]) > 0 for x in sup), "supersalario = todos com líquido acima do teto (40 + o de R$ 600 mil)")
    check([float(x["excedente"]) for x in sup] == sorted((float(x["excedente"]) for x in sup), reverse=True), "supersalario em ordem decrescente de excedente")
    check(sum(1 for x in sup if x["prioridade"] == "S") == 30, "prioridade = 30 maiores + 3 por órgão (aqui um órgão só)")
    check(len(g("intermediario")) == 100 and len(g("amostra")) == 100, "100 intermediários e 100 da amostra")
    inter = {x["nome"] for x in g("intermediario")}
    check(all(950 <= int(n.split()[1]) < 1100 or int(n.split()[1]) == 7003 for n in inter), "intermediario só entre bruto acima e líquido abaixo do teto")
    org_am = {x["orgao"] for x in g("amostra")}
    check(org_am == {"Governo MS — SEFAZ", "Governo MS — SED"}, "amostra estratificada (os dois órgãos aparecem)")
    check(all(x["link_contracheque_original"] and "buscar" in x["observacao"] for x in ls), "toda linha tem link da fonte original e os filtros na observação")
    primeira = open(csvp, encoding="utf-8").read()
    roda("gerar_conferencia.py", "--folha", arq, "--saida", csvp)
    check(open(csvp, encoding="utf-8").read() == primeira, "sorteio reproduzível: mesma folha e semente = mesma lista")
    # preenche e regera: o que foi conferido fica
    ls[0]["conferido"], ls[-1]["conferido"] = "S", "N"
    with open(csvp, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(ls[0].keys()))
        w.writeheader()
        w.writerows(ls)
    roda("gerar_conferencia.py", "--folha", arq, "--saida", csvp)
    ls2 = list(csv.DictReader(open(csvp, encoding="utf-8")))
    check(ls2[0]["conferido"] == "S" and ls2[-1]["conferido"] == "N", "regerar a lista mantém o que já foi conferido")
    # resumo
    rj = Path(tmp) / "resumo.json"
    for x in ls2:
        if x["grupo"] == "amostra":
            x["conferido"] = "S"
    with open(csvp, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(ls2[0].keys()))
        w.writeheader()
        w.writerows(ls2)
    roda("resumo_conferencia.py", "--csv", csvp, "--saida", rj)
    R = json.load(open(rj, encoding="utf-8"))["grupos"]
    check(R["amostra"]["conferidos"] == 100 and R["amostra"]["comErro"] == 0 and abs(R["amostra"]["limiteSuperior95"] - 0.0295) < 0.0005,
          f"amostra: 0 erros em 100 → limite superior 95% ≈ 2,95% ({R['amostra']['limiteSuperior95']})")
    check(R["supersalario"]["conferidos"] == 1 and R["supersalario"]["comErro"] == 0 and R["supersalario"]["pendentes"] == 40, "contagem por grupo")
check(abs(rc.clopper_pearson_sup(1, 100) - 0.0466) < 0.0005 and abs(rc.clopper_pearson_sup(0, 30) - 0.0950) < 0.0005, "Clopper–Pearson: 1/100 ≈ 4,66%; 0/30 ≈ 9,5%")

print(f"✅ {len(oks)} checagens OK · ❌ {len(erros)} erros")
for e in erros:
    print("❌", e)
sys.exit(1 if erros else 0)
