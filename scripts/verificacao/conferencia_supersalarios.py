#!/usr/bin/env python3
"""
Cofre Aberto MS — conferência AUTOMÁTICA de Supersalários (substitui a conferência manual)

Roda no robô diário, depois da coleta (precisa da folha completa, sem CPF: artefato folha-supersalarios-* CIFRADO — artefato de repositório público
é baixável por qualquer usuário logado no GitHub; ver SEGURANCA_ARTEFATOS.md).
Grupos (os mesmos da antiga lista manual):
  supersalario   todos os contracheques com líquido acima do teto do mês
  intermediario  100 sorteados (semente 42, estratificado por órgão) entre bruto acima e líquido abaixo do teto
  amostra        100 sorteados abaixo do teto (semente = data, estratificado por órgão), com janela de 30 dias + hash
Cada contracheque é reconsultado e recebe status "confere", "diverge" ou "não verificado (motivo)":
  Governo MS     nova consulta à folha do Estado pelo nome dentro do órgão (mesma matrícula): bruto, eventuais e
                 líquido. Rótulo: "mesma fonte — confirma a leitura". A fonte publica só remuneração fixa, eventuais e
                 valor após deduções: não é possível separar verbas indenizatórias.
  TRT24          comparado com a folha lida no portal do próprio TRT24 (Anexo VIII) na mesma coleta
                 (dados/trt24_magistrados.json): bruto e líquido. Rótulo: "conferido no arquivo original do órgão".
  TJMS           o portal do TJMS bloqueia acessos de fora do Brasil: sem o arquivo original → não verificado.
  TCE-MS         servidores: nova consulta ao portal do TCE por matrícula (salário-base, outras verbas, líquido).
                 Membros (contracheque em PDF): não verificado até a dupla extração do PDF do TCE entrar.
Teto: config/teto.json (valor, data de início e lei), aplicado pelo mês de cada contracheque.
Rubricas (Judiciário e membros do TCE): config/rubricas.json (remuneratório, indenizatório ou excluído do teto, com a
base legal). Rubrica fora da tabela → "não verificado — rubrica não classificada" (aviso no log). Não adivinha.

Saídas: dados/verificacao/conferencia_supersalarios.csv (sem colunas manuais) e dados/verificacao/conferencia_supersalarios.json
(totais por grupo, órgão e status; Clopper–Pearson da amostra; rubricas não classificadas).

Uso: python3 scripts/verificacao/conferencia_supersalarios.py [--folha ARQ] [--sem-rede]
"""
import csv, gzip, hashlib, json, os, random, re, sys, time, unicodedata
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(Path(__file__).parent))
from checagem_automatica import unidade, mes_iso  # noqa: E402
from gerar_conferencia import sorteio, fonte_original  # noqa: E402
from resumo_conferencia import clopper_pearson_sup  # noqa: E402

DADOS = ROOT / "dados"
FOLHA = ROOT / "folha_completa" / "folha_supersalarios.jsonl.gz"
SAIDA_CSV = DADOS / "verificacao" / "conferencia_supersalarios.csv"
SAIDA_JSON = DADOS / "verificacao" / "conferencia_supersalarios.json"
CONF = ROOT / "config"
ROTULO = {"governo": "mesma fonte — confirma a leitura", "trt24": "conferido no arquivo original do órgão",
          "tce": "mesma fonte — confirma a leitura", "tjms": "conferido no DadosJusBr (o portal do TJMS bloqueia acesso de fora do Brasil)"}
GOVERNO_SEM_RUBRICAS = ("a fonte publica só remuneração fixa, eventuais e valor após deduções; "
                        "não é possível separar verbas indenizatórias")
COLUNAS = ["grupo", "nome", "orgao", "mes", "bruto", "liquido", "teto_mes", "lei_teto", "excedente", "total_remuneratorio",
           "total_indenizatorio", "total_excluido_do_teto", "abate_teto", "status", "motivo", "conferido_em", "rotulo", "link_contracheque_original"]


