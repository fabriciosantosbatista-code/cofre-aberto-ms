#!/usr/bin/env python3
"""
Cofre Aberto MS — troca de titular e suplente nos senadores de MS (sem rede, caso simulado)

Cenário: o titular A (id 100) exerceu de janeiro a março e saiu de exercício; o suplente B (id 200) assumiu em abril.
A lista "atual" do Senado só traz B, C e D. O site precisa manter as notas dos dois, cada um na sua página, e a de A
mostrar os gastos do período em que exerceu.

Uso: python3 tests/test_senado_suplente.py   (código 1 se algum teste falhar)
"""
import json, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import coletar_dados as cd  # noqa: E402

oks, erros = [], []


def check(c, m):
    (oks if c else erros).append(m)


def nota(d, v, doc):
    return {"data": d, "mes": int(d[5:7]), "categoria": "Locomoção", "fornecedor": "POSTO X", "cnpjCpf": "11.037.808/0001-60",
            "doc": doc, "valor": v}


NOTAS = {100: [nota("2026-01-10", 300.0, "1"), nota("2026-03-20", 200.0, "2")],            # titular A, saiu em março
         200: [nota("2026-04-05", 150.0, "3"), nota("2026-10-01", 250.0, "4")],            # suplente B, desde abril
         300: [nota("2026-02-02", 100.0, "5")], 400: [nota("2026-05-05", 50.0, "6")]}


def ident(i, nome):
    return {"IdentificacaoParlamentar": {"CodigoParlamentar": str(i), "NomeParlamentar": nome, "NomeParlamentarFormatado": nome,
                                         "SiglaPartidoParlamentar": "X", "UfParlamentar": "MS"}}


class Resp:
    def __init__(self, j):
        self.j = j

    def raise_for_status(self):
        pass

    def json(self):
        return self.j


tmp = Path(tempfile.mkdtemp(prefix="senado-suplente-"))
cd.DADOS = tmp
cd.time.sleep = lambda *_: None
cd.log = lambda *_: None
cd.requests.get = lambda url, **kw: Resp({"ListaParlamentarEmExercicio": {"Parlamentares": {"Parlamentar": [
    ident(200, "Suplente B"), ident(300, "Senador C"), ident(400, "Senador D")]}}})
cd.carregar_notas_ceaps_senado = lambda ano: NOTAS
cd.buscar_recursos_senador = lambda sid, ano: {"ceaps": {"Locomoção": sum(n["valor"] for n in NOTAS[sid])}, "gastosExtras": {}, "pessoal": {},
                                               "beneficios": {}, "totalCeaps": sum(n["valor"] for n in NOTAS[sid]), "totalExtras": 0, "ano": ano}
# arquivo anterior (mesmo ano): A ainda estava em exercício
(tmp / "senadores_ms.json").write_text(json.dumps({"ano": cd.ANO, "senadores": [
    {"id": 100, "nome": "Titular A", "partido": "X", "notasCeaps": NOTAS[100]}, {"id": 300, "nome": "Senador C", "notasCeaps": NOTAS[300]},
    {"id": 400, "nome": "Senador D", "notasCeaps": NOTAS[400]}]}), encoding="utf-8")

cd.coletar_senadores_ms()
d = json.loads((tmp / "senadores_ms.json").read_text(encoding="utf-8"))
por = {s["id"]: s for s in d["senadores"]}
check(set(por) == {100, 200, 300, 400}, f"titular que saiu (A) e suplente que entrou (B) no arquivo: {sorted(por)}")
a, b = por.get(100, {}), por.get(200, {})
check(a.get("emExercicio") is False and b.get("emExercicio") is True, "A marcado fora de exercício; B em exercício")
check(len(a.get("notasCeaps") or []) == 2 and abs((a.get("cotaGastaAno") or 0) - 500) < 0.01, "A mantém as 2 notas e o total do período (R$ 500)")
check(len(b.get("notasCeaps") or []) == 2 and abs((b.get("cotaGastaAno") or 0) - 400) < 0.01, "B tem só as notas dele (R$ 400)")
check("10/01/2026 a 20/03/2026" in (a.get("situacaoExercicio") or ""), f"página de A mostra o período: {a.get('situacaoExercicio')}")
check(sum(1 for s in d["senadores"] if s.get("emExercicio", True)) == 3, "3 em exercício (a checagem diária conta só esses)")
# 2ª coleta: A continua (o arquivo anterior agora já o tem como fora de exercício)
cd.coletar_senadores_ms()
d2 = json.loads((tmp / "senadores_ms.json").read_text(encoding="utf-8"))
check(any(s["id"] == 100 and s.get("emExercicio") is False for s in d2["senadores"]), "A continua no site na coleta seguinte")
# notas por estado: os de MS fora de exercício entram no arquivo de MS
cd.salvar_notas_por_uf("ceaps_senado", [(200, "MS"), (300, "MS"), (400, "MS")] + [(100, "MS")], NOTAS, "teste")
ms = json.loads((tmp / "ceaps_senado" / "MS.json").read_text(encoding="utf-8"))
par = ms.get("parlamentares") or ms.get("deputados") or {}
check("100" in par and len(par["100"]) == 2, "notas do titular A no arquivo de notas de MS (página dele)")

for e in erros:
    print("❌", e)
print(f"✅ {len(oks)} checagens OK · ❌ {len(erros)} erros")
sys.exit(1 if erros else 0)
