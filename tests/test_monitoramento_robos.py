#!/usr/bin/env python3
"""
Cofre Aberto MS — testes do monitoramento dos robôs (registrar_execucao.py), da dimensão F do ICP e da proteção da
publicação (proteger_publicacao.py). Não acessa a internet nem o GitHub: a API é simulada com logs sintéticos.

  logs        nenhum aviso · um aviso · vários avisos · erros · falha parcial · fonte fora do ar · log vazio ·
              log indisponível (403/404/500/rede) · formato inesperado · eco de comando · aviso da plataforma ·
              job com falha · etapa com falha · API de jobs fora · fonte sem publicação nova
  ICP (F)     falta de informação não vira nota; falhas derrubam F; registros antigos sem estado não contam
  publicação  falha intencional de integridade e de CPF num clone temporário do repositório: a versão publicada é
              mantida, arquivos novos são retidos, históricos permanentes preservados, evidências e registro gravados

Uso: python3 tests/test_monitoramento_robos.py   (código 1 se algum teste falhar)
"""

import json, os, random, shutil, subprocess, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import registrar_execucao as rx  # noqa: E402
import gerar_icp as gi  # noqa: E402

oks, erros = [], []


def check(cond, msg):
    (oks if cond else erros).append(msg)


TS = "2026-11-17T21:56:{:02d}.1234567Z "


def log(*linhas):
    base = ["##[group]Run actions/checkout@v4", "Syncing repository", "##[endgroup]", "##[group]Run python3 -u scripts/coletar.py",
            "\x1b[36;1mpython3 -u scripts/coletar.py || echo \"⚠️ coletar.py falhou — dados anteriores mantidos\"\x1b[0m", "##[endgroup]",
            "✅ coleta concluída"]
    return "\n".join(TS.format(i % 60) + l for i, l in enumerate(base + list(linhas))).encode()


def api(logs, jobs=None, jobs_erro=None):
    """Simula a API: logs = {job_id: bytes | ('erro', status)}."""
    jobs = jobs or [{"id": k, "name": n, "status": "completed", "conclusion": c, "started_at": "2026-11-17T21:55:00Z",
                     "completed_at": "2026-11-17T22:00:00Z", "steps": st} for k, (n, c, st) in JOB.items()]

    def get(url, autenticar=True, timeout=90):
        if "/runs/" in url and url.split("?")[0].endswith("/jobs"):
            if jobs_erro:
                return jobs_erro, None, f"HTTP {jobs_erro}"
            return 200, json.dumps({"total_count": len(jobs), "jobs": jobs}).encode(), None
        jid = int(url.split("/jobs/")[1].split("/")[0])
        v = logs.get(jid)
        if isinstance(v, tuple):
            return v[1], None, f"HTTP {v[1]}" if v[1] else "ConnectionError: rede fora"
        return 200, v, None
    return get


OK_ST = [{"name": "Coletar", "conclusion": "success"}]
JOB = {1: ("coletar_tre_ms", "success", OK_ST), 2: ("coletar_contratos_cg", "success", OK_ST), 3: ("coletar_dados", "success", OK_ST),
       4: ("coletar_verba_camara", "success", OK_ST), 5: ("coletar_tjms", "success", OK_ST), 6: ("coletar_governo_ms", "success", OK_ST),
       7: ("coletar_emendas_alems", "success", [{"name": "Coletar", "conclusion": "success"}, {"name": "Emendas", "conclusion": "failure"}]),
       8: ("coletar_fontes_federais", "failure", OK_ST), 9: ("coletar_trt24", "success", OK_ST), 10: ("coletar_fontes_auditoria", "success", OK_ST)}
