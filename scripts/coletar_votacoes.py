#!/usr/bin/env python3
"""
Cofre Aberto MS — participação dos deputados federais e senadores de MS nas votações nominais do plenário

  Câmara  lista as votações do plenário no ano (dadosabertos.camara.leg.br /votacoes, idOrgao=180) e, em cada
          uma, os votos (/votacoes/{id}/votos). Só as votações nominais têm votos; as simbólicas vêm vazias.
          Guarda em cache o que já foi lido (votação passada não muda).
  Senado  votações nominais de cada senador no ano (legis.senado.leg.br /senador/{código}/votacoes), com o voto.

Para cada parlamentar: votações nominais no ano, quantas votou, ausências (justificadas ou não) e as últimas
votações com o voto. Não é "presença em sessão" (as Casas não publicam isso de forma simples): é participação
nas votações nominais do plenário — o momento em que o voto de cada um fica registrado.

Gera dados/votacoes.json; cache em dados/votacoes_cache.json.
"""

import json, sys, time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from pathlib import Path

import requests

DADOS = Path(__file__).parent.parent / "dados"
CACHE, SAIDA = DADOS / "votacoes_cache.json", DADOS / "votacoes.json"
H = {"Accept": "application/json", "User-Agent": "Mozilla/5.0 (CofreAbertoMS; +https://cofreabertoms.com.br)"}
CAM = "https://dadosabertos.camara.leg.br/api/v2"
SEN = "https://legis.senado.leg.br/dadosabertos"
HOJE = date.today()
ANO = HOJE.year
VOTOU = {"SIM", "NÃO", "NAO", "ABSTENÇÃO", "ABSTENCAO", "OBSTRUÇÃO", "OBSTRUCAO", "ARTIGO 17", "VOTOU"}


def get(url, params=None, tent=5):
    for t in range(tent):
        try:
            r = requests.get(url, params=params, headers=H, timeout=60)
            if r.status_code == 200:
                return r.json()
            if r.status_code in (400, 404):
                return {"dados": [], "naoEncontrado": True}  # sem registro: não é votação nominal
        except (requests.RequestException, ValueError):
            pass
        time.sleep(2 * (t + 1))
    return None


def carregar(nome):
    try:
        return json.load(open(DADOS / nome, encoding="utf-8"))
    except Exception:
        return {}


def camara(cache):
    deps = {str(d["id"]): d["nome"] for d in carregar("deputados_federais_ms.json").get("deputados", [])}
    cv = cache.setdefault("camara", {})
    lista = []
    ini = date(ANO, 1, 1)
    while ini <= HOJE:  # a API pede janelas curtas: mês a mês
        fim = min(HOJE, (date(ini.year, ini.month % 12 + 1, 1) if ini.month < 12 else date(ini.year + 1, 1, 1)) - timedelta(days=1))
        pag = 1
        while True:
            j = get(f"{CAM}/votacoes", {"idOrgao": 180, "dataInicio": ini.isoformat(), "dataFim": fim.isoformat(), "itens": 200, "pagina": pag})
            if not j:
                break
            lista += j.get("dados") or []
            if not any(l.get("rel") == "next" for l in j.get("links") or []):
                break
            pag += 1
        ini = fim + timedelta(days=1)
    novas = [v for v in lista if v["id"] not in cv or (v.get("data") or "") >= (HOJE - timedelta(days=3)).isoformat()]
    print(f"  Câmara: {len(lista)} votações do plenário em {ANO}, {len(novas)} para ler")

    def votos(v):
        j = get(f"{CAM}/votacoes/{v['id']}/votos")
        return v, (j or {}).get("dados")

    with ThreadPoolExecutor(4) as ex:
        for v, vs in ex.map(votos, novas):
            if vs is None:
                continue  # falhou: tenta de novo na próxima coleta
            cv[v["id"]] = {"data": v.get("data"), "descricao": (v.get("descricao") or "").strip()[:220], "nominal": bool(vs), "total": len(vs),
                           "votos": {str(x["deputado_"]["id"]): x.get("tipoVoto") for x in vs if str(x["deputado_"]["id"]) in deps}}
    nominais = sorted((v for k, v in cv.items() if v.get("nominal") and (v.get("data") or "").startswith(str(ANO))), key=lambda v: v["data"])
    out = []
    for i, nome in deps.items():
        votou = [v for v in nominais if (v["votos"].get(i) or "").upper() in VOTOU]
        out.append({"grupo": "federal", "id": i, "nome": nome, "nominais": len(nominais), "votou": len(votou),
                    "ausente": len(nominais) - len(votou), "justificadas": None,
                    "participacao": round(len(votou) / len(nominais) * 100, 1) if nominais else None,
                    "ultimas": [{"data": v["data"], "descricao": v["descricao"], "voto": v["votos"].get(i) or "Não votou"} for v in nominais[-15:][::-1]]})
    return out


