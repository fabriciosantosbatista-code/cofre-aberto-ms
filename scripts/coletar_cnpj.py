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
    # credores do Governo do Estado: só empresas privadas que receberam R$ 50 mil ou mais no ano
    for c in carregar("governo_ms_credores.json").get("credores", []):
        if len(c) > 4 and c[4] == "fornecedor" and (c[2] or 0) >= 50000:
            soma(c[0], c[2])
    # contratos e licitações do Estado; fornecedores da Prefeitura com R$ 50 mil ou mais pagos
    for c in carregar("governo_ms_contratos.json").get("contratos", []):
        soma(c.get("cnpj"), c.get("valor"))
    for f in carregar("governo_ms_licitacoes.json").get("fornecedores", []):
        soma(f.get("cnpj"), f.get("valor"))
    al = carregar("alugueis.json")  # locadores de imóveis (Prefeitura de CG e PNCP): para ver os sócios
    for c in (al.get("pncp") or {}).get("lista") or []:
        if c.get("locador") and c["locador"].get("tipo") == "PJ":
            soma(c["locador"].get("doc"), max(c.get("valor") or 0, 50000))
    for a in (al.get("prefeitura") or {}).get("lista") or []:
        if a.get("tipo") == "PJ":
            soma(a.get("doc"), max(a.get("valor") or 0, 50000))
    pref = {}
    for x in carregar("prefeitura.json").get("despesas", []):
        d = dig(x.get("cnpj"))
        pref[d] = pref.get(d, 0) + (x.get("valor") or 0)
    for d, v in pref.items():
        if v >= 50000:
            soma(d, v)
    # filial (0002, 0016...): também a matriz (0001), para saber desde quando a empresa ou entidade existe de fato
    for c, v in list(valor.items()):
        if c[8:12] != "0001":
            m = matriz(c)
            valor[m] = max(valor.get(m, 0), v)
    return sorted(valor, key=lambda c: -valor[c])


def matriz(c):
    """CNPJ da matriz (0001) com os dígitos verificadores."""
    def dv(s, w):
        r = sum(int(x) * y for x, y in zip(s, w)) % 11
        return "0" if r < 2 else str(11 - r)
    b = c[:8] + "0001"
    w1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    d1 = dv(b, w1)
    return b + d1 + dv(b + d1, [6] + w1)


def abertura_real(c, cache):
    """Data em que a empresa/entidade passou a existir: a da matriz quando c é filial (None se a matriz ainda não foi consultada)."""
    info = cache.get(c) or {}
    if c[8:12] == "0001":
        return info.get("abertura")
    return (cache.get(matriz(c)) or {}).get("abertura")


def resumir(d):
    return {"razao": d.get("razao_social"), "fantasia": d.get("nome_fantasia") or None,
            "abertura": d.get("data_inicio_atividade"), "cnae": str(d.get("cnae_fiscal") or ""),
            "cnaeDesc": d.get("cnae_fiscal_descricao"),
            "cnaesSec": [str(c.get("codigo")) for c in d.get("cnaes_secundarios") or [] if c.get("codigo")],
            "capital": d.get("capital_social"), "situacao": d.get("descricao_situacao_cadastral"),
            "dataSituacao": d.get("data_situacao_cadastral"), "motivoSituacao": d.get("descricao_motivo_situacao_cadastral"),
            "municipio": d.get("municipio"), "uf": d.get("uf"), "porte": d.get("porte"),
            "mei": d.get("opcao_pelo_mei"), "natureza": d.get("natureza_juridica"),
            "endereco": " ".join(str(x) for x in (d.get("descricao_tipo_de_logradouro"), d.get("logradouro"), d.get("numero"),
                                                   d.get("complemento")) if x).strip() or None,
            "bairro": d.get("bairro") or None, "cep": re.sub(r"\D", "", str(d.get("cep") or "")) or None,
            "telefones": [re.sub(r"\D", "", t) for t in (d.get("ddd_telefone_1"), d.get("ddd_telefone_2")) if t and len(re.sub(r"\D", "", t)) >= 10],
            # "cpf": os 6 dígitos do meio do CPF do sócio, como a Receita publica (***123456**)
            "socios": [{"nome": q.get("nome_socio"), "qualificacao": q.get("qualificacao_socio"),
                        "entrada": q.get("data_entrada_sociedade"),
                        "cpf": re.sub(r"\D", "", str(q.get("cnpj_cpf_do_socio") or ""))[:6] or None} for q in d.get("qsa") or []],
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
    # novos primeiro, depois os vencidos e os consultados antes de o endereço ser guardado (sem "cep")
    novos_ = [c for c in alvo if c not in cache]
    velhos = [c for c in alvo if c in cache and ((hoje - date.fromisoformat(cache[c].get("consultadoEm", "2000-01-01"))) > VALIDADE
                                                 or (("cep" not in cache[c] or any("cpf" not in q for q in cache[c].get("socios", [])))
                                                     and not cache[c].get("naoEncontrado")))]
    # divergiram da Receita na última conferência na fonte (validar_fontes.py): consulta de novo antes de tudo
    try:
        reconsultar = [c for c in json.load(open(DADOS / "cnpj_reconsultar.json", encoding="utf-8")).get("cnpjs") or [] if c in cache]
    except Exception:
        reconsultar = []
    pendentes = list(dict.fromkeys(reconsultar + novos_ + velhos))[:max(limite, len(reconsultar))]
    if reconsultar:
        print(f"🔁 CNPJ: {len(reconsultar)} entidade(s) que divergiram da Receita na conferência — consultando de novo")
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
    if reconsultar:  # sai da lista o que foi consultado agora; o que falhou fica para a próxima
        feitos = {c for c in reconsultar if (cache.get(c) or {}).get("consultadoEm") == hoje.isoformat()}
        resto = [c for c in reconsultar if c not in feitos]
        arq = DADOS / "cnpj_reconsultar.json"
        if resto:
            arq.write_text(json.dumps({"motivo": "divergiram do cadastro da Receita na conferência na fonte", "cnpjs": resto},
                                      ensure_ascii=False, indent=1), encoding="utf-8")
        else:
            arq.unlink(missing_ok=True)
    print(f"✅ cnpj_cache.json — {novos} consultados, {falhas} falhas, {len(cache)} no cache "
          f"({CACHE.stat().st_size // 1024} KB) · {datetime.now():%H:%M}")


if __name__ == "__main__":
    main()
