#!/usr/bin/env python3
"""
Cofre Aberto MS — Script de coleta automática de dados
Roda via GitHub Actions todo dia às 6h BRT

Fontes:
- Câmara Federal: dadosabertos.camara.leg.br (API REST, CORS livre)
- Senado Federal: adm.senado.gov.br/ergon-ng-reports (API REST)
- ALEMS: consulta.transparencia.al.ms.gov.br/ceap (grid ScriptCase, sessão por deputado)
"""

import json, requests, csv, io, os, sys, time
from datetime import datetime, date
from pathlib import Path

ROOT = Path(__file__).parent.parent
DADOS = ROOT / "dados"
ANO = date.today().year
hoje = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

# Headers padrão para evitar bloqueios
HEADERS = {
    "User-Agent": "CoffreAbertoMS/1.0 (github.com/cofre-aberto-ms; transparencia publica)",
    "Accept": "application/json",
}

def get_com_retry(url, tentativas=3, **kwargs):
    headers = {**HEADERS, **kwargs.pop("headers", {})}
    for i in range(tentativas):
        try:
            r = requests.get(url, headers=headers, timeout=60, **kwargs)
            r.raise_for_status()
            return r
        except Exception as e:
            if i == tentativas - 1:
                raise
            log(f"  Tentativa {i+1} falhou, tentando novamente...")
            time.sleep(5)


def log(msg): print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")
def salvar(nome, data):
    path = DADOS / nome
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    log(f"✅ {nome} salvo ({path.stat().st_size//1024}KB)")

# ============================================================
# 1. DEPUTADOS FEDERAIS DE MS — API da Câmara
# ============================================================
def coletar_dep_federais_ms():
    log("Coletando deputados federais de MS...")

    # Lista deputados em exercício por UF
    url = f"https://dadosabertos.camara.leg.br/api/v2/deputados?siglaUf=MS&ordem=ASC&ordenarPor=nome"
    r = get_com_retry(url)
    r.raise_for_status()
    deputados = r.json().get("dados", [])
    log(f"  {len(deputados)} deputados federais de MS encontrados")

    resultado = []
    for d in deputados:
        dep_id = d["id"]
        time.sleep(0.3)  # respeitar rate limit

        # Buscar detalhes completos
        try:
            det = requests.get(
                f"https://dadosabertos.camara.leg.br/api/v2/deputados/{dep_id}",
                headers=HEADERS, timeout=20
            ).json().get("dados", {})
        except:
            det = {}

        # Buscar CEAP do ano atual (paginado — um deputado pode ter mais de 100 notas/ano)
        ceap = {"cotaGastaAno": None, "ceapCategorias": [], "totalNotasFiscais": 0}
        try:
            ceap = buscar_ceap_deputado_agregado(dep_id, ANO)
        except Exception as e:
            log(f"    CEAP erro para {d.get('nome')}: {e}")

        resultado.append({
            "id": dep_id,
            "nome": d.get("nome"),
            "nomeCompleto": det.get("nomeCivil", d.get("nome")),
            "partido": d.get("siglaPartido"),
            "uf": "MS",
            "cargo": "Deputado(a) Federal",
            "foto": d.get("urlFoto"),
            "email": det.get("ultimoStatus", {}).get("email"),
            "gabinete": det.get("ultimoStatus", {}).get("gabinete", {}),
            "urlPerfil": f"https://www.camara.leg.br/deputados/{dep_id}",
            "urlCeap": f"https://dadosabertos.camara.leg.br/api/v2/deputados/{dep_id}/despesas?ano={ANO}",
            "salarioBase": 41650.92,
            **ceap,
        })
        log(f"  ✓ {d.get('nome')} — CEAP: R$ {ceap['cotaGastaAno']:,.2f}" if ceap["cotaGastaAno"] else f"  ✓ {d.get('nome')}")

    data = {
        "ultimaAtualizacao": hoje,
        "ano": ANO,
        "fonte": f"API da Câmara dos Deputados (dadosabertos.camara.leg.br) — {hoje}",
        "total": len(resultado),
        "deputados": resultado,
    }
    salvar("deputados_federais_ms.json", data)
    return resultado

