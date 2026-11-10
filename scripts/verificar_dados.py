#!/usr/bin/env python3
"""
Cofre Aberto MS — verificação de saúde dos dados (roda ao fim de cada coleta)

Por que existe: os coletores, quando uma fonte falha, mantêm o dado anterior
em silêncio e o GitHub Actions mostra "sucesso". Assim o TJMS ficou parado de
julho a novembro/2026, o CEAP federal ficou vazio de agosto a novembro e a
Prefeitura ficou presa em maio — sem ninguém perceber.

Este script olha o CONTEÚDO dos JSONs (data da nota/empenho mais recente,
mês de referência, contagens, quedas bruscas em relação à versão anterior
do arquivo no git) e gera um relatório em Markdown.

  ❌ ERRO  — fonte principal parada ou dado quebrado: o job falha (e-mail do GitHub)
  ⚠️ AVISO — fonte secundária desatualizada (ex.: câmara do interior fora do ar)

Uso:  python3 scripts/verificar_dados.py [--relatorio arquivo.md]
Saída: código 1 se houver algum ERRO, 0 caso contrário.
"""

import json, subprocess, sys
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).parent.parent
DADOS = ROOT / "dados"
HOJE = date.today()
MESES = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]

erros, avisos, ok = [], [], []


def carregar(nome):
    try:
        return json.load(open(DADOS / nome, encoding="utf-8"))
    except Exception as e:
        erros.append(f"`{nome}`: não abre como JSON ({e})")
        return None


def versao_anterior(nome):
    """Conteúdo da versão anterior do arquivo no git (para detectar quedas bruscas)."""
    try:
        hashes = subprocess.check_output(["git", "log", "-n", "2", "--format=%H", "--", f"dados/{nome}"],
                                         cwd=ROOT, text=True, stderr=subprocess.DEVNULL).split()
        if len(hashes) < 2:
            return None
        return json.loads(subprocess.check_output(["git", "show", f"{hashes[1]}:dados/{nome}"],
                                                  cwd=ROOT, stderr=subprocess.DEVNULL))
    except Exception:
        return None


def dias_desde(txt):
    if not txt:
        return None
    try:
        return (HOJE - datetime.fromisoformat(str(txt)[:10]).date()).days
    except ValueError:
        return None


def checa(condicao_ok, msg_ok, msg_falha, nivel="erro"):
    if condicao_ok:
        ok.append(msg_ok)
    else:
        (erros if nivel == "erro" else avisos).append(msg_falha)


def recente(nome_fonte, data_txt, max_dias, nivel="erro", o_que="dado mais recente"):
    d = dias_desde(data_txt)
    checa(d is not None and d <= max_dias,
          f"{nome_fonte}: {o_que} de {data_txt} ({d} dias)",
          f"**{nome_fonte}**: {o_que} é de {data_txt or 'data desconhecida'}"
          + (f" ({d} dias, limite {max_dias})" if d is not None else "") + " — a fonte pode ter parado",
          nivel)


def queda(nome_fonte, atual, anterior, tolerancia=0.10, nivel="erro"):
    if anterior and atual < anterior * (1 - tolerancia):
        (erros if nivel == "erro" else avisos).append(
            f"**{nome_fonte}**: caiu de {anterior:,} para {atual:,} em relação à coleta anterior".replace(",", "."))


def mes_ref_ord(txt):
    try:
        m, a = str(txt).split("/")
        return int(a) * 12 + int(m)
    except Exception:
        return None


