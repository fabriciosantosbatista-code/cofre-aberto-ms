#!/usr/bin/env python3
"""
Cofre Aberto MS — post da vez para o Instagram e o Facebook (carrossel de 3 imagens + legenda), feito com os dados do site

Os temas se revezam (o próximo é o seguinte ao último publicado, em instagram/historico.json):
  precos · shows · obras · vereadores · publicidade · entidades · emendas · supersalarios
Cada post: capa (número principal), lista dos 5 maiores e uma imagem final com a fonte e o link. Linguagem de "sinal de
atenção", nunca acusação; servidores não são citados pelo nome (só cargo e órgão).

Regras de conteúdo (25/11/2026):
  - só temas cuja base está "confere" no ICP (última conferência válida = confere e status sem divergência/falha);
  - nenhum nome de pessoa que esteja em "sinal de atenção" na Auditoria, nem pagamento/contracheque com divergência da
    fonte sem resposta ao pedido de esclarecimento: o item sai da lista; se for o citado na legenda, o tema é pulado;
  - no máximo 1 post por horário (11h47 e 19h00) e 2 por dia (publicar_instagram.py).

Grava instagram/<data>-<tema>-1.jpg, -2.jpg, -3.jpg (1080×1350, JPEG — o Instagram só aceita JPEG) e instagram/proximo.json
com as imagens e a legenda. Quem publica é scripts/publicar_instagram.py.

Uso:  python3 scripts/gerar_posts_instagram.py            # o próximo tema da fila
      python3 scripts/gerar_posts_instagram.py shows      # um tema específico
"""

import io, json, re, sys
from datetime import date
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).parent))
from cartoes import FUNDO, OURO, TINTA, CINZA, cadeado, fonte, quebra  # noqa: E402

ROOT = Path(__file__).parent.parent
DADOS, PASTA = ROOT / "dados", ROOT / "instagram"
SITE = "https://cofreabertoms.com.br"
W, H = 1080, 1350
HOJE = date.today()
VERMELHO, LINHA = (229, 72, 77), (40, 45, 60)
TEMAS = ["shows",  # "precos" desligado a pedido; para voltar, ponha de novo no começo da lista
         "obras", "vereadores", "publicidade", "entidades", "emendas", "supersalarios"]
TAGS = "#MatoGrossoDoSul #CampoGrande #MS #transparencia #dinheiropublico #fiscalizacao #CofreAbertoMS"


BASE_ICP = {"precos": None, "shows": "shows", "obras": "obras", "vereadores": "camara", "publicidade": "publicidade",
            "entidades": "entidades", "emendas": "emendas", "supersalarios": "supersalarios"}
ICP_LIBERADO = ("verificado", "verificado_reforcado", "parcial")


def _n(t):
    import unicodedata
    return " ".join(unicodedata.normalize("NFKD", str(t or "")).encode("ascii", "ignore").decode().upper().split())


def tema_liberado(tema):
    """(liberado, motivo): a base do tema precisa estar "confere" no ICP."""
    b = BASE_ICP.get(tema)
    if not b:
        return False, "tema sem base no ICP"
    x = ((carregar("icp.json") or {}).get("bases") or {}).get(b) or {}
    u = x.get("ultimaVerificacao") or {}
    if x.get("status") not in ICP_LIBERADO or u.get("resultado") != "confere":
        return False, f"ICP de {b}: {x.get('status') or 'sem status'} (última conferência: {u.get('resultado') or 'nenhuma'})"
    return True, f"ICP de {b}: {x['status']}, última conferência confere em {str(u.get('em'))[:10]}"


def nomes_bloqueados():
    """Nomes que não entram em post: pessoas em sinal de atenção (Auditoria) e contracheques com divergência da fonte
    sem resposta ao pedido de esclarecimento (Supersalários)."""
    out = set()
    for x in (carregar("auditoria.json") or {}).get("sinais") or []:
        for k in ("quem",):
            if x.get(k):
                out.add(_n(x[k]))
    esc = {(e.get("orgaoId"), e.get("mes")): e for e in (carregar("../config/esclarecimentos_fonte.json") or {}).get("pedidos") or []}
    for d in (carregar("verificacao/conferencia_supersalarios.json") or {}).get("divergenciasFonte") or []:
        if not (esc.get((d.get("orgaoId"), d.get("mes"))) or {}).get("resposta"):
            out.add(_n(d.get("nome")))
    return out


