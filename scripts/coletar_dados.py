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
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    log(f"✅ {nome} salvo ({path.stat().st_size//1024}KB)")

# ============================================================
# 1. DEPUTADOS FEDERAIS DE MS — API da Câmara
# ============================================================
def coletar_dep_federais_ms():
    log("Coletando deputados federais de MS...")

    # Lista deputados em exercício por UF
    try:
        url = f"https://dadosabertos.camara.leg.br/api/v2/deputados?siglaUf=MS&ordem=ASC&ordenarPor=nome"
        r = get_com_retry(url)
        r.raise_for_status()
        deputados = r.json().get("dados", [])
    except Exception as e:
        log(f"  ⚠️ API Câmara indisponível: {e} — mantendo dados anteriores")
        return None
    log(f"  {len(deputados)} deputados federais de MS encontrados")

    try:
        dados_ant = json.load(open(DADOS / "deputados_federais_ms.json", encoding="utf-8"))
        ceap_ant = {d["id"]: d for d in dados_ant.get("deputados", [])}
    except:
        ceap_ant = {}

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

        # Buscar CEAP do ano atual (paginado — um deputado pode ter mais de 100 notas/ano).
        # Se a API falhar, mantém o CEAP anterior em vez de zerar o dado já publicado.
        ant = ceap_ant.get(dep_id, {})
        ceap_anterior = {
            "cotaGastaAno": ant.get("cotaGastaAno"),
            "ceapCategorias": ant.get("ceapCategorias", []),
            "totalNotasFiscais": ant.get("totalNotasFiscais", 0),
        }
        try:
            ceap = buscar_ceap_deputado_agregado(dep_id, ANO)
        except Exception as e:
            log(f"    CEAP erro para {d.get('nome')}: {e} — mantendo dado anterior")
            ceap = ceap_anterior

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

    try:
        dados_ant = json.load(open(DADOS / "deputados_federais_brasil.json", encoding="utf-8"))
        ceap_ant = {d["id"]: d for d in dados_ant.get("deputados", [])}
    except:
        ceap_ant = {}

    resultado = []
    for i, d in enumerate(deputados):
        time.sleep(0.3)
        ant = ceap_ant.get(d["id"], {})
        ceap = {
            "cotaGastaAno": ant.get("cotaGastaAno"),
            "ceapCategorias": ant.get("ceapCategorias", []),
            "totalNotasFiscais": ant.get("totalNotasFiscais", 0),
        }
        try:
            ceap = buscar_ceap_deputado_agregado(d["id"], ANO)
        except Exception as e:
            log(f"    CEAP erro para {d.get('nome')}: {e} — mantendo dado anterior")

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
# C\u00c2MARAS MUNICIPAIS DO INTERIOR DE MS
# Cada c\u00e2mara pode usar um sistema diferente (SAPL, Fiorilli, etc.);
# uma fun\u00e7\u00e3o por c\u00e2mara, salvando em dados/camaras/<cidade>.json.
# ============================================================
def coletar_camara_dourados():
    log("Coletando C\u00e2mara Municipal de Dourados (SAPL)...")
    import re

    BASE = "https://sapl.dourados.ms.leg.br/api"
    try:
        parlamentares = get_com_retry(f"{BASE}/parlamentares/parlamentar/?page_size=50").json()["results"]
        filiacoes = get_com_retry(f"{BASE}/parlamentares/filiacao/?page_size=50").json()["results"]
    except Exception as e:
        log(f"  \u26a0\ufe0f SAPL Dourados indispon\u00edvel: {e} \u2014 mantendo dados anteriores")
        return None

    filiacao_por_parlamentar = {f["parlamentar"]: f for f in filiacoes}

    def limpar_html(txt):
        import html
        txt = re.sub(r"<[^>]+>", " ", txt or "")
        txt = html.unescape(txt)
        txt = re.sub(r"\s+", " ", txt).strip()
        return txt

    vereadores = []
    for p in parlamentares:
        if not p.get("ativo"):
            continue
        fil = filiacao_por_parlamentar.get(p["id"], {})
        partido_str = fil.get("__str__", "")
        partido_sigla = partido_str.split(" - ")[1] if " - " in partido_str else None
        vereadores.append({
            "id": p["id"],
            "nome": p["nome_parlamentar"],
            "nomeCompleto": p["nome_completo"],
            "partido": partido_sigla,
            "email": p.get("email"),
            "telefone": p.get("telefone"),
            "foto": p.get("fotografia"),
            "urlPerfil": p.get("endereco_web"),
            "biografia": limpar_html(p.get("biografia"))[:600] or None,
        })

    vereadores.sort(key=lambda v: v["nome"])
    data = {
        "cidade": "Dourados",
        "ultimaAtualizacao": hoje,
        "fonte": f"SAPL Dourados (sapl.dourados.ms.leg.br/api/) \u2014 {hoje}",
        "sistema": "SAPL/Interlegis",
        "portalOficial": "https://www.camaradourados.ms.gov.br/",
        "temDadosFinanceiros": False,
        "notaFinanceiro": "O SAPL cobre dados legislativos (vereadores, mandatos, mat\u00e9rias). Dados financeiros (subs\u00eddio, verba indenizat\u00f3ria) n\u00e3o s\u00e3o expostos por essa API \u2014 precisam ser buscados em outro sistema da pr\u00f3pria C\u00e2mara.",
        "totalVereadores": len(vereadores),
        "vereadores": vereadores,
    }
    salvar("camaras/dourados.json", data)
    log(f"  {len(vereadores)} vereadores de Dourados salvos")
    return data


