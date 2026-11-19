#!/usr/bin/env python3
"""
Cofre Aberto MS — testes da contenção de dados pessoais (Fase 1)

  artefatos   todo envio de artefato do robô de dados vem logo depois de "mascarar_cpf.py && tests/test_cpf.py" (sem "|| echo"),
              e um envio com always() só acontece se esse passo deu certo; nenhum artefato com retenção acima de 30 dias
  PDFs        os PDFs da Câmara só vão para o artefato se forem novos (pdfs_novos.py antes do envio): simulação com PDFs
              falsos e um manifesto anterior — os já guardados saem da pasta temporária, os novos ficam
  privado     a pasta privado/ (e backups/chaves) está no .gitignore do projeto, nada dela é rastreado e um arquivo novo
              dentro dela é ignorado

Uso: python3 tests/test_contencao.py   (código 1 se algum teste falhar)
"""

import hashlib, json, subprocess, sys, tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
oks, erros = [], []


def check(c, m):
    (oks if c else erros).append(m)


# ── artefatos ──
WF = sys.argv[sys.argv.index("--workflow") + 1] if "--workflow" in sys.argv else ROOT / ".github/workflows/atualizar.yml"
wf = yaml.safe_load(open(WF, encoding="utf-8"))
for job, j in wf["jobs"].items():
    passos = j.get("steps") or []
    for i, s in enumerate(passos):
        if "upload-artifact" not in str(s.get("uses", "")):
            continue
        nome = s["with"]["name"]
        ret = int(s["with"].get("retention-days", 90))
        if nome.startswith("folha-supersalarios"):
            # decisão do responsável (19/11/2026): folha completa por 90 dias, só cifrada (artefato de repositório público é
            # baixável por qualquer usuário logado), e só se a checagem (que varre CPF) passou
            check(ret <= 90, f"{job} · {nome}: retenção {ret} dias (≤ 90, decisão registrada)")
            ids = {x.get("id"): x for x in passos if x.get("id")}
            cond = str(s.get("if", ""))
            check(any(f"steps.{k}.outcome == 'success'" in cond and "checagem_automatica.py" in str(v.get("run", "")) for k, v in ids.items()),
                  f"{job} · {nome}: só sobe se a checagem automática (detector de CPF) passou")
            check(str(s["with"].get("path", "")).strip() == "artefato_cifrado/folha-supersalarios.tar.gpg"
                  and "cifrar_artefato.sh folha_completa" in str(passos[i - 1].get("run", "")),
                  f"{job} · {nome}: só a folha_completa/ CIFRADA (.gpg feito por cifrar_artefato.sh no passo anterior)")
        else:
            check(ret <= 30, f"{job} · {nome}: retenção {ret} dias (≤ 30)")
        if nome.startswith("dados-"):
            ant = passos[i - 1]
            run = str(ant.get("run", ""))
            check("mascarar_cpf.py" in run and "tests/test_cpf.py" in run and "|| echo" not in run,
                  f"{job} · {nome}: logo antes do envio, máscara E detector de CPF, sem '|| echo'")
            if "always()" in str(s.get("if", "")):
                check(ant.get("id") and f"steps.{ant['id']}.outcome == 'success'" in str(s["if"]),
                      f"{job} · {nome}: envio com always() exige o passo de máscara/detector bem-sucedido")
        if nome.startswith("pdfs-camara-cg"):
            check("pdfs_novos.py" in str(passos[i - 2].get("run", "")) and "cifrar_artefato.sh pdfs_camara_cg" in str(passos[i - 1].get("run", ""))
                  and str(s["with"].get("path", "")).strip().endswith(".gpg"),
                  f"{job} · {nome}: só PDFs novos (pdfs_novos.py) e CIFRADOS (cifrar_artefato.sh) antes do envio")
        if nome.startswith("coleta-bloqueada"):
            check("bloqueio/" in str(s["with"].get("path", "")), f"{job} · {nome}: evidências só da pasta bloqueio/")

# ── PDFs: simulação ──
with tempfile.TemporaryDirectory() as tmp:
    pasta = Path(tmp) / "pdfs"; pasta.mkdir()
    velhos = [b"%PDF-1.4 velho " + bytes([i]) for i in range(3)]
    novos = [b"%PDF-1.4 novo " + bytes([i]) for i in range(2)]
    for i, c in enumerate(velhos + novos):
        (pasta / f"doc{i}.pdf").write_bytes(c)
    man = Path(tmp) / "manifesto.json"
    man.write_text(json.dumps({hashlib.sha256(c).hexdigest(): {"arquivo": "x"} for c in velhos}), encoding="utf-8")
    p = subprocess.run([sys.executable, str(ROOT / "scripts/pdfs_novos.py"), "--pasta", str(pasta), "--manifesto-anterior", str(man)],
                       capture_output=True, text=True)
    sobrou = {f.read_bytes() for f in pasta.iterdir()}
    check(p.returncode == 0 and sobrou == set(novos), f"PDFs: ficam só os 2 novos, saem os 3 já guardados ({len(sobrou)} na pasta)")
    for f in pasta.iterdir():
        f.unlink()
    man.write_text("{}", encoding="utf-8")
    (pasta / "a.pdf").write_bytes(b"%PDF primeira vez")
    subprocess.run([sys.executable, str(ROOT / "scripts/pdfs_novos.py"), "--pasta", str(pasta), "--manifesto-anterior", str(man)], capture_output=True)
    check((pasta / "a.pdf").exists(), "PDFs: sem manifesto anterior (1ª coleta), todos os PDFs são guardados")
p = subprocess.run([sys.executable, str(ROOT / "scripts/pdfs_novos.py"), "--pasta", "/caminho/que/nao/existe"], capture_output=True, text=True)
check(p.returncode == 0, "PDFs: sem pasta de PDFs na coleta, o passo não falha")

# ── privado/ ──
gi = (ROOT / ".gitignore").read_text(encoding="utf-8")
check("/privado/" in gi.split(), ".gitignore protege a pasta privado/ inteira")
for f in ("privado/DIAGNOSTICO_LIMPEZA_HISTORICO_GIT.md", "privado/MAPA_HASHES_PROPOSTO.csv", "privado/qualquer/arquivo_futuro.txt",
          "backup.bundle", "backup.bundle.age", "chave-backup-cofre.txt"):
    r = subprocess.run(["git", "-C", str(ROOT), "check-ignore", "-q", "--no-index", f])
    check(r.returncode == 0, f"ignorado pelo Git: {f}")
check(subprocess.run(["git", "-C", str(ROOT), "ls-files", "privado/"], capture_output=True, text=True).stdout.strip() == "",
      "nenhum arquivo de privado/ rastreado pelo Git")
check(subprocess.run(["git", "-C", str(ROOT), "ls-files", "-ci", "--exclude-standard"], capture_output=True, text=True).stdout.strip() == "",
      "as regras novas do .gitignore não escondem nenhum arquivo já rastreado")

print(f"✅ {len(oks)} checagens OK · ❌ {len(erros)} erros")
for e in erros:
    print("❌", e)
sys.exit(1 if erros else 0)
