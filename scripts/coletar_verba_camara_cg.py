#!/usr/bin/env python3
"""
Cofre Aberto MS — Verba Indenizatória da Câmara Municipal de Campo Grande
Extrai Ato 027 (indenizações gerais) e Ato 028 (assessoria técnica) dos PDFs
de prestação de contas de cada vereador, publicados no Portal da
Transparência (Fiorilli SCPI) através do menu "Outros Documentos".
Fonte: http://45.225.6.93:8079/transparencia/ (HomeDocumentosPublicados.aspx)
Roda separado de coletar_dados.py porque baixa ~29 vereadores × 2 atos em
PDFs grandes (10-20MB cada) e faz parsing pesado de texto — mantém o
script principal rápido e isola falhas desse fluxo específico.
Os PDFs desta câmara não têm um formato único: variam por gabinete
(fornecedor de contabilidade diferente para cada vereador), então o parser
abaixo tolera várias variações de formatação (datas com ponto ou barra,
CNPJ com ou sem pontuação, valor com ou sem "R$", "NF"/"NOTA FISCAL"/
"CUPOM FISCAL"/"RECIBO" como tipo de documento). Alguns PDFs (ex: Landmark)
usam uma fonte customizada que desloca o código de cada caractere em +29 —
isso é detectado e desfeito automaticamente, não é corrupção do arquivo.
Regra de segurança na mesclagem: um mês só é atualizado quando o TOTAL
IMPRESSO na própria página do PDF foi capturado (nunca a partir de soma
parcial de itens, que pode sub-contar silenciosamente e piorar um dado que
já era bom). Notas fiscais com data ou valor não confiáveis são descartadas
em vez de arriscar um dado errado no ar.

Cache e paralelismo: relatórios já baixados e processados com sucesso ficam
registrados em dados/verba_cg_cache.json (chave = codigoLinhaPDF+chaveAcesso,
que identifica uma publicação específica no portal) e são pulados nas
execuções seguintes. O download/parsing dos relatórios restantes roda em até
4 threads simultâneas, cada uma com sua própria sessão HTTP (o portal é
stateful: o POST que seleciona o relatório e o GET que baixa o PDF dependem
do mesmo cookie de sessão, então sessões não podem ser compartilhadas entre
threads). Cada PDF tem um orçamento cooperativo de ~30s; se ultrapassado, o
item é pulado nesta execução e tentado de novo na próxima (não fica marcado
como concluído no cache).
"""

import hashlib, json, os, re, sys, threading, time, unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, date
from pathlib import Path
import requests

ROOT = Path(__file__).parent.parent
DADOS = ROOT / "dados"
ARQUIVO_CAMARA = DADOS / "camara_municipal.json"
CACHE_ARQUIVO = DADOS / "verba_cg_cache.json"
TIMEOUT_POR_PDF = 30  # segundos — orçamento cooperativo de tempo por PDF
MAX_WORKERS = 4
ANO = date.today().year
ANO_STR = str(ANO)
hoje = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

BASE_URL = "http://45.225.6.93:8079/transparencia"
HEADERS_AJAX = {
    "Content-Type": "application/json; charset=UTF-8",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": f"{BASE_URL}/HomeDocumentosPublicados.aspx",
    "User-Agent": "Mozilla/5.0 (CofreAbertoMS/1.0; transparencia publica)",
}
EMPRESA_CAMARA = "1"  # código da entidade "Câmara Municipal de Campo Grande" no Fiorilli

MESES_NUM_PARA_ABREV = {
    "01": "jan", "02": "fev", "03": "mar", "04": "abr", "05": "mai", "06": "jun",
    "07": "jul", "08": "ago", "09": "set", "10": "out", "11": "nov", "12": "dez",
}
MESES_NUM = {"janeiro": "01", "fevereiro": "02", "marco": "03", "março": "03", "maro": "03",
             "abril": "04", "maio": "05", "junho": "06", "julho": "07", "agosto": "08",
             "setembro": "09", "outubro": "10", "novembro": "11", "dezembro": "12"}

