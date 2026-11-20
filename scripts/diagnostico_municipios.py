#!/usr/bin/env python3
"""Cofre Aberto MS — diagnóstico dos portais de transparência dos 79 municípios de MS (só leitura).

Roda no GitHub Actions (workflow "Diagnóstico dos municípios"), de onde o robô coletaria. Não grava nada no
repositório: imprime uma linha "MUN|{json}" por município e um resumo. Para cada município:
  - lista oficial: Siconfi (Tesouro Nacional), com código IBGE, CNPJ e população;
  - site da prefeitura: Wikidata (P856) e os endereços .ms.gov.br de costume; lê a página inicial e procura o link do
    portal da transparência;
  - fornecedor do portal (prefeitura e câmara): pelos links e por endereços-padrão de cada fornecedor (Fiorilli SCPI,
    IPM Atende, Elotech Oxy, Betha, ...); status HTTP e tempo de resposta;
  - formato: JSON (endpoint conhecido do fornecedor respondeu), ou só tela;
  - fontes nacionais: Siconfi (RREO 2026, RGF 2026, DCA 2025) de cada município.
Educado com os servidores: uma requisição por vez em cada município, tempo-limite curto, poucos endereços por cidade.
"""
import concurrent.futures as cf, json, re, time, unicodedata, urllib.parse
import requests

UA = {"User-Agent": "Mozilla/5.0 (CofreAbertoMS; transparencia publica; diagnostico)", "Accept": "*/*"}
TO = (8, 15)
S = requests.Session()
S.headers.update(UA)


def slug(n, sep=""):
    n = unicodedata.normalize("NFKD", n).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", sep, n).strip(sep)


def get(url, **kw):
    t = time.monotonic()
    try:
        r = S.get(url, timeout=TO, allow_redirects=True, **kw)
        return r, round(time.monotonic() - t, 1), None
    except Exception as e:
        return None, round(time.monotonic() - t, 1), type(e).__name__


FORNECEDORES = [  # (nome, regex no endereço)
    ("Fiorilli SCPI", r"rcmsuporte|:8079|scpi|/transparenciacm|fiorilli"),
    ("IPM Atende", r"atende\.net"),
    ("Elotech Oxy", r"elotech"),
    ("Betha", r"betha"),
    ("Agili", r"agili"),
    ("Quality Sistemas", r"qualitysistemas|portaltransparencia\.quality"),
    ("Portal Fácil", r"portalfacil"),
    ("GovBR/Interlegis (SAPL)", r"sapl\.|\.leg\.br/(?:transparencia)?"),
    ("Sintese/Tecnosweb", r"tecnos|sintese"),
    ("Dueto", r"dueto"),
    ("Assessor Público", r"assessorpublico"),
    ("Siga/E-gov", r"egov|e-gov"),
    ("Transparência Nuvem/GDS", r"nuvem|gdstec"),
]


def fornecedor(url):
    for nome, rx in FORNECEDORES:
        if re.search(rx, url or "", re.I):
            return nome
    return None


def links_transparencia(html, base):
    out = []
    for m in re.finditer(r'href=["\']([^"\'#]+)["\']', html or "", re.I):
        h = m.group(1)
        if re.search(r"transpar|scpi|8079|atende\.net|elotech|betha|portal.?da.?transp", h, re.I):
            out.append(urllib.parse.urljoin(base, h))
    return list(dict.fromkeys(out))[:12]


def descobre_portal(candidatos_site, padroes, cm=False):
    """Primeiro site que responde; links de transparência nele; fornecedor; testes nos endereços-padrão."""
    res = {"site": None, "siteStatus": None, "portal": None, "fornecedor": None, "status": None, "tempo": None, "erro": None}
    for u in candidatos_site:
        r, t, err = get(u)
        if r is not None and r.status_code < 400 and len(r.text) > 300:
            res.update(site=r.url, siteStatus=r.status_code)
            ls = links_transparencia(r.text, r.url)
            pref = [l for l in ls if fornecedor(l)] or ls
            if pref:
                res["portal"] = pref[0]
                res["fornecedor"] = fornecedor(pref[0])
            break
        res["erro"] = err or (r.status_code if r is not None else None)
    for nome, u in padroes:  # endereço-padrão do fornecedor responde?
        if res["fornecedor"] and res["fornecedor"] != nome and res["portal"]:
            continue
        r, t, err = get(u)
        if r is not None and r.status_code < 400 and len(r.text) > 200:
            if not res["portal"] or not res["fornecedor"]:
                res.update(portal=r.url, fornecedor=nome)
            break
    if res["portal"]:
        r, t, err = get(res["portal"])
        res.update(status=(r.status_code if r is not None else None), tempo=t, erro=err)
        if r is not None and not res["fornecedor"]:
            res["fornecedor"] = fornecedor(r.url) or ("próprio/outro: " + urllib.parse.urlparse(r.url).netloc)
    return res


