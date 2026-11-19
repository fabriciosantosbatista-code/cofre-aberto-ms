#!/usr/bin/env python3
"""
Cofre Aberto MS — Script de coleta automática de dados
Roda via GitHub Actions todo dia às 6h BRT

Fontes:
- Câmara Federal: dadosabertos.camara.leg.br (lista) + camara.leg.br/cotas/Ano-AAAA.csv.zip (CEAP completo)
- Senado Federal: adm.senado.gov.br/ergon-ng-reports (API REST)
- ALEMS: transparencia2.al.ms.gov.br/ceap (API JSON própria, token por deputado)
"""

import json, requests, csv, io, os, sys, time
from datetime import datetime, date, timedelta
from pathlib import Path

import re as _re
PASSAGEM = _re.compile(r"SIGEPA|PASSAGE[MN]S? A[EÉ]REA - RPA", _re.I)  # na API da Câmara só estas não vêm com o sinal invertido (o reembolso de passagem vem)
# Paginação da API da Câmara (/deputados/{id}/despesas): sem ordenação, repete e pula despesas entre as páginas (a
# mesma deputada veio com 472 e com 360 linhas, 61 repetidas, em duas leituras seguidas); ordenada pela data no ano
# inteiro, também perde linhas (um deputado veio com 351 de 490). Lida mês a mês (cada mês cabe numa página de 100),
# ordenada pela data, a leitura é completa e igual entre rodadas.
ORDEM_API = {"ordenarPor": "dataDocumento", "ordem": "ASC"}


def despesas_api_por_mes(dep_id, ano, timeout=30, get=None):
    """Todas as despesas do deputado no ano pela API, mês a mês (ordenadas pela data dentro do mês). Levanta exceção
    se alguma página não vier — leitura parcial não serve."""
    get = get or (lambda params: requests.get(f"https://dadosabertos.camara.leg.br/api/v2/deputados/{dep_id}/despesas",
                                              params=params, headers=HEADERS, timeout=timeout))
    hoje = date.today()
    ult = 12 if int(ano) < hoje.year else hoje.month
    out = []
    for mes in range(1, ult + 1):
        pagina = 1
        while True:
            r = get({"ano": ano, "mes": mes, "itens": 100, "pagina": pagina, **ORDEM_API})
            r.raise_for_status()
            j = r.json()
            out += j.get("dados") or []
            if not any(l.get("rel") == "next" for l in j.get("links") or []):
                break
            pagina += 1
    return out

ROOT = Path(__file__).parent.parent
DADOS = ROOT / "dados"
sys.path.insert(0, str(Path(__file__).parent))
from ano_ref import ano_referencia
import limite_cgu
# Ano de referência: vira em 1º de fevereiro (ver scripts/ano_ref.py) — em janeiro
# ainda chegam as notas de dezembro, então o ano anterior fecha completo.
ANO = ano_referencia()
MESES_PT = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]


def mes_fim_periodo():
    """Último mês do período coletado, em português (dez se o ano de referência já fechou)."""
    return "dez" if ANO < date.today().year else MESES_PT[date.today().month - 1]


def mesmo_ano(dados_ant):
    """Os dados anteriores são do mesmo ano de referência? (na virada, não podem ser reaproveitados)"""
    return (dados_ant or {}).get("ano", 2026) == ANO
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
            if "api.portaldatransparencia.gov.br" in url:
                limite_cgu.esperar_vez()  # cada tentativa conta: 400/min de dia, 700/min de madrugada — passar suspende o token
            r = requests.get(url, headers=headers, timeout=60, **kwargs)
            r.raise_for_status()
            return r
        except Exception as e:
            if i == tentativas - 1:
                raise
            st = getattr(getattr(e, "response", None), "status_code", None)
            if st == 429:  # limite da API: espera o que ela pedir (Retry-After) ou 30–60 s, até 2 repetições
                espera = limite_cgu.espera_429(e.response.headers.get("Retry-After"))
                log(f"  429 (limite de requisições) — esperando {espera:.0f} s antes da repetição {i + 1} de {tentativas - 1}")
                time.sleep(espera)
                continue
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
# CEAP — arquivo completo da Câmara (camara.leg.br/cotas/Ano-AAAA.csv.zip)
# ============================================================
# O endpoint /deputados/{id}/despesas da API passou a devolver lista vazia
# (desde ago/2026, para qualquer ano). O arquivo anual completo, publicado
# pela própria Câmara e atualizado diariamente, tem as mesmas notas — é a
# fonte primária; a API por deputado fica só como fallback.
_CEAP_BULK = {}

def _formata_cnpj_cpf(txt):
    # O CSV da Câmara traz a máscara deslocada (ex.: "049.904.400/0019-4")
    n = "".join(ch for ch in (txt or "") if ch.isdigit())
    if len(n) == 14:
        return f"{n[:2]}.{n[2:5]}.{n[5:8]}/{n[8:12]}-{n[12:]}"
    if len(n) == 11:
        return f"{n[:3]}.{n[3:6]}.{n[6:9]}-{n[9:]}"
    return (txt or "").strip()

def salvar_notas_por_uf(pasta, ids_uf, notas_por_id, fonte):
    """Grava dados/<pasta>/<UF>.json = {"deputados"/"parlamentares": {id: [notas]}}.
    Um arquivo por estado: o painel só baixa o do parlamentar que o usuário abrir.
    Se notas_por_id estiver vazio (fonte fora do ar), não mexe nos arquivos."""
    if not notas_por_id:
        log(f"  ⚠️ Sem notas para {pasta} — mantendo arquivos anteriores")
        return
    por_uf = {}
    for pid, uf in ids_uf:
        if not uf:
            continue
        por_uf.setdefault(uf, {})[str(pid)] = notas_por_id.get(pid, [])
    def compacta(n):
        # sem campos vazios nem "mes" (já está na data) — reduz o arquivo ~40%
        return {k: v for k, v in n.items() if v not in (None, "") and k != "mes"}
    (DADOS / pasta).mkdir(parents=True, exist_ok=True)
    for uf, mapa in sorted(por_uf.items()):
        cab = {"ultimaAtualizacao": hoje, "ano": ANO, "uf": uf, "fonte": fonte,
               "totalNotas": sum(len(v) for v in mapa.values())}
        # JSON compacto, uma linha por parlamentar (diffs diários pequenos)
        linhas = [f"{json.dumps(pid)}:{json.dumps([compacta(n) for n in notas], ensure_ascii=False, separators=(',', ':'))}"
                  for pid, notas in sorted(mapa.items(), key=lambda x: int(x[0]))]
        texto = json.dumps(cab, ensure_ascii=False)[:-1] + ',"parlamentares":{\n' + ",\n".join(linhas) + "\n}}\n"
        path = DADOS / pasta / f"{uf}.json"
        path.write_text(texto, encoding="utf-8")
    log(f"✅ {pasta}/: {len(por_uf)} estados salvos")


