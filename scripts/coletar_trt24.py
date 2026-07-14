#!/usr/bin/env python3
"""
Cofre Aberto MS — Remuneração dos magistrados do TRT24
(Tribunal Regional do Trabalho da 24ª Região — Mato Grosso do Sul)

Fonte: https://www.trt24.jus.br/web/transparencia/remuneracao
Publicam mensalmente, em formato aberto (.ods), a folha de pagamento
nominal de magistrados e servidores (Anexo VIII da Resolução CNJ 102/2009).
Sem chave de API, sem CPF — só baixar o arquivo do mês mais recente.

O arquivo cobre TODO o pessoal do tribunal (magistrados, servidores,
estagiários, pensionistas); este script filtra apenas os cargos de
magistrado (Desembargador e Juiz, em qualquer variação/nível).
"""

import json, re, time, zipfile
import xml.etree.ElementTree as ET
from datetime import datetime
from io import BytesIO
from pathlib import Path

import requests

ROOT = Path(__file__).parent.parent
DADOS = ROOT / "dados"
hoje = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

BASE_URL = "https://www.trt24.jus.br"
PAGINA_REMUNERACAO = f"{BASE_URL}/web/transparencia/remuneracao"
HEADERS = {
    "User-Agent": "CoffreAbertoMS/1.0 (github.com/cofre-aberto-ms; transparencia publica)",
}

NS = {
    "table": "urn:oasis:names:tc:opendocument:xmlns:table:1.0",
    "text": "urn:oasis:names:tc:opendocument:xmlns:text:1.0",
}
T_NS = "urn:oasis:names:tc:opendocument:xmlns:table:1.0"

# Colunas do Anexo VIII, na ordem em que aparecem na planilha do TRT24
COLUNAS = [
    "nome", "cargo", "lotacao",
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
            r = requests.get(url, headers=HEADERS, timeout=60, **kwargs)
            r.raise_for_status()
            return r
        except Exception as e:
            if i == tentativas - 1:
                raise
            log(f"  Tentativa {i + 1} falhou ({e}), tentando novamente...")
            time.sleep(5)


def encontra_arquivo_mais_recente(sessao):
    """A página de transparência lista um link .ods por mês, com o padrão
    'MM-YYYY - Remuneração e diárias (folha de pagamento).ods'. Pega o mais
    recente comparando (ano, mês) em vez de confiar na ordem de listagem."""
    r = get_com_retry(PAGINA_REMUNERACAO)
    html = r.text
    candidatos = []
    for m in re.finditer(r'href="(/documents/[^"]*\.ods)"', html):
        href = m.group(1)
        mm = re.search(r'(\d{2})-(\d{4})', href)
        if mm:
            mes, ano = mm.groups()
            candidatos.append((int(ano), int(mes), href))
    if not candidatos:
        raise RuntimeError("Nenhum link .ods encontrado na página de remuneração do TRT24")
    candidatos.sort()
    ano, mes, href = candidatos[-1]
    url = BASE_URL + href.replace("&amp;", "&")
    return url, f"{mes:02d}/{ano}"


def texto_celula(cel):
    return " ".join((p.text or "") for p in cel.findall("text:p", NS))


def parse_valor(txt):
    if txt in (None, "", "-"):
        return 0.0
    txt = txt.strip().replace(".", "").replace(",", ".")
    try:
        return round(float(txt), 2)
    except ValueError:
        return 0.0


def processa_ods(conteudo_bytes):
    with zipfile.ZipFile(BytesIO(conteudo_bytes)) as z:
        content_xml = z.read("content.xml")
    root = ET.fromstring(content_xml)

    tabelas = root.findall(".//table:table", NS)
    aba = next((t for t in tabelas if t.get(f"{{{T_NS}}}name") == "ANEXO_VIII"), None)
    if aba is None:
        raise RuntimeError("Aba ANEXO_VIII não encontrada no arquivo ODS")

    pessoas = []
    for linha in aba.findall("table:table-row", NS):
        celulas = []
        for cel in linha.findall("table:table-cell", NS):
            repetido = int(cel.get(f"{{{T_NS}}}number-columns-repeated", "1"))
            if repetido > 5:  # célula vazia repetida até o fim da linha — não é dado
                continue
            celulas.append(texto_celula(cel))

        # linhas de dado têm nome (texto) na primeira coluna e >= 18 colunas no total;
        # cabeçalho/legenda/linhas em branco não batem esse formato
        if len(celulas) < len(COLUNAS) or not celulas[0].strip():
            continue
        if celulas[0].strip().upper() in ("NOME",):
            continue

        registro = dict(zip(COLUNAS, celulas))
        # startswith, não "in" — "ASSISTENTE DE JUIZ" é cargo de servidor, não de magistrado
        cargo_upper = registro["cargo"].strip().upper()
        if not (cargo_upper.startswith("JUIZ") or cargo_upper.startswith("DESEMBARGADOR")):
            continue

        for campo in COLUNAS:
            if campo not in ("nome", "cargo", "lotacao"):
                registro[campo] = parse_valor(registro[campo])
        registro["nome"] = registro["nome"].strip()
        registro["cargo"] = registro["cargo"].strip()
        registro["lotacao"] = registro["lotacao"].strip()
        pessoas.append(registro)

    return pessoas


def coletar_trt24():
    log("Coletando remuneração de magistrados do TRT24...")
    sessao = requests.Session()

    try:
        url_arquivo, mes_referencia = encontra_arquivo_mais_recente(sessao)
    except Exception as e:
        log(f"  ⚠️ Não foi possível localizar o arquivo mais recente: {e}")
        return None

    log(f"  Arquivo mais recente: {mes_referencia} — {url_arquivo}")

    try:
        resp = get_com_retry(url_arquivo)
        magistrados = processa_ods(resp.content)
    except Exception as e:
        log(f"  ⚠️ Falha ao baixar/processar o arquivo: {e} — mantendo dados anteriores")
        return None

    if not magistrados:
        log("  ⚠️ Nenhum magistrado encontrado no arquivo — mantendo dados anteriores")
        return None

    magistrados.sort(key=lambda m: -m["remuneracaoBruta"])
    total_folha = round(sum(m["remuneracaoBruta"] for m in magistrados), 2)

    por_cargo = {}
    for m in magistrados:
        grupo = ("Desembargador" if "DESEMBARGADOR" in m["cargo"].upper()
                 else "Juiz Substituto" if "SUBSTITUTO" in m["cargo"].upper()
                 else "Juiz Classista" if "CLASSISTA" in m["cargo"].upper()
                 else "Juiz Titular")
        por_cargo[grupo] = por_cargo.get(grupo, 0) + 1

    data = {
        "ultimaAtualizacao": hoje,
        "fonte": f"Portal da Transparência do TRT24 (trt24.jus.br/web/transparencia/remuneracao) — Anexo VIII, Resolução CNJ 102/2009 — coleta automática {hoje}",
        "mesReferencia": mes_referencia,
        "resumo": {
            "totalMagistrados": len(magistrados),
            "totalFolhaMensalBruta": total_folha,
            "porCargo": por_cargo,
        },
        "magistrados": magistrados,
    }
    salvar("trt24_magistrados.json", data)
    log(f"  {len(magistrados)} magistrados — folha bruta de {mes_referencia}: R$ {total_folha:,.2f}")
    return data


if __name__ == "__main__":
    coletar_trt24()