def _fiorilli_parse_valor(txt):
    txt = (txt or "0").strip().replace(".", "").replace(",", ".")
    try:
        return float(txt)
    except:
        return 0.0


def _fiorilli_data_iso(txt):
    # vem como "23/04/2026 00:00:00" — formatDate() do front-end espera ISO
    try:
        data_parte = (txt or "").split(" ")[0]
        d, m, a = data_parte.split("/")
        return f"{a}-{m}-{d}"
    except:
        return None


# Elemento de despesa — classificação orçamentária padrão nacional (STN),
# usada por todos os municípios brasileiros. O Fiorilli devolve só o
# código numérico (ex.: "11"), não o nome — mapeamos os mais comuns.
_ELEMENTO_DESPESA_NOME = {
    "07": "Contribuição a Entidades Fechadas de Previdência",
    "08": "Outros Benefícios Assistenciais do Servidor",
    "11": "Vencimentos e Vantagens Fixas — Pessoal Civil",
    "13": "Obrigações Patronais",
    "14": "Diárias — Civil",
    "16": "Outras Despesas Variáveis — Pessoal Civil",
    "30": "Material de Consumo",
    "33": "Passagens e Despesas com Locomoção",
    "34": "Outras Despesas de Pessoal (Terceirização)",
    "35": "Serviços de Consultoria",
    "36": "Outros Serviços de Terceiros — Pessoa Física",
    "37": "Locação de Mão de Obra",
    "39": "Outros Serviços de Terceiros — Pessoa Jurídica",
    "40": "Serviços de Tecnologia da Informação",
    "41": "Contribuições",
    "46": "Auxílio-Alimentação",
    "47": "Obrigações Tributárias e Contributivas",
    "51": "Obras e Instalações",
    "52": "Equipamentos e Material Permanente",
    "92": "Despesas de Exercícios Anteriores",
    "93": "Indenizações e Restituições",
    "95": "Indenização pela Execução de Trabalhos de Campo",
    "97": "Aporte para Cobertura de Déficit Atuarial do RPPS",
}


def _fiorilli_categoria_nome(elemento):
    elemento = (elemento or "").strip()
    return _ELEMENTO_DESPESA_NOME.get(elemento, f"Elemento {elemento}" if elemento else "Outros")


def _slug(texto):
    import unicodedata
    texto = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return texto.lower().replace(" ", "-")