LOGS = {
    1: log(),                                                                   # nenhum aviso
    2: log("⚠️ PNCP: página 3 de 2026-05 sem resposta, nova tentativa"),         # um aviso
    3: log("⚠️ Servidores indisponível para Sonora: Connection reset by peer", "⚠️ Nenhum dado coletado para Sonora — mantendo dados anteriores",
           "⚠️ Prefeitura: exportação parada, lendo empenho a empenho", "⚠️ Prefeitura: exportação parada, lendo empenho a empenho"),  # vários + repetido
    4: log("❌ relatórios da Câmara Municipal de Campo Grande: erro ao ler o PDF", "Traceback (most recent call last):", "ValueError: página vazia"),
    5: log("⚠️ TJMS: coletar_tjms.py falhou — dados anteriores mantidos"),       # falha parcial
    6: b"",                                                                     # log vazio
    7: log("ok"),                                                               # etapa com falha (steps)
    8: log("ok"),                                                               # job com falha
    9: ("erro", 403),                                                           # sem permissão
    10: b"\x89PNG\r\n\x1a\n\x00\x00binario",                                     # formato inesperado (não é texto)
}

# ── 1. registro com a API simulada ──
reg = rx.montar_registro("o/r", "99", get=api(LOGS))
j = reg["jobs"]
check(j["coletar_tre_ms"]["estado"] == "sem_avisos" and j["coletar_tre_ms"]["nAvisos"] == 0, "log sem avisos → sem_avisos, 0 avisos")
check(j["coletar_tre_ms"]["avisosPlataforma"] == [] and j["coletar_tre_ms"]["nErros"] == 0, "eco do comando '|| echo ⚠️ … falhou' não conta como aviso nem falha")
check(j["coletar_contratos_cg"]["estado"] == "com_avisos" and j["coletar_contratos_cg"]["nAvisos"] == 1, "um aviso → com_avisos, 1 aviso")
check(j["coletar_dados"]["nAvisos"] == 3, f"vários avisos (um repetido) → 3 avisos distintos (registrado {j['coletar_dados']['nAvisos']})")
check(j["coletar_dados"]["estado"] == "parcial" and reg["bases"]["camaras-ms"] == "fonte_indisponivel",
      "fonte fora do ar + dado anterior mantido → job parcial e base Câmaras do interior 'fonte_indisponivel'")
check(reg["bases"]["deputados"] in ("sem_avisos", "com_avisos") and reg["bases"]["camaras-ms"] != reg["bases"]["deputados"],
      "aviso atribuído só à base certa (Sonora → Câmaras do interior, não aos deputados)")
check(j["coletar_verba_camara"]["estado"] == "com_erros" and j["coletar_verba_camara"]["nErros"] == 3, "❌ + Traceback + Error → com_erros, 3 erros")
check(j["coletar_tjms"]["estado"] == "parcial" and j["coletar_tjms"]["nFalhas"] == 1, "'… falhou — dados anteriores mantidos' → parcial")
check(j["coletar_governo_ms"]["estado"] == "leitura_indisponivel" and j["coletar_governo_ms"]["nAvisos"] is None and j["coletar_governo_ms"]["leitura"] == "vazio",
      "log vazio → leitura_indisponivel e avisos = None (não 0)")
check(j["coletar_emendas_alems"]["estado"] == "parcial" and "Emendas" in j["coletar_emendas_alems"]["etapas"].get("falharam", []), "etapa com falha → parcial, etapa listada")
check(j["coletar_fontes_federais"]["estado"] == "falha_execucao" and reg["bases"]["arrecadacao"] == "falha_execucao", "job 'failure' → falha_execucao nas bases do job")
check(j["coletar_trt24"]["estado"] == "leitura_indisponivel" and "403" in (j["coletar_trt24"]["erroLeitura"] or ""), "HTTP 403 → leitura_indisponivel com o motivo")
check(j["coletar_fontes_auditoria"]["estado"] == "leitura_indisponivel" and j["coletar_fontes_auditoria"]["nErros"] is None, "log binário/inesperado → leitura_indisponivel")
check(reg["leitura"] == "parcial", "leitura geral 'parcial' quando só parte dos logs foi lida")

