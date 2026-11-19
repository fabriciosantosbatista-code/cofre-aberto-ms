#!/usr/bin/env python3
"""
Cofre Aberto MS — Contratos do Governo do Estado de MS e quem paga cada empresa

Portal da Transparência de MS (token anônimo /Auth/Token, o mesmo que o site
público usa):
  contratos  todos os contratos celebrados no ano, órgão por órgão
             (transpctpublico/contratopublico/consultar): fornecedor, CNPJ,
             valor atual, modalidade, vigência e renovações
  obras      contratos de obras (transpcontrato/ContratosEkronos): objeto,
             prazo inicial, dias aditados e paralisados, % executado
  pagadores  para as empresas que a Auditoria acompanha de perto (sócio
             servidor, empresa punida, CNPJ irregular, MEI, capital baixo,
             empresa nova), qual órgão do Estado pagou e quanto
             (transpdespesas/despesaporcredores)

Gera dados/governo_ms_contratos.json.
"""

import json, re, sys, time
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import coletar_governo_ms as g  # noqa: E402

DADOS = Path(__file__).parent.parent / "dados"
ANO = date.today().year
CT = "/k0156/transpctpublico/v1/contratopublico/consultar"


def dig(t):
    return re.sub(r"\D", "", str(t or ""))


def iso(br):
    m = re.match(r"(\d{2})/(\d{2})/(\d{4})", br or "")
    return f"{m[3]}-{m[2]}-{m[1]}" if m else (br[:10] if br and re.match(r"\d{4}-\d{2}-\d{2}", br) else None)


def carregar(nome):
    try:
        return json.load(open(DADOS / nome, encoding="utf-8"))
    except Exception:
        return {}


def contratos():
    orgaos = g.api(CT, {"exercicio": ANO})["data"]["contrato"]
    out = []
    for o in orgaos:
        pag, total = 1, 1
        while pag <= total:
            j = g.api(CT, {"exercicio": ANO, "orgao": o["codigo"], "pagina": pag})
            total = (j.get("paginacao") or {}).get("totalDePaginas") or 1
            for c in j["data"].get("contrato") or []:
                vig = c.get("vigencias") or []
                if not vig:
                    continue
                atual = vig[-1]
                for f in c.get("fornecedores") or [{}]:
                    out.append({"orgao": c.get("orgao"), "orgaoNome": c.get("descricaoOrgao"), "numero": c.get("numeroContrato"),
                                "fornecedor": re.sub(r"\s+", " ", f.get("razaoSocial") or "").strip(), "cnpj": dig(f.get("cpfCnpj")),
                                "valor": round(atual.get("valorAtualContrato") or 0, 2), "valorInicial": round(vig[0].get("valorAtualContrato") or 0, 2),
                                "modalidade": (atual.get("modalidade") or "").strip(), "situacao": atual.get("situacao"),
                                "inicio": iso(vig[0].get("inicioVigenciaComMascara")), "fim": iso(atual.get("fimVigenciaComMascara")),
                                "renovacoes": sum(1 for v in vig if v.get("renovado") == "SIM")})
            pag += 1
        print(f"  {o['orgao']}: {o['totalCelebrado']} contratos")
    return orgaos, out