def aplicar_regras(p):
    """Tira da lista os nomes bloqueados; se o primeiro (o citado na legenda) sair, o tema é pulado (None)."""
    bloq = nomes_bloqueados()
    fora = [i for i, (nome, _s, _v) in enumerate(p["lista"]) if _n(nome) in bloq]
    if 0 in fora:
        return None, f"o primeiro da lista ({p['lista'][0][0]}) está em sinal de atenção ou divergência sem resposta"
    p["lista"] = [x for i, x in enumerate(p["lista"]) if i not in fora]
    return p, (f"{len(fora)} item(ns) retirado(s) da lista (sinal de atenção ou divergência sem resposta)" if fora else "nenhum nome bloqueado")


def carregar(nome):
    try:
        return json.load(open(DADOS / nome, encoding="utf-8"))
    except Exception:
        return {}


def brl(v, centavos=False):
    s = f"{v:,.2f}" if centavos else f"{round(v):,}"
    return "R$ " + s.replace(",", "X").replace(".", ",").replace("X", ".")


def mil(n):
    """Contagem no padrão brasileiro: 1.074 (não 1074)."""
    try:
        return f"{int(round(float(n))):,}".replace(",", ".")
    except (TypeError, ValueError):
        return str(n)


def curto(v):
    for lim, nome in ((1e9, "bilhão" if v < 2e9 else "bilhões"), (1e6, "milhão" if v < 2e6 else "milhões"), (1e3, "mil")):
        if v >= lim:
            n = f"{v / lim:,.1f}".replace(".", ",").replace(",0", "")
            return f"R$ {n} {nome}"
    return brl(v)


def titulo_nome(t):
    pequenas = {"de", "da", "do", "das", "dos", "e", "em", "a", "o"}
    pal = re.sub(r"\s+", " ", (t or "").strip()).lower().split()
    return " ".join(p if (i and p in pequenas) else (p.upper() if p in {"ms", "cg", "ltda", "me", "s/a", "sa"} else p.capitalize()) for i, p in enumerate(pal))


# ─────────────────────────── temas ───────────────────────────

def t_precos(n):
    d = carregar("precos.json")
    prods = [p for p in d.get("produtos") or [] if p["compras"] >= 8]
    if not prods:
        return None
    p = prods[n % len(prods)]
    vistos, top = set(), []
    for x in p["itens"]:
        if x["orgao"] in vistos or x["vsMediana"] <= 0:
            continue
        vistos.add(x["orgao"])
        top.append(x)
        if len(top) == 5:
            break
    item = p["nome"].split(" (")[0].lower()
    un = p["unidade"]
    return {"tema": "precos", "kicker": "PREÇOS PAGOS", "titulo": f"Quem pagou mais caro: {item}",
            "numero": brl(top[0]["precoUnidade"], True), "rotulo": f"por {un}, pago por {titulo_nome(top[0]['orgao'])}. O preço do meio em MS é {brl(p['mediana'], True)}",
            "lista_titulo": f"{p['nome']}: os 5 preços mais altos",
            "lista": [(titulo_nome(x["orgao"]), f"{x.get('cidade') or ''} · {'+' if x['vsMediana'] > 0 else ''}{x['vsMediana']:.0f}% sobre a mediana".strip(" ·"),
                       brl(x["precoUnidade"], True)) for x in top],
            "fonte": "Portal Nacional de Contratações Públicas (PNCP), compras de órgãos de MS em " + str(d.get("ano")),
            "aba": "precos",
            "nota": "Frete, prazo, quantidade e cidade influem no preço. Pagar acima da mediana é um ponto para perguntar, não prova de irregularidade.",
            "legenda": (f"Quanto os órgãos públicos de MS pagam pelo mesmo produto? Comparamos {mil(p['compras'])} compras de {item} feitas em {d.get('ano')} "
                        f"por {mil(p['orgaos'])} órgãos (prefeituras, câmaras, Governo do Estado).\n\n"
                        f"O preço do meio (mediana) foi {brl(p['mediana'], True)} por {un}. O mais alto: {brl(top[0]['precoUnidade'], True)}, "
                        f"pago por {titulo_nome(top[0]['orgao'])}.\n\nFrete, quantidade e cidade pesam no preço — diferença grande é um bom motivo para perguntar.")}