# ============================================================
# 2. SENADORES DE MS — API do Senado
# ============================================================
def buscar_recursos_senador(sen_id, ano):
    """Busca CEAPS, gastos extras, benefícios e pessoal de um senador na API oficial.
    A API redireciona (302) de ergon-ng-reports para adm-dadosabertos e agrupa tudo
    dentro de data[0] — não usar o formato plano (ceaps/gastosNaoCeaps) do endpoint antigo.
    """
    r = requests.get(
        f"https://adm.senado.gov.br/ergon-ng-reports/api/v1/senadores/{sen_id}/recursos-utilizados"
        f"?ano={ano}&formato=json",
        headers=HEADERS, timeout=20
    )
    r.raise_for_status()
    registros = r.json().get("data") or []
    if not registros:
        return None
    reg = registros[0]

    ceaps = {item["recurso"]: float(item.get("valor") or 0) for item in reg.get("cotas", {}).get("despesas", [])}
    extras = {item["recurso"]: float(item.get("valor") or 0) for item in reg.get("gastosNaoInclusos", {}).get("despesas", [])}

    pessoal = {}
    for grupo in reg.get("pessoal", []):
        comissionados = sum(v["quantidade"] for v in grupo.get("vinculos", []) if v.get("vinculo") == "Comissionado")
        if grupo.get("local") == "Gabinete":
            pessoal["gabinete"] = grupo.get("quantidadeTotalEscritorio")
            pessoal["gabineteComissionados"] = comissionados
        elif "Apoio" in (grupo.get("local") or ""):
            pessoal["escritorio"] = grupo.get("quantidadeTotalEscritorio")
            pessoal["escritorioComissionados"] = comissionados

    beneficios = {}
    for b in reg.get("beneficios", []):
        if b.get("beneficio") == "Auxílio-Moradia":
            beneficios["auxilioMoradia"] = b.get("utilizacao")
        elif b.get("beneficio") == "Imóvel Funcional":
            beneficios["imovelFuncional"] = b.get("utilizacao")

    return {
        "ceaps": ceaps,
        "gastosExtras": extras,
        "pessoal": pessoal,
        "beneficios": beneficios,
        "totalCeaps": reg.get("cotas", {}).get("totalValor"),
        "totalExtras": reg.get("gastosNaoInclusos", {}).get("totalValor"),
        "ano": reg.get("ano", ano),
    }


def coletar_senadores_ms():
    log("Coletando senadores de MS...")

    # Lista senadores em exercício
    r = requests.get(
        "https://legis.senado.leg.br/dadosabertos/senador/lista/atual",
        headers={**HEADERS, "Accept": "application/json"},
        timeout=60
    )
    r.raise_for_status()
    parlamentares = r.json().get("ListaParlamentarEmExercicio", {}).get("Parlamentares", {}).get("Parlamentar", [])

    senadores_ms = [p for p in parlamentares
                   if p.get("IdentificacaoParlamentar", {}).get("UfParlamentar") == "MS"]
    log(f"  {len(senadores_ms)} senadores de MS encontrados")

    # Carregar dados anteriores para manter fotos embutidas e dados históricos
    dados_ant = {}
    try:
        ant = json.load(open(DADOS / "senadores_brasil.json"))
        for s in ant.get("senadores", []):
            dados_ant[s["id"]] = s
    except: pass

    resultado = []
    for p in senadores_ms:
        ident = p["IdentificacaoParlamentar"]
        sen_id = int(ident["CodigoParlamentar"])
        time.sleep(0.5)

        # Buscar recursos utilizados via API JSON — tenta o ano corrente, cai para o anterior
        recursos = None
        ano_dados = ANO
        for tentativa_ano in (ANO, ANO - 1):
            try:
                recursos = buscar_recursos_senador(sen_id, tentativa_ano)
                if recursos and (recursos["totalCeaps"] or recursos["totalExtras"]):
                    ano_dados = tentativa_ano
                    break
            except Exception as e:
                log(f"    API Senado erro para {ident.get('NomeParlamentar')} ({tentativa_ano}): {e}")
        recursos = recursos or {"ceaps": {}, "gastosExtras": {}, "pessoal": {}, "beneficios": {}, "totalCeaps": None, "totalExtras": None}

        ant_s = dados_ant.get(sen_id, {})
        total_ceaps = recursos["totalCeaps"] or 0
        total_extras = recursos["totalExtras"] or 0

        resultado.append({
            "id": sen_id,
            "nome": ident.get("NomeParlamentarFormatado") or ident.get("NomeParlamentar"),
            "partido": ident.get("SiglaPartidoParlamentar"),
            "uf": "MS",
            "cargo": "Senador(a)",
            "foto": ant_s.get("fotoBase64") or ident.get("UrlFotoParlamentar") or
                    f"https://legis.senado.leg.br/senadores/fotos-oficiais/{sen_id}",
            "urlTransparencia": f"https://www6g.senado.leg.br/transparencia/sen/{sen_id}/?ano={ANO}",
            "anoReferencia": ano_dados,
            "ceaps": recursos["ceaps"],
            "gastosExtras": recursos["gastosExtras"],
            "pessoal": recursos["pessoal"],
            "beneficios": recursos["beneficios"],
            "cotaGastaAno": round(total_ceaps, 2) if total_ceaps else ant_s.get("cotaGastaAno"),
            "totalGasto": round(total_ceaps + total_extras, 2) if total_ceaps else None,
            "ceapsCategorias": [{"categoria": k, "valor": round(v, 2)}
                                for k, v in sorted(recursos["ceaps"].items(), key=lambda x: -x[1]) if v > 0],
            "despesas": ant_s.get("despesas", []),
            "escritorioApoio": ant_s.get("escritorioApoio", ""),
            "fonteCeaps": f"adm.senado.gov.br — dados de {hoje}",
            "nota": "" if total_ceaps else f"Dados de {ANO} ainda não publicados. Exibindo {ano_dados}.",
        })
        log(f"  ✓ {ident.get('NomeParlamentar')} — CEAPS {ano_dados}: R$ {total_ceaps:,.2f}")

    data = {
        "ultimaAtualizacao": hoje,
        "ano": ANO,
        "fonte": f"API do Senado Federal (adm.senado.gov.br) — {hoje}",
        "total": len(resultado),
        "senadores": resultado,
    }
    salvar("senadores_ms.json", data)
    return resultado

