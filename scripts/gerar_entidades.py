#!/usr/bin/env python3
"""
Cofre Aberto MS — dinheiro público para entidades sem fins lucrativos (ONGs, associações, fundações privadas,
organizações religiosas e Organizações Sociais) em MS

Quem é entidade: a natureza jurídica no cadastro da Receita Federal (dados/cnpj_cache.json, coletado por coletar_cnpj.py):
Associação Privada, Fundação Privada, Organização Religiosa, Organização Social (OS) e Serviço Social Autônomo. As
Organizações Sociais que administram hospitais e unidades de saúde em geral aparecem como "Associação Privada".

  Governo de MS   pagamentos do ano a cada entidade (dados/governo_ms_credores.json) e, quando o robô já leu, o órgão pagador
  Prefeitura CG   pagamentos do ano (dados/prefeitura.json), por categoria de despesa (subvenção, serviço hospitalar...) e órgão
  Emendas         emendas parlamentares pagas direto à entidade, com os autores (dados/emendas_municipios.json)

Área de atuação: pela atividade principal (CNAE) na Receita. Associações de servidores, sindicatos e caixas de assistência
recebem do Estado, em geral, o repasse das mensalidades e consignados descontados em folha — ficam numa lista à parte e
fora dos totais.

Gera dados/entidades.json.
"""

import json, re
from datetime import date, datetime
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent))
from coletar_cnpj import abertura_real  # noqa: E402

DADOS = Path(__file__).parent.parent / "dados"
HOJE = date.today()
NATUREZAS = {"Associação Privada", "Fundação Privada", "Organização Religiosa", "Organização Social (OS)", "Serviço Social Autônomo"}
_SERV = (r"SERVIDOR|POLICIA|MILITAR|PROFESSOR|APOSENTAD|SUBTENENTE|SARGENTO|OFICIA|DELEGAD|FISCA|BOMBEIRO|PRA[CÇ]AS|"
         r"AGENTES PENIT|PENSIONIST|MAGISTRAD|PROMOTOR|DEFENSOR|PROCURADOR|AUDITOR|TRABALHADORES EM EDUCA|FUNCION|MEMBROS")
_CLUBE = r"ASSOC|CAIXA|SINDICATO|FEDERA[CÇ][AÃ]O|UNISAUDE|CASSEMS|M[UÚ]TUA|PEC[UÚ]LIO|CLUBE|CENTRO SOCIAL"


class _Consig:
    """Associação, caixa, sindicato ou federação DE servidores (em geral, repasse do que é descontado em folha)."""
    def search(self, nome):
        n = nome or ""
        if re.search(r"SINDICATO RURAL|EQUOTERAPIA|APAE|EXCEPCIONA|PAIS E MESTRE|ESCOLA|COLEGIO", n, re.I):
            return False
        return bool(re.search(r"CASSEMS|UNISAUDE|CAIXA (DE )?ASSIST", n, re.I) or (re.search(_CLUBE, n, re.I) and re.search(_SERV, n, re.I)))


CONSIGNACAO = _Consig()


def carregar(nome):
    try:
        return json.load(open(DADOS / nome, encoding="utf-8"))
    except Exception:
        return {}


def dig(t):
    return re.sub(r"\D", "", str(t or ""))


def area(c):
    cn = str(c.get("cnae") or "")
    if cn.startswith("86"):
        return "Saúde"
    if cn.startswith(("87", "88")):
        return "Assistência social"
    if cn.startswith("85"):
        return "Educação"
    if cn.startswith(("90", "91", "93")):
        return "Cultura, esporte e lazer"
    if cn.startswith("9491"):
        return "Religiosa"
    if cn.startswith(("72", "70", "74")):
        return "Pesquisa, gestão e consultoria"
    if cn.startswith("94"):
        return "Associações e outras entidades"
    return "Outras"


