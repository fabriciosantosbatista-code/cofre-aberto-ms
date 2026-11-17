#!/usr/bin/env python3
"""
Cofre Aberto MS — publica no Instagram o post preparado por gerar_posts_instagram.py (instagram/proximo.json)

API oficial do Instagram com login do Instagram (graph.instagram.com), sem página do Facebook:
  1. cria um contêiner para cada imagem do carrossel (a imagem precisa estar num endereço público: o site)
  2. cria o contêiner do carrossel com a legenda e espera ficar pronto
  3. publica

Segredos do GitHub (Settings → Secrets and variables → Actions):
  IG_TOKEN   chave de acesso de longa duração da conta do Instagram (vale 60 dias e é renovada aqui a cada execução)
  GH_PAT     opcional: chave do GitHub com permissão de gravar Secrets neste repositório, para guardar a chave renovada
             do Instagram. Sem ela, a renovação só funciona enquanto a chave atual valer — o aviso aparece no log.

Sem IG_TOKEN, não publica nada (só avisa). Grava o resultado em instagram/historico.json.
"""

import json, os, subprocess, sys, time
from datetime import datetime
from pathlib import Path

import requests

ROOT = Path(__file__).parent.parent
PASTA = ROOT / "instagram"
API = "https://graph.instagram.com/" + os.environ.get("IG_API_VERSAO", "v23.0")


def chamar(metodo, caminho, token, **params):
    r = requests.request(metodo, f"{API}/{caminho}", params={**params, "access_token": token}, timeout=60)
    try:
        j = r.json()
    except ValueError:
        j = {}
    if r.status_code != 200 or "error" in j:
        raise RuntimeError(f"{caminho}: {(j.get('error') or {}).get('message') or r.text[:300]}")
    return j


def renovar(token):
    """Renova a chave por mais 60 dias e, se houver GH_PAT, guarda a nova no Secret IG_TOKEN."""
    try:
        r = requests.get("https://graph.instagram.com/refresh_access_token",
                         params={"grant_type": "ig_refresh_token", "access_token": token}, timeout=60).json()
    except Exception as e:
        print(f"  ⚠️ renovação da chave: {e}")
        return token
    novo = r.get("access_token")
    if not novo:
        print(f"  ⚠️ renovação da chave: {(r.get('error') or {}).get('message') or r}")
        return token
    dias = round((r.get("expires_in") or 0) / 86400)
    if novo != token:
        if os.environ.get("GH_PAT") and os.environ.get("GITHUB_REPOSITORY"):
            p = subprocess.run(["gh", "secret", "set", "IG_TOKEN", "--repo", os.environ["GITHUB_REPOSITORY"], "--body", novo],
                               env={**os.environ, "GH_TOKEN": os.environ["GH_PAT"]}, capture_output=True, text=True)
            print("  🔑 chave do Instagram renovada e guardada" if p.returncode == 0 else f"  ⚠️ não consegui guardar a chave renovada: {p.stderr[:200]}")
        else:
            print("  ⚠️ a chave renovada é diferente da guardada e não há GH_PAT para salvá-la — renove o Secret IG_TOKEN antes de vencer")
    print(f"  chave do Instagram válida por mais {dias} dias")
    return novo


def main():
    token = os.environ.get("IG_TOKEN", "").strip()
    if not token:
        print("ℹ️ sem o Secret IG_TOKEN — post gerado, mas não publicado")
        return
    try:
        post = json.load(open(PASTA / "proximo.json", encoding="utf-8"))
    except Exception:
        print("⚠️ sem instagram/proximo.json")
        return
    hist_f = PASTA / "historico.json"
    try:
        hist = json.load(open(hist_f, encoding="utf-8"))
    except Exception:
        hist = {"publicados": []}
    if any(x.get("imagens") == post["imagens"] for x in hist["publicados"]):
        print("ℹ️ este post já foi publicado")
        return
    token = renovar(token)
    eu = chamar("GET", "me", token, fields="user_id,username")
    uid = eu["user_id"]
    # as imagens precisam já estar no site (GitHub Pages leva ~1 min depois do push)
    for u in post["urls"]:
        for _ in range(40):
            try:
                if requests.head(u, timeout=20).status_code == 200:
                    break
            except requests.RequestException:
                pass
            time.sleep(15)
        else:
            sys.exit(f"❌ a imagem não apareceu no site: {u}")
    filhos = [chamar("POST", f"{uid}/media", token, image_url=u, is_carousel_item="true")["id"] for u in post["urls"]]
    cont = chamar("POST", f"{uid}/media", token, media_type="CAROUSEL", children=",".join(filhos), caption=post["legenda"])["id"]
    for _ in range(30):
        st = chamar("GET", cont, token, fields="status_code").get("status_code")
        if st == "FINISHED":
            break
        if st in ("ERROR", "EXPIRED"):
            sys.exit(f"❌ o Instagram recusou o carrossel ({st})")
        time.sleep(10)
    mid = chamar("POST", f"{uid}/media_publish", token, creation_id=cont)["id"]
    link = chamar("GET", mid, token, fields="permalink").get("permalink")
    hist["publicados"].append({"tema": post["tema"], "data": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"), "imagens": post["imagens"],
                               "id": mid, "link": link, "conta": eu.get("username")})
    hist_f.write_text(json.dumps(hist, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✅ publicado no Instagram (@{eu.get('username')}): {link}")


if __name__ == "__main__":
    main()
