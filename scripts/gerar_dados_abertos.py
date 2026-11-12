#!/usr/bin/env python3
"""
Cofre Aberto MS — dados abertos para download + status de cada fonte

Roda no fim da coleta diária (depois de gerar_analises.py) e gera:

1. dados/csv/*.csv — uma planilha por aba do painel (e uma de notas fiscais
   onde houver). Formato pensado para o Excel em português: separador ";",
   vírgula decimal, UTF-8 com BOM. Para uso em código, os JSONs originais
   continuam em dados/.

2. dados/status_fontes.json — para cada aba: qual a fonte oficial, quando
   foi a última coleta, qual o dado mais recente (nota, empenho, folha) e um
   nível "ok" ou "atencao", exibido como selo no topo de cada aba e na
   página de Metodologia.
"""

import csv, io, json
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).parent.parent
DADOS = ROOT / "dados"
HOJE = date.today()
import sys as _sys
_sys.path.insert(0, str(Path(__file__).parent))
from ano_ref import ano_referencia
ANO = ano_referencia()
MESES = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]


def carregar(nome):
    try:
        return json.load(open(DADOS / nome, encoding="utf-8"))
    except Exception:
        return {}


def num(v):
    """Número no padrão brasileiro (vírgula decimal), vazio se não houver."""
    if v is None or v == "":
        return ""
    try:
        return f"{float(v):.2f}".replace(".", ",")
    except (TypeError, ValueError):
        return str(v)


def grava_csv(nome, cabecalho, linhas):
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";", quoting=csv.QUOTE_MINIMAL, lineterminator="\n")
    w.writerow(cabecalho)
    for l in linhas:
        w.writerow(["" if x is None else x for x in l])
    path = DADOS / "csv" / nome
    path.parent.mkdir(parents=True, exist_ok=True)
    novo = ("﻿" + buf.getvalue()).encode("utf-8")
    if not path.exists() or path.read_bytes() != novo:
        path.write_bytes(novo)
    return len(linhas)


def dias(iso):
    try:
        return (HOJE - datetime.fromisoformat(str(iso)[:10]).date()).days
    except (TypeError, ValueError):
        return None


def em_dia(iso, limite):
    """True se a data existe e tem no máximo `limite` dias (0 = hoje conta como em dia)."""
    d = dias(iso)
    return d is not None and d <= limite


def data_br(iso):
    try:
        return datetime.fromisoformat(str(iso)[:10]).strftime("%d/%m/%Y")
    except (TypeError, ValueError):
        return None


