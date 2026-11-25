#!/usr/bin/env python3
"""
Cofre Aberto MS — Instagram em modo aprovação (decidido em 25/11/2026: nas primeiras 4 semanas, nada é publicado sem o ok
do dono)

Enquanto hoje <= "aprovacaoAte" (instagram/config.json):
  - o robô gera o post da vez e abre uma issue "Instagram: aprovar post de DD/MM (tema)" com as 3 imagens e a legenda,
    com o rótulo "instagram-rascunho"; não publica;
  - aprovar = pôr o rótulo "aprovado" na issue (o workflow roda na hora e publica); recusar = fechar a issue sem o rótulo
    (o tema recusado fica registrado e o próximo rascunho é de outro tema);
  - um rascunho por vez: com issue aberta esperando, não gera outro;
  - rascunho sem resposta por 3 dias: o robô fecha a issue sozinho ("expirado"), registra como recusado e gera outro
    (decidido em 25/11/2026); a vistoria do fim do dia avisa.
Depois de "aprovacaoAte": gera e publica direto, com as mesmas regras de conteúdo (gerar_posts_instagram.py) e no máximo
1 post por dia (publicar_instagram.py).

Uso (no workflow, com GH_TOKEN e GITHUB_REPOSITORY):
  python3 scripts/instagram_aprovacao.py estado        → grava acao=gerar_rascunho|aguardar|publicar_aprovado|publicar_direto
                                                         e issue=N em $GITHUB_OUTPUT
  python3 scripts/instagram_aprovacao.py abrir         → abre a issue do rascunho (instagram/proximo.json)
  python3 scripts/instagram_aprovacao.py fechar N      → comenta o link do post publicado e fecha a issue N
"""
import json, os, subprocess, sys
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent.parent
PASTA = ROOT / "instagram"
ROTULO_RASCUNHO, ROTULO_APROVADO = "instagram-rascunho", "aprovado"
DONO = "fabriciosantosbatista-code"


def cfg():
    try:
        return json.load(open(PASTA / "config.json", encoding="utf-8"))
    except Exception:
        return {}


def em_aprovacao(hoje=None):
    ate = cfg().get("aprovacaoAte")
    return bool(ate) and (hoje or date.today()) <= date.fromisoformat(ate)


def gh(*args, entrada=None):
    r = subprocess.run(["gh", *args], capture_output=True, text=True, input=entrada)
    if r.returncode:
        raise RuntimeError(f"gh {' '.join(args[:2])}: {r.stderr.strip()[:300]}")
    return r.stdout


def issues(estado="open"):
    out = gh("issue", "list", "--repo", os.environ["GITHUB_REPOSITORY"], "--label", ROTULO_RASCUNHO, "--state", estado,
             "--limit", "30", "--json", "number,title,labels,body,createdAt,closedAt")
    return json.loads(out or "[]")


def rotulos(i):
    return {l["name"] for l in i.get("labels") or []}


DIAS_EXPIRA = 3


def expirados(abertas, agora=None):
    """Rascunhos abertos há DIAS_EXPIRA dias ou mais sem o rótulo "aprovado"."""
    agora = agora or datetime.now(timezone.utc)
    out = []
    for i in abertas:
        if ROTULO_APROVADO in rotulos(i):
            continue
        try:
            criado = datetime.fromisoformat(str(i.get("createdAt")).replace("Z", "+00:00"))
        except ValueError:
            continue
        if (agora - criado).total_seconds() >= DIAS_EXPIRA * 86400:
            out.append(i)
    return out


