#!/usr/bin/env python3
"""
Cofre Aberto MS — proteção da publicação: nada é publicado se falhar nos testes

Roda no robô depois de todos os geradores e ANTES do commit. Executa, sobre os dados e páginas prontos para publicar:
  1. tests/test_cpf.py             nenhum CPF completo (detector independente da máscara, com autoteste)
  2. tests/test_integridade_dados  as contas fecham (somas, totais, contagens, painel leve = dados completos)
  3. gerar_monitoramento + tests/test_variacoes   formato das fontes, queda brusca de registros ou do total, exposição

Se algum teste BLOQUEANTE falhar:
  - a última versão publicada (o commit atual, HEAD) é mantida: os caminhos publicáveis voltam ao HEAD;
  - arquivos novos desta coleta (ainda não publicados) são retidos em bloqueio/novos/ — não vão para o site;
  - as evidências ficam em bloqueio/ (relatório dos testes, lista de arquivos, cópia dos dados rejeitados quando o
    teste de CPF passou) e o robô as guarda como artefato por 30 dias;
  - dados/icp_publicacao.json registra o bloqueio, qual teste falhou, em qual base e o que foi mantido;
  - os testes rodam de novo sobre a versão mantida, para o ICP descrever o que está de fato publicado.

Não bloqueiam (aparecem no ICP, mas não impedem a publicação): a classificação das fontes (fonte parada ou divergência
na conferência), porque a versão anterior não é "mais válida" nesses casos — a fonte é a mesma —, e avisos.

Os históricos que só crescem (icp_verificacoes.jsonl, icp_execucoes_historico.jsonl, icp_notas_historico.jsonl, monitoramento_historico.json)
NUNCA são revertidos.

Se o teste de CPF falhar mesmo na versão mantida, o script sai com código 1: o robô não faz commit nenhum.
Uso: python3 scripts/proteger_publicacao.py [--raiz PASTA]   (a raiz só muda nos testes)
"""

import json, os, shutil, subprocess, sys
from datetime import datetime
from pathlib import Path

RAIZ = Path(sys.argv[sys.argv.index("--raiz") + 1]).resolve() if "--raiz" in sys.argv else Path(__file__).resolve().parent.parent
LISTA = RAIZ / ".github" / "publicar.txt"
NUNCA_REVERTER = {"dados/icp_verificacoes.jsonl", "dados/icp_execucoes_historico.jsonl", "dados/monitoramento_historico.json", "dados/icp_notas_historico.jsonl",
                  "dados/icp_execucoes.json", "dados/icp_publicacao.json"}
BLOQUEIO = RAIZ / "bloqueio"


def caminhos_publicaveis():
    return [l.strip() for l in open(LISTA, encoding="utf-8") if l.strip() and not l.startswith("#")]


def roda(cmd):
    p = subprocess.run(cmd, cwd=RAIZ, capture_output=True, text=True, timeout=1800)
    return p.returncode, p.stdout + p.stderr


def git(*a):
    return subprocess.run(["git", *a], cwd=RAIZ, capture_output=True, text=True, timeout=600)


def J(rel):
    try:
        return json.load(open(RAIZ / rel, encoding="utf-8"))
    except Exception:
        return {}


def rodar_testes():
    """Executa a bateria e devolve {teste: {"codigo", "saida", "itens"}}."""
    out = {}
    c, s = roda([sys.executable, "tests/test_cpf.py", "--json", "dados/icp_testes_cpf.json"])
    out["cpf"] = {"codigo": c, "saida": s}
    c, s = roda([sys.executable, "tests/test_integridade_dados.py", "--json", "dados/icp_testes_integridade.json"])
    out["integridade"] = {"codigo": c, "saida": s}
    roda([sys.executable, "scripts/gerar_monitoramento.py"])
    c, s = roda([sys.executable, "tests/test_variacoes.py", "--json", "dados/icp_testes_variacoes.json"])
    out["variacoes"] = {"codigo": c, "saida": s}
    for nome, arq in (("cpf", "dados/icp_testes_cpf.json"), ("integridade", "dados/icp_testes_integridade.json"), ("variacoes", "dados/icp_testes_variacoes.json")):
        out[nome]["itens"] = J(arq).get("itens")
    return out


def bloqueantes(res):
    """Lista de {teste, base, texto} que impedem a publicação."""
    mon = J("dados/monitoramento.json").get("fontes") or {}
    classificacao = tuple(f"{f.get('nome')}: {f.get('classeRotulo')}" for f in mon.values())
    out = []
    for teste in ("cpf", "integridade", "variacoes"):
        r = res[teste]
        itens = r.get("itens")
        if itens is None:  # o teste não produziu resultado (quebrou): bloqueia — ausência de resultado não é aprovação
            if r["codigo"] != 0 or teste == "cpf":
                out.append({"teste": teste, "base": "geral", "texto": f"o teste {teste} não produziu resultado (código {r['codigo']}): {r['saida'][-300:]}"})
            continue
        for x in itens:
            if x.get("nivel") != "erro":
                continue
            if teste == "variacoes" and x["texto"].startswith(classificacao):
                continue  # classificação da fonte (parada/divergência): vai para o ICP, não bloqueia
            out.append({"teste": teste, "base": x.get("base") or "geral", "texto": x["texto"][:300]})
    return out