# ------------------------------------------------------------------
# CSVs
# ------------------------------------------------------------------
def gerar_csvs():
    contagem = {}
    cg = carregar("camara_municipal.json").get("vereadores", [])
    contagem["vereadores_cg.csv"] = grava_csv("vereadores_cg.csv",
        ["vereador", "nome_completo", "partido", f"verba_paga_{ANO}", "verba_ato027", "verba_ato028", "cota_anual",
         "pct_cota", "notas_fiscais", "funcionarios_gabinete", "gasto_pessoal_gabinete_mensal", "subsidio_mensal", "observacao_coleta"],
        [[v["nome"], v.get("nomeCompleto"), v.get("partido"),
          num((v.get("verbaIndenizatoria") or {}).get(f"gastoPago{ANO}")),
          num((v.get("verbaIndenizatoria") or {}).get(f"gastoAto027_{ANO}")),
          num((v.get("verbaIndenizatoria") or {}).get(f"gastoAto028_{ANO}")),
          num((v.get("verbaIndenizatoria") or {}).get(f"cotaAnual{ANO}")),
          num((v.get("verbaIndenizatoria") or {}).get("percentualUsado")),
          v.get("totalNotasFiscais"), (v.get("gabinete") or {}).get("numFuncionarios"),
          num((v.get("gabinete") or {}).get("gastoPessoalMensal")), num(v.get("salarioBase")),
          (v.get("verbaIndenizatoria") or {}).get("notaColeta")] for v in cg])
    contagem["vereadores_cg_notas.csv"] = grava_csv("vereadores_cg_notas.csv",
        ["vereador", "data", "fornecedor", "cnpj_cpf", "valor", "ato", "descricao", "documento"],
        [[v["nome"], n.get("data"), n.get("fornecedor"), n.get("cnpj"), num(n.get("valor")), n.get("ato"),
          n.get("descricao"), n.get("nf")] for v in cg for n in v.get("despesas") or []])

    est = carregar("deputados_estaduais_ms.json").get("vereadores", [])
    contagem["deputados_estaduais.csv"] = grava_csv("deputados_estaduais.csv",
        ["deputado", "partido", f"ceap_paga_{ANO}", "cota_anual", "pct_cota", "notas_fiscais", "subsidio_mensal", "periodo"],
        [[d["nome"], d.get("partido"), num((d.get("verbaIndenizatoria") or {}).get(f"gastoPago{ANO}")),
          num((d.get("verbaIndenizatoria") or {}).get(f"cotaAnual{ANO}")),
          num((d.get("verbaIndenizatoria") or {}).get("percentualUsado")), len(d.get("despesas") or []),
          num(d.get("salarioBase")), (d.get("verbaIndenizatoria") or {}).get("periodoColetado")] for d in est])
    contagem["deputados_estaduais_notas.csv"] = grava_csv("deputados_estaduais_notas.csv",
        ["deputado", "mes_competencia", "data_emissao", "categoria", "fornecedor", "cnpj_cpf", "documento", "valor", "link_pdf"],
        [[d["nome"], n.get("mes"), n.get("data"), n.get("categoria"), n.get("fornecedor"), n.get("cnpj"), n.get("nf"),
          num(n.get("valor")), n.get("urlPdf")] for d in est for n in d.get("despesas") or []])

    fed = carregar("deputados_federais_ms.json").get("deputados", [])
    contagem["deputados_federais_ms.csv"] = grava_csv("deputados_federais_ms.csv",
        ["deputado", "id_camara", "partido", f"ceap_{ANO}", "notas_fiscais", "perfil_oficial"],
        [[d["nome"], d["id"], d.get("partido"), num(d.get("cotaGastaAno")), d.get("totalNotasFiscais"), d.get("urlPerfil")] for d in fed])
    contagem["deputados_federais_ms_notas.csv"] = grava_csv("deputados_federais_ms_notas.csv",
        ["deputado", "mes_competencia", "data_emissao", "categoria", "fornecedor", "cnpj_cpf", "documento", "valor", "link_documento"],
        [[d["nome"], n.get("mes"), n.get("data"), n.get("categoria"), n.get("fornecedor"), n.get("cnpjCpfFornecedor"),
          n.get("doc"), num(n.get("valor")), n.get("urlNotaFiscal")] for d in fed for n in d.get("despesas") or []])

    sen = carregar("senadores_ms.json").get("senadores", [])
    contagem["senadores_ms.csv"] = grava_csv("senadores_ms.csv",
        ["senador", "id_senado", "partido", f"ceaps_{ANO}", "gasto_total_com_extras", "notas_fiscais", "portal_oficial"],
        [[s["nome"], s["id"], s.get("partido"), num(s.get("cotaGastaAno")), num(s.get("totalGasto")),
          len(s.get("notasCeaps") or []), s.get("urlTransparencia")] for s in sen])
    contagem["senadores_ms_notas.csv"] = grava_csv("senadores_ms_notas.csv",
        ["senador", "mes_competencia", "data", "categoria", "tipo_documento", "fornecedor", "cnpj_cpf", "documento", "detalhamento", "valor"],
        [[s["nome"], n.get("mes"), n.get("data"), n.get("categoria"), n.get("tipoDocumento"), n.get("fornecedor"),
          n.get("cnpjCpf"), n.get("doc"), n.get("detalhamento"), num(n.get("valor"))] for s in sen for n in s.get("notasCeaps") or []])

    br = carregar("deputados_federais_brasil.json").get("deputados", [])
    contagem["deputados_federais_brasil.csv"] = grava_csv("deputados_federais_brasil.csv",
        ["deputado", "id_camara", "partido", "uf", f"ceap_{ANO}", "notas_fiscais", "perfil_oficial"],
        [[d["nome"], d["id"], d.get("partido"), d.get("uf"), num(d.get("cotaGastaAno")), d.get("totalNotasFiscais"), d.get("urlPerfil")] for d in br])
    sbr = carregar("senadores_brasil.json").get("senadores", [])
    contagem["senadores_brasil.csv"] = grava_csv("senadores_brasil.csv",
        ["senador", "id_senado", "partido", "uf", f"ceaps_{ANO}", "portal_oficial"],
        [[s["nome"], s["id"], s.get("partido"), s.get("uf"), num(s.get("cotaGastaAno")), s.get("urlTransparencia")] for s in sbr])

    pref = carregar("prefeitura.json").get("despesas", [])
    contagem["prefeitura_despesas.csv"] = grava_csv("prefeitura_despesas.csv",
        ["data_empenho", "orgao", "categoria", "fornecedor", "cnpj_cpf", "valor_pago", "valor_empenhado", "modalidade_licitacao", "link_detalhe"],
        [[d.get("data"), d.get("orgao"), d.get("categoria"), d.get("fornecedor"), d.get("cnpj"), num(d.get("valor")),
          num(d.get("empenhado")), d.get("modalidade"), d.get("urlDetalhe")] for d in pref])

    ct = carregar("prefeitura_contratos.json")
    contagem["prefeitura_contratos.csv"] = grava_csv("prefeitura_contratos.csv",
        ["inicio", "fim", "tipo", "compra_ou_servico", "fornecedor", "cnpj", "objeto", "valor", "situacao", "registro_cadastral"],
        [[c.get("inicio"), c.get("fim"), c.get("tipo"), "sim" if c.get("compra") else "não", c.get("fornecedor"), c.get("cnpj"),
          c.get("objeto"), num(c.get("valor")), c.get("situacao"), c.get("registro")] for c in ct.get("contratos", [])])
    contagem["prefeitura_licitacoes.csv"] = grava_csv("prefeitura_licitacoes.csv",
        ["data", "modalidade", "numero", "processo", "situacao", "objeto", "gestor", "valor_estimado", "vencedor", "cnpj_vencedor"],
        [[l.get("data"), l.get("modalidade"), l.get("numero"), l.get("processo"), l.get("status"), l.get("objeto"), l.get("gestor"),
          num(l.get("valorEstimado")), v.get("nome"), v.get("cnpj")]
         for l in ct.get("licitacoes", []) for v in (l.get("vencedores") or [{}])])

    em = carregar("emendas_municipios.json")
    contagem["emendas_municipios.csv"] = grava_csv("emendas_municipios.csv",
        ["municipio", "autor_da_emenda", "parlamentar_atual_de_ms", f"valor_recebido_{ANO}"],
        [[m["municipio"], a["autor"], "sim" if a.get("atual") else "não", num(a["valor"])]
         for m in em.get("municipios", []) for a in m.get("autores", [])])
    contagem["emendas_favorecidos.csv"] = grava_csv("emendas_favorecidos.csv",
        ["favorecido", "cnpj_cpf", "natureza_juridica", "municipio", f"valor_recebido_{ANO}", "autores"],
        [[f["nome"], f.get("doc"), f.get("natureza"), f.get("municipio"), num(f["valor"]),
          " | ".join(f"{a['autor']} ({num(a['valor'])})" for a in f.get("autores", []))] for f in em.get("favorecidos", [])])
    ss = carregar("supersalarios.json")
    contagem["supersalarios_ranking.csv"] = grava_csv("supersalarios_ranking.csv",
        ["posicao", "nome", "cargo", "orgao", "lotacao_ou_vinculo", "situacao", "mes", "remuneracao_base", "outras_ou_eventuais",
         "bruto", "descontos", "liquido", "bruto_acima_do_teto", "itens_alem_da_base"],
        [[i + 1, p.get("nome"), p.get("cargo"), p.get("orgao"), p.get("lotacao"), p.get("situacao"), p.get("mes"), num(p.get("base")),
          num(p.get("outras")), num(p.get("bruto")), num(p.get("descontos")), num(p.get("liquido")), num(p.get("acimaTeto")),
          " | ".join(f"{x['item']}: {num(x['valor'])}" for x in p.get("itens") or [])] for i, p in enumerate(ss.get("ranking", []))])
    contagem["supersalarios_orgaos.csv"] = grava_csv("supersalarios_orgaos.csv",
        ["orgao", "mes", "pessoas", "media_bruta", "maior_bruto", "liquido_acima_do_teto", "bruto_acima_do_teto",
         "valor_bruto_acima_do_teto", "total_base", "total_outras", "fonte"],
        [[o["orgao"], o["mes"], o["pessoas"], num(o["mediaBruta"]), num(o["maiorBruto"]), o.get("liquidoAcimaTeto"), o["acimaTeto"],
          num(o["valorAcimaTeto"]), num(o["totalBase"]), num(o["totalOutras"]), o["fonte"]]
         for o in ss.get("orgaos", []) + ss.get("orgaosGoverno", [])])
    contagem["supersalarios_penduricalhos.csv"] = grava_csv("supersalarios_penduricalhos.csv",
        ["orgao", "mes", "item", "categoria_dadosjusbr", "valor_total", "pessoas"],
        [[p["orgao"], p["mes"], i["item"], i["categoria"], num(i["valor"]), i["pessoas"]]
         for p in (ss.get("penduricalhos") or {}).values() for i in p["itens"] if i["valor"]])

    al = carregar("alems_servidores.json")
    contagem["alems_servidores.csv"] = grava_csv("alems_servidores.csv",
        ["matricula", "nome", "cargo", "simbolo", "vencimento_base_tabela"],
        [[x.get("matricula"), x.get("nome"), x.get("cargo"), x.get("simbolo"), num(x.get("vencimento"))] for x in al.get("servidores", [])])
    alc = carregar("alertas_contratos.json")
    contagem["alertas_contratos.csv"] = grava_csv("alertas_contratos.csv",
        ["visto_em", "tipo", "titulo", "descricao", "empresa", "cnpj", "valor", "data"],
        [[a.get("vistoEm"), a.get("rotulo"), a.get("titulo"), a.get("descricao"), a.get("empresa"), a.get("cnpj"),
          num(a.get("valor")), a.get("data")] for a in alc.get("alertas", [])])
    gc = carregar("governo_ms_contratos.json")
    contagem["governo_ms_contratos.csv"] = grava_csv("governo_ms_contratos.csv",
        ["orgao", "orgao_nome", "numero", "fornecedor", "cnpj_cpf", "modalidade", "situacao", "inicio", "fim", "renovacoes", "valor_inicial", "valor_atual"],
        [[c.get("orgao"), c.get("orgaoNome"), c.get("numero"), c.get("fornecedor"), c.get("cnpj"), c.get("modalidade"), c.get("situacao"),
          c.get("inicio"), c.get("fim"), c.get("renovacoes"), num(c.get("valorInicial")), num(c.get("valor"))] for c in gc.get("contratos", [])])
    contagem["governo_ms_obras.csv"] = grava_csv("governo_ms_obras.csv",
        ["orgao", "numero", "processo", "fornecedor", "cnpj", "objeto", "municipios", "situacao", "inicio", "fim", "prazo_inicial_dias",
         "dias_aditados", "dias_paralisados", "percentual_executado", "valor_atual"],
        [[o.get("orgao"), o.get("numero"), o.get("processo"), o.get("fornecedor"), o.get("cnpj"), o.get("objeto"), o.get("municipios"),
          o.get("situacao"), o.get("inicio"), o.get("fim"), o.get("prazoInicial"), o.get("diasAditados"), o.get("diasParalisados"),
          o.get("executado"), num(o.get("valor"))] for o in gc.get("obras", [])])
    pr = carregar("presidencia.json")
    contagem["presidencia_cartao.csv"] = grava_csv("presidencia_cartao.csv",
        ["mes", "presidente", "presidencia_total", "presidencia_sigiloso", "vice_total", "vice_sigiloso"],
        [[x["mes"], x["presidente"], num(x["pr"]), num(x["prSig"]), num(x["vice"]), num(x["viceSig"])] for x in (pr.get("cartao") or {}).get("serie", [])])
    contagem["presidencia_viagens_ministros.csv"] = grava_csv("presidencia_viagens_ministros.csv",
        ["ano", "ministro", "orgao", "viagens", "diarias", "passagens", "outros", "total", "destinos_mais_frequentes"],
        [[a, m["nome"], m["orgao"], m["viagens"], num(m["diarias"]), num(m["passagens"]), num(m["outros"]), num(m["total"]), " | ".join(m["destinos"])]
         for a, v in sorted((pr.get("viagens") or {}).items()) for m in v.get("ministros", [])])
    contagem["presidencia_ministros.csv"] = grava_csv("presidencia_ministros.csv",
        ["mes", "ministro", "orgao", "remuneracao_bruta", "abate_teto", "eventuais_jetons", "ferias", "gratificacao_natalina", "liquido", "indenizatorias"],
        [[(pr.get("remuneracao") or {}).get("mes"), m["nome"], m["orgao"], num(m["bruto"]), num(m["abateTeto"]), num(m["eventuais"]),
          num(m["ferias"]), num(m["natalina"]), num(m["liquido"]), num(m["indenizatorias"])] for m in (pr.get("remuneracao") or {}).get("ministros", [])])
    ms = pr.get("ms") or {}
    contagem["uniao_transferencias_ms.csv"] = grava_csv("uniao_transferencias_ms.csv", ["recorte", "nome", f"valor_{ms.get('ano')}"],
        [[r, x["nome"], num(x["valor"])] for r in ("tipo", "orgao", "municipio") for x in ms.get(r, [])])
    gl = carregar("governo_ms_licitacoes.json")
    contagem["governo_ms_licitacoes.csv"] = grava_csv("governo_ms_licitacoes.csv",
        ["id_pncp", "orgao", "unidade", "modalidade", "numero", "processo", "data", "objeto", "situacao", "valor_estimado", "valor_homologado", "vencedores", "link"],
        [[c.get("id"), c.get("orgao"), c.get("unidade"), c.get("modalidade"), c.get("numero"), c.get("processo"), c.get("data"), c.get("objeto"),
          c.get("situacao"), num(c.get("estimado")), num(c.get("homologado")),
          " | ".join(f"{v['nome']} ({v['cnpj']}): {num(v['valor'])}" for v in c.get("vencedores") or []), c.get("link")] for c in gl.get("compras", [])])
    au = carregar("auditoria.json")
    contagem["auditoria_sinais.csv"] = grava_csv("auditoria_sinais.csv",
        ["visto_em", "teste", "nivel", "titulo", "descricao", "quem_pagou", "empresa", "cnpj", "valor", "evidencias"],
        [[s.get("vistoEm"), s.get("rotulo"), s.get("nivel"), s.get("titulo"), s.get("descricao"), s.get("quem"), s.get("empresa"),
          s.get("cnpj"), num(s.get("valor")), " | ".join(s.get("evidencias") or [])] for s in au.get("sinais", [])])

    gov = carregar("governo_ms.json")
    contagem["governo_ms_orgaos.csv"] = grava_csv("governo_ms_orgaos.csv",
        ["codigo_unidade_gestora", "orgao", "empenhado", "liquidado", "pago"],
        [[o.get("codigo"), o.get("orgao"), num(o.get("empenhado")), num(o.get("liquidado")), num(o.get("pago"))] for o in gov.get("orgaos", [])])
    gcred = carregar("governo_ms_credores.json")
    contagem["governo_ms_credores.csv"] = grava_csv("governo_ms_credores.csv",
        ["cnpj_cpf", "credor", f"pago_{ANO}", f"empenhado_{ANO}", "tipo"],
        [[c[0], c[1], num(c[2]), num(c[3]), c[4] if len(c) > 4 else ""] for c in sorted(gcred.get("credores", []), key=lambda c: -(c[2] or 0))])
    di = gov.get("diarias") or {}
    contagem["governo_ms_diarias.csv"] = grava_csv("governo_ms_diarias.csv",
        ["nome", "cpf_mascarado", "cargo", "orgao", "tipo_beneficiario", "trechos", "valor", "destinos_mais_frequentes"],
        [[p.get("nome"), p.get("cpf"), p.get("cargo"), p.get("orgao"), p.get("tipo"), p.get("trechos"), num(p.get("valor")),
          " | ".join(p.get("destinos") or [])] for p in di.get("maiores", [])])
    pe = gov.get("primeiroEscalao") or {}
    contagem["governo_ms_primeiro_escalao.csv"] = grava_csv("governo_ms_primeiro_escalao.csv",
        ["competencia", "nome", "cargo", "orgao", "situacao", "remuneracao_fixa", "remuneracoes_eventuais", "bruto", "liquido", f"bruto_soma_{ANO}"],
        [[pe.get("competencia"), p.get("nome"), p.get("cargo"), p.get("orgao"), p.get("situacao"), num(p.get("fixa")),
          num(p.get("eventuais")), num(p.get("bruto")), num(p.get("liquido")), num(p.get("somaAno"))] for p in pe.get("pessoas", [])])

    linhas = []
    for arq, trib in (("trt24_magistrados.json", "TRT24"), ("tre_ms_magistrados.json", "TRE-MS"), ("tjms_magistrados.json", "TJMS")):
        j = carregar(arq)
        for m in j.get("magistrados", []):
            linhas.append([trib, j.get("mesReferencia"), m.get("nome"), m.get("cargo"), m.get("lotacao"), m.get("situacao"),
                           num(m.get("subsidio")), num(m.get("vantagensPessoais")), num(m.get("indenizacoes")),
                           num(m.get("vantagensEventuais")), num(m.get("gratificacoes")), num(m.get("remuneracaoBruta")),
                           num(m.get("totalDescontos")), num(m.get("remuneracaoLiquida")), num(m.get("diarias"))])
    contagem["judiciario_magistrados.csv"] = grava_csv("judiciario_magistrados.csv",
        ["tribunal", "mes_referencia", "nome", "cargo", "lotacao", "situacao", "subsidio", "vantagens_pessoais", "indenizacoes",
         "vantagens_eventuais", "gratificacoes", "remuneracao_bruta", "total_descontos", "remuneracao_liquida", "diarias"], linhas)

    linhas = []
    for f in sorted((DADOS / "camaras").glob("*.json")):
        j = carregar(f"camaras/{f.name}")
        for v in j.get("vereadores", []):
            linhas.append([j.get("cidade"), v.get("nome"), num(v.get("subsidioMensal")), v.get("referenciaFolha"),
                           num(v.get(f"totalDiarias{ANO}")), v.get(f"numDiarias{ANO}"), (j.get("ultimaAtualizacao") or "")[:10]])
    contagem["camaras_interior.csv"] = grava_csv("camaras_interior.csv",
        ["cidade", "vereador", "subsidio_mensal", "referencia_folha", f"diarias_{ANO}", f"num_diarias_{ANO}", "ultima_coleta"], linhas)

    cx = carregar("conexoes_fornecedores.json").get("conexoes", [])
    contagem["conexoes_fornecedores.csv"] = grava_csv("conexoes_fornecedores.csv",
        ["empresa", "cnpj_raiz", "cnpjs", "num_pagadores", "pagador", "cargo_pagador", "partido", "valor_pago", "notas"],
        [[c["nome"], c["raiz"], " | ".join(c["cnpjs"]), c["numPagadores"], p["nome"], p["rotulo"], p.get("partido"),
          num(p["total"]), p["notas"]] for c in cx for p in c["pagadores"]])

    ev = carregar("evolucao_mensal.json")
    linhas = []
    for g, lst in (ev.get("grupos") or {}).items():
        for p in lst:
            for i, m in enumerate(MESES):
                linhas.append([g, p["nome"], p.get("partido"), i + 1, m, num(p["m"][i]),
                               num(p["mAnterior"][i]) if p.get("mAnterior") else ""])
    contagem["evolucao_mensal.csv"] = grava_csv("evolucao_mensal.csv",
        ["grupo", "parlamentar", "partido", "mes", "mes_nome", f"valor_{ANO}", f"valor_{ANO - 1}"], linhas)
    return contagem