def obras():
    # o portal repete as mesmas obras em páginas seguidas (e diz que há mais): guarda cada obra uma vez
    # (número + processo + CNPJ + órgão) e para quando uma página não traz nenhuma obra nova
    out, vistos, pag = [], set(), 1
    while True:
        j = g.api("/d0371/transpcontrato/v1/ContratosEkronos", {"ano": ANO, "pageno": pag, "pagesize": 2000, "exportarcsv": "false"})
        novos = 0
        for x in j.get("data") or []:
            k = (x.get("numeroContrato"), x.get("numeroProcesso"), dig(x.get("cnpjCpf")), x.get("orgao"))
            if k in vistos:
                continue
            vistos.add(k)
            novos += 1
            out.append({"numero": x.get("numeroContrato"), "processo": x.get("numeroProcesso"), "orgao": x.get("orgao"),
                        "fornecedor": re.sub(r"\s+", " ", x.get("nome") or "").strip(), "cnpj": dig(x.get("cnpjCpf")),
                        "objeto": re.sub(r"\s+", " ", x.get("objeto") or "").strip()[:300], "valor": round(x.get("valorAtualContrato") or 0, 2),
                        "prazoInicial": x.get("prazoInicialExecucaoDias"), "diasAditados": x.get("diasAditados") or 0,
                        "diasParalisados": x.get("diasParalisados") or 0, "executado": x.get("percentualExecutado"),
                        "situacao": x.get("situacao"), "inicio": iso(x.get("inicioObra")), "fim": iso(x.get("fimObra")),
                        "municipios": x.get("municipios")})
        if not novos or not (j.get("pagination") or {}).get("has_next") or pag >= 50:
            break
        pag += 1
    print(f"  obras: {len(out)} contratos de obra ({pag} páginas lidas)")
    return out


def pagadores():
    """Para a lista de vigilância da Auditoria: qual órgão do Estado pagou a empresa."""
    cad = carregar("cnpj_cache.json")
    vig = {x["cnpj"] for x in carregar("servidores_socios.json").get("achados", [])}
    vig |= {x["cnpj"] for x in carregar("sancoes.json").get("empresas", [])}
    for c, i in cad.items():
        if i.get("naoEncontrado"):
            continue
        if (i.get("situacao") or "ATIVA") != "ATIVA" or i.get("mei") or (i.get("capital") is not None and i["capital"] <= 10000) \
                or (i.get("abertura") or "") >= f"{ANO - 1}-01-01":
            vig.add(c)
    ini, fim = date(ANO, 1, 1), date.today()
    cred = g.despesas_periodo("despesapordatacredores", ini, fim, 40000)["despesas"]
    # agências de publicidade (aba Publicidade): também quero saber qual órgão do Estado paga cada uma
    try:
        from gerar_publicidade import AGENCIA, NAO
        vig |= {dig(c["cpfCnpj"]) for c in cred if AGENCIA.search(c.get("credor") or "") and not NAO.search(c.get("credor") or "")}
    except Exception as e:
        print(f"  ⚠️ agências de publicidade: {e}")
    hashes = {dig(c["cpfCnpj"]): c for c in cred if len(dig(c["cpfCnpj"])) == 14}
    alvo = [c for c in vig if c in hashes and (hashes[c].get("pago") or hashes[c].get("empenhado"))]
    anterior = carregar("governo_ms_contratos.json")
    antes, quando = anterior.get("pagadores") or {}, dict(anterior.get("pagadoresEm") or {})
    # checkpoint: começa pelas empresas atualizadas há mais tempo (ou nunca) — se o tempo acabar, as que ficaram para trás
    # mantêm o valor anterior e são as primeiras da próxima coleta
    alvo.sort(key=lambda c: (quando.get(c) or "", c))
    out, vazios, erros, t0 = {}, 0, 0, time.monotonic()
    LIMITE_MIN = 20  # minutos para este passo (o passo do workflow tem 30)
    import threading
    from concurrent.futures import ThreadPoolExecutor, as_completed
    trava, estado = threading.Lock(), {"seguidos": 0, "feitos": 0, "parar": False}

    def consulta(c):
        if estado["parar"]:
            return c, None, "não consultada"
        h = hashes[c]
        for t in range(2):  # a API às vezes devolve a lista vazia: tenta de novo e, se seguir vazia, fica o valor anterior
            try:
                j = g.api(g.DESPESAS + "/despesaporcredores", {"credor": h["hash"], "nomeCredor": h["credor"],
                                                               "dataInicio": g.br(ini), "dataFim": g.br(fim)})
                lst = [[re.sub(r"\s+", " ", d.get("orgao") or "").strip(), round(d.get("pago") or 0, 2), round(d.get("empenhado") or 0, 2),
                        d.get("elementoDespesa"), d.get("tipoLicitacao")] for d in j["data"][0].get("despesas") or []]
            except Exception as e:
                with trava:  # espera crescente a cada erro seguido (2, 4, 8… até 60 s), para não insistir num portal lento
                    estado["seguidos"] += 1
                    espera = min(60, 2 ** estado["seguidos"])
                time.sleep(espera)
                return c, None, str(e)
            with trava:
                estado["seguidos"] = 0
            if lst:
                return c, lst, None
            time.sleep(2)
        return c, [], None

    # no máximo 4 consultas ao mesmo tempo; 429/Retry-After e 5xx já são tratados em g.api (token novo, espera)
    with ThreadPoolExecutor(4) as ex:
        futuros = [ex.submit(consulta, c) for c in alvo]
        for f in as_completed(futuros):
            c, lst, erro = f.result()
            estado["feitos"] += 1
            if erro and erro != "não consultada":
                erros += 1
                print(f"  ⚠️ pagadores de {c}: {erro}")
            if lst:
                out[c] = lst
                quando[c] = date.today().isoformat()
            elif antes.get(c):
                out[c] = antes[c]
                vazios += lst == []
            # trava de segurança: passou do limite de tempo, ou as 10 primeiras deram erro → para e fica o valor anterior
            if not estado["parar"] and (time.monotonic() - t0 > LIMITE_MIN * 60 or (estado["feitos"] == 10 and erros >= 10)):
                estado["parar"] = True
                print(f"  ⚠️ pagadores: interrompido em {estado['feitos']} de {len(alvo)} ({'erro em todas' if erros >= 10 else 'tempo esgotado'}) — mantidos os anteriores")
    minutos = (time.monotonic() - t0) / 60
    feitas = sum(1 for c in alvo if quando.get(c) == date.today().isoformat())
    print(f"  pagadores: {feitas} consultadas em {minutos:.1f} min ({feitas / minutos if minutos else 0:.0f} por minuto, 4 em paralelo)")
    if vazios:
        print(f"  pagadores: {vazios} respostas vazias — mantido o valor anterior")
    print(f"  pagadores: {len(out)} de {len(alvo)} empresas acompanhadas")
    pagadores.quando = {c: quando[c] for c in out if c in quando}
    return out


