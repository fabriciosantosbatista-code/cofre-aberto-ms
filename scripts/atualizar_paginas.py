#!/usr/bin/env python3
"""
Cofre Aberto MS — atualiza os números das páginas estáticas a partir dos JSONs

O painel (cofre-aberto-ms.html) lê os JSONs ao vivo, mas a capa (index.html)
e as páginas de SEO (vereadores-campo-grande.html, deputados-estaduais-ms.html,
senadores-ms.html) têm os números escritos no HTML — de propósito, para o
Google indexar texto. Até nov/2026 eles eram editados à mão e ficaram parados
em julho. Este script roda no fim da coleta diária (GitHub Actions) e
reescreve só os trechos de números/tabelas, sem mexer no resto do HTML.
"""

import json, re
from datetime import date
from pathlib import Path

ROOT = Path(__file__).parent.parent
DADOS = ROOT / "dados"
MESES = ["Jan", "Fev", "Mar", "Abr", "Mai", "Jun", "Jul", "Ago", "Set", "Out", "Nov", "Dez"]


def carregar(nome):
    try:
        return json.load(open(DADOS / nome, encoding="utf-8"))
    except Exception:
        return {}


def brl(v):
    s = f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {s}"


def milhar(n):
    return f"{n:,}".replace(",", ".")


def compacto_mi(v):
    return f"R$ {v / 1e6:,.1f}mi".replace(",", "X").replace(".", ",").replace("X", ".") if v < 1e8 \
        else f"R$ {round(v / 1e6):,}mi".replace(",", ".")


def troca(html, padrao, novo, nome, flags=re.S):
    html2, n = re.subn(padrao, novo, html, count=1, flags=flags)
    if not n:
        print(f"  ⚠️ trecho não encontrado: {nome}")
    return html2


def tabela(linhas):
    return "\n".join("      <tr>\n" + "\n".join(f"        {c}" for c in l) + "\n      </tr>" for l in linhas)


def resumo_grid(itens):
    return "\n".join(f'      <div class="resumo-item"><div class="resumo-val">{v}</div>'
                     f'<div class="resumo-label">{r}</div></div>' for v, r in itens)


