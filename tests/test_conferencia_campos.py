#!/usr/bin/env python3
"""
Cofre Aberto MS — conferência de Supersalários: campo que a fonte não informa e divergência com o Anexo VIII
(casos simulados, sem rede).

Regra (21/11/2026): campo que a fonte não traz fica "não verificado" — nunca completado com o nosso número; o
contracheque só "confere" se todos os campos comparados batem. Divergência com o Anexo VIII vira um selo com os dois
valores e uma frase neutra sobre a fonte.
Uso: python3 tests/test_conferencia_campos.py   (código 1 se algum teste falhar)
"""
import json, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts" / "verificacao"))
sys.path.insert(0, str(ROOT / "scripts"))
import conferencia_supersalarios as cs  # noqa: E402

oks, erros = [], []
check = lambda c, m: (oks if c else erros).append(m)


def anexo(nome, sub, vp, ind, ev, prev, ir, dd=0.0, ret=0.0):
    bruto = round(sub + vp + ind + ev, 2)
    desc = round(prev + ir + dd + ret, 2)
    return {"nome": nome, "subsidio": sub, "vantagensPessoais": vp, "indenizacoes": ind, "vantagensEventuais": ev, "gratificacoes": 0.0,
            "remuneracaoParadigma": 0.0, "remuneracaoBruta": bruto, "previdencia": -prev, "impostoRenda": -ir, "descontosDiversos": -dd,
            "retencaoTeto": -ret, "totalDescontos": -desc, "remuneracaoLiquida": round(bruto - desc, 2)}


def site(nome, bruto, descontos, ind_itens):
    return {"nome": nome, "orgaoId": "trt24", "mes": "08/2026", "bruto": bruto, "descontos": descontos, "liquido": round(bruto - descontos, 2),
            "itens": [{"item": "Antiguidade", "valor": ind_itens, "categoria": "indenizações"}]}


A = [  # Anexo VIII simulado (valores no formato dos casos reais de 08/2026)
    anexo("APOSENTADA X", 39753.21, 5211.40, 13913.62, 0.0, 2000.0, 4298.30),                 # sem descontos diversos
    anexo("JUIZ Y", 39753.21, 12171.93, 27827.24, 74215.39, 7088.34, 11369.25),             # verba de 35% a mais
    anexo("DESEMB Z", 41845.49, 17061.58, 29291.84, 36062.60, 9000.0, 13569.17, ret=4988.21),  # descontos iguais
    anexo("JUIZA W", 39753.21, 0.0, 9938.30, 0.0, 2000.0, 5000.0),                           # tudo igual
    anexo("DESEMB V", 41845.49, 7568.58, 7086.74, 0.0, 8787.16, 16814.37),                   # composição diferente
]
S = [site("Aposentada X", 58878.23, 6298.30 + 2408.51, 13913.62),
     site("Juiz Y", 140054.15, 18457.59 + 3235.72, 13913.62),
     site("Desemb Z", 109615.59, 27557.38, 14645.92),
     site("Juiza W", 49691.51, 7000.0, 9938.30),
     site("Desemb V", 76223.63, 25606.44, 14645.92)]
cs.anexo_viii = lambda oid, mes: (A, "conferido no arquivo original do órgão")
cs.esgotado = lambda: False
cs.esclarecimentos = lambda: [{"orgaoId": "trt24", "mes": "08/2026"}]
r = {p["nome"]: v for p, v in zip(S, (cs.compara_anexo(S, "trt24", lambda p: 46366.19)[id(p)] for p in S))}

st, mot, cl = r["Aposentada X"]
check(st == "nao_verificado" and cl["campos"] == {"bruto": "confere", "líquido": "nao_verificado"},
      f"sem descontos diversos no Anexo VIII: bruto confere, líquido não verificado, contracheque não verificado ({st}, {cl['campos']})")
check(mot == "bruto confere; líquido não verificado — o Anexo VIII não informa os descontos diversos", f"motivo: {mot}")
check("divergencia" not in cl, "não verificado não vira selo de divergência")

st, mot, cl = r["Juiz Y"]
check(st == "diverge" and cl["campos"]["bruto"] == "diverge" and cl["campos"]["líquido"] == "nao_verificado",
      f"verba a mais: bruto diverge e o líquido continua não verificado ({cl['campos']})")