def main():
    anterior = carregar("governo_ms_contratos.json")
    orgaos, ct = contratos()
    ob = obras()
    try:
        pg = pagadores()
    except Exception as e:
        print(f"  ⚠️ pagadores: {e} — mantidos os anteriores")
        pg = anterior.get("pagadores") or {}
    if len(ct) < 0.5 * len(anterior.get("contratos") or []):
        print(f"❌ só {len(ct)} contratos (antes {len(anterior['contratos'])}) — arquivo mantido")
        sys.exit(1)
    (DADOS / "governo_ms_contratos.json").write_text(json.dumps({
        "ano": ANO, "ultimaAtualizacao": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "fonte": "Portal da Transparência do Estado de MS — contratos públicos, contratos de obras e despesas por credor",
        "totalCelebrado": sum(o.get("valorCelebrado") or 0 for o in orgaos), "orgaos": [
            {"codigo": o["codigo"], "sigla": o["orgao"], "nome": o["nome"], "contratos": o["totalCelebrado"], "valor": o["valorCelebrado"]}
            for o in sorted(orgaos, key=lambda o: -(o.get("valorCelebrado") or 0))],
        "contratos": sorted(ct, key=lambda c: -c["valor"]), "obras": sorted(ob, key=lambda o: -o["valor"]), "pagadores": pg,
        "pagadoresEm": getattr(pagadores, "quando", None) or anterior.get("pagadoresEm") or {}},
        ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"✅ governo_ms_contratos.json — {len(ct)} contratos, {len(ob)} obras, pagadores de {len(pg)} empresas")


if __name__ == "__main__":
    main()