def carregar_ceap_bulk(ano):
    """Devolve {ideCadastro: {"cotaGastaAno", "ceapCategorias", "totalNotasFiscais", "despesas"}}
    ou None se o arquivo não puder ser baixado/lido."""
    if ano in _CEAP_BULK:
        return _CEAP_BULK[ano]
    import zipfile, tempfile
    url = f"https://www.camara.leg.br/cotas/Ano-{ano}.csv.zip"
    log(f"Baixando CEAP completo da Câmara ({url})...")
    try:
        with tempfile.TemporaryFile() as tmp:
            with requests.get(url, headers={**HEADERS, "Accept": "*/*"}, timeout=300, stream=True) as r:
                r.raise_for_status()
                for bloco in r.iter_content(1 << 20):
                    tmp.write(bloco)
            tmp.seek(0)
            z = zipfile.ZipFile(tmp)
            nome_csv = next(n for n in z.namelist() if n.lower().endswith(".csv"))
            por_dep = {}
            with z.open(nome_csv) as f:
                leitor = csv.DictReader(io.TextIOWrapper(f, encoding="utf-8-sig"), delimiter=";")
                for row in leitor:
                    try:
                        dep_id = int(row.get("ideCadastro") or 0)
                    except ValueError:
                        continue
                    if not dep_id:
                        continue
                    valor = float((row.get("vlrLiquido") or "0").replace(",", ".") or 0)
                    d = por_dep.setdefault(dep_id, {"total": 0.0, "cats": {}, "despesas": [], "uf": row.get("sgUF")})
                    cat = row.get("txtDescricao") or "Outros"
                    d["total"] += valor
                    d["cats"][cat] = d["cats"].get(cat, 0) + valor
                    mes = int(row.get("numMes") or 0) or None
                    d["despesas"].append({
                        "data": (row.get("datEmissao") or "")[:10] or (f"{ano}-{mes:02d}-01" if mes else None),
                        "categoria": cat,
                        "fornecedor": (row.get("txtFornecedor") or "").strip(),
                        "cnpjCpfFornecedor": _formata_cnpj_cpf(row.get("txtCNPJCPF")),
                        "valor": round(valor, 2),
                        "doc": (row.get("txtNumero") or "").strip(),
                        "urlNotaFiscal": row.get("urlDocumento") or None,
                        "mes": mes,
                    })
    except Exception as e:
        log(f"  ⚠️ CEAP completo indisponível: {e} — usando API por deputado")
        _CEAP_BULK[ano] = None
        return None

    # Em 2026 o arquivo anual deixou de trazer as passagens aéreas emitidas pelo SIGEPA (sistema de passagens da
    # Câmara), que contam na cota e aparecem na API. Se o arquivo não tiver nenhuma, completa pela API.
    if not any("SIGEPA" in c for d in por_dep.values() for c in d["cats"]):
        ordem = sorted(por_dep, key=lambda i: por_dep[i].get("uf") != "MS")  # MS primeiro
        for dep_id, notas in sigepa_pela_api(ordem, ano).items():
            d = por_dep[dep_id]
            for n in notas:
                d["total"] += n["valor"]
                d["cats"][n["categoria"]] = d["cats"].get(n["categoria"], 0) + n["valor"]
                d["despesas"].append(n)

    resultado = {}
    for dep_id, d in por_dep.items():
        d["despesas"].sort(key=lambda x: x["data"] or "", reverse=True)
        resultado[dep_id] = {
            "cotaGastaAno": round(d["total"], 2),
            "ceapCategorias": [{"categoria": k, "valor": round(v, 2)}
                               for k, v in sorted(d["cats"].items(), key=lambda x: -x[1])],
            "totalNotasFiscais": len(d["despesas"]),
            "despesas": d["despesas"],
        }
    log(f"  CEAP {ano}: {sum(x['totalNotasFiscais'] for x in resultado.values())} notas de {len(resultado)} deputados")
    _CEAP_BULK[ano] = resultado
    return resultado


def api_invertida(itens):
    """A API da Câmara passou (nov/2026) a devolver o valorLiquido com o sinal invertido em relação ao arquivo anual
    oficial em todas as despesas comuns (as passagens do SIGEPA não). Detecta pela própria resposta: se a maioria das
    despesas comuns com documento positivo vem com líquido negativo, a resposta está invertida."""
    comuns = [x for x in itens if not PASSAGEM.search(x.get("tipoDespesa") or "") and float(x.get("valorDocumento") or 0) > 0]
    neg = sum(1 for x in comuns if float(x.get("valorLiquido") or 0) < 0)
    return bool(comuns) and neg > len(comuns) / 2


def _valor_api(item, invertida=False):
    """Valor líquido de uma despesa da API, com o sinal do arquivo anual oficial da Câmara (conferido centavo por centavo)."""
    liq = float(item.get("valorLiquido") or 0)
    if PASSAGEM.search(item.get("tipoDespesa") or ""):  # SIGEPA, RPA...
        return liq  # passagens: sinal certo (negativo = estorno de bilhete)
    return -liq if invertida else liq


