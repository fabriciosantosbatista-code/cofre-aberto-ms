#!/usr/bin/env python3
"""
Cofre Aberto MS — monta a pasta do site publicado (_site/) só com o que está em .github/site.txt

Usado pelo workflow publicar-site.yml (actions/deploy-pages). Só copia arquivos rastreados pelo Git (nada de
privado/, folha_completa/ ou arquivos locais). Para com erro se um item da lista não existir, se sobrar algum .md
ou se uma URL do sitemap não tiver arquivo.

Uso: python3 scripts/montar_site.py [_site]
"""
import re, shutil, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LISTA = ROOT / ".github" / "site.txt"


def itens():
    return [l.strip() for l in LISTA.read_text(encoding="utf-8").splitlines() if l.strip() and not l.lstrip().startswith("#")]


def rastreados():
    out = subprocess.run(["git", "-C", str(ROOT), "ls-files", "-z"], capture_output=True, check=True).stdout.decode()
    return [x for x in out.split("\0") if x]


def selecionados():
    lst, git = itens(), rastreados()
    faltam = [i for i in lst if not any(f == i or f.startswith(i + "/") for f in git)]
    if faltam:
        raise SystemExit(f"❌ itens de .github/site.txt que não existem no repositório: {faltam}")
    return sorted(f for f in git if any(f == i or f.startswith(i + "/") for i in lst))


def montar(destino):
    destino = Path(destino)
    if destino.exists():
        shutil.rmtree(destino)
    arquivos = selecionados()
    md = [f for f in arquivos if f.lower().endswith(".md")]
    if md:
        raise SystemExit(f"❌ arquivo .md iria para o ar: {md[:5]}")
    for f in arquivos:
        (destino / f).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / f, destino / f)
    # toda URL do sitemap tem de existir no site montado
    sm = (destino / "sitemap.xml").read_text(encoding="utf-8")
    sem = []
    for u in re.findall(r"<loc>https://cofreabertoms\.com\.br/([^<]*)</loc>", sm):
        p = u.split("#")[0]
        alvo = destino / p / "index.html" if (p == "" or p.endswith("/")) else destino / p
        if not alvo.exists():
            sem.append(u)
    if sem:
        raise SystemExit(f"❌ {len(sem)} URL(s) do sitemap sem arquivo no site montado: {sem[:5]}")
    print(f"✅ site montado em {destino}: {len(arquivos)} arquivos; {sm.count('<loc>')} URLs do sitemap conferidas")
    return arquivos


if __name__ == "__main__":
    montar(sys.argv[1] if len(sys.argv) > 1 else ROOT / "_site")