def t_shows(n):
    d = carregar("shows.json")
    s = [x for x in d.get("shows") or [] if x.get("artista")][:5]
    if not s:
        return None
    return {"tema": "shows", "kicker": "SHOWS COM DINHEIRO PÚBLICO", "titulo": f"Os maiores cachês pagos em MS em {d['ano']}",
            "numero": curto(d["valorShows"]), "rotulo": f"em {mil(d['totalShows'])} shows contratados sem licitação pelo Estado, prefeituras e câmaras",
            "lista_titulo": "Os 5 maiores cachês",
            "lista": [(titulo_nome(x["artista"]), f"{x.get('cidade') or ''} · {titulo_nome(x.get('evento') or '')}".strip(" ·"), brl(x["valor"])) for x in s],
            "fonte": "Portal Nacional de Contratações Públicas (PNCP), contratações por inexigibilidade", "aba": "shows",
            "nota": "Contratar artista sem licitação é permitido por lei (inexigibilidade). O que mostramos é quanto foi pago, a quem e para qual evento.",
            "legenda": (f"Em {d['ano']}, órgãos públicos de MS já contrataram {mil(d['totalShows'])} shows, somando {curto(d['valorShows'])} em cachês.\n\n"
                        f"O maior: {titulo_nome(s[0]['artista'])}, {brl(s[0]['valor'])}, em {s[0].get('cidade') or 'MS'}.\n\n"
                        "No site dá para ver todos os shows de cada cidade e quanto cada uma pagou pelo mesmo artista.")}


def t_obras(n):
    d = carregar("obras.json")
    ob = [o for o in d.get("obras") or [] if {"paralisada", "vencida"} & set(o.get("marcas") or [])]
    if not ob:
        return None
    ob.sort(key=lambda o: -(o.get("valor") or 0))
    soma = sum(o.get("valor") or 0 for o in ob)

    def sub(o):
        m = "prazo vencido" if "vencida" in o["marcas"] else "teve paralisação"
        return f"{(o.get('municipios') or '').split(',')[0].replace('/MS', '')} · {m} · {o.get('executado') or 0:.0f}% feita".strip(" ·")
    return {"tema": "obras", "kicker": "OBRAS ATRASADAS", "titulo": "Obras do Governo de MS paradas ou com prazo vencido",
            "numero": curto(soma), "rotulo": f"em {mil(len(ob))} obras que tiveram paralisação ou passaram do prazo sem terminar",
            "lista_titulo": "As 5 maiores",
            "lista": [(o["objeto"].capitalize(), sub(o), curto(o.get("valor") or 0)) for o in ob[:5]],
            "fonte": "Portal da Transparência do Estado de MS, contratos de obras (prazo, aditivos e % executado)", "aba": "obras",
            "nota": "Usamos o % executado e as datas que o próprio Estado publica. Atraso pode ter motivo técnico; vale cobrar a explicação.",
            "legenda": (f"{mil(len(ob))} obras do Governo de MS tiveram paralisação ou passaram do prazo sem terminar — {curto(soma)} em contratos.\n\n"
                        "No site estão todas, com empresa, cidade, prazo e quanto já foi executado. Tem obra parada na sua cidade?")}


def t_vereadores(n):
    d = carregar("camara_municipal.json")
    ano = d.get("ano") or HOJE.year
    vs = [(v["nome"], v.get("partido") or "", (v.get("verbaIndenizatoria") or {}).get(f"gastoPago{ano}") or 0) for v in d.get("vereadores") or []]
    vs = sorted([v for v in vs if v[2]], key=lambda v: -v[2])
    if not vs:
        return None
    soma = sum(v[2] for v in vs)
    return {"tema": "vereadores", "kicker": "CÂMARA DE CAMPO GRANDE", "titulo": f"Quem mais gastou verba indenizatória em {ano}",
            "numero": curto(soma), "rotulo": f"gastos pelos {mil(len(vs))} vereadores de Campo Grande, além do salário",
            "lista_titulo": "Os 5 que mais gastaram", "lista": [(v[0], v[1], brl(v[2])) for v in vs[:5]],
            "fonte": "Portal da Transparência da Câmara Municipal de Campo Grande (Atos da Mesa 27 e 28/2017)", "aba": "camara",
            "nota": "A verba indenizatória é permitida e reembolsa despesas do mandato. No site estão as notas fiscais e os fornecedores de cada vereador.",
            "legenda": (f"Os vereadores de Campo Grande já usaram {curto(soma)} de verba indenizatória em {ano}, além do salário.\n\n"
                        f"Quem mais gastou: {vs[0][0]} ({vs[0][1]}), {brl(vs[0][2])}.\n\n"
                        "No site estão as notas fiscais, os fornecedores e a equipe do gabinete de cada um.")}


