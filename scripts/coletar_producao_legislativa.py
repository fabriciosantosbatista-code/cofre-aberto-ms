#!/usr/bin/env python3
"""
Cofre Aberto MS — produção legislativa dos deputados federais e senadores de MS na legislatura atual (desde 01/02/2023)

  Câmara dos Deputados  dadosabertos.camara.leg.br/api/v2/proposicoes?idDeputadoAutor=…  (autor ou coautor); para os
                        projetos (PL, PLP, PEC, PDL), /proposicoes/{id}/autores diz quem assinou primeiro (autor principal);
                        codSituacao=1140 = "Transformado em Norma Jurídica"
  Senado Federal        legis.senado.leg.br/dadosabertos/processo?codigoParlamentarAutor=…  (a autoria vem em ordem: o
                        primeiro nome é o autor principal; "normaGerada" diz a lei que o projeto virou)

Conta separado: projetos (de lei, lei complementar, emenda à Constituição e decreto legislativo), requerimentos e o resto
(emendas, pareceres, indicações). "Virou lei" conta os projetos apresentados nesta legislatura que já viraram norma.

Gera dados/producao_legislativa.json; cache dos autores em dados/producao_cache.json.
"""

import json, re, time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from pathlib import Path

import requests

DADOS = Path(__file__).parent.parent / "dados"
SAIDA, CACHE = DADOS / "producao_legislativa.json", DADOS / "producao_cache.json"
INICIO = "2023-02-01"
ANO = date.today().year
CAM = "https://dadosabertos.camara.leg.br/api/v2"
SEN = "https://legis.senado.leg.br/dadosabertos"
H = {"User-Agent": "Mozilla/5.0 (CofreAbertoMS; +https://cofreabertoms.com.br)", "Accept": "application/json"}
PROJETOS = {"PL", "PLP", "PEC", "PDL"}
REQUER = {"REQ", "RQS", "RIC", "INC", "RQN", "INS"}
NOME_TIPO = {"PL": "Projetos de lei", "PLP": "Projetos de lei complementar", "PEC": "Propostas de emenda à Constituição",
             "PDL": "Projetos de decreto legislativo"}


def get(url, params=None, tent=4):
    for t in range(tent):
        try:
            r = requests.get(url, params=params, headers=H, timeout=60)
            if r.status_code == 200:
                return r.json()
            if r.status_code in (400, 404):
                return None
        except (requests.RequestException, ValueError):
            pass
        time.sleep(2 * (t + 1))
    return None


def carregar(nome):
    try:
        return json.load(open(DADOS / nome, encoding="utf-8"))
    except Exception:
        return {}


def listar_camara(dep_id, **extra):
    out, p = [], 1
    while True:
        d = get(f"{CAM}/proposicoes", {"idDeputadoAutor": dep_id, "dataApresentacaoInicio": INICIO, "itens": 100, "pagina": p,
                                       "ordem": "DESC", "ordenarPor": "id", **extra})
        if not d:
            break
        out += d.get("dados") or []
        if not any(l.get("rel") == "next" for l in d.get("links") or []):
            break
        p += 1
    return out


def deputado(p, cache):
    lst = listar_camara(p["id"])
    proj = [x for x in lst if x["siglaTipo"] in PROJETOS]

    def principal(x):
        k = f"c{x['id']}"
        if k not in cache:
            a = (get(f"{CAM}/proposicoes/{x['id']}/autores") or {}).get("dados") or []
            prim = min(a, key=lambda y: y.get("ordemAssinatura") or 99) if a else {}
            cache[k] = str(p["id"]) in (prim.get("uri") or "") or (len(a) == 1 and str(p["id"]) in (a[0].get("uri") or ""))
        return cache[k]

    def situacao(x):
        """situação atual; quem já virou lei fica no cache (não muda mais)"""
        k = f"s{x['id']}"
        if k in cache:
            return cache[k]
        s_ = ((get(f"{CAM}/proposicoes/{x['id']}") or {}).get("dados") or {}).get("statusProposicao") or {}
        txt = (s_.get("descricaoSituacao") or s_.get("descricaoTramitacao") or "").strip()
        if s_.get("codSituacao") == 1140 or "norma jur" in txt.lower():
            cache[k] = txt
        return txt

    with ThreadPoolExecutor(6) as ex:
        flags = list(ex.map(principal, proj))
        sits = list(ex.map(situacao, proj))
    itens = []
    for x, pr, st in zip(proj, flags, sits):
        itens.append({"sigla": f"{x['siglaTipo']} {x['numero']}/{x['ano']}", "tipo": x["siglaTipo"], "ementa": (x.get("ementa") or "").strip(),
                      "data": (x.get("dataApresentacao") or "")[:10], "principal": pr, "lei": "norma jur" in st.lower(), "norma": None, "situacao": st,
                      "link": f"https://www.camara.leg.br/propostas-legislativas/{x['id']}"})
    return resumo(p, "federal", itens, sum(1 for x in lst if x["siglaTipo"] in REQUER), len(lst))