def main():
    cg = carregar("camara_municipal.json")
    est = carregar("deputados_estaduais_ms.json")
    fed = carregar("deputados_federais_ms.json")
    sen = carregar("senadores_ms.json")
    senbr = carregar("senadores_brasil.json")
    emendas = carregar("emendas_ms.json")
    mags = [carregar(f) for f in ("trt24_magistrados.json", "tre_ms_magistrados.json", "tjms_magistrados.json")]
    status = carregar("status.json")

    vereadores = cg.get("vereadores", [])
    deps_est = est.get("vereadores", [])
    deps_fed = fed.get("deputados", [])
    senadores = sen.get("senadores", [])

    n_cg = sum(v.get("totalNotasFiscais") or len(v.get("despesas") or []) for v in vereadores)
    n_est = sum(len(d.get("despesas") or []) for d in deps_est)
    n_fed = sum(len(d.get("despesas") or []) or (d.get("totalNotasFiscais") or 0) for d in deps_fed)
    n_sen = sum(len(s.get("notasCeaps") or []) for s in senadores)
    n_total = n_cg + n_est + n_fed + n_sen
    ceap_est = (est.get("resumo") or {}).get("totalVerbaIndenizatoriaPaga2026") or \
        sum((d.get("verbaIndenizatoria") or {}).get("gastoPago2026") or 0 for d in deps_est)
    verba_cg = sum((v.get("verbaIndenizatoria") or {}).get("gastoPago2026") or 0 for v in vereadores)
    ativos = sum((m.get("resumo") or {}).get("totalAtivos") or 0 for m in mags)
    mes_fim = MESES[date.today().month - 1]
    periodo = f"Jan–{mes_fim}/{date.today().year}"

    # ---------------- index.html (capa) ----------------
    p = ROOT / "index.html"
    html = p.read_text(encoding="utf-8")

    def stat(html, rotulo, valor_txt, contagem=None):
        attr = f' data-count="{contagem}"' if contagem is not None else ""
        return troca(html,
                     rf'(<(div|span) class="stat-val")[^>]*>[^<]*(</\2>\s*<(?:div|span) class="stat-label">{re.escape(rotulo)}<)',
                     rf'\1{attr}>{valor_txt}\3', f"capa: {rotulo}")

    html = stat(html, "Vereadores CG", len(vereadores), len(vereadores))
    html = stat(html, "Dep. Estaduais", len(deps_est), len(deps_est))
    html = stat(html, "Senadores MS", len(senadores), len(senadores))
    html = stat(html, "Notas fiscais", milhar(n_total), n_total)
    if ativos:
        html = stat(html, "Magistrados MS", ativos, ativos)
    if ceap_est:
        html = stat(html, "CEAP Estadual 2026", compacto_mi(ceap_est))
    if emendas.get("totalGeralPago"):
        html = stat(html, "Emendas Parlamentares MS 2026", compacto_mi(emendas["totalGeralPago"]))
    html = re.sub(r"\d{1,3}(?:\.\d{3})* notas fiscais reais", f"{milhar(n_total)} notas fiscais reais", html)
    html = re.sub(r"<p>\d{1,3}(?:\.\d{3})* notas fiscais com fornecedor", f"<p>{milhar(n_total)} notas fiscais com fornecedor", html)
    html = re.sub(r"(pessoal dos gabinetes, )\d{1,3}(?:\.\d{3})*( notas fiscais)", rf"\g<1>{milhar(n_cg)}\2", html)
    html = re.sub(r"CEAP Jan–\w{3}/\d{4}, \d{1,3}(?:\.\d{3})*( notas fiscais)", f"CEAP {periodo}, {milhar(n_est)}\\1", html)
    html = re.sub(r"(CEAPS \d{4} com )\d{1,3}(?:\.\d{3})*( notas fiscais)", rf"\g<1>{milhar(n_sen)}\2", html)
    html = re.sub(r"(CEAP \d{4} com )\d{1,3}(?:\.\d{3})*( notas fiscais, fotos)", rf"\g<1>{milhar(n_fed)}\2", html)
    html = re.sub(r'(<div class="aba-num">)\d+(</div>\s*<div class="aba-title">Dep\. Estaduais)', rf"\g<1>{len(deps_est)}\2", html)
    if ativos:
        html = re.sub(r'(<div class="aba-num">)\d+(</div>\s*<div class="aba-title">Judiciário MS)', rf"\g<1>{ativos}\2", html)
    cx = carregar("conexoes_fornecedores.json").get("totalEmpresas")
    if cx:
        html = re.sub(r'(<div class="aba-num">)\d+(</div>\s*<div class="aba-title">Conexões entre fornecedores)', rf"\g<1>{cx}\2", html)
    nf = len(carregar("feeds/index.json").get("parlamentares") or [])
    if nf:
        html = re.sub(r'(<div class="aba-num">)\d+(</div>\s*<div class="aba-title">Siga um político)', rf"\g<1>{nf}\2", html)
    if status.get("ultimaAtualizacao"):
        a, m, d = status["ultimaAtualizacao"][:10].split("-")
        html = re.sub(r'(<time id="data-atualizacao">)[^<]*(</time>)', rf"\g<1>{d}/{m}/{a}\2", html)
    p.write_text(html, encoding="utf-8")
    print(f"✅ index.html — {milhar(n_total)} notas, {len(deps_est)} dep. estaduais, {ativos} magistrados")

    # ---------------- vereadores-campo-grande.html ----------------
    p = ROOT / "vereadores-campo-grande.html"
    if p.exists() and vereadores:
        html = p.read_text(encoding="utf-8")
        subsidio = (vereadores[0].get("salarioBase") or 26080.98)
        html = troca(html, r'(<div class="resumo-grid">\n).*?(\n    </div>)',
                     r"\g<1>" + resumo_grid([
                         (len(vereadores), "Vereadores"),
                         (brl(verba_cg), "Verba indenizatória paga em 2026"),
                         (milhar(n_cg), "Notas fiscais coletadas"),
                         (brl(subsidio), "Subsídio mensal por vereador"),
                     ]).replace("\\", "\\\\") + r"\2", "vereadores: resumo")
        linhas = []
        for v in sorted(vereadores, key=lambda v: -((v.get("verbaIndenizatoria") or {}).get("gastoPago2026") or 0)):
            vi = v.get("verbaIndenizatoria") or {}
            pago = vi.get("gastoPago2026") or 0
            cota = vi.get("cotaAnual2026") or 300000
            linhas.append([f'<td class="nome">{v["nome"]}</td>', f"<td>{v.get('partido') or '—'}</td>",
                           f'<td class="num">{brl(pago)}</td>', f'<td class="num">{pago / cota * 100:.1f}%</td>',
                           f'<td class="num">{v.get("totalNotasFiscais") or 0}</td>'])
        html = troca(html, r"(<tbody>\n).*?(\n      </tbody>)", r"\g<1>" + tabela(linhas).replace("\\", "\\\\") + r"\2", "vereadores: tabela")
        p.write_text(html, encoding="utf-8")
        print("✅ vereadores-campo-grande.html")

    # ---------------- deputados-estaduais-ms.html ----------------
    p = ROOT / "deputados-estaduais-ms.html"
    if p.exists() and deps_est:
        html = p.read_text(encoding="utf-8")
        html = re.sub(r"\b\d+ deputados estaduais", f"{len(deps_est)} deputados estaduais", html)
        html = re.sub(r"Jan–\w{3}/\d{4}", periodo, html)
        html = re.sub(r"período de Jan a \w{3}/\d{4}", f"período de Jan a {mes_fim}/{date.today().year}", html)
        subsidio = next((d.get("salarioBase") for d in deps_est if d.get("salarioBase")), 34774.64)
        html = troca(html, r'(<div class="resumo-grid">\n).*?(\n    </div>)',
                     r"\g<1>" + resumo_grid([
                         (len(deps_est), "Deputados estaduais"),
                         (brl(ceap_est), f"CEAP paga em {periodo}"),
                         (milhar(n_est), "Notas fiscais coletadas"),
                         (brl(subsidio), "Subsídio mensal por deputado"),
                     ]).replace("\\", "\\\\") + r"\2", "dep. estaduais: resumo")
        linhas = [[f'<td class="nome">{d["nome"]}</td>', f"<td>{d.get('partido') or '—'}</td>",
                   f'<td class="num">{len(d.get("despesas") or [])}</td>']
                  for d in sorted(deps_est, key=lambda d: -len(d.get("despesas") or []))]
        html = troca(html, r"(<tbody>\n).*?(\n      </tbody>)", r"\g<1>" + tabela(linhas).replace("\\", "\\\\") + r"\2", "dep. estaduais: tabela")
        p.write_text(html, encoding="utf-8")
        print("✅ deputados-estaduais-ms.html")

    # ---------------- senadores-ms.html ----------------
    p = ROOT / "senadores-ms.html"
    if p.exists() and senadores:
        html = p.read_text(encoding="utf-8")
        html = troca(html, r'(<div class="resumo-grid">\n).*?(\n    </div>)',
                     r"\g<1>" + resumo_grid([
                         (len(senadores), "Senadores de MS"),
                         (len(senbr.get("senadores") or []) or 81, "Senadores no Brasil"),
                         (brl(sum(s.get("cotaGastaAno") or 0 for s in senadores)), "CEAPS gasta em 2026 (MS)"),
                         (milhar(n_sen), "Notas fiscais coletadas"),
                     ]).replace("\\", "\\\\") + r"\2", "senadores: resumo")
        linhas = [[f'<td class="nome">{s["nome"]}</td>', f"<td>{s.get('partido') or '—'}</td>",
                   f'<td class="num">{brl(s.get("cotaGastaAno") or 0)}</td>',
                   f'<td class="num">{len(s.get("notasCeaps") or [])}</td>']
                  for s in sorted(senadores, key=lambda s: -(s.get("cotaGastaAno") or 0))]
        html = troca(html, r"(<tbody>\n).*?(\n      </tbody>)", r"\g<1>" + tabela(linhas).replace("\\", "\\\\") + r"\2", "senadores: tabela")
        p.write_text(html, encoding="utf-8")
        print("✅ senadores-ms.html")


if __name__ == "__main__":
    main()
