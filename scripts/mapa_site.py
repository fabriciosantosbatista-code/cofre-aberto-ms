#!/usr/bin/env python3
"""Cofre Aberto MS — "mapa do site" do rodapé, com os mesmos grupos e cores do menu do painel.

Fonte única: as páginas geradas usam MAPA_HTML no RODAPE; index.html e cofre-aberto-ms.html recebem o mesmo bloco
entre <!--MAPA--> e <!--/MAPA--> (injetar()).
"""
import re
from pathlib import Path

P = "/cofre-aberto-ms.html#aba="
WHATS = "https://wa.me/5567982095384?text=Ol%C3%A1!%20Vim%20pelo%20Cofre%20Aberto%20MS%20e%20gostaria%20de%20saber%20mais."
GRUPOS = [
    ("Parlamentares", "#3987e5", [("Senado MS", P + "senadores"), ("Dep. Federais MS", P + "deputados"), ("Dep. Estaduais MS", P + "deputados-estaduais"),
                                  ("Câmara CG", P + "camara"), ("Câmaras MS", P + "camaras-ms")]),
    ("Executivo", "#199e70", [("Governo MS", P + "governo-ms"), ("Prefeitura CG", P + "prefeitura"), ("Contratos CG", P + "contratos-cg"),
                              ("Governo MS em números", "/governo-ms/"), ("Prefeitura CG em números", "/prefeitura-campo-grande/")]),
    ("Emendas", "#d95926", [("Emendas Parlamentares", P + "emendas"), ("Emendas Municípios", "/municipio/"), ("Emendas de MS em números", "/emendas-parlamentares-ms/")]),
    ("Justiça e salários", "#9085e9", [("Judiciário MS", P + "judiciario"), ("Supersalários", P + "supersalarios"), ("Supersalários em MS", "/supersalarios-ms/"),
                                       ("Salário dos ministros do STF", "/salario-ministros-stf/")]),
    ("Fiscalização", "#c98500", [("Auditoria", P + "auditoria"), ("Conexões", P + "conexoes"), ("Presença e votação", P + "votacoes"),
                                 ("Eleições e patrimônio", P + "eleicoes"), ("Evolução", P + "evolucao"), ("Termômetro da transparência", "/termometro-da-transparencia/")]),
    ("Brasil", "#2bb3a3", [("Presidência", P + "presidencia"), ("Senado Brasil", P + "senado-brasil"), ("Dep. Federais Brasil", P + "deputados-brasil"),
                           ("STF", P + "stf"), ("Cartão corporativo", "/cartao-corporativo-presidente/")]),
    ("Publicações", "#e0679f", [("Boletim semanal", "/boletim/"), ("Empresas", "/empresa/"), ("Órgãos", "/orgao/"), ("Perguntas frequentes", "/perguntas/")]),
    ("Sobre o projeto", "#7aa2c8", [("Início", "/"), ("Painel", "/cofre-aberto-ms.html"), ("Sobre", P + "sobre"), ("Metodologia e dados", "/metodologia.html"),
                                    ("Imprensa", "/press.html"), ("Apoie", "/apoie/"),
                                    ("💬 WhatsApp: (67) 98209-5384", WHATS)]),
]

CSS = (".mapa-site{display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:18px 22px;border-top:1px solid var(--border,#2a2a2a);"
       "padding:24px 0 8px;margin-top:28px;font-size:.8rem;line-height:1.5}"
       ".mapa-site h4{margin:0 0 6px;font-size:.72rem;letter-spacing:.06em;text-transform:uppercase;color:var(--cor);font-weight:700}"
       ".mapa-site ul{list-style:none;margin:0;padding:0}.mapa-site li{margin:2px 0}"
       ".mapa-site a{color:var(--ink-soft,#aaa);text-decoration:none}.mapa-site a:hover{color:var(--cor);text-decoration:underline}")

MAPA_HTML = (f'<style>{CSS}</style><nav class="mapa-site" aria-label="Mapa do site">'
             + "".join(f'<div style="--cor:{cor}"><h4>{g}</h4><ul>' + "".join((f'<li><a href="{u}" target="_blank" rel="noopener">{n}</a></li>' if u.startswith("http") else f'<li><a href="{u}">{n}</a></li>') for n, u in itens) + "</ul></div>"
                       for g, cor, itens in GRUPOS)
             + "</nav>")


def injetar(caminho):
    """Coloca (ou atualiza) o mapa antes do primeiro <footer da página."""
    p = Path(caminho)
    h = p.read_text(encoding="utf-8")
    bloco = f"<!--MAPA-->{MAPA_HTML}<!--/MAPA-->\n  "
    if "<!--MAPA-->" in h:
        novo = re.sub(r"<!--MAPA-->.*?<!--/MAPA-->\n  ", lambda m: bloco, h, count=1, flags=re.S)
    else:
        i = h.index("<footer")
        novo = h[:i] + bloco + h[i:]
    if novo != h:
        p.write_text(novo, encoding="utf-8")
        return True
    return False


if __name__ == "__main__":
    raiz = Path(__file__).parent.parent
    for f in ("index.html", "cofre-aberto-ms.html"):
        print(f, "atualizado" if injetar(raiz / f) else "sem mudança")