def formato(p):
    """Endpoint de dados conhecido do fornecedor responde com JSON?"""
    f, u = p.get("fornecedor") or "", p.get("portal") or ""
    if not u:
        return None
    if f.startswith("Fiorilli"):
        m = re.match(r"(https?://[^/]+/transparencia(?:cm)?)", u)
        if m:
            r, t, err = get(m.group(1) + "/VersaoJson/Despesas/?Listagem=DespesasGerais&DiaInicioPeriodo=01&MesInicialPeriodo=01"
                                          "&DiaFinalPeriodo=31&MesFinalPeriodo=01&Ano=2026&Empresa=1")
            if r is not None and r.status_code == 200 and r.text.strip()[:1] in "[{":
                return "JSON (VersaoJson)"
            return "tela (VersaoJson sem resposta)"
    if f == "IPM Atende":
        return "tela + exportação CSV/JSON (a confirmar por endpoint)"
    if f == "Elotech Oxy":
        host = urllib.parse.urlparse(u).netloc
        r, t, err = get(f"https://{host}/portaltransparencia-api/api/entidades")
        if r is not None and r.status_code == 200 and r.text.strip()[:1] in "[{":
            return "JSON (portaltransparencia-api)"
        return "tela (API sem resposta)"
    if f == "Betha":
        return "tela + dados abertos Betha (a confirmar)"
    return "tela/PDF (sem endpoint conhecido)"


def siconfi(ibge):
    base = "https://apidatalake.tesouro.gov.br/ords/siconfi/tt"
    out = {}
    for nome, url in (("rreo2026", f"{base}/rreo?an_exercicio=2026&nr_periodo=4&co_tipo_demonstrativo=RREO&no_anexo=RREO-Anexo%2001&id_ente={ibge}"),
                      ("rgf2026", f"{base}/rgf?an_exercicio=2026&in_periodicidade=Q&nr_periodo=2&co_tipo_demonstrativo=RGF&no_anexo=RGF-Anexo%2001&co_poder=E&id_ente={ibge}"),
                      ("dca2025", f"{base}/dca?an_exercicio=2025&no_anexo=DCA-Anexo%20I-C&id_ente={ibge}")):
        r, t, err = get(url)
        try:
            out[nome] = len(r.json().get("items") or []) if r is not None and r.status_code == 200 else (err or r.status_code)
        except Exception:
            out[nome] = "resposta inválida"
    return out


def pncp(cnpj):
    """Contratos de 2026 que a prefeitura (CNPJ do ente) publicou no PNCP — um pedido, só o total."""
    if not cnpj:
        return None
    r, t, err = get("https://pncp.gov.br/api/consulta/v1/contratos", params={"dataInicial": "20260101", "dataFinal": "20261119",
                                                                             "cnpjOrgao": cnpj, "pagina": 1, "tamanhoPagina": 10})
    if r is None:
        return err
    if r.status_code == 204:
        return 0
    try:
        return r.json().get("totalRegistros") if r.status_code == 200 else r.status_code
    except Exception:
        return "resposta inválida"


def wikidata_sites():
    q = """SELECT ?ibge ?site WHERE { ?m wdt:P1585 ?ibge; wdt:P856 ?site . FILTER(STRSTARTS(?ibge, "50")) }"""
    r, t, err = get("https://query.wikidata.org/sparql", params={"query": q, "format": "json"})
    sites = {}
    try:
        for b in r.json()["results"]["bindings"]:
            sites.setdefault(b["ibge"]["value"], []).append(b["site"]["value"])
    except Exception:
        pass
    return sites