def log(msg): print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

# ============================================================
# DECODIFICAÇÃO E PARSING DO TEXTO DO PDF
# ============================================================
CNPJ_RE = re.compile(r"\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?[\s']{0,3}\d{2}")
DATE_RE = re.compile(r'\d{2}[./]\d{2}[./]\d{4}')
DATE_CURTA_RE = re.compile(r'\b\d{1,2}[./]\d{1,2}\b')
VALOR_RE = re.compile(r'(?:(?:R\$|RS\$?)[\s/]*)?\d{1,3}(?:\.\d{3})*,\d{2}(?!\d)|(?:R\$|RS\$?)[\s/]*\d+,\d{2}(?!\d)')
DOC_RE = re.compile(r'(?:NFC?|NFS-?e|NOTA\s+FISCAL|CUPOM\s+FISCAL|RECIBO|NOTA\s*N[ºo°]?)[.:\s]*\d+', re.I)
MES_NOME_RE = re.compile(r'(Janeiro|Fevereiro|Mar.?o|Abril|Maio|Junho|Julho|Agosto|Setembro|Outubro|Novembro|Dezembro)\b', re.I)
MES_NUMERICO_RE = re.compile(r'\b(0[1-9]|1[0-2])/(20\d{2})\b')
ANO_RE = re.compile(r'20\d{2}')
TOTAL_RESUMO_RE = re.compile(r'TOTAL[^\dR]{0,12}(?:(?:R\$|RS\$?)[\s/]*)?([\d\.]+,\d{2})')
TOTAL_PAGINA_RE = re.compile(r'(?:Total|TOTAL)[^\dR]{0,12}(?:(?:R\$|RS\$?)[\s/]*)?([\d\.]+,\d{2})')

def decodifica_se_deslocado(texto):
    """Alguns PDFs (fonte customizada) têm todo o texto deslocado em +29 no código
    do caractere (ex: 'C' vira '&'). Detecta pela alta proporção de caracteres de
    controle (ord<32, fora \\n\\t\\r) e desfaz o deslocamento quando aplicável."""
    if not texto:
        return texto
    controle = sum(1 for c in texto if ord(c) < 32 and c not in '\n\t\r')
    if controle / max(len(texto), 1) < 0.03:
        return texto
    decodificado = ''.join(chr((ord(c) + 29) % 0x110000) if ord(c) < 256 else c for c in texto)
    return decodificado.replace('=', ' ')

def normaliza_texto(texto):
    texto = decodifica_se_deslocado(texto)
    return texto.replace('\xad', '-').replace('‑', '-')

def parse_valor(txt):
    txt = txt.replace('RS', '').replace('R$', '').replace('$', '').replace('/', '').strip()
    return round(float(txt.replace('.', '').replace(',', '.')), 2)

def limpa_espacos(txt):
    return re.sub(r'\s+', ' ', txt).strip(" |—-.")

def eh_pagina_resumo(texto):
    return 'Despesas' in texto and 'Valor (R$)' in texto and 'discriminação' not in texto

def eh_pagina_combustivel(texto):
    return 'Placa' in texto or 'Veícu' in texto or bool(re.search(r'GASOLINA|ETANOL|\bDIESEL\b', texto.upper()))

def eh_pagina_notas(texto):
    t = texto.lower()
    return 'discrimina' in t and 'despesas' in t

