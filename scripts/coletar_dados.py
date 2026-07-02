#!/usr/bin/env python3
"""
Cofre Aberto MS — Script de coleta automática de dados
Roda via GitHub Actions todo dia às 6h BRT

Fontes:
- Câmara Federal: dadosabertos.camara.leg.br (API REST, CORS livre)
- Senado Federal: adm.senado.gov.br/ergon-ng-reports (API REST)
- ALEMS: consulta.transparencia.al.ms.gov.br/ceap (CSV público)
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
    for i in range(tentativas):
        try:
            r = requests.get(url, headers=HEADERS, timeout=60, **kwargs)
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

        # Buscar CEAP do ano atual
        ceap_total = None
        ceap_cats = []
        try:
            ceap_r = requests.get(
                f"https://dadosabertos.camara.leg.br/api/v2/deputados/{dep_id}/despesas"
                f"?ano={ANO}&itens=100&ordem=DESC&ordenarPor=dataDocumento",
                headers=HEADERS, timeout=20
            ).json().get("dados", [])

            if ceap_r:
                # Agrupar por tipo
                por_tipo = {}
                for item in ceap_r:
                    tipo = item.get("tipoDespesa", "Outros")
                    valor = float(item.get("valorLiquido") or 0)
                    por_tipo[tipo] = por_tipo.get(tipo, 0) + valor
                ceap_total = sum(por_tipo.values())
                ceap_cats = [{"categoria": k, "valor": round(v, 2)}
                             for k, v in sorted(por_tipo.items(), key=lambda x: -x[1])]
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
            "cotaGastaAno": round(ceap_total, 2) if ceap_total else None,
            "ceapCategorias": ceap_cats,
            "salarioBase": 41650.92,
        })
        log(f"  ✓ {d.get('nome')} — CEAP: R$ {ceap_total:,.2f}" if ceap_total else f"  ✓ {d.get('nome')}")

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

        # Buscar recursos utilizados via API JSON
        ceaps = {}
        extras = {}
        pessoal = {}
        ano_dados = ANO
        try:
            api_r = requests.get(
                f"https://adm.senado.gov.br/ergon-ng-reports/api/v1/senadores/{sen_id}/recursos-utilizados"
                f"?ano={ANO}&formato=json",
                headers=HEADERS, timeout=20
            )
            if api_r.ok:
                api_data = api_r.json()
                # Extrair CEAPS
                for item in api_data.get("ceaps", []):
                    ceaps[item.get("descricao", "Outros")] = float(item.get("valor", 0) or 0)
                # Extrair gastos extras
                for item in api_data.get("gastosNaoCeaps", []):
                    extras[item.get("descricao", "Outros")] = float(item.get("valor", 0) or 0)
                pessoal = api_data.get("pessoal", {})
                ano_dados = api_data.get("ano", ANO)
        except Exception as e:
            log(f"    API Senado erro para {ident.get('NomeParlamentar')}: {e}")

        ant_s = dados_ant.get(sen_id, {})
        total_ceaps = sum(ceaps.values())
        total_extras = sum(extras.values())

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
            "ceaps": ceaps,
            "gastosExtras": extras,
            "pessoal": pessoal,
            "cotaGastaAno": round(total_ceaps, 2) if total_ceaps else ant_s.get("cotaGastaAno"),
            "totalGasto": round(total_ceaps + total_extras, 2) if total_ceaps else None,
            "ceapsCategorias": [{"categoria": k, "valor": round(v, 2)}
                                for k, v in sorted(ceaps.items(), key=lambda x: -x[1]) if v > 0],
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
def coletar_dep_estaduais():
    log("Coletando deputados estaduais ALEMS...")

    # CSV de CEAP da ALEMS (URL pública)
    url_ceap = f"https://consulta.transparencia.al.ms.gov.br/ceap/export/csv"

    try:
        r = get_com_retry(url_ceap)
        r.raise_for_status()
        texto = r.content.decode("utf-8-sig", errors="replace")
        reader = csv.DictReader(io.StringIO(texto), delimiter=";")
        linhas = list(reader)
        log(f"  {len(linhas)} linhas no CSV ALEMS")
    except Exception as e:
        log(f"  ⚠️ CSV ALEMS indisponível: {e} — mantendo dados anteriores")
        return None

    # Agrupar por deputado e categoria
    por_dep = {}
    for row in linhas:
        nome = row.get("Deputado", "").strip()
        cat = row.get("Categoria/Despesa", "").strip()
        try:
            valor = float(row.get("Valor (R$)", "0").replace(".", "").replace(",", "."))
        except:
            valor = 0

        if nome not in por_dep:
            por_dep[nome] = {"total": 0, "categorias": {}}
        por_dep[nome]["categorias"][cat] = por_dep[nome]["categorias"].get(cat, 0) + valor
        por_dep[nome]["total"] += valor

    log(f"  {len(por_dep)} deputados com gastos em {ANO}")

    # Carregar dados anteriores (fotos, notas fiscais)
    try:
        dados_ant = json.load(open(DADOS / "deputados_estaduais_ms.json"))
        deps_ant = {d["nome"]: d for d in dados_ant.get("vereadores", [])}
    except:
        deps_ant = {}

    deps = []
    for nome_csv, gastos in por_dep.items():
        # Normalizar nome
        nome_norm = nome_csv.replace("Dep. ", "").replace("DEP. ", "").strip()
        ant = deps_ant.get(nome_norm, {})

        deps.append({
            **ant,  # manter tudo que já tínhamos (fotos, notas, etc.)
            "nome": ant.get("nome", nome_norm),
            "ultimaAtualizacao": hoje,
            "verbaIndenizatoria": {
                **ant.get("verbaIndenizatoria", {}),
                "gastoPago2026": round(gastos["total"], 2),
                "categorias": {k: round(v, 2) for k, v in gastos["categorias"].items()},
                "periodoColetado": f"Jan–{datetime.now().strftime('%b')}/{ANO}",
                "fonte": f"consulta.transparencia.al.ms.gov.br/ceap — {hoje}",
            },
        })

    data = {
        **(dados_ant if deps_ant else {}),
        "ultimaAtualizacao": hoje,
        "fonte": f"Portal da Transparência ALEMS (consulta.transparencia.al.ms.gov.br/ceap) — {hoje}",
        "vereadores": deps if deps else dados_ant.get("vereadores", []),
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
        ant = sens_ant.get(sid, {})

        senadores.append({
            **ant,
            "id": sid,
            "nome": ident.get("NomeParlamentarFormatado") or ident.get("NomeParlamentar"),
            "partido": ident.get("SiglaPartidoParlamentar"),
            "uf": ident.get("UfParlamentar"),
            "foto": ant.get("fotoBase64") or ident.get("UrlFotoParlamentar") or
                    f"https://legis.senado.leg.br/senadores/fotos-oficiais/{sid}",
            "urlTransparencia": f"https://www6g.senado.leg.br/transparencia/sen/{sid}/?ano={ANO}",
        })

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

    # Carregar dados anteriores
    try:
        dados_ant = json.load(open(DADOS / "deputados_federais_brasil.json"))
    except:
        dados_ant = {}

    data = {
        "ultimaAtualizacao": hoje,
        "fonte": f"API da Câmara dos Deputados — {hoje}",
        "total": len(deputados),
        "deputados": [{
            "id": d["id"],
            "nome": d["nome"],
            "partido": d["siglaPartido"],
            "uf": d["siglaUf"],
            "foto": d["urlFoto"],
            "urlPerfil": f"https://www.camara.leg.br/deputados/{d['id']}",
        } for d in deputados],
    }
    salvar("deputados_federais_brasil.json", data)
    return deputados

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

    # Agrupar por secretaria
    por_secretaria = {}
    total_geral = 0
    for row in linhas:
        try:
            secretaria = (row.get("orgao") or "Outros").strip()
            valor_str = (row.get("total_pago") or "0").strip()
            # Tratar formato BR (1.234,56) e centavos inteiros (123456)
            v = valor_str.strip().replace("R$", "").strip()
            if "," in v:
                # Formato BR: 1.234,56 → remover pontos de milhar, trocar vírgula por ponto
                v = v.replace(".", "").replace(",", ".")
            elif "." in v:
                # Formato US: 1234.56 → usar direto
                pass
            else:
                # Inteiro puro — pode estar em centavos
                v = v or "0"
            valor = float(v or 0)
            # Sanity check: se valor unitário > 1 bilhão, provavelmente está em centavos
            if valor > 1_000_000_000:
                valor = valor / 100
            por_secretaria[secretaria] = por_secretaria.get(secretaria, 0) + valor
            total_geral += valor
        except:
            continue

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
    }
    salvar("prefeitura.json", data)
    log(f"  Total despesas {ano}: R$ {total_geral:,.2f}")
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

    gerar_status()

    log("=" * 50)
    if erros:
        log(f"⚠️ Concluído com {len(erros)} erro(s): {erros}")
        sys.exit(1)
    else:
        log("✅ Todos os dados coletados com sucesso!")
