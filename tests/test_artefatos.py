#!/usr/bin/env python3
"""
Cofre Aberto MS — nenhum artefato do Actions com dado pessoal sem criptografia

Artefato de repositório público é baixável por qualquer usuário logado no GitHub. Este teste lê todos os workflows e
falha se algum upload-artifact enviar um caminho marcado como sensível em config/artefatos_sensiveis.json (ou uma
pasta/curinga que o inclua, como "dados/**" incluindo uma pasta sensível, ou "." ) sem que o que vai no artefato seja
um arquivo .gpg/.age criptografado num passo anterior do mesmo job. O pacote do site (upload-pages-artifact) é público
por definição e é conferido por scripts/montar_site.py.

Uso: python3 tests/test_artefatos.py   (código 1 se algum teste falhar)
"""
import fnmatch, glob, json, re, sys
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parent.parent
SENS = json.load(open(ROOT / "config/artefatos_sensiveis.json", encoding="utf-8"))["sensiveis"]
oks, erros = [], []
import subprocess
RASTREADOS = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True).stdout.splitlines()
CRIPTO = re.compile(r"scripts/cifrar_artefato\.sh|\bgpg\b[^\n]*--symmetric|\bgpg\b[^\n]*(-c|--encrypt)\b|\bage\b[^\n]*(-r|-R|--recipient|-p|--passphrase)\b")


def caminhos(st):
    p = (st.get("with") or {}).get("path") or ""
    return [l.strip() for l in str(p).splitlines() if l.strip()]


def toca(caminho, sens):
    """O caminho enviado inclui o sensível? (igual, pasta que o contém, curinga que casa, ou o sensível é um curinga)"""
    c = caminho.lstrip("./")
    s = sens.lstrip("./")
    if c.startswith("!"):
        return False
    if c in ("", "*", "**") or caminho in (".", "./"):
        return True
    if s.startswith("*"):  # curinga de extensão: o caminho casa, ou a pasta enviada tem (no Git) arquivo desse tipo
        if fnmatch.fnmatch(c, s) or fnmatch.fnmatch(c, "*" + s):
            return True
        base = c.split("*")[0].rstrip("/")
        return bool(base) and any(fnmatch.fnmatch(x, s) for x in RASTREADOS if x.startswith(base + "/"))
    if c.rstrip("/") == s.rstrip("/") or c.startswith(s) or s.startswith(c.rstrip("*").rstrip("/") + "/"):
        return True
    return fnmatch.fnmatch(s, c) or fnmatch.fnmatch(s.rstrip("/"), c)


def criptografado(caminho):
    return caminho.rstrip("/").endswith((".gpg", ".age"))


for f in sorted(glob.glob(str(ROOT / ".github/workflows/*.yml"))):
    w = yaml.safe_load(open(f, encoding="utf-8"))
    for jn, j in (w.get("jobs") or {}).items():
        antes = ""
        for st in j.get("steps") or []:
            antes += "\n" + str(st.get("run") or "")
            if "upload-artifact" not in str(st.get("uses") or ""):
                continue
            nome = (st.get("with") or {}).get("name")
            for c in caminhos(st):
                ruins = [s for s in SENS if toca(c, s["caminho"])]
                rot = f"{Path(f).name} · {jn} · artefato {nome!r} · {c}"
                if not ruins:
                    oks.append(rot)
                elif criptografado(c) and CRIPTO.search(antes):
                    oks.append(rot + " (criptografado)")
                else:
                    erros.append(rot + " — sem criptografia: " + "; ".join(s["motivo"] for s in ruins))

# a cifragem usada pelo robô: senha só pelo descritor 3 (nunca na linha de comando) e conferência do arquivo cifrado
cif = open(ROOT / "scripts/cifrar_artefato.sh", encoding="utf-8").read()
for cond, rot in [("--passphrase-fd 3" in cif and "--passphrase " not in cif, "cifrar_artefato.sh: senha pelo descritor 3, nunca em --passphrase"),
                  ("--cipher-algo AES256" in cif, "cifrar_artefato.sh: AES-256"),
                  ("PGP symmetric key encrypted" in cif and "! -name '*.gpg'" in cif, "cifrar_artefato.sh: falha se sobrar arquivo não cifrado ou se a saída não for OpenPGP cifrado"),
                  (not re.search(r"(echo|printf)[^\n]*\$\{?ARTEFATO_CHAVE[^\n]*$", "\n".join(l for l in cif.splitlines() if "3<" not in l), re.M),
                   "cifrar_artefato.sh: a senha só é lida pelo descritor 3 do gpg (nenhum echo/printf a imprime)")]:
    (oks if cond else erros).append(rot)

# o próprio teste precisa reconhecer os casos que deve barrar
for c, s, esperado in [("pdfs_camara_cg/", "pdfs_camara_cg/", True), ("folha_completa/", "folha_completa/", True),
                       (".", "folha_completa/", True), ("dados/governo_ms.json", "folha_completa/", False),
                       ("saida/paginas/", "saida/", True), ("paginas/p1.png", "*.png", True), ("dados/camara_municipal.json", "*.png", False),
                       ("pdfs/*.pdf", "*.pdf", True), ("artefato_cifrado/", "artefato_cifrado/", True), ("dados/historico_*_camara_cg.json", "*.pdf", False), ("folha_completa/folha.jsonl.gz.gpg", "folha_completa/", True)]:
    (oks if toca(c, s) == esperado else erros).append(f"regra: {c} × {s} → {'sensível' if esperado else 'livre'}")

for e in erros:
    print("❌", e)
print(f"✅ {len(oks)} checagens OK · ❌ {len(erros)} erros")
sys.exit(1 if erros else 0)
