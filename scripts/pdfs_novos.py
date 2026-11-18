#!/usr/bin/env python3
"""
Cofre Aberto MS — deixa em pdfs_camara_cg/ só os PDFs da Câmara de CG que ainda NÃO tinham sido guardados

O coletor (coletar_verba_camara_cg.py) copia para pdfs_camara_cg/ todos os PDFs lidos na coleta, e o robô guarda essa pasta
como artefato. Como os mesmos PDFs são lidos de novo a cada coleta, o robô acumulava uma cópia completa (58 PDFs, ~584 MB)
por execução. Os PDFs podem conter CPF impresso (são documentos oficiais digitalizados) e não passam pela máscara.

Este script compara o SHA-256 de cada PDF da pasta com o manifesto da coleta ANTERIOR (dados/camara_cg_pdfs.json no commit
atual, HEAD — o manifesto é indexado pelo SHA-256) e apaga da pasta TEMPORÁRIA do robô os que já constavam: assim só os PDFs
novos vão para o artefato. Não mexe no manifesto, nos dados nem na fonte oficial; o coletor já leu todos os PDFs antes.

Uso: python3 scripts/pdfs_novos.py [--pasta pdfs_camara_cg] [--manifesto-anterior ARQUIVO]
"""

import hashlib, json, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def arg(nome, padrao):
    return sys.argv[sys.argv.index(nome) + 1] if nome in sys.argv else padrao


def manifesto_anterior(caminho=None):
    if caminho:
        return json.load(open(caminho, encoding="utf-8"))
    p = subprocess.run(["git", "-C", str(ROOT), "show", "HEAD:dados/camara_cg_pdfs.json"], capture_output=True, text=True)
    return json.loads(p.stdout) if p.returncode == 0 and p.stdout.strip() else {}


def main():
    pasta = Path(arg("--pasta", str(ROOT / "pdfs_camara_cg")))
    if not pasta.is_dir():
        print("ℹ️ nenhuma pasta de PDFs nesta coleta")
        return 0
    ja = set(manifesto_anterior(arg("--manifesto-anterior", None)))
    novos = removidos = 0
    for f in sorted(pasta.rglob("*")):
        if not f.is_file():
            continue
        h = hashlib.sha256(f.read_bytes()).hexdigest()
        if h in ja:
            f.unlink()
            removidos += 1
        else:
            novos += 1
    print(f"✅ PDFs da Câmara: {novos} novo(s) vão para o artefato · {removidos} já guardado(s) antes, fora do artefato")
    return 0


if __name__ == "__main__":
    sys.exit(main())
