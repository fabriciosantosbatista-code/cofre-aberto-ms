#!/usr/bin/env python3
"""
Cofre Aberto MS — publica no Instagram o post preparado por gerar_posts_instagram.py (instagram/proximo.json)

Dois tipos de chave (o publicador descobre sozinho qual é):
  - login do Instagram (graph.instagram.com): vale 60 dias e é renovada aqui a cada execução;
  - login unificado / usuário do sistema do portfólio da Meta (graph.facebook.com, 25/11/2026): não expira; o ID da
    conta vem de IG_USER_ID (variável do workflow) ou das páginas ligadas ao token. Não há renovação.
Passos:
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
VERSAO = os.environ.get("IG_API_VERSAO", "v23.0")
API_IG = "https://graph.instagram.com/" + VERSAO
API_FB = "https://graph.facebook.com/" + VERSAO
API = API_IG


def chamar(metodo, caminho, token, api=None, **params):
    r = requests.request(metodo, f"{api or API}/{caminho}", params={**params, "access_token": token}, timeout=60)
    try:
        j = r.json()
    except ValueError:
        j = {}
    if r.status_code != 200 or "error" in j:
        raise RuntimeError(f"{caminho}: {(j.get('error') or {}).get('message') or r.text[:300]}")
    return j


def conta(token):
    """(api, id da conta do Instagram, nome de usuário, tipo da chave). Tenta a chave do login do Instagram; se a API do
    Instagram recusar, usa a do Facebook (usuário do sistema), com IG_USER_ID ou a conta ligada às páginas do token."""
    try:
        eu = chamar("GET", "me", token, api=API_IG, fields="user_id,username")
        return API_IG, eu["user_id"], eu.get("username"), "instagram"
    except RuntimeError as e:
        erro_ig = str(e)
    uid = (os.environ.get("IG_USER_ID") or "").strip()
    if not uid:
        pags = chamar("GET", "me/accounts", token, api=API_FB, fields="instagram_business_account{id,username}").get("data") or []
        contas = [p["instagram_business_account"] for p in pags if p.get("instagram_business_account")]
        if not contas:
            raise RuntimeError(f"a chave não é do login do Instagram ({erro_ig}) e nenhuma página ligada a ela tem conta do "
                               "Instagram — defina IG_USER_ID no workflow ou ligue a conta a uma página do Facebook")
        uid = contas[0]["id"]
    info = chamar("GET", uid, token, api=API_FB, fields="username")
    return API_FB, uid, info.get("username"), "facebook"


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


def conferir():
    """Checagem diária da chave (só leitura: consulta a conta). Falha = a Meta recusou a chave → o job falha e o GitHub
    avisa o dono na hora; a vistoria do fim do dia repete o aviso. (25/11/2026)"""
    token = os.environ.get("IG_TOKEN", "").strip()
    if not token:
        print("❌ chave do Instagram: o Secret IG_TOKEN está vazio")
        return 1
    try:
        _api, uid, usuario, tipo = conta(token)
    except Exception as e:
        print(f"❌ chave do Instagram recusada pela Meta: {e}")
        return 1
    dono = ""
    if tipo == "facebook":  # a quem a chave pertence (o usuário do sistema do portfólio, ex.: cofre-robo)
        try:
            me = chamar("GET", "me", token, api=API_FB, fields="id,name")
            dono = f"; usuário do sistema: {me.get('name')} ({me.get('id')})"
        except Exception as e:
            dono = f"; dono da chave não consultado ({str(e)[:120]})"
    print(f"✅ chave do Instagram válida: @{usuario} (conta {uid}, chave {'do usuário do sistema' if tipo == 'facebook' else 'do login do Instagram'}{dono})")
    return 0


def main():
    if "--conferir" in sys.argv:
        sys.exit(conferir())
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
    hoje = datetime.now().strftime("%Y-%m-%d")
    if any(str(x.get("data") or "")[:10] == hoje for x in hist["publicados"]):  # regra: no máximo 1 post por dia
        print("ℹ️ já houve post hoje — no máximo 1 por dia; fica para amanhã")
        return
    sys.path.insert(0, str(Path(__file__).parent))
    import instagram_aprovacao as ap
    if not ap.publicar_ligado():
        print("⏸ Instagram pausado (instagram/config.json → publicar: false): não publico")
        return
    if ap.em_aprovacao() and os.environ.get("IG_APROVADO") != "1":  # modo aprovação: só com o rótulo "aprovado" na issue
        print(f"ℹ️ modo aprovação até {ap.cfg().get('aprovacaoAte')}: não publico sem aprovação (rótulo \"aprovado\" na issue do rascunho)")
        return
    global API
    API, uid, usuario, tipo = conta(token)
    eu = {"username": usuario}
    if tipo == "instagram":
        token = renovar(token)
    else:
        print("  chave do usuário do sistema da Meta (graph.facebook.com): não expira, sem renovação")
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
    publicar_story(post, uid, token, eu, hist, hist_f, ap)


def publicar_story(post, uid, token, eu, hist, hist_f, ap, espera=time.sleep):
    """Story do dia, logo depois do post do feed (mesmo tema, mesmas regras). Interruptor separado em
    instagram/config.json → "stories". Falha no story não desfaz o post do feed: só fica o aviso no log."""
    if ap.cfg().get("stories", True) is False:
        print("⏸ story desligado (instagram/config.json → stories: false)")
        return None
    url = post.get("storyUrl")
    if not url:
        print("ℹ️ este post não tem story (gerado antes de 25/11/2026)")
        return None
    try:
        for _ in range(40):
            try:
                if requests.head(url, timeout=20).status_code == 200:
                    break
            except requests.RequestException:
                pass
            espera(15)
        else:
            raise RuntimeError(f"a imagem do story não apareceu no site: {url}")
        cont = chamar("POST", f"{uid}/media", token, image_url=url, media_type="STORIES")["id"]
        for _ in range(30):
            if chamar("GET", cont, token, fields="status_code").get("status_code") == "FINISHED":
                break
            espera(10)
        sid = chamar("POST", f"{uid}/media_publish", token, creation_id=cont)["id"]
    except Exception as e:
        print(f"⚠️ story não publicado: {e}")
        return None
    hist["publicados"][-1].update({"story": post.get("story"), "storyId": sid, "storyEm": datetime.now().strftime("%Y-%m-%dT%H:%M:%S")})
    hist_f.write_text(json.dumps(hist, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✅ story publicado no Instagram (@{eu.get('username')}): id {sid}")
    return sid


if __name__ == "__main__":
    main()
