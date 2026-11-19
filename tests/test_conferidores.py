#!/usr/bin/env python3
"""
Cofre Aberto MS — testes dos conferidores na fonte oficial (scripts/validar_fontes.py), sem rede

A fonte é simulada: cada conferidor precisa dizer "confere" quando o site é igual à fonte, "diverge" quando um único
item difere (um voto, um município, um número de projetos) e "indisponivel" quando a fonte não responde — nunca
"confere" sem ter comparado nada.

Uso: python3 tests/test_conferidores.py   (código 1 se algum teste falhar)
"""
import copy, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import validar_fontes as v  # noqa: E402

oks, erros = [], []


def check(c, m):
    (oks if c else erros).append(m)


VOT = {"quadroCamara": {"deputados": {"1": "Ana", "2": "Bia"},
                        "votacoes": [{"id": "10-1", "votos": {"1": "Sim", "2": "Não"}}, {"id": "10-2", "votos": {"1": "Não"}}]}}
FONTE_VOT = {"10-1": [("1", "Sim"), ("2", "Não")], "10-2": [("1", "Não")]}
PROD = {"inicio": "2023-02-01", "parlamentares": [{"grupo": "federal", "id": "1", "nome": "Ana", "projetos": 3},
                                                  {"grupo": "senador", "id": "9", "nome": "Sen", "projetos": 5}]}
ENT = {"entidades": [{"cnpj": "11", "abertura": "2001-01-01", "municipio": "CAMPO GRANDE", "situacao": "ATIVA"}]}
TJ = {"mesReferencia": "09/2026", "magistrados": [{"situacao": "ATIVO", "subsidio": 100.0}, {"situacao": "ATIVO", "subsidio": 50.0}]}


def rodar(dados, fonte, fn):
    orig_J, orig_get = v.J, v.get
    v.J = lambda n: copy.deepcopy(dados.get(n, {}))
    v.get = fonte
    try:
        return fn()
    finally:
        v.J, v.get = orig_J, orig_get


def fonte_padrao(votos=FONTE_VOT, n_proj=3, ent=None, tj=(2, 150.0), fora=False):
    def get(url, params=None, tent=3, timeout=90):
        if fora:
            return None
        if "/votacoes/" in url:
            vid = url.split("/votacoes/")[1].split("/")[0]
            return {"dados": [{"deputado_": {"id": int(i)}, "tipoVoto": t} for i, t in votos.get(vid, [])]}
        if "/proposicoes" in url:
            return {"dados": [{}] * n_proj, "links": []}
        if "minhareceita" in url:
            return ent or {"data_inicio_atividade": "2001-01-01", "municipio": "Campo Grande", "descricao_situacao_cadastral": "ATIVA"}
        if "dadosjusbr" in url:
            return {"sumarios": {"membros_ativos": {"quantidade": tj[0], "remuneracao_base": {"total": tj[1]}}}}
        return None
    return get


D = {"votacoes.json": VOT, "producao_legislativa.json": PROD, "entidades.json": ENT, "tjms_magistrados.json": TJ}

# votações
r = rodar(D, fonte_padrao(), v.v_votacoes)
check(r["resultado"] == "confere" and r["unidadesConferidas"] == 2 and r["unidadesBase"] == 2, "votações: todos os votos iguais → confere, 2 de 2 votações")
check(r["conferidos"] == 4, "votações: um item por deputado em cada votação (ausente conta como '—')")
check(r["registrosAbrangidos"] == 2 and r["registrosBase"] == 2, "votações: a cobertura conta votações (registros da base), não votos")
r = rodar(D, fonte_padrao(votos={**FONTE_VOT, "10-1": [("1", "Não"), ("2", "Não")]}), v.v_votacoes)
check(r["resultado"] == "diverge" and len(r["divergentes"]) == 1, "votações: um único voto diferente → diverge (não passa pela tolerância)")
r = rodar(D, fonte_padrao(votos={**FONTE_VOT, "10-2": [("1", "Não"), ("2", "Sim")]}), v.v_votacoes)
check(r["resultado"] == "diverge", "votações: deputado ausente no site mas com voto na fonte → diverge")
r = rodar(D, fonte_padrao(fora=True), v.v_votacoes)
check(r["resultado"] == "indisponivel", "votações: fonte fora do ar → indisponível (nunca confere)")