# ============================================================
# 3. DEPUTADOS ESTADUAIS ALEMS — CSV público
# ============================================================
def _alems_post_latin1(session, url, data, **kwargs):
    # O portal da ALEMS (ScriptCase/ISO-8859-1) só casa o filtro exato de
    # deputado se os campos acentuados forem enviados em latin-1 — em UTF-8
    # o "busca" falha silenciosamente e devolve a grade da consulta anterior.
    import urllib.parse
    body = "&".join(
        urllib.parse.quote(str(k)) + "=" + urllib.parse.quote(str(v).encode("iso-8859-1"))
        for k, v in data.items()
    )
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    return session.post(url, data=body.encode("ascii"), headers=headers, **kwargs)


def _alems_parse_valor(txt):
    txt = (txt or "").replace("R$", "").strip().replace(".", "").replace(",", ".")
    try:
        return float(txt)
    except:
        return 0.0


def _alems_parse_data(txt):
    # vem como DD/MM/YYYY; formatDate() do front-end espera ISO (new Date(iso))
    try:
        d, m, a = txt.strip().split("/")
        return f"{a}-{m}-{d}"
    except:
        return txt


def coletar_dep_estaduais():
    log("Coletando deputados estaduais ALEMS (CEAP)...")
    import re

    BASE = "https://consulta.transparencia.al.ms.gov.br/ceap/"
    session = requests.Session()

    try:
        r = session.get(BASE, headers=HEADERS, timeout=30)
        html = r.text
        script_case_init = re.search(r'name="script_case_init" value="(\d+)"', html).group(1)
        tab_label = re.search(r'name="nmgp_tab_label" value="([^"]*)"', html).group(1)
        select_html = re.search(
            r'<SELECT[^>]*id="SC_deputados_nome".*?</SELECT>', html, re.S | re.I
        ).group(0)
        deputados = re.findall(r'<OPTION value="([^"]+)##@@', select_html, re.I)
        deputados = [d for d in deputados if d.strip()]
        log(f"  {len(deputados)} deputados no filtro da ALEMS")
    except Exception as e:
        log(f"  ⚠️ ALEMS indisponível ao abrir o filtro: {e} — mantendo dados anteriores")
        return None

    try:
        dados_ant = json.load(open(DADOS / "deputados_estaduais_ms.json", encoding="utf-8"))
        deps_ant = {d["nome"]: d for d in dados_ant.get("vereadores", [])}
    except:
        dados_ant = {}
        deps_ant = {}

    resultados = {}
    total_geral = 0.0
    for i, nome_dep in enumerate(deputados):
        try:
            busca = {
                'script_case_init': script_case_init,
                'nmgp_opcao': 'busca',
                'deputados_nome': f"{nome_dep}##@@{nome_dep}",
                'deputados_nome_cond': 'qp',
                'categoriadespesas_descricao': '',
                'categoriadespesas_descricao_cond': 'qp',
                'verbaindenizatoria_mes_referencia': '',
                'verbaindenizatoria_mes_referencia_cond': 'qp',
                'verbaindenizatoria_ano_referencia': str(ANO),
                'verbaindenizatoria_ano_referencia_cond': 'bw',
                'verbaindenizatoria_ano_referencia_autocomp': str(ANO),
                'verbaindenizatoria_ano_referencia_input_2': '',
                'NM_operador': 'and',
                'nmgp_tab_label': tab_label,
                'bprocessa': 'pesq',
                'nmgp_save_name_bot': '',
                'form_condicao': '3',
            }
            _alems_post_latin1(session, BASE, busca, timeout=30)
            r2 = session.post(BASE, data={'script_case_init': script_case_init, 'nmgp_opcao': 'pesq'}, timeout=30)
            grid = r2.text

            grupo = re.findall(r'Nome</td><td> => </td><td>([^<]*)</td>', grid)
            if grupo != [nome_dep]:
                continue  # sem gastos no período ou filtro não pegou — pula

            categorias_ctx = {
                m.group(1): (m.group(2), m.group(3))
                for m in re.finditer(
                    r'id="id_sc_field_categoriadespesas_descricao_(\d+)">([^<]*)</span>.*?'
                    r'id="id_sc_field_verbaindenizatoria_mes_referencia_\1">([^<]*)</span>',
                    grid, re.S
                )
            }

            # Cada bloco de fornecedores vai do seu marcador até o próximo
            # (o fechamento de tabelas aninhadas é irregular demais para casar por regex)
            marcadores = [(m.group(1), m.start()) for m in re.finditer(r'id="emb_search_ceap_linha_(\d+)"', grid)]

            notas = []
            for j, (idx, pos) in enumerate(marcadores):
                fim = marcadores[j + 1][1] if j + 1 < len(marcadores) else len(grid)
                corpo = grid[pos:fim]
                categoria, mes = categorias_ctx.get(idx, ("", ""))
                for linha in re.finditer(
                    r'fornecedorverbaidenizatoria_cpf_cnpj_\d+">([^<]*)</span>.*?'
                    r'fornecedorverbaidenizatoria_razao_social_\d+">([^<]*)</span>.*?'
                    r'fornecedorverbaidenizatoria_documento_\d+">([^<]*)</span>.*?'
                    r'fornecedorverbaidenizatoria_documento_data_\d+">([^<]*)</span>.*?'
                    r'fornecedorverbaidenizatoria_valor_reembolsado_\d+">([^<]*)</span>.*?'
                    r'href="([^"]+)"', corpo, re.S
                ):
                    cpf, fornecedor, doc, data_doc, valor, url_pdf = linha.groups()
                    notas.append({
                        "categoria": categoria,
                        "mes": mes,
                        "fornecedor": fornecedor.strip(),
                        "cnpj": cpf.strip(),
                        "nf": doc.strip(),
                        "data": _alems_parse_data(data_doc),
                        "valor": round(_alems_parse_valor(valor), 2),
                        "urlPdf": url_pdf,
                    })

            if not notas:
                continue

            por_categoria = {}
            for n in notas:
                por_categoria[n["categoria"]] = round(por_categoria.get(n["categoria"], 0) + n["valor"], 2)
            total_dep = round(sum(n["valor"] for n in notas), 2)
            resultados[nome_dep] = {"notas": notas, "categorias": por_categoria, "total": total_dep}
            total_geral += total_dep
            log(f"  [{i+1}/{len(deputados)}] {nome_dep}: {len(notas)} notas, R$ {total_dep:,.2f}")
        except Exception as e:
            log(f"  ⚠️ {nome_dep}: {e} — pulando")
            continue

    if not resultados:
        log("  ⚠️ Nenhum resultado da ALEMS — mantendo dados anteriores")
        return None

    log(f"  Total ALEMS {ANO}: R$ {total_geral:,.2f} — {len(resultados)} deputados com gastos")

    deps = []
    for nome_dep, gastos in resultados.items():
        nome_norm = re.sub(r'^Dep\.?\s*', '', nome_dep, flags=re.I).strip()
        ant = deps_ant.get(nome_norm, {})
        cota_anual = (ant.get("verbaIndenizatoria") or {}).get(f"cotaAnual{ANO}")
        deps.append({
            **ant,
            "nome": ant.get("nome", nome_norm),
            "ultimaAtualizacao": hoje,
            "verbaIndenizatoria": {
                **ant.get("verbaIndenizatoria", {}),
                f"gastoPago{ANO}": gastos["total"],
                "categorias": gastos["categorias"],
                "periodoColetado": f"Jan–{datetime.now().strftime('%b')}/{ANO}",
                "percentualUsado": round(gastos["total"] / cota_anual * 100, 1) if cota_anual else None,
                "descricaoGeral": "CEAP — Cota do Exercício da Atividade Parlamentar (ALEMS).",
                "fonte": f"Portal da Transparência ALEMS — consulta.transparencia.al.ms.gov.br/ceap/ — {hoje}",
            },
            "despesas": gastos["notas"],
            "totalNotasFiscais": len(gastos["notas"]),
        })

    data = {
        **dados_ant,
        "ultimaAtualizacao": hoje,
        "fonte": f"Despesas CEAP: Portal da Transparência ALEMS (consulta.transparencia.al.ms.gov.br/ceap/) — coleta automática {hoje}. Total geral {ANO}: R$ {total_geral:,.2f}.",
        "resumo": {
            **(dados_ant.get("resumo") or {}),
            "totalDeputados": len(deps),
            f"totalVerbaIndenizatoriaPaga{ANO}": round(total_geral, 2),
            "periodoColetado": f"Jan–{datetime.now().strftime('%b')}/{ANO}",
        },
        "vereadores": deps,
    }
    salvar("deputados_estaduais_ms.json", data)
    return deps

