#!/usr/bin/env python3
"""
Cofre Aberto MS — uma página por parlamentar (roda ao fim da coleta diária)

Gera HTML estático (indexável pelo Google, com prévia no WhatsApp) em:

  /vereador/<nome>/            29 vereadores de Campo Grande
  /deputado-estadual/<nome>/   deputados estaduais de MS (ALEMS)
  /deputado-federal/<nome>/    513 deputados federais (os de MS com notas completas)
  /senador/<nome>/             81 senadores (os de MS com notas completas)

mais uma página-índice por grupo, dados/paginas_index.json (usado pelo painel
para linkar cada parlamentar à sua página) e o sitemap.xml.

Fotos embutidas em base64 no JSON (vereadores, dep. estaduais) são gravadas
como arquivo em fotos/p/ — a prévia do WhatsApp/Facebook precisa de uma URL
de imagem. Os arquivos só são reescritos quando o conteúdo muda.
"""

import base64, hashlib, html, json, re, unicodedata
from datetime import date, datetime
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).parent.parent
DADOS = ROOT / "dados"
SITE = "https://cofreabertoms.com.br"
import sys as _sys
_sys.path.insert(0, str(Path(__file__).parent))
from ano_ref import ano_referencia
ANO = ano_referencia()
HOJE = date.today()
MESES = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]
COR_ATUAL, COR_ANTERIOR = "#3987e5", "#d95926"   # mesmas cores validadas da aba Evolução

FONTE_OFICIAL = {
    "vereador": "Portal da Transparência da Câmara Municipal de Campo Grande",
    "estadual": "Portal da Transparência da Assembleia Legislativa de MS (ALEMS)",
    "federal": "Câmara dos Deputados, arquivo da Cota para o Exercício da Atividade Parlamentar",
    "senador": "Senado Federal, dados abertos da CEAPS",
}

GRUPOS = {
    "vereador": {"pasta": "vereador", "cargo": "Vereador(a) de Campo Grande", "plural": "Vereadores de Campo Grande",
                 "aba": "camara", "cota": "verba indenizatória (Atos 027/028)", "feed": "vereador"},
    "estadual": {"pasta": "deputado-estadual", "cargo": "Deputado(a) estadual de MS", "plural": "Deputados estaduais de MS",
                 "aba": "deputados-estaduais", "cota": "CEAP da ALEMS", "feed": "estadual"},
    "federal": {"pasta": "deputado-federal", "cargo": "Deputado(a) federal", "plural": "Deputados federais",
                "aba": "deputados", "aba_br": "deputados-brasil", "cota": "CEAP da Câmara dos Deputados", "feed": "federal"},
    "senador": {"pasta": "senador", "cargo": "Senador(a)", "plural": "Senadores",
                "aba": "senadores", "aba_br": "senado-brasil", "cota": "CEAPS do Senado", "feed": "senador"},
}


def carregar(nome):
    try:
        return json.load(open(DADOS / nome, encoding="utf-8"))
    except Exception:
        return {}