def main():
    # ---------- arquivo de status (a coleta rodou?) ----------
    st = carregar("status.json") or {}
    recente("Coleta diária (status.json)", st.get("ultimaAtualizacao"), 2, o_que="última coleta")

    # ---------- Câmara CG ----------
    cg = carregar("camara_municipal.json")
    if cg:
        v = cg.get("vereadores", [])
        checa(len(v) == 29, "Câmara CG: 29 vereadores", f"**Câmara CG**: {len(v)} vereadores (esperado 29)")
        ult = -1
        for x in v:
            vi = x.get("verbaIndenizatoria") or {}
            for m in list((vi.get("mesesAto027") or {})) + list((vi.get("mesesAto028") or {})):
                if m in MESES:
                    ult = max(ult, MESES.index(m))
        if ult >= 0:
            ano = int(str(cg.get("ultimaAtualizacao", HOJE.year))[:4])
            atraso = (HOJE.year * 12 + HOJE.month) - (ano * 12 + ult + 1)
            # a Câmara publica a verba com ~1–2 meses de atraso
            checa(atraso <= 3, f"Câmara CG: verba até {MESES[ult]}/{ano}",
                  f"**Câmara CG**: verba indenizatória só até {MESES[ult]}/{ano} ({atraso} meses) — "
                  "veja o log do job coletar_verba_camara (timeouts nos PDFs?)")
        notas = sum(x.get("totalNotasFiscais") or 0 for x in v)
        ant = versao_anterior("camara_municipal.json")
        queda("Câmara CG — notas fiscais", notas,
              sum(x.get("totalNotasFiscais") or 0 for x in (ant or {}).get("vereadores", [])) if ant else None)
        soma = round(sum((x.get("verbaIndenizatoria") or {}).get("gastoPago2026") or 0 for x in v), 2)
        resumo = (cg.get("resumo") or {}).get("totalVerbaIndenizatoriaPaga2026")
        checa(resumo is None or abs((resumo or 0) - soma) < 1, "Câmara CG: total do resumo bate com os vereadores",
              f"**Câmara CG**: resumo (R$ {resumo:,.2f}) diferente da soma dos vereadores (R$ {soma:,.2f})")
        ref = cg.get("referenciaPessoal")
        if ref:
            mes_nome, ano_p = ref.split("/")
            meses_nome = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho",
                          "agosto", "setembro", "outubro", "novembro", "dezembro"]
            if mes_nome in meses_nome:
                atraso = (HOJE.year * 12 + HOJE.month) - (int(ano_p) * 12 + meses_nome.index(mes_nome) + 1)
                checa(atraso <= 2, f"Câmara CG: pessoal dos gabinetes de {ref}",
                      f"**Câmara CG**: folha de pessoal dos gabinetes ainda é de {ref}", "aviso")

    # ---------- Deputados estaduais ----------
    est = carregar("deputados_estaduais_ms.json")
    if est:
        d = est.get("vereadores", [])
        checa(24 <= len(d) <= 26, f"Dep. estaduais: {len(d)} deputados", f"**Dep. estaduais**: {len(d)} deputados (esperado 24–26)")
        datas = [n.get("data") for x in d for n in (x.get("despesas") or []) if n.get("data")]
        recente("Dep. estaduais (ALEMS)", max(datas) if datas else None, 30, o_que="nota fiscal mais recente")
        sem_foto = [x["nome"] for x in d if not x.get("foto")]
        checa(not sem_foto, "Dep. estaduais: todos com foto", f"**Dep. estaduais** sem foto: {', '.join(sem_foto)}", "aviso")
        ant = versao_anterior("deputados_estaduais_ms.json")
        queda("Dep. estaduais — notas fiscais", len(datas),
              sum(len(x.get("despesas") or []) for x in (ant or {}).get("vereadores", [])) if ant else None)

    # ---------- Deputados federais MS / Brasil ----------
    fed = carregar("deputados_federais_ms.json")
    if fed:
        d = fed.get("deputados", [])
        checa(len(d) == 8, "Dep. federais MS: 8 deputados", f"**Dep. federais MS**: {len(d)} deputados (esperado 8)")
        checa(all(x.get("cotaGastaAno") is not None for x in d), "Dep. federais MS: CEAP de todos",
              "**Dep. federais MS**: deputado(s) sem CEAP (cotaGastaAno vazio) — fonte da Câmara falhou?")
        datas = [n.get("data") for x in d for n in (x.get("despesas") or []) if n.get("data")]
        recente("Dep. federais MS (CEAP)", max(datas) if datas else None, 30, o_que="nota fiscal mais recente")
    br = carregar("deputados_federais_brasil.json")
    if br:
        d = br.get("deputados", [])
        checa(505 <= len(d) <= 520, f"Dep. federais Brasil: {len(d)}", f"**Dep. federais Brasil**: {len(d)} deputados (esperado ~513)")
        sem = sum(1 for x in d if x.get("cotaGastaAno") is None)
        checa(sem <= len(d) * 0.05, f"Dep. federais Brasil: {len(d) - sem} com CEAP",
              f"**Dep. federais Brasil**: {sem} de {len(d)} sem CEAP — fonte da Câmara falhou?")

    # ---------- Senadores ----------
    sen = carregar("senadores_ms.json")
    if sen:
        s = sen.get("senadores", [])
        checa(len(s) == 3, "Senadores MS: 3", f"**Senadores MS**: {len(s)} (esperado 3)")
        datas = [n.get("data") for x in s for n in (x.get("notasCeaps") or []) if n.get("data")]
        recente("Senadores MS (CEAPS)", max(datas) if datas else None, 45, o_que="nota fiscal mais recente")
    sbr = carregar("senadores_brasil.json")
    if sbr:
        n = len(sbr.get("senadores", []))
        checa(78 <= n <= 81, f"Senado Brasil: {n}", f"**Senado Brasil**: {n} senadores (esperado 81)")

    # ---------- Prefeitura ----------
    pref = carregar("prefeitura.json")
    if pref:
        recente("Prefeitura CG", pref.get("ultimoEmpenho") or max((x.get("data") or "" for x in pref.get("despesas", [])), default=None),
                45, o_que="empenho mais recente")
        ant = versao_anterior("prefeitura.json")
        if ant and (ant.get("totalDespesas") or 0) > (pref.get("totalDespesas") or 0) * 1.02:
            erros.append(f"**Prefeitura CG**: total pago caiu de R$ {ant['totalDespesas']:,.2f} para "
                         f"R$ {pref.get('totalDespesas', 0):,.2f} — voltou a ler um arquivo antigo?")

    # ---------- Judiciário ----------
    ativos = 0
    for arq, nome in (("trt24_magistrados.json", "TRT24"), ("tre_ms_magistrados.json", "TRE-MS"), ("tjms_magistrados.json", "TJMS")):
        j = carregar(arq)
        if not j:
            continue
        ativos += (j.get("resumo") or {}).get("totalAtivos") or 0
        ref = mes_ref_ord(j.get("mesReferencia"))
        atraso = (HOJE.year * 12 + HOJE.month) - ref if ref else None
        # tribunais publicam a folha com ~1–2 meses de atraso
        checa(atraso is not None and atraso <= 3, f"{nome}: folha de {j.get('mesReferencia')}",
              f"**{nome}**: folha mais recente é de {j.get('mesReferencia')} ({atraso} meses)")
    checa(ativos >= 320, f"Judiciário: {ativos} magistrados ativos", f"**Judiciário**: só {ativos} magistrados ativos (esperado ~348)")

    # ---------- Câmaras do interior (aviso) ----------
    for f in sorted((DADOS / "camaras").glob("*.json")):
        j = carregar(f"camaras/{f.name}")
        if j:
            recente(f"Câmara de {j.get('cidade', f.stem)}", j.get("ultimaAtualizacao"), 7, nivel="aviso", o_que="última coleta")

    # ---------- análises derivadas (gerar_analises.py) ----------
    cx = carregar("conexoes_fornecedores.json")
    if cx:
        recente("Conexões entre fornecedores", cx.get("ultimaAtualizacao"), 2, o_que="última geração")
        checa(cx.get("totalEmpresas", 0) >= 100, f"Conexões: {cx.get('totalEmpresas')} empresas",
              f"**Conexões entre fornecedores**: só {cx.get('totalEmpresas')} empresas — notas faltando?", "aviso")
    ev = carregar("evolucao_mensal.json")
    if ev:
        recente("Evolução mensal", ev.get("ultimaAtualizacao"), 2, o_que="última geração")
        faltando = [g for g in ("vereador", "estadual", "federal", "senador") if not (ev.get("grupos") or {}).get(g)]
        checa(not faltando, "Evolução: 4 grupos", f"**Evolução mensal**: grupos sem dados: {', '.join(faltando)}")
    fi = carregar("feeds/index.json")
    if fi:
        n = len(fi.get("parlamentares", []))
        checa(n >= 60, f"Feeds RSS: {n} parlamentares", f"**Feeds RSS**: só {n} parlamentares")

    # ---------- páginas próprias dos parlamentares ----------
    paginas = list(ROOT.glob("vereador/*/index.html")) + list(ROOT.glob("deputado-estadual/*/index.html")) + \
              list(ROOT.glob("deputado-federal/*/index.html")) + list(ROOT.glob("senador/*/index.html"))
    checa(len(paginas) >= 600, f"Páginas de parlamentares: {len(paginas)}",
          f"**Páginas de parlamentares**: só {len(paginas)} (esperado ~648)")
    smap = (ROOT / "sitemap.xml").read_text(encoding="utf-8") if (ROOT / "sitemap.xml").exists() else ""
    checa(smap.count("<url>") >= 600, f"sitemap.xml: {smap.count('<url>')} endereços",
          f"**sitemap.xml**: só {smap.count('<url>')} endereços", "aviso")

    # ---------- arquivos de notas por estado ----------
    for pasta, nome in (("ceap_federal", "Notas dep. federais por UF"), ("ceaps_senado", "Notas senadores por UF")):
        arqs = list((DADOS / pasta).glob("*.json"))
        checa(len(arqs) >= 26, f"{nome}: {len(arqs)} estados", f"**{nome}**: só {len(arqs)} arquivos de estado", "aviso")


def relatorio():
    linhas = [f"# Saúde dos dados — {HOJE.strftime('%d/%m/%Y')}", ""]
    if erros:
        linhas += ["## ❌ Erros (fonte principal parada ou dado quebrado)", ""] + [f"- {e}" for e in erros] + [""]
    if avisos:
        linhas += ["## ⚠️ Avisos", ""] + [f"- {a}" for a in avisos] + [""]
    linhas += [f"<details><summary>✅ {len(ok)} verificações OK</summary>", ""] + [f"- {o}" for o in ok] + ["", "</details>", ""]
    linhas += ["_Gerado por `scripts/verificar_dados.py` ao fim da coleta diária._"]
    return "\n".join(linhas)


if __name__ == "__main__":
    main()
    texto = relatorio()
    if "--relatorio" in sys.argv:
        Path(sys.argv[sys.argv.index("--relatorio") + 1]).write_text(texto, encoding="utf-8")
    print(texto)
    print(f"\nResultado: {len(erros)} erro(s), {len(avisos)} aviso(s), {len(ok)} OK")
    sys.exit(1 if erros else 0)
