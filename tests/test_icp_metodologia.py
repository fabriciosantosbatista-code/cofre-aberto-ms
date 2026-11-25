#!/usr/bin/env python3
"""
Cofre Aberto MS — testes da metodologia 2.0 do ICP (cobertura, nível de evidência, nota)

Cenários sintéticos (scripts/icp_metodologia.py):
  · 2 registros conferidos em 92 mil não dão nota máxima nem selo verde
  · 10 de 206 é conferência PARCIAL (nível 2), com cobertura de 4,85%
  · base integralmente conferida pode chegar ao nível 3 (e 4 com repetição em dias diferentes)
  · base sem conferência oficial não passa de 70 nem fica verde
  · integração quebrada (F < 50) limita a nota a 50
  · fonte sem publicação nova ≠ falha de coleta (só a falha tem teto 50)
  · denominador desconhecido nunca gera cobertura de 100% (cobertura "não calculada")
  · amostras repetidas não inflam a cobertura (a mesma contratação conta uma vez)
  · divergência reduz a precisão (≤ 40) e o limite estatístico
  · um único teste aprovado não vale integridade 100
Regressão com as 21 bases publicadas (dados/icp.json):
  · nota 2.0 reproduzida a partir das dimensões, cobertura e nível; nota geral com as 21 bases
  · cobertura reconstruída de forma independente a partir do histórico permanente das conferências
  · nível de evidência recalculado; verde só com nível ≥ 3; nenhuma base sem conferência acima de 70
  · histórico das notas: o retrato da metodologia 1.0 está preservado e nenhuma linha antiga foi apagada

Uso: python3 tests/test_icp_metodologia.py   (código 1 se algum teste falhar)
"""

import json, subprocess, sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import icp_metodologia as m  # noqa: E402
import validar_fontes as vf  # noqa: E402

oks, erros = [], []


def check(cond, msg):
    (oks if cond else erros).append(msg)


AGORA = datetime(2026, 11, 18, 12, 0)
H = lambda dias=0, **k: {"em": (AGORA - timedelta(days=dias)).strftime("%Y-%m-%dT%H:%M:%S"), "resultado": "confere", "fonteUrl": "https://fonte",
                         "comparados": [{"item": "x"}], "metodologia": "ICP 2.0", **k}
CHEIO = {"A": 100, "T": 100, "R": 100, "F": 100, "I": 100}


def avalia(hist, dims=None, classe="importado", integridade_ok=True, registros=None):
    cob = m.cobertura(hist, AGORA, registros)
    niv = m.nivel(cob, integridade_ok, hist, AGORA)
    d = {**(dims or CHEIO), "P": m.dim_P(cob)}
    return cob, niv, d, m.nota(d, classe, cob, niv)


# ── amostra de 2 em 92 mil (supersalários) ──
cob, niv, d, nt = avalia([H(granularidade="registro", unidadesBase=92796, idsConferidos=["a", "b"], registrosBase=92796, unidadesConferidas=2)])
check(nt < 100 and nt <= 71, f"2 de 92.796 conferidos → nota {nt} (não é máxima; teto de cobertura ≈ 70)")
check(niv == 2, "2 de 92.796 → nível 2 (conferência parcial), nunca verde")
check(d["P"] < 30, f"2 de 92.796 → precisão {d['P']} (o limite de 95% deixa até ~78% de erro possível)")

# ── 10 de 206 (aluguéis) ──
cob, niv, d, nt = avalia([H(granularidade="registro", unidadesBase=206, idsConferidos=[f"c{i}" for i in range(10)], registrosBase=206)])
check(niv == 2 and abs(cob["percentual"] - 4.85) < 0.01, f"10 de 206 → parcial, cobertura {cob['percentual']}%")
check(nt <= 72, f"10 de 206 → nota {nt} ≤ 70 + 30 × 4,85%")

# ── base integralmente conferida ──
cob, niv, d, nt = avalia([H(granularidade="registro", unidadesBase=206, idsConferidos=[f"c{i}" for i in range(206)], registrosBase=206)])
check(niv == 3 and cob["percentual"] == 100 and d["P"] == 100 and nt == 100, f"206 de 206 → nível 3, P 100, nota {nt}")
reforco = [H(0, granularidade="unidade", unidadesBase=25, unidadesConferidas=25, idsConferidos=[str(i) for i in range(25)], registrosBase=500, registrosAbrangidos=500),
           H(1, granularidade="unidade", unidadesBase=25, unidadesConferidas=25, idsConferidos=[str(i) for i in range(25)], registrosBase=500, registrosAbrangidos=500),
           H(2, granularidade="unidade", unidadesBase=25, unidadesConferidas=25, idsConferidos=[str(i) for i in range(25)], registrosBase=500, registrosAbrangidos=500)]