def slug(txt):
    t = unicodedata.normalize("NFD", txt or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", t).strip("-")


def e(t):
    return html.escape(str(t if t is not None else ""), quote=True)


def brl(v):
    return "R$ " + f"{float(v or 0):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def milhar(n):
    return f"{int(n or 0):,}".replace(",", ".")


def minusc(t):
    # "Vereadores de Campo Grande" -> "vereadores de Campo Grande" (só a 1ª palavra)
    return t[:1].lower() + t[1:]


def compacto(v):
    v = float(v or 0)
    if v >= 1e6:
        return f"R$ {v / 1e6:,.1f} mi".replace(".", ",")
    if v >= 1e3:
        return f"R$ {v / 1e3:,.1f} mil".replace(".", ",")
    return brl(v)


def data_br(iso):
    try:
        return datetime.fromisoformat(str(iso)[:10]).strftime("%d/%m/%Y")
    except ValueError:
        return "—"


def limpa_nome(t):
    t = re.sub(r"^[^\w/]*", "", (t or "").strip())
    t = re.sub(r"^/\d+\s+", "", t)
    return re.sub(r"^[^\w]+", "", t).strip()


def escreve_se_mudou(path, conteudo):
    path.parent.mkdir(parents=True, exist_ok=True)
    dados = conteudo.encode("utf-8") if isinstance(conteudo, str) else conteudo
    if path.exists() and path.read_bytes() == dados:
        return False
    path.write_bytes(dados)
    return True


def foto_publica(grupo, s, foto):
    """URL absoluta de imagem para og:image; base64 vira arquivo em fotos/p/."""
    foto = str(foto or "")
    if foto.startswith("data:image"):
        m = re.match(r"data:image/(\w+);base64,(.*)", foto, re.S)
        if not m:
            return None
        ext = "jpg" if m.group(1) in ("jpeg", "jpg") else m.group(1)
        nome = f"{grupo}-{s}.{ext}"
        escreve_se_mudou(ROOT / "fotos" / "p" / nome, base64.b64decode(m.group(2)))
        return f"/fotos/p/{nome}"
    if foto.startswith("http://"):
        foto = "https://" + foto[len("http://"):]
    return foto or None


# ------------------------------------------------------------------
# Monta a lista de parlamentares com tudo o que a página precisa
# ------------------------------------------------------------------
def coleta():
    evol = carregar("evolucao_mensal.json")
    ev = {(g, p["nome"]): p for g, lst in (evol.get("grupos") or {}).items() for p in lst}
    cx = carregar("conexoes_fornecedores.json").get("conexoes", [])
    notas_uf = {}

    def notas_estado(pasta, uf, pid):
        if (pasta, uf) not in notas_uf:
            notas_uf[(pasta, uf)] = carregar(f"{pasta}/{uf}.json").get("parlamentares", {}) if uf else {}
        return notas_uf[(pasta, uf)].get(str(pid), [])

    def conexoes_de(grupo, nome):
        out = []
        for c in cx:
            if any(p["tipo"] == grupo and p["nome"] == nome for p in c["pagadores"]):
                outros = [p for p in c["pagadores"] if not (p["tipo"] == grupo and p["nome"] == nome)]
                meu = next(p for p in c["pagadores"] if p["tipo"] == grupo and p["nome"] == nome)
                out.append({"empresa": c["nome"], "cnpj": c["cnpjs"][0], "meu": meu["total"], "outros": outros})
        out.sort(key=lambda x: (-len(x["outros"]), -x["meu"]))
        return out[:8]

    lista = []
    for v in carregar("camara_municipal.json").get("vereadores", []):
        vi = v.get("verbaIndenizatoria") or {}
        cats = {}
        for n in v.get("despesas") or []:
            k = (n.get("descricao") or n.get("ato") or "Outros").strip()[:60] or "Outros"
            cats[k] = cats.get(k, 0) + (n.get("valor") or 0)
        lista.append(dict(grupo="vereador", nome=v["nome"], partido=v.get("partido"), uf="MS", foto=v.get("foto"),
                          nomeCompleto=v.get("nomeCompleto"), total=vi.get(f"gastoPago{ANO}") or 0,
                          cota=vi.get(f"cotaAnual{ANO}"), notas=v.get("despesas") or [],
                          totalNotas=v.get("totalNotasFiscais") or len(v.get("despesas") or []),
                          categorias={"Ato 027 — atividade parlamentar (combustível, divulgação, locação de veículo…)": vi.get(f"gastoAto027_{ANO}") or 0,
                                      "Ato 028 — assessoria técnica": vi.get(f"gastoAto028_{ANO}") or 0},
                          extra={"Funcionários no gabinete": v.get("gabinete", {}).get("numFuncionarios"),
                                                  "Gasto com pessoal/mês": brl(v.get("gabinete", {}).get("gastoPessoalMensal")) if v.get("gabinete", {}).get("gastoPessoalMensal") else None},
                          aba="camara", ms=True))
    for v in carregar("deputados_estaduais_ms.json").get("vereadores", []):
        vi = v.get("verbaIndenizatoria") or {}
        lista.append(dict(grupo="estadual", nome=v["nome"], partido=v.get("partido"), uf="MS", foto=v.get("foto"),
                          total=vi.get(f"gastoPago{ANO}") or 0, cota=vi.get(f"cotaAnual{ANO}"),
                          notas=[{**n, "url": n.get("urlPdf")} for n in v.get("despesas") or []],
                          totalNotas=len(v.get("despesas") or []), categorias=vi.get("categorias"),
                          extra={}, aba="deputados-estaduais", ms=True))
    fed_ms = {d["id"]: d for d in carregar("deputados_federais_ms.json").get("deputados", [])}
    for d in carregar("deputados_federais_brasil.json").get("deputados", []):
        ms = d.get("uf") == "MS"
        fonte = fed_ms.get(d["id"], d)
        notas = fonte.get("despesas") or notas_estado("ceap_federal", d.get("uf"), d["id"])
        lista.append(dict(grupo="federal", nome=d["nome"], partido=d.get("partido"), uf=d.get("uf"), foto=d.get("foto"),
                          total=d.get("cotaGastaAno") or 0, cota=None,
                          notas=[{"data": n.get("data"), "fornecedor": n.get("fornecedor"), "categoria": n.get("categoria"),
                                  "valor": n.get("valor"), "url": n.get("urlNotaFiscal")} for n in notas],
                          totalNotas=d.get("totalNotasFiscais") or len(notas),
                          categorias={c["categoria"]: c["valor"] for c in d.get("ceapCategorias") or []},
                          extra={}, aba="deputados" if ms else "deputados-brasil", ms=ms, id=d["id"],
                          urlOficial=d.get("urlPerfil")))
    for s in carregar("senadores_brasil.json").get("senadores", []):
        ms = s.get("uf") == "MS"
        notas = notas_estado("ceaps_senado", s.get("uf"), s["id"])
        lista.append(dict(grupo="senador", nome=s["nome"], partido=s.get("partido"), uf=s.get("uf"), foto=s.get("foto"),
                          total=s.get("cotaGastaAno") or 0, cota=None,
                          notas=[{"data": n.get("data"), "fornecedor": n.get("fornecedor"), "categoria": n.get("categoria"),
                                  "valor": n.get("valor"), "detalhe": n.get("detalhamento")} for n in notas],
                          totalNotas=len(notas), categorias={k: v for k, v in (s.get("ceaps") or {}).items() if v},
                          extra={}, aba="senadores" if ms else "senado-brasil", ms=ms, id=s["id"],
                          urlOficial=s.get("urlTransparencia")))

    # slugs únicos por grupo
    usados = {}
    for p in lista:
        base = slug(p["nome"]) or "parlamentar"
        chave = (p["grupo"], base)
        if chave in usados:
            base = f"{base}-{slug(p.get('uf') or '')}" if p.get("uf") else f"{base}-{p.get('id')}"
        usados[(p["grupo"], base)] = True
        p["slug"] = base
        p["url"] = f"/{GRUPOS[p['grupo']]['pasta']}/{base}/"
        p["evol"] = ev.get((p["grupo"], p["nome"])) if p["ms"] else None
        p["conexoes"] = conexoes_de(p["grupo"], p["nome"]) if p["ms"] else []
    return lista


# ------------------------------------------------------------------
# HTML
# ------------------------------------------------------------------
CSS = """*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
:root{--bg:#070910;--surface:#0f1117;--surface-2:#161a23;--border:#232839;--ink:#f0f3fa;--ink-soft:#8b95aa;--ink-faint:#454d60;--ink-caption:#6b7387;--accent:#4d7dff;--accent-btn:#3f6bf0;--amber:#f5c842}
html,body{min-height:100vh;background:var(--bg);color:var(--ink);font-family:"Inter",system-ui,sans-serif;-webkit-font-smoothing:antialiased}
a{color:var(--accent);text-decoration:none}a:hover{text-decoration:underline}
.page{max-width:900px;margin:0 auto;padding:0 24px}
nav{display:flex;align-items:center;justify-content:space-between;padding:20px 0;border-bottom:1px solid var(--border);gap:12px}
.nav-cta{background:var(--accent-btn);color:#fff!important;border-radius:8px;padding:9px 18px;font-weight:600;font-size:.86rem;white-space:nowrap}
.breadcrumb{font-size:.8rem;color:var(--ink-soft);padding:18px 0 0}.breadcrumb a{color:var(--ink-soft)}
article{padding:24px 0 56px}
.perfil{display:flex;gap:20px;align-items:center;margin-bottom:22px}
.perfil img{width:96px;height:96px;border-radius:50%;object-fit:cover;border:2px solid var(--border);background:var(--surface-2);flex-shrink:0}
.perfil .ini{width:96px;height:96px;border-radius:50%;display:flex;align-items:center;justify-content:center;background:var(--surface-2);border:2px solid var(--border);font-family:"Sora",sans-serif;font-weight:800;font-size:1.8rem;color:var(--ink-soft);flex-shrink:0}
h1{font-family:"Sora",sans-serif;font-size:clamp(1.6rem,4vw,2.3rem);font-weight:800;letter-spacing:-.02em;line-height:1.15}
.cargo{color:var(--ink-soft);margin-top:6px;font-size:.95rem}
h2{font-family:"Sora",sans-serif;font-size:1.2rem;font-weight:700;margin:34px 0 12px}
p{font-size:.93rem;color:var(--ink-soft);line-height:1.7;margin-bottom:12px;max-width:740px}p strong{color:var(--ink)}
.resumo-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:1px;background:var(--border);border:1px solid var(--border);border-radius:14px;overflow:hidden;margin:8px 0 18px}
.resumo-item{background:var(--surface);padding:16px}
.resumo-val{font-family:"Sora",sans-serif;font-size:1.35rem;font-weight:800}
.resumo-label{font-size:.68rem;color:var(--ink-caption);text-transform:uppercase;letter-spacing:.06em;margin-top:4px;font-weight:600}
.acoes{display:flex;gap:8px;flex-wrap:wrap;margin:6px 0 8px}
.btn{display:inline-flex;align-items:center;gap:6px;border:1px solid var(--border);border-radius:9px;padding:9px 14px;font-size:.84rem;color:var(--ink)!important;background:var(--surface);font-weight:600}
.btn:hover{border-color:var(--accent);text-decoration:none}.btn.prim{background:var(--accent-btn);border-color:var(--accent-btn);color:#fff!important}
.btn.zap{border-color:#25D366}
.bars{display:flex;flex-direction:column;gap:8px}
.bar{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:4px 12px;font-size:.82rem;color:var(--ink-soft)}
.bar .t{height:6px;border-radius:3px;background:var(--surface-2);grid-column:1/-1;overflow:hidden}.bar .t i{display:block;height:100%;background:var(--amber);border-radius:3px}
.bar b{color:var(--ink);font-weight:600;white-space:nowrap}
.tabela-wrap{overflow-x:auto;border:1px solid var(--border);border-radius:12px;background:var(--surface)}
table{width:100%;border-collapse:collapse;font-size:.83rem}
th{text-align:left;padding:9px 12px;font-size:.66rem;text-transform:uppercase;letter-spacing:.05em;color:var(--ink-caption);background:var(--surface-2);border-bottom:1px solid var(--border);white-space:nowrap}
td{padding:8px 12px;border-bottom:1px solid var(--border);color:var(--ink-soft);vertical-align:top}
tbody tr:last-child td{border-bottom:none}
td.num,th.num{text-align:right;white-space:nowrap}td.num{color:var(--amber);font-weight:700;font-family:"Sora",sans-serif}
td.f{color:var(--ink)}td small{display:block;color:var(--ink-caption);font-size:.72rem;margin-top:2px}
.graf{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:14px}
.graf svg{width:100%;height:auto;display:block}.g-estreita{display:none}
@media(max-width:560px){.g-larga{display:none}.g-estreita{display:block}}
.leg{display:flex;gap:16px;font-size:.76rem;color:var(--ink-soft);margin-bottom:6px}.leg i{display:inline-block;width:18px;border-top:2px solid;vertical-align:middle;margin-right:6px}
details{margin-top:8px;font-size:.8rem;color:var(--ink-soft)}summary{cursor:pointer}
.citar{font-family:ui-monospace,Menlo,monospace;font-size:.78rem;color:var(--ink);background:var(--surface-2);border:1px solid var(--border);border-radius:8px;padding:10px 12px;line-height:1.6}
.aviso{font-size:.8rem;color:var(--ink-soft);border:1px solid var(--border);border-radius:10px;padding:10px 12px;background:var(--surface-2)}
.lista{columns:2 240px;gap:24px;font-size:.88rem;line-height:1.9}.lista a{color:var(--ink)}
.lista span{color:var(--ink-caption);font-size:.78rem}
.uf{break-inside:avoid;margin-bottom:14px}.uf h3{font-family:"Sora",sans-serif;font-size:.9rem;margin-bottom:4px;color:var(--ink-soft)}
footer{border-top:1px solid var(--border);padding:22px 0;font-size:.78rem;color:var(--ink-caption);display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap}
footer a{color:var(--ink-soft)}
@media(max-width:640px){.page{padding:0 16px}.perfil img,.perfil .ini{width:72px;height:72px}td,th{padding:7px 8px}}"""


def cabecalho(titulo, descricao, url, imagem, jsonld, tipo="profile"):
    img = imagem or f"{SITE}/og-image.png"
    if img.startswith("/"):
        img = SITE + img   # og:image precisa de URL absoluta
    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<title>{e(titulo)}</title>
<meta name="description" content="{e(descricao)}"/>
<link rel="canonical" href="{SITE}{url}"/>
<meta property="og:type" content="{tipo}"/>
<meta property="og:url" content="{SITE}{url}"/>
<meta property="og:title" content="{e(titulo)}"/>
<meta property="og:description" content="{e(descricao)}"/>
<meta property="og:image" content="{e(img)}"/>
<meta property="og:locale" content="pt_BR"/>
<meta property="og:site_name" content="Cofre Aberto MS"/>
<meta name="twitter:card" content="summary"/>
<meta name="twitter:title" content="{e(titulo)}"/>
<meta name="twitter:description" content="{e(descricao)}"/>
<meta name="twitter:image" content="{e(img)}"/>
<link rel="icon" type="image/svg+xml" href="/favicon.svg"/>
<link rel="preconnect" href="https://fonts.googleapis.com"/>
<link href="https://fonts.googleapis.com/css2?family=Sora:wght@600;700;800&family=Inter:wght@400;500;600&display=swap" rel="stylesheet"/>
<style>{CSS}</style>
<script type="application/ld+json">{json.dumps(jsonld, ensure_ascii=False)}</script>
<script defer data-domain="cofreabertoms.com.br" src="https://plausible.io/js/script.js"></script>
</head>
<body>
<div class="page">
<nav><a href="/"><img src="/logo.svg" alt="Cofre Aberto MS" width="147" height="44" style="display:block"/></a>
<a class="nav-cta" href="/cofre-aberto-ms.html">Painel completo →</a></nav>
"""


RODAPE = f"""<footer><span>© {ANO} Cofre Aberto MS — dados públicos de fontes oficiais, coletados automaticamente.</span>
<span><a href="/">Início</a> · <a href="/cofre-aberto-ms.html">Painel</a> · <a href="/boletim/">Boletim semanal</a> · <a href="/empresa/">Empresas</a> · <a href="/metodologia.html">Metodologia e dados</a> · <a href="/press.html">Imprensa</a></span></footer>
</div>
</body>
</html>
"""


def grafico(evol, ano):
    if not evol:
        return ""
    larga, estreita = _grafico(evol, ano, 640, 220, 11, 1), _grafico(evol, ano, 340, 230, 11, 2)
    if not larga:
        return ""
    svg_l, leg, tabela = larga
    svg_e = estreita[0]
    return (f'<h2>Evolução do gasto em {ano}</h2><div class="graf">{leg}'
            f'<div class="g-larga">{svg_l}</div><div class="g-estreita">{svg_e}</div></div>{tabela}')


def _grafico(evol, ano, W, H, fs, passo_mes):
    m = evol["m"]
    ant = evol.get("mAnterior")
    ult = max([i for i, v in enumerate(m) if v > 0], default=-1)
    if ult < 0:
        return ""
    acA, s = [], 0
    for v in m[:ult + 1]:
        s += v
        acA.append(s)
    acB = None
    if ant:
        acB, s = [], 0
        for v in ant:
            s += v
            acB.append(s)
    pl, pr, pt, pb = (58, 40, 10, 24) if W > 400 else (50, 34, 10, 22)
    topo = max(acA + (acB or [])) or 1
    passo = 10 ** len(str(int(topo / 4))) / 10
    passo = next(p * passo for p in (1, 2, 2.5, 5, 10, 20, 25, 50) if p * passo >= topo / 4)
    topo = passo * -(-topo // passo)
    x = lambda i: pl + (W - pl - pr) * i / 11
    y = lambda v: pt + (H - pt - pb) * (1 - v / topo)
    pts = lambda arr: " ".join(f"{x(i):.1f},{y(v):.1f}" for i, v in enumerate(arr))
    out = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="Gasto acumulado por mês em {ano}{f" e {ano - 1}" if acB else ""}">']
    t = 0
    while t <= topo + 1e-6:
        out.append(f'<line x1="{pl}" x2="{W - pr}" y1="{y(t):.1f}" y2="{y(t):.1f}" stroke="#232839"/>'
                   f'<text x="{pl - 8}" y="{y(t) + 4:.1f}" text-anchor="end" font-size="{fs}" fill="#8b95aa">{e(compacto(t).replace("R$ ", "").replace(",0 ", " ") if t else "0")}</text>')
        t += passo
    for i, ms in enumerate(MESES):
        if i % passo_mes == 0:
            out.append(f'<text x="{x(i):.1f}" y="{H - 6}" text-anchor="middle" font-size="{fs}" fill="#8b95aa">{ms}</text>')
    if acB:
        out.append(f'<polyline points="{pts(acB)}" fill="none" stroke="{COR_ANTERIOR}" stroke-width="2" stroke-dasharray="5 4" stroke-linejoin="round"/>'
                   f'<text x="{x(11) + 4:.1f}" y="{y(acB[11]) + 4:.1f}" font-size="{fs}" fill="#8b95aa">{ano - 1}</text>')
    out.append(f'<polyline points="{pts(acA)}" fill="none" stroke="{COR_ATUAL}" stroke-width="2" stroke-linejoin="round"/>'
               f'<circle cx="{x(ult):.1f}" cy="{y(acA[ult]):.1f}" r="4" fill="{COR_ATUAL}" stroke="#0f1117" stroke-width="2"/>'
               f'<text x="{x(ult) + 7:.1f}" y="{y(acA[ult]) + 4:.1f}" font-size="{fs}" font-weight="600" fill="#f0f3fa">{ano}</text></svg>')
    leg = (f'<div class="leg"><span><i style="border-color:{COR_ATUAL}"></i>{ano}</span>'
           f'<span><i style="border-color:{COR_ANTERIOR};border-top-style:dashed"></i>{ano - 1}</span></div>') if acB else ""
    linhas = "".join(f"<tr><td>{ms}</td><td class='num'>{brl(m[i]) if i <= ult else '—'}</td>"
                     + (f"<td class='num'>{brl(ant[i])}</td>" if ant else "") + "</tr>" for i, ms in enumerate(MESES))
    tabela = (f"<details><summary>Ver mês a mês em tabela</summary><div class='tabela-wrap' style='margin-top:8px'><table>"
              f"<thead><tr><th>Mês</th><th class='num'>{ano}</th>{f'<th class=num>{ano - 1}</th>' if ant else ''}</tr></thead>"
              f"<tbody>{linhas}</tbody></table></div></details>")
    return "".join(out), leg, tabela


_EMENDAS = None


def emendas_de(p):
    """Emendas pagas em MS no ano por este deputado federal/senador (dados/emendas_municipios.json)."""
    global _EMENDAS
    if _EMENDAS is None:
        em = carregar("emendas_municipios.json")
        _EMENDAS = {}
        if em.get("ano") == ANO:
            emp = carregar("empresas_index.json") or {}
            for a in em.get("autores", []):
                if a.get("atual"):
                    _EMENDAS[(a.get("grupo"), slug(a["autor"]))] = (a, emp)
    return _EMENDAS.get((p["grupo"], slug(p["nome"])))


def bloco_emendas(p):
    achado = emendas_de(p) if p["grupo"] in ("federal", "senador") and p.get("ms") else None
    if not achado:
        return ""
    a, emp = achado
    mun = a["municipios"][:10]
    mx = mun[0]["valor"] if mun else 1
    barras = "".join(f"<div class='bar'><span>{e(m['municipio'])}</span><b>{brl(m['valor'])}</b><div class='t'><i style='width:{m['valor'] / mx * 100:.1f}%'></i></div></div>" for m in mun)
    def fav(f):
        d = re.sub(r"\D", "", f.get("doc") or "")
        nome = e(f["nome"])
        if len(d) == 14 and d[:8] in emp:
            nome = f"<a href='/empresa/{d[:8]}/'>{nome}</a>"
        return f"<tr><td class='f'>{nome}<small>{e(f.get('municipio') or '')}</small></td><td class='num'>{brl(f['valor'])}</td></tr>"
    tipos = " · ".join(f"{e(t['tipo'])}: <strong>{brl(t['valor'])}</strong>" for t in a.get("tipos", []))
    fora = f" Mais {brl(a['totalBR'] - a['totalMS'])} foram para fora de MS." if a["totalBR"] - a["totalMS"] > 1 else ""
    return (f"<h2>Para onde foram as emendas</h2>"
            f"<p>Em {ANO}, emendas de <strong>{e(p['nome'])}</strong> pagaram <strong>{brl(a['totalMS'])}</strong> a "
            f"{len(a['municipios'])} município(s) de MS.{fora} {tipos}.</p>"
            f"<div class='bars'>{barras}</div>"
            + (f"<p style='margin-top:12px'>{len(a['municipios']) - 10} outros municípios receberam valores menores.</p>" if len(a["municipios"]) > 10 else "")
            + f"<h2 style='font-size:1rem;margin-top:22px'>Quem recebeu</h2><div class='tabela-wrap'><table><thead><tr><th>Favorecido</th>"
            f"<th class='num'>Valor</th></tr></thead><tbody>{''.join(fav(f) for f in a['favorecidos'][:10])}</tbody></table></div>"
            f"<p style='margin-top:10px;font-size:.8rem'>Fonte: Portal da Transparência do Governo Federal (CGU), pagamentos de emendas por favorecido. "
            f"Conta o mês do pagamento, inclusive de emendas de anos anteriores. <a href='/cofre-aberto-ms.html#aba=emendas'>Ver todas as emendas no painel →</a></p>")


def pagina(p, irmaos):
    g = GRUPOS[p["grupo"]]
    cargo = g["cargo"] if p["grupo"] in ("vereador", "estadual") else f"{g['cargo']} por {p['uf']}"
    titulo = f"{p['nome']} ({p['partido'] or 'sem partido'}) — {cargo}: gastos {ANO} | Cofre Aberto MS"
    total, n = p["total"], p["totalNotas"]
    desc = (f"{p['nome']} ({cargo}) gastou {brl(total)} de {g['cota']} em {ANO}"
            + (f", em {milhar(n)} notas fiscais" if n else "")
            + ". Veja fornecedores, notas e a evolução mês a mês.")
    foto = foto_publica(p["grupo"], p["slug"], p.get("foto"))
    painel = f"/cofre-aberto-ms.html#aba={p['aba']}&p={quote(p['nome'])}"
    url_abs = SITE + p["url"]
    zap = "https://wa.me/?text=" + quote(f"{p['nome']} ({cargo}) gastou {compacto(total)} da cota em {ANO}. Veja as notas fiscais: {url_abs}")
    feed = f"/dados/feeds/{g['feed']}-{p['slug']}.xml" if p["ms"] and (ROOT / "dados" / "feeds" / f"{g['feed']}-{p['slug']}.xml").exists() else None

    # resumo
    itens = [(brl(total), f"Gasto em {ANO} ({g['cota']})"), (milhar(n), "Notas fiscais")]
    if p.get("cota"):
        itens.append((f"{total / p['cota'] * 100:.1f}%".replace(".", ","), f"da cota anual de {compacto(p['cota'])}"))
    ev = p.get("evol")
    var_txt = ""
    if ev and ev.get("mAnterior"):
        fechado = 11 if ANO < HOJE.year else HOJE.month - 2   # índice do último mês fechado
        M = max(0, min(fechado, max([i for i, v in enumerate(ev["m"]) if v > 0], default=0)))
        a, b = sum(ev["m"][:M + 1]), sum(ev["mAnterior"][:M + 1])
        if b:
            v = (a / b - 1) * 100
            seta = "≈ 0%" if abs(v) < 0.05 else f"{'▲ +' if v > 0 else '▼ '}{v:.1f}%".replace(".", ",")
            itens.append((seta, f"vs jan–{MESES[M]} de {ANO - 1}"))
            var_txt = (f" De janeiro a {MESES[M]}, o gasto foi {compacto(a)}, contra {compacto(b)} no mesmo período de {ANO - 1} ({seta}).")
    for k, val in (p.get("extra") or {}).items():
        if val:
            itens.append((val, k))
    resumo = "".join(f'<div class="resumo-item"><div class="resumo-val">{e(v)}</div><div class="resumo-label">{e(r)}</div></div>' for v, r in itens)

    # categorias
    cats = p.get("categorias") or {}
    if not cats and p["notas"]:
        for nt in p["notas"]:
            k = (nt.get("categoria") or "Outros")[:70]
            cats[k] = cats.get(k, 0) + float(nt.get("valor") or 0)
    cats = sorted(((k, v) for k, v in cats.items() if v), key=lambda x: -x[1])[:8]
    mx = cats[0][1] if cats else 1
    bloco_cat = ("<h2>Onde o dinheiro foi gasto</h2><div class='bars'>" + "".join(
        f"<div class='bar'><span>{e(k)}</span><b>{brl(v)}</b><div class='t'><i style='width:{v / mx * 100:.1f}%'></i></div></div>"
        for k, v in cats) + "</div>") if cats else ""

    # últimas notas
    notas = sorted((x for x in p["notas"] if x.get("data")), key=lambda x: x["data"], reverse=True)[:15]
    def linha_nota(x):
        forn = e(limpa_nome(x.get("fornecedor")) or "—")
        if x.get("url"):
            forn = f'<a href="{e(x["url"])}" target="_blank" rel="noopener nofollow">{forn}</a>'
        sub = e((x.get("categoria") or x.get("descricao") or "")[:90])
        return (f"<tr><td style='white-space:nowrap'>{data_br(x['data'])}</td><td class='f'>{forn}<small>{sub}</small></td>"
                f"<td class='num'>{brl(x.get('valor'))}</td></tr>")
    bloco_notas = (f"<h2>Últimas notas fiscais</h2><div class='tabela-wrap'><table><thead><tr><th>Data</th><th>Fornecedor</th>"
                   f"<th class='num'>Valor</th></tr></thead><tbody>{''.join(linha_nota(x) for x in notas)}</tbody></table></div>"
                   f"<p style='margin-top:10px'>{'As ' + str(len(notas)) + ' mais recentes de ' + milhar(n) + ' notas. ' if n > len(notas) else ''}"
                   f"<a href='{painel}'>Ver todas as notas no painel →</a></p>") if notas else ""

    # conexões
    bloco_cx = ""
    if p["conexoes"]:
        lin = "".join(
            f"<tr><td class='f'><a href='/cofre-aberto-ms.html#aba=conexoes&amp;p={quote(c['empresa'])}'>{e(c['empresa'])}</a><small>{e(c['cnpj'])}</small></td>"
            f"<td>{len(c['outros'])} outro(s): {e(', '.join(o['nome'] for o in c['outros'][:3]))}{'…' if len(c['outros']) > 3 else ''}</td>"
            f"<td class='num'>{brl(c['meu'])}</td></tr>" for c in p["conexoes"])
        bloco_cx = (f"<h2>Fornecedores em comum com outros políticos</h2><p class='aviso'>Empresas que também receberam de outros "
                    f"pagadores públicos de MS. Um fornecedor em comum <strong>não indica irregularidade</strong> — postos, "
                    f"companhias aéreas e gráficas atendem muitos gabinetes.</p><div class='tabela-wrap'><table><thead><tr>"
                    f"<th>Empresa</th><th>Também pagaram</th><th class='num'>Pago por {e(p['nome'])}</th></tr></thead>"
                    f"<tbody>{lin}</tbody></table></div>")

    # links para outros do grupo
    outros = [o for o in irmaos if o is not p][:12]
    bloco_irmaos = ("<h2>Outros " + e(minusc(g["plural"]) if p["grupo"] in ("vereador", "estadual") else f"{minusc(g['plural'])} de {p['uf']}")
                    + "</h2><div class='lista'>" + "".join(f"<div><a href='{o['url']}'>{e(o['nome'])}</a> <span>{e(o['partido'] or '')}</span></div>" for o in outros)
                    + f"</div><p style='margin-top:10px'><a href='/{g['pasta']}/'>Ver todos os {e(minusc(g['plural']))} →</a></p>") if outros else ""

    iniciais = "".join(w[0] for w in p["nome"].split()[:2]).upper()
    img_html = f'<img src="{e(foto)}" alt="Foto de {e(p["nome"])}" width="96" height="96" loading="lazy" onerror="this.outerHTML=\'<div class=ini>{e(iniciais)}</div>\'"/>' if foto else f'<div class="ini">{e(iniciais)}</div>'
    jsonld = {"@context": "https://schema.org", "@graph": [
        {"@type": "Person", "name": p["nome"], "jobTitle": cargo, "image": (SITE + foto) if foto and foto.startswith("/") else foto,
         "affiliation": {"@type": "Organization", "name": p["partido"]} if p.get("partido") else None,
         "url": url_abs},
        {"@type": "BreadcrumbList", "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "Início", "item": SITE + "/"},
            {"@type": "ListItem", "position": 2, "name": g["plural"], "item": f"{SITE}/{g['pasta']}/"},
            {"@type": "ListItem", "position": 3, "name": p["nome"], "item": url_abs}]}]}
    fonte_data = carregar("status.json").get("ultimaAtualizacao", "")[:10]
    corpo = f"""<p class="breadcrumb"><a href="/">Início</a> / <a href="/{g['pasta']}/">{e(g['plural'])}</a> / {e(p['nome'])}</p>
<article>
<div class="perfil">{img_html}<div><h1>{e(p['nome'])}</h1>
<div class="cargo">{e(cargo)} · {e(p['partido'] or 'sem partido')}{f" · {e(p['nomeCompleto'])}" if p.get('nomeCompleto') else ''}</div></div></div>
<p><strong>{e(p['nome'])}</strong> gastou <strong>{brl(total)}</strong> de {e(g['cota'])} em {ANO}{f", registrados em <strong>{milhar(n)}</strong> notas fiscais" if n else ""}.{var_txt}</p>
<div class="resumo-grid">{resumo}</div>
<div class="acoes">
<a class="btn prim" href="{painel}">Ver detalhes no painel</a>
<a class="btn zap" href="{zap}" target="_blank" rel="noopener">💬 Compartilhar no WhatsApp</a>
{f'<a class="btn" href="{feed}">🔔 Seguir notas novas (RSS)</a>' if feed else ''}
{f'<a class="btn" href="{e(p["urlOficial"])}" target="_blank" rel="noopener">Fonte oficial ↗</a>' if p.get('urlOficial') else ''}
</div>
{grafico(ev, ANO)}
{bloco_cat}
{bloco_notas}
{bloco_cx}
{bloco_emendas(p)}
{bloco_irmaos}
<h2>Como citar</h2>
<div class="citar">COFRE ABERTO MS. <i>{e(p['nome'])} ({e(cargo)}): gastos de {e(g['cota'])} em {ANO}</i>. Fonte dos dados: {e(FONTE_OFICIAL[p['grupo']])}. Coletados em {data_br(fonte_data)}. Disponível em: {e(url_abs)}. Acesso em: {data_br(HOJE.isoformat())}.</div>
<p style="margin-top:14px;font-size:.78rem">Dados públicos de {e(g['cota'])}, coletados automaticamente das fontes oficiais — <a href="/metodologia.html">veja a metodologia, as limitações de cada fonte e como baixar os dados</a>. Encontrou um erro? <a href="/metodologia.html#correcoes">Envie uma correção</a>. Última coleta: {data_br(fonte_data)}.</p>
</article>
"""
    return cabecalho(titulo, desc, p["url"], foto, jsonld) + corpo + RODAPE


def indice(grupo, lst):
    g = GRUPOS[grupo]
    url = f"/{g['pasta']}/"
    titulo = f"{g['plural']} — gastos {ANO} | Cofre Aberto MS"
    desc = f"Gastos de {g['cota']} em {ANO} de {len(lst)} {minusc(g['plural'])}, com notas fiscais e fornecedores. Dados públicos."
    if grupo in ("federal", "senador"):
        por_uf = {}
        for p in sorted(lst, key=lambda p: p["nome"]):
            por_uf.setdefault(p["uf"] or "—", []).append(p)
        ordem = ["MS"] + sorted(u for u in por_uf if u != "MS")
        corpo_lista = "<div class='lista'>" + "".join(
            f"<div class='uf'><h3>{e(u)}</h3>" + "".join(f"<div><a href='{p['url']}'>{e(p['nome'])}</a> <span>{e(p['partido'] or '')} · {compacto(p['total'])}</span></div>" for p in por_uf[u]) + "</div>"
            for u in ordem if u in por_uf) + "</div>"
    else:
        corpo_lista = "<div class='lista'>" + "".join(
            f"<div><a href='{p['url']}'>{e(p['nome'])}</a> <span>{e(p['partido'] or '')} · {compacto(p['total'])}</span></div>"
            for p in sorted(lst, key=lambda p: -p["total"])) + "</div>"
    jsonld = {"@context": "https://schema.org", "@type": "CollectionPage", "name": titulo, "url": SITE + url}
    corpo = f"""<p class="breadcrumb"><a href="/">Início</a> / {e(g['plural'])}</p>
<article><h1>{e(g['plural'])}</h1>
<p class="cargo" style="margin-bottom:18px">Gastos de {e(g['cota'])} em {ANO} — clique num nome para ver as notas fiscais, os fornecedores e a evolução mês a mês.</p>
{corpo_lista}</article>
"""
    return cabecalho(titulo, desc, url, None, jsonld, tipo="website") + corpo + RODAPE


def sitemap(lista):
    hoje = HOJE.isoformat()
    fixos = [("/", "daily", "1.0"), ("/cofre-aberto-ms.html", "daily", "0.9"), ("/vereadores-campo-grande.html", "daily", "0.8"),
             ("/deputados-estaduais-ms.html", "daily", "0.8"), ("/senadores-ms.html", "daily", "0.8"), ("/press.html", "monthly", "0.5"), ("/metodologia.html", "weekly", "0.7")]
    fixos += [(f"/{g['pasta']}/", "daily", "0.8") for g in GRUPOS.values()]
    urls = [f"  <url><loc>{SITE}{u}</loc><lastmod>{hoje}</lastmod><changefreq>{c}</changefreq><priority>{pr}</priority></url>" for u, c, pr in fixos]
    urls += [f"  <url><loc>{SITE}{p['url']}</loc><lastmod>{hoje}</lastmod><changefreq>daily</changefreq><priority>{'0.7' if p['ms'] else '0.5'}</priority></url>" for p in lista]
    return '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' + "\n".join(urls) + "\n</urlset>\n"


def main():
    lista = coleta()
    por_grupo = {}
    for p in lista:
        chave = (p["grupo"], p["uf"] if p["grupo"] in ("federal", "senador") else "MS")
        por_grupo.setdefault(chave, []).append(p)
    mudou = 0
    validos = set()
    for p in lista:
        irmaos = sorted(por_grupo[(p["grupo"], p["uf"] if p["grupo"] in ("federal", "senador") else "MS")], key=lambda o: -o["total"])
        caminho = ROOT / GRUPOS[p["grupo"]]["pasta"] / p["slug"] / "index.html"
        validos.add(caminho.parent)
        mudou += escreve_se_mudou(caminho, pagina(p, irmaos))
    for grupo, g in GRUPOS.items():
        escreve_se_mudou(ROOT / g["pasta"] / "index.html", indice(grupo, [p for p in lista if p["grupo"] == grupo]))
        # remove páginas de quem saiu (ex.: suplente que deixou o cargo)
        for d in (ROOT / g["pasta"]).iterdir():
            if d.is_dir() and d not in validos:
                for f in d.iterdir():
                    f.unlink()
                d.rmdir()
                print(f"  removida página antiga: {d.relative_to(ROOT)}")
    escreve_se_mudou(ROOT / "sitemap.xml", sitemap(lista))
    idx = {f"{p['grupo']}|{p['nome']}": p["url"] for p in lista}
    escreve_se_mudou(DADOS / "paginas_index.json", json.dumps(idx, ensure_ascii=False, separators=(",", ":")))
    print(f"✅ {len(lista)} páginas de parlamentares ({mudou} alteradas) + {len(GRUPOS)} índices + sitemap.xml")


if __name__ == "__main__":
    main()