# ============================================================
# 4. SENADO BRASIL — lista completa 81 senadores
# ============================================================
def coletar_senado_brasil():
    log("Coletando lista completa do Senado...")

    # Carregar dados anteriores
    try:
        dados_ant = json.load(open(DADOS / "senadores_brasil.json"))
        sens_ant = {s["id"]: s for s in dados_ant.get("senadores", [])}
    except:
        sens_ant = {}

    try:
        r = requests.get(
            "https://legis.senado.leg.br/dadosabertos/senador/lista/atual",
            headers={**HEADERS, "Accept": "application/json"},
            timeout=60
        )
        r.raise_for_status()
        parlamentares = r.json().get("ListaParlamentarEmExercicio", {}).get("Parlamentares", {}).get("Parlamentar", [])
    except Exception as e:
        log(f"  ⚠️ API Senado indisponível: {e} — mantendo dados anteriores")
        return None

    senadores = []
    for p in parlamentares:
        ident = p.get("IdentificacaoParlamentar", {})
        sid = int(ident.get("CodigoParlamentar", 0))
        uf = ident.get("UfParlamentar")
        ant = sens_ant.get(sid, {})

        registro = {
            **ant,
            "id": sid,
            "nome": ident.get("NomeParlamentarFormatado") or ident.get("NomeParlamentar"),
            "partido": ident.get("SiglaPartidoParlamentar"),
            "uf": uf,
            "foto": ant.get("fotoBase64") or ident.get("UrlFotoParlamentar") or
                    f"https://legis.senado.leg.br/senadores/fotos-oficiais/{sid}",
            "urlTransparencia": f"https://www6g.senado.leg.br/transparencia/sen/{sid}/?ano={ANO}",
        }

        # Enriquecer todos os senadores com CEAPS/gastos extras/pessoal/benefícios reais
        time.sleep(0.5)
        recursos = None
        for tentativa_ano in (ANO, ANO - 1):
            try:
                recursos = buscar_recursos_senador(sid, tentativa_ano)
                if recursos and (recursos["totalCeaps"] or recursos["totalExtras"]):
                    break
            except Exception as e:
                log(f"    API Senado erro para {registro['nome']} ({tentativa_ano}): {e}")
        if recursos:
            registro.update({
                "ceaps": recursos["ceaps"],
                "gastosExtras": recursos["gastosExtras"],
                "pessoal": recursos["pessoal"],
                "beneficios": recursos["beneficios"],
                "cotaGastaAno": round(recursos["totalCeaps"], 2) if recursos["totalCeaps"] else ant.get("cotaGastaAno"),
                "anoReferencia": recursos["ano"],
                "fonteCeaps": f"adm.senado.gov.br — dados de {hoje}",
            })

        senadores.append(registro)

    log(f"  {len(senadores)} senadores em exercício")

    data = {
        **(dados_ant if sens_ant else {}),
        "ultimaAtualizacao": hoje,
        "fonte": f"API do Senado Federal — {hoje}",
        "totalSenadores": len(senadores),
        "senadores": senadores,
    }
    salvar("senadores_brasil.json", data)
    return senadores