def senado():
    out = []
    for s in carregar("senadores_ms.json").get("senadores", []):
        j = get(f"{SEN}/senador/{s['id']}/votacoes", {"ano": ANO})
        vs = (((j or {}).get("VotacaoParlamentar") or {}).get("Parlamentar") or {}).get("Votacoes", {}).get("Votacao") or []
        if isinstance(vs, dict):
            vs = [vs]
        if not j:
            print(f"  ⚠️ Senado: sem resposta para {s['nome']}")
            continue
        vs = sorted(vs, key=lambda v: (v.get("SessaoPlenaria") or {}).get("DataSessao") or "")
        voto = lambda v: (v.get("SiglaDescricaoVoto") or v.get("DescricaoVoto") or "").strip()
        votou = [v for v in vs if voto(v).upper() in VOTOU]
        # ausência justificada: licença, missão oficial, atividade parlamentar (LS, LP, MIS, AP, LAP...)
        just = [v for v in vs if voto(v).upper() in {"LS", "LP", "LAP", "MIS", "AP", "LG", "LC", "LAU", "REP", "NA"}]
        presente = [v for v in vs if voto(v).upper() == "P-NRV"]  # estava no plenário e não votou (ex.: presidindo a sessão)
        out.append({"grupo": "senador", "id": str(s["id"]), "nome": s["nome"], "nominais": len(vs), "votou": len(votou),
                    "presenteSemVoto": len(presente), "ausente": len(vs) - len(votou) - len(presente), "justificadas": len(just),
                    "participacao": round(len(votou) / len(vs) * 100, 1) if vs else None,
                    "ultimas": [{"data": (v.get("SessaoPlenaria") or {}).get("DataSessao"),
                                 "descricao": f"{(v.get('Materia') or {}).get('DescricaoIdentificacao') or ''} — {v.get('DescricaoVotacao') or ''}".strip(" —")[:220],
                                 "voto": voto(v) or "—"} for v in vs[-15:][::-1]]})
    return out


def main():
    cache = carregar("votacoes_cache.json")
    anterior = carregar("votacoes.json")
    try:
        cam = camara(cache)
    except Exception as e:
        print(f"  ⚠️ Câmara: {e} — mantido o anterior")
        cam = [p for p in anterior.get("parlamentares", []) if p["grupo"] == "federal"]
    CACHE.write_text(json.dumps(cache, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    try:
        sen = senado()
    except Exception as e:
        print(f"  ⚠️ Senado: {e} — mantido o anterior")
        sen = []
    if not sen:
        sen = [p for p in anterior.get("parlamentares", []) if p["grupo"] == "senador"]
    if not cam and not sen:
        print("❌ sem votações — arquivo mantido")
        sys.exit(1)
    SAIDA.write_text(json.dumps({"ano": ANO, "ultimaAtualizacao": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
                                 "fonte": "Câmara dos Deputados (dadosabertos.camara.leg.br) e Senado Federal (legis.senado.leg.br) — votações nominais do plenário",
                                 "parlamentares": cam + sen}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"✅ votacoes.json — {len(cam)} deputados federais, {len(sen)} senadores de MS")
    for p in cam + sen:
        print(f"   {p['nome']}: votou em {p['votou']} de {p['nominais']} ({p['participacao']}%)")


if __name__ == "__main__":
    main()