def main():
    cad = carregar("cnpj_cache.json")
    paginas = carregar("empresas_index.json") or {}
    ents = {}

    def ent(doc, nome):
        c = cad.get(doc) or {}
        if c.get("natureza") not in NATUREZAS:
            return None
        e = ents.get(doc)
        if not e:
            abertura = abertura_real(doc, cad) or (c.get("abertura") if doc[8:12] == "0001" else None)  # filial: desde quando a entidade existe
            e = ents[doc] = {"cnpj": doc, "nome": re.sub(r"\s+", " ", c.get("razao") or nome or "").strip(), "fantasia": c.get("fantasia"),
                             "natureza": c.get("natureza"), "area": area(c), "atividade": c.get("cnaeDesc"), "municipio": c.get("municipio"),
                             "uf": c.get("uf"), "abertura": abertura, "aberturaFilial": c.get("abertura") if doc[8:12] != "0001" else None, "situacao": c.get("situacao"),
                             "idadeAnos": round((HOJE - date.fromisoformat(abertura)).days / 365.25, 1) if abertura else None,
                             "dirigentes": [s.get("nome") for s in (c.get("socios") or [])][:6],
                             "consignacao": bool(CONSIGNACAO.search(c.get("razao") or nome or "")),
                             "estado": 0.0, "prefeitura": 0.0, "emendas": 0.0, "orgaosEstado": [], "categoriasPrefeitura": {},
                             "orgaosPrefeitura": {}, "autoresEmendas": [], "pagina": f"/empresa/{doc[:8]}/" if doc[:8] in paginas else None}
        return e

    # Governo do Estado
    for c in carregar("governo_ms_credores.json").get("credores") or []:
        e = ent(dig(c[0]), c[1])
        if e:
            e["estado"] += c[2] or 0
    pag = carregar("governo_ms_contratos.json").get("pagadores") or {}
    for doc, lst in pag.items():
        if doc in ents:
            orgs = {}
            for o, pago, *_ in lst:
                orgs[o] = orgs.get(o, 0) + (pago or 0)
            ents[doc]["orgaosEstado"] = sorted(([o, round(v, 2)] for o, v in orgs.items()), key=lambda t: -t[1])
    # Prefeitura de Campo Grande
    pref = carregar("prefeitura.json")
    for r in pref.get("despesas") or []:
        e = ent(dig(r.get("cnpj")), r.get("fornecedor"))
        if not e:
            continue
        v = r.get("valor") or 0
        e["prefeitura"] += v
        cat = re.sub(r"^\d+\s*-\s*", "", r.get("categoria") or "—").capitalize()
        e["categoriasPrefeitura"][cat] = e["categoriasPrefeitura"].get(cat, 0) + v
        e["orgaosPrefeitura"][r.get("orgao") or "—"] = e["orgaosPrefeitura"].get(r.get("orgao") or "—", 0) + v
    # Emendas parlamentares pagas direto à entidade
    em = carregar("emendas_municipios.json")
    for f in em.get("favorecidos") or []:
        doc = dig(f.get("doc"))
        if f.get("natureza") not in NATUREZAS and (cad.get(doc) or {}).get("natureza") not in NATUREZAS:
            continue
        if doc not in cad:  # sem cadastro: monta com o que a CGU informa
            cad[doc] = {"razao": f.get("nome"), "natureza": f.get("natureza"), "municipio": f.get("municipio")}
        e = ent(doc, f.get("nome"))
        if e:
            e["emendas"] += f.get("valor") or 0
            e["autoresEmendas"] = [[a.get("autor"), round(a.get("valor") or 0, 2)] for a in f.get("autores") or []]

    sinais = {}
    for x in (carregar("auditoria.json") or {}).get("sinais") or []:
        if x.get("cnpj"):
            sinais.setdefault(x["cnpj"], []).append(x.get("rotulo"))
    lista = []
    for e in ents.values():
        e["sinais"] = sorted(set(sinais.get(e["cnpj"], [])))
        e["total"] = round(e["estado"] + e["prefeitura"] + e["emendas"], 2)
        if e["total"] <= 0:
            continue
        for k in ("estado", "prefeitura", "emendas"):
            e[k] = round(e[k], 2)
        for k in ("categoriasPrefeitura", "orgaosPrefeitura"):
            e[k] = sorted(([o, round(v, 2)] for o, v in e[k].items()), key=lambda t: -t[1])
        lista.append(e)
    lista.sort(key=lambda e: -e["total"])
    principais = [e for e in lista if not e["consignacao"]]
    areas = {}
    for e in principais:
        a = areas.setdefault(e["area"], {"area": e["area"], "entidades": 0, "valor": 0.0})
        a["entidades"] += 1
        a["valor"] += e["total"]

    def soma(campo):
        return round(sum(e[campo] for e in principais), 2)

    (DADOS / "entidades.json").write_text(json.dumps({
        "ano": pref.get("ano") or HOJE.year, "geradoEm": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "fontes": {"estado": carregar("governo_ms.json").get("ultimaAtualizacao"), "prefeitura": pref.get("ultimaAtualizacao"),
                   "emendas": em.get("ultimaAtualizacao")},
        "total": round(sum(e["total"] for e in principais), 2), "estado": soma("estado"), "prefeitura": soma("prefeitura"),
        "emendas": soma("emendas"), "quantidade": len(principais), "prefeituraAte": pref.get("ultimoEmpenho"),
        "areas": sorted(({**a, "valor": round(a["valor"], 2)} for a in areas.values()), key=lambda a: -a["valor"]),
        "entidades": principais,
        "consignacoes": {"quantidade": len(lista) - len(principais), "valor": round(sum(e["total"] for e in lista if e["consignacao"]), 2),
                         "lista": [{k: e[k] for k in ("cnpj", "nome", "estado", "prefeitura", "total")} for e in lista if e["consignacao"]][:80]}},
        ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"✅ entidades.json — {len(principais)} entidades, R$ {sum(e['total'] for e in principais):,.0f} "
          f"(Estado {soma('estado'):,.0f} · Prefeitura {soma('prefeitura'):,.0f} · emendas {soma('emendas'):,.0f}); "
          f"{len(lista) - len(principais)} associações de servidores à parte")


if __name__ == "__main__":
    main()