def sigepa_pela_api(dep_ids, ano, limite_seg=9 * 60):
    """{dep_id: [notas de passagem aérea SIGEPA]} lidas da API por deputado (em paralelo, com limite de tempo)."""
    from concurrent.futures import ThreadPoolExecutor
    t0 = time.monotonic()

    def um(dep_id):
        if time.monotonic() - t0 > limite_seg:
            return dep_id, None
        try:
            itens = despesas_api_por_mes(dep_id, ano)
        except Exception:
            return dep_id, None
        out = []
        for it in itens:
            if "SIGEPA" in (it.get("tipoDespesa") or ""):
                v = round(_valor_api(it), 2)
                out.append({"data": (it.get("dataDocumento") or "")[:10] or None, "categoria": it.get("tipoDespesa"),
                            "fornecedor": (it.get("nomeFornecedor") or "").strip(), "cnpjCpfFornecedor": _formata_cnpj_cpf(it.get("cnpjCpfFornecedor")),
                            "valor": v, "doc": (it.get("numDocumento") or "").strip(), "urlNotaFiscal": it.get("urlDocumento") or None,
                            "mes": it.get("mes")})
        return dep_id, out

    res, falhas = {}, 0
    with ThreadPoolExecutor(8) as ex:
        for dep_id, notas in ex.map(um, dep_ids):
            if notas is None:
                falhas += 1
            elif notas:
                res[dep_id] = notas
    log(f"  SIGEPA: passagens aéreas de {len(res)} deputados lidas pela API ({sum(len(v) for v in res.values())} bilhetes)"
        + (f"; {falhas} sem resposta" if falhas else ""))
    return res


def ceap_do_deputado(dep_id, ceap_anterior, nome, incluir_notas):
    """CEAP de um deputado: arquivo completo primeiro, API como fallback,
    e nunca apaga um valor já publicado por causa de uma resposta vazia."""
    bulk = carregar_ceap_bulk(ANO)
    if bulk is not None:
        ceap = dict(bulk.get(dep_id) or {"cotaGastaAno": None, "ceapCategorias": [], "totalNotasFiscais": 0, "despesas": []})
    else:
        try:
            ceap = buscar_ceap_deputado_agregado(dep_id, ANO)
        except Exception as e:
            log(f"    CEAP erro para {nome}: {e} — mantendo dado anterior")
            ceap = ceap_anterior
    if not incluir_notas:
        ceap.pop("despesas", None)
    return _preservar_ceap_se_vazio(ceap, ceap_anterior, nome)


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
        deputados = None
        log(f"  ⚠️ API Câmara indisponível: {e}")

    try:
        dados_ant = json.load(open(DADOS / "deputados_federais_ms.json", encoding="utf-8"))
        ceap_ant = {d["id"]: d for d in dados_ant.get("deputados", [])}
    except:
        dados_ant, ceap_ant = {}, {}
    if not mesmo_ano(dados_ant):
        # virada do ano: a lista anterior serve de reserva, mas o CEAP/notas não
        ceap_ant = {k: {kk: vv for kk, vv in v.items() if kk not in ("cotaGastaAno", "ceapCategorias", "totalNotasFiscais", "despesas")}
                    for k, v in ceap_ant.items()}

    if not deputados:
        # Lista da API fora do ar: reaproveita a lista anterior (o CEAP vem do arquivo completo)
        if not ceap_ant or carregar_ceap_bulk(ANO) is None:
            log("  ⚠️ Sem lista de deputados — mantendo dados anteriores")
            return None
        log("  Usando a lista de deputados da coleta anterior")
        deputados = [{"id": a["id"], "nome": a.get("nome"), "siglaPartido": a.get("partido"),
                      "urlFoto": a.get("foto"), "_ant": a} for a in ceap_ant.values()]
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
        if not det and d.get("_ant"):
            a = d["_ant"]
            det = {"nomeCivil": a.get("nomeCompleto"), "ultimoStatus": {"email": a.get("email"), "gabinete": a.get("gabinete", {})}}

        # Buscar CEAP do ano atual (paginado — um deputado pode ter mais de 100 notas/ano).
        # Se a API falhar, mantém o CEAP anterior em vez de zerar o dado já publicado.
        ant = ceap_ant.get(dep_id, {})
        ceap_anterior = {
            "cotaGastaAno": ant.get("cotaGastaAno"),
            "ceapCategorias": ant.get("ceapCategorias", []),
            "totalNotasFiscais": ant.get("totalNotasFiscais", 0),
            "despesas": ant.get("despesas", []),
        }
        ceap = ceap_do_deputado(dep_id, ceap_anterior, d.get("nome"), incluir_notas=True)

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


_CEAPS_NOTAS = {}

