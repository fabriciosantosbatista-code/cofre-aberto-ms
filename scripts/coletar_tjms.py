#!/usr/bin/env python3
"""
Cofre Aberto MS — Remuneração dos magistrados do TJMS
(Tribunal de Justiça do Estado de Mato Grosso do Sul)

Fonte: https://www.tjms.jus.br/transparencia/resolucaoCNJ215/detalhamentoFolha.php
Listagem aberta (sem CPF, sem chave de API) de PDFs mensais "Detalhamento
Folha de Pagamento", padrão CNJ (Anexo VIII, Resolução 102/2009 c/c
215/2015) — cobre TODO o pessoal do tribunal (magistrados, servidores,
aposentados) num único PDF de dezenas de páginas.

Diferente do TRT24/TRE-MS (tabela/planilha estruturada), aqui o dado só
existe em PDF sem colunas delimitadas — nome, lotação e cargo vêm colados
num único bloco de texto por linha. A estratégia:
  1. Os 15 números no final da linha (padrão CNJ) são fáceis de ancorar
     via regex (formato "1.234,56" ou "-1.234,56").
  2. O nome é o prefixo em CAIXA ALTA da linha (até a primeira palavra
     com letra minúscula, onde começa lotação/cargo).
  3. Cargo é localizado por um vocabulário fixo de termos de magistrado,
     com fronteira de palavra (\\b) — sem isso, "Desembargador" (cargo)
     casa como substring dentro de "Desembargadores" (nome de um setor),
     embaralhando o resultado; erro identificado e corrigido durante o
     desenvolvimento deste script.
  4. Cargos de servidor que mencionam magistrado de passagem — "Assessor
     de Desembargador", "Assessor de Juiz" — são excluídos explicitamente
     antes de tentar casar os termos de magistrado.
"""

import json, re, time
from datetime import datetime
from io import BytesIO
from pathlib import Path

import requests
from pypdf import PdfReader

ROOT = Path(__file__).parent.parent
DADOS = ROOT / "dados"
hoje = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

BASE_URL = "https://www5.tjms.jus.br"
PAGINA_LISTAGEM = f"{BASE_URL}/transparencia/resolucaoCNJ215/detalhamentoFolha.php"
HEADERS = {
    "User-Agent": "CoffreAbertoMS/1.0 (github.com/cofre-aberto-ms; transparencia publica)",
}

MESES_PT = {
    "janeiro": 1, "fevereiro": 2, "março": 3, "marco": 3, "abril": 4,
    "maio": 5, "junho": 6, "julho": 7, "agosto": 8, "setembro": 9,
    "outubro": 10, "novembro": 11, "dezembro": 12,
}

CARGOS_MAGISTRADO = ["desembargador", "juiz de direito", "juiz substituto", "juiz auxiliar"]
CARGOS_EXCLUIR = ["assessor de desembargador", "assessor de juiz", "assessor jurídico de juiz",
                   "analista", "técnico", "tecnico"]

VALOR_RE = re.compile(r"-?\d{1,3}(?:\.\d{3})*,\d{2}")
NOME_RE = re.compile(r"^([A-ZÀÁÂÃÉÊÍÓÔÕÚÜÇÑ\.\-\s]+?)\s+(?=[A-ZÀ-Ü][a-zà-ü])")

COLUNAS_NUMERICAS = [
    "remuneracaoParadigma", "vantagensPessoais", "subsidio",
    "indenizacoes", "vantagensEventuais", "gratificacoes",
    "remuneracaoBruta", "previdencia", "impostoRenda",
    "descontosDiversos", "retencaoTeto", "totalDescontos",
    "remuneracaoLiquida", "remuneracaoOrgaoOrigem", "diarias",
]


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")


def salvar(nome, data):
    path = DADOS / nome
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    log(f"✅ {nome} salvo ({path.stat().st_size // 1024}KB)")


def get_com_retry(url, tentativas=3, **kwargs):
    for i in range(tentativas):
        try:
            r = requests.get(url, headers=HEADERS, timeout=90, **kwargs)
            r.raise_for_status()
            return r
        except Exception as e:
            if i == tentativas - 1:
                raise
            log(f"  Tentativa {i + 1} falhou ({e}), tentando novamente...")
            time.sleep(5)