# ============================================================
# 5. DEPUTADOS FEDERAIS BRASIL — lista completa 513
# ============================================================
def buscar_ceap_deputado_agregado(dep_id, ano):
    """Soma a CEAP de um deputado no ano, paginando (um deputado pode ter 100+ notas/ano)."""
    total = 0.0
    categorias = {}
    notas = 0
    pagina = 1
    while True:
        r = requests.get(
            f"https://dadosabertos.camara.leg.br/api/v2/deputados/{dep_id}/despesas"
            f"?ano={ano}&itens=100&pagina={pagina}",
            headers=HEADERS, timeout=20
        )
        r.raise_for_status()
        itens = r.json().get("dados", [])
        if not itens:
            break
        for item in itens:
            tipo = item.get("tipoDespesa", "Outros")
            valor = float(item.get("valorLiquido") or 0)
            categorias[tipo] = categorias.get(tipo, 0) + valor
            total += valor
        notas += len(itens)
        if len(itens) < 100:
            break
        pagina += 1
        time.sleep(0.2)

    cats = [{"categoria": k, "valor": round(v, 2)} for k, v in sorted(categorias.items(), key=lambda x: -x[1])]
    return {"cotaGastaAno": round(total, 2) if notas else None, "ceapCategorias": cats, "totalNotasFiscais": notas}


