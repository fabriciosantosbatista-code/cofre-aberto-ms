#!/usr/bin/env python3
"""
Cofre Aberto MS — Cadastro na Receita Federal das empresas que recebem dinheiro público

Consulta, na BrasilAPI (espelho público do cadastro de CNPJ da Receita Federal),
as empresas que aparecem nas notas dos parlamentares de MS e nos contratos e
licitações da Prefeitura de Campo Grande: atividade (CNAE principal e
secundárias), data de abertura, capital social, situação cadastral, porte e
quadro de sócios.

Guarda tudo em dados/cnpj_cache.json e só consulta de novo o que é novo ou tem
mais de 90 dias — a primeira execução leva uns 15 minutos; as diárias, segundos.
Usado por gerar_auditoria.py.

Uso:  python3 scripts/coletar_cnpj.py [limite_de_consultas]
"""

import json, re, sys, time
from datetime import date, datetime, timedelta
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent))
from gerar_analises import cnpj_valido  # noqa: E402

ROOT = Path(__file__).parent.parent
DADOS = ROOT / "dados"
CACHE = DADOS / "cnpj_cache.json"
APIS = ("https://brasilapi.com.br/api/cnpj/v1/{}", "https://minhareceita.org/{}")
UA = {"User-Agent": "Mozilla/5.0 (CofreAbertoMS; +https://cofreabertoms.com.br)"}
VALIDADE = timedelta(days=90)


def dig(t):
    return re.sub(r"\D", "", str(t or ""))


def carregar(nome):
    try:
        return json.load(open(DADOS / nome, encoding="utf-8"))
    except Exception:
        return {}


def cnpjs_alvo():
    """CNPJs válidos das notas dos parlamentares e dos contratos/licitações, com o valor recebido (prioridade)."""
    valor = {}
    def soma(c, v):
        c = dig(c)
        if len(c) == 14 and cnpj_valido(c):
            valor[c] = valor.get(c, 0) + (v or 0)
    for v in carregar("camara_municipal.json").get("vereadores", []):
        for n in v.get("despesas") or []:
            soma(n.get("cnpj"), n.get("valor"))
    for v in carregar("deputados_estaduais_ms.json").get("vereadores", []):
        for n in v.get("despesas") or []:
            soma(n.get("cnpj"), n.get("valor"))
    for v in carregar("deputados_federais_ms.json").get("deputados", []):
        for n in v.get("despesas") or []:
            soma(n.get("cnpjCpfFornecedor"), n.get("valor"))
    for v in carregar("senadores_ms.json").get("senadores", []):
        for n in v.get("notasCeaps") or []:
            soma(n.get("cnpjCpf"), n.get("valor"))
    ct = carregar("prefeitura_contratos.json")
    for c in ct.get("contratos", []):
        soma(c.get("cnpj"), c.get("valor"))
    for l in ct.get("licitacoes", []):
        for w in l.get("vencedores", []):
            soma(w.get("cnpj"), 1)
    return sorted(valor, key=lambda c: -valor[c])


def resumir(d):
    return {"razao": d.get("razao_social"), "fantasia": d.get("nome_fantasia") or None,
            "abertura": d.get("data_inicio_atividade"), "cnae": str(d.get("cnae_fiscal") or ""),
            "cnaeDesc": d.get("cnae_fiscal_descricao"),
            "cnaesSec": [str(c.get("codigo")) for c in d.get("cnaes_secundarios") or [] if c.get("codigo")],
            "capital": d.get("capital_social"), "situacao": d.get("descricao_situacao_cadastral"),
            "dataSituacao": d.get("data_situacao_cadastral"), "motivoSituacao": d.get("descricao_motivo_situacao_cadastral"),
            "municipio": d.get("municipio"), "uf": d.get("uf"), "porte": d.get("porte"),
            "mei": d.get("opcao_pelo_mei"), "natureza": d.get("natureza_juridica"),
            "socios": [{"nome": q.get("nome_socio"), "qualificacao": q.get("qualificacao_socio"),
                        "entrada": q.get("data_entrada_sociedade")} for q in d.get("qsa") or []],
            "consultadoEm": date.today().isoformat()}


def consultar(c):
    for url in APIS:
        for t in range(3):
            try:
                r = requests.get(url.format(c), headers=UA, timeout=30)
                if r.status_code == 200:
                    return resumir(r.json())
                if r.status_code in (400, 404):
                    return {"naoEncontrado": True, "consultadoEm": date.today().isoformat()}
                if r.status_code == 429:
                    time.sleep(10 * (t + 1))
                    continue
            except Exception:
                time.sleep(3)
        # tenta a próxima base
    return None


def main():
    limite = int(sys.argv[1]) if len(sys.argv) > 1 else 3000
    try:
        cache = json.load(open(CACHE, encoding="utf-8"))
    except Exception:
        cache = {}
    alvo = cnpjs_alvo()
    hoje = date.today()
    pendentes = [c for c in alvo if c not in cache or
                 (hoje - date.fromisoformat(cache[c].get("consultadoEm", "2000-01-01"))) > VALIDADE][:limite]
    print(f"🔎 CNPJ: {len(alvo)} empresas, {len(pendentes)} para consultar agora (cache com {len(cache)})")
    novos, falhas = 0, 0
    for i, c in enumerate(pendentes):
        r = consultar(c)
        if r is None:
            falhas += 1
        else:
            cache[c] = r
            novos += 1
        if (i + 1) % 200 == 0:
            print(f"  {i + 1}/{len(pendentes)}")
            CACHE.write_text(json.dumps(cache, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        time.sleep(0.35)
    CACHE.write_text(json.dumps(cache, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"✅ cnpj_cache.json — {novos} consultados, {falhas} falhas, {len(cache)} no cache "
          f"({CACHE.stat().st_size // 1024} KB) · {datetime.now():%H:%M}")


if __name__ == "__main__":
    main()