# Câmaras que usam o sistema Fiorilli SCPI 9.0 e expõem a API pública
# "Dados Abertos" (VersaoJson/*) sem sessão — descoberta em investigação
# manual. "temServidores" indica se o endpoint de folha de pagamento
# (que traz o subsídio do vereador) responde para essa entidade; onde
# não responde (erro 500 do lado deles), usamos só Diárias.
FIORILLI_CAMARAS = [
    {
        "cidade": "Ponta Porã",
        "urlBase": "https://contabilidade.pontapora.ms.gov.br/transparenciacm",
        "empresa": "15",
        "paramAno": "Ano",
        "temServidores": True,
        "portalOficial": "https://www.camarapontapora.ms.gov.br/",
    },
    {
        "cidade": "Três Lagoas",
        "urlBase": "http://pmtreslagoas.rcmsuporte.com.br:8079/transparenciacm",
        "empresa": "18",
        "paramAno": "Ano",
        "temServidores": True,
        "portalOficial": "https://cmtls.ms.gov.br/",
    },
    {
        "cidade": "Corumbá",
        "urlBase": "http://swb.corumba.ms.gov.br:8079/transparenciacm",
        "empresa": "46",
        "paramAno": "Ano",
        "temServidores": False,
        "portalOficial": "https://camaracorumba.ms.gov.br/",
    },
    {
        "cidade": "Paranaíba",
        "urlBase": "http://45.184.83.32:8079/transparenciacm",
        "empresa": "2",
        "paramAno": "Exercicio",
        "temServidores": False,
        "portalOficial": "https://cmparanaiba.ms.gov.br/",
    },
    {
        "cidade": "Sidrolândia",
        "urlBase": "https://transparencia.camarasidrolandia.ms.gov.br",
        "empresa": "2",
        "paramAno": "Ano",
        "temServidores": True,
        "portalOficial": "https://camarasidrolandia.ms.gov.br/",
    },
    {
        "cidade": "Aquidauana",
        "urlBase": "http://pmaquidauana.rcmsuporte.com.br:8079/transparenciacm",
        "empresa": "2",
        "paramAno": "Ano",
        "temServidores": False,
        "portalOficial": "https://cmaquidauana.ms.gov.br/",
    },
    {
        "cidade": "Coxim",
        "urlBase": "http://pmcoxim.rcmsuporte.com.br:8079/transparenciacm",
        "empresa": "1",
        "paramAno": "Ano",
        "temServidores": True,
        "portalOficial": "https://www.camaracoxim.ms.gov.br/",
    },
    {
        "cidade": "Jardim",
        "urlBase": "http://200.209.160.171:8079/transparenciacm",
        "empresa": "12",
        "paramAno": "Ano",
        "temServidores": False,
        "portalOficial": "https://camaramunicipaldejardim.ms.gov.br/",
    },
    {
        "cidade": "Chapadão do Sul",
        "urlBase": "http://pmchapadao.rcmsuporte.com.br:8079/transparenciaCM",
        "empresa": "1",
        "paramAno": "Ano",
        "temServidores": True,
        "portalOficial": "https://www.camarachapadaodosul.ms.gov.br/",
    },
    {
        "cidade": "Bonito",
        "urlBase": "http://45.188.183.155:8079/TransparenciaCM",
        "empresa": "15",
        "paramAno": "Ano",
        "temServidores": True,
        "portalOficial": "https://camarabonito.ms.gov.br/",
    },
    {
        "cidade": "Sonora",
        "urlBase": "http://pmsonora.rcmsuporte.com.br:8079/transparenciacm",
        "empresa": "1",
        "paramAno": "Ano",
        "temServidores": True,
        "portalOficial": "https://camarasonora.ms.gov.br/",
    },
    {
        "cidade": "Ribas do Rio Pardo",
        "urlBase": "http://45.174.220.245:8079/transparenciacm",
        "empresa": "10",
        "paramAno": "Ano",
        "temServidores": True,
        "portalOficial": "https://www.ribasdoriopardo.ms.leg.br/",
    },
]