def carregar_notas_ceaps_senado(ano):
    """Notas fiscais individuais da CEAPS de todos os senadores no ano, da API
    de dados abertos do Senado. Devolve {codSenador: [notas]} ou None."""
    if ano in _CEAPS_NOTAS:
        return _CEAPS_NOTAS[ano]
    import re
    url = f"https://adm.senado.gov.br/adm-dadosabertos/api/v1/senadores/despesas_ceaps/{ano}"
    try:
        r = requests.get(url, headers=HEADERS, timeout=180)
        r.raise_for_status()
        itens = r.json()
        if not isinstance(itens, list):
            raise ValueError("formato inesperado")
    except Exception as e:
        log(f"  ⚠️ Notas CEAPS indisponíveis: {e} — mantendo notas anteriores")
        _CEAPS_NOTAS[ano] = None
        return None
    por_sen = {}
    for n in itens:
        por_sen.setdefault(n.get("codSenador"), []).append({
            "data": n.get("data"),
            "mes": n.get("mes"),
            "categoria": re.split(r",\s*(?:compreendendo|inclusive)\b", n.get("tipoDespesa") or "")[0].strip().rstrip("."),
            "fornecedor": (n.get("fornecedor") or "").strip(),
            "cnpjCpf": (n.get("cpfCnpj") or "").strip(),
            "doc": (n.get("documento") or "").strip(),
            "tipoDocumento": n.get("tipoDocumento"),
            "detalhamento": n.get("detalhamento"),
            "valor": round(float(n.get("valorReembolsado") or 0), 2),
        })
    for L in por_sen.values():
        L.sort(key=lambda x: x["data"] or "", reverse=True)
    log(f"  Notas CEAPS {ano}: {len(itens)} notas de {len(por_sen)} senadores")
    _CEAPS_NOTAS[ano] = por_sen
    return por_sen


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

    notas_ant = {}
    try:
        _sen_ant = json.load(open(DADOS / "senadores_ms.json", encoding="utf-8"))
        if mesmo_ano(_sen_ant):  # na virada do ano, notas antigas não valem para o ano novo
            for s_ant in _sen_ant.get("senadores", []):
                notas_ant[s_ant["id"]] = s_ant.get("notasCeaps", [])
    except: pass
    notas_ceaps = carregar_notas_ceaps_senado(ANO)

    resultado = []
    for p in senadores_ms:
        ident = p["IdentificacaoParlamentar"]
        sen_id = int(ident["CodigoParlamentar"])
        time.sleep(0.5)
        notas = (notas_ceaps or {}).get(sen_id) if notas_ceaps is not None else None
        if not notas:
            notas = notas_ant.get(sen_id, [])  # API fora do ar ou vazia: não apaga as notas já publicadas

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
            "cotaGastaAno": round(total_ceaps, 2) if total_ceaps else (ant_s.get("cotaGastaAno") if ant_s.get("anoReferencia") == ano_dados else None),
            "totalGasto": round(total_ceaps + total_extras, 2) if total_ceaps else None,
            "ceapsCategorias": [{"categoria": k, "valor": round(v, 2)}
                                for k, v in sorted(recursos["ceaps"].items(), key=lambda x: -x[1]) if v > 0],
            "despesas": ant_s.get("despesas", []),
            "notasCeaps": notas,
            "totalNotasFiscais": len(notas),
            "escritorioApoio": ant_s.get("escritorioApoio", ""),
            "fonteCeaps": f"adm.senado.gov.br — dados de {hoje}",
            "nota": "" if total_ceaps else f"Dados de {ANO} ainda não publicados. Exibindo {ano_dados}.",
        })
        log(f"  ✓ {ident.get('NomeParlamentar')} — CEAPS {ano_dados}: R$ {total_ceaps:,.2f} — {len(notas)} notas")

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
    # Em ago/2026 a ALEMS migrou o portal de consulta.transparencia.al.ms.gov.br
    # (ScriptCase, HTML raspado) para transparencia2.al.ms.gov.br (API JSON própria).
    # O endpoint /ceap/data lista os deputados com gasto no ano e um "detalheToken"
    # por deputado; /ceap/notas (paginado, perPage=50) devolve as notas fiscais
    # daquele deputado usando esse token — sem precisar simular formulário/sessão.
    log("Coletando deputados estaduais ALEMS (CEAP)...")
    import re

    BASE = "https://transparencia2.al.ms.gov.br/ceap"

    try:
        # perPage padrão do endpoint é 10 — sem informar explicitamente, a
        # resposta vem truncada e a maioria dos deputados nem aparece.
        linhas = []
        pagina = 1
        while True:
            r = requests.get(f"{BASE}/data", params={"ano": ANO, "page": pagina, "perPage": 50},
                              headers={**HEADERS, "Accept": "application/json"}, timeout=30)
            r.raise_for_status()
            pag = r.json()
            linhas.extend(pag.get("rows", []))
            if len(linhas) >= pag.get("total", len(linhas)):
                break
            pagina += 1
        log(f"  {len(linhas)} deputados com gastos no filtro da ALEMS")
    except Exception as e:
        log(f"  ⚠️ ALEMS indisponível ao abrir o filtro: {e} — mantendo dados anteriores")
        return None

    try:
        dados_ant = json.load(open(DADOS / "deputados_estaduais_ms.json", encoding="utf-8"))
        deps_ant = {d["nome"]: d for d in dados_ant.get("vereadores", [])}
    except:
        dados_ant = {}
        deps_ant = {}
    if not mesmo_ano(dados_ant):
        # Virada do ano: mantém o cadastro (foto, partido, gabinete), zera CEAP e notas
        # e leva a cota anual para o ano novo (o valor da cota é o mesmo até mudar a lei).
        ano_ant = dados_ant.get("ano", 2026)
        for d in deps_ant.values():
            vi = d.get("verbaIndenizatoria") or {}
            cota = vi.get(f"cotaAnual{ano_ant}")
            d["verbaIndenizatoria"] = {k: v for k, v in vi.items() if not re.search(r"\d{4}$", k) and k not in ("categorias", "percentualUsado")}
            if cota:
                d["verbaIndenizatoria"][f"cotaAnual{ANO}"] = cota
            d["despesas"], d["totalNotasFiscais"] = [], 0
        dados_ant = {k: v for k, v in dados_ant.items() if k != "resumo"} | {"resumo": {
            k: v for k, v in (dados_ant.get("resumo") or {}).items() if not re.search(r"\d{4}$", k)}}
        log(f"  Virada do ano ({ano_ant} → {ANO}): CEAP e notas zerados, cadastro mantido")

    resultados = {}
    total_geral = 0.0
    for i, linha in enumerate(linhas):
        nome_dep = linha.get("deputado", "")
        token = linha.get("detalheToken")
        if not token:
            continue
        try:
            # A API pagina de 50 em 50. Ordenada por data de emissão (muitas notas com a
            # mesma data), a ordem entre páginas não é estável: notas se repetiam e
            # outras sumiam (6 deputados com total diferente do portal em nov/2026).
            # Ordenando por documento e por valor, junta-se sem repetição e confere-se
            # a soma com o total que o próprio portal informa para o deputado.
            total_portal = _alems_parse_valor(linha.get("total")) if linha.get("total") else None
            vistas, notas = set(), []
            for ordem in ("documento", "valor", "emissao"):
                pagina = 1
                while True:
                    r2 = requests.get(f"{BASE}/notas", params={
                        "ano": ANO, "token": token, "sort": ordem, "dir": "asc",
                        "page": pagina, "perPage": 50,
                    }, headers={**HEADERS, "Accept": "application/json"}, timeout=30)
                    r2.raise_for_status()
                    pag = r2.json()
                    for n in pag.get("rows", []):
                        chave = tuple(str(n.get(k) or "") for k in ("documento", "comprovante", "valor", "emissao",
                                                                     "lancamento", "fornecedor", "cpfCnpj", "mes", "categoria"))
                        if chave in vistas:
                            continue
                        vistas.add(chave)
                        notas.append({
                            "categoria": n.get("categoria", ""),
                            "mes": n.get("mes", ""),
                            "fornecedor": (n.get("fornecedor") or "").strip(),
                            "cnpj": (n.get("cpfCnpj") or "").strip(),
                            "nf": (n.get("documento") or "").strip(),
                            "data": _alems_parse_data(n.get("emissao", "")),
                            "valor": round(_alems_parse_valor(n.get("valor")), 2),
                            "urlPdf": n.get("comprovante", ""),
                        })
                    if not pag.get("hasMore"):
                        break
                    pagina += 1
                    time.sleep(0.2)
                soma = round(sum(n["valor"] for n in notas), 2)
                if total_portal is None or abs(soma - total_portal) < 0.01:
                    break
            if total_portal is not None and abs(round(sum(n["valor"] for n in notas), 2) - total_portal) >= 0.01:
                log(f"  ⚠️ {nome_dep}: soma das notas R$ {sum(n['valor'] for n in notas):,.2f} ≠ total do portal R$ {total_portal:,.2f}")
            notas.sort(key=lambda n: n["data"] or "", reverse=True)

            if not notas:
                continue

            por_categoria = {}
            for n in notas:
                por_categoria[n["categoria"]] = round(por_categoria.get(n["categoria"], 0) + n["valor"], 2)
            total_dep = round(sum(n["valor"] for n in notas), 2)
            resultados[nome_dep] = {"notas": notas, "categorias": por_categoria, "total": total_dep}
            total_geral += total_dep
            log(f"  [{i+1}/{len(linhas)}] {nome_dep}: {len(notas)} notas, R$ {total_dep:,.2f}")
        except Exception as e:
            log(f"  ⚠️ {nome_dep}: {e} — pulando")
            continue

    if not resultados:
        log("  ⚠️ Nenhum resultado da ALEMS — mantendo dados anteriores")
        return None

    log(f"  Total ALEMS {ANO}: R$ {total_geral:,.2f} — {len(resultados)} deputados com gastos")

    # Deputados sem despesas registradas no ano nem aparecem em /ceap/data —
    # mantém quem já estava no arquivo (nome_norm) para não sumir do ranking.
    gastos_por_nome_norm = {
        re.sub(r'^Dep\.?\s*', '', nome_dep, flags=re.I).strip(): gastos
        for nome_dep, gastos in resultados.items()
    }
    deps = []
    for nome_norm in {**deps_ant, **gastos_por_nome_norm}:
        ant = deps_ant.get(nome_norm, {})
        gastos = gastos_por_nome_norm.get(nome_norm)
        ant.pop("notasFiscais", None)  # campo da carga manual de jun/2026, substituído por "despesas"
        if gastos is None:
            deps.append(ant)
            continue
        cota_anual = (ant.get("verbaIndenizatoria") or {}).get(f"cotaAnual{ANO}")
        deps.append({
            **ant,
            "nome": ant.get("nome", nome_norm),
            "ultimaAtualizacao": hoje,
            "verbaIndenizatoria": {
                **ant.get("verbaIndenizatoria", {}),
                f"gastoPago{ANO}": gastos["total"],
                "categorias": gastos["categorias"],
                "periodoColetado": f"Jan–{mes_fim_periodo().capitalize()}/{ANO}",
                "percentualUsado": round(gastos["total"] / cota_anual * 100, 1) if cota_anual else None,
                "descricaoGeral": "CEAP — Cota do Exercício da Atividade Parlamentar (ALEMS).",
                "fonte": f"Portal da Transparência ALEMS — transparencia2.al.ms.gov.br/ceap — {hoje}",
            },
            "despesas": gastos["notas"],
            "totalNotasFiscais": len(gastos["notas"]),
        })

    data = {
        **dados_ant,
        "ano": ANO,
        "ultimaAtualizacao": hoje,
        "fonte": f"Despesas CEAP: Portal da Transparência ALEMS (transparencia2.al.ms.gov.br/ceap) — coleta automática {hoje}. Total geral {ANO}: R$ {total_geral:,.2f}.",
        "resumo": {
            **(dados_ant.get("resumo") or {}),
            "totalDeputados": len(deps),
            f"totalVerbaIndenizatoriaPaga{ANO}": round(total_geral, 2),
            "periodoColetado": f"Jan–{mes_fim_periodo().capitalize()}/{ANO}",
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
                "cotaGastaAno": round(recursos["totalCeaps"], 2) if recursos["totalCeaps"] else (ant.get("cotaGastaAno") if ant.get("anoReferencia") == recursos["ano"] else None),
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
    notas = carregar_notas_ceaps_senado(ANO)
    if notas is not None:
        salvar_notas_por_uf("ceaps_senado", ((s["id"], s.get("uf")) for s in senadores), notas,
                            "CEAPS — API de dados abertos do Senado (adm.senado.gov.br)")
    return senadores

# ============================================================
# 5. DEPUTADOS FEDERAIS BRASIL — lista completa 513
# ============================================================
def _preservar_ceap_se_vazio(ceap, ceap_anterior, nome=None):
    """A API da Câmara às vezes responde 200 com lista vazia (instabilidade do
    lado deles). Uma resposta vazia não pode apagar um CEAP já publicado: o
    gasto acumulado no ano nunca diminui para zero."""
    if ceap.get("cotaGastaAno") is None and ceap_anterior.get("cotaGastaAno") is not None:
        log(f"    CEAP vazio para {nome} — API sem notas, mantendo dado anterior")
        return ceap_anterior
    return ceap


def buscar_ceap_deputado_agregado(dep_id, ano):
    """Soma a CEAP de um deputado no ano pela API (reserva, quando o arquivo anual não baixa), paginando.
    A inversão de sinal da API é detectada sobre todas as despesas do deputado, não página a página."""
    itens_todos = despesas_api_por_mes(dep_id, ano, timeout=20)
    inv = api_invertida(itens_todos)
    total, categorias = 0.0, {}
    for item in itens_todos:
        tipo = item.get("tipoDespesa", "Outros")
        valor = _valor_api(item, inv)
        categorias[tipo] = categorias.get(tipo, 0) + valor
        total += valor
    notas = len(itens_todos)
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
        deputados = None
        log(f"  ⚠️ API Câmara indisponível: {e}")

    try:
        dados_ant = json.load(open(DADOS / "deputados_federais_brasil.json", encoding="utf-8"))
        ceap_ant = {d["id"]: d for d in dados_ant.get("deputados", [])}
    except:
        dados_ant, ceap_ant = {}, {}
    if not mesmo_ano(dados_ant):
        ceap_ant = {k: {kk: vv for kk, vv in v.items() if kk not in ("cotaGastaAno", "ceapCategorias", "totalNotasFiscais")}
                    for k, v in ceap_ant.items()}

    if not deputados:
        if not ceap_ant or carregar_ceap_bulk(ANO) is None:
            log("  ⚠️ Sem lista de deputados — mantendo dados anteriores")
            return None
        log("  Usando a lista de deputados da coleta anterior")
        deputados = [{"id": a["id"], "nome": a.get("nome"), "siglaPartido": a.get("partido"),
                      "siglaUf": a.get("uf"), "urlFoto": a.get("foto")} for a in ceap_ant.values()]

    log(f"  {len(deputados)} deputados federais em exercício")
    usa_bulk = carregar_ceap_bulk(ANO) is not None

    resultado = []
    for i, d in enumerate(deputados):
        if not usa_bulk:
            time.sleep(0.3)  # respeitar rate limit da API por deputado
        ant = ceap_ant.get(d["id"], {})
        ceap = ceap_do_deputado(d["id"], {
            "cotaGastaAno": ant.get("cotaGastaAno"),
            "ceapCategorias": ant.get("ceapCategorias", []),
            "totalNotasFiscais": ant.get("totalNotasFiscais", 0),
        }, d.get("nome"), incluir_notas=False)

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
    salvar_notas_por_uf("ceap_federal", ((d["id"], d["uf"]) for d in resultado),
                        {k: v["despesas"] for k, v in (carregar_ceap_bulk(ANO) or {}).items()},
                        "CEAP — arquivo completo da Câmara (camara.leg.br/cotas)")
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
            "alems": "transparencia2.al.ms.gov.br/ceap",
            "camaraCG": "dados manuais (portal sem API)",
        }
    }
    salvar("status.json", status)

