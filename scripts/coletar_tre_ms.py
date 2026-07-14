#!/usr/bin/env python3
"""
Cofre Aberto MS — Remuneração dos magistrados do TRE-MS
(Tribunal Regional Eleitoral de Mato Grosso do Sul)

Fonte: https://cnj2.app.tre-ms.jus.br/anexo8.do
Página aberta (sem CPF, sem chave de API) com a folha de pagamento nominal
completa de magistrados e servidores, no padrão CNJ (Anexo VIII, Resolução
102/2009 c/c 215/2015). Uma única tabela HTML de ~600 linhas, sempre com o
mês/ano de referência mais recente já selecionado por padrão.

Os magistrados do TRE-MS são juízes de direito cedidos pelo TJMS (e
advogados indicados) para atuar nas zonas eleitorais — aparecem com cargo
"JUIZ ELEITORAL - EFETIVO" ou "JUIZ ELEITORAL - SUBSTITUTO". O restante da
tabela é servidor/requisitado/inativo, que este script ignora.
"""

import json, re, time
from datetime import datetime
from pathlib import Path

import requests

ROOT = Path(__file__).parent.parent
DADOS = ROOT / "dados"
hoje = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

URL_ANEXO8 = "https://cnj2.app.tre-ms.jus.br/anexo8.do"
HEADERS = {
    "User-Agent": "CoffreAbertoMS/1.0 (github.com/cofre-aberto-ms; transparencia publica)",
}

# Ordem das colunas de dado na tabela (após Matrícula, Nome, Lotação, Cargo)
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
            r = requests.get(url, headers=HEADERS, timeout=60, **kwargs)
            r.raise_for_status()
            return r
        except Exception as e:
            if i == tentativas - 1:
                raise
            log(f"  Tentativa {i + 1} falhou ({e}), tentando novamente...")
            time.sleep(5)


def limpa_texto(html_celula):
    texto = re.sub(r"<br\s*/?>", " ", html_celula)
    texto = re.sub(r"<[^>]+>", "", texto)
    return re.sub(r"\s+", " ", texto).strip()


def parse_valor(txt):
    txt = (txt or "").strip()
    if txt in ("", "-"):
        return 0.0
    try:
        return round(float(txt.replace(".", "").replace(",", ".")), 2)
    except ValueError:
        return 0.0


def processa_html(html):
    m = re.search(r'value="(\d{2}/\d{4})"', html)
    mes_referencia = m.group(1) if m else None

    linhas = re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S)
    magistrados = []
    for linha in linhas:
        celulas = re.findall(r"<td[^>]*>(.*?)</td>", linha, re.S)
        celulas = [limpa_texto(c) for c in celulas]
        if len(celulas) < 19:
            continue  # cabeçalho ou linha incompleta

        cargo = celulas[3].strip()
        if not cargo.upper().startswith("JUIZ"):
            continue

        registro = {
            "matricula": celulas[0],
            "nome": celulas[1],
            "lotacao": celulas[2],
            "cargo": cargo,
        }
        for campo, valor in zip(COLUNAS_NUMERICAS, celulas[4:19]):
            registro[campo] = parse_valor(valor)
        magistrados.append(registro)

    return magistrados, mes_referencia


def coletar_tre_ms():
    log("Coletando remuneração de magistrados do TRE-MS...")
    try:
        resp = get_com_retry(URL_ANEXO8)
        magistrados, mes_referencia = processa_html(resp.text)
    except Exception as e:
        log(f"  ⚠️ Falha ao baixar/processar a página: {e} — mantendo dados anteriores")
        return None

    if not magistrados:
        log("  ⚠️ Nenhum magistrado encontrado — mantendo dados anteriores")
        return None

    magistrados.sort(key=lambda m: -m["remuneracaoBruta"])
    total_folha = round(sum(m["remuneracaoBruta"] for m in magistrados), 2)

    por_cargo = {}
    for m in magistrados:
        por_cargo[m["cargo"]] = por_cargo.get(m["cargo"], 0) + 1

    data = {
        "ultimaAtualizacao": hoje,
        "fonte": f"Portal da Transparência do TRE-MS (cnj2.app.tre-ms.jus.br/anexo8.do) — Anexo VIII, Resolução CNJ 102/2009 c/c 215/2015 — coleta automática {hoje}",
        "mesReferencia": mes_referencia,
        "resumo": {
            "totalMagistrados": len(magistrados),
            "totalFolhaMensalBruta": total_folha,
            "porCargo": por_cargo,
        },
        "magistrados": magistrados,
    }
    salvar("tre_ms_magistrados.json", data)
    log(f"  {len(magistrados)} magistrados — folha bruta de {mes_referencia}: R$ {total_folha:,.2f}")
    return data


if __name__ == "__main__":
    coletar_tre_ms()