def coletar_camara_fiorilli(cfg):
    log(f"Coletando Câmara Municipal de {cfg['cidade']} (Fiorilli SCPI)...")
    base = cfg["urlBase"]
    empresa = cfg["empresa"]
    param_ano = cfg["paramAno"]
    conectar = f"&ConectarExercicio={ANO}" if param_ano == "Ano" else ""

    vereadores = {}

    if cfg.get("temServidores"):
        # A folha do mês corrente costuma não estar publicada ainda —
        # tenta o mês atual e recua até 3 meses se vier vazio.
        mes_ref = datetime.now().month
        for tentativa in range(4):
            mes_tentado = mes_ref - tentativa
            if mes_tentado < 1:
                break
            try:
                url = (f"{base}/VersaoJson/Pessoal/?Listagem=Servidores&Empresa={empresa}"
                       f"&{param_ano}={ANO}{conectar}&MesFinalPeriodo={mes_tentado:02d}")
                registros = get_com_retry(url, tentativas=1).json()
                if registros:
                    for reg in registros:
                        if not (reg.get("CARGO") or "").strip().upper().startswith("VEREADOR"):
                            continue
                        nome = (reg.get("NOME") or "").strip()
                        if not nome:
                            continue
                        vereadores.setdefault(nome, {"nome": nome, "cargo": "Vereador(a)"})
                        vereadores[nome]["subsidioMensal"] = round(_fiorilli_parse_valor(reg.get("PROVENTOS")), 2)
                        vereadores[nome]["descontos"] = round(_fiorilli_parse_valor(reg.get("DESCONTOS")), 2)
                        vereadores[nome]["referenciaFolha"] = reg.get("REFERENCIA_NOME")
                    break
            except Exception as e:
                log(f"  ⚠️ Servidores ({mes_tentado:02d}/{ANO}) indisponível para {cfg['cidade']}: {e}")
                break  # erro real (ex.: 500) não adianta tentar outro mês

    try:
        url = (f"{base}/VersaoJson/Despesas/?Listagem=Diarias&DiaInicioPeriodo=01&MesInicialPeriodo=01"
               f"&DiaFinalPeriodo=31&MesFinalPeriodo=12&{param_ano}={ANO}{conectar}"
               f"&Empresa={empresa}&MostraDadosConsolidado=False")
        diarias = get_com_retry(url, tentativas=1).json()
        for d in diarias:
            if not (d.get("CARGO") or "").strip().upper().startswith("VEREADOR"):
                continue
            nome = (d.get("FAVORECIDO") or "").strip()
            if not nome:
                continue
            vereadores.setdefault(nome, {"nome": nome, "cargo": "Vereador(a)"})
            v = vereadores[nome]
            valor = round(_fiorilli_parse_valor(d.get("VALOR")), 2)
            v.setdefault("diarias", []).append({
                # não existe campo estruturado de destino/motivo nesse sistema —
                # essa informação vem embutida em texto livre na descrição.
                "data": _fiorilli_data_iso(d.get("DATA")),
                "valor": valor,
                "descricao": (d.get("DESCRICAO") or "").strip() or None,
            })
            v[f"totalDiarias{ANO}"] = round(v.get(f"totalDiarias{ANO}", 0) + valor, 2)
            v[f"numDiarias{ANO}"] = v.get(f"numDiarias{ANO}", 0) + 1
    except Exception as e:
        log(f"  ⚠️ Diárias indisponível para {cfg['cidade']}: {e}")

    if not vereadores:
        log(f"  ⚠️ Nenhum dado coletado para {cfg['cidade']} — mantendo dados anteriores")
        return None

    for v in vereadores.values():
        if "diarias" in v:
            v["diarias"].sort(key=lambda x: x["data"] or "", reverse=True)

    # Despesas institucionais — gasto da Câmara como entidade (fornecedor,
    # licitação, categoria de elemento de despesa). NÃO é atribuível a um
    # vereador específico, é o gasto da instituição como um todo.
    despesas_institucionais = None
    try:
        url = (f"{base}/VersaoJson/Despesas/?Listagem=DespesasGerais&DiaInicioPeriodo=01&MesInicialPeriodo=01"
               f"&DiaFinalPeriodo=31&MesFinalPeriodo=12&{param_ano}={ANO}{conectar}"
               f"&Empresa={empresa}&MostrarFornecedor=True&MostraDadosConsolidado=False"
               f"&UFParaFiltroCOVID=&MostrarCNPJFornecedor=True&ApenasIDEmpenho=False")
        registros = get_com_retry(url, tentativas=1).json()
        despesas = []
        por_categoria = {}
        total_geral = 0.0
        for r in registros:
            valor = round(_fiorilli_parse_valor(r.get("PAGO") or r.get("EMPENHADO")), 2)
            categoria = r.get("NOME_ELEMENTO") or _fiorilli_categoria_nome(r.get("ELEMENTO"))
            despesas.append({
                "data": _fiorilli_data_iso(r.get("DATAE")),
                "fornecedor": (r.get("NOMEFOR") or "").strip() or None,
                "cnpj": (r.get("CPFFORMATADO") or "").strip() or None,
                "categoria": categoria,
                "valor": valor,
                "descricao": (r.get("PRODU") or "").strip()[:300] or None,
            })
            por_categoria[categoria] = round(por_categoria.get(categoria, 0) + valor, 2)
            total_geral += valor
        despesas.sort(key=lambda x: x["valor"], reverse=True)
        despesas_institucionais = {
            "totalGeral": round(total_geral, 2),
            "totalNotas": len(despesas),
            "porCategoria": dict(sorted(por_categoria.items(), key=lambda x: -x[1])),
            "despesas": despesas,
        }
    except Exception as e:
        log(f"  ⚠️ Despesas gerais indisponível para {cfg['cidade']}: {e}")

    lista = sorted(vereadores.values(), key=lambda v: v["nome"])
    tem_subsidio = any("subsidioMensal" in v for v in lista)
    host = base.split("//")[1].split("/")[0]
    data = {
        "cidade": cfg["cidade"],
        "ultimaAtualizacao": hoje,
        "fonte": f"Portal Transparência Fiorilli ({host}) — Dados Abertos — {hoje}",
        "sistema": "Fiorilli SCPI 9.0",
        "portalOficial": cfg["portalOficial"],
        "temDadosFinanceiros": True,
        "totalVereadores": len(lista),
        "vereadores": lista,
        "despesasInstitucionais": despesas_institucionais,
    }
    if not tem_subsidio:
        data["notaFinanceiro"] = "O endpoint de folha de pagamento (subsídio) está indisponível nesta câmara no momento (erro do lado deles). Os valores mostrados são apenas diárias pagas."
    salvar(f"camaras/{_slug(cfg['cidade'])}.json", data)
    log(f"  {len(lista)} vereadores de {cfg['cidade']} salvos ({'com subsídio' if tem_subsidio else 'só diárias'})"
        + (f", {despesas_institucionais['totalNotas']} despesas institucionais" if despesas_institucionais else ""))
    return data