check(avalia(reforco)[1] == 4, "conferência abrangente repetida 3 vezes em 3 dias → nível 4 (reforçada)")
check(avalia(reforco[:1] * 3)[1] == 3, "3 conferências no MESMO dia não bastam para o nível 4")
perto = [dict(r, em=e) for r, e in zip(reforco, ("2026-11-17T21:40:00", "2026-11-18T01:02:00", "2026-11-18T01:40:00"))]
check(avalia(perto)[1] == 3, "conferências com 4 h de diferença, de datas diferentes (fuso/meia-noite), não contam como dias diferentes")
check(avalia([H(granularidade="total", unidadesBase=1, unidadesConferidas=1, idsConferidos=["total"], registrosBase=1000, registrosAbrangidos=1000)])[1] == 2,
      "um único total geral conferido → nível 2 (não localiza erros que se compensam)")

# ── sem conferência oficial ──
cob, niv, d, nt = avalia([])
check(cob is None and niv == 1 and d["P"] is None and nt == 70, f"sem conferência na fonte → nível 1, P não avaliada (vale 0), nota {nt} = máximo 70")
check(avalia([], integridade_ok=False, dims={"A": 100, "T": 100, "R": 100, "F": 100, "I": None})[1] == 0, "sem testes e sem conferência → nível 0")
check(avalia([H(40, granularidade="registro", unidadesBase=10, idsConferidos=list("abcdefghij"), registrosBase=10)])[0] is None,
      "conferência com mais de 30 dias não vale")

# ── integração quebrada ──
cob, niv, d, nt = avalia([H(granularidade="registro", unidadesBase=10, idsConferidos=list("abcdefghij"), registrosBase=10)], dims={**CHEIO, "F": 0})
check(nt <= 50, f"base conferida por inteiro mas integração quebrada (F = 0) → nota {nt} ≤ 50")
cob, niv, d, nt = avalia([H(granularidade="registro", unidadesBase=10, idsConferidos=list("abcdefghij"), registrosBase=10)], dims={**CHEIO, "F": 60})
check(nt > 50, f"integração com F = 60 não leva o teto de 50 (nota {nt})")

# ── sem publicação nova × falha de coleta ──
hist_ok = [H(granularidade="registro", unidadesBase=10, idsConferidos=list("abcdefghij"), registrosBase=10)]
_, _, _, n_aguardando = avalia(hist_ok, dims={**CHEIO, "A": 40}, classe="aguardando_fonte")
_, _, _, n_falha = avalia(hist_ok, dims={**CHEIO, "A": 0}, classe="falha_coleta")
check(n_aguardando > 50 and n_falha == 50, f"fonte sem publicação nova ({n_aguardando}) ≠ falha de coleta ({n_falha}, teto 50)")

# ── denominador desconhecido ──
cob, niv, d, nt = avalia([H(granularidade="registro", unidadesBase=None, idsConferidos=list("abcdefgh"), registrosBase=None)])
check(cob["percentual"] is None and not cob["calculavel"], "total desconhecido → cobertura 'não calculada' (nunca 100%)")
check(niv == 2 and d["P"] < 75, f"total desconhecido → nível 2 e precisão pelo limite binomial (base infinita): {d['P']}")
check(m.fracao_conferida(cob) == 0, "total desconhecido → fração conferida 0 no teto de cobertura")
cob1 = m.cobertura([{"em": AGORA.strftime("%Y-%m-%dT%H:%M:%S"), "resultado": "confere", "conferidos": 8, "comparados": [{"item": i} for i in "abcdefgh"]}], AGORA, 206)
check(cob1["percentual"] is None and not cob1["calculavel"], "conferência antiga (metodologia 1.0, sem cobertura registrada) → cobertura não calculada")

# ── amostras repetidas ──
rep = [H(0, granularidade="registro", unidadesBase=206, idsConferidos=list("abcdefgh"), registrosBase=206),
       H(1, granularidade="registro", unidadesBase=206, idsConferidos=list("abcdefgh"), registrosBase=206),
       H(2, granularidade="registro", unidadesBase=206, idsConferidos=list("abcdefgh") + ["a", "b"], registrosBase=206)]
