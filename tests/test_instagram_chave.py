#!/usr/bin/env python3
"""
Cofre Aberto MS — publicador do Instagram com os dois tipos de chave (API simulada, sem rede)

25/11/2026: o app novo da Meta usa login unificado; a chave do usuário do sistema é do Facebook (graph.facebook.com)
e não expira. O publicador descobre o tipo da chave sozinho e só renova a do login do Instagram (60 dias).
Uso: python3 tests/test_instagram_chave.py   (código 1 se algum teste falhar)
"""
import os, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import publicar_instagram as pi  # noqa: E402

oks, erros = [], []
check = lambda c, m: (oks if c else erros).append(m)


class R:
    def __init__(self, code, j):
        self.status_code, self._j, self.text = code, j, str(j)

    def json(self):
        return self._j


def api(chaves_ig, paginas=None):
    chamadas = []

    def req(metodo, url, params=None, timeout=None):
        chamadas.append(url)
        tok = (params or {}).get("access_token")
        if url.startswith(pi.API_IG):
            if tok in chaves_ig and url.endswith("/me"):
                return R(200, {"user_id": "111", "username": "cofre_abertoms"})
            return R(400, {"error": {"message": "Invalid OAuth access token - Cannot parse access token"}})
        if url.endswith("/me/accounts"):
            return R(200, {"data": paginas or []})
        if url.endswith("/17841400153468200") or url.endswith("/222"):
            return R(200, {"username": "cofre_abertoms", "id": url.rsplit("/", 1)[1]})
        return R(404, {"error": {"message": "não simulado"}})
    pi.requests.request = req
    return chamadas


# chave do login do Instagram
api({"IGTOK"})
a, uid, user, tipo = pi.conta("IGTOK")
check((a, uid, tipo) == (pi.API_IG, "111", "instagram"), f"chave do login do Instagram → graph.instagram.com ({a}, {uid}, {tipo})")

# chave do usuário do sistema, com IG_USER_ID do workflow
os.environ["IG_USER_ID"] = "17841400153468200"
api(set())
a, uid, user, tipo = pi.conta("FBTOK")
check((a, uid, tipo, user) == (pi.API_FB, "17841400153468200", "facebook", "cofre_abertoms"),
      f"chave do usuário do sistema → graph.facebook.com com IG_USER_ID ({a}, {uid}, {tipo}, {user})")

# sem IG_USER_ID: descobre pela página ligada
os.environ.pop("IG_USER_ID")
api(set(), paginas=[{"instagram_business_account": {"id": "222", "username": "cofre_abertoms"}}])
a, uid, user, tipo = pi.conta("FBTOK")
check(uid == "222" and tipo == "facebook", f"sem IG_USER_ID: conta da página ligada ao token ({uid})")

# sem página e sem IG_USER_ID: erro claro
api(set(), paginas=[])
try:
    pi.conta("FBTOK")
    check(False, "sem conta: deveria dar erro")
except RuntimeError as e:
    check("IG_USER_ID" in str(e) and "página" in str(e), "sem conta: erro diz o que falta (IG_USER_ID ou página ligada)")

src = (ROOT / "scripts" / "publicar_instagram.py").read_text(encoding="utf-8")
check('if tipo == "instagram":\n        token = renovar(token)' in src, "só renova a chave do login do Instagram")
wf = (ROOT / ".github" / "workflows" / "instagram.yml").read_text(encoding="utf-8")
check('IG_USER_ID: "17841400153468200"' in wf, "workflow passa o ID da @cofre_abertoms")

for e in erros:
    print("❌", e)
print(f"✅ {len(oks)} checagens OK · ❌ {len(erros)} erros")
sys.exit(1 if erros else 0)