def municipio(e, wd, camaras_conhecidas):
    nome, ibge = e["ente"], str(e["cod_ibge"])
    s, sh = slug(nome), slug(nome, "-")
    site_pm = (wd.get(ibge) or []) + [f"https://www.{s}.ms.gov.br/", f"https://{s}.ms.gov.br/", f"https://www.pm{s}.ms.gov.br/"]
    pad_pm = [("Fiorilli SCPI", f"http://pm{s}.rcmsuporte.com.br:8079/transparencia/"), ("IPM Atende", f"https://{s}.atende.net/transparencia/"),
              ("Elotech Oxy", f"https://{s}.oxy.elotech.com.br/portaltransparencia/")]
    site_cm = ([camaras_conhecidas[sh]] if sh in camaras_conhecidas else []) + [
        f"https://camara{s}.ms.gov.br/", f"https://www.camara{s}.ms.gov.br/", f"https://cm{s}.ms.gov.br/", f"https://www.{s}.ms.leg.br/"]
    pad_cm = [("Fiorilli SCPI", f"http://pm{s}.rcmsuporte.com.br:8079/transparenciacm/"), ("IPM Atende", f"https://camara{s}.atende.net/transparencia/")]
    pm = descobre_portal(site_pm, pad_pm)
    pm["formato"] = formato(pm)
    cm = descobre_portal(site_cm, pad_cm, cm=True)
    cm["formato"] = formato(cm)
    return {"municipio": nome, "ibge": ibge, "cnpj": e.get("cnpj"), "populacao": e.get("populacao"),
            "prefeitura": pm, "camara": cm, "siconfi": siconfi(ibge), "pncpContratos2026": pncp(e.get("cnpj"))}


def main():
    t0 = time.monotonic()
    r, t, err = get("https://apidatalake.tesouro.gov.br/ords/siconfi/tt/entes")
    entes = sorted([x for x in r.json()["items"] if x.get("uf") == "MS" and x.get("esfera") == "M"], key=lambda x: x["ente"])
    wd = wikidata_sites()
    print(f"entes={len(entes)} wikidata_sites={len(wd)}", flush=True)
    try:
        import glob
        camaras = {}
        for f in glob.glob("dados/camaras/*.json"):
            d = json.load(open(f, encoding="utf-8"))
            camaras[f.split("/")[-1][:-5]] = d.get("portal") or d.get("portalOficial") or d.get("url")
    except Exception:
        camaras = {}
    with cf.ThreadPoolExecutor(max_workers=8) as ex:
        for res in ex.map(lambda e: municipio(e, wd, camaras), entes):
            print("MUN|" + json.dumps(res, ensure_ascii=False), flush=True)
    print(f"FIM em {round(time.monotonic() - t0)} s", flush=True)


if __name__ == "__main__" and __import__("os").environ.get("DIAG") not in ("2", "3", "4"):
    main()


# ---------------------------------------------------------------- 2ª passada (DIAG=2): Fiorilli, Siconfi, PNCP
def fiorilli_empresas(base):
    """Códigos de entidade (Empresa) do portal Fiorilli: lidos do seletor da página inicial."""
    r, t, err = get(base + "/")
    if r is None or r.status_code >= 400:
        return [], (err or (r.status_code if r is not None else None)), t
    ops = re.findall(r'<option[^>]*value=["\']?(\d{1,3})["\']?[^>]*>([^<]{2,80})</option>', r.text, re.I)
    return list(dict.fromkeys(ops))[:12], r.status_code, t


def fiorilli_json(base, empresa, ano=2026):
    out = {}
    for nome, q in (("despesas", f"Despesas/?Listagem=DespesasGerais&DiaInicioPeriodo=01&MesInicialPeriodo=01&DiaFinalPeriodo=31&MesFinalPeriodo=01&Ano={ano}&Exercicio={ano}&Empresa={empresa}"),
                    ("servidores", f"Pessoal/?Listagem=Servidores&Empresa={empresa}&Ano={ano}&Exercicio={ano}&MesInicialPeriodo=10&MesFinalPeriodo=10")):
        r, t, err = get(f"{base}/VersaoJson/{q}")
        if r is None:
            out[nome] = err
            continue
        try:
            j = r.json()
            n = len(j) if isinstance(j, list) else len(next((v for v in j.values() if isinstance(v, list)), [])) if isinstance(j, dict) else 0
            out[nome] = {"json": True, "registros": n, "tempo": t}
        except Exception:
            out[nome] = {"json": False, "status": r.status_code, "tempo": t}
    return out


