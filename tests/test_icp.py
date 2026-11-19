#!/usr/bin/env python3
"""
Cofre Aberto MS — testes do ICP (Índice de Confiabilidade Pública)

  status        todo status é um dos públicos; verde SÓ com conferência na fonte (≤ 30 dias, confere/mudou) da base INTEIRA (nível ≥ 3)
  notas         recalcula a nota 2.0 de cada base (e a 1.0 preservada) a partir das dimensões, pesos e tetos; recalcula o ICP geral
  tetos         simulações da fórmula 1.0 (preservada); as da 2.0 estão em tests/test_icp_metodologia.py
  indicadores   os números do painel batem com a contagem das bases
  alertas       toda base com divergência ou falha de coleta aparece nos problemas críticos
  falhas        simulação: aviso "Connection refused" no log vira falha da base certa; job "failure" marca todas as bases dele
  histórico     icp_verificacoes.jsonl e icp_execucoes_historico.jsonl só crescem (a versão do git é prefixo da atual)
  páginas       /confiabilidade/ e uma página por base existem, com aviso de metodologia independente, viewport, filtros,
                link oficial e links internos válidos; /monitoramento/ redireciona
  integração    o painel lê icp.json e leva o selo para /confiabilidade/<base>/; o robô roda registrar_execucao e gerar_icp

Uso: python3 tests/test_icp.py   (código de saída 1 se houver erro)
"""

import json, re, subprocess, sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
erros, oks = [], []


def check(cond, msg):
    (oks if cond else erros).append(msg)


icp = json.load(open(ROOT / "dados/icp.json", encoding="utf-8"))
import gerar_icp as g  # noqa: E402
from html import escape as _esc  # noqa: E402
html_esc = lambda s: _esc(s, quote=True)

bases = icp["bases"]
check(len(bases) >= 20, f"ICP com {len(bases)} bases")

# ── status ──
for fid, b in bases.items():
    check(b["status"] in g.STATUS, f"{fid}: status '{b['status']}' é um dos públicos")
    check(b["statusCor"] == g.STATUS[b["status"]][1], f"{fid}: cor do status coerente")
    if b["statusCor"] == "verde":
        uv = b.get("ultimaVerificacao") or {}
        idade = (datetime.now() - datetime.fromisoformat(uv["em"][:19])).days if uv.get("em") else 999
        check(uv.get("resultado") in ("confere", "mudou_na_fonte") and idade <= 30,
              f"{fid}: verde só com conferência na fonte recente (resultado {uv.get('resultado')}, {idade} dias)")
        c = b.get("cobertura") or {}
        check(b["nivel"] >= 3 and c.get("calculavel") and c.get("unidadesConferidas", 0) >= (c.get("unidadesBase") or 10 ** 9),
              f"{fid}: verde só com a base inteira conferida (nível {b['nivel']}, {c.get('unidadesConferidas')} de {c.get('unidadesBase')})")
    if b["status"] == "consistente":
        check(b["testes"]["erros"] == 0 and b["testes"]["ok"] > 0, f"{fid}: 'consistência aprovada' exige testes sem erro")

# ── notas ──
for fid, b in bases.items():
    check(b["nota"] == g.met.nota(b["dimensoes"], b["classe"], b.get("cobertura"), b.get("nivel")), f"{fid}: nota 2.0 recalculada = {b['nota']}")
    check(b.get("notaV1") == g.nota_base(b["dimensoesV1"], b["classe"]), f"{fid}: nota 1.0 preservada para comparação = {b.get('notaV1')}")
    check(b["nota"] is not None, f"{fid}: toda base tem nota 2.0 (nenhuma fica fora da média)")
    for k, v in b["dimensoes"].items():
        check(v is None or 0 <= v <= 100, f"{fid}: dimensão {k} entre 0 e 100")
aval = [b for b in bases.values() if b["nota"] is not None]
geral = round(sum(b["nota"] * b["importancia"] for b in aval) / sum(b["importancia"] for b in aval)) if aval else None
check(icp["nota"] == geral, f"ICP geral recalculado = {geral}")
for k in g.PESOS_DIM:
    xs = [(b["dimensoes"][k], b["importancia"]) for b in bases.values() if b["dimensoes"][k] is not None]
    esp = round(sum(v * w for v, w in xs) / sum(w for _, w in xs)) if xs else None
    check(icp["dimensoes"][k] == esp, f"dimensão geral {k} recalculada = {esp}")

