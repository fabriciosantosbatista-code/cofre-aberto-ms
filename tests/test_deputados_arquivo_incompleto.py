#!/usr/bin/env python3
"""
Cofre Aberto MS — Deputados: arquivo anual da Câmara incompleto, completado pela API (casos simulados, sem rede)

Regra de 26/11/2026: quando o arquivo anual traz menos que a versão publicada além do limite da proteção (total −2% ou
notas −10%), os meses que encolheram de cada deputado são lidos da API, mês a mês e por data; as notas que faltam
entram com origem "API da Câmara (arquivo anual incompleto em DD/MM)". Arquivo normal = nada da API por esse caminho
(o arquivo volta a prevalecer). A proteção da publicação continua valendo.
Uso: python3 tests/test_deputados_arquivo_incompleto.py   (código 1 se algum teste falhar)
"""
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import coletar_dados as cd  # noqa: E402

cd.log = lambda *a, **k: None
oks, erros = [], []
check = lambda c, m: (oks if c else erros).append(m)


def nota(cod, mes, valor):
    return {"codDocumento": str(cod), "mes": mes, "data": f"2026-{mes:02d}-10", "valor": valor, "categoria": "COMBUSTÍVEIS",
            "cnpjCpfFornecedor": "11.111.111/0001-11", "doc": f"N{cod}"}


def item_api(cod, mes, valor):
    return {"codDocumento": cod, "mes": mes, "dataDocumento": f"2026-{mes:02d}-10", "valorLiquido": valor, "valorDocumento": valor,
            "tipoDespesa": "COMBUSTÍVEIS", "cnpjCpfFornecedor": "11111111000111", "numDocumento": f"N{cod}", "nomeFornecedor": "Posto"}


publicado = {1: [nota(i, 1 + i % 3, 100.0) for i in range(30)]}            # 30 notas, meses 1–3, R$ 3.000
arquivo_ok = {1: {"total": 3000.0, "cats": {}, "despesas": [nota(i, 1 + i % 3, 100.0) for i in range(30)]}}
arquivo_curto = {1: {"total": 0.0, "cats": {}, "despesas": [nota(i, 1 + i % 3, 100.0) for i in range(30) if i % 3 != 1]}}  # sem o mês 2

check(cd.arquivo_encolheu(arquivo_ok, publicado)[0] is False, "arquivo igual à versão publicada: não encolheu")
check(cd.arquivo_encolheu(arquivo_curto, publicado)[0] is True, "arquivo sem um mês inteiro: encolheu além do limite")
check(cd.meses_encolhidos(arquivo_curto[1]["despesas"], publicado[1]) == [2], "só o mês que encolheu é lido da API")

pedidos = []
def ler(dep, meses):
    pedidos.append((dep, list(meses)))
    return {2: [item_api(i, 2, 100.0) for i in range(30) if i % 3 == 1]}
check(cd.complementar_encolhidos(arquivo_ok, publicado, 2026, ler=ler) == {} and not pedidos, "arquivo normal: a API não é usada (o arquivo prevalece)")
rel = cd.complementar_encolhidos(arquivo_curto, publicado, 2026, hoje=date(2026, 11, 26), ler=ler)
check(pedidos == [(1, [2])], f"pediu à API só o deputado e o mês que encolheram: {pedidos}")
novas = [n for n in arquivo_curto[1]["despesas"] if n.get("origem")]
check(len(novas) == 10 and rel[1]["novas"] == 10, f"10 notas do mês 2 completadas pela API: {len(novas)}")
check(all(n["origem"] == "API da Câmara (arquivo anual incompleto em 26/11)" for n in novas), "marca: 'API da Câmara (arquivo anual incompleto em 26/11)'")
check(cd.arquivo_encolheu(arquivo_curto, publicado)[0] is False, "arquivo + API voltou ao nível da versão publicada")
# nota que já está no arquivo não entra de novo
antes = len(arquivo_curto[1]["despesas"])
cd.complementar_encolhidos(arquivo_curto, publicado, 2026, ler=ler)
check(len(arquivo_curto[1]["despesas"]) == antes, "sem duplicar notas já completadas")

# API que não responde: o mês fica de fora e a proteção decide
falha = {1: {"total": 0.0, "cats": {}, "despesas": [nota(i, 1 + i % 3, 100.0) for i in range(30) if i % 3 != 1]}}
rel = cd.complementar_encolhidos(falha, publicado, 2026, ler=lambda d, m: {})
check(rel[1]["novas"] == 0 and cd.arquivo_encolheu(falha, publicado)[0], "API sem resposta: continua abaixo e a proteção mantém a versão anterior")

# leitura mês a mês, por data, com novas tentativas; mês incompleto fica de fora
class R:
    def __init__(self, j, erro=False): self.j, self.erro = j, erro
    def raise_for_status(self):
        if self.erro: raise RuntimeError("503")
    def json(self): return self.j
chamadas = []
def get(params):
    chamadas.append(params)
    if params["mes"] == 3 and params["pagina"] == 1 and sum(1 for c in chamadas if c["mes"] == 3) == 1:
        return R({}, erro=True)          # 1ª tentativa do mês 3 falha, a 2ª passa
    if params["mes"] == 5:
        return R({}, erro=True)          # mês 5 nunca responde
    if params["mes"] == 2 and params["pagina"] == 1:
        return R({"dados": [{"a": 1}], "links": [{"rel": "next"}]})
    return R({"dados": [{"a": 2}], "links": []})
out = cd.despesas_api_meses(9, 2026, [2, 3, 5], tentativas=3, espera=lambda s: None, get=get)
check(sorted(out) == [2, 3] and len(out[2]) == 2, f"mês 2 com 2 páginas, mês 3 depois de nova tentativa, mês 5 fora: {sorted(out)}")
check(all(c.get("ordenarPor") == "dataDocumento" and c.get("ordem") == "ASC" for c in chamadas), "cada mês lido ordenado pela data")

for e in erros:
    print("❌", e)
print(f"✅ {len(oks)} checagens OK · ❌ {len(erros)} erros")
sys.exit(1 if erros else 0)