# outros indisponíveis: 404, 500, rede
for st, nome in ((404, "404"), (500, "500"), (None, "rede")):
    r2 = rx.montar_registro("o/r", "99", get=api({k: ("erro", st) for k in JOB}))
    check(all(v["estado"] in ("leitura_indisponivel", "falha_execucao") for v in r2["jobs"].values()) and r2["leitura"] == "indisponivel"
          and all(v["nAvisos"] is None for v in r2["jobs"].values()), f"log indisponível ({nome}) em todos os jobs → nenhum 'sem_avisos', leitura indisponível")
# API de jobs fora
r3 = rx.montar_registro("o/r", "99", get=api({}, jobs_erro=503))
check(r3["leitura"] == "indisponivel" and set(r3["bases"].values()) == {"leitura_indisponivel"}, "API de jobs fora → todas as bases 'leitura_indisponivel'")
# formato texto sem carimbo de hora nem grupos (ex.: página HTML de erro)
st, b, _ = 200, b"<html><body>Rate limit</body></html>", None
r4 = rx.analisar_log(b.decode())
check(not r4["formatoReconhecido"], "texto que não parece log do Actions → formato não reconhecido")
# aviso da plataforma do GitHub
r5 = rx.analisar_log(log("##[warning]Node.js 20 is deprecated. The following actions target Node.js 20").decode())
check(r5["avisos"] == [] and len(r5["plataforma"]) == 1, "aviso da plataforma (Node.js) separado, não conta para a base")
# CPF em linha de log é mascarado antes de gravar
rng = random.Random(7)
d = [rng.randint(0, 9) for _ in range(9)]
for n in (9, 10):
    d.append((sum(d[i] * (n + 1 - i) for i in range(n)) * 10) % 11 % 10)
c = "".join(map(str, d))
r6 = rx.analisar_log(log(f"⚠️ fornecedor FULANO DE TAL {c} sem CNPJ", f"⚠️ CPF {c[:3]}.{c[3:6]}.{c[6:9]}-{c[9:]} inválido").decode())
check(all(c not in l and f"{c[:3]}.{c[3:6]}" not in l for l in r6["avisos"]), "CPF numa linha de log é mascarado antes de ir para o registro")
# atribuição do aviso à base: pelo trecho do log (linha anterior) e pelo passo, não a todas as bases do job
an = rx.analisar_log(log("##[group]Run python3 scripts/coletar_dados.py", "Coletando deputados federais (Câmara dos Deputados)...",
                         "Coletando Câmara Municipal de Jardim (Fiorilli SCPI)...", "  Tentativa 1 falhou, tentando novamente...",
                         "  ⚠️ Diárias indisponível para Jardim: Max retries exceeded", "  ⚠️ Nenhum dado coletado para Jardim — mantendo dados anteriores",
                         "Coletando senadores...").decode())
eb = rx.estado_bases("coletar_dados", "parcial", an, {})
check(eb["camaras-ms"] == "fonte_indisponivel" and eb["deputados"] == "sem_avisos" and eb["senadores"] == "sem_avisos" and eb["prefeitura"] == "sem_avisos",
      "falha de uma Câmara do interior conta só para Câmaras do interior (não para deputados, senadores, prefeitura)")
an = rx.analisar_log(log("##[group]Run python3 scripts/coletar_contratos_governo.py", "⚠️ coletar_contratos_governo.py falhou — contratos anteriores mantidos").decode())
eb = rx.estado_bases("coletar_fontes_auditoria", "parcial", an, {})
check(eb == {"auditoria": "parcial", "supersalarios": "sem_avisos"}, "falha num passo de coletor de uma base só conta só para essa base")
an = rx.analisar_log(log("##[group]Run python3 scripts/coletar_governo_ms.py", "  diárias: 61401 trechos", "  ❌ primeiroEscalao: /d0125/x: 401 None").decode())
check(rx.estado_bases("coletar_governo_ms", "com_erros", an, {}) == {"governo-ms": "com_erros", "obras": "sem_avisos"}, "erro da folha do primeiro escalão conta para o Governo, não para Obras")
an = rx.analisar_log(log("##[group]Run python3 scripts/x.py", "  ⚠️ algo falhou — dados anteriores mantidos").decode())
check(set(rx.estado_bases("coletar_governo_ms", "parcial", an, {}).values()) == {"parcial"}, "sem palavra-chave nem trecho: vale para todas as bases do job (não esconde falha)")
an = rx.analisar_log(log("##[group]Run python3 scripts/coletar_dados.py", "Coletando Câmara Municipal de Jardim...", "##[endgroup]",
                         "##[group]Run python3 scripts/outro.py", "  ⚠️ falhou — dados anteriores mantidos").decode())