dv = cl.get("divergencia") or {}
check(dv.get("causa") == "verba_a_mais", f"causa = verba a mais (Δ indenizações = Δ bruto): {dv.get('causa')}")
check(dv.get("frase") == "o TRT24 publica, no próprio Anexo VIII, uma verba a mais que não consta no painel do CNJ; pedido de esclarecimento em preparação",
      f"sem protocolo: 'em preparação', nunca 'enviado' ({dv.get('frase')})")
check(dv.get("valores") == [{"campo": "bruto", "cnj": 140054.15, "anexo": 153967.77}], f"os dois valores lado a lado: {dv.get('valores')}")

st, mot, cl = r["Desemb Z"]
check(st == "diverge" and cl["campos"] == {"bruto": "diverge", "líquido": "diverge"}, f"descontos informados: líquido é comparado ({cl['campos']})")

st, mot, cl = r["Juiza W"]
check(st == "confere" and cl["campos"] == {"bruto": "confere", "líquido": "confere"}, f"tudo igual: confere ({st})")

st, mot, cl = r["Desemb V"]
dv = cl.get("divergencia") or {}
check(st == "diverge" and dv.get("causa") == "composicao" and "composição deste contracheque diferente" in dv.get("frase", ""),
      f"composição diferente (site maior que o Anexo VIII): {dv.get('causa')}")

# regra geral: campo que a fonte não traz (None) → não verificado, nunca 0 nem o nosso número
s_, m_, c_ = cs.compara([("bruto", 100.0, 100.0, None), ("líquido", 80.0, None, None)], "fonte")
check(s_ == "nao_verificado" and c_ == {"bruto": "confere", "líquido": "nao_verificado"} and "fonte não informa" in m_,
      f"campo ausente na fonte (Governo/TCE): {s_} · {m_}")
s_, m_, c_ = cs.compara([("bruto", 100.0, 150.0, None), ("líquido", 80.0, None, None)], "fonte")
check(s_ == "diverge", "divergência continua divergência mesmo com outro campo não verificado")

cs.esclarecimentos = lambda: [{"orgaoId": "trt24", "mes": "08/2026", "protocolo": "  "}]
check(cs.frase_divergencia("trt24", "08/2026", "verba_a_mais").endswith("pedido de esclarecimento em preparação"), "protocolo em branco = em preparação")
cs.esclarecimentos = lambda: [{"orgaoId": "trt24", "mes": "08/2026", "protocolo": "12345/2026"}]
check(cs.frase_divergencia("trt24", "08/2026", "verba_a_mais").endswith("pedido de esclarecimento enviado (protocolo nº 12345/2026)"), "com protocolo: enviado (protocolo nº X)")
cs.esclarecimentos = lambda: []
check(cs.frase_divergencia("trt24", "08/2026", "verba_a_mais").endswith("painel do CNJ"), "sem pedido registrado: nada sobre pedido")
cs.esclarecimentos = lambda: [{"orgaoId": "trt24", "mes": "08/2026"}]
# frases: sobre a fonte, nunca sobre a pessoa
fr = [cs.frase_divergencia("trt24", "08/2026", c) for c in ("verba_a_mais", "composicao", "liquido")]
check(not any(re.search(r"irregular|fraude|ilegal|indevid|suspeit", f, re.I) for f in fr), "nenhuma frase sugere irregularidade da pessoa")
check(all(f.startswith("o TRT24 publica") or f.startswith("o valor publicado pelo TRT24") for f in fr), "as frases falam da publicação do órgão")

cfg = json.load(open(ROOT / "config" / "esclarecimentos_fonte.json", encoding="utf-8"))
check(any(e["orgaoId"] == "trt24" and e["mes"] == "08/2026" for e in cfg["pedidos"]), "pedido de esclarecimento do TRT24 (08/2026) registrado")
cs.esclarecimentos = lambda: cfg["pedidos"]  # o arquivo real: sem protocolo → nunca "enviado"
for e in cfg["pedidos"]:
    f_ = cs.frase_divergencia(e["orgaoId"], e["mes"], "verba_a_mais")
    check(("enviado (protocolo nº" in f_) if str(e.get("protocolo") or "").strip() else ("em preparação" in f_ and "enviado" not in f_),
          f"config real ({e['orgaoId']} {e['mes']}): {f_.split('; ')[-1]}")

for e in erros:
    print("❌", e)
print(f"✅ {len(oks)} checagens OK · ❌ {len(erros)} erros")
sys.exit(1 if erros else 0)
