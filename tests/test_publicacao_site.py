#!/usr/bin/env python3
"""
Cofre Aberto MS — publicação do site com 2ª tentativa (estrutura do workflow, sem rede)

25/11/2026: o GitHub às vezes não encontra o pacote do site recém-enviado ("No artifacts named github-pages");
4 publicações seguidas falharam e as mudanças não entraram no ar. A publicação tenta de novo depois de 1 minuto.
26/11/2026: causa encontrada — envio e publicação no mesmo job; o deploy consultava a API 0,4 s depois do envio, antes de
o pacote aparecer. Agora: job "montar" envia, job "publicar" (needs: montar) espera o pacote aparecer na API e publica.
Uso: python3 tests/test_publicacao_site.py   (código 1 se algum teste falhar)
"""
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
oks, erros = [], []
check = lambda c, m: (oks if c else erros).append(m)
w = yaml.safe_load(open(ROOT / ".github/workflows/publicar-site.yml", encoding="utf-8"))
j = w["jobs"]["publicar"]
passos = {p.get("id") or p.get("name"): p for p in j["steps"]}
d1, d2 = passos.get("deploy") or {}, passos.get("deploy2") or {}
check(d1.get("uses", "").startswith("actions/deploy-pages") and d1.get("continue-on-error") is True, "1ª tentativa não derruba o job")
check(d2.get("uses", "").startswith("actions/deploy-pages") and d2.get("if") == "steps.deploy.outcome == 'failure'", "2ª tentativa só se a 1ª falhar")
espera = next((p for p in j["steps"] if "sleep 60" in str(p.get("run"))), None)
check(espera is not None and espera.get("if") == "steps.deploy.outcome == 'failure'", "espera de 1 minuto antes da 2ª tentativa")
check("deploy2.outputs.page_url" in j["environment"]["url"], "endereço do site vem da tentativa que deu certo")
check("continue-on-error" not in d2, "se a 2ª também falhar, o job falha (o GitHub avisa)")
m = w["jobs"].get("montar") or {}
check(any("upload-pages-artifact" in str(p.get("uses")) for p in m.get("steps", [])), "o pacote é enviado no job montar")
check(not any("upload-pages-artifact" in str(p.get("uses")) for p in j["steps"]), "o job publicar não envia o pacote (jobs separados)")
check(j.get("needs") == "montar", "publicar espera o job montar terminar")
esp = j["steps"][0]
check("artifacts?name=github-pages" in str(esp.get("run")) and "total_count" in str(esp.get("run")), "antes de publicar, espera o pacote aparecer na API")
check(w["permissions"].get("actions") == "read", "permissão para consultar os pacotes da execução")
for e in erros:
    print("❌", e)
print(f"✅ {len(oks)} checagens OK · ❌ {len(erros)} erros")
sys.exit(1 if erros else 0)