def t_publicidade(n):
    d = carregar("publicidade.json")
    ag = (d.get("agencias") or [])[:5]
    if not ag:
        return None
    tot = d["estado"]["total"] + d["prefeitura"]["total"]
    return {"tema": "publicidade", "kicker": "PUBLICIDADE", "titulo": f"Quanto o Governo de MS e a Prefeitura de CG pagam em propaganda",
            "numero": curto(tot), "rotulo": f"pagos a agências de publicidade em {d['ano']} ({curto(d['estado']['total'])} do Estado e {curto(d['prefeitura']['total'])} da Prefeitura)",
            "lista_titulo": "As 5 agências que mais receberam",
            "lista": [(titulo_nome(a["nome"]), "Estado e Prefeitura" if a["estado"] and a["prefeitura"] else ("Governo de MS" if a["estado"] else "Prefeitura de CG"), curto(a["total"])) for a in ag],
            "fonte": "Portal da Transparência do Estado de MS e SIG-Transparência da Prefeitura de Campo Grande", "aba": "publicidade",
            "nota": "Publicidade de governo é permitida por lei e deve ter caráter informativo. Mostramos quanto foi pago e a quem.",
            "legenda": (f"Em {d['ano']}, o Governo de MS e a Prefeitura de Campo Grande já pagaram {curto(tot)} a agências de publicidade.\n\n"
                        f"A que mais recebeu: {titulo_nome(ag[0]['nome'])}, {curto(ag[0]['total'])}.")}


def t_entidades(n):
    d = carregar("entidades.json")
    en = (d.get("entidades") or [])[:5]
    if not en:
        return None
    return {"tema": "entidades", "kicker": "ONGS E ENTIDADES", "titulo": "Dinheiro público para ONGs, associações e fundações em MS",
            "numero": curto(d["total"]), "rotulo": f"pagos em {d['ano']} a {d['quantidade']} entidades sem fins lucrativos pelo Estado, pela Prefeitura de CG e por emendas",
            "lista_titulo": "As 5 que mais receberam",
            "lista": [(titulo_nome(e.get("fantasia") or e["nome"])[:70], f"{e.get('area') or ''} · {titulo_nome(e.get('municipio') or '')}".strip(" ·"), curto(e["total"])) for e in en],
            "fonte": "Portal da Transparência do Estado de MS, SIG-Transparência da Prefeitura de CG, emendas (CGU) e cadastro da Receita Federal", "aba": "entidades",
            "nota": "Boa parte desse dinheiro paga hospitais e serviços de saúde e assistência. No site está quanto cada entidade recebeu e de quem.",
            "legenda": (f"{d['quantidade']} entidades sem fins lucrativos receberam {curto(d['total'])} de dinheiro público em MS em {d['ano']}.\n\n"
                        f"A que mais recebeu: {titulo_nome(en[0].get('fantasia') or en[0]['nome'])}, {curto(en[0]['total'])}.")}


def t_emendas(n):
    d = carregar("emendas_municipios.json")
    m = sorted(d.get("municipios") or [], key=lambda x: -(x.get("total") or 0))[:5]
    if not m:
        return None
    return {"tema": "emendas", "kicker": "EMENDAS PARLAMENTARES", "titulo": f"As cidades de MS que mais receberam emendas em {d['ano']}",
            "numero": curto(d["totalMS"]), "rotulo": "em emendas de deputados federais e senadores pagas para MS",
            "lista_titulo": "As 5 cidades que mais receberam",
            "lista": [(x["municipio"], f"{mil(len(x.get('autores') or []))} parlamentares autores", curto(x["total"])) for x in m],
            "fonte": "Portal da Transparência do Governo Federal (CGU), emendas parlamentares pagas", "aba": "emendas",
            "nota": "No site está quem mandou cada emenda, para qual cidade e quem recebeu o dinheiro.",
            "legenda": (f"Deputados federais e senadores já mandaram {curto(d['totalMS'])} em emendas pagas para MS em {d['ano']}.\n\n"
                        f"A cidade que mais recebeu: {m[0]['municipio']}, {curto(m[0]['total'])}. Procure a sua no site.")}