# ------------------------------------------------------------------
# Status por fonte
# ------------------------------------------------------------------
def status_fontes():
    st = {}

    def add(aba, fonte, url, coleta, recente_txt, ok, msg=None):
        st[aba] = {"fonte": fonte, "url": url, "coleta": coleta, "dadoMaisRecente": recente_txt,
                   "nivel": "ok" if ok else "atencao", "mensagem": msg}

    def max_data(itens):
        d = [str(x) for x in itens if x]
        return max(d) if d else None

    cg = carregar("camara_municipal.json")
    ult = -1
    for v in cg.get("vereadores", []):
        vi = v.get("verbaIndenizatoria") or {}
        for m in list(vi.get("mesesAto027") or {}) + list(vi.get("mesesAto028") or {}):
            if m in MESES:
                ult = max(ult, MESES.index(m))
    atraso = ((HOJE.year * 12 + HOJE.month) - (ANO * 12 + ult + 1)) if ult >= 0 else 99
    add("camara", "Portal da Transparência da Câmara Municipal de Campo Grande (SCPI Fiorilli)",
        "http://45.225.6.93:8079/transparencia/", max(filter(None, [cg.get("ultimaAtualizacao"), cg.get("ultimaVerificacao")])),
        f"verba indenizatória até {MESES[ult]}/{ANO}" if ult >= 0 else None,
        atraso <= 3 and em_dia(max(filter(None, [cg.get("ultimaAtualizacao"), cg.get("ultimaVerificacao")])), 3),
        None if atraso <= 3 else "a Câmara ainda não publicou os PDFs dos meses mais recentes")

    est = carregar("deputados_estaduais_ms.json")
    d = max_data(n.get("data") for v in est.get("vereadores", []) for n in v.get("despesas") or [])
    add("deputados-estaduais", "Portal da Transparência da ALEMS — CEAP", "https://transparencia2.al.ms.gov.br/ceap",
        est.get("ultimaAtualizacao"), f"nota fiscal de {data_br(d)}" if d else None, em_dia(d, 30))

    fed = carregar("deputados_federais_ms.json")
    d = max_data(n.get("data") for v in fed.get("deputados", []) for n in v.get("despesas") or [])
    add("deputados", "Câmara dos Deputados — arquivo completo da CEAP", "https://www.camara.leg.br/cotas/",
        fed.get("ultimaAtualizacao"), f"nota fiscal de {data_br(d)}" if d else None, em_dia(d, 30))

    sen = carregar("senadores_ms.json")
    d = max_data(n.get("data") for v in sen.get("senadores", []) for n in v.get("notasCeaps") or [])
    add("senadores", "Senado Federal — dados abertos da CEAPS", "https://adm.senado.gov.br/adm-dadosabertos/swagger-ui/index.html",
        sen.get("ultimaAtualizacao"), f"nota fiscal de {data_br(d)}" if d else None, em_dia(d, 45))

    pref = carregar("prefeitura.json")
    d = pref.get("ultimoEmpenho")
    add("prefeitura", "SIG-Transparência da Prefeitura de Campo Grande", "https://sig-transparencia.campogrande.ms.gov.br/despesas/consulta",
        pref.get("ultimaAtualizacao"), f"empenho de {data_br(d)}" if d else None, em_dia(d, 45))

    ct = carregar("prefeitura_contratos.json")
    d = max_data(c.get("inicio") for c in ct.get("contratos", []))
    dl = max_data(l.get("data") for l in ct.get("licitacoes", []))
    add("contratos-cg", "SIG-Transparência da Prefeitura de Campo Grande — Contratos e Licitações",
        "https://sig-transparencia.campogrande.ms.gov.br/contratos/consulta", ct.get("ultimaAtualizacao"),
        f"contrato de {data_br(d)}, licitação de {data_br(dl)}" if d and dl else None,
        ct.get("ano") == ANO and em_dia(max_data([d, dl]), 45))

    gov = carregar("governo_ms.json")
    trechos = (gov.get("diarias") or {}).get("trechos")
    pe = gov.get("primeiroEscalao") or {}
    partes = [f"despesas até {data_br((gov.get('ultimaAtualizacao') or '')[:10])}" if gov.get("totais") else None,
              f"folha de {pe['competencia']}" if pe.get("competencia") else None,
              f"{trechos:,} trechos de diárias".replace(",", ".") if trechos else None]
    add("governo-ms", "Portal da Transparência do Estado de Mato Grosso do Sul", "https://www.transparencia.ms.gov.br/",
        gov.get("ultimaAtualizacao"), ", ".join(p for p in partes if p) or None,
        gov.get("ano") == ANO and bool(gov.get("totais")) and not gov.get("coletaParcial"),
        "parte das consultas do portal estadual falhou na última coleta" if gov.get("coletaParcial") else None)

    em = carregar("emendas_municipios.json")
    add("emendas", "Portal da Transparência do Governo Federal (CGU) — emendas por favorecido",
        "https://portaldatransparencia.gov.br/download-de-dados/emendas-parlamentares", em.get("ultimaAtualizacao"),
        f"pagamentos até {em['mesMaisRecente']}" if em.get("mesMaisRecente") else None,
        em.get("ano") == ANO and em_dia(em.get("ultimaAtualizacao"), 3))

    ss = carregar("supersalarios.json")
    add("supersalarios", "DadosJusBr / Transparência Brasil (Judiciário) e Portal da Transparência de MS (folha do Estado)",
        "https://dadosjusbr.org/", ss.get("ultimaAtualizacao"),
        "contracheques de " + ", ".join(sorted({o["mes"] for o in ss.get("orgaos", [])})) if ss.get("orgaos") else None,
        ss.get("ano") == ANO and em_dia(ss.get("ultimaAtualizacao"), 3) and not ss.get("falhas"),
        "; ".join(ss.get("falhas") or []) or None)

    au = carregar("auditoria.json")
    add("auditoria", "Cruzamento das bases do site com a Receita Federal (BrasilAPI / Minha Receita), o TSE e a folha do Estado",
        "https://brasilapi.com.br/docs#tag/CNPJ", au.get("ultimaAtualizacao"),
        f"{au.get('empresasConsultadas', 0)} empresas checadas na Receita" if au else None,
        au.get("ano") == ANO and em_dia(au.get("ultimaAtualizacao"), 3))

    pr = carregar("presidencia.json")
    ult_cartao = ((pr.get("cartao") or {}).get("serie") or [{}])[-1].get("mes")
    add("presidencia", "Portal da Transparência do Governo Federal (CGU) — cartão de pagamento, viagens, orçamento, servidores e transferências",
        "https://portaldatransparencia.gov.br/download-de-dados", pr.get("ultimaAtualizacao"),
        f"cartão até {ult_cartao[5:]}/{ult_cartao[:4]}" if ult_cartao else None, bool(pr) and em_dia(pr.get("ultimaAtualizacao"), 8))

    cidades, paradas = 0, []
    for f in sorted((DADOS / "camaras").glob("*.json")):
        j = carregar(f"camaras/{f.name}")
        cidades += 1
        if not em_dia(j.get("ultimaAtualizacao"), 7):
            paradas.append(f"{j.get('cidade')} ({data_br(j.get('ultimaAtualizacao'))})")
    add("camaras-ms", "Portais de transparência das câmaras (Fiorilli SCPI / SAPL)", None,
        carregar("status.json").get("ultimaAtualizacao"), f"{cidades - len(paradas)} de {cidades} câmaras atualizadas",
        not paradas, ("sem resposta do portal: " + ", ".join(paradas)) if paradas else None)

    refs, msgs = [], []
    for arq, nome in (("trt24_magistrados.json", "TRT24"), ("tre_ms_magistrados.json", "TRE-MS"), ("tjms_magistrados.json", "TJMS")):
        j = carregar(arq)
        refs.append(f"{nome} {j.get('mesReferencia')}")
        try:
            m, a = j["mesReferencia"].split("/")
            if (HOJE.year * 12 + HOJE.month) - (int(a) * 12 + int(m)) > 3:
                msgs.append(f"{nome} parado em {j['mesReferencia']}")
        except Exception:
            msgs.append(f"{nome} sem mês de referência")
    add("judiciario", "Anexo VIII (Res. CNJ 102/2009) — portais do TRT24 e TRE-MS; TJMS via DadosJusBr", "https://dadosjusbr.org/",
        carregar("tjms_magistrados.json").get("ultimaAtualizacao"), "folha de " + ", ".join(refs), not msgs, "; ".join(msgs) or None)

    br = carregar("deputados_federais_brasil.json")
    sem = sum(1 for x in br.get("deputados", []) if x.get("cotaGastaAno") is None)
    add("deputados-brasil", "Câmara dos Deputados — arquivo completo da CEAP", "https://www.camara.leg.br/cotas/",
        br.get("ultimaAtualizacao"), f"{len(br.get('deputados', [])) - sem} de {len(br.get('deputados', []))} com CEAP", sem <= 25)
    sbr = carregar("senadores_brasil.json")
    add("senado-brasil", "Senado Federal — dados abertos", "https://adm.senado.gov.br/adm-dadosabertos/swagger-ui/index.html",
        sbr.get("ultimaAtualizacao"), f"{len(sbr.get('senadores', []))} senadores", em_dia(sbr.get("ultimaAtualizacao"), 3))

    for aba, arq, fonte in (("conexoes", "conexoes_fornecedores.json", "Cruzamento das notas fiscais de todas as fontes acima"),
                            ("evolucao", "evolucao_mensal.json", "Notas fiscais das fontes acima + histórico do ano anterior")):
        j = carregar(arq)
        add(aba, fonte, None, j.get("ultimaAtualizacao"), "gerado a cada coleta", em_dia(j.get("ultimaAtualizacao"), 3))

    for v in st.values():
        dd = dias(v["coleta"])
        if dd is not None and dd > 3 and v["nivel"] == "ok":
            v["nivel"] = "atencao"
            v["mensagem"] = v["mensagem"] or "a coleta automática não atualizou esta fonte nos últimos dias"
    saida = {"geradoEm": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"), "fontes": st}
    (DADOS / "status_fontes.json").write_text(json.dumps(saida, ensure_ascii=False, indent=1), encoding="utf-8")
    return st


if __name__ == "__main__":
    c = gerar_csvs()
    print(f"✅ {len(c)} planilhas CSV em dados/csv/ ({sum(c.values()):,} linhas)".replace(",", "."))
    s = status_fontes()
    print("✅ status_fontes.json — " + ", ".join(f"{k}: {v['nivel']}" for k, v in s.items()))
