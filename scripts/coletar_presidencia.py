#!/usr/bin/env python3
"""
Cofre Aberto MS — Coleta de dados da Presidência da República
Fonte: Portal da Transparência do Governo Federal (api.portaldatransparencia.gov.br)

Códigos SIAFI usados:
  20000 = Presidência da República (órgão superior — inclui EBC, Imprensa Nacional etc.)
  20101 = Presidência da República (unidade principal)
  60000 = Gabinete da Vice-Presidência da República

Observações importantes sobre os dados desta fonte (ver notasMetodologicas no JSON final):
- O portador do cartão corporativo (CPGF) não é divulgado pelo Portal da Transparência
  por sigilo — a maior parte das transações do código 20101 é do Gabinete de Segurança
  Institucional, então não é possível montar um "ranking por responsável" nominal.
- As viagens/diárias vinculadas aos órgãos 20101/60000 são de servidores e equipe da
  Presidência e da Vice-Presidência, não do Presidente e do Vice-Presidente pessoalmente
  — eles não têm PCDP (Proposta de Concessão de Diárias e Passagens) individual nesse
  sistema.
- Não existe dado público específico sobre o custo operacional da aeronave presidencial
  (FAB) nesta API; os valores de passagem aqui são de viagens de equipe, não da aeronave.
"""

import json, os, time
from datetime import datetime, date
from pathlib import Path
import requests

ROOT = Path(__file__).parent.parent
DADOS = ROOT / "dados"
ANO = date.today().year
hoje = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

HEADERS = {
    "User-Agent": "CoffreAbertoMS/1.0 (github.com/cofre-aberto-ms; transparencia publica)",
    "Accept": "application/json",
}

CODIGO_PRESIDENCIA = "20101"
CODIGO_VICE_PRESIDENCIA = "60000"
CODIGO_ORGAO_SUPERIOR = "20000"


def log(msg): print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")


def salvar(nome, data):
    path = DADOS / nome
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    log(f"✅ {nome} salvo ({path.stat().st_size//1024}KB)")


def get_com_retry(url, api_key, params, tentativas=3):
    headers = {**HEADERS, "chave-api-dados": api_key}
    for i in range(tentativas):
        try:
            r = requests.get(url, headers=headers, params=params, timeout=30)
            r.raise_for_status()
            return r
        except Exception as e:
            if i == tentativas - 1:
                raise
            log(f"  Tentativa {i+1} falhou ({e}), tentando novamente...")
            time.sleep(5)


def _parse_valor_br(v):
    if v is None:
        return 0.0
    if isinstance(v, (int, float)):
        return float(v)
    txt = str(v).strip().replace(".", "").replace(",", ".")
    try:
        return float(txt)
    except Exception:
        return 0.0


# ============================================================
# 1. CARTÃO DE PAGAMENTO DO GOVERNO FEDERAL (CPGF)
# ============================================================
def coletar_cartoes_presidencia(api_key):
    log("Coletando cartão corporativo (CPGF) da Presidência...")
    total_gasto = 0.0
    total_transacoes = 0
    por_unidade_gestora = {}
    por_mes = {}

    pagina = 1
    while True:
        try:
            r = get_com_retry(
                "https://api.portaldatransparencia.gov.br/api-de-dados/cartoes",
                api_key,
                {
                    "mesExtratoInicio": f"01/{ANO}",
                    "mesExtratoFim": f"12/{ANO}",
                    "codigoOrgao": CODIGO_PRESIDENCIA,
                    "pagina": pagina,
                },
                tentativas=2,
            )
        except Exception as e:
            log(f"  ⚠️ Erro na página {pagina}: {e}")
            break

        lote = r.json()
        if not lote:
            break

        for t in lote:
            valor = _parse_valor_br(t.get("valorTransacao"))
            total_gasto += valor
            total_transacoes += 1
            ug = (t.get("unidadeGestora") or {}).get("nome") or "Não informado"
            mes = t.get("mesExtrato") or "?"
            por_unidade_gestora[ug] = round(por_unidade_gestora.get(ug, 0) + valor, 2)
            por_mes[mes] = round(por_mes.get(mes, 0) + valor, 2)

        pagina += 1
        if pagina > 200:
            break
        time.sleep(0.05)

    log(f"  {total_transacoes} transações de cartão corporativo, R$ {total_gasto:,.2f}")
    return {
        "totalGasto": round(total_gasto, 2),
        "totalTransacoes": total_transacoes,
        "porUnidadeGestora": dict(sorted(por_unidade_gestora.items(), key=lambda x: -x[1])),
        "porMes": dict(sorted(por_mes.items(), key=lambda x: x[0][3:] + x[0][:2])),
        "nomePortadorDisponivel": False,
    }