# Prazo interno (job próprio "conferir_supersalarios", limite de 45 min): passado o prazo, o que falta reconsultar fica
# "não verificado — tempo esgotado" e o resultado é gravado com o que já foi conferido.
PRAZO_MIN = float(os.environ.get("CONF_SS_PRAZO_MIN") or 40)
FIM = time.monotonic() + PRAZO_MIN * 60
ESGOTADO = ("nao_verificado", f"tempo esgotado na conferência (prazo de {PRAZO_MIN:.0f} min)")


def esgotado():
    return time.monotonic() > FIM


def brl(v):
    return f"{v or 0:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def arg(nome, padrao):
    return sys.argv[sys.argv.index(nome) + 1] if nome in sys.argv else padrao


def norm(t):
    t = "".join(c for c in unicodedata.normalize("NFD", str(t or "").upper()) if unicodedata.category(c) != "Mn")
    return re.sub(r"[^A-Z ]", "", t).strip()


def tetos():
    vs = sorted(json.load(open(CONF / "teto.json", encoding="utf-8"))["versoes"], key=lambda v: v["desde"])
    return vs


def teto_do_mes(mes, vs=None):
    """Teto em vigor no mês do contracheque ("MM/AAAA"); None se o mês for anterior à primeira versão."""
    iso = mes_iso(mes) + "-01"
    val = None
    for v in vs or tetos():
        if v["desde"] <= iso:
            val = v
    return val


def rubricas():
    return json.load(open(CONF / "rubricas.json", encoding="utf-8"))["rubricas"]


def classifica(p, tab):
    """(remuneratório, indenizatório, excluído do teto, rubricas não classificadas) — só onde há rubricas."""
    tot = {"remuneratorio": 0.0, "indenizatorio": 0.0, "excluida_do_teto": 0.0}
    sem = []
    itens = list(p.get("itens") or [])
    base = p.get("base") or 0
    if p.get("orgaoId") in ("tjms", "trt24", "trems") and base:
        itens = [{"item": "Subsídio", "valor": base}] + itens
    for i in itens:
        nome = re.sub(r"\s+", " ", str(i.get("item") or "")).strip()
        r = tab.get(nome)
        if not r:
            sem.append(nome)
            continue
        tot[r["categoria"]] += i.get("valor") or 0
    return {k: round(v, 2) for k, v in tot.items()}, sem


def hash_cc(p):
    return hashlib.sha1(json.dumps([p.get("orgaoId"), p.get("orgaoSigla"), p.get("matricula"), p.get("nome"), p.get("mes"),
                                    round(p.get("bruto") or 0, 2), round(p.get("liquido") or 0, 2)]).encode()).hexdigest()[:12]


# ── reconsultas ──────────────────────────────────────────────────────────────────────────────────────────────
def reconsulta_governo(ps, sem_rede=False):
    """{id(p): (status, motivo)} — nova consulta à folha do Estado pelo nome dentro do órgão (mesma matrícula)."""
    out = {}
    if sem_rede or not ps:
        return {id(p): ("nao_verificado", "reconsulta não feita (sem rede)") for p in ps}
    import validar_fontes as vf
    import coletar_governo_ms as g
    from concurrent.futures import ThreadPoolExecutor

    def um(p):
        if esgotado():
            return p, ESGOTADO
        try:
            mm, aa = p["mes"].split("/")
            prm = {"anoexercicio": int(aa), "mescompetencia": int(mm), "tipoFolha": 1, "nome": p["nome"].upper(), "pageno": 1,
                   "pagesize": 50, "exportarcsv": "false"}
            if p.get("orgaoSigla") not in vf.ORGAO_PAI:
                prm["orgao"] = p["orgaoSigla"]
            r = g.requisitar(vf.FOLHA_GOV, prm, 120)
            d = [x for x in r.json().get("data") or [] if str(x.get("matricula")) == str(p.get("matricula"))]
        except Exception as e:
            return p, ("nao_verificado", f"fonte inacessível ({type(e).__name__})")
        if not d:
            return p, ("nao_verificado", "matrícula não encontrada na nova consulta (nome/órgão)")
        x = d[0]
        campos = [("bruto", p["bruto"], (x.get("remuneracaoFixa") or 0) + (x.get("remuneracoesEventuais") or 0)),
                  ("eventuais", p.get("outras") or 0, x.get("remuneracoesEventuais") or 0),
                  ("líquido", p["liquido"], x.get("remuneracaoAposDeducoes") or 0)]
        ruins = [f"{c}: site R$ {brl(a)} × fonte R$ {brl(b)}" for c, a, b in campos if abs((a or 0) - (b or 0)) > 1]
        return p, (("diverge", "; ".join(ruins)) if ruins else ("confere", "bruto, eventuais e líquido iguais"))
    with ThreadPoolExecutor(4) as ex:  # no máximo 4 consultas ao mesmo tempo no gateway do Estado
        for p, st in ex.map(um, ps):
            out[id(p)] = st
    return out


