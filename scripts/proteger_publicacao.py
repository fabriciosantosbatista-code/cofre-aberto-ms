#!/usr/bin/env python3
"""
Cofre Aberto MS — proteção da publicação: nada é publicado se falhar nos testes

Roda no robô depois de todos os geradores e ANTES do commit. Executa, sobre os dados e páginas prontos para publicar:
  1. tests/test_cpf.py             nenhum CPF completo (detector independente da máscara, com autoteste)
  2. tests/test_integridade_dados  as contas fecham (somas, totais, contagens, painel leve = dados completos)
  3. gerar_monitoramento + tests/test_variacoes   formato das fontes, queda brusca de registros ou do total, exposição

POR BASE (desde 20/11/2026): se os erros bloqueantes forem todos de bases identificadas (integridade ou variações de uma
base com arquivos conhecidos), só ESSAS bases voltam à versão publicada (HEAD); os derivados (painel leve, planilhas,
páginas de parlamentares, números da capa) são regerados e a bateria roda de novo. Passou: as outras bases publicam
normalmente ("publicado_parcial"), a base mantida mostra no site "dados de DD/MM: a coleta de hoje não passou no teste
de integridade" e a falha fica no ICP e no log. Ainda falhou: bloqueio do site inteiro, como abaixo.
BLOQUEIA TUDO: CPF exposto (detector), JSON corrompido em dados/, teste de contenção (tests/test_contencao.py), teste
que não produziu resultado, erro sem base identificada ("geral") ou de base sem arquivos conhecidos.

Se algum teste BLOQUEANTE falhar (e não der para segurar só a base):
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


# arquivos de cada base (os mesmos do ICP); só com eles dá para manter uma base na versão anterior sem mexer nas outras
ARQUIVOS_BASE_PADRAO = {"senadores": ["dados/senadores_ms.json"], "deputados": ["dados/deputados_federais_ms.json"],
                        "deputados-estaduais": ["dados/deputados_estaduais_ms.json"]}
# derivados regerados depois de manter uma base (para continuarem iguais aos dados publicados)
DERIVADOS = [["scripts/gerar_dados_abertos.py"], ["scripts/gerar_paginas_parlamentares.py"], ["scripts/gerar_painel_leve.py"],
             ["scripts/atualizar_paginas.py"], ["scripts/mascarar_cpf.py", "--paginas"]]


def arquivos_das_bases():
    m = dict(ARQUIVOS_BASE_PADRAO)
    for b, v in (J("dados/icp.json").get("bases") or {}).items():
        if v.get("arquivos"):
            m[b] = list(v["arquivos"])
    return m


def json_corrompidos():
    ruins = []
    for f in sorted((RAIZ / "dados").rglob("*.json")):
        try:
            json.load(open(f, encoding="utf-8"))
        except Exception as e:
            ruins.append({"nivel": "erro", "base": "geral", "texto": f"JSON corrompido: {f.relative_to(RAIZ)} ({type(e).__name__})"})
    return ruins


def rodar_testes():
    """Executa a bateria e devolve {teste: {"codigo", "saida", "itens"}}."""
    out = {}
    ruins = json_corrompidos()
    out["json"] = {"codigo": 1 if ruins else 0, "saida": "\n".join(x["texto"] for x in ruins), "itens": ruins}
    if (RAIZ / "tests/test_contencao.py").exists():
        c, s = roda([sys.executable, "tests/test_contencao.py"])
        out["contencao"] = {"codigo": c, "saida": s, "itens": [] if c == 0 else None}
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


TESTES_GLOBAIS = ("cpf", "json", "contencao")  # falha nesses bloqueia o site inteiro


def separa(motivos, mapa):
    """(globais, {base: [motivos]}): o que bloqueia tudo e o que dá para segurar só na base."""
    globais, por_base = [], {}
    for m in motivos:
        if m["teste"] in TESTES_GLOBAIS or m["base"] in ("geral", "", None) or m["base"] not in mapa:
            globais.append(m)
        else:
            por_base.setdefault(m["base"], []).append(m)
    return globais, por_base


def data_publicada(arqs):
    """Data da versão mantida (a do HEAD) de uma base, em DD/MM, a partir do campo de atualização do arquivo."""
    for a in arqs:
        d = J(a)
        v = d.get("ultimaAtualizacao") or d.get("geradoEm") or d.get("atualizadoEm") if isinstance(d, dict) else None
        if v:
            return f"{str(v)[8:10]}/{str(v)[5:7]}"
    return None


def manter_bases(por_base, mapa):
    """Volta SÓ os arquivos dessas bases ao HEAD (guarda a cópia rejeitada nas evidências) e regera os derivados."""
    if BLOQUEIO.exists():
        shutil.rmtree(BLOQUEIO)
    BLOQUEIO.mkdir(parents=True)
    mantidas = {}
    for b, ms in por_base.items():
        arqs = [a for a in mapa[b] if (RAIZ / a).exists() or git("ls-files", a).stdout.strip()]
        for a in arqs:
            if (RAIZ / a).is_file():
                dst = BLOQUEIO / "rejeitados" / a
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(RAIZ / a, dst)
        rastreados = [a for a in arqs if git("ls-files", a).stdout.strip()]
        if rastreados:
            git("checkout", "HEAD", "--", *rastreados)
        quando = data_publicada(rastreados)
        mantidas[b] = {"dadosDe": quando, "arquivos": rastreados, "motivos": ms[:10],
                       "texto": f"dados de {quando or 'a coleta anterior'}: a coleta de hoje não passou no teste de integridade"}
    for cmd in DERIVADOS:
        if (RAIZ / cmd[0]).exists():
            roda([sys.executable, *cmd])
    with open(BLOQUEIO / "relatorio.md", "w", encoding="utf-8") as f:
        f.write(f"# Bases mantidas na versão anterior — {datetime.now():%d/%m/%Y %H:%M}\n\nRun: {os.environ.get('GITHUB_RUN_ID', 'local')}\n\n")
        for b, v in mantidas.items():
            f.write(f"## {b} — {v['texto']}\n\n" + "\n".join(f"- **{m['teste']}** · {m['texto']}" for m in v["motivos"]) + "\n\n")
    return mantidas


def bloqueantes(res):
    """Lista de {teste, base, texto} que impedem a publicação."""
    mon = J("dados/monitoramento.json").get("fontes") or {}
    classificacao = tuple(f"{f.get('nome')}: {f.get('classeRotulo')}" for f in mon.values())
    out = []
    for teste in ("json", "contencao", "cpf", "integridade", "variacoes"):
        if teste not in res:
            continue
        r = res[teste]
        itens = r.get("itens")
        if itens is None:  # o teste não produziu resultado (quebrou): bloqueia — ausência de resultado não é aprovação
            if r["codigo"] != 0 or teste in ("cpf", "json"):
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
    mantidas = {}
    if motivos:
        mapa = arquivos_das_bases()
        globais, por_base = separa(motivos, mapa)
        if not globais and por_base:  # só bases identificadas: segura essas e publica o resto
            mantidas = manter_bases(por_base, mapa)
            res_p = rodar_testes()
            resto = bloqueantes(res_p)
            if not resto:
                reg.update({"resultado": "publicado_parcial", "motivos": motivos[:50], "basesAfetadas": sorted(mantidas),
                            "basesMantidas": mantidas, "versaoMantida": head, "testes": resumo(res_p),
                            "evidencias": f"artefato coleta-bloqueada-{os.environ.get('GITHUB_RUN_ID', 'local')} (30 dias)"})
                print(f"⚠️ publicação PARCIAL: {len(mantidas)} base(s) mantida(s) na versão anterior ({', '.join(sorted(mantidas))}); as outras publicam")
                for b, v in mantidas.items():
                    print(f"   ⏸ {b}: {v['texto']}")
                    for m in v["motivos"][:5]:
                        print(f"      ❌ [{m['teste']}] {m['texto'][:200]}")
                motivos = []
            else:
                print(f"⚠️ manter só as bases não bastou ({len(resto)} erro(s) depois): bloqueio do site inteiro")
                motivos = motivos + [m for m in resto if m not in motivos]
    if not motivos and not mantidas:
        reg.update({"resultado": "publicado", "motivos": []})
        print(f"✅ publicação liberada: CPF, integridade e variações sem erro bloqueante")
    elif motivos:
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
