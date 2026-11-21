#!/usr/bin/env python3
"""Cofre Aberto MS — saúde do disparo externo da coleta (Cloudflare Worker). Usado pela vistoria da manhã.
Imprime uma linha por item: ✅ / ⚠️. Código 1 se houver aviso. Só leitura (gh api)."""
import json, subprocess, sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
cfg = json.load(open(ROOT / "config/disparo_externo.json", encoding="utf-8"))
avisos = []
vence = cfg.get("tokenVenceEm")
if not vence:
    avisos.append("⚠️ disparo externo: data de vencimento do token não informada (config/disparo_externo.json → tokenVenceEm)")
else:
    faltam = (date.fromisoformat(vence) - date.today()).days
    if faltam < 0:
        avisos.append(f"⚠️ disparo externo: o token GH_TOKEN VENCEU em {vence} — a coleta principal não está sendo disparada; renove")
    elif faltam <= int(cfg.get("avisarDiasAntes") or 30):
        avisos.append(f"⚠️ disparo externo: o token GH_TOKEN vence em {faltam} dia(s) ({vence}) — renove e atualize tokenVenceEm")
    else:
        print(f"✅ disparo externo: token válido até {vence} ({faltam} dias)")
try:
    runs = json.loads(subprocess.run(["gh", "api", "repos/fabriciosantosbatista-code/cofre-aberto-ms/actions/workflows/atualizar.yml/runs?event=workflow_dispatch&per_page=20"],
                                     capture_output=True, text=True, check=True).stdout)["workflow_runs"]
    ext = [r for r in runs if "externo" in (r.get("display_title") or "")]
    if not ext:
        avisos.append("⚠️ disparo externo: nenhuma coleta com origem \"externo\" encontrada")
    else:
        idade = datetime.now(timezone.utc) - datetime.fromisoformat(ext[0]["created_at"].replace("Z", "+00:00"))
        (avisos.append if idade > timedelta(hours=26) else (lambda m: print(m)))(
            f"{'⚠️' if idade > timedelta(hours=26) else '✅'} disparo externo: último em {ext[0]['created_at']} ({idade.total_seconds() / 3600:.0f} h atrás) — {ext[0]['conclusion'] or ext[0]['status']}")
except Exception as e:
    avisos.append(f"⚠️ disparo externo: não consegui consultar as execuções ({type(e).__name__})")
for a in avisos:
    print(a)
sys.exit(1 if avisos else 0)
