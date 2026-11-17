#!/usr/bin/env python3
"""
Cofre Aberto MS — registro do que cada robô de coleta fez nesta execução (para o ICP distinguir falha técnica de
falta de publicação da fonte)

Lê, pela API do GitHub, os jobs da execução atual do workflow e o log de cada um, e guarda:
  - a conclusão do job (success / failure / cancelled)
  - as linhas de aviso e erro do log ("⚠️", "❌", "Traceback") — p.ex. "Connection refused" no portal da Câmara de CG

Os coletores usam "|| echo ⚠️ ..." para não derrubar a coleta inteira: por isso o job pode terminar "success" mesmo com a
fonte fora do ar — o aviso no log é o que revela a falha. Nenhum dado pessoal é gravado (as linhas passam pela máscara
de CPF).

Saídas: dados/icp_execucoes.json (esta execução) e dados/icp_execucoes_historico.jsonl (uma linha por execução, só cresce).
Uso (no robô): GITHUB_REPOSITORY, GITHUB_RUN_ID e GH_TOKEN no ambiente.
"""

import json, os, re, subprocess, sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from mascarar_cpf import CPF  # noqa: E402

DADOS = Path(__file__).parent.parent / "dados"
# job do workflow → bases do ICP que ele coleta
JOB_BASES = {
    "coletar_dados": ["deputados", "deputados-estaduais", "senadores", "prefeitura", "deputados-brasil", "senado-brasil"],
    "coletar_verba_camara": ["camara"],
    "coletar_contratos_cg": ["contratos-cg", "shows", "alugueis"],
    "coletar_governo_ms": ["governo-ms", "obras"],
    "coletar_fontes_federais": ["eleicoes", "presidencia", "stf", "votacoes", "producao", "arrecadacao"],
    "coletar_emendas_alems": ["emendas"],
    "coletar_tjms": ["judiciario", "supersalarios"], "coletar_trt24": ["judiciario"], "coletar_tre_ms": ["judiciario"],
    "coletar_fontes_auditoria": ["auditoria", "supersalarios", "camaras-ms"],
}
LIXO = re.compile(r"\[36;1m|echo \"|\|\| echo|^\s*#")


def gh(*args):
    p = subprocess.run(["gh", "api", *args], capture_output=True, text=True, timeout=120)
    return p.stdout if p.returncode == 0 else None


def main():
    repo, run = os.environ.get("GITHUB_REPOSITORY"), os.environ.get("GITHUB_RUN_ID")
    if not (repo and run):
        print("ℹ️ fora do robô (sem GITHUB_RUN_ID) — registro de execução não gerado")
        return
    jobs = json.loads(gh(f"repos/{repo}/actions/runs/{run}/jobs?per_page=100") or "{}").get("jobs") or []
    inicio = (json.loads(gh(f"repos/{repo}/actions/runs/{run}") or "{}") or {}).get("run_started_at")
    out = {}
    for j in jobs:
        nome = j.get("name")
        if nome not in JOB_BASES:
            continue
        log = gh(f"repos/{repo}/actions/jobs/{j['id']}/logs") or ""
        linhas = []
        for l in log.splitlines():
            l = re.sub(r"^\S+Z\s", "", l)  # tira o carimbo de hora do GitHub
            if re.search(r"⚠️|❌|Traceback|Error:", l) and not LIXO.search(l):
                l = CPF.sub(lambda m: f"***.{m.group(2)}.{m.group(3)}-**", l)[:300]
                if l not in linhas:
                    linhas.append(l)
        out[nome] = {"conclusao": j.get("conclusion"), "inicio": j.get("started_at"), "fim": j.get("completed_at"),
                     "bases": JOB_BASES[nome], "avisos": linhas[:25], "nAvisos": len(linhas)}
    reg = {"runId": run, "inicio": inicio, "registradoEm": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"), "jobs": out}
    (DADOS / "icp_execucoes.json").write_text(json.dumps(reg, ensure_ascii=False, indent=1), encoding="utf-8")
    with open(DADOS / "icp_execucoes_historico.jsonl", "a", encoding="utf-8") as h:
        h.write(json.dumps({"runId": run, "inicio": inicio, "jobs": {k: {"conclusao": v["conclusao"], "nAvisos": v["nAvisos"], "avisos": v["avisos"][:5]}
                                                                     for k, v in out.items()}}, ensure_ascii=False) + "\n")
    print(f"✅ execução {run}: " + ", ".join(f"{k} {v['conclusao']} ({v['nAvisos']} avisos)" for k, v in out.items()))


if __name__ == "__main__":
    main()