# ============================================================
# 2. VIAGENS E DIÁRIAS (Presidência + Vice-Presidência)
# ============================================================
def _dias_no_mes(ano, mes):
    if mes == 12:
        return 31
    return (date(ano, mes + 1, 1) - date(ano, mes, 1)).days


def coletar_viagens_presidencia(api_key):
    log("Coletando viagens/diárias vinculadas à Presidência e Vice-Presidência...")
    total_viagens = 0
    total_diarias = 0.0
    total_passagens = 0.0
    por_orgao = {}
    viagens_todas = []

    for codigo_orgao in (CODIGO_PRESIDENCIA, CODIGO_VICE_PRESIDENCIA):
        for mes in range(1, 13):
            ultimo_dia = _dias_no_mes(ANO, mes)
            ini = f"01/{mes:02d}/{ANO}"
            fim = f"{ultimo_dia:02d}/{mes:02d}/{ANO}"
            pagina = 1
            while True:
                try:
                    r = get_com_retry(
                        "https://api.portaldatransparencia.gov.br/api-de-dados/viagens",
                        api_key,
                        {
                            "dataIdaDe": ini, "dataIdaAte": fim,
                            "dataRetornoDe": ini, "dataRetornoAte": fim,
                            "codigoOrgao": codigo_orgao,
                            "pagina": pagina,
                        },
                        tentativas=2,
                    )
                except Exception as e:
                    log(f"  ⚠️ Erro em {codigo_orgao} {mes:02d}/{ANO} pág.{pagina}: {e}")
                    break

                lote = r.json()
                if not lote:
                    break

                for v in lote:
                    diarias = v.get("valorTotalDiarias") or 0
                    passagem = v.get("valorTotalPassagem") or 0
                    valor_total = v.get("valorTotalViagem") or 0
                    orgao_nome = (v.get("orgao") or {}).get("nome") or "Não informado"

                    total_viagens += 1
                    total_diarias += diarias
                    total_passagens += passagem
                    por_orgao[orgao_nome] = round(por_orgao.get(orgao_nome, 0) + valor_total, 2)

                    viagens_todas.append({
                        "beneficiario": (v.get("beneficiario") or {}).get("nome"),
                        "cargo": (v.get("funcao") or {}).get("descricao") or (v.get("cargo") or {}).get("descricao"),
                        "orgao": orgao_nome,
                        "motivo": (v.get("viagem") or {}).get("motivo"),
                        "dataInicio": v.get("dataInicioAfastamento"),
                        "dataFim": v.get("dataFimAfastamento"),
                        "valorDiarias": round(diarias, 2),
                        "valorPassagem": round(passagem, 2),
                        "valorTotal": round(valor_total, 2),
                    })

                pagina += 1
                if pagina > 100:
                    break
            time.sleep(0.05)

    viagens_todas.sort(key=lambda x: x["valorTotal"], reverse=True)
    log(f"  {total_viagens} viagens, R$ {total_diarias + total_passagens:,.2f} (diárias + passagens)")
    return {
        "totalViagens": total_viagens,
        "totalDiarias": round(total_diarias, 2),
        "totalPassagens": round(total_passagens, 2),
        "totalGeral": round(total_diarias + total_passagens, 2),
        "porOrgao": dict(sorted(por_orgao.items(), key=lambda x: -x[1])),
        "principais": viagens_todas[:50],
    }