def t_supersalarios(n):
    d = carregar("supersalarios.json")
    bloq = nomes_bloqueados()  # fora: contracheque com divergência da fonte sem resposta ao pedido de esclarecimento
    r = [x for x in d.get("ranking") or [] if (x.get("base") or 0) >= 1 and _n(x.get("nome")) not in bloq][:5]  # e pagamento eventual
    if not r:
        return None
    return {"tema": "supersalarios", "kicker": "SUPERSALÁRIOS", "titulo": "Quantos ganham acima do teto em MS",
            "numero": mil(d['acimaTeto']) + " pessoas",
            "rotulo": f"receberam acima do teto de {brl(d['teto'])} em algum mês de {d['ano']}, somando {curto(d['valorAcimaTeto'])} além do teto",
            "lista_titulo": "Os 5 maiores pagamentos brutos de um mês (por cargo)",
            "lista": [(x["cargo"].capitalize(), x.get("orgaoSigla") or x.get("orgao") or "", brl(x["bruto"])) for x in r],
            "fonte": "Portais da transparência do Estado, do TCE-MS e da Câmara de CG, e o DadosJusBr (TJMS e TRT24)", "aba": "supersalarios",
            "nota": "Parte das verbas fica fora do teto por lei (férias, indenizações e atrasados). No site está o detalhe de cada pagamento.",
            "legenda": (mil(d['acimaTeto']) + f" pessoas do poder público de MS receberam acima do teto de {brl(d['teto'])} em algum mês de {d['ano']}.\n\n"
                        "Grande parte vem de verbas que a lei deixa fora do teto (os chamados penduricalhos). No site estão os valores, cargo e órgão.")}


FUNCOES = {"precos": t_precos, "shows": t_shows, "obras": t_obras, "vereadores": t_vereadores, "publicidade": t_publicidade,
           "entidades": t_entidades, "emendas": t_emendas, "supersalarios": t_supersalarios}


# ─────────────────────────── imagens ───────────────────────────

def base(pagina, total):
    img = Image.new("RGB", (W, H), FUNDO)
    d = ImageDraw.Draw(img)
    for i in range(H):
        c = int(8 * i / H)
        d.line([(0, i), (W, i)], fill=(FUNDO[0] + c, FUNDO[1] + c, FUNDO[2] + c + 5))
    d.rectangle([0, 0, W, 12], fill=OURO)
    cadeado(d, 72, 82, 36)
    d.text((140, 70), "COFRE", font=fonte("x", 38), fill=OURO)
    d.text((140 + d.textlength("COFRE ", font=fonte("x", 38)), 70), "ABERTO MS", font=fonte("x", 38), fill=TINTA)
    t = f"{pagina}/{total}"
    d.text((W - 72 - d.textlength(t, font=fonte("s", 30)), 76), t, font=fonte("s", 30), fill=CINZA)
    d.line([(72, H - 110), (W - 72, H - 110)], fill=LINHA, width=2)
    d.text((72, H - 88), "cofreabertoms.com.br", font=fonte("s", 32), fill=OURO)
    return img, d


def texto(d, xy, txt, f, cor, larg, max_l, entre):
    x, y = xy
    for ln in quebra(d, txt, f, larg, max_l):
        d.text((x, y), ln, font=f, fill=cor)
        y += entre
    return y


