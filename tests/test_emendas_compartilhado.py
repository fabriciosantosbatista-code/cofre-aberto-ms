#!/usr/bin/env python3
"""
Cofre Aberto MS — Emendas: documento de pagamento compartilhado entre emendas e nota sobre a fonte (sem rede)

Regras (22/11/2026): se o texto do documento informa a parte de cada emenda, a conferência compara com essa parte;
se não informa, "não verificado — o documento de pagamento é compartilhado entre emendas e a API não informa a parte
de cada uma". Valor do download = 2× o da API: aviso ao dono. Nota neutra sobre a fonte só enquanto o arquivo da CGU
ainda trouxer o valor anotado. Textos dos documentos reais de 2026 (API da CGU).
Uso: python3 tests/test_emendas_compartilhado.py   (código 1 se algum teste falhar)
"""
import copy, json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import validar_fontes as vf  # noqa: E402
import coletar_emendas_municipios as ce  # noqa: E402

oks, erros = [], []
check = lambda c, m: (oks if c else erros).append(m)

OB182 = ("PAGAMENTO DE SERVICOS DE HOSPEDAGENS DE ELEN NALERIO E CITIELI GIONGO. NFE 489. AF SEI 13025619 E AF SEI 12448644. SRP 90001/2025. "
         "SEI 21193.000107/2025-74. AP SEI 13457990 (R$ 1.300,00 EMENDA DANIEL TRZECIAK, 25NC001290) E (R$ 5.000,00 EMENDA 202528620007 BOHN GASS, 25NC001277)")
OB6585 = ("PAGAMENTO: NFSE 38167, PRESTACAO DE SERVICOS DE GESTAO ADMINISTRATIVA E FINANCEIRA, NECESSARIOS A EXECUCAO DO DESENVOLVIMENTO DE ACOES "
          "DE FORMACAO E EXTENSAO NO CONTEXTO DO PROGRAMA UFMS INDIGENA, CONTRATO 44/2026, FONTE 1000000000 (EMENDA Nº 202614450007 E Nº 202614450013 "
          "- GERALDO RESENDE, PROCESSO 23450.001433/2026-27.")
DF1169 = ("RETENCAO DO DIVS DA NF 193099 - PROCESSO: 23069.154460/2026-13 - AQUISICAO DE APARELHOS E UTENSILIOS DOMESTICOS. TOMBAMENTO: 672.846 A "
          "672.849, 672.850 A 672.869, 672.870 A 672.879 E 672.825 A 672.834. COMPETENCIA: 01/2026.")

check(vf.parte_da_emenda(OB182, "202528620007") == ("parte", 5000.0), f"texto informa a parte (Bohn Gass): {vf.parte_da_emenda(OB182, '202528620007')}")
check(vf.parte_da_emenda(OB6585, "202614450007") == ("compartilhado", None), f"duas emendas sem a parte de cada (FAPEC): {vf.parte_da_emenda(OB6585, '202614450007')}")
check(vf.parte_da_emenda(OB6585, "202614450013") == ("compartilhado", None), "a outra emenda do mesmo documento também fica sem parte")
check(vf.parte_da_emenda(DF1169, "202544830021") == ("exclusivo", None), "documento de uma emenda só (processo/tombamento não são códigos de emenda)")
check(vf.parte_da_emenda("", "202544830021") == ("exclusivo", None), "sem texto: documento exclusivo")
check(vf.parte_da_emenda("EMENDA 202528620007 R$ 2.500,00 E EMENDA 202599990001 R$ 1.000,00", "202528620007") == ("parte", 2500.0),
      "parte informada depois do código")
check("compartilhado entre emendas e a API não informa a parte de cada uma" in vf.COMPARTILHADO, "motivo combinado")

# nota sobre a fonte: anexada enquanto o valor do arquivo bate; some se a CGU corrigir
base = {"pagamentosMS": [{"emenda": "202544830021", "doc": "11319557000378", "mes": "04/2026", "valor": 10827.18, "autor": "Tarcisio Motta", "municipio": "Mundo Novo"}],
        "favorecidos": [{"nome": "DENTECK LTDA", "doc": "11319557000378", "valor": 97953.59}],
        "municipios": [{"municipio": "Mundo Novo", "favorecidos": [{"nome": "DENTECK LTDA", "doc": "11319557000378", "valor": 97953.59}]}],
        "autores": [{"autor": "Tarcisio Motta", "favorecidos": [{"nome": "DENTECK LTDA", "doc": "11319557000378", "valor": 97953.59}]},
                    {"autor": "Outro Autor", "favorecidos": [{"nome": "DENTECK LTDA", "doc": "11319557000378", "valor": 5000.0}]}]}