def coletar_dep_federais_brasil():
    log("Coletando lista completa de deputados federais...")

    try:
        r = requests.get(
            "https://dadosabertos.camara.leg.br/api/v2/deputados?itens=513",
            headers=HEADERS, timeout=60
        )
        r.raise_for_status()
        deputados = r.json().get("dados", [])
    except Exception as e:
        log(f"  ⚠️ API Câmara indisponível: {e}")
        return None

    log(f"  {len(deputados)} deputados federais em exercício")

    resultado = []
    for i, d in enumerate(deputados):
        time.sleep(0.3)
        ceap = {"cotaGastaAno": None, "ceapCategorias": [], "totalNotasFiscais": 0}
        try:
            ceap = buscar_ceap_deputado_agregado(d["id"], ANO)
        except Exception as e:
            log(f"    CEAP erro para {d.get('nome')}: {e}")

        resultado.append({
            "id": d["id"],
            "nome": d["nome"],
            "partido": d["siglaPartido"],
            "uf": d["siglaUf"],
            "foto": d["urlFoto"],
            "urlPerfil": f"https://www.camara.leg.br/deputados/{d['id']}",
            **ceap,
        })
        if (i + 1) % 50 == 0:
            log(f"  ... {i + 1}/{len(deputados)} deputados processados")

    data = {
        "ultimaAtualizacao": hoje,
        "ano": ANO,
        "fonte": f"API da Câmara dos Deputados — {hoje}",
        "total": len(resultado),
        "deputados": resultado,
    }
    salvar("deputados_federais_brasil.json", data)
    return resultado

# ============================================================
# 6. GERAR TIMESTAMP de última atualização
# ============================================================
def gerar_status():
    status = {
        "ultimaAtualizacao": hoje,
        "ano": ANO,
        "fontes": {
            "camaraFederal": "dadosabertos.camara.leg.br",
            "senadoFederal": "adm.senado.gov.br/ergon-ng-reports",
            "alems": "consulta.transparencia.al.ms.gov.br/ceap",
            "camaraCG": "dados manuais (portal sem API)",
        }
    }
    salvar("status.json", status)