def coletar_camaras_fiorilli():
    for cfg in FIORILLI_CAMARAS:
        try:
            coletar_camara_fiorilli(cfg)
        except Exception as e:
            log(f"  ❌ {cfg['cidade']}: {e}")

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
        coletar_prefeitura()
    except Exception as e:
        erros.append(f"Prefeitura: {e}")
        log(f"❌ {e}")

    try:
        coletar_emendas_ms()
    except Exception as e:
        erros.append(f"Emendas MS: {e}")
        log(f"❌ {e}")

    try:
        coletar_camara_dourados()
    except Exception as e:
        erros.append(f"Câmara Dourados: {e}")
        log(f"❌ {e}")

    try:
        coletar_camaras_fiorilli()
    except Exception as e:
        erros.append(f"Câmaras Fiorilli: {e}")
        log(f"❌ {e}")

    # Coletores "pesados" (listas completas do Brasil, 500+ requisicoes) rodam
    # por ultimo -- se uma API externa estiver degradada e o timeout do job
    # estourar, as fontes de MS ja estarao salvas.
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

    gerar_status()

    log("=" * 50)
    if erros:
        log(f"⚠️ Concluído com {len(erros)} erro(s): {erros}")
        sys.exit(1)
    else:
        log("✅ Todos os dados coletados com sucesso!")