# ============================================================
# 6. PREFEITURA DE CAMPO GRANDE — CSV de Despesas
# ============================================================
def _pref_baixar_sig(ano):
    """Exportação JSON da consulta de despesas do SIG-Transparência (dados do
    dia). O formulário é Laravel: GET para pegar _token + cookie, POST com
    download=json para o período do ano inteiro."""
    import re as _re
    base = "https://sig-transparencia.campogrande.ms.gov.br/despesas/consulta"
    s = requests.Session()
    s.headers.update({"User-Agent": "Mozilla/5.0 (CofreAbertoMS; transparencia publica)"})
    r = s.get(base, timeout=90)
    r.raise_for_status()
    m = _re.search(r'name="_token" value="([^"]+)"', r.text)
    if not m:
        raise RuntimeError("token do formulário não encontrado")
    fim = date.today() if ano == date.today().year else date(ano, 12, 31)
    r = s.post(base, timeout=600, data={
        "_token": m.group(1), "page": "1", "orderColumn": "dataempenho", "orderDirection": "DESC",
        "download": "json", "periodo-inicio": f"{ano}-01-01", "periodo-fim": fim.isoformat(),
        "orgao": "", "fornecedor": "", "cpf_cnpj": "", "categoria": "",
    })
    r.raise_for_status()
    linhas = r.json()
    if not isinstance(linhas, list) or not linhas:
        raise RuntimeError("exportação vazia")
    for x in linhas:  # normaliza para o formato do CSV de dados abertos
        d = str(x.get("dataempenho") or "")
        if _re.match(r"\d{2}/\d{2}/\d{4}$", d):
            x["dataempenho"] = f"{d[6:]}-{d[3:5]}-{d[:2]}"
        x.setdefault("itemclassificacaodespesaitemclassificacaodespesa", x.get("itemclassificacaodespesa"))
    return linhas