def siconfi2(ibge):
    base = "https://apidatalake.tesouro.gov.br/ords/siconfi/tt"
    out = {}
    for nome, url in (("rreo2026_b3", f"{base}/rreo?an_exercicio=2026&nr_periodo=3&co_tipo_demonstrativo=RREO&id_ente={ibge}"),
                      ("rreo2026_b4", f"{base}/rreo?an_exercicio=2026&nr_periodo=4&co_tipo_demonstrativo=RREO&id_ente={ibge}"),
                      ("rgf2026_s1", f"{base}/rgf?an_exercicio=2026&in_periodicidade=S&nr_periodo=1&co_tipo_demonstrativo=RGF&co_poder=E&id_ente={ibge}"),
                      ("rgf2026_q2", f"{base}/rgf?an_exercicio=2026&in_periodicidade=Q&nr_periodo=2&co_tipo_demonstrativo=RGF&co_poder=E&id_ente={ibge}"),
                      ("rgf2026_s1_leg", f"{base}/rgf?an_exercicio=2026&in_periodicidade=S&nr_periodo=1&co_tipo_demonstrativo=RGF&co_poder=L&id_ente={ibge}"),
                      ("rgf2026_q2_leg", f"{base}/rgf?an_exercicio=2026&in_periodicidade=Q&nr_periodo=2&co_tipo_demonstrativo=RGF&co_poder=L&id_ente={ibge}")):
        r, t, err = get(url)
        try:
            out[nome] = len(r.json().get("items") or []) if r is not None and r.status_code == 200 else (err or r.status_code)
        except Exception:
            out[nome] = "resposta inválida"
    return out


def pncp2(cnpj):
    t0 = time.monotonic()
    for tent in range(2):
        try:
            r = S.get("https://pncp.gov.br/api/consulta/v1/contratos", params={"dataInicial": "20260101", "dataFinal": "20261119",
                      "cnpjOrgao": cnpj, "pagina": 1, "tamanhoPagina": 10}, timeout=(10, 60))
            if r.status_code == 204:
                return {"contratos2026": 0, "tempo": round(time.monotonic() - t0, 1)}
            return {"contratos2026": r.json().get("totalRegistros") if r.status_code == 200 else r.status_code, "tempo": round(time.monotonic() - t0, 1)}
        except Exception as e:
            err = type(e).__name__
            time.sleep(5)
    return {"contratos2026": err, "tempo": round(time.monotonic() - t0, 1)}


def segunda_passada():
    cfg = json.load(open("config/municipios_diag.json", encoding="utf-8"))
    t0 = time.monotonic()

    def fio(b):
        emps, st, t = fiorilli_empresas(b["base"])
        testes = {}
        for cod, nome in emps[:4]:
            testes[cod] = {"nome": nome.strip()[:60], **fiorilli_json(b["base"], cod)}
        return {**b, "statusPagina": st, "tempoPagina": t, "empresas": len(emps), "testes": testes}
    with cf.ThreadPoolExecutor(max_workers=6) as ex:
        for res in ex.map(fio, cfg["fiorilli"]):
            print("FIO|" + json.dumps(res, ensure_ascii=False), flush=True)
    with cf.ThreadPoolExecutor(max_workers=4) as ex:
        for e, res in zip(cfg["entes"], ex.map(lambda e: siconfi2(e["ibge"]), cfg["entes"])):
            print("SIC|" + json.dumps({"municipio": e["municipio"], "populacao": e["populacao"], **res}, ensure_ascii=False), flush=True)
    for e in cfg["entes"]:  # PNCP: um de cada vez (é lento)
        print("PNCP|" + json.dumps({"municipio": e["municipio"], **pncp2(e["cnpj"])}, ensure_ascii=False), flush=True)
    print(f"FIM2 em {round(time.monotonic() - t0)} s", flush=True)


if __name__ == "__main__" and __import__("os").environ.get("DIAG") == "2":
    segunda_passada()


# ---------------------------------------------------------------- 3ª passada (DIAG=3): TCE-MS como fonte única
TCE_URLS = [
    "https://www.tce.ms.gov.br/mapa-dos-jurisdicionados", "https://transparencia.tce.ms.gov.br/",
    "https://esfinge-portal.tce.ms.gov.br/", "https://portaljurisdicionado.tce.ms.gov.br/", "https://portaljurisdicionado.tce.ms.gov.br/ver-indice",
    "https://portal-services.tce.ms.gov.br/portal-services/", "https://portal-services.tce.ms.gov.br/portal-services/v3/api-docs",
    "https://portal-services.tce.ms.gov.br/portal-services/v2/api-docs", "https://portal-services.tce.ms.gov.br/portal-services/swagger-ui.html",
    "https://portal-services.tce.ms.gov.br/portal-services/swagger-ui/index.html", "https://esfinge-portal.tce.ms.gov.br/api",
    "https://esfinge-portal.tce.ms.gov.br/v3/api-docs", "https://esic.tce.ms.gov.br/",
]


