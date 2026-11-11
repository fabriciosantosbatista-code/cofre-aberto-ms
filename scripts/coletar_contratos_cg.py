#!/usr/bin/env python3
"""
Cofre Aberto MS — Contratos e licitações da Prefeitura de Campo Grande

Fonte: SIG-Transparência (sig-transparencia.campogrande.ms.gov.br), consultas
"Contratos" e "Licitações". Os formulários são Laravel: GET para pegar o _token
e o cookie, POST com download=json devolve a consulta inteira.

Gera dados/prefeitura_contratos.json com:
  contratos     todos os contratos com início no ano (tipo, objeto, fornecedor,
                vigência, valor, situação); o CNPJ é completado pelo nome do
                fornecedor, cruzando com as licitações e as despesas da Prefeitura
  licitacoes    um item por licitação/dispensa (o portal repete a linha para cada
                vencedor — aqui viram uma lista de vencedores)
  fornecedores  quem mais tem contratos e quem mais vence licitações
  resumo        totais por tipo, modalidade e situação

Dívidas parceladas e demandas judiciais aparecem na consulta de contratos, mas
não são compras: ficam fora dos totais de "contratos de compras e serviços"
(o maior item de 2026, por exemplo, é o parcelamento de dívida do IMPCG).

Uso:  python3 scripts/coletar_contratos_cg.py
"""

import json, re, sys, unicodedata
from datetime import date, datetime
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent))
from ano_ref import ano_referencia  # noqa: E402

ROOT = Path(__file__).parent.parent
SAIDA = ROOT / "dados" / "prefeitura_contratos.json"
BASE = "https://sig-transparencia.campogrande.ms.gov.br"
ANO = ano_referencia()
HOJE = date.today()
NAO_COMPRA = {"DIVIDA", "DÍVIDA", "DEMANDA JUDICIAL"}


def consulta(caminho, campos, tentativas=3):
    erro = None
    for _ in range(tentativas):
        try:
            s = requests.Session()
            s.headers.update({"User-Agent": "Mozilla/5.0 (CofreAbertoMS; transparencia publica)"})
            r = s.get(BASE + caminho, timeout=90)
            r.raise_for_status()
            m = re.search(r'name="_token" value="([^"]+)"', r.text)
            if not m:
                raise RuntimeError("token do formulário não encontrado")
            r = s.post(BASE + caminho, timeout=300, data={"_token": m.group(1), "page": "1", "download": "json", **campos})
            r.raise_for_status()
            linhas = r.json()
            if isinstance(linhas, list):
                return linhas
            erro = "resposta não é lista"
        except Exception as e:
            erro = str(e)
    raise RuntimeError(f"{caminho}: {erro}")


def limpa(t):
    return re.sub(r"\s+", " ", str(t or "")).strip()