# produção legislativa
r = rodar(D, fonte_padrao(), v.v_producao)
check(r["resultado"] == "confere" and r["conferidos"] == 1, "produção: mesmo nº de projetos → confere (só deputados federais)")
r = rodar(D, fonte_padrao(n_proj=5), v.v_producao)
check(r["resultado"] == "mudou_na_fonte", "produção: fonte com até 3 projetos a mais → mudou na fonte (projeto novo depois da coleta)")
r = rodar(D, fonte_padrao(n_proj=1), v.v_producao)
check(r["resultado"] == "diverge", "produção: fonte com menos projetos que o site → diverge")
r = rodar(D, fonte_padrao(fora=True), v.v_producao)
check(r["resultado"] == "indisponivel", "produção: fonte fora do ar → indisponível")

# entidades
r = rodar(D, fonte_padrao(), v.v_entidades)
check(r["resultado"] == "confere" and r["conferidos"] == 3, "entidades: abertura, município e situação iguais (sem acento/caixa) → confere")
check(r["unidadesConferidas"] == 1 and r["registrosAbrangidos"] == 1 and r["idsConferidos"] == ["11"], "entidades: a cobertura conta entidades (CNPJ), não campos")
r = rodar(D, fonte_padrao(ent={"data_inicio_atividade": "2001-01-01", "municipio": "DOURADOS", "descricao_situacao_cadastral": "ATIVA"}), v.v_entidades)
check(r["resultado"] == "diverge", "entidades: município diferente → diverge")
r = rodar(D, fonte_padrao(ent={"data_inicio_atividade": "2001-01-01", "municipio": "CAMPO GRANDE", "descricao_situacao_cadastral": "BAIXADA"}), v.v_entidades)
check(r["resultado"] == "mudou_na_fonte", "entidades: só a situação cadastral diferente → mudou na fonte")
r = rodar(D, fonte_padrao(fora=True), v.v_entidades)
check(r["resultado"] == "indisponivel", "entidades: fonte fora do ar → indisponível")

r = rodar({**D, "entidades.json": {"entidades": [{"cnpj": "11000000000211", "abertura": "1990-01-01", "aberturaFilial": "2016-07-04",
                                                   "municipio": "CAMPO GRANDE", "situacao": "ATIVA"}]}},
          fonte_padrao(ent={"data_inicio_atividade": "2016-07-04", "municipio": "CAMPO GRANDE", "descricao_situacao_cadastral": "ATIVA"}), v.v_entidades)
check(r["resultado"] == "confere", "entidades: filial — compara a abertura da filial (o site mostra a da matriz em 'abertura')")

r = rodar({**D, "entidades.json": {"entidades": [ENT["entidades"][0], {"cnpj": "22", "abertura": None, "situacao": None, "municipio": "CAMPO GRANDE"}]}},
          fonte_padrao(), v.v_entidades)
check(r["resultado"] == "confere" and r["unidadesConferidas"] == 1 and r.get("lacunas") == ["22"],
      "entidades: sem o cadastro no site → não conferida, registrada como lacuna (nem confere nem diverge)")
check(list((r.get("hashes") or {}).keys()) == ["11"], "entidades: hash gravado só para a entidade que bateu com a fonte")

# judiciário
r = rodar(D, fonte_padrao(), v.v_judiciario)
check(r["resultado"] == "confere", "judiciário: nº de magistrados e soma do subsídio iguais → confere")
r = rodar(D, fonte_padrao(tj=(3, 150.0)), v.v_judiciario)
check(r["resultado"] == "diverge", "judiciário: um magistrado a mais na fonte → diverge")
r = rodar(D, fonte_padrao(tj=(2, 152.0)), v.v_judiciario)
check(r["resultado"] == "diverge", "judiciário: subsídio com diferença acima de R$ 1 → diverge")
r = rodar(D, fonte_padrao(fora=True), v.v_judiciario)
check(r["resultado"] == "indisponivel", "judiciário: fonte fora do ar → indisponível")

# supersalários (TJMS no DadosJusBr): contagem de pessoas não pode passar pela tolerância de R$ 1
SS = {"supersalarios.json": {"orgaos": [{"orgao": "TJMS — Tribunal de Justiça", "mes": "09/2026", "pessoas": 2, "totalBase": 150.0}], "totalPessoas": 2}}
r = rodar(SS, fonte_padrao(tj=(3, 150.0)), v.v_tjms)
check(r["resultado"] == "diverge", "supersalários: um magistrado a mais na fonte → diverge (contagem com tolerância 0)")
r = rodar(SS, fonte_padrao(tj=(2, 150.4)), v.v_tjms)
check(r["resultado"] == "confere", "supersalários: diferença de centavos no salário-base → confere (tolerância R$ 1)")