def ocr_tce_membros(pdf_bytes):
    """Segundo extrator do PDF dos membros do TCE: OCR (tesseract) da página renderizada. A página só mostra as
    colunas até a VPNI — as demais rubricas ficam fora da área visível (só na camada de texto). Devolve
    {matrícula: (subsídio, vpni)} ou None se o OCR não estiver disponível."""
    import shutil, subprocess, tempfile
    if not (shutil.which("pdftoppm") and shutil.which("tesseract")):
        return None
    num = lambda t: float(t.replace(".", "").replace(",", "."))
    out = {}
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / "m.pdf"
        f.write_bytes(pdf_bytes)
        subprocess.run(["pdftoppm", "-r", "400", "-gray", "-png", str(f), str(Path(d) / "p")], check=True, timeout=120)
        for img in sorted(Path(d).glob("p*.png")):
            txt = subprocess.run(["tesseract", str(img), "stdout", "-l", "por", "--psm", "6"], capture_output=True, timeout=120).stdout.decode("utf-8", "ignore")
            for l in txt.splitlines():
                m = re.match(r"\s*(\d{5})\s.*?(\d{2}/\d{4})\s+(\d[\d.]*,\d{2})(?:\s+(\d[\d.]*(?:,\d{2})?))?", l)
                if m:
                    out[m.group(1)] = (num(m.group(3)), num(m.group(4)) if m.group(4) and "," in m.group(4) else float(m.group(4) or 0))
    return out


def reconsulta_tce_membros(ps, sem_rede=False):
    """Membros do TCE (contracheque em PDF): (1) releitura da camada de texto do PDF do mesmo mês — difere do site =
    diverge; (2) OCR da página — confere subsídio e VPNI de cada matrícula. Mesmo com os dois de acordo, o contracheque
    fica "não verificado": a página do PDF só mostra 2 das colunas; as demais rubricas estão só na camada de texto."""
    out = {}
    if sem_rede or not ps:
        return {id(p): ("nao_verificado", "reconsulta não feita (sem rede)") for p in ps}
    import requests
    import coletar_supersalarios as cs_
    for mes in sorted({p["mes"] for p in ps}):
        m, a = mes.split("/")
        lst = [p for p in ps if p["mes"] == mes]
        if esgotado():
            out.update({id(p): ESGOTADO for p in lst})
            continue
        try:
            r = requests.get(f"{cs_.TCE}/Servidores/Exportar", params={"ano": int(a), "mes": int(m), "tipo": 2, "vinculo": 2, "tipoConteudo": 1},
                             headers=cs_.UA, timeout=120)
            r.raise_for_status()
            texto = {x["matricula"]: x for x in cs_.tce_membros(int(a), int(m))}
            ocr = ocr_tce_membros(r.content)
        except Exception as e:
            out.update({id(p): ("nao_verificado", f"PDF dos membros do TCE inacessível ({type(e).__name__})") for p in lst})
            continue
        for p in lst:
            x = texto.get(str(p.get("matricula")))
            if not x:
                out[id(p)] = ("nao_verificado", "matrícula não encontrada na releitura do PDF")
                continue
            ruins = [f"{c}: site R$ {brl(a_)} × PDF R$ {brl(b)}" for c, a_, b in (("bruto", p["bruto"], x["bruto"]), ("líquido", p["liquido"], x["liquido"]))
                     if abs((a_ or 0) - (b or 0)) > 1]
            if ruins:
                out[id(p)] = ("diverge", "; ".join(ruins))
                continue
            if ocr is None:
                out[id(p)] = ("nao_verificado", "uma leitura só do PDF (OCR indisponível)")
                continue
            o = ocr.get(str(p.get("matricula")))
            vpni = next((i["valor"] for i in x.get("itens") or [] if "VPNI" in i["item"] or "Vantagem Pessoal" in i["item"]), 0.0)
            if not o or abs(o[0] - (x.get("base") or 0)) > 0.01 or abs(o[1] - vpni) > 0.01:
                out[id(p)] = ("nao_verificado", "o OCR da página e a camada de texto discordam no subsídio ou na VPNI")
                continue
            out[id(p)] = ("nao_verificado", "subsídio e VPNI conferem nos 2 extratores; as demais rubricas estão fora da área visível da página "
                                            "do PDF (só na camada de texto) — não há segunda leitura delas")
    return out