# ============================================================
# 6. PREFEITURA DE CAMPO GRANDE — CSV de Despesas
# ============================================================
def coletar_prefeitura():
    log("Coletando despesas da Prefeitura de CG...")

    import csv, io
    from datetime import date

    ano = date.today().year
    url = f"https://cdn.campogrande.ms.gov.br/portal/prod/uploads/{ano}/05/Consulta_de_Despesas__{ano}.csv"

    try:
        r = get_com_retry(url)
        texto = r.content.decode("utf-8-sig", errors="replace")
        reader = csv.DictReader(io.StringIO(texto), delimiter=";")
        linhas = list(reader)
        log(f"  {len(linhas)} linhas no CSV da Prefeitura")
    except Exception as e:
        log(f"  \u26a0\ufe0f CSV Prefeitura indispon\u00edvel: {e} \u2014 tentando m\u00eas anterior...")
        try:
            url2 = f"https://cdn.campogrande.ms.gov.br/portal/prod/uploads/{ano}/04/Consulta_de_Despesas__{ano}.csv"
            r = get_com_retry(url2)
            texto = r.content.decode("utf-8-sig", errors="replace")
            reader = csv.DictReader(io.StringIO(texto), delimiter=";")
            linhas = list(reader)
            log(f"  {len(linhas)} linhas (m\u00eas anterior)")
        except Exception as e2:
            log(f"  \u26a0\ufe0f Prefeitura indispon\u00edvel: {e2} \u2014 mantendo dados anteriores")
            return None

    def parse_valor(valor_str):
        v = (valor_str or "0").strip().replace("R$", "").strip()
        if "," in v:
            v = v.replace(".", "").replace(",", ".")
        valor = float(v or 0)
        if valor > 1_000_000_000:
            valor = valor / 100
        return valor

    # Agrupar por secretaria e extrair cada despesa individual (nota/empenho)
    por_secretaria = {}
    total_geral = 0
    despesas = []
    for row in linhas:
        try:
            secretaria = (row.get("orgao") or "Outros").strip()
            valor = parse_valor(row.get("total_pago"))
            por_secretaria[secretaria] = por_secretaria.get(secretaria, 0) + valor
            total_geral += valor
            if valor > 0:
                ano_row = (row.get("ano") or "").strip()
                uge = (row.get("uge") or "").strip()
                num = (row.get("num") or "").strip()
                despesas.append({
                    "data": row.get("dataempenho"),
                    "orgao": secretaria,
                    "categoria": (row.get("itemclassificacaodespesaitemclassificacaodespesa") or "").strip(),
                    "fornecedor": (row.get("nomefornecedor") or "").strip(),
                    "cnpj": (row.get("cnpjfornecedor") or "").strip(),
                    "valor": round(valor, 2),
                    "urlDetalhe": f"https://sig-transparencia.campogrande.ms.gov.br/despesas/detalhe/{ano_row}/{uge}/{num}"
                        if ano_row and uge and num else None,
                })
        except:
            continue

    despesas.sort(key=lambda x: x["data"] or "", reverse=True)

    # Carregar dados anteriores para manter estrutura
    try:
        dados_ant = json.load(open(DADOS / "prefeitura.json", encoding="utf-8"))
    except:
        dados_ant = {}

    data = {
        **dados_ant,
        "ultimaAtualizacao": hoje,
        "ano": ano,
        "totalDespesas": round(total_geral, 2),
        "fonte": f"cdn.campogrande.ms.gov.br \u2014 {hoje}",
        "porSecretaria": {k: round(v, 2) for k, v in sorted(por_secretaria.items(), key=lambda x: -x[1])[:20]},
        "totalLinhas": len(linhas),
        "totalNotasFiscais": len(despesas),
        "despesas": despesas,
    }
    salvar("prefeitura.json", data)
    log(f"  Total despesas {ano}: R$ {total_geral:,.2f} \u2014 {len(despesas)} notas com valor pago")
    return data

# ============================================================
# EMENDAS PARLAMENTARES \u2014 deputados federais e senadores de MS
# Fonte: Portal da Transpar\u00eancia (api.portaldatransparencia.gov.br)
# Requer chave pessoal em PORTAL_TRANSPARENCIA_API_KEY (vari\u00e1vel de
# ambiente / secret do GitHub Actions) \u2014 n\u00e3o \u00e9 embutida no c\u00f3digo.
# ============================================================
def _emendas_parse_valor(txt):
    txt = (txt or "0").strip().replace(".", "").replace(",", ".")
    try:
        return float(txt)
    except:
        return 0.0


def _emendas_buscar_autor(nome_autor, api_key):
    emendas = []
    pagina = 1
    while True:
        r = get_com_retry(
            "https://api.portaldatransparencia.gov.br/api-de-dados/emendas",
            headers={**HEADERS, "chave-api-dados": api_key},
            params={"ano": ANO, "nomeAutor": nome_autor, "pagina": pagina},
        )
        lote = r.json()
        if not lote:
            break
        emendas.extend(lote)
        pagina += 1
    return emendas