PREF_PAGOS_CACHE = DADOS / "prefeitura_pagos_cache.json"


def _pref_num(v):
    if isinstance(v, (int, float)):
        return float(v)
    t = str(v or "0").replace("R$", "").strip()
    if "," in t:
        t = t.replace(".", "").replace(",", ".")
    try:
        return float(t or 0)
    except ValueError:
        return 0.0


def _pref_atualizar_pagos(linhas, limite_seg=12 * 60, hilos=6):
    """A consulta/exportação do SIG congelou os valores pagos em 02/10/2026, mas a página de detalhe de cada empenho
    continua recebendo os pagamentos. Aqui lemos o detalhe dos empenhos com saldo a pagar (os nunca lidos primeiro,
    depois os lidos há mais tempo, os de maior saldo antes) e guardamos empenhado/liquidado/pago em cache."""
    import html as _html, re as _re, time as _time
    from concurrent.futures import ThreadPoolExecutor
    try:
        cache = json.load(open(PREF_PAGOS_CACHE, encoding="utf-8"))
    except Exception:
        cache = {}
    hoje_s = date.today().isoformat()
    ontem_s = (date.today() - timedelta(days=1)).isoformat()
    cand = []
    for x in linhas:
        k = f"{x.get('ano')}/{x.get('uge')}/{x.get('num')}"
        emp, pago = _pref_num(x.get("total_empenhado")), _pref_num(x.get("total_pago"))
        c = cache.get(k)
        if c and c.get("p", 0) >= c.get("e", 0) - 0.01:
            continue  # já quitado no detalhe
        if c and c.get("d", "") >= ontem_s:
            continue  # lido há menos de 2 dias
        if emp - max(pago, (c or {}).get("p", 0)) > 0.01:
            cand.append((c.get("d", "") if c else "", -(emp - pago), k))
    cand.sort()
    s = requests.Session()
    s.headers.update({"User-Agent": "Mozilla/5.0 (CofreAbertoMS; transparencia publica)"})
    t0 = _time.monotonic()

    def ler(k):
        if _time.monotonic() - t0 > limite_seg:
            return k, None
        for t in range(3):
            try:
                r = s.get(f"https://sig-transparencia.campogrande.ms.gov.br/despesas/detalhe/{k}", timeout=60)
                if r.status_code != 200:
                    _time.sleep(2)
                    continue
                txt = _re.sub(r"\s+", " ", _html.unescape(_re.sub(r"<[^>]+>", " ", _re.sub(r"<script.*?</script>", "", r.text, flags=_re.S))))
                m = _re.search(r"Saldo a Pagar \*\* ((?:R\$ [\d.,]+ ){9})", txt)
                if not m:
                    return k, None
                v = [_pref_num(z) for z in _re.findall(r"R\$ [\d.,]+", m.group(1))]
                return k, {"e": round(v[4], 2), "l": round(v[5], 2), "p": round(v[6], 2), "d": hoje_s}
            except Exception:
                _time.sleep(3)
        return k, None

    n = 0
    with ThreadPoolExecutor(hilos) as ex:
        for k, v in ex.map(ler, [k for _, _, k in cand]):
            if v:
                cache[k] = v
                n += 1
    PREF_PAGOS_CACHE.write_text(json.dumps(cache, separators=(",", ":")), encoding="utf-8")
    log(f"  detalhes de empenho: {n} lidos agora ({len(cand)} com saldo a pagar; {len(cache)} no cache)")
    return cache


