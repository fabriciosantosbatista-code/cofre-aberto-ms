#!/usr/bin/env python3
"""
Cofre Aberto MS — conferência na fonte: teto de tempo por base, ordem pela mais antiga e aviso de 3 coletas sem
conferência (bases simuladas, sem rede).

Regra (25/11/2026): cada base tem teto próprio; ao estourar, para e fica "tempo esgotado" sem tirar tempo das outras;
a ordem começa pela base conferida há mais tempo; 3 coletas seguidas sem conferência = aviso.
Uso: python3 tests/test_conferencia_orcamento.py   (código 1 se algum teste falhar)
"""
import io, json, os, sys, tempfile, time
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
os.environ["CONFERENCIA_PRAZO_MIN"] = "1"
import validar_fontes as vf  # noqa: E402

oks, erros = [], []
check = lambda c, m: (oks if c else erros).append(m)
tmp = Path(tempfile.mkdtemp())
vf.SAIDA, vf.HISTORICO = tmp / "validacao.json", tmp / "hist.jsonl"
vf.janela_coleta = lambda: (True, None)
vf.TETO_BASE_SEG, vf.TETO_PADRAO_SEG = {"lenta": 1}, 1
chamadas = []


def lenta():  # fica consultando até o prazo acabar (como Deputados em 25/11, que tomou 27 min)
    chamadas.append("lenta")
    while True:
        r = vf._resta()
        if r is not None and r <= 0:
            vf.PRAZO["esgotado"] = True
            return {"resultado": "confere", "em": vf.AGORA}
        time.sleep(0.05)


def rapida(nome):
    def f():
        chamadas.append(nome)
        return {"resultado": "confere", "em": vf.AGORA, "conferidos": 1, "comparados": [], "divergentes": []}
    return f


vf.CONFERENCIAS = (("a", rapida("a")), ("lenta", lenta), ("b", rapida("b")), ("c", rapida("c")))
ant = {"a": {"resultado": "confere", "em": "2026-11-24T10:00:00"}, "lenta": {"resultado": "confere", "em": "2026-11-20T10:00:00"},
       "b": {"resultado": "confere", "em": "2026-11-22T10:00:00"}}  # c nunca foi conferida
vf.J = lambda n: {"fontes": json.loads(json.dumps(ant))} if n == "validacao_fontes.json" else {}

ordem = [f for f, _ in vf.ordem_conferencia(vf.CONFERENCIAS, ant)]
check(ordem == ["c", "lenta", "b", "a"], f"ordem: nunca conferida primeiro, depois a conferida há mais tempo: {ordem}")

t0 = time.monotonic()
buf = io.StringIO()
with redirect_stdout(buf):
    vf.main()
dur = time.monotonic() - t0
out = json.loads(vf.SAIDA.read_text())["fontes"]
check(dur < 5, f"a base lenta parou no próprio teto (1 s), não no prazo total (60 s): {dur:.1f} s")
check(chamadas == ["c", "lenta", "b", "a"], f"as bases depois da lenta rodaram: {chamadas}")
check(out["lenta"]["em"] == "2026-11-20T10:00:00" and "tempo esgotado" in out["lenta"]["ultimaTentativaResultado"],
      "lenta: fica a conferência anterior, marcada 'tempo esgotado'")
check(out["lenta"]["coletasSemConferencia"] == 1, "contagem de coletas seguidas sem conferência: 1")
check(out["b"]["em"] == vf.AGORA and "coletasSemConferencia" not in out["b"], "as outras foram conferidas nesta coleta")

# mais 2 coletas com a lenta estourando: na 3ª, aviso
for _ in range(2):
    ant = out
    vf.J = lambda n, a=json.loads(json.dumps(ant)): {"fontes": a} if n == "validacao_fontes.json" else {}
    buf = io.StringIO()
    with redirect_stdout(buf):
        vf.main()
    out = json.loads(vf.SAIDA.read_text())["fontes"]
check(out["lenta"]["coletasSemConferencia"] == 3, f"3 coletas seguidas sem conferência: {out['lenta'].get('coletasSemConferencia')}")
check("lenta: 3 coletas seguidas sem conferência" in buf.getvalue(), "aviso no log da conferência")
first = buf.getvalue().split("ordem desta coleta")[1].split("\n")[0]
check(first.strip(" :(a conferida há mais tempo primeiro)").startswith("lenta"), f"a que ficou sem conferência passa a ir primeiro: {first}")

# conferida de novo: a contagem zera
vf.CONFERENCIAS = (("lenta", rapida("lenta")),)
vf.J = lambda n, a=json.loads(json.dumps(out)): {"fontes": a} if n == "validacao_fontes.json" else {}
with redirect_stdout(io.StringIO()):
    vf.main()
out = json.loads(vf.SAIDA.read_text())["fontes"]
check("coletasSemConferencia" not in out["lenta"], "conferida de novo: a contagem zera")

# a vistoria (verificar_dados.py) avisa com 3 ou mais
src = (ROOT / "scripts" / "verificar_dados.py").read_text(encoding="utf-8")
check('coletasSemConferencia' in src and "coletas seguidas sem conferência" in src, "verificar_dados.py avisa com 3 coletas seguidas sem conferência")

for e in erros:
    print("❌", e)
print(f"✅ {len(oks)} checagens OK · ❌ {len(erros)} erros")
sys.exit(1 if erros else 0)