def encontra_pdf_mais_recente():
    """A listagem tem um link por mês, com o padrão de texto
    'Detalhamento Folha de Pagamento_<Mês> <Ano>'. Escolhe o mais recente
    comparando (ano, mês) — a própria página tem pelo menos um erro de
    digitação de ano observado (um mês de 2026 aparece rotulado '2025'),
    então não dá pra confiar na ordem de listagem por si só."""
    r = get_com_retry(PAGINA_LISTAGEM)
    html = r.text
    candidatos = []
    for m in re.finditer(
        r'href="(/webfiles/cms-arquivos/[a-f0-9]+\.pdf)"[^>]*>\s*Detalhamento Folha de Pagamento_(\w+) (\d{4})',
        html,
    ):
        href, mes_nome, ano = m.groups()
        mes_num = MESES_PT.get(mes_nome.lower())
        if mes_num:
            candidatos.append((int(ano), mes_num, href))
    if not candidatos:
        raise RuntimeError("Nenhum link de folha de pagamento encontrado na listagem do TJMS")
    candidatos.sort()
    ano, mes, href = candidatos[-1]
    return f"{BASE_URL}{href}", f"{mes:02d}/{ano}"


def extrai_lotacao_cargo(texto):
    baixo = texto.lower()
    for excluir in CARGOS_EXCLUIR:
        if re.search(r"\b" + re.escape(excluir) + r"\b", baixo):
            return None, None
    for cargo_base in CARGOS_MAGISTRADO:
        m = re.search(r"\b" + re.escape(cargo_base) + r"\b", baixo)
        if m:
            return texto[:m.start()].strip(" -"), texto[m.start():].strip()
    return None, None


def parse_valor(txt):
    try:
        return round(float(txt.replace(".", "").replace(",", ".")), 2)
    except (ValueError, AttributeError):
        return 0.0


def determina_situacao(cargo, lotacao):
    texto = f"{cargo} {lotacao}".upper()
    if "INATIVO" in texto or "PENSIONISTA" in texto:
        return "INATIVO"
    return "ATIVO"


def processa_linha(linha):
    valores = list(VALOR_RE.finditer(linha))
    if len(valores) < 15:
        return None
    ultimos15 = valores[-15:]
    texto_antes = linha[:ultimos15[0].start()].strip()

    m = NOME_RE.match(texto_antes)
    if not m:
        return None
    nome = m.group(1).strip()
    resto = texto_antes[m.end():].strip()

    lotacao, cargo = extrai_lotacao_cargo(resto)
    if not cargo:
        return None

    registro = {"nome": nome, "lotacao": lotacao, "cargo": cargo, "situacao": determina_situacao(cargo, lotacao)}
    for campo, m_valor in zip(COLUNAS_NUMERICAS, ultimos15):
        registro[campo] = parse_valor(m_valor.group(0))
    return registro


def processa_pdf(conteudo_bytes):
    reader = PdfReader(BytesIO(conteudo_bytes))
    magistrados = []
    for pagina in reader.pages:
        try:
            texto = pagina.extract_text() or ""
        except Exception:
            continue
        for linha in texto.split("\n"):
            registro = processa_linha(linha)
            if registro:
                magistrados.append(registro)
    return magistrados


def coletar_tjms():
    log("Coletando remuneração de magistrados do TJMS...")
    try:
        url_pdf, mes_referencia = encontra_pdf_mais_recente()
    except Exception as e:
        log(f"  ⚠️ Não foi possível localizar o PDF mais recente: {e}")
        return None

    log(f"  Arquivo mais recente: {mes_referencia} — {url_pdf}")

    try:
        resp = get_com_retry(url_pdf)
        magistrados = processa_pdf(resp.content)
    except Exception as e:
        log(f"  ⚠️ Falha ao baixar/processar o PDF: {e} — mantendo dados anteriores")
        return None

    if not magistrados:
        log("  ⚠️ Nenhum magistrado encontrado no PDF — mantendo dados anteriores")
        return None

    magistrados.sort(key=lambda m: -m["remuneracaoBruta"])
    total_folha = round(sum(m["remuneracaoBruta"] for m in magistrados), 2)
    ativos = [m for m in magistrados if m["situacao"] == "ATIVO"]
    total_folha_ativos = round(sum(m["remuneracaoBruta"] for m in ativos), 2)

    por_cargo = {}
    for m in magistrados:
        por_cargo[m["cargo"]] = por_cargo.get(m["cargo"], 0) + 1

    data = {
        "ultimaAtualizacao": hoje,
        "fonte": f"Portal da Transparência do TJMS (tjms.jus.br/transparencia/resolucaoCNJ215) — Anexo VIII, Resolução CNJ 102/2009 c/c 215/2015 — coleta automática {hoje}",
        "mesReferencia": mes_referencia,
        "resumo": {
            "totalMagistrados": len(magistrados),
            "totalFolhaMensalBruta": total_folha,
            "totalAtivos": len(ativos),
            "totalFolhaMensalBrutaAtivos": total_folha_ativos,
            "porCargo": por_cargo,
        },
        "magistrados": magistrados,
    }
    salvar("tjms_magistrados.json", data)
    log(f"  {len(magistrados)} magistrados — folha bruta de {mes_referencia}: R$ {total_folha:,.2f}")
    return data


if __name__ == "__main__":
    coletar_tjms()