# registro a registro (casar): usa só a resposta que a fonte já devolveu
k = lambda x: x["k"]
ok_, dv, na = v.casar([{"k": "a", "v": 10}, {"k": "b", "v": 5}, {"k": "b", "v": 7}, {"k": "c", "v": 1}],
                      [{"k": "a", "v": 10.4}, {"k": "b", "v": 7}, {"k": "b", "v": 5}, {"k": "x", "v": 9}], k, k, lambda x: x["v"], lambda x: x["v"])
check(ok_ == 3 and not dv and na == 1, "casar: chave igual com o mesmo conjunto de valores → comparados um a um; chave só no site → não achado (não diverge)")
ok_, dv, na = v.casar([{"k": "a", "v": 10}], [{"k": "a", "v": 12}], k, k, lambda x: x["v"], lambda x: x["v"])
check(ok_ == 0 and len(dv) == 1, "casar: valor diferente na mesma chave → divergência registro a registro")
res = {"resultado": "confere", "registrosAbrangidos": 3, "registrosBase": 3, "divergentes": []}
orig = v.HISTORICO
v.HISTORICO = Path("/nao/existe.jsonl")
v._um_a_um(res, "teste", {"P1": ([{"x": 1}], 1, [], 0), "P2": ([{"x": 2}, {"x": 3}], 1, [("k", [3], [4])], 0)}, ("x",))
v.HISTORICO = orig
check(res["registrosConferidosUmAUm"] == 2 and res["registrosPorTotais"] == 3 and res["resultado"] == "diverge" and res["divergentesRegistros"],
      "um a um: conta só os registros casados; total vira 'coberto por totais'; divergência de registro aparece e a base diverge")
# fonte independente agregada (RGF): diferença em % e tolerância de 10%
SSR = {"orgaos": [{"orgao": "Governo do Estado — ativos", "mes": "10/2026", "totalBase": 100.0, "totalOutras": 0.0},
                  {"orgao": "Governo do Estado — aposentados e pensionistas", "mes": "10/2026", "totalBase": 50.0, "totalOutras": 0.0}]}
def rgf(venc, apos, pens):
    return lambda url, params=None, tent=3, timeout=90: {"items": [
        {"conta": "Vencimentos, Vantagens e Outras Despesas Variáveis", "coluna": "TOTAL (ÚLTIMOS 12 MESES) (a)", "valor": venc},
        {"conta": "Aposentadorias, Reserva e Reformas", "coluna": "TOTAL (ÚLTIMOS 12 MESES) (a)", "valor": apos},
        {"conta": "Pensões", "coluna": "TOTAL (ÚLTIMOS 12 MESES) (a)", "valor": pens}]} if "rgf" in url else None
g0 = v.get
v.get = rgf(1260, 540, 60)
r = v.rgf_executivo(SSR)
check(r["resultado"] == "confere" and [l["diferencaPct"] for l in r["linhas"]] == [-4.8, 0.0], f"RGF: média mensal × folha, diferença em % ({[l['diferencaPct'] for l in r['linhas']]})")
v.get = rgf(1800, 540, 60)
r = v.rgf_executivo(SSR)
check(r["resultado"] == "diverge" and r["linhas"][0]["resultado"] == "diverge", "RGF: diferença acima de 10% → diverge (selo à parte, não muda a contagem)")
v.get = g0

# trava de procedimento: só entra no ICP dentro da coleta (mesmo ID) e até 2 h depois do início dela
import os
from datetime import datetime as _dt, timezone as _tz, timedelta as _td
def janela(env, depois_h):
    antes = {k: os.environ.get(k) for k in ("GITHUB_RUN_ID", "GITHUB_WORKFLOW", "COLETA_INICIO", "GITHUB_EVENT_NAME")}
    for k in antes:
        os.environ.pop(k, None)
    os.environ.update(env)
    try:
        ini = _dt.fromisoformat(env["COLETA_INICIO"].replace("Z", "+00:00")) if env.get("COLETA_INICIO") else _dt.now(_tz.utc)
        return v.janela_coleta(ini + _td(hours=depois_h))
    finally:
        for k, x in antes.items():
            os.environ.pop(k, None)
            if x is not None:
                os.environ[k] = x