# ── tetos (simulação) ──
cheio = {k: 100 for k in g.PESOS_DIM}
check(g.nota_base(cheio, "verificado") == 100, "tudo 100 e verificado = 100")
check(g.nota_base(cheio, "divergencia") == 40, "divergência limita a 40")
check(g.nota_base(cheio, "falha_coleta") == 50, "falha de coleta limita a 50")
check(g.nota_base(cheio, "revisao_manual") == 70, "revisão manual limita a 70")
check(g.nota_base({**cheio, "P": None}, "importado") == 80, "sem conferência na fonte limita a 80")
check(g.nota_base({"P": 100, "A": 100, "I": 100, "T": None, "R": None, "F": None}, "verificado") is None, "menos de 4 dimensões = não avaliado")
check(g.nota_base({"P": 0, "A": 100, "I": 100, "T": 100, "R": 100, "F": 100}, "verificado") == 70, "precisão 0 derruba 30 pontos")

# ── indicadores ──
I = icp["indicadores"]
conta = lambda st: sum(1 for b in bases.values() if b["status"] == st)
check(I["verificadas"] == sum(1 for b in bases.values() if b["nivel"] >= 3), "indicador verificadas = bases com conferência abrangente")
check(I["conferenciaParcial"] == sum(1 for b in bases.values() if b["nivel"] == 2), "indicador conferência parcial")
check(I["semVerificacaoOficial"] == sum(1 for b in bases.values() if b["nivel"] <= 1), "indicador sem verificação oficial")
check(I["criticos"] == len(icp["criticos"]), "indicador de problemas críticos")
for chave, st in (("aguardando", "aguardando_fonte"), ("divergencias", "divergencia"), ("falhas", "falha_coleta"), ("revisaoManual", "revisao_manual")):
    check(I[chave] == conta(st), f"indicador {chave} = {I[chave]}")
check(I["total"] == len(bases), "indicador total")
check(I["naoAvaliadas"] == sum(1 for b in bases.values() if b["nota"] is None), "indicador não avaliadas")
check(I["pendentesVerificacao"] == sum(1 for b in bases.values() if b["dimensoes"]["P"] is None), "indicador pendentes de verificação")

# ── alertas ──
ids_crit = {c["id"] for c in icp["criticos"]}
for fid, b in bases.items():
    if b["status"] in ("divergencia", "falha_coleta"):
        check(fid in ids_crit, f"{fid}: {b['status']} aparece nos problemas críticos")
    if b["importancia"] >= 2 and any(v is not None and v <= 40 for k, v in b["dimensoes"].items() if k != "I"):  # 2.0: testes rasos vão para os avisos da base
        check(fid in ids_crit, f"{fid}: dimensão ≤ 40 (atualização, precisão, rastreabilidade ou integração) numa base importante aparece nos problemas críticos")
    if b["dimensoes"].get("I") is not None and len(b.get("categoriasTeste") or []) < 5:
        check(any("tipos de conferência" in a for a in b.get("avisosMetodologicos") or []), f"{fid}: testes rasos aparecem nos avisos da base")

# ── falhas (simulação) — os estados vêm de registrar_execucao.py; o detalhe está em tests/test_monitoramento_robos.py ──
import registrar_execucao as rx  # noqa: E402
an = rx.analisar_log("\n".join(f"2026-11-17T22:00:0{i}.1Z {l}" for i, l in enumerate([
    "##[group]Run x", "⚠️ portal da Câmara Municipal de Campo Grande: Connection refused", "⚠️ relatórios: coleta falhou — dados anteriores mantidos",
    "ℹ️ 0 linhas novas", "##[endgroup]"])))
eb = rx.estado_bases("coletar_verba_camara", rx.classificar({"conclusion": "success", "status": "completed"}, "ok", an)[0], an, {})
check(eb.get("camara") == "fonte_indisponivel", "conexão recusada + dado anterior mantido → Câmara de CG 'fonte_indisponivel'")
check(rx.estado_bases("coletar_tjms", "falha_execucao", an, {}) == {"judiciario": "falha_execucao", "supersalarios": "falha_execucao"}, "job 'failure' marca todas as bases dele")
an2 = rx.analisar_log("\n".join(f"2026-11-17T22:00:0{i}.1Z {l}" for i, l in enumerate(["##[group]Run x", "ℹ️ 0 linhas novas", "##[endgroup]"])))
check(rx.classificar({"conclusion": "success", "status": "completed"}, "ok", an2)[0] == "sem_avisos", "mensagem informativa (sem aviso) não vira falha")
_h = g.jsonl("icp_execucoes_historico.jsonl")
_ult = {h.get("runId"): i for i, h in enumerate(_h)}
HIST_EXEC = [h for i, h in enumerate(_h) if _ult.get(h.get("runId")) == i]  # o registro mais recente de cada coleta
for fid, b in bases.items():
    ue = b.get("ultimaExecucao") or {}
    if ue.get("estado") in rx.RUIM:
        check(any(x.startswith("última coleta:") for x in b["pendencias"]), f"{fid}: falha da última coleta aparece nas pendências")
    if ue.get("estado") == "leitura_indisponivel":
        check(any("monitoramento indisponível" in x for x in b["pendencias"]), f"{fid}: log ilegível aparece como monitoramento indisponível")
    check(b["dimensoes"]["F"] == g.dimensao_F(HIST_EXEC, fid), f"{fid}: F recalculado a partir do histórico de execuções")