def capa(p):
    img, d = base(1, 3)
    y = 300
    d.rounded_rectangle([72, y, 72 + d.textlength(p["kicker"], font=fonte("x", 30)) + 40, y + 56], radius=12, fill=OURO)
    d.text((92, y + 10), p["kicker"], font=fonte("x", 30), fill=FUNDO)
    y = texto(d, (72, y + 100), p["titulo"], fonte("x", 76), TINTA, W - 144, 4, 90) + 50
    tam = 120
    while d.textlength(p["numero"], font=fonte("x", tam)) > W - 144 and tam > 60:
        tam -= 4
    d.text((72, y), p["numero"], font=fonte("x", tam), fill=OURO)
    y = texto(d, (72, y + tam + 24), p["rotulo"], fonte("s", 38), TINTA, W - 144, 4, 52)
    t = "arraste para o lado  →"
    d.text((W - 72 - d.textlength(t, font=fonte("s", 32)), H - 88), t, font=fonte("s", 32), fill=CINZA)
    return img


def lista(p):
    img, d = base(2, 3)
    y = texto(d, (72, 200), p["lista_titulo"], fonte("x", 54), TINTA, W - 144, 2, 66) + 40
    for i, (nome, sub, valor) in enumerate(p["lista"], 1):
        d.line([(72, y), (W - 72, y)], fill=LINHA, width=2)
        y += 30
        d.text((72, y), str(i), font=fonte("x", 56), fill=OURO)
        fv = fonte("x", 40)
        lv = d.textlength(valor, font=fv)
        d.text((W - 72 - lv, y + 8), valor, font=fv, fill=OURO)
        larg = W - 72 - lv - 40 - 150
        yy = texto(d, (150, y + 4), nome, fonte("x", 36), TINTA, larg, 2, 44)
        yy = texto(d, (150, yy + 4), sub, fonte("r", 28), CINZA, larg, 1, 36)
        y = max(yy, y + 70) + 26
    return img


def final(p):
    img, d = base(3, 3)
    y = texto(d, (72, 230), "Veja todos os dados, com o link de cada documento oficial", fonte("x", 58), TINTA, W - 144, 4, 72) + 50
    d.rounded_rectangle([72, y, W - 72, y + 110], radius=24, fill=OURO)
    t = "cofreabertoms.com.br"
    d.text(((W - d.textlength(t, font=fonte("x", 52))) / 2, y + 24), t, font=fonte("x", 52), fill=FUNDO)
    y += 170
    y = texto(d, (72, y), p["nota"], fonte("s", 34), TINTA, W - 144, 5, 48) + 40
    y = texto(d, (72, y), "Fonte: " + p["fonte"] + ".", fonte("r", 30), CINZA, W - 144, 4, 42) + 20
    texto(d, (72, y), f"Dados coletados em {HOJE.strftime('%d/%m/%Y')}. Site independente e sem fins lucrativos.", fonte("r", 30), CINZA, W - 144, 2, 42)
    return img


SW, SH = 1080, 1920  # story (vertical)


def frase_story(p):
    """Frase curta do story: o rótulo do número, cortado na primeira vírgula/ponto se for longo."""
    r = str(p.get("rotulo") or "")
    if len(r) > 110:
        for sep in (", ", ". ", " — "):
            if sep in r[:110]:
                return r[:r.index(sep, 0, 110)]
        return r[:107].rsplit(" ", 1)[0] + "…"
    return r


def story(p):
    """Story 1080×1920 na identidade do site: marca, tema, o número principal do post do dia, uma frase curta e
    "veja no perfil / link na bio". Texto importante fora das faixas de cima e de baixo (ícones do Instagram)."""
    img = Image.new("RGB", (SW, SH), FUNDO)
    d = ImageDraw.Draw(img)
    for i in range(SH):
        c = int(10 * i / SH)
        d.line([(0, i), (SW, i)], fill=(FUNDO[0] + c, FUNDO[1] + c, FUNDO[2] + c + 6))
    d.rectangle([0, 0, SW, 14], fill=OURO)
    cadeado(d, 80, 300, 44)
    d.text((158, 286), "COFRE", font=fonte("x", 46), fill=OURO)
    d.text((158 + d.textlength("COFRE ", font=fonte("x", 46)), 286), "ABERTO MS", font=fonte("x", 46), fill=TINTA)
    y = 470
    d.rounded_rectangle([80, y, 80 + d.textlength(p["kicker"], font=fonte("x", 34)) + 44, y + 62], radius=14, fill=OURO)
    d.text((102, y + 11), p["kicker"], font=fonte("x", 34), fill=FUNDO)
    y = texto(d, (80, y + 120), p["titulo"], fonte("x", 70), TINTA, SW - 160, 4, 84) + 60
    tam = 150
    while d.textlength(p["numero"], font=fonte("x", tam)) > SW - 160 and tam > 70:
        tam -= 4
    d.text((80, y), p["numero"], font=fonte("x", tam), fill=OURO)
    y = texto(d, (80, y + tam + 34), frase_story(p), fonte("s", 44), TINTA, SW - 160, 4, 60)
    caixa = SH - 470
    d.rounded_rectangle([80, caixa, SW - 80, caixa + 130], radius=28, fill=OURO)
    t = "Veja no perfil · link na bio"
    d.text(((SW - d.textlength(t, font=fonte("x", 50))) / 2, caixa + 34), t, font=fonte("x", 50), fill=FUNDO)
    t = "@cofre_abertoms · cofreabertoms.com.br"
    d.text(((SW - d.textlength(t, font=fonte("s", 36))) / 2, caixa + 170), t, font=fonte("s", 36), fill=CINZA)
    return img


