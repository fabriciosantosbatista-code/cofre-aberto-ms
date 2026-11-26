#!/usr/bin/env python3
"""
Cofre Aberto MS — Instagram: post às 11h47 de Campo Grande pelo disparo externo; agendamento do GitHub como reserva
(casos simulados, sem rede)

Regra de 26/11/2026 (o dono não quer post de madrugada): o Cloudflare Worker cofre-disparo-coleta tem 2 crons —
"37 4 * * *" dispara a coleta (atualizar.yml) e "47 15 * * *" dispara o Instagram (instagram.yml), ambos com
origem "externo"; o worker escolhe o workflow por event.cron. O Instagram não roda mais logo depois da coleta. O
agendamento do GitHub é reserva: encerra se o post do dia já saiu. Sem coleta publicada até 11h47, posta com os dados
que estão no site. "Hoje" é o dia de Campo Grande. Depois de gravar as imagens, o workflow dispara a publicação do site.
Uso: python3 tests/test_instagram_dia.py   (código 1 se algum teste falhar)
"""
import json, re, shutil, subprocess, sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import publicar_instagram as pi  # noqa: E402

oks, erros = [], []
check = lambda c, m: (oks if c else erros).append(m)
onze47 = datetime(2026, 11, 26, 15, 47, tzinfo=timezone.utc)  # 11h47 em Campo Grande
ontem = {"publicados": [{"tema": "shows", "data": "2026-11-25T19:19:43", "link": "https://www.instagram.com/p/x/"}]}
hoje = {"publicados": ontem["publicados"] + [{"tema": "obras", "data": "2026-11-26T15:48:30", "link": "https://www.instagram.com/p/y/"}]}

check(pi.hoje_cg(onze47) == "2026-11-26", "dia de Campo Grande")
check(pi.dia_cg("2026-11-26T03:30:00") == "2026-11-25", "registro às 03h30 UTC é do dia anterior em Campo Grande")
s, m = pi.decidir_dia("externo", ontem, onze47)
check(s and "dados que estão no site" in m, f"disparo externo das 11h47 posta com os dados do site: {m}")
check(not pi.decidir_dia("externo", hoje, onze47)[0], "disparo externo não repete o post do dia")
s, m = pi.decidir_dia("schedule", hoje, onze47)
check(not s and "encerrado" in m, f"reserva do GitHub encerra se o post de hoje já saiu: {m}")
check(pi.decidir_dia("schedule", ontem, onze47)[0], "reserva publica se o disparo externo falhou")
check(pi.decidir_dia("workflow_dispatch", hoje, onze47)[0], "manual segue as regras de sempre (o limite de 1 por dia continua no publicador)")
check(pi.post_de_hoje(hoje, onze47)["tema"] == "obras" and pi.post_de_hoje(ontem, onze47) is None, "post de hoje pelo dia de Campo Grande")

w = yaml.safe_load(open(ROOT / ".github/workflows/instagram.yml", encoding="utf-8"))
on = w[True]
check("workflow_run" not in on, "o Instagram não roda mais logo depois da coleta")
check([c["cron"] for c in on["schedule"]] == ["47 15 * * *", "0 23 * * *"], "reservas do GitHub às 15h47 e 23h00 UTC")
check("origem" in on["workflow_dispatch"]["inputs"], "aceita a entrada origem (o worker manda origem=externo)")
dia = next(p for p in w["jobs"]["post"]["steps"] if p.get("id") == "dia")
check("--dia" in dia["run"] and "inputs.origem == 'externo'" in dia["env"]["EVENTO"], "o passo do dia distingue o disparo externo")
passos = {p.get("name"): p for p in w["jobs"]["post"]["steps"]}
check("steps.dia.outputs.seguir == '1'" in passos["Modo aprovação — o que fazer hoje"]["if"], "sem 'seguir', não gera nem publica")
img = passos["Publicar as imagens no site"]
check("gh workflow run publicar-site.yml" in img["run"] and w["permissions"].get("actions") == "write", "depois de gravar as imagens, dispara a publicação do site")