ROBO = {"GITHUB_RUN_ID": "123", "GITHUB_WORKFLOW": "Atualizar dados diariamente", "COLETA_INICIO": "2026-11-19T07:30:00Z"}
check(janela(ROBO, 0.7)[0], "dentro do robô, 42 min depois do início da coleta → entra no ICP")
for ev in ("schedule", "workflow_dispatch"):
    check(janela({**ROBO, "GITHUB_EVENT_NAME": ev}, 0.7)[0], f"execução completa disparada por {ev} → entra no ICP (vale a mesma coleta, não quem disparou)")
check(not janela(ROBO, 2.5)[0], "2,5 h depois do início da coleta → só relatório")
check(not janela({}, 0)[0], "rodada manual (sem ID de coleta) → só relatório")
check(not janela({**ROBO, "GITHUB_WORKFLOW": "Supersalários — conferência manual"}, 0.1)[0], "outro workflow → só relatório")
check(not janela({**ROBO, "COLETA_INICIO": ""}, 0.1)[0], "sem horário de início da coleta → só relatório")

# notas da CEAP: chave completa; sem data na API → nº + valor + CNPJ/CPF; mais de um par possível → ambígua
CJ = "04.990.440/0001-94"
def nota_s(doc, valor, data="2026-10-05", cnpj=CJ): return {"cnpjCpfFornecedor": cnpj, "doc": doc, "data": data, "valor": valor}
def nota_f(doc, valor, data="2026-10-05T00:00:00", cnpj="04990440000194"): return {"cnpjCpfFornecedor": cnpj, "numDocumento": doc, "dataDocumento": data, "valorLiquido": valor}
def casa(site, fonte):
    return v.casar_em_etapas(site, fonte, lambda x: (v._dig(x.get("cnpjCpfFornecedor")), str(x.get("doc") or "").strip(), str(x.get("data"))[:10]),
                             lambda x: (v._dig(x.get("cnpjCpfFornecedor")), str(x.get("numDocumento") or "").strip(), str(x.get("dataDocumento"))[:10]),
                             lambda x: x.get("valor"), lambda x: x.get("valorLiquido"), v.ETAPAS_CAMARA)
check(casa([nota_s("1", 100)], [nota_f("1", 100)])[:4] == (1, [], 0, 0), "nota com data: casa pela chave completa")
check(casa([nota_s("1", 100)], [nota_f("1", 100, data=None)])[:4] == (1, [], 0, 0), "API sem data: casa por nº + valor + CNPJ")
check(casa([nota_s("1", 100)], [nota_f("1", 90, data=None)])[:4] == (0, [], 1, 0), "API sem data e valor diferente: não achada (não conta)")
check(casa([nota_s("1", 100), nota_s("1", 100, data="2026-10-06")], [nota_f("1", 100, data=None), nota_f("1", 100, data=None)])[:4] == (0, [], 0, 2),
      "API sem data e a chave casa com mais de uma nota → ambígua, não conferida")
check(casa([nota_s("1", 100)], [nota_f("1", 100), nota_f("1", 100, data=None)])[:4] == (1, [], 0, 0),
      "registro da fonte usado na chave completa não volta a ser usado na etapa sem data")

# coleta da Câmara: despesas lidas mês a mês, ordenadas, paginando dentro do mês; página que falha → exceção
sys.path.insert(0, str(ROOT / "scripts"))
import coletar_dados as cd  # noqa: E402
class _R:
    def __init__(self, j, st=200): self.j, self.st = j, st
    def raise_for_status(self):
        if self.st != 200: raise RuntimeError(self.st)
    def json(self): return self.j
pedidos = []
def _get_api(params):
    pedidos.append(params)
    if params["mes"] == 2 and params["pagina"] == 1:
        return _R({"dados": [{"codDocumento": "a"}], "links": [{"rel": "next"}]})
    return _R({"dados": [{"codDocumento": f"{params['mes']}-{params['pagina']}"}], "links": []})
lido = cd.despesas_api_por_mes(1, 2025, get=_get_api)
check(len(pedidos) == 13 and len(lido) == 13 and all(p["ordenarPor"] == "dataDocumento" and "mes" in p for p in pedidos),
      "Câmara: lê os 12 meses, ordenados pela data, e pagina dentro do mês")
try:
    cd.despesas_api_por_mes(1, 2025, get=lambda p: _R({}, 504))
    check(False, "Câmara: página que não vem → exceção (leitura parcial não serve)")
except RuntimeError:
    check(True, "Câmara: página que não vem → exceção (leitura parcial não serve)")

print(f"✅ {len(oks)} checagens OK · ❌ {len(erros)} erros")
for e in erros:
    print("❌", e)
sys.exit(1 if erros else 0)