# ============================================================
# 3. DESPESAS POR ÓRGÃO VINCULADO
# ============================================================
def coletar_despesas_presidencia(api_key):
    log("Coletando despesas por órgão vinculado à Presidência...")
    try:
        r = get_com_retry(
            "https://api.portaldatransparencia.gov.br/api-de-dados/despesas/por-orgao",
            api_key,
            {"ano": ANO, "orgaoSuperior": CODIGO_ORGAO_SUPERIOR, "pagina": 1},
            tentativas=2,
        )
    except Exception as e:
        log(f"  ⚠️ Erro ao coletar despesas por órgão: {e}")
        return []

    registros = r.json()
    resultado = []
    for reg in registros:
        resultado.append({
            "orgao": reg.get("orgao"),
            "codigoOrgao": reg.get("codigoOrgao"),
            "empenhado": round(_parse_valor_br(reg.get("empenhado")), 2),
            "liquidado": round(_parse_valor_br(reg.get("liquidado")), 2),
            "pago": round(_parse_valor_br(reg.get("pago")), 2),
        })
    resultado.sort(key=lambda x: -x["pago"])
    log(f"  {len(resultado)} órgãos vinculados coletados")
    return resultado


# ============================================================
# MAIN
# ============================================================
if __name__ == "__main__":
    api_key = os.environ.get("PORTAL_TRANSPARENCIA_API_KEY")
    if not api_key:
        log("⚠️ PORTAL_TRANSPARENCIA_API_KEY não configurada — abortando coleta da Presidência")
        raise SystemExit(0)

    cartoes = coletar_cartoes_presidencia(api_key)
    viagens = coletar_viagens_presidencia(api_key)
    despesas_por_orgao = coletar_despesas_presidencia(api_key)

    # Total "headline": só Presidência + Vice-Presidência (exclui EBC e Imprensa
    # Nacional, que são entidades vinculadas mas não são o gabinete presidencial).
    total_geral_pago = sum(
        d["pago"] for d in despesas_por_orgao
        if d["codigoOrgao"] in (CODIGO_PRESIDENCIA, CODIGO_VICE_PRESIDENCIA)
    )

    data = {
        "ultimaAtualizacao": hoje,
        "ano": ANO,
        "fonte": f"Portal da Transparência do Governo Federal (api.portaldatransparencia.gov.br) — {hoje}",
        "totalGeralPago": round(total_geral_pago, 2),
        "cartaoCorporativo": cartoes,
        "viagens": viagens,
        "despesasPorOrgao": despesas_por_orgao,
        "notasMetodologicas": [
            "O nome do portador do cartão corporativo (CPGF) não é divulgado pelo Portal da Transparência por sigilo — a maior parte das transações do código 20101 pertence ao Gabinete de Segurança Institucional. Não é possível publicar um ranking nominal de responsáveis.",
            "As viagens e diárias listadas são de servidores e equipe vinculados à Presidência e à Vice-Presidência da República, não do Presidente ou do Vice-Presidente pessoalmente — eles não possuem PCDP (Proposta de Concessão de Diárias e Passagens) individual neste sistema.",
            "Não há dado público sobre o custo operacional da aeronave presidencial (FAB) nesta API. Os valores de passagem aqui refletem viagens de equipe/servidores, não da aeronave presidencial.",
            "O total geral em destaque soma apenas Presidência da República e Gabinete da Vice-Presidência. A tabela de despesas por órgão também lista a Empresa Brasil de Comunicação (EBC) e a Imprensa Nacional, que são entidades vinculadas à Presidência mas com orçamento e gestão próprios.",
        ],
    }

    salvar("presidencia.json", data)
    log(f"✅ Total geral (Presidência + Vice): R$ {total_geral_pago:,.2f}")
