#!/usr/bin/env python3
"""
Cofre Aberto MS — Emendas conferida em job próprio (28/11/2026; casos simulados, sem rede)

Na conferência geral o teto de 300 s não cabia (4 coletas sem conferir). Agora o passo principal pula Emendas
(CONFERENCIA_PULAR=emendas) e o job "conferir_emendas", depois da publicação, roda só Emendas com teto próprio
(CONFERENCIA_TETO_SEG), dentro da janela de 2 h da coleta.
Uso: python3 tests/test_emendas_job_proprio.py   (código 1 se algum teste falhar)
"""
import os, sys, tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import validar_fontes as vf  # noqa: E402

oks, erros = [], []
check = lambda c, m: (oks if c else erros).append(m)
tmp = Path(tempfile.mkdtemp())
vf.SAIDA, vf.HISTORICO = tmp / "validacao_fontes.json", tmp / "historico.jsonl"
vf.janela_coleta = lambda: (True, "teste")
chamadas, tetos = [], {}


def falsa(nome):
    def f():
        chamadas.append(nome)
        tetos[nome] = round(vf.PRAZO["fim"] - vf.time.monotonic())
        return {"resultado": "confere", "em": vf.AGORA, "conferidos": 1, "comparados": []}
    return f


vf.CONFERENCIAS = [("emendas", falsa("emendas")), ("obras", falsa("obras"))]
vf.registrar = lambda fonte, r, out: out.__setitem__(fonte, r) or r


def rodar(argv, env):
    chamadas.clear(); tetos.clear()
    for k in ("CONFERENCIA_PULAR", "CONFERENCIA_TETO_SEG"):
        os.environ.pop(k, None)
    os.environ.update(env)
    sys.argv = ["validar_fontes.py"] + argv
    vf.main()


rodar([], {"CONFERENCIA_PULAR": "emendas"})
check(chamadas == ["obras"], "passo principal: Emendas pulada, as outras conferidas")
rodar(["emendas"], {"CONFERENCIA_TETO_SEG": "1080", "CONFERENCIA_PRAZO_MIN": "18"})
check(chamadas == ["emendas"], "job próprio: só Emendas")
check(1000 < tetos.get("emendas", 0) <= 1080, "job próprio: teto de 18 min em vez de 300 s")
rodar([], {})
check(tetos.get("emendas", 0) <= 300, "sem o job próprio, o teto de Emendas continua 300 s")

w = yaml.safe_load(open(ROOT / ".github/workflows/atualizar.yml", encoding="utf-8"))
j = w["jobs"].get("conferir_emendas") or {}
check(j.get("needs") == ["commit_e_push"], "job conferir_emendas depois da publicação")
passo = [s for s in j.get("steps", []) if "validar_fontes.py emendas" in str(s.get("run"))]
check(passo and passo[0]["env"].get("CONFERENCIA_TETO_SEG") == "1080", "job roda só Emendas com teto de 1080 s")
principal = [s for s in w["jobs"]["commit_e_push"]["steps"] if "validar_fontes.py" in str(s.get("run"))]
check(principal and principal[0]["env"].get("CONFERENCIA_PULAR") == "emendas", "passo principal pula Emendas")

for m in oks:
    print("✓", m)
for m in erros:
    print("✗", m)
print(f"{len(oks)} ok, {len(erros)} falha(s)")
sys.exit(1 if erros else 0)