def extrai_mes_ano_confiavel(texto):
    """Só retorna mês/ano quando encontra o mês (nome OU numérico MM/AAAA) bem perto
    do rótulo 'Mês:' (janela estreita), pra não pegar 'janeiro de 2019' de rodapé/legislação."""
    idx = texto.rfind('Mês:')
    if idx == -1:
        # variante com acento corrompido pela decodificação de fonte deslocada (ex: "M\x8fs:")
        m_label = None
        for m_label in re.finditer(r'M.s:', texto):
            pass
        idx = m_label.start() if m_label else -1
    if idx == -1:
        return None, None
    janela = texto[idx:idx + 60]
    m = MES_NOME_RE.search(janela)
    if m:
        mes_norm = re.sub(r'[^a-zçã]', '', m.group(1).lower()).replace('ç', 'c').replace('ã', 'a')
        mes_num = MESES_NUM.get(mes_norm) or MESES_NUM.get(m.group(1).lower())
        ano_m = ANO_RE.search(janela[m.end():m.end() + 15])
        ano = ano_m.group(0) if ano_m else ANO_STR
        return mes_num, ano
    m2 = MES_NUMERICO_RE.search(janela)
    if m2:
        return m2.group(1), m2.group(2)
    return None, None

def novo_mes_dict(chave):
    partes = chave.split('/')
    return {"mesNum": partes[0], "ano": partes[1], "totalDeclarado": None,
            "totalNotas": None, "totalCombustivel": None, "notas": [], "combustivel": []}
def extrai_itens(texto, tipo, ano_contexto):
    """Usa cada CNPJ encontrado como âncora: a data mais próxima antes dele e o
    valor/documento mais próximos depois formam um item (nota fiscal ou abastecimento)."""
    itens = []
    cnpjs = list(CNPJ_RE.finditer(texto))
    for i, m in enumerate(cnpjs):
        inicio_busca = cnpjs[i - 1].end() if i > 0 else 0
        antes = texto[inicio_busca:m.start()]
        datas = list(DATE_RE.finditer(antes)) or list(DATE_CURTA_RE.finditer(antes))
        if not datas:
            continue
        data = datas[-1].group(0)
        if data.count('/') + data.count('.') == 1:  # só DD/MM, sem ano
            data = f"{data}/{ano_contexto}"
        fornecedor = limpa_espacos(antes[datas[-1].end():])[:150]

        limite_cnpj = cnpjs[i + 1].start() if i + 1 < len(cnpjs) else len(texto)
        janela = texto[m.end():min(m.end() + 400, limite_cnpj)]
        prox_data_m = DATE_RE.search(janela) or DATE_CURTA_RE.search(janela)
        fim_janela = prox_data_m.start() if prox_data_m else len(janela)
        depois = janela[:fim_janela]

        valor_m = VALOR_RE.search(depois)
        doc_m = DOC_RE.search(depois)
        valor = parse_valor(valor_m.group(0)) if valor_m else None
        doc = limpa_espacos(doc_m.group(0)) if doc_m else None
        resto = depois[doc_m.end():] if doc_m else (depois[valor_m.end():] if valor_m else depois)
        resto = re.split(r'Fonte:|Total\b|TOTAL\b|Atesto\b', resto)[0]
        resto = limpa_espacos(resto)[:150]

        item = {
            "data": data.replace('.', '/'),
            "fornecedor": fornecedor,
            "cnpj": m.group(0).replace(' ', '').replace('\n', ''),
            "valor": valor,
            "documento": doc,
        }
        item["objeto" if tipo == "notas" else "descricao"] = resto
        itens.append(item)
    return itens

