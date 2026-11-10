#!/usr/bin/env python3
"""
Cofre Aberto MS — coletas que só funcionam a partir de uma conexão no Brasil

O portal do TJMS e os das câmaras de Sonora e Itaporã recusam conexões de
fora do país, inclusive dos servidores do GitHub Actions (EUA). Este script
roda numa máquina no Brasil (ver docs/coleta-brasil.md), agendado por cron,
e grava só os arquivos dessas fontes; o resto continua na coleta diária do
GitHub. As duas coletas não se atropelam: o TJMS do GitHub (via DadosJusBr)
nunca substitui uma folha mais nova, e as câmaras que falham lá mantêm o
arquivo como está.

Uso:  python3 scripts/coleta_brasil.py            (TJMS + Sonora + Itaporã)
      python3 scripts/coleta_brasil.py Sonora     (só as câmaras indicadas)
"""
import re, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import requests
import coletar_dados as cd
import coletar_tjms

CAMARAS_BLOQUEADAS = ["Sonora", "Itaporã"]


def portal_responde(base):
    try:
        r = requests.get(base + "/", headers=cd.HEADERS, timeout=30)
        return r.status_code < 500
    except Exception:
        return False


def descobrir_base_fiorilli(cfg):
    """Procura no site oficial da câmara o link do portal Fiorilli (…/transparenciacm)
    — usado quando o endereço configurado saiu do ar (ex.: Itaporã, jul/2026)."""
    try:
        html = requests.get(cfg["portalOficial"], headers={"User-Agent": "Mozilla/5.0"}, timeout=40).text
    except Exception as e:
        cd.log(f"  site oficial de {cfg['cidade']} não respondeu: {e}")
        return None
    for href in re.findall(r'href=["\']([^"\']+)["\']', html):
        m = re.match(r"(https?://[^\s\"']+?/transparenciacm)", href, re.I)
        if m:
            return m.group(1)
    return None


def main(cidades):
    cd.log("=== Coleta pelo Brasil ===")
    if not cidades or "TJMS" in cidades:
        try:
            coletar_tjms.coletar_tjms()   # tenta o portal oficial primeiro; DadosJusBr só se falhar
        except Exception as e:
            cd.log(f"❌ TJMS: {e}")
    alvo = [c for c in (cidades or CAMARAS_BLOQUEADAS) if c != "TJMS"]
    for cfg in cd.FIORILLI_CAMARAS:
        if cfg["cidade"] not in alvo:
            continue
        cfg = dict(cfg)
        if not portal_responde(cfg["urlBase"]):
            nova = descobrir_base_fiorilli(cfg)
            if nova and nova != cfg["urlBase"]:
                cd.log(f"  {cfg['cidade']}: endereço configurado fora do ar; usando o do site oficial: {nova}")
                cd.log(f"  → atualize 'urlBase' de {cfg['cidade']} em FIORILLI_CAMARAS (scripts/coletar_dados.py)")
                cfg["urlBase"] = nova
        try:
            cd.coletar_camara_fiorilli(cfg)
        except Exception as e:
            cd.log(f"❌ {cfg['cidade']}: {e}")


if __name__ == "__main__":
    main(sys.argv[1:])
