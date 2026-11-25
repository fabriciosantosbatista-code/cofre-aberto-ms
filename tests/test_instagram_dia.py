#!/usr/bin/env python3
"""
Cofre Aberto MS — Instagram: post depois da coleta do dia, horário agendado só como reserva (casos simulados, sem rede)

Regra de 26/11/2026: o workflow roda quando a coleta do dia termina (workflow_run) e publica se ela publicou com
sucesso; o horário das 11h47 de Campo Grande é reserva (encerra se o post do dia já saiu; se a coleta falhou, publica
com os dados do dia anterior). "Hoje" é o dia de Campo Grande. Depois de gravar as imagens, o workflow dispara a
publicação do site (o commit do robô não dispara "push").
Uso: python3 tests/test_instagram_dia.py   (código 1 se algum teste falhar)
"""
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import publicar_instagram as pi  # noqa: E402

oks, erros = [], []
check = lambda c, m: (oks if c else erros).append(m)
# 26/11 01h40 em Campo Grande = 05h40 UTC (coleta das 04h37 UTC terminando)
madrugada = datetime(2026, 11, 26, 5, 40, tzinfo=timezone.utc)
ontem = {"publicados": [{"tema": "shows", "data": "2026-11-25T19:19:43", "link": "https://www.instagram.com/p/x/"}]}
hoje = {"publicados": ontem["publicados"] + [{"tema": "obras", "data": "2026-11-26T05:52:00", "link": "https://www.instagram.com/p/y/"}]}
ok_pub = {"runId": "777", "resultado": "publicado"}

check(pi.hoje_cg(madrugada) == "2026-11-26", "dia de Campo Grande")
check(pi.dia_cg("2026-11-26T03:30:00") == "2026-11-25", "registro às 03h30 UTC é do dia anterior em Campo Grande")
check(pi.decidir_dia("workflow_run", ontem, ok_pub, "777", madrugada)[0], "coleta publicou → posta")
check(pi.decidir_dia("workflow_run", ontem, {"runId": "777", "resultado": "publicado_parcial"}, "777", madrugada)[0], "publicação parcial também vale")
s, m = pi.decidir_dia("workflow_run", ontem, {"runId": "777", "resultado": "bloqueado"}, "777", madrugada)
check(not s and "reserva" in m, f"publicação bloqueada → fica para a reserva: {m}")
check(not pi.decidir_dia("workflow_run", ontem, {"runId": "123", "resultado": "publicado"}, "777", madrugada)[0], "icp_publicacao.json de outra execução não vale")
check(not pi.decidir_dia("workflow_run", hoje, ok_pub, "777", madrugada)[0], "2ª coleta no mesmo dia não gera outro post")
s, m = pi.decidir_dia("schedule", hoje, None, None, madrugada)
check(not s and "reserva encerrada" in m, f"reserva encerra se o post de hoje já saiu: {m}")
check(pi.decidir_dia("schedule", ontem, None, None, madrugada)[0], "reserva publica se o post de hoje não saiu (coleta falhou)")
check(pi.decidir_dia("workflow_dispatch", hoje, None, None, madrugada)[0], "manual segue as regras de sempre (o limite de 1 por dia continua no publicador)")
check(pi.post_de_hoje(hoje, madrugada)["tema"] == "obras" and pi.post_de_hoje(ontem, madrugada) is None, "post de hoje pelo dia de Campo Grande")

w = yaml.safe_load(open(ROOT / ".github/workflows/instagram.yml", encoding="utf-8"))
on = w[True]
check(on.get("workflow_run", {}).get("workflows") == ["Atualizar dados diariamente"] and "schedule" in on, "gatilhos: fim da coleta + horário de reserva")
j = w["jobs"]["post"]
check("github.event.workflow_run.conclusion == 'success'" in j["if"], "depois da coleta, só se ela terminou com sucesso")
passos = {p.get("name"): p for p in j["steps"]}
dia = next(p for p in j["steps"] if p.get("id") == "dia")
check("--dia" in dia["run"] and "workflow_run.id" in str(dia.get("env")), "passo que decide o dia recebe o evento e a execução da coleta")
check("steps.dia.outputs.seguir == '1'" in passos["Modo aprovação — o que fazer hoje"]["if"], "sem 'seguir', não gera nem publica")
img = passos["Publicar as imagens no site"]
check("gh workflow run publicar-site.yml" in img["run"] and w["permissions"].get("actions") == "write", "depois de gravar as imagens, dispara a publicação do site")

for e in erros:
    print("❌", e)
print(f"✅ {len(oks)} checagens OK · ❌ {len(erros)} erros")
sys.exit(1 if erros else 0)