check(avalia(rep)[0]["unidadesConferidas"] == 8, "a mesma amostra conferida 3 vezes conta 8 contratações, não 24")
dif = rep[:1] + [H(1, granularidade="registro", unidadesBase=206, idsConferidos=list("ijklmnop"), registrosBase=206)]
check(avalia(dif)[0]["unidadesConferidas"] == 16, "amostras diferentes em dias diferentes somam (16 contratações distintas)")
check(avalia([H(granularidade="registro", unidadesBase=5, idsConferidos=list("abcdefgh"), registrosBase=5)])[0]["unidadesConferidas"] == 5,
      "cobertura nunca passa do total da base")

# ── divergência ──
_, _, d_ok, n_ok = avalia([H(granularidade="registro", unidadesBase=206, idsConferidos=[f"c{i}" for i in range(206)], registrosBase=206)])
_, _, d_div, n_div = avalia([H(granularidade="registro", unidadesBase=206, idsConferidos=[f"c{i}" for i in range(206)], registrosBase=206,
                                resultado="diverge", divergentes=[{"item": "c1"}, {"item": "c2"}])], classe="divergencia")
check(d_div["P"] <= 40 and n_div <= 40 and n_div < n_ok, f"divergência reduz precisão ({d_ok['P']} → {d_div['P']}) e nota ({n_ok} → {n_div})")
check(m.limite_superior(206, 8, 1) > m.limite_superior(206, 8, 0), "uma divergência na amostra aumenta o limite superior de erro")

# ── integridade: quantidade e qualidade dos testes ──
um = [{"nivel": "ok", "texto": "registros judiciario"}]
cinco = [{"nivel": "ok", "texto": t} for t in ("formato x.json: campos", "x: total = soma das notas", "x: nº de notas = registros",
                                               "x: notas repetidas", "x: valor negativo ou zero")]
check(m.dim_I(um)[0] < 100 and m.dim_I(um)[0] == 20, f"um único teste aprovado → integridade {m.dim_I(um)[0]} (não 100)")
check(m.dim_I(cinco)[0] == 100, "testes aprovados nos 5 tipos (estrutura, totais, contagem, duplicidade, faixa) → integridade 100")
check(m.dim_I([])[0] is None, "sem testes → integridade não avaliada (vale 0 na nota)")
check(m.dim_I(cinco + [{"nivel": "erro", "texto": "x: total = soma"}])[0] < 100, "um erro reduz a integridade")

# ── estatística ──
check(abs(m.limite_superior(206, 8, 0) - 0.3058) < 0.001, "limite hipergeométrico 8 de 206 sem erro ≈ 30,6%")
check(m.limite_superior(206, 206, 0) == 0 and m.limite_superior(25, 25, 1) == 0.04, "base inteira conferida: limite = proporção observada")
check(m.limite_superior(None, 2, 0) > 0.7, "2 itens de base de tamanho desconhecido: limite > 70% (quase nada se pode afirmar)")

# ── regressão com as 21 bases publicadas ──
icp = json.load(open(ROOT / "dados/icp.json", encoding="utf-8"))
_inv = {str(x.get("runId")) for x in (json.load(open(ROOT / "dados/icp_anotacoes.json", encoding="utf-8")).get("execucoesInvalidas") or [])}
hist = [h for h in (json.loads(l) for l in open(ROOT / "dados/icp_verificacoes.jsonl", encoding="utf-8") if l.strip())
        if str(h.get("coletaRunId")) not in _inv]  # mesma regra do ICP: execuções inválidas ficam fora (25/11/2026)
agora = datetime.fromisoformat(icp["geradoEm"])
check(len(icp["bases"]) == 21, f"{len(icp['bases'])} bases no ICP")
for fid, b in icp["bases"].items():
    hb = [h for h in hist if h.get("base") == fid]
    cob = m.cobertura(hb, agora, b.get("registros"), vf.hashes_atuais(fid))  # com os hashes de hoje (janela de 30 dias)
    if b["cobertura"] is not None and cob is not None:
        check((cob["unidadesConferidas"], cob["percentual"]) == (b["cobertura"]["unidadesConferidas"], b["cobertura"]["percentual"]),
              f"{fid}: cobertura reconstruída do histórico permanente = publicada ({cob['unidadesConferidas']} un., {cob['percentual']}%)")
    check(b["nota"] == m.nota(b["dimensoes"], b["classe"], b["cobertura"], b["nivel"]), f"{fid}: nota 2.0 reproduzível ({b['nota']})")
    if b["cobertura"] is None or b["cobertura"]["resultado"] not in m.COMPATIVEL:
        check(b["nota"] <= 70, f"{fid}: sem conferência compatível na fonte → nota {b['nota']} ≤ 70")
    if b["statusCor"] == "verde":
        check(b["nivel"] >= 3, f"{fid}: verde exige nível ≥ 3")
    if b["nivel"] == 2:
        check(b["nota"] <= round(70 + 30 * m.fracao_conferida(b["cobertura"])), f"{fid}: nível 2 respeita o teto de cobertura ({b['nota']})")
    if b["cobertura"] and not b["cobertura"]["calculavel"]:
        check(b["cobertura"]["percentual"] is None, f"{fid}: sem denominador, sem percentual")