def reverter(motivos, res):
    """Volta os caminhos publicáveis ao HEAD (última versão publicada) e guarda as evidências."""
    if BLOQUEIO.exists():
        shutil.rmtree(BLOQUEIO)
    (BLOQUEIO / "novos").mkdir(parents=True)
    caminhos = caminhos_publicaveis()
    mudados = [l[3:].strip() for l in git("status", "--porcelain", "--", *caminhos).stdout.splitlines() if l.strip()]
    novos = [l for l in git("ls-files", "--others", "--exclude-standard", "--", *caminhos).stdout.splitlines() if l.strip()]
    cpf_ok = not any(m["teste"] == "cpf" for m in motivos)
    if cpf_ok:  # cópia dos dados rejeitados (só se não houver CPF exposto neles)
        for rel in mudados:
            src = RAIZ / rel
            if src.is_file() and rel.startswith("dados/"):
                dst = BLOQUEIO / "rejeitados" / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
    guardar = {rel: (RAIZ / rel).read_bytes() for rel in NUNCA_REVERTER if (RAIZ / rel).exists()}
    rastreados = [p for p in caminhos if git("ls-files", "--error-unmatch", p).returncode == 0 or git("ls-files", p).stdout.strip()]
    if rastreados:
        git("checkout", "HEAD", "--", *rastreados)
    for rel in novos:  # retém (não apaga) os arquivos novos desta coleta
        if rel in NUNCA_REVERTER:
            continue
        dst = BLOQUEIO / "novos" / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(RAIZ / rel), str(dst))
    for rel, b in guardar.items():
        (RAIZ / rel).write_bytes(b)
    with open(BLOQUEIO / "relatorio.md", "w", encoding="utf-8") as f:
        f.write(f"# Coleta bloqueada — {datetime.now():%d/%m/%Y %H:%M}\n\nRun: {os.environ.get('GITHUB_RUN_ID', 'local')}\n\n## Testes que falharam\n\n")
        for m in motivos:
            f.write(f"- **{m['teste']}** · base `{m['base']}` · {m['texto']}\n")
        f.write(f"\n## Arquivos alterados nesta coleta e revertidos ({len(mudados)})\n\n" + "\n".join(f"- {r}" for r in mudados[:500]))
        f.write(f"\n\n## Arquivos novos retidos em bloqueio/novos ({len(novos)})\n\n" + "\n".join(f"- {r}" for r in novos[:500]))
        for t, r in res.items():
            f.write(f"\n\n## Saída de {t} (código {r['codigo']})\n\n```\n{r['saida'][-6000:]}\n```\n")
    return mudados, novos


def main():
    res = rodar_testes()
    motivos = bloqueantes(res)
    head = git("rev-parse", "HEAD").stdout.strip()
    resumo = lambda r: {t: {"codigo": v["codigo"], "erros": sum(1 for x in v.get("itens") or [] if x.get("nivel") == "erro")} for t, v in r.items()}
    reg = {"em": datetime.now(__import__("zoneinfo").ZoneInfo("America/Campo_Grande")).strftime("%Y-%m-%dT%H:%M:%S"), "runId": os.environ.get("GITHUB_RUN_ID"), "testes": resumo(res)}
    if not motivos:
        reg.update({"resultado": "publicado", "motivos": []})
        print(f"✅ publicação liberada: CPF, integridade e variações sem erro bloqueante")
    else:
        mudados, novos = reverter(motivos, res)
        res2 = rodar_testes()  # o ICP precisa descrever a versão que fica publicada
        resto = bloqueantes(res2)
        reg.update({"resultado": "bloqueado", "motivos": motivos[:50], "basesAfetadas": sorted({m["base"] for m in motivos}),
                    "versaoMantida": head, "arquivosRevertidos": len(mudados), "arquivosNovosRetidos": len(novos),
                    "evidencias": f"artefato coleta-bloqueada-{os.environ.get('GITHUB_RUN_ID', 'local')} (30 dias)",
                    "versaoMantidaTambemFalha": [m for m in resto][:20], "testesDepoisDeReverter": resumo(res2)})
        print(f"⛔ publicação BLOQUEADA: {len(motivos)} erro(s) bloqueante(s) — mantida a versão publicada {head[:9]}; "
              f"{len(mudados)} arquivo(s) revertido(s), {len(novos)} novo(s) retido(s); evidências em bloqueio/")
        for m in motivos[:15]:
            print(f"   ❌ [{m['teste']}] {m['base']}: {m['texto'][:200]}")
    (RAIZ / "dados" / "icp_publicacao.json").write_text(json.dumps(reg, ensure_ascii=False, indent=1), encoding="utf-8")
    if reg["resultado"] == "bloqueado" and any(m["teste"] == "cpf" for m in reg["versaoMantidaTambemFalha"]):
        print("❌ a versão mantida também tem CPF exposto — nenhum commit será feito")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