check(set(rx.estado_bases("coletar_dados", "parcial", an, {}).values()) == {"parcial"}, "o trecho não atravessa passos do job")
# gerar_icp usa a mesma atribuição gravada no registro (origemLinhas)
check(gi.linhas_da_base({"jobs": {"coletar_dados": {"bases": rx.JOB_BASES["coletar_dados"], "falhas": ["⚠️ Nenhum dado para Jardim — mantendo dados anteriores"],
                         "origemLinhas": {"⚠️ Nenhum dado para Jardim — mantendo dados anteriores": ["camaras-ms"]}}}}, "deputados") == [],
      "pendências do ICP: linha atribuída a Câmaras do interior não aparece em Deputados")
# fonte sem publicação nova (monitoramento)
orig = rx.J
rx.J = lambda n: {"fontes": {"prefeitura": {"classe": "aguardando_fonte"}}} if n == "monitoramento.json" else orig(n)
r7 = rx.montar_registro("o/r", "99", get=api({k: log() for k in JOB}))
rx.J = orig
check(r7["bases"]["prefeitura"] == "sem_publicacao_nova", "coleta ok + fonte sem dado novo → 'sem_publicacao_nova'")

# ── 2. dimensão F do ICP ──
H = lambda *e: [{"runId": str(i), "bases": {"x": s}} for i, s in enumerate(e)]
check(gi.dimensao_F([], "x") is None, "F sem nenhuma coleta registrada = não avaliado (não 100)")
check(gi.dimensao_F(H("leitura_indisponivel", "leitura_indisponivel"), "x") is None, "F só com logs ilegíveis = não avaliado (não 100)")
check(gi.dimensao_F([{"runId": "1", "jobs": {"coletar_dados": {"conclusao": "success", "nAvisos": 0}}}], "x") is None,
      "registro antigo sem estado por base (antes da correção) não conta como sucesso")
check(gi.dimensao_F(H("sem_avisos", "com_avisos", "sem_publicacao_nova", "leitura_indisponivel"), "x") == 100, "F = 100 com 3 coletas boas e 1 ilegível (ilegível fora da conta)")
check(gi.dimensao_F(H("sem_avisos", "parcial", "fonte_indisponivel", "falha_execucao"), "x") == 25, "F = 25 com 1 boa e 3 falhas")
check(gi.dimensao_F(H("com_erros", "com_erros"), "x") == 0, "F = 0 com erros em todas as coletas")