d = copy.deepcopy(base)
check(ce.anexar_notas_fonte(d) == 1, "nota da Denteck anexada")
t = (d["favorecidos"][0].get("notasFonte") or [""])[0]
check(t == "Emenda 202544830021 (Tarcisio Motta): o arquivo de download da CGU traz R$ 10.827,18 em 04/2026, exatamente o dobro do "
          "documento de pagamento na API da CGU (R$ 5.413,59).", f"texto da nota: {t}")
check(d["municipios"][0]["favorecidos"][0].get("notasFonte") == [t] and d["autores"][0]["favorecidos"][0].get("notasFonte") == [t],
      "nota nas listas do município e do autor")
check("notasFonte" not in d["autores"][1]["favorecidos"][0], "a nota não aparece no mesmo favorecido na lista de outro autor")
check(d["pagamentosMS"][0]["valor"] == 10827.18, "o número publicado continua o do arquivo da CGU")
d2 = copy.deepcopy(base); d2["pagamentosMS"][0]["valor"] = 5413.59
check(ce.anexar_notas_fonte(d2) == 0 and "notasFonte" not in d2["favorecidos"][0], "se a CGU corrigir o arquivo, a nota some")
cfg = json.load(open(ROOT / "config" / "notas_fonte_emendas.json", encoding="utf-8"))
check(not any(w in n["nota"].lower() for n in cfg["notas"] for w in ("irregular", "fraude", "indevid", "suspeit")), "notas neutras (sobre a fonte)")

# conferência simulada com os 3 pagamentos reais (API falsa)
pags = [{"emenda": "202528620007", "doc": "03624856000126", "favorecido": "F", "mes": "05/2026", "valor": 5000.0},
        {"emenda": "202614450007", "doc": "15513690000150", "favorecido": "G", "mes": "11/2026", "valor": 1000000.0},
        {"emenda": "202544830021", "doc": "11319557000378", "favorecido": "D", "mes": "04/2026", "valor": 10827.18},
        {"emenda": "202599990001", "doc": "11111111000191", "favorecido": "H", "mes": "06/2026", "valor": 200.0}]
docs = {"202528620007": "A", "202614450007": "B", "202544830021": "C", "202599990001": "E"}
det = {"A": {"data": "07/05/2026", "valor": "6.300,00", "ufFavorecido": "MS", "codigoFavorecido": "03.624.856/0001-26", "observacao": OB182},
       "B": {"data": "06/11/2026", "valor": "1.400.000,00", "ufFavorecido": "MS", "codigoFavorecido": "15.513.690/0001-50", "observacao": OB6585},
       "C": {"data": "14/04/2026", "valor": "5.413,59", "ufFavorecido": "MS", "codigoFavorecido": "11.319.557/0003-78", "observacao": DF1169},
       "E": {"data": "10/06/2026", "valor": "100,00", "ufFavorecido": "MS", "codigoFavorecido": "11.111.111/0001-91", "observacao": "PAGAMENTO NF 1"}}
vf._cgu = lambda c, params=None: ([{"fase": "Pagamento", "codigoDocumento": docs[c.split("/")[-1]]}] if (params or {}).get("pagina") == 1 else []) \
    if c.startswith("emendas/documentos/") else det[c.split("/")[-1]]
vf.J = lambda n: {"ano": 2026, "pagamentosMS": pags} if n == "emendas_municipios.json" else {}
vf.ja_conferidos_na_janela = lambda b: {}
vf.com_hashes = lambda res, b, ok: res
import limite_cgu  # noqa: E402
limite_cgu.chave = lambda: "x"
r = vf.v_emendas(4)
div = {d["item"] for d in r.get("divergentes") or []}
mot = r["motivosRegistros"]
check("202528620007|03624856000126|05/2026" not in div and "202528620007|03624856000126|05/2026" not in mot, "Bohn Gass: compara com a parte do texto (5.000) e confere")
check(mot.get("202614450007|15513690000150|11/2026") == vf.COMPARTILHADO and "202614450007|15513690000150|11/2026" not in div,
      "FAPEC: não verificado — documento compartilhado sem a parte")
check("202544830021|11319557000378|04/2026" in div, "Denteck continua divergência (é da fonte; aparece no site e no ICP)")
dob = {d["item"]: d for d in r["dobroDownload"]}
check(dob.get("202544830021|11319557000378|04/2026", {}).get("jaAnotada") is True, "Denteck: dobro já anotado (sem novo aviso)")
check(dob.get("202599990001|11111111000191|06/2026", {}).get("jaAnotada") is False, "novo caso de download = 2× API sinalizado para o dono decidir")
check(r["conferidos"] == 3, f"conferidos = 3 (o compartilhado sem parte não conta): {r['conferidos']}")

for e in erros:
    print("❌", e)
print(f"✅ {len(oks)} checagens OK · ❌ {len(erros)} erros")
sys.exit(1 if erros else 0)
