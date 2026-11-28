#!/usr/bin/env python3
"""
Cofre Aberto MS — Emendas: reavaliação, sem API, da conferência gravada (28/11/2026; em cópias, sem rede)

Usa a conferência de Emendas de 28/11/2026 (3 divergências) e as evidências de config/emendas_reavaliacao.json: as 3
passam a "não verificado", o histórico ganha uma linha marcada "reavaliacao" (só acrescenta) e a conferência original
ganha uma anotação. Rodar de novo não reavalia duas vezes. Site maior que o documento continua divergência.
Uso: python3 tests/test_emendas_reavaliacao.py   (código 1 se algum teste falhar)
"""
import json, shutil, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import validar_fontes as vf  # noqa: E402

oks, erros = [], []
check = lambda c, m: (oks if c else erros).append(m)
tmp = Path(tempfile.mkdtemp()) / "dados"
tmp.mkdir()
(tmp.parent / "config").mkdir()
shutil.copy(ROOT / "config" / "emendas_reavaliacao.json", tmp.parent / "config")
shutil.copy(ROOT / "dados" / "icp_anotacoes.json", tmp)
EM = "2026-11-28T01:40:44"
DIV = [{"item": "202543670019|11319557000378|02/2026", "site": 3900.0, "fonte": 5507.77, "diferenca": -1607.77},
       {"item": "202643180009|30521824000178|07/2026", "site": 8333.32, "fonte": 62136.81, "diferenca": -53803.49},
       {"item": "202643180009|32352772000189|08/2026", "site": 15000.0, "fonte": 27346.85, "diferenca": -12346.85},
       {"item": "202600000001|99888777000166|10/2026", "site": 9000.0, "fonte": 5000.0, "diferenca": 4000.0}]  # site maior: fica
(tmp / "validacao_fontes.json").write_text(json.dumps({"fontes": {"emendas": {"resultado": "diverge", "em": EM, "conferidos": 102,
    "divergentes": DIV, "comparados": DIV, "motivosRegistros": {}, "nota": ""}}}), encoding="utf-8")
(tmp / "icp_verificacoes.jsonl").write_text("", encoding="utf-8")
vf.DADOS, vf.SAIDA, vf.HISTORICO = tmp, tmp / "validacao_fontes.json", tmp / "icp_verificacoes.jsonl"
vf.J = lambda n: json.load(open(tmp / n, encoding="utf-8"))
vf.janela_coleta = lambda: (True, "teste")
vf.reavaliar_emendas()
r = json.load(open(tmp / "validacao_fontes.json"))["fontes"]["emendas"]
check([d["item"] for d in r["divergentes"]] == ["202600000001|99888777000166|10/2026"], "as 3 de 28/11 saem da divergência; site maior que o documento fica")
check(all(r["motivosRegistros"].get(d["item"]) == vf.PAGA_OUTRAS for d in DIV[:3]), "as 3 ficam com o motivo de não verificado")
check(r["conferidos"] == 99 and r["reavaliacao"]["de"] == EM and r["reavaliacao"]["semNovaChamadaApi"], "conferidos e registro da reavaliação")
h = [json.loads(x) for x in open(tmp / "icp_verificacoes.jsonl", encoding="utf-8")]
check(len(h) == 1 and h[0].get("reavaliacao", {}).get("de") == EM, "histórico: uma linha nova marcada como reavaliação")
an = [a for a in json.load(open(tmp / "icp_anotacoes.json"))["anotacoes"] if a["base"] == "emendas" and a["em"] == EM]
check(len(an) == 1 and "sem nova chamada à API" in an[0]["nota"], "anotação ligada à conferência original")
vf.reavaliar_emendas()
check(len(open(tmp / "icp_verificacoes.jsonl").readlines()) == 1, "rodar de novo não reavalia duas vezes")
for x in oks:
    print("✓", x)
for x in erros:
    print("✗", x)
print(f"{len(oks)} ok, {len(erros)} falha(s)")
sys.exit(1 if erros else 0)