def reconsulta_tce(ps, sem_rede=False):
    out = reconsulta_tce_membros([p for p in ps if "membros" in (p.get("orgao") or "")], sem_rede)
    serv = [p for p in ps if "membros" not in (p.get("orgao") or "")]
    if not serv:
        return out
    if sem_rede:
        return {**out, **{id(p): ("nao_verificado", "reconsulta não feita (sem rede)") for p in serv}}
    import validar_fontes as vf
    por_mes = defaultdict(list)
    for p in serv:
        por_mes[p["mes"]].append(p)
    for mes, lst in por_mes.items():
        m, a = mes.split("/")
        if esgotado():
            out.update({id(p): ESGOTADO for p in lst})
            continue

        def lista(ep):
            res, pg = [], 0
            while True:
                r = vf.get(f"{vf.TCE_PESSOAS}/{ep}", {"ano": int(a), "mes": int(m), "pageNumber": pg, "pageSize": 500}, timeout=120)
                if r is None:
                    return None
                res += r.get("items") or []
                pg += 1
                if pg >= (r.get("totalPages") or 0):
                    return res
        rem, op = lista("Remuneracao"), lista("OutroPagamento")
        if rem is None:
            out.update({id(p): ("nao_verificado", "fonte inacessível (portal do TCE)") for p in lst})
            continue
        rm = {str(x.get("matricula")): x for x in rem}
        om = {str(x.get("matricula")): x for x in op or []}
        for p in lst:
            x = rm.get(str(p.get("matricula")))
            if not x:
                out[id(p)] = ("nao_verificado", "matrícula não encontrada na nova consulta")
                continue
            o = om.get(str(p.get("matricula"))) or {}
            campos = [("salário-base", p.get("base") or 0, x.get("totalVencimentosRemuneracao") or 0),
                      ("outras verbas", p.get("outras") or 0, o.get("totalVencimentoOutrosPagamentos") or 0),
                      ("líquido", p["liquido"], (x.get("totalCalculadoRemuneracao") or 0) + (o.get("totalCalculadoOutrosPagamentos") or 0))]
            ruins = [f"{c}: site R$ {brl(a_)} × fonte R$ {brl(b)}" for c, a_, b in campos if abs((a_ or 0) - (b or 0)) > 1]
            out[id(p)] = ("diverge", "; ".join(ruins)) if ruins else ("confere", "salário-base, outras verbas e líquido iguais")
    return out


ANEXO_REM = ("subsidio", "vantagensPessoais", "vantagensEventuais", "gratificacoes", "remuneracaoParadigma")