# worker: cada cron dispara o seu workflow, com origem externo
js = (ROOT / "infra/cloudflare-worker/disparo-coleta.js").read_text(encoding="utf-8")
mapa = dict(re.findall(r'"([0-9*/ ,-]+)":\s*\{\s*workflow:\s*"([a-z-]+\.yml)"', js))
check(mapa == {"37 4 * * *": "atualizar.yml", "47 15 * * *": "instagram.yml", "0 23 * * *": "instagram.yml"}, f"worker: crons → workflows {mapa}")
check("DISPAROS[event.cron]" in js and 'origem: "externo"' in js, "worker escolhe o workflow por event.cron e manda origem=externo")
ig_crons = sorted(c for c, wf in mapa.items() if wf == "instagram.yml")
check(ig_crons == sorted(c["cron"] for c in on["schedule"]), "crons do worker e reservas do GitHub nos mesmos horários (11h47 e 19h00)")
if shutil.which("node"):  # o worker carrega e despacha certo (fetch simulado)
    prog = (js.replace("export default", "const W =") + """
const chamadas = []; globalThis.fetch = async (u, o) => { chamadas.push([u, JSON.parse(o.body)]); return { status: 204 }; };
const ctx = { waitUntil: (p) => p };
(async () => {
  await W.scheduled({ cron: "37 4 * * *" }, { GH_TOKEN: "x" }, { waitUntil: async (p) => await p });
  await W.scheduled({ cron: "47 15 * * *" }, { GH_TOKEN: "x" }, { waitUntil: async (p) => await p });
  let erro = ""; try { await W.scheduled({ cron: "0 0 * * *" }, {}, ctx); } catch (e) { erro = e.message; }
  await new Promise((r) => setTimeout(r, 50));
  console.log(JSON.stringify({ chamadas, erro }));
})();
""")
    r = subprocess.run(["node", "-e", prog], capture_output=True, text=True)
    try:
        out = json.loads(r.stdout.strip().splitlines()[-1])
        urls = [c[0].rsplit("/workflows/", 1)[1] for c in out["chamadas"]]
        check(urls == ["atualizar.yml/dispatches", "instagram.yml/dispatches"] and all(c[1]["inputs"]["origem"] == "externo" for c in out["chamadas"]),
              f"worker (node): 04h37 → coleta, 15h47 → Instagram: {urls}")
        check("sem workflow associado" in out["erro"], "worker (node): cron desconhecido não dispara nada")
    except Exception as e:
        check(False, f"worker (node) não rodou: {e} {r.stderr[:200]}")

# dois horários por dia (26/11/2026): 11h47 e 19h00 de Campo Grande, 1 post por horário, 2 por dia
noite = datetime(2026, 11, 26, 23, 0, tzinfo=timezone.utc)   # 19h00 em Campo Grande
check(pi.horario(onze47) == "manhã" and pi.horario(noite) == "noite", "horários manhã/noite pelo relógio de Campo Grande")
s1 = pi.decidir_dia("externo", hoje, noite)
check(s1[0], f"19h: o post da manhã já saiu, o da noite ainda não — publica: {s1[1]}")
dois = {"publicados": hoje["publicados"] + [{"tema": "shows", "data": "2026-11-26T23:00:40", "link": "z"}]}
check(not pi.decidir_dia("externo", dois, noite)[0], "19h: o post da noite já saiu — não repete")
check(not pi.decidir_dia("schedule", dois, noite, cron="0 23 * * *")[0], "reserva das 19h encerra se o post da noite já saiu")
s2 = pi.decidir_dia("schedule", hoje, noite, cron="47 15 * * *")
check(not s2[0] and "atrasada" in s2[1], f"reserva da manhã que roda atrasada à noite não publica no lugar do post da noite: {s2[1]}")
check(pi.decidir_dia("schedule", ontem, noite, cron="0 23 * * *")[0], "reserva das 19h publica se o disparo externo falhou")
src = (ROOT / "scripts" / "publicar_instagram.py").read_text(encoding="utf-8")
check("post_do_horario(hist)" in src and "MAX_POR_DIA" in src, "publicador: no máximo 1 por horário e 2 por dia")

for e in erros:
    print("❌", e)
print(f"✅ {len(oks)} checagens OK · ❌ {len(erros)} erros")
sys.exit(1 if erros else 0)