ex = icp.get("execucao") or {}
check(ex.get("runId") and ex.get("leitura") in ("ok", "parcial", "indisponivel"), "ICP traz o resumo da última execução dos robôs")
check(all(j.get("nAvisos") is None or isinstance(j.get("nAvisos"), int) for j in ex.get("jobs") or []), "avisos = número ou None (não lido), nunca 0 inventado")
check(bases["camaras-ms"]["registros"] and all((ROOT / a).exists() for a in bases["camaras-ms"]["arquivos"]),
      "Câmaras do interior: arquivos de dados existem e a base tem registros")

# ── histórico: só cresce ──
# Nenhuma linha das versões anteriores (últimos 10 commits que mexeram no arquivo) pode sumir da versão atual.
# (Comparar só com o HEAD não basta: no robô o HEAD é o próprio commit da coleta.)
for arq in ("dados/icp_verificacoes.jsonl", "dados/icp_execucoes_historico.jsonl"):
    atual = (ROOT / arq).read_text(encoding="utf-8") if (ROOT / arq).exists() else ""
    linhas = set(atual.splitlines())
    shas = subprocess.run(["git", "-C", str(ROOT), "log", "-10", "--format=%H", "--", arq], capture_output=True, text=True).stdout.split()
    perdidas = 0
    for s in shas:
        p = subprocess.run(["git", "-C", str(ROOT), "show", f"{s}:{arq}"], capture_output=True, text=True)
        if p.returncode == 0:
            perdidas += sum(1 for l in p.stdout.splitlines() if l.strip() and l not in linhas)
    check(perdidas == 0, f"{arq}: nenhuma linha de {len(shas)} versão(ões) anterior(es) foi apagada ({perdidas} perdidas)")
    for n, l in enumerate(atual.splitlines(), 1):
        try:
            json.loads(l)
        except ValueError:
            erros.append(f"{arq}: linha {n} não é JSON válido")
            break

# ── páginas ──
painel = (ROOT / "cofre-aberto-ms.html").read_text(encoding="utf-8")
_ini = painel.index('id="tab-confiabilidade"')
aba = painel[_ini:painel.index('<section class="tabpanel"', _ini + 10)]
check("não é uma certificação oficial" in aba, "aba do ICP diz que não é certificação oficial")
check('id="busca-icp"' in aba and 'id="icp-filtros"' in aba and "data-cartoes" in aba, "aba do ICP tem busca, filtro de status e tabela em cartões no celular")
check('data-tab="confiabilidade"' in painel, "menu lateral do painel tem a aba 'Confiabilidade dos Dados'")
idx = (ROOT / "confiabilidade/index.html").read_text(encoding="utf-8")
check("#aba=confiabilidade" in idx, "/confiabilidade/ abre a aba do painel")
for fid, b in bases.items():
    pg = ROOT / "confiabilidade" / fid / "index.html"
    check(pg.exists(), f"página da base {fid} existe")
    if pg.exists():
        t = pg.read_text(encoding="utf-8")
        if b.get("url"):
            check(b["url"].startswith("http") and html_esc(b["url"]) in t, f"{fid}: link oficial na página")
        for sec in ("Transparência técnica", "Histórico de verificações", "Histórico de correções", "Limitações conhecidas", "Testes matemáticos"):
            check(sec in t, f"{fid}: seção '{sec}'")
mon = (ROOT / "monitoramento/index.html").read_text(encoding="utf-8")
check("#aba=confiabilidade" in mon, "/monitoramento/ redireciona para a aba do ICP")

# ── integração ──
check('carregarJSON("dados/icp.json")' in painel and 'data-icp="${aba}"' in painel, "selo do painel lê icp.json e abre o detalhe da base na aba do ICP")
wf = (ROOT / ".github/workflows/atualizar.yml").read_text(encoding="utf-8")
check("registrar_execucao.py" in wf and "gerar_icp.py" in wf and "actions: read" in wf, "robô registra a execução e recalcula o ICP a cada coleta")
check("confiabilidade/" in wf, "robô publica as páginas /confiabilidade/")

print(f"✅ {len(oks)} checagens OK · ❌ {len(erros)} erros")
for e in erros:
    print("❌", e)
sys.exit(1 if erros else 0)