def main():
    PASTA.mkdir(exist_ok=True)
    try:
        hist = json.load(open(PASTA / "historico.json", encoding="utf-8"))
    except Exception:
        hist = {"publicados": []}
    n = len(hist["publicados"])
    if len(sys.argv) > 1:
        ordem = [sys.argv[1]]
    else:
        ult = hist["publicados"][-1]["tema"] if hist["publicados"] else None
        i = (TEMAS.index(ult) + 1) % len(TEMAS) if ult in TEMAS else 0
        ordem = TEMAS[i:] + TEMAS[:i]
    p, regras = None, []
    recusados = [r.get("tema") for r in hist.get("recusados") or []]
    if len(sys.argv) <= 1 and recusados:  # tema recusado no modo aprovação: o próximo rascunho é de outro tema
        ordem = [t for t in ordem if t != recusados[-1]] + [recusados[-1]]
    for tema in ordem:
        ok, motivo = tema_liberado(tema)
        if not ok:
            print(f"  ⏭ {tema}: {motivo}")
            continue
        p = FUNCOES[tema](sum(1 for x in hist["publicados"] if x["tema"] == tema))
        if not p:
            continue
        p, motivo2 = aplicar_regras(p)
        if not p:
            print(f"  ⏭ {tema}: {motivo2}")
            continue
        regras = [motivo, motivo2]
        break
    if not p:
        print("⚠️ nenhum tema com dados")
        return
    # apaga o rascunho anterior não publicado
    publicadas = {img for x in hist["publicados"] for img in (x.get("imagens") or []) + ([x["story"]] if x.get("story") else [])}
    for f in PASTA.glob("*.jpg"):
        if f.name not in publicadas:
            f.unlink()
    nomes = []
    for i, fn in enumerate((capa, lista, final), 1):
        buf = io.BytesIO()
        fn(p).save(buf, "JPEG", quality=88, optimize=True, progressive=False)
        nome = f"{HOJE.isoformat()}-{p['tema']}-{i}.jpg"
        (PASTA / nome).write_bytes(buf.getvalue())
        nomes.append(nome)
    buf = io.BytesIO()
    story(p).save(buf, "JPEG", quality=88, optimize=True, progressive=False)
    nome_story = f"{HOJE.isoformat()}-{p['tema']}-story.jpg"
    (PASTA / nome_story).write_bytes(buf.getvalue())
    legenda = (p["legenda"] + f"\n\n🔗 Veja tudo no site: cofreabertoms.com.br (link na bio)\nFonte: {p['fonte']}.\n\n{TAGS}")
    (PASTA / "proximo.json").write_text(json.dumps({"tema": p["tema"], "data": HOJE.isoformat(), "imagens": nomes,
                                                    "urls": [f"{SITE}/instagram/{x}" for x in nomes], "legenda": legenda,
                                                    "link": f"{SITE}/cofre-aberto-ms.html#aba={p['aba']}",
                                                    "regras": "; ".join(regras), "story": nome_story,
                                                    "storyUrl": f"{SITE}/instagram/{nome_story}"}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✅ post do Instagram: {p['tema']} — {', '.join(nomes)} (post nº {n + 1})")


if __name__ == "__main__":
    main()
