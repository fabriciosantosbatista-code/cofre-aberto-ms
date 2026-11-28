#!/usr/bin/env python3
"""
Cofre Aberto MS — publica na página de Metodologia (metodologia.html#mudancas-regras) a tabela de mudanças de regra do ICP

Fonte única: a seção "3.0 Mudanças de aplicação" do ICP_DOCUMENTACAO.md (pedido de 28/11/2026). Cada linha da tabela
vira uma linha na página: data, a mudança (o título em negrito, em linguagem simples) e o detalhe com o motivo, que abre
ao clicar. O texto da página é gerado entre os marcadores <!--MUDANCAS--> e <!--/MUDANCAS-->; nada mais da página muda.
Uso: python3 scripts/gerar_mudancas_metodologia.py   (roda na coleta; código 1 se a seção não for encontrada)
"""
import html, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOC, PAGINA = ROOT / "ICP_DOCUMENTACAO.md", ROOT / "metodologia.html"
INI, FIM = "<!--MUDANCAS-->", "<!--/MUDANCAS-->"


def linhas_da_secao(md):
    m = re.search(r"^### 3\.0 [^\n]*\n(.*?)(?=^#{2,3} )", md, re.S | re.M)
    if not m:
        return []
    out = []
    for ln in m.group(1).splitlines():
        c = re.match(r"^\|\s*(\d{2}/\d{2}/\d{4})\s*\|\s*(.*)\|\s*$", ln)
        if c:
            out.append((c.group(1), c.group(2).strip()))
    return out


def md_inline(t):
    """Markdown de uma célula → HTML simples (negrito, código, itálico); o resto é escapado."""
    t = html.escape(t, quote=False)
    t = re.sub(r"`([^`]+)`", r"<code>\1</code>", t)
    t = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", t)
    return re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<em>\1</em>", t)


def titulo_e_detalhe(celula):
    """O título é o trecho em negrito do começo da célula ("**Emendas — ...:**"); sem ele, a primeira frase.
    Tudo a partir de "**Detalhe técnico:**" fica só na documentação: não vai para a página."""
    celula = re.split(r"\s*\*\*Detalhe técnico:?\*\*", celula, maxsplit=1)[0].strip()
    m = re.match(r"^\*\*(.+?):?\*\*:?\s*(.*)$", celula, re.S)
    if m:
        det = m.group(2)
        return m.group(1).rstrip(":."), det[:1].upper() + det[1:]
    frase = re.split(r"(?<=[.!?])\s", celula, maxsplit=1)
    return frase[0], (frase[1] if len(frase) > 1 else "")


def partes(h):
    """"O que mudou", "Por quê" e "Para quem lê o site" em parágrafos separados."""
    return re.sub(r"\s*(<strong>(?:Por quê|Para quem lê o site):</strong>)", r"<br><br>\1", h)


def montar(linhas):
    corpo = "".join(
        f"<tr><td style='white-space:nowrap'>{d}</td><td><details><summary>{md_inline(t)}</summary>"
        f"<div style='margin-top:6px;font-size:.88rem;line-height:1.6'>{partes(md_inline(det)) or '—'}</div></details></td></tr>"
        for d, (t, det) in ((d, titulo_e_detalhe(c)) for d, c in linhas))
    return (f"{INI}\n<h2 id=\"mudancas-regras\">Mudanças nas regras de conferência</h2>\n"
            "<p>Quando mudamos a forma de conferir os dados na fonte oficial ou de calcular o índice de confiabilidade (ICP), a mudança "
            "fica registrada aqui, com a data e o motivo. Os pesos e a fórmula do índice não mudam nessas alterações. Clique em cada "
            "linha para ver o detalhe.</p>\n<div class=\"tabela-wrap\" style=\"overflow-x:hidden\"><table style=\"width:100%;table-layout:fixed\"><colgroup><col style=\"width:7.5em\"><col></colgroup>\n<thead><tr><th>Desde</th><th>O que mudou (clique para ver o "
            f"motivo)</th></tr></thead>\n<tbody>{corpo}</tbody></table></div>\n"
            "<p style=\"font-size:.82rem\">Gerado automaticamente a partir da documentação do ICP (seção 3.0).</p>\n" + FIM)


def main():
    linhas = linhas_da_secao(DOC.read_text(encoding="utf-8"))
    if not linhas:
        print("❌ seção 3.0 (mudanças de aplicação) não encontrada em ICP_DOCUMENTACAO.md")
        return 1
    pag = PAGINA.read_text(encoding="utf-8")
    bloco = montar(linhas)
    if INI in pag:
        novo = re.sub(re.escape(INI) + r".*?" + re.escape(FIM), lambda _: bloco, pag, flags=re.S)
    else:  # 1ª vez: logo antes de "Correções e direito de resposta"
        novo = pag.replace('<h2 id="correcoes">', bloco + '\n\n<h2 id="correcoes">', 1)
    if novo != pag:
        PAGINA.write_text(novo, encoding="utf-8")
    print(f"✅ metodologia.html — {len(linhas)} mudanças de regra publicadas")
    return 0


if __name__ == "__main__":
    sys.exit(main())