def anexo_viii(oid, mes):
    """Linhas do Anexo VIII (Res. CNJ 102/2009) do órgão no mês: TJMS pelo DadosJusBr (dados/tjms_magistrados.json — o
    portal do TJMS bloqueia acesso de fora do Brasil); TRT24 pela planilha original do portal do próprio tribunal (a do
    mês lida na coleta ou, se o mês for outro, baixada de novo). Devolve (linhas, rótulo) ou (None, motivo)."""
    arq = DADOS / ("tjms_magistrados.json" if oid == "tjms" else "trt24_magistrados.json")
    try:
        t = json.load(open(arq, encoding="utf-8"))
    except Exception:
        t = {}
    if oid == "tjms":
        if t.get("mesReferencia") != mes:
            return None, f"o Anexo VIII do TJMS lido é de {t.get('mesReferencia')}; o contracheque é de {mes}"
        return t.get("magistrados") or [], "conferido no DadosJusBr (o portal do TJMS bloqueia acesso de fora do Brasil)"
    if t.get("mesReferencia") == mes:
        return t.get("magistrados") or [], "conferido no arquivo original do órgão"
    try:  # outro mês: baixa a planilha do mês no portal do TRT24
        import requests
        import coletar_trt24 as tr
        s = requests.Session()
        url = tr.arquivo_do_mes(s, mes)
        if not url:
            return None, f"o portal do TRT24 não tem a planilha de {mes}"
        return tr.processa_ods(tr.get_com_retry(url).content), "conferido no arquivo original do órgão"
    except Exception as e:
        return None, f"arquivo original do TRT24 de {mes} inacessível ({type(e).__name__})"


def compara_anexo(ps, oid, teto_de):
    """Judiciário: contracheque do site × linha do Anexo VIII do mesmo nome e mês (bruto e líquido). Classifica pelas colunas
    do Anexo VIII (classificação oficial do órgão): remuneratório = subsídio + vantagens pessoais + vantagens eventuais +
    gratificações (+ paradigma); indenizatório = indenizações. Confere se a retenção por teto foi aplicada.
    Devolve {id(p): (status, motivo, classificação)}."""
    out, cache = {}, {}
    for p in ps:
        mes = p.get("mes")
        if mes not in cache and esgotado():
            out[id(p)] = (*ESGOTADO, None)
            continue
        if mes not in cache:
            cache[mes] = anexo_viii(oid, mes)
        linhas, rot = cache[mes]
        if linhas is None:
            out[id(p)] = ("nao_verificado", rot, None)
            continue
        xs = [x for x in linhas if norm(x.get("nome")) == norm(p.get("nome"))]
        if len(xs) != 1:
            out[id(p)] = ("nao_verificado", "nome não encontrado no Anexo VIII" if not xs else "nome ambíguo no Anexo VIII", None)
            continue
        x = xs[0]
        rem = round(sum(abs(x.get(k) or 0) for k in ANEXO_REM), 2)
        ind = round(abs(x.get("indenizacoes") or 0), 2)
        ret = round(abs(x.get("retencaoTeto") or 0), 2)
        teto = teto_de(p)
        # abate do teto: o que passa do teto no subsídio + vantagens pessoais (VPNI, ATS etc. entram no teto); indenizações
        # ficam fora; gratificações e vantagens eventuais não entram nesta conta (não presumimos a regra de cada uma)
        sujeito = sum(abs(x.get(k) or 0) for k in ("subsidio", "vantagensPessoais", "remuneracaoParadigma"))
        devido = max(0.0, round(sujeito - teto, 2))
        abate = ("não se aplica" if devido <= 1 else "aplicado" if ret + 1 >= devido else
                 f"retenção de R$ {brl(ret)} menor que o excedente de R$ {brl(devido)} do subsídio + vantagens pessoais")
        cl = {"remuneratorio": rem, "indenizatorio": ind, "retencaoTeto": ret, "abateTeto": abate, "excedente": devido}
        campos = [("bruto", p["bruto"], abs(x.get("remuneracaoBruta") or 0)), ("líquido", p["liquido"], abs(x.get("remuneracaoLiquida") or 0))]
        ruins = [f"{c}: site R$ {brl(a)} × Anexo VIII R$ {brl(b)}" for c, a, b in campos if abs((a or 0) - (b or 0)) > 1]
        out[id(p)] = (("diverge", "; ".join(ruins), cl) if ruins else ("confere", f"bruto e líquido iguais ao Anexo VIII · {rot}", cl))
    return out


