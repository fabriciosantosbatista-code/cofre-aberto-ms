#!/usr/bin/env python3
"""
Cofre Aberto MS — auditoria: sinal nunca é removido e recriado (casos simulados, sem rede)

Regra de 26/11/2026: (1) a fonte lista as vencedoras de uma licitação em ordem que muda entre coletas; o sinal de duas
empresas tem de manter o mesmo id e a data em que foi visto pela 1ª vez ("vistoEm"); (2) quando a fonte de um sinal
falha numa coleta (cadastro da Receita sem resposta, licitações que não vieram), o sinal anterior fica, com a data
original, marcado "não reconferido nesta coleta"; (3) sinal só sai quando a fonte respondeu e ele deixou de existir.
Uso: python3 tests/test_auditoria_sinais_estaveis.py   (código 1 se algum teste falhar)
"""
import copy, sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import gerar_auditoria as ga  # noqa: E402

oks, erros = [], []
check = lambda c, m: (oks if c else erros).append(m)
A, B = "11222333000181", "44555666000190"
SOCIO = [{"nome": "FULANO DE TAL", "cpf": "123456", "qualificacao": "Sócio-Administrador"}]


def cad(socios_b=True):
    return {A: {"razao": "EMPRESA A LTDA", "socios": SOCIO},
            B: {"razao": "EMPRESA B LTDA", **({"socios": SOCIO} if socios_b else {})}}


def licit(ordem):
    return [{"processo": "011494/2026-03", "numero": "102/2026", "numeroFonte": "102/102", "modalidade": "Pregão Eletrônico",
             "objeto": "aquisição de veículos", "data": "2026-11-10", "status": "Homologada", "valorEstimado": 100000,
             "vencedores": [{"cnpj": c, "nome": "EMPRESA " + ("A" if c == A else "B") + " LTDA"} for c in ordem]}]


def rodar(cad_, licit_, anterior, hoje):
    base = {"cnpj_cache.json": cad_, "auditoria.json": anterior,
            "prefeitura_contratos.json": {"ano": ga.ANO, "contratos": [], "licitacoes": licit_}}
    saida = {}
    ga.carregar = lambda nome: copy.deepcopy(base.get(nome, {}))
    ga.salvar = lambda nome, d: saida.__setitem__(nome, d)
    ga.notas_parlamentares = lambda: []
    ga.HOJE = hoje
    ga.main()
    return [s for s in saida["auditoria.json"]["sinais"] if s["teste"] == "socios_licitacao"]


d1 = rodar(cad(), licit([A, B]), {}, date(2026, 11, 17))
check(len(d1) == 1 and d1[0]["vistoEm"] == "2026-11-17", "sinal criado em 17/11")
d2 = rodar(cad(), licit([B, A]), {"sinais": d1}, date(2026, 11, 26))
check(len(d2) == 1 and d2[0]["id"] == d1[0]["id"], "ordem das vencedoras invertida: mesmo id")
check(d2 and d2[0]["vistoEm"] == "2026-11-17", "ordem invertida: data de 17/11 mantida")
check(d2 and not d2[0].get("naoReconferido"), "reconferido normalmente")
# sinal antigo gravado na outra ordem (antes da correção) continua com o id e a data dele
velho = [{**d1[0], "id": ga.hashlib.sha1("|".join(["socios_licitacao", "011494/2026-03", "102/102", B, A]).encode()).hexdigest()[:12]}]
d2b = rodar(cad(), licit([A, B]), {"sinais": velho}, date(2026, 11, 26))
check(len(d2b) == 1 and d2b[0]["id"] == velho[0]["id"] and d2b[0]["vistoEm"] == "2026-11-17", "sinal antigo na outra ordem: id e data mantidos")
d3 = rodar(cad(socios_b=False), licit([A, B]), {"sinais": d2}, date(2026, 11, 27))
check(len(d3) == 1 and d3[0]["id"] == d1[0]["id"] and d3[0]["vistoEm"] == "2026-11-17", "Receita falhou: sinal fica com a data original")
check(d3 and d3[0].get("naoReconferido") is True and "Receita" in d3[0].get("naoReconferidoMotivo", ""), "Receita falhou: marcado não reconferido")
d4 = rodar(cad(), [], {"sinais": d3}, date(2026, 11, 28))
check(len(d4) == 1 and d4[0].get("naoReconferido") and d4[0]["vistoEm"] == "2026-11-17", "licitações não vieram: sinal fica, não reconferido")
d5 = rodar(cad(), licit([A, B]), {"sinais": d4}, date(2026, 11, 29))
check(len(d5) == 1 and not d5[0].get("naoReconferido") and d5[0]["vistoEm"] == "2026-11-17", "fonte voltou: reconferido, data original")
outro = cad(); outro[B]["socios"] = [{"nome": "OUTRA PESSOA", "cpf": "654321"}]
d6 = rodar(outro, licit([A, B]), {"sinais": d5}, date(2026, 11, 30))
check(d6 == [], "fonte respondeu e o sócio em comum não existe mais: sinal sai")

for m in oks:
    print("✓", m)
for m in erros:
    print("✗", m)
print(f"{len(oks)} ok, {len(erros)} falha(s)")
sys.exit(1 if erros else 0)