geral = round(sum(b["nota"] * b["importancia"] for b in icp["bases"].values()) / sum(b["importancia"] for b in icp["bases"].values()))
check(icp["nota"] == geral, f"nota geral = média das 21 bases com os pesos de importância ({geral})")
check(icp["metodologia"]["versao"] == m.VERSAO and icp["metodologia"]["anterior"]["versao"] == "1.0", "icp.json identifica a metodologia (2.0) e a anterior (1.0)")

# ── histórico das notas ──
hn = ROOT / "dados/icp_notas_historico.jsonl"
linhas = [json.loads(l) for l in open(hn, encoding="utf-8") if l.strip()] if hn.exists() else []
check(any(l.get("metodologia") == "1.0" and l.get("formula") for l in linhas), "retrato da metodologia 1.0 (nota e fórmula) preservado no histórico das notas")
p = subprocess.run(["git", "-C", str(ROOT), "log", "--format=%H", "--", "dados/icp_notas_historico.jsonl"], capture_output=True, text=True)
atual = set(open(hn, encoding="utf-8").read().splitlines()) if hn.exists() else set()
perdidas = 0
for c in p.stdout.split():
    perdidas += sum(1 for l in subprocess.run(["git", "-C", str(ROOT), "show", f"{c}:dados/icp_notas_historico.jsonl"], capture_output=True, text=True).stdout.splitlines()
                    if l.strip() and l not in atual)
check(perdidas == 0, f"histórico das notas: nenhuma linha antiga apagada ({perdidas} perdidas)")

# ── janela móvel de 30 dias com hash do registro (desde 19/11/2026) ──
def conf(em, ids, hashes=None, res="confere"):
    h = {"em": em, "resultado": res, "granularidade": "registro", "unidade": "contratação", "unidadesBase": 5, "registrosBase": 5,
         "idsConferidos": ids, "unidadesConferidas": len(ids), "divergentes": [], "comparados": [{"item": i} for i in ids], "fonteUrl": "x"}
    if hashes is not None:
        h["hashes"] = hashes
    return h
hist = [conf("2026-11-10T10:00:00", ["a", "b"], {"a": "1", "b": "2"}), conf("2026-11-17T10:00:00", ["c"], {"c": "3"})]
c = m.cobertura(hist, AGORA, 5, {"a": "1", "b": "2", "c": "3", "d": "4", "e": "5"})
check(c["unidadesConferidas"] == 3, "janela de 30 dias: a união das amostras soma os registros conferidos que não mudaram (3 de 5)")
c = m.cobertura(hist, AGORA, 5, {"a": "1", "b": "MUDOU", "c": "3", "d": "4", "e": "5"})
check(c["unidadesConferidas"] == 2, "registro que mudou depois da conferência volta a 'não conferido'")
c = m.cobertura(hist, AGORA, 5, {"c": "3", "d": "4", "e": "5"})
check(c["unidadesConferidas"] == 1, "registro que saiu da base não conta")
c = m.cobertura([conf("2026-11-17T10:00:00", ["a", "b"])], AGORA, 5, {"a": "1", "b": "2"})
check(c["unidadesConferidas"] == 0, "conferência sem hash gravado não prova que o registro está igual: não conta")
c = m.cobertura([conf("2026-10-10T10:00:00", ["a"], {"a": "1"}), conf("2026-11-17T10:00:00", ["b"], {"b": "2"})], AGORA, 5, {"a": "1", "b": "2"})
check(c["unidadesConferidas"] == 1, "conferência com mais de 30 dias não conta")
c = m.cobertura(hist, AGORA, 5, None)
check(c["unidadesConferidas"] == 3, "base sem hashes (granularidade por unidade/total): regra anterior inalterada")
check(m.teto_cobertura({**c, "percentual": 60.0}, 2) == 70 + 30 * 0.6, "a fórmula 70 + 30 × fração conferida não mudou")

print(f"✅ {len(oks)} checagens OK · ❌ {len(erros)} erros")
for e in erros:
    print("❌", e)
sys.exit(1 if erros else 0)
