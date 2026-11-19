#!/usr/bin/env python3
"""
Cofre Aberto MS — política de repetição da API do Governo de MS (scripts/coletar_governo_ms.py), sem rede

  401, 429 e 5xx: repete até 2 vezes, com token novo e espera de 30–60 s (ou Retry-After); depois falha normalmente
  outros 4xx: falha na hora, sem repetir
  log: horário, status, validade do token (iat/exp) e cabeçalhos — nunca o token

Uso: python3 tests/test_api_governo.py   (código 1 se algum teste falhar)
"""
import base64, contextlib, io, json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import coletar_governo_ms as g  # noqa: E402

oks, erros = [], []


def check(c, m):
    (oks if c else erros).append(m)


def jwt(n):
    corpo = base64.urlsafe_b64encode(json.dumps({"iat": 1795051105, "exp": 1795051405, "n": n}).encode()).decode().rstrip("=")
    return f"cabecalho.{corpo}.SEGREDO{n}"


class Resp:
    def __init__(self, status, corpo=None, headers=None):
        self.status_code, self._corpo, self.headers, self.text = status, corpo, headers or {}, ""

    def json(self):
        if self._corpo is None:
            raise ValueError("sem JSON")
        return self._corpo


def cenario(respostas):
    """Roda g.api com respostas em sequência; devolve (resultado ou exceção, nº de chamadas, esperas, log)."""
    fila, chamadas, esperas, tokens = list(respostas), [], [], []

    def get(url, params=None, timeout=None, headers=None):
        chamadas.append(headers)
        return fila.pop(0)
    orig = (g.sess.get, g.token, g.time.sleep)
    g.sess.get = get
    g.token = lambda: tokens.append(jwt(len(tokens))) or tokens[-1]
    g.time.sleep = esperas.append
    saida = io.StringIO()
    try:
        with contextlib.redirect_stdout(saida):
            try:
                res = g.api("/rota", {})
            except Exception as e:
                res = e
    finally:
        g.sess.get, g.token, g.time.sleep = orig
    return res, chamadas, esperas, saida.getvalue(), tokens


OK = Resp(200, {"status": {"code": 200}, "data": [1]})
r, ch, es, log, tk = cenario([Resp(401, None, {"Via": "kong/2.2.0"}), OK])
check(isinstance(r, dict) and len(ch) == 2, "401 passageiro → repete e funciona na 2ª tentativa")
check(len(set(tk)) == 2 and ch[0]["Authorization"] != ch[1]["Authorization"], "cada tentativa usa um token novo")
check(len(es) == 1 and 30 <= es[0] <= 60, f"espera entre 30 e 60 s ({es})")
check("HTTP 401" in log and "emitido" in log and "vale até" in log and "kong/2.2.0" in log and " UTC" in log,
      "log: status, horário, validade do token e cabeçalhos")
check(not any(t in log or t.split(".")[2] in log for t in tk), "o token nunca aparece no log")

r, ch, es, log, _ = cenario([Resp(401), Resp(401), Resp(401)])
check(isinstance(r, RuntimeError) and len(ch) == 3 and "401" in str(r), "401 nas 3 tentativas → falha normal (registrada no ICP), sem repetir além de 2")

r, ch, es, log, _ = cenario([Resp(429, None, {"Retry-After": "7"}), OK])
check(isinstance(r, dict) and es[:1] == [7], "429 → respeita o Retry-After")

r, ch, es, log, _ = cenario([Resp(503), Resp(502), OK])
check(isinstance(r, dict) and len(ch) == 3, "5xx → repete até 2 vezes")

r, ch, es, log, _ = cenario([Resp(404, {"status": {"code": 404, "message": "não encontrado"}})])
check(isinstance(r, RuntimeError) and len(ch) == 1 and es == [], "404 (outro 4xx) → falha na hora, sem repetir")

r, ch, es, log, _ = cenario([Resp(200, {"status": {"code": 400, "message": "parâmetro"}})])
check(isinstance(r, RuntimeError) and len(ch) == 1, "erro de parâmetro no corpo (400) → falha na hora")

print(f"✅ {len(oks)} checagens OK · ❌ {len(erros)} erros")
for e in erros:
    print("❌", e)
sys.exit(1 if erros else 0)