# ── principal ────────────────────────────────────────────────────────────────────────────────────────────────
def main():
    arq, sem_rede = Path(arg("--folha", FOLHA)), "--sem-rede" in sys.argv
    hoje = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    if not arq.exists():
        print(f"⚠️ folha completa não encontrada ({arq}) — conferência de Supersalários não feita nesta coleta")
        return 0
    folha = [json.loads(l) for l in gzip.open(arq, "rt", encoding="utf-8") if l.strip()]
    vs = tetos()
    sem_teto = sorted({p.get("mes") for p in folha if teto_do_mes(p.get("mes") or "01/1900", vs) is None})
    if sem_teto:
        print(f"❌ meses sem teto definido em config/teto.json: {sem_teto}")
        return 1
    teto = lambda p: teto_do_mes(p["mes"], vs)
    sup = sorted((p for p in folha if p["liquido"] > teto(p)["valor"]), key=lambda p: -(p["liquido"] - teto(p)["valor"]))
    inter = sorted(sorteio([p for p in folha if p["bruto"] > teto(p)["valor"] >= p["liquido"]], 100, 42), key=lambda p: -p["bruto"])
    # amostra abaixo do teto: semente = data; primeiro o que não vale na janela de 30 dias (hash diferente ou novo)
    ant = {}
    try:
        ant = json.load(open(SAIDA_JSON, encoding="utf-8"))
    except Exception:
        pass
    limite = (date.today() - timedelta(days=30)).isoformat()
    janela = {h: em for h, em in (ant.get("amostraJanela") or {}).items() if em >= limite}
    abaixo = [p for p in folha if p["bruto"] <= teto(p)["valor"]]
    faltam = [p for p in abaixo if hash_cc(p) not in janela]
    amostra = sorted(sorteio(faltam if len(faltam) >= 100 else abaixo, 100, date.today().toordinal()), key=lambda p: -p["bruto"])
    grupos = [("supersalario", p) for p in sup] + [("intermediario", p) for p in inter] + [("amostra", p) for p in amostra]

    sel = [p for _, p in grupos]
    st = {}
    classif = {}
    for oid in ("tjms", "trt24"):  # ordem: as reconsultas rápidas primeiro; o Governo (o gargalo) por último
        for k, (s_, m_, cl) in compara_anexo([p for p in sel if p.get("orgaoId") == oid], oid, lambda p: teto(p)["valor"]).items():
            st[k], classif[k] = (s_, m_), cl
    st.update(reconsulta_tce([p for p in sel if p.get("orgaoId") == "tce"], sem_rede))
    st.update(reconsulta_governo([p for p in sel if p.get("orgaoId") == "governo"], sem_rede))
    n_esg = sum(1 for v in st.values() if v == ESGOTADO)
    if n_esg:
        print(f"  ⏱ prazo interno de {PRAZO_MIN:.0f} min: {n_esg} contracheque(s) ficaram para a próxima coleta (não verificado — tempo esgotado)")
    for p in sel:
        st.setdefault(id(p), ("nao_verificado", "sem reconsulta automática para este órgão"))

    tab = rubricas()
    sem_classe = Counter()
    linhas = []
    for grupo, p in grupos:
        t = teto(p)
        status, motivo = st[id(p)]
        rem = ind = exc = abate = ""
        if p.get("orgaoId") in ("tjms", "trt24"):  # classificação pelas colunas do Anexo VIII (oficial do órgão)
            cl = classif.get(id(p))
            if cl:
                rem, ind, abate = f"{cl['remuneratorio']:.2f}", f"{cl['indenizatorio']:.2f}", cl["abateTeto"]
            elif status == "confere":
                status, motivo = "nao_verificado", "sem as colunas do Anexo VIII para classificar"
        elif p.get("orgaoId") == "tce" and "membros" in (p.get("orgao") or ""):  # rubricas fora do Anexo VIII
            tot, sem = classifica(p, tab)
            rem, ind, exc = f"{tot['remuneratorio']:.2f}", f"{tot['indenizatorio']:.2f}", f"{tot['excluida_do_teto']:.2f}"
            if sem:
                sem_classe.update(sem)
                status = "nao_verificado"
                motivo = "rubrica não classificada: " + ", ".join(sorted(set(sem)))[:300] + (f" · {motivo}" if motivo else "")
        elif p.get("orgaoId") == "governo":
            motivo = f"{motivo} · {GOVERNO_SEM_RUBRICAS}"
        exc_val = (p["liquido"] if grupo == "supersalario" else p["bruto"]) - t["valor"]
        link, _obs = fonte_original(p)
        linhas.append({"grupo": grupo, "nome": p.get("nome"), "orgao": unidade(p), "mes": p.get("mes"), "bruto": f"{p['bruto']:.2f}",
                       "liquido": f"{p['liquido']:.2f}", "teto_mes": f"{t['valor']:.2f}", "lei_teto": t["lei"], "excedente": f"{max(0, exc_val):.2f}",
                       "total_remuneratorio": rem, "total_indenizatorio": ind, "total_excluido_do_teto": exc, "abate_teto": abate, "status": status,
                       "motivo": motivo, "conferido_em": hoje, "rotulo": ROTULO.get(p.get("orgaoId"), ""), "link_contracheque_original": link})
        if grupo == "amostra" and status == "confere":
            janela[hash_cc(p)] = hoje[:10]
    for r, n in sem_classe.most_common():
        print(f"  ⚠️ rubrica não classificada em config/rubricas.json: \"{r}\" ({n} contracheque(s))")

    SAIDA_CSV.parent.mkdir(parents=True, exist_ok=True)
    with open(SAIDA_CSV, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUNAS)
        w.writeheader()
        w.writerows(linhas)
    por_grupo = {g: Counter(x["status"] for x in linhas if x["grupo"] == g) for g in ("supersalario", "intermediario", "amostra")}
    por_orgao = defaultdict(Counter)
    for x in linhas:
        por_orgao[x["orgao"]][x["status"]] += 1
    motivos = Counter(x["motivo"].split(":")[0].split(" · ")[0] for x in linhas if x["status"] == "nao_verificado")

    def cp(g):
        c = por_grupo[g]
        n = c["confere"] + c["diverge"]
        return {"conferidos": n, "comErro": c["diverge"], "limiteSuperior95": round(clopper_pearson_sup(c["diverge"], n), 4) if n else None}
    resumo = {"geradoEm": hoje, "metodo": __doc__.split("\n\n")[1].strip() if __doc__ else "",
              "grupos": {g: {**dict(c), "total": sum(c.values())} for g, c in por_grupo.items()},
              "porOrgao": {o: dict(c) for o, c in sorted(por_orgao.items())},
              "naoVerificadoPorMotivo": motivos.most_common(),
              "rubricasNaoClassificadas": sem_classe.most_common(),
              "sinaisAbateTeto": [{"nome": x["nome"], "orgao": x["orgao"], "mes": x["mes"], "texto": "abate-teto aplicado abaixo do excedente",
                                   "detalhe": x["abate_teto"]} for x in linhas if x["abate_teto"].startswith("retenção de")],
              "abateTeto": Counter(x["abate_teto"].split(" de R$")[0] if x["abate_teto"] else "" for x in linhas if x["abate_teto"]).most_common(),
              "clopperPearson": {"amostra": cp("amostra"), "intermediario": cp("intermediario")},
              "teto": vs, "amostraJanela": janela,
              "rotulos": {**ROTULO, "governoRubricas": GOVERNO_SEM_RUBRICAS}}
    SAIDA_JSON.write_text(json.dumps(resumo, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"✅ conferência de Supersalários: " + " · ".join(f"{g} {dict(c)}" for g, c in por_grupo.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
