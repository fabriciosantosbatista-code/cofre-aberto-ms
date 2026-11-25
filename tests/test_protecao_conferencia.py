#!/usr/bin/env python3
"""
Cofre Aberto MS — a conferência na fonte compara a versão que vai ao ar (casos simulados, sem rede)

Regras de 25/11/2026 (o ICP de Deputados mostrou "verificado" com divergência na conferência mais recente):
  1. a conferência roda DEPOIS da proteção da publicação e antes do ICP (compara a versão mantida, se houver);
  2. Supersalários, que compara a folha cifrada desta coleta, fica "versão: conferência não aplicada" quando a base é
     mantida ou a publicação inteira é bloqueada — nenhum resultado gravado;
  3. manter uma base regera também a evolução mensal (gerar_analises.py), para o resto da coleta poder publicar;
  4. execuções cujas conferências não valem (dados/icp_anotacoes.json → execucoesInvalidas) ficam no histórico, mas fora
     do status, da nota e da cobertura do ICP.
Uso: python3 tests/test_protecao_conferencia.py   (código 1 se algum teste falhar)
"""
import io, json, os, sys, tempfile
from contextlib import redirect_stdout
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import validar_fontes as vf  # noqa: E402
import gerar_icp as gi  # noqa: E402
import proteger_publicacao as pp  # noqa: E402

oks, erros = [], []
check = lambda c, m: (oks if c else erros).append(m)

# 1. ordem no workflow
wf = yaml.safe_load(open(ROOT / ".github" / "workflows" / "atualizar.yml", encoding="utf-8"))
passos = [p.get("name", "") for p in wf["jobs"]["commit_e_push"]["steps"]]
i_prot = next(i for i, n in enumerate(passos) if n.startswith("Proteger a publicação"))
i_conf = next(i for i, n in enumerate(passos) if n.startswith("Conferir os dados direto nas fontes"))
i_icp = next(i for i, n in enumerate(passos) if n.startswith("ICP — registro"))
check(i_prot < i_conf < i_icp, f"ordem: proteção ({i_prot}) → conferência ({i_conf}) → ICP ({i_icp})")

# 2. bases mantidas nesta coleta (icp_publicacao.json da mesma execução)
os.environ["GITHUB_RUN_ID"] = "999"
pub = {}
vf.J = lambda n: pub if n == "icp_publicacao.json" else {}
pub.update({"runId": "999", "resultado": "bloqueado"})
check(vf.bases_mantidas_nesta_coleta() == {"*"}, "publicação inteira bloqueada → todas as bases")
pub.clear(); pub.update({"runId": "999", "resultado": "publicado_parcial", "basesMantidas": {"deputados": {}}, "basesAfetadas": ["deputados"]})
check(vf.bases_mantidas_nesta_coleta() == {"deputados"}, "publicação parcial → só a base mantida")
pub.clear(); pub.update({"runId": "123", "resultado": "bloqueado"})
check(vf.bases_mantidas_nesta_coleta() == set(), "icp_publicacao.json de outra execução não vale")

# Supersalários (dados da coleta) não é conferido quando mantido; as outras bases são
tmp = Path(tempfile.mkdtemp())
vf.SAIDA, vf.HISTORICO = tmp / "v.json", tmp / "h.jsonl"
vf.janela_coleta = lambda: (True, None)
chamadas = []
ok = lambda nome: (lambda: chamadas.append(nome) or {"resultado": "confere", "em": vf.AGORA, "conferidos": 1, "comparados": [], "divergentes": []})
vf.CONFERENCIAS = (("supersalarios", ok("supersalarios")), ("deputados", ok("deputados")))
ant = {"supersalarios": {"resultado": "confere", "em": "2026-11-24T10:00:00"}, "deputados": {"resultado": "confere", "em": "2026-11-24T10:00:00"}}
pub.clear(); pub.update({"runId": "999", "resultado": "bloqueado"})
vf.J = lambda n: pub if n == "icp_publicacao.json" else ({"fontes": json.loads(json.dumps(ant))} if n == "validacao_fontes.json" else {})
with redirect_stdout(io.StringIO()):
    vf.main()
out = json.loads(vf.SAIDA.read_text())["fontes"]
check(chamadas == ["deputados"], f"Supersalários não é conferido com a base mantida; Deputados (dados do site) é: {chamadas}")
check(out["supersalarios"]["em"] == "2026-11-24T10:00:00" and out["supersalarios"]["ultimaTentativaResultado"] == vf.NAO_APLICADA,
      "Supersalários: fica a conferência anterior, marcada 'versão: conferência não aplicada'")
hist = [json.loads(l) for l in vf.HISTORICO.read_text().splitlines()] if vf.HISTORICO.exists() else []
check(not any(h["base"] == "supersalarios" for h in hist), "nenhuma linha de Supersalários no histórico desta coleta")
src = (ROOT / "scripts" / "verificacao" / "conferencia_supersalarios.py").read_text(encoding="utf-8")
check("versão: conferência não aplicada" in src, "o job próprio da conferência de Supersalários também não grava com a base mantida")

# 3. evolução mensal entre os derivados regerados
check(pp.DERIVADOS[0] == ["scripts/gerar_analises.py"], f"manter uma base regera a evolução mensal primeiro: {pp.DERIVADOS[0]}")

# 4. execuções inválidas fora do ICP
inv = gi.execucoes_invalidas()
check({"45624667052", "45639387411", "45649872489"} <= set(inv) and all(inv.values()), "as 3 execuções de 25/11 anotadas como inválidas, com motivo")
icp_src = (ROOT / "scripts" / "gerar_icp.py").read_text(encoding="utf-8")
check('str(h.get("coletaRunId")) not in invalidas' in icp_src and 'str(h.get("runId")) not in invalidas' in icp_src,
      "o ICP tira as conferências e as execuções inválidas do cálculo")

for e in erros:
    print("❌", e)
print(f"✅ {len(oks)} checagens OK · ❌ {len(erros)} erros")
sys.exit(1 if erros else 0)