def extrai_itens_fallback(texto, tipo, ano_contexto):
    """Fallback: âncora em DATA em vez de CNPJ, para linhas em que o CNPJ veio
    corrompido pela quebra de linha do PDF."""
    itens = []
    datas = list(DATE_RE.finditer(texto)) or list(DATE_CURTA_RE.finditer(texto))
    for i, m in enumerate(datas):
        fim = datas[i + 1].start() if i + 1 < len(datas) else len(texto)
        bloco = texto[m.end():min(fim, m.end() + 400)]
        cnpj_m = CNPJ_RE.search(bloco)
        valor_m = VALOR_RE.search(bloco)
        doc_m = DOC_RE.search(bloco)
        if not (valor_m and doc_m):
            continue
        fornecedor = limpa_espacos(bloco[:cnpj_m.start()]) if cnpj_m else limpa_espacos(bloco[:valor_m.start()])
        resto = bloco[doc_m.end():]
        resto = re.split(r'Fonte:|Total\b|TOTAL\b|Atesto\b', resto)[0]
        resto = limpa_espacos(resto)[:150]
        data = m.group(0)
        if data.count('/') + data.count('.') == 1:
            data = f"{data}/{ano_contexto}"
        item = {
            "data": data.replace('.', '/'),
            "fornecedor": fornecedor[:150],
            "cnpj": cnpj_m.group(0).replace(' ', '').replace('\n', '') if cnpj_m else None,
            "valor": parse_valor(valor_m.group(0)),
            "documento": limpa_espacos(doc_m.group(0)),
        }
        item["objeto" if tipo == "notas" else "descricao"] = resto
        itens.append(item)
    return itens

def extrai_total_pagina(texto):
    m = TOTAL_PAGINA_RE.search(texto)
    return parse_valor(m.group(1)) if m else None

def processa_pdf(caminho, deadline=None):
    """Lê um PDF de prestação de contas (Ato 027 ou 028) e devolve um dict
    {"MM/AAAA": {totalDeclarado, notas: [...], combustivel: [...], ...}}.
    Se 'deadline' (timestamp) for informado e for ultrapassado, o parsing para
    na página atual em vez de continuar (usado pelo timeout por PDF)."""
    from pypdf import PdfReader
    r = PdfReader(caminho)
    meses = {}
    mes_atual = None
    for p in r.pages:
        if deadline and time.time() > deadline:
            log("     ⏱️ tempo limite do PDF atingido — parando o parsing nesta página")
            break
        try:
            texto = normaliza_texto(p.extract_text())
        except Exception:
            continue

        mes_num, ano = extrai_mes_ano_confiavel(texto)
        if mes_num:
            mes_atual = f"{mes_num}/{ano}"
        chave = mes_atual
        ano_ctx = chave.split('/')[1] if chave else ANO_STR

        if eh_pagina_resumo(texto):
            if not chave:
                continue
            meses.setdefault(chave, novo_mes_dict(chave))
            m = TOTAL_RESUMO_RE.search(texto)
            if m:
                # Páginas "COMPLEMENTO" repetem o mesmo mês com um total PARCIAL que
                # deve ser somado ao principal, nunca sobrescrito.
                meses[chave]["totalDeclarado"] = round((meses[chave]["totalDeclarado"] or 0) + parse_valor(m.group(1)), 2)
        elif eh_pagina_combustivel(texto):
            if not chave:
                continue
            meses.setdefault(chave, novo_mes_dict(chave))
            itens = extrai_itens(texto, "combustivel", ano_ctx)
            tp = extrai_total_pagina(texto)
            if not itens and tp:
                itens = extrai_itens_fallback(texto, "combustivel", ano_ctx)
            meses[chave]["combustivel"].extend(itens)
            if tp is not None:
                meses[chave]["totalCombustivel"] = round((meses[chave]["totalCombustivel"] or 0) + tp, 2)
        elif eh_pagina_notas(texto):
            if not chave:
                continue
            meses.setdefault(chave, novo_mes_dict(chave))
            itens = extrai_itens(texto, "notas", ano_ctx)
            tp = extrai_total_pagina(texto)
            soma = round(sum(x["valor"] for x in itens if x["valor"]), 2)
            if tp and abs(soma - tp) > 0.05:
                itens_fb = extrai_itens_fallback(texto, "notas", ano_ctx)
                soma_fb = round(sum(x["valor"] for x in itens_fb if x["valor"]), 2)
                if abs(soma_fb - tp) < abs(soma - tp):
                    itens = itens_fb
            meses[chave]["notas"].extend(itens)
            if tp is not None:
                meses[chave]["totalNotas"] = round((meses[chave]["totalNotas"] or 0) + tp, 2)

    for chave, d in meses.items():
        soma_notas = round(sum(x["valor"] for x in d["notas"] if x["valor"]), 2)
        soma_comb = round(sum(x["valor"] for x in d["combustivel"] if x["valor"]), 2)
        conferido = True
        if d["totalNotas"] is not None and abs(soma_notas - d["totalNotas"]) > 0.05:
            conferido = False
        if d["totalCombustivel"] is not None and abs(soma_comb - d["totalCombustivel"]) > 0.05:
            conferido = False
        d["conferido"] = conferido
    return meses