def _pref_baixar_csv_dados_abertos(ano):
    """CSV de 'Despesas – Dados Abertos'. O link muda de pasta a cada upload
    (uploads/AAAA/MM/), então é lido da própria página em vez de fixo."""
    import csv, io, re as _re
    pag = get_com_retry("https://transparencia.campogrande.ms.gov.br/canais/despesas-dados-abertos/").text
    links = _re.findall(rf'href="(https://cdn\.campogrande\.ms\.gov\.br/[^"]*Consulta_de_Despesas__{ano}\.csv)"', pag)
    if not links:
        raise RuntimeError(f"link do CSV {ano} não encontrado na página de dados abertos")
    r = get_com_retry(links[0])
    return list(csv.DictReader(io.StringIO(r.content.decode("utf-8-sig", errors="replace")), delimiter=";"))


def coletar_prefeitura():
    log("Coletando despesas da Prefeitura de CG...")
    ano = ANO
    fonte = None
    try:
        linhas = _pref_baixar_sig(ano)
        fonte = "SIG-Transparência da Prefeitura (sig-transparencia.campogrande.ms.gov.br/despesas) — exportação do dia"
        log(f"  {len(linhas)} empenhos na consulta online (SIG-Transparência)")
    except Exception as e:
        log(f"  ⚠️ Consulta online indisponível: {e} — tentando o CSV de dados abertos")
        try:
            linhas = _pref_baixar_csv_dados_abertos(ano)
            fonte = "Dados Abertos da Prefeitura (transparencia.campogrande.ms.gov.br) — CSV de despesas"
            log(f"  {len(linhas)} linhas no CSV de dados abertos")
        except Exception as e2:
            log(f"  ⚠️ Prefeitura indisponível: {e2} — mantendo dados anteriores")
            return None

    def parse_valor(valor_str):
        v = str(valor_str or "0").strip().replace("R$", "").strip()
        if "," in v:
            v = v.replace(".", "").replace(",", ".")
        return float(v or 0)

    try:
        dados_ant = json.load(open(DADOS / "prefeitura.json", encoding="utf-8"))
    except:
        dados_ant = {}

    try:
        pagos = _pref_atualizar_pagos(linhas) if fonte and fonte.startswith("SIG") else {}
    except Exception as e:
        log(f"  ⚠️ detalhes de empenho: {e}")
        pagos = {}
    por_secretaria = {}
    total_geral = total_empenhado = total_liquidado = 0.0
    despesas = []
    for row in linhas:
        try:
            # A exportação do SIG traz em "orgao" nomes antigos/trocados (ex.: "FUNDO MUNICIPAL
            # DO IDOSO" em empenhos da FUNDAC, "GABINETE DO PREFEITO" na Casa Civil); a
            # unidade gestora é a que de fato fez a despesa — e é a que aparece no detalhe.
            secretaria = (row.get("nomeunidadegestora") or row.get("orgao") or "Outros").strip()
            valor = parse_valor(row.get("total_pago"))
            empenhado = parse_valor(row.get("total_empenhado"))
            liquidado = parse_valor(row.get("total_liquidado"))
            c_ = pagos.get(f"{row.get('ano')}/{row.get('uge')}/{row.get('num')}")
            if c_ and c_.get("p", 0) > valor:  # a página de detalhe tem pagamentos que a exportação ainda não mostra
                valor, liquidado, empenhado = c_["p"], max(liquidado, c_.get("l", 0)), c_.get("e", empenhado) or empenhado
            por_secretaria[secretaria] = por_secretaria.get(secretaria, 0) + valor
            total_geral += valor
            total_empenhado += empenhado
            total_liquidado += liquidado
            if valor > 0:
                ano_row = str(row.get("ano") or "").strip()
                uge = str(row.get("uge") or "").strip()
                num = str(row.get("num") or "").strip()
                item = {
                    "data": row.get("dataempenho"),
                    "orgao": secretaria,
                    "categoria": (row.get("itemclassificacaodespesaitemclassificacaodespesa") or "").strip(),
                    "fornecedor": (row.get("nomefornecedor") or "").strip(),
                    "cnpj": str(row.get("cnpjfornecedor") or "").strip(),
                    "valor": round(valor, 2),
                    "empenhado": round(empenhado, 2),
                    "urlDetalhe": f"https://sig-transparencia.campogrande.ms.gov.br/despesas/detalhe/{ano_row}/{uge}/{num}"
                        if ano_row and uge and num else None,
                }
                if row.get("modalidadelicitacao"):
                    item["modalidade"] = row["modalidadelicitacao"].strip()
                if str(row.get("processoorigem") or "").strip():
                    item["processo"] = str(row["processoorigem"]).strip()
                despesas.append(item)
        except Exception:
            continue

    # Não regride: se a fonte trouxer menos pago que o já publicado (no MESMO ano), mantém
    if dados_ant.get("ano") == ano and total_geral < (dados_ant.get("totalDespesas") or 0) * 0.98:
        log(f"  ⚠️ Total pago caiu (R$ {total_geral:,.2f} < R$ {dados_ant.get('totalDespesas'):,.2f}) — mantendo dados anteriores")
        return None

    despesas.sort(key=lambda x: x["data"] or "", reverse=True)
    data = {
        **dados_ant,
        "ultimaAtualizacao": hoje,
        "ano": ano,
        "totalDespesas": round(total_geral, 2),
        "totalEmpenhado": round(total_empenhado, 2),
        "totalLiquidado": round(total_liquidado, 2),
        "ultimoEmpenho": max((str(r.get("dataempenho") or "") for r in linhas), default=None),
        "fonte": f"{fonte} — {hoje}",
        "porSecretaria": {k: round(v, 2) for k, v in sorted(por_secretaria.items(), key=lambda x: -x[1])[:20]},
        "totalLinhas": len(linhas),
        "totalNotasFiscais": len(despesas),
        "despesas": despesas,
    }
    # compacto (sem indentação): ~12 mil empenhos, o arquivo cai de ~5 MB para ~3 MB
    with open(DADOS / "prefeitura.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    log(f"✅ prefeitura.json salvo ({(DADOS / 'prefeitura.json').stat().st_size // 1024}KB)")
    log(f"  Total pago {ano}: R$ {total_geral:,.2f} — {len(despesas)} empenhos com valor pago")
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

    api_key = limite_cgu.chave()
    if not api_key:
        log("  ⚠️ PORTAL_TRANSPARENCIA_API_KEY não configurada — pulando emendas pela API (o arquivo de download continua)")
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


def _fiorilli_chave_nome(nome):
    """Chave de comparação sem acento/case — a folha de pagamento e as diárias
    às vezes grafam o mesmo vereador de forma diferente (ex: com ou sem acento),
    o que sem isso cria dois registros pra mesma pessoa."""
    import unicodedata
    texto = unicodedata.normalize("NFKD", nome.upper()).encode("ascii", "ignore").decode()
    return " ".join(texto.split())


def _fiorilli_tem_acento(nome):
    import unicodedata
    return any(unicodedata.combining(c) for c in unicodedata.normalize("NFKD", nome))


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
    {
        "cidade": "Itaporã",
        # O endereço antigo (itaporams.ddns.net:5656) saiu do ar em jul/2026; este é o
        # link publicado no site da Câmara, que voltou a responder em 11/11/2026.
        "urlBase": "https://transparencia.itapora.ms.gov.br/Transparenciacm",
        "empresa": "9",
        "paramAno": "Ano",
        "temServidores": True,
        "portalOficial": "https://camaraitapora.ms.gov.br/",
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
                registros = get_com_retry(url, tentativas=3).json()
                if registros:
                    for reg in registros:
                        if not (reg.get("CARGO") or "").strip().upper().startswith("VEREADOR"):
                            continue
                        nome = (reg.get("NOME") or "").strip()
                        if not nome:
                            continue
                        chave = _fiorilli_chave_nome(nome)
                        vereadores.setdefault(chave, {"nome": nome, "cargo": "Vereador(a)"})
                        if _fiorilli_tem_acento(nome) and not _fiorilli_tem_acento(vereadores[chave]["nome"]):
                            vereadores[chave]["nome"] = nome
                        vereadores[chave]["subsidioMensal"] = round(_fiorilli_parse_valor(reg.get("PROVENTOS")), 2)
                        vereadores[chave]["descontos"] = round(_fiorilli_parse_valor(reg.get("DESCONTOS")), 2)
                        vereadores[chave]["referenciaFolha"] = reg.get("REFERENCIA_NOME")
                    break
            except Exception as e:
                log(f"  ⚠️ Servidores ({mes_tentado:02d}/{ANO}) indisponível para {cfg['cidade']}: {e}")
                break  # erro real (ex.: 500) não adianta tentar outro mês

    try:
        url = (f"{base}/VersaoJson/Despesas/?Listagem=Diarias&DiaInicioPeriodo=01&MesInicialPeriodo=01"
               f"&DiaFinalPeriodo=31&MesFinalPeriodo=12&{param_ano}={ANO}{conectar}"
               f"&Empresa={empresa}&MostraDadosConsolidado=False")
        diarias = get_com_retry(url, tentativas=3).json()
        for d in diarias:
            nome = (d.get("FAVORECIDO") or "").strip()
            if not nome:
                continue
            chave = _fiorilli_chave_nome(nome)
            cargo_cru = (d.get("CARGO") or "").strip().upper()
            # Em algumas instalações (ex.: Itaporã) o campo CARGO vem vazio nas
            # diárias — só é confiável na folha/Servidores. Nesses casos, só
            # inclui quem já foi identificado como vereador ali.
            if not cargo_cru.startswith("VEREADOR") and chave not in vereadores:
                continue
            vereadores.setdefault(chave, {"nome": nome, "cargo": "Vereador(a)"})
            if _fiorilli_tem_acento(nome) and not _fiorilli_tem_acento(vereadores[chave]["nome"]):
                vereadores[chave]["nome"] = nome
            v = vereadores[chave]
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
        registros = get_com_retry(url, tentativas=3).json()
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