def chave_nome(t):
    t = unicodedata.normalize("NFD", limpa(t).upper()).encode("ascii", "ignore").decode()
    t = re.sub(r"[^A-Z0-9 ]", " ", t)
    t = re.sub(r"\b(LTDA|EPP|ME|EIRELI|S A|SA|S/A)\b", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def iso(d):
    d = limpa(d)
    return f"{d[6:10]}-{d[3:5]}-{d[:2]}" if re.match(r"\d{2}/\d{2}/\d{4}", d) else None


def num(v):
    try:
        return round(float(v), 2)
    except (TypeError, ValueError):
        return None


def so_digitos(t):
    return re.sub(r"\D", "", str(t or "")) or None


def cnpj_por_nome():
    """Nome → CNPJ a partir das despesas da Prefeitura (mesma base cadastral)."""
    mapa = {}
    try:
        d = json.load(open(ROOT / "dados" / "prefeitura.json", encoding="utf-8"))
        for x in d.get("despesas", []):
            if x.get("cnpj") and x.get("fornecedor"):
                mapa.setdefault(chave_nome(x["fornecedor"]), so_digitos(x["cnpj"]))
    except Exception:
        pass
    return mapa


def main():
    print(f"📑 Contratos e licitações — Prefeitura de Campo Grande {ANO}")
    fim = HOJE if ANO == HOJE.year else date(ANO, 12, 31)
    try:
        anterior = json.load(open(SAIDA, encoding="utf-8"))
    except Exception:
        anterior = {}

    try:
        brutos_c = consulta("/contratos/consulta", {
            "orderColumn": "contratos.data_inicio", "orderDirection": "DESC",
            "periodo-inicio": f"{ANO}-01-01", "periodo-fim": fim.isoformat(), "tipo": "", "orgao": "",
            "fornecedor": "", "cpf_cnpj": "", "objeto_contrato": "", "registro_cadastral": ""})
        brutos_l = consulta("/licitacoes/consulta", {
            "orderColumn": "data", "orderDirection": "DESC", "ano": str(ANO), "status": "", "palavra_chave": "",
            "numero_edital": "", "processo_origem": "", "gestor": "", "modalidade": "", "cpf_cnpj": ""})
    except Exception as e:
        print(f"❌ {e} — arquivo anterior mantido")
        sys.exit(1)
    if not brutos_c and not brutos_l:
        print("❌ consultas vazias — arquivo anterior mantido")
        sys.exit(1)
    if anterior.get("ano") == ANO and len(brutos_c) + len(brutos_l) < 0.5 * (
            len(anterior.get("contratos", [])) + anterior.get("resumo", {}).get("linhasLicitacoes", 0)):
        print("❌ consulta veio com menos da metade dos registros de ontem — arquivo anterior mantido")
        sys.exit(1)

    # Licitações: agrupa as linhas por processo (uma por vencedor)
    licit, nomes_cnpj = {}, cnpj_por_nome()
    for x in brutos_l:
        k = (x.get("codigomodalidade"), limpa(x.get("numero")), limpa(x.get("processo_origem")))
        l = licit.get(k)
        if not l:
            l = licit[k] = {"data": iso(x.get("data")), "modalidade": limpa(x.get("modalidade")).title(),
                            "numero": limpa(x.get("numero")), "edital": x.get("numeroedital"),
                            "status": limpa(x.get("status")), "objeto": limpa(x.get("descricao"))[:400],
                            "gestor": limpa(x.get("gestorcompras")), "valorEstimado": num(x.get("valorestimado")),
                            "processo": limpa(x.get("processo_origem")), "vencedores": []}
        cnpj, nome = so_digitos(x.get("cnpjfornecedor")), limpa(x.get("nomefornecedor"))
        if nome and all(v["nome"] != nome for v in l["vencedores"]):
            l["vencedores"].append({"cnpj": cnpj, "nome": nome})
            if cnpj:
                nomes_cnpj.setdefault(chave_nome(nome), cnpj)
        v = num(x.get("valorestimado"))
        if v and (l["valorEstimado"] or 0) < v:
            l["valorEstimado"] = v
    licitacoes = sorted(licit.values(), key=lambda l: l["data"] or "", reverse=True)

    contratos = []
    for x in brutos_c:
        tipo = limpa(x.get("descr_tipo"))
        forn = limpa(x.get("fornecedor"))
        contratos.append({"tipo": tipo, "compra": tipo.upper() not in NAO_COMPRA,
                          "objeto": limpa(x.get("objeto"))[:400], "fornecedor": forn,
                          "cnpj": nomes_cnpj.get(chave_nome(forn)), "inicio": iso(x.get("data_inicio")),
                          "fim": iso(x.get("data_fim")), "valor": num(x.get("total_contrato")) or 0,
                          "situacao": limpa(x.get("descr_situacao")), "registro": x.get("registro_cadastral")})
    contratos.sort(key=lambda c: -c["valor"])

    # Ranking de fornecedores (contratos de compras/serviços + licitações vencidas)
    forn = {}
    def item(nome, cnpj):
        k = cnpj or chave_nome(nome)
        f = forn.setdefault(k, {"nome": nome, "cnpj": cnpj, "contratos": 0, "valorContratos": 0.0,
                                "licitacoesVencidas": 0})
        if cnpj and not f["cnpj"]:
            f["cnpj"] = cnpj
        return f
    for c in contratos:
        if c["compra"] and c["fornecedor"]:
            f = item(c["fornecedor"], c["cnpj"])
            f["contratos"] += 1
            f["valorContratos"] += c["valor"]
    for l in licitacoes:
        for v in l["vencedores"]:
            item(v["nome"], v["cnpj"] or nomes_cnpj.get(chave_nome(v["nome"])))["licitacoesVencidas"] += 1
    fornecedores = sorted(forn.values(), key=lambda f: (-f["valorContratos"], -f["licitacoesVencidas"]))
    for f in fornecedores:
        f["valorContratos"] = round(f["valorContratos"], 2)

    def conta(lista, campo):
        out = {}
        for x in lista:
            out[x[campo] or "—"] = out.get(x[campo] or "—", 0) + 1
        return dict(sorted(out.items(), key=lambda kv: -kv[1]))

    por_tipo = {}
    for c in contratos:
        t = por_tipo.setdefault(c["tipo"] or "—", {"quantidade": 0, "valor": 0.0, "compra": c["compra"]})
        t["quantidade"] += 1
        t["valor"] = round(t["valor"] + c["valor"], 2)
    compras = [c for c in contratos if c["compra"]]
    resumo = {
        "contratos": len(contratos), "contratosCompras": len(compras),
        "valorCompras": round(sum(c["valor"] for c in compras), 2),
        "valorNaoCompras": round(sum(c["valor"] for c in contratos if not c["compra"]), 2),
        "porTipo": dict(sorted(por_tipo.items(), key=lambda kv: -kv[1]["valor"])),
        "licitacoes": len(licitacoes), "linhasLicitacoes": len(brutos_l),
        "porModalidade": conta(licitacoes, "modalidade"), "porStatus": conta(licitacoes, "status"),
        "valorEstimadoLicitacoes": round(sum(l["valorEstimado"] or 0 for l in licitacoes), 2),
        "comVencedor": sum(1 for l in licitacoes if l["vencedores"]),
        "contratosComCnpj": sum(1 for c in contratos if c["cnpj"]),
    }
    out = {"ano": ANO, "ultimaAtualizacao": datetime.now().isoformat(timespec="seconds"),
           "fonte": BASE + "/contratos/consulta", "fonteLicitacoes": BASE + "/licitacoes/consulta",
           "resumo": resumo, "fornecedores": fornecedores[:500], "contratos": contratos, "licitacoes": licitacoes}
    SAIDA.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"  contratos: {len(contratos)} (compras R$ {resumo['valorCompras']:,.2f}; "
          f"com CNPJ {resumo['contratosComCnpj']}) · licitações: {len(licitacoes)} "
          f"({resumo['comVencedor']} com vencedor) · fornecedores: {len(fornecedores)}")
    print(f"✅ {SAIDA.relative_to(ROOT)} ({SAIDA.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