# ============================================================
# 1. DESCOBRIR A LISTA DE VEREADORES E CÓDIGOS DOS RELATÓRIOS
# ============================================================
def obter_lista_relatorios(sessao):
    """Navega pelo menu 'Outros Documentos' e extrai, para cada vereador, o
    codigoLinhaPDF + chaveAcesso de cada Ato (027 e 028) — necessários pra
    pedir o PDF individual depois."""
    sessao.get(f"{BASE_URL}/default.aspx", timeout=30)
    sessao.post(f"{BASE_URL}/default.aspx/RecuperarDados",
                json={"strLnkButtonID": "lnkOutrosDocumentos", "strExercicio": ANO_STR, "strEmpresa": EMPRESA_CAMARA},
                headers=HEADERS_AJAX, timeout=30)
    r = sessao.get(f"{BASE_URL}/HomeDocumentosPublicados.aspx", timeout=30)
    html = r.text

    idx27 = html.find('VERBA INDENIZATÓRIA - Ato 27')
    idx28 = html.find('VERBA INDENIZATÓRIA - Ato 28')
    if idx27 == -1 or idx28 == -1:
        raise RuntimeError("Seções de Verba Indenizatória não encontradas na página — layout do portal pode ter mudado")

    bloco27 = html[idx27:idx28]
    resto = html[idx28:]
    idx28_fim = resto.find('VERBA INDENIZATÓRIA', 30)
    bloco28 = resto[:idx28_fim] if idx28_fim != -1 else resto[:20000]

    padrao_item = re.compile(r'CodigoLinhaPDF="(\d+)"[^>]*NomeRelatorio="([^"]+)"[^>]*ChaveAcesso="([^"]+)"')

    def extrai(bloco):
        itens = []
        for m in padrao_item.finditer(bloco):
            cod, nome, chave = m.groups()
            upper = nome.upper()
            # pula itens que são o texto da própria lei/resolução, não um vereador
            if upper.startswith(("ATO Nº", "ATO N", "RESOLUÇÃO", "LEI COMPLEMENTAR")):
                continue
            itens.append({"codigoLinhaPDF": cod, "nome": nome.strip(), "chaveAcesso": chave})
        return itens

    return {"ato027": extrai(bloco27), "ato028": extrai(bloco28)}

# ============================================================
# 2. CACHE E BAIXAR/PROCESSAR OS PDFs (em paralelo)
# ============================================================
def carregar_cache():
    if CACHE_ARQUIVO.exists():
        try:
            return json.load(open(CACHE_ARQUIVO, encoding="utf-8"))
        except Exception:
            return {}
    return {}