# ── 3. proteção da publicação: falha intencional num clone temporário ──
def clone():
    tmp = Path(tempfile.mkdtemp(prefix="cofre-protecao-"))
    subprocess.run(["git", "clone", "-q", "--local", "--no-hardlinks", str(ROOT), str(tmp / "r")], check=True)
    r = tmp / "r"
    for rel in ("scripts", "tests", ".github", "dados"):  # o código e os dados de trabalho atuais (inclusive o que ainda não tem commit)
        if (r / rel).exists():
            shutil.rmtree(r / rel)
        shutil.copytree(ROOT / rel, r / rel, ignore=shutil.ignore_patterns("__pycache__"))
    subprocess.run(["git", "-C", str(r), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(r), "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "base válida"], check=True)
    return tmp, r


def protege(r):
    p = subprocess.run([sys.executable, "scripts/proteger_publicacao.py", "--raiz", str(r)], cwd=r, capture_output=True, text=True, timeout=1800)
    return p.returncode, p.stdout + p.stderr, json.load(open(r / "dados/icp_publicacao.json", encoding="utf-8"))


if "--rapido" not in sys.argv:
    tmp, r = clone()
    try:
        alvo = r / "dados/deputados_estaduais_ms.json"
        valido = alvo.read_bytes()
        d = json.loads(valido)
        d["resumo"][f"totalVerbaIndenizatoriaPaga{d['ano']}"] = (d["resumo"].get(f"totalVerbaIndenizatoriaPaga{d['ano']}") or 0) + 12345.67  # total que não fecha
        alvo.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
        (r / "dados/novo_desta_coleta.json").write_text('{"x": 1}', encoding="utf-8")
        hist = r / "dados/icp_verificacoes.jsonl"
        hist.write_text(hist.read_text(encoding="utf-8") + '{"em":"2026-11-17T23:59:59","base":"teste","resultado":"confere"}\n', encoding="utf-8")
        c, saida, pub = protege(r)
        check(pub["resultado"] == "bloqueado" and any(m["teste"] == "integridade" for m in pub["motivos"]), "falha intencional de integridade → publicação bloqueada, teste identificado")
        check("deputados-estaduais" in pub["basesAfetadas"], f"base afetada identificada (deputados-estaduais) — {pub.get('basesAfetadas')}")
        check(alvo.read_bytes() == valido, "dado inválido revertido: a última versão válida (HEAD) foi mantida")
        check(not (r / "dados/novo_desta_coleta.json").exists() and (r / "bloqueio/novos/dados/novo_desta_coleta.json").exists(),
              "arquivo novo da coleta bloqueada retido em bloqueio/novos (não publicado, não apagado)")
        check("2026-11-17T23:59:59" in hist.read_text(encoding="utf-8"), "histórico permanente (icp_verificacoes.jsonl) preservado no bloqueio")
        check((r / "bloqueio/relatorio.md").exists() and (r / "bloqueio/rejeitados/dados/deputados_estaduais_ms.json").exists(),
              "evidências gravadas (relatório + cópia dos dados rejeitados)")
        check(c == 0 and not pub["versaoMantidaTambemFalha"], "versão mantida passa nos testes; o robô segue para registrar a falha")
        # CPF exposto intencionalmente
        rng = random.Random(11)
        d = [rng.randint(0, 9) for _ in range(9)]
        for n in (9, 10):
            d.append((sum(d[i] * (n + 1 - i) for i in range(n)) * 10) % 11 % 10)
        cpf = "".join(map(str, d))
        al = r / "dados/alugueis.json"
        valido2 = al.read_bytes()
        a = json.loads(valido2)
        a["pncp"]["lista"][0]["locador"] = {"nome": "FULANO DE TAL", "doc": f"{cpf[:3]}.{cpf[3:6]}.{cpf[6:9]}-{cpf[9:]}", "tipo": "PF"}
        al.write_text(json.dumps(a, ensure_ascii=False), encoding="utf-8")
        shutil.rmtree(r / "bloqueio", ignore_errors=True)
        c, saida, pub = protege(r)
        check(pub["resultado"] == "bloqueado" and any(m["teste"] == "cpf" for m in pub["motivos"]), "CPF exposto intencionalmente → publicação bloqueada pelo detector de CPF")
        check(al.read_bytes() == valido2, "arquivo com CPF revertido à versão publicada")
        check(not (r / "bloqueio/rejeitados").exists(), "com CPF exposto, os dados rejeitados NÃO são copiados para as evidências")
        check(cpf not in (r / "bloqueio/relatorio.md").read_text(encoding="utf-8"), "o relatório de evidências não contém o CPF")
        # coleta válida passa
        shutil.rmtree(r / "bloqueio", ignore_errors=True)
        c, saida, pub = protege(r)
        check(pub["resultado"] == "publicado" and c == 0, f"coleta válida → publicação liberada ({pub['resultado']})")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

print(f"✅ {len(oks)} checagens OK · ❌ {len(erros)} erros")
for e in erros:
    print("❌", e)
sys.exit(1 if erros else 0)