def expirar(i):
    """Fecha o rascunho expirado e registra no histórico (recusado, motivo "expirado")."""
    repo = os.environ["GITHUB_REPOSITORY"]
    gh("issue", "close", str(i["number"]), "--repo", repo, "--comment",
       f"⏰ Fechado sem aprovação depois de {DIAS_EXPIRA} dias (regra de 25/11/2026). O próximo rascunho vem de outro tema.")
    hf = PASTA / "historico.json"
    try:
        hist = json.load(open(hf, encoding="utf-8"))
    except Exception:
        hist = {"publicados": []}
    tema = next((l.split(":", 1)[1].strip() for l in (i.get("body") or "").splitlines() if l.startswith("tema:")), None)
    hist.setdefault("recusados", []).append({"issue": i["number"], "tema": tema, "data": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
                                             "motivo": f"expirado ({DIAS_EXPIRA} dias sem aprovação)"})
    hf.write_text(json.dumps(hist, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"⏰ rascunho expirado: issue #{i['number']} ({tema}) fechada sem aprovação depois de {DIAS_EXPIRA} dias")


def decidir(abertas, hoje=None, aprovacao=None):
    """(acao, issue). Testável sem rede."""
    aprovacao = em_aprovacao(hoje) if aprovacao is None else aprovacao
    if not aprovacao:
        return "publicar_direto", None
    aprovadas = [i for i in abertas if ROTULO_APROVADO in rotulos(i)]
    if aprovadas:
        return "publicar_aprovado", min(i["number"] for i in aprovadas)
    if abertas:
        return "aguardar", min(i["number"] for i in abertas)
    return "gerar_rascunho", None


def registrar_recusados():
    """Rascunhos fechados sem "aprovado" entram em historico.json → recusados (o próximo rascunho é de outro tema)."""
    hf = PASTA / "historico.json"
    try:
        hist = json.load(open(hf, encoding="utf-8"))
    except Exception:
        hist = {"publicados": []}
    feitos = {r.get("issue") for r in hist.get("recusados") or []}
    novos = []
    for i in issues("closed"):
        if ROTULO_APROVADO in rotulos(i) or i["number"] in feitos:
            continue
        tema = next((l.split(":", 1)[1].strip() for l in (i.get("body") or "").splitlines() if l.startswith("tema:")), None)
        novos.append({"issue": i["number"], "tema": tema, "data": (i.get("closedAt") or "")[:19]})
    if novos:
        hist.setdefault("recusados", []).extend(novos)
        hf.write_text(json.dumps(hist, ensure_ascii=False, indent=2), encoding="utf-8")
    return novos


def corpo_issue(p, repo):
    raw = f"https://raw.githubusercontent.com/{repo}/main/instagram"
    imgs = "\n".join(f"![imagem {n}]({raw}/{x})" for n, x in enumerate(p["imagens"], 1))
    return (f"@{DONO} rascunho do post do Instagram para aprovar (modo aprovação até {cfg().get('aprovacaoAte')}).\n\n"
            f"- **Para aprovar:** adicione o rótulo `{ROTULO_APROVADO}` nesta issue — o robô publica em seguida.\n"
            f"- **Para recusar:** feche a issue sem o rótulo — o próximo rascunho vem de outro tema.\n\n"
            f"{imgs}\n\n**Legenda:**\n\n```\n{p['legenda']}\n```\n\n"
            f"**Regras conferidas pelo robô:** {p.get('regras') or '—'}\n\n"
            f"tema: {p['tema']}\nimagens: {', '.join(p['imagens'])}\n")


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "estado"
    repo = os.environ.get("GITHUB_REPOSITORY", "fabriciosantosbatista-code/cofre-aberto-ms")
    if cmd == "estado":
        if em_aprovacao():
            rec = registrar_recusados()
            for r in rec:
                print(f"  rascunho recusado: issue #{r['issue']} ({r['tema']})")
        abertas = issues() if em_aprovacao() else []
        for i in expirados(abertas):
            expirar(i)
            abertas = [x for x in abertas if x["number"] != i["number"]]
        acao, num = decidir(abertas)
        print(f"Instagram: {acao}" + (f" (issue #{num})" if num else ""))
        with open(os.environ.get("GITHUB_OUTPUT", os.devnull), "a") as f:
            f.write(f"acao={acao}\nissue={num or ''}\n")
    elif cmd == "abrir":
        p = json.load(open(PASTA / "proximo.json", encoding="utf-8"))
        for nome, cor, desc in ((ROTULO_RASCUNHO, "c98500", "Rascunho de post do Instagram esperando aprovação"),
                                (ROTULO_APROVADO, "2bb3a3", "Aprovado para publicar")):
            subprocess.run(["gh", "label", "create", nome, "--repo", repo, "--color", cor, "--description", desc], capture_output=True)
        titulo = f"Instagram: aprovar post de {datetime.fromisoformat(p['data']).strftime('%d/%m')} ({p['tema']})"
        url = gh("issue", "create", "--repo", repo, "--title", titulo, "--label", ROTULO_RASCUNHO, "--body-file", "-",
                 entrada=corpo_issue(p, repo)).strip()
        print(f"✅ rascunho para aprovação: {url}")
    elif cmd == "fechar":
        num = sys.argv[2]
        try:
            hist = json.load(open(PASTA / "historico.json", encoding="utf-8"))
            link = (hist.get("publicados") or [{}])[-1].get("link")
        except Exception:
            link = None
        gh("issue", "close", num, "--repo", repo, "--comment", f"✅ Publicado: {link}" if link else "✅ Publicado.")
        print(f"issue #{num} fechada")


if __name__ == "__main__":
    main()