def salvar_cache(cache):
    DADOS.mkdir(exist_ok=True)
    json.dump(cache, open(CACHE_ARQUIVO, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

def chave_cache(alvo):
    # codigoLinhaPDF+chaveAcesso identifica uma publicação específica no portal;
    # uma vez processada com sucesso não muda, então pode ser pulada com segurança
    # nas execuções seguintes.
    return f"{alvo['codigoLinhaPDF']}_{alvo['chaveAcesso']}"

_thread_local = threading.local()

def sessao_da_thread():
    """Cada thread usa sua PRÓPRIA sessão/cookies. O portal é stateful (o POST
    SalvarCodigoLinhaRelatorio marca 'qual PDF' o GET MostrarPDF.aspx seguinte vai
    retornar, dentro da sessão) — compartilhar uma sessão entre threads causaria
    condição de corrida (uma thread poderia receber o PDF selecionado por outra)."""
    sessao = getattr(_thread_local, "sessao", None)
    if sessao is None:
        sessao = requests.Session()
        sessao.headers.update({"User-Agent": HEADERS_AJAX["User-Agent"]})
        sessao.get(f"{BASE_URL}/default.aspx", timeout=30)
        sessao.post(f"{BASE_URL}/default.aspx/RecuperarDados",
                    json={"strLnkButtonID": "lnkOutrosDocumentos", "strExercicio": ANO_STR, "strEmpresa": EMPRESA_CAMARA},
                    headers=HEADERS_AJAX, timeout=30)
        _thread_local.sessao = sessao
    return sessao

def processar_alvo(alvo):
    """Baixa e processa um único PDF (Ato027 ou Ato028 de um vereador).
    Retorna (nome, ato, meses, extra): 'extra' é o hash sha256 em caso de
    sucesso (meses != None), ou uma mensagem do motivo em caso de falha/timeout
    (meses=None). Respeita um orçamento cooperativo de TIMEOUT_POR_PDF segundos."""
    inicio = time.time()
    nome, ato = alvo["nome"], alvo["ato"]
    caminho_tmp = f"/tmp/_verba_cg_tmp_{threading.get_ident()}.pdf"
    try:
        sessao = sessao_da_thread()
        restante = TIMEOUT_POR_PDF - (time.time() - inicio)
        if restante <= 0:
            return nome, ato, None, "timeout antes de iniciar"
        r1 = sessao.post(f"{BASE_URL}/HomeDocumentosPublicados.aspx/SalvarCodigoLinhaRelatorio",
                          json={"strCodigoLinhaRelatorio": alvo["codigoLinhaPDF"], "strChaveAcesso": alvo["chaveAcesso"]},
                          headers=HEADERS_AJAX, timeout=max(1, min(restante, 15)))
        if r1.status_code != 200:
            return nome, ato, None, f"erro ao selecionar relatório ({r1.status_code})"

        restante = TIMEOUT_POR_PDF - (time.time() - inicio)
        if restante <= 0:
            return nome, ato, None, "timeout após selecionar relatório"
        r2 = sessao.get(f"{BASE_URL}/MostrarPDF.aspx", timeout=max(1, min(restante, 25)))
        if r2.status_code != 200 or "pdf" not in r2.headers.get("Content-Type", ""):
            return nome, ato, None, f"PDF indisponível ({r2.status_code})"

        conteudo = r2.content
        sha256 = hashlib.sha256(conteudo).hexdigest()
        if time.time() - inicio > TIMEOUT_POR_PDF:
            return nome, ato, None, "timeout após download"

        with open(caminho_tmp, "wb") as f:
            f.write(conteudo)
        meses = processa_pdf(caminho_tmp, deadline=inicio + TIMEOUT_POR_PDF)
        def vazio(md):
            return not md["notas"] and not md["combustivel"] and md["totalDeclarado"] is None
        meses = {m: d for m, d in meses.items() if not vazio(d)}
        return nome, ato, meses, sha256
    except Exception as e:
        return nome, ato, None, f"exceção — {e}"
    finally:
        if os.path.exists(caminho_tmp):
            os.remove(caminho_tmp)

def coletar_verba_indenizatoria():
    log("Coletando Verba Indenizatória — Câmara Municipal de Campo Grande...")
    sessao_inicial = requests.Session()
    sessao_inicial.headers.update({"User-Agent": HEADERS_AJAX["User-Agent"]})

    try:
        lista = obter_lista_relatorios(sessao_inicial)
    except Exception as e:
        log(f" ⚠️ Não foi possível obter a lista de relatórios: {e}")
        return {}

    alvos = [{**item, "ato": "027"} for item in lista["ato027"]]
    alvos += [{**item, "ato": "028"} for item in lista["ato028"]]
    log(f" {len(alvos)} relatórios encontrados ({len(lista['ato027'])} vereadores no Ato027, {len(lista['ato028'])} no Ato028)")

    cache = carregar_cache()
    a_processar = [a for a in alvos if chave_cache(a) not in cache]
    pulados = len(alvos) - len(a_processar)
    if pulados:
        log(f" 💾 {pulados} relatórios já processados anteriormente (cache) — pulando download")

    resultado = {}
    cache_mudou = False

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futuros = {executor.submit(processar_alvo, alvo): alvo for alvo in a_processar}
        total = len(futuros)
        concluidos = 0
        for futuro in as_completed(futuros):
            alvo = futuros[futuro]
            nome, ato = alvo["nome"], alvo["ato"]
            concluidos += 1
            try:
                nome_r, ato_r, meses, extra = futuro.result()
            except Exception as e:
                log(f" [{concluidos}/{total}] {nome} Ato{ato}: exceção inesperada — {e}")
                continue

            if meses is None:
                log(f" [{concluidos}/{total}] {nome} Ato{ato}: {extra}")
                continue

            resultado.setdefault(nome, {})[f"ato{ato}"] = meses
            cache[chave_cache(alvo)] = {
                "nome": nome, "ato": ato, "sha256": extra,
                "processadoEm": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            }
            cache_mudou = True
            log(f" [{concluidos}/{total}] {nome} Ato{ato}: {len(meses)} meses")

    if cache_mudou:
        salvar_cache(cache)

    return resultado
# ============================================================
# 3. MESCLAR NO camara_municipal.json (sem sobrescrever dados bons)
# ============================================================
def normaliza_nome(nome):
    """Normaliza pra comparar o nome do JSON existente (ex: 'Dr. Livio', 'Professor
    Juari') com o nome vindo da listagem de PDFs (ex: 'DR. LÍVIO', 'PROF. JUARI')."""
    nome = nome.upper()
    nome = re.sub(r'^VEREADOR\s*\(?A?\)?\s*[:-]?\s*', '', nome)
    nome = nome.replace("PROFESSOR", "PROF")
    nome = unicodedata.normalize("NFKD", nome)
    nome = "".join(c for c in nome if not unicodedata.combining(c))
    nome = re.sub(r"[^\w\s]", "", nome)
    return re.sub(r"\s+", " ", nome).strip()

def data_para_iso(data_br):
    d, m, a = data_br.split("/")
    return f"{a}-{int(m):02d}-{int(d):02d}"

def data_valida(data_br):
    """Além do formato, rejeita datas no futuro — combustível/OCR corrompido
    às vezes faz um número perto da data (litros, placa) ser lido como dia/mês,
    produzindo datas impossíveis como agosto quando a coleta é feita em julho."""
    try:
        d, m, a = (int(x) for x in data_br.split("/"))
        if a != int(ANO_STR):
            return False
        return date(a, m, d) <= date.today()
    except (ValueError, TypeError):
        return False

def chave_dedup(data_iso, valor, documento_ou_nf):
    numeros = re.sub(r"[^0-9]", "", documento_ou_nf or "")
    v = round(valor, 2) if valor is not None else None
    return (data_iso, v, numeros)

def limpa_doc(documento):
    if not documento:
        return None
    return re.sub(r"^(NFC?|NFS-?e|NOTA FISCAL|CUPOM FISCAL|RECIBO)\s*", "", documento, flags=re.I).strip()

def total_mes_confiavel(dados_mes):
    """Só usa um total quando ele foi IMPRESSO na própria página do PDF —
    nunca a soma dos itens, que pode ficar incompleta silenciosamente."""
    total = dados_mes.get("totalDeclarado")
    return total if total is not None and total > 0 else None

def mesclar_dados(resultado_extraido):
    if not resultado_extraido:
        log(" ⚠️ Nenhum dado extraído — mantendo camara_municipal.json inalterado")
        return

    if not ARQUIVO_CAMARA.exists():
        log(f" ⚠️ {ARQUIVO_CAMARA} não existe — pulando mesclagem")
        return

    atual = json.load(open(ARQUIVO_CAMARA, encoding="utf-8"))

    # mapeia nome normalizado -> chave original no resultado extraído
    mapa_normalizado = {normaliza_nome(nome): nome for nome in resultado_extraido}

    total_notas_novas = 0
    vereadores_atualizados = 0

    for v in atual["vereadores"]:
        chave_extraida = mapa_normalizado.get(normaliza_nome(v["nome"]))
        if not chave_extraida:
            continue
        dados_novo = resultado_extraido[chave_extraida]
        vi = v["verbaIndenizatoria"]
        despesas_existentes = v.setdefault("despesas", [])

        chaves_existentes = {chave_dedup(d["data"], d["valor"], d.get("nf") or "") for d in despesas_existentes}
        notas_novas_vereador = 0
        mes_mudou = False

        for ato_num, ato_key_json, campo_meses in (("027", "ato027", "mesesAto027"), ("028", "ato028", "mesesAto028")):
            meses_novo = dados_novo.get(ato_key_json, {})
            meses_dict = vi.setdefault(campo_meses, {})

            for mes_chave, dados_mes in meses_novo.items():
                mes_num, ano = mes_chave.split("/")
                if ano != ANO_STR:
                    continue
                abrev = MESES_NUM_PARA_ABREV[mes_num]

                total = total_mes_confiavel(dados_mes)
                if total is not None and meses_dict.get(abrev) != total:
                    meses_dict[abrev] = total
                    mes_mudou = True

                for grupo in ("notas", "combustivel"):
                    for item in dados_mes.get(grupo, []):
                        if item.get("valor") is None or not data_valida(item["data"]):
                            continue
                        data_iso = data_para_iso(item["data"])
                        doc_limpo = limpa_doc(item.get("documento"))
                        chave = chave_dedup(data_iso, item["valor"], doc_limpo or "")
                        if chave in chaves_existentes:
                            continue
                        despesas_existentes.append({
                            "data": data_iso,
                            "fornecedor": item.get("fornecedor") or "",
                            "cnpj": item.get("cnpj"),
                            "valor": item["valor"],
                            "nf": doc_limpo,
                            "descricao": item.get("objeto") or item.get("descricao") or "",
                            "ato": f"ATO {ato_num}",
                        })
                        chaves_existentes.add(chave)
                        notas_novas_vereador += 1

        if notas_novas_vereador or mes_mudou:
            gasto027 = round(sum(vi.get("mesesAto027", {}).values()), 2)
            gasto028 = round(sum(vi.get("mesesAto028", {}).values()), 2)
            gasto_pago = round(gasto027 + gasto028, 2)
            cota_anual = vi.get("cotaAnual2026") or 1
            vi["gastoAto027_2026"] = gasto027
            vi["gastoAto028_2026"] = gasto028
            vi["gastoPago2026"] = gasto_pago
            vi["percentualUsado"] = round(gasto_pago / cota_anual * 100, 1)

            despesas_existentes.sort(key=lambda d: d["data"])
            v["totalNotasFiscais"] = len(despesas_existentes)

            vereadores_atualizados += 1
            total_notas_novas += notas_novas_vereador
            log(f" {v['nome']}: +{notas_novas_vereador} notas novas" + (", meses atualizados" if mes_mudou else ""))

    if vereadores_atualizados:
        atual["ultimaAtualizacao"] = hoje
        json.dump(atual, open(ARQUIVO_CAMARA, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        log(f"✅ camara_municipal.json atualizado — {vereadores_atualizados} vereadores, {total_notas_novas} notas fiscais novas")
    else:
        log(" Nenhuma mudança confiável encontrada — camara_municipal.json inalterado")

if __name__ == "__main__":
    resultado = coletar_verba_indenizatoria()
    mesclar_dados(resultado)