def coletar_emendas_ms():
    log("Coletando emendas parlamentares de MS...")

    api_key = os.environ.get("PORTAL_TRANSPARENCIA_API_KEY")
    if not api_key:
        log("  \u26a0\ufe0f PORTAL_TRANSPARENCIA_API_KEY n\u00e3o configurada \u2014 pulando emendas")
        return None

    try:
        deps = json.load(open(DADOS / "deputados_federais_ms.json", encoding="utf-8")).get("deputados", [])
    except:
        deps = []
    try:
        sens = json.load(open(DADOS / "senadores_ms.json", encoding="utf-8")).get("senadores", [])
    except:
        sens = []

    parlamentares = [{"nome": d["nome"], "cargo": "Deputado(a) Federal", "partido": d.get("partido")} for d in deps] \
        + [{"nome": s["nome"], "cargo": "Senador(a)", "partido": s.get("partido")} for s in sens]

    resultados = []
    total_geral_pago = 0.0
    for p in parlamentares:
        try:
            brutas = _emendas_buscar_autor(p["nome"].upper(), api_key)
        except Exception as e:
            log(f"  \u26a0\ufe0f {p['nome']}: {e} \u2014 pulando")
            continue

        if not brutas:
            continue

        itens = []
        por_tipo = {}
        total_empenhado = total_pago = 0.0
        for e in brutas:
            empenhado = _emendas_parse_valor(e.get("valorEmpenhado"))
            pago = _emendas_parse_valor(e.get("valorPago"))
            tipo = "Emenda Pix" if "Especiais" in (e.get("tipoEmenda") or "") else "Projeto Definido"
            itens.append({
                "numero": e.get("numeroEmenda"),
                "tipo": tipo,
                "municipio": e.get("localidadeDoGasto"),
                "funcao": e.get("funcao"),
                "subfuncao": e.get("subfuncao"),
                "valorEmpenhado": round(empenhado, 2),
                "valorPago": round(pago, 2),
            })
            por_tipo[tipo] = round(por_tipo.get(tipo, 0) + pago, 2)
            total_empenhado += empenhado
            total_pago += pago

        itens.sort(key=lambda x: x["valorPago"], reverse=True)
        resultados.append({
            "nome": p["nome"],
            "cargo": p["cargo"],
            "partido": p["partido"],
            "totalEmpenhado": round(total_empenhado, 2),
            "totalPago": round(total_pago, 2),
            "porTipo": por_tipo,
            "totalEmendas": len(itens),
            "emendas": itens,
        })
        total_geral_pago += total_pago
        log(f"  {p['nome']}: {len(itens)} emendas, R$ {total_pago:,.2f} pago")

    if not resultados:
        log("  \u26a0\ufe0f Nenhuma emenda coletada \u2014 mantendo dados anteriores")
        return None

    resultados.sort(key=lambda x: x["totalPago"], reverse=True)
    data = {
        "ultimaAtualizacao": hoje,
        "ano": ANO,
        "fonte": f"Portal da Transpar\u00eancia (api.portaldatransparencia.gov.br/api-de-dados/emendas) \u2014 {hoje}",
        "totalGeralPago": round(total_geral_pago, 2),
        "parlamentares": resultados,
    }
    salvar("emendas_ms.json", data)
    log(f"  Total emendas MS {ANO}: R$ {total_geral_pago:,.2f} \u2014 {len(resultados)} parlamentares")
    return data

# ============================================================
# MAIN
# ============================================================
if __name__ == "__main__":
    log("=" * 50)
    log(f"Cofre Aberto MS — Coleta automática {hoje}")
    log("=" * 50)

    erros = []

    try:
        coletar_dep_federais_ms()
    except Exception as e:
        erros.append(f"Dep. Federais MS: {e}")
        log(f"❌ {e}")

    try:
        coletar_senadores_ms()
    except Exception as e:
        erros.append(f"Senadores MS: {e}")
        log(f"❌ {e}")

    try:
        coletar_dep_estaduais()
    except Exception as e:
        erros.append(f"Dep. Estaduais: {e}")
        log(f"❌ {e}")

    try:
        coletar_senado_brasil()
    except Exception as e:
        erros.append(f"Senado Brasil: {e}")
        log(f"❌ {e}")

    try:
        coletar_dep_federais_brasil()
    except Exception as e:
        erros.append(f"Dep. Federais Brasil: {e}")
        log(f"❌ {e}")

    try:
        coletar_prefeitura()
    except Exception as e:
        erros.append(f"Prefeitura: {e}")
        log(f"\u274c {e}")

    try:
        coletar_emendas_ms()
    except Exception as e:
        erros.append(f"Emendas MS: {e}")
        log(f"\u274c {e}")

    gerar_status()

    log("=" * 50)
    if erros:
        log(f"⚠️ Concluído com {len(erros)} erro(s): {erros}")
        sys.exit(1)
    else:
        log("✅ Todos os dados coletados com sucesso!")