def senador(p, cache):
    lst = get(f"{SEN}/processo", {"codigoParlamentarAutor": p["id"], "dataInicioApresentacao": INICIO}) or []
    sobrenome = p["nome"].split()[-1].lower()
    itens, req = [], 0
    for x in lst:
        sig = (x.get("identificacao") or "").split()[0]
        if sig in REQUER:
            req += 1
        if sig not in PROJETOS:
            continue
        aut = (x.get("autoria") or "").split(",")[0].lower()
        itens.append({"sigla": x["identificacao"], "tipo": sig, "ementa": (x.get("ementa") or "").strip(), "data": x.get("dataApresentacao"),
                      "principal": sobrenome in aut, "lei": "NORMA JUR" in (x.get("situacaoAtual") or "").upper(), "norma": x.get("normaGerada"),
                      "situacao": (x.get("situacaoAtual") or "").capitalize(),
                      "link": f"https://www25.senado.leg.br/web/atividade/materias/-/materia/{x.get('codigoMateria')}"})
    itens.sort(key=lambda i: i["data"] or "", reverse=True)
    return resumo(p, "senador", itens, req, len(lst))


def resumo(p, grupo, itens, req, total):
    princ = [i for i in itens if i["principal"]]
    return {"grupo": grupo, "id": p["id"], "nome": p["nome"], "partido": p.get("partido"),
            "proposicoes": total, "requerimentos": req, "outras": total - req - len(itens),
            "projetos": len(itens), "projetosPrincipal": len(princ),
            "projetosNoAno": sum(1 for i in princ if (i["data"] or "").startswith(str(ANO))),
            "porTipo": {t: sum(1 for i in princ if i["tipo"] == t) for t in ("PL", "PLP", "PEC", "PDL")},
            "leis": len([i for i in itens if i["lei"]]), "leisPrincipal": len([i for i in princ if i["lei"]]),
            "listaLeis": [i for i in itens if i["lei"]][:30],
            "recentes": [{k: i.get(k) for k in ("sigla", "tipo", "ementa", "data", "situacao", "link")} for i in princ[:8]]}


def main():
    cache = carregar("producao_cache.json")
    feds = [{"id": d["id"], "nome": d["nome"], "partido": d.get("partido")} for d in carregar("deputados_federais_ms.json").get("deputados") or []]
    sens = [{"id": s["id"], "nome": s["nome"], "partido": s.get("partido")} for s in carregar("senadores_ms.json").get("senadores") or []]
    out, falhas = [], []
    for p in feds:
        try:
            out.append(deputado(p, cache))
        except Exception as e:
            falhas.append(f"{p['nome']}: {e}")
    for p in sens:
        try:
            out.append(senador(p, cache))
        except Exception as e:
            falhas.append(f"{p['nome']}: {e}")
    CACHE.write_text(json.dumps(cache, separators=(",", ":")), encoding="utf-8")
    if not out:
        print("⚠️ produção legislativa: nada coletado — dados anteriores mantidos", falhas)
        return
    SAIDA.write_text(json.dumps({"ultimaAtualizacao": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"), "inicio": INICIO, "ano": ANO,
                                 "fonte": "Câmara dos Deputados e Senado Federal — dados abertos das proposições",
                                 "fonteUrl": "https://dadosabertos.camara.leg.br/", "tipos": NOME_TIPO, "falhas": falhas,
                                 "parlamentares": out}, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    for p in out:
        print(f"  {p['nome']}: {p['projetosPrincipal']} projetos como autor principal ({p['projetos']} com coautoria), "
              f"{p['leis']} viraram lei, {p['requerimentos']} requerimentos")
    print(f"✅ producao_legislativa.json — {len(out)} parlamentares" + (f"; falhas: {falhas}" if falhas else ""))


if __name__ == "__main__":
    main()
