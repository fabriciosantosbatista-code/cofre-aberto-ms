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

print(f"✅ {len(oks)} checagens OK · ❌ {len(erros)} erros")
for e in erros:
    print("❌", e)
sys.exit(1 if erros else 0)
