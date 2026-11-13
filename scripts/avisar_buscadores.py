#!/usr/bin/env python3
"""
Cofre Aberto MS — avisa os buscadores (IndexNow: Bing, DuckDuckGo, Yahoo, Yandex) das páginas que mudaram hoje.

Lê o sitemap.xml e envia as URLs com lastmod de hoje para api.indexnow.org. A chave
fica no arquivo /a6c43339621944defe82ee379f985ec0.txt na raiz do site (é o que prova que o site é nosso; não é segredo).
Roda no robô diário depois do push. O Google não usa IndexNow: para ele, o sitemap e o Search Console.
"""

import re, sys
from datetime import date
from pathlib import Path

import requests

ROOT = Path(__file__).parent.parent
SITE = "https://cofreabertoms.com.br"
CHAVE = "a6c43339621944defe82ee379f985ec0"


def main():
    hoje = date.today().isoformat()
    sm = (ROOT / "sitemap.xml").read_text(encoding="utf-8")
    urls = [u for u, d in re.findall(r"<loc>([^<]+)</loc><lastmod>([^<]+)</lastmod>", sm) if d.startswith(hoje)]
    if "--tudo" in sys.argv:
        urls = re.findall(r"<loc>([^<]+)</loc>", sm)
    if not urls:
        print("  nenhuma página mudou hoje — nada a avisar")
        return
    r = requests.post("https://api.indexnow.org/indexnow", timeout=60, json={
        "host": "cofreabertoms.com.br", "key": CHAVE, "keyLocation": f"{SITE}/{CHAVE}.txt", "urlList": urls[:10000]})
    print(f"{'✅' if r.status_code in (200, 202) else '⚠️'} IndexNow: {len(urls[:10000])} páginas avisadas (HTTP {r.status_code})")


if __name__ == "__main__":
    main()