def sonda(url, bundles=True):
    r, t, err = get(url)
    res = {"url": url, "status": r.status_code if r is not None else err, "tempo": t}
    if r is None:
        return res
    ct = r.headers.get("content-type", "")
    res.update(final=r.url, tipo=ct.split(";")[0], tamanho=len(r.content),
               titulo=(re.search(r"<title>([^<]*)", r.text or "", re.I).group(1).strip()[:80] if "html" in ct and re.search(r"<title>", r.text or "", re.I) else None))
    if "json" in ct:
        res["amostraChaves"] = list(r.json().keys())[:25] if isinstance(r.json(), dict) else f"lista de {len(r.json())}"
    if bundles and "html" in ct:
        achados = set()
        srcs = [urllib.parse.urljoin(r.url, s) for s in re.findall(r'<script[^>]+src=["\']([^"\']+)["\']', r.text, re.I)]
        srcs = [s for s in srcs if urllib.parse.urlparse(s).netloc.endswith("tce.ms.gov.br")][:6]
        for s in srcs:
            rj, tj, ej = get(s)
            if rj is None:
                continue
            for m in re.findall(r'["\'`](https?://[a-z0-9.-]*tce\.ms\.gov\.br[^"\'`\s]{0,120}|/(?:api|portal-services|esfinge|services?)/[^"\'`\s]{2,120})["\'`]', rj.text):
                achados.add(m)
        res["scripts"] = len(srcs)
        res["endpointsNoJs"] = sorted(achados)[:60]
        res["linksNaPagina"] = sorted(set(re.findall(r'href=["\'](https?://[^"\']*tce\.ms\.gov\.br[^"\']*)["\']', r.text)))[:30]
    return res


def terceira_passada():
    for u in TCE_URLS:
        print("TCE|" + json.dumps(sonda(u), ensure_ascii=False), flush=True)


if __name__ == "__main__" and __import__("os").environ.get("DIAG") == "3":
    terceira_passada()


# ---------------------------------------------------------------- 4ª passada (DIAG=4): chamadas de API dos portais do TCE-MS
def trechos_js(pagina, rx=r"barramento|/api/|api/|municip|sala-do-prefeito|emenda|iegm|remess|entreg|pessoal|folha|despes|empenh|licita|contrat|receit|prestac|jurisdicionad"):
    r, t, err = get(pagina)
    if r is None:
        return {"pagina": pagina, "erro": err}
    srcs = [urllib.parse.urljoin(r.url, s) for s in re.findall(r'<script[^>]+src=["\']([^"\']+)["\']', r.text, re.I)]
    out = {"pagina": pagina, "scripts": srcs[:8], "trechos": []}
    vistos = set()
    for s in srcs[:8]:
        rj, tj, ej = get(s)
        if rj is None or len(rj.text) < 500:
            continue
        for m in re.finditer(r'["\'`]([^"\'`\n]{0,140}?(?:' + rx + r')[^"\'`\n]{0,140}?)["\'`]', rj.text, re.I):
            v = m.group(1)
            if v in vistos or len(v) < 6 or re.search(r"\s{3,}|function|=>|\{", v):
                continue
            vistos.add(v)
            out["trechos"].append(v[:200])
            if len(out["trechos"]) >= 250:
                break
    return out


def quarta_passada():
    for p in ("https://portaljurisdicionado.tce.ms.gov.br/sala-do-prefeito", "https://esfinge-portal.tce.ms.gov.br/",
              "https://contasirregulares.tce.ms.gov.br/home"):
        print("JS|" + json.dumps(trechos_js(p), ensure_ascii=False), flush=True)
    for u in ("https://sip-barramento.tce.ms.gov.br/barramento/api", "https://sip-barramento.tce.ms.gov.br/barramento/api/",
              "https://contasirregulares.tce.ms.gov.br/", "https://jurisprudencia.tce.ms.gov.br/dashboard"):
        print("TCE|" + json.dumps(sonda(u, bundles=False), ensure_ascii=False), flush=True)


if __name__ == "__main__" and __import__("os").environ.get("DIAG") == "4":
    quarta_passada()
