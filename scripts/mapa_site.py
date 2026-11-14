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
    ("Executivo", "#199e70", [("Governo MS", P + "governo-ms"), ("Prefeitura CG", P + "prefeitura"), ("Contratos CG", P + "contratos-cg")]),
    ("Emendas", "#d95926", [("Emendas Parlamentares", P + "emendas"), ("Emendas Municípios", "/municipio/")]),
    ("Justiça e salários", "#9085e9", [("Judiciário MS", P + "judiciario"), ("Supersalários", P + "supersalarios")]),
    ("Fiscalização", "#c98500", [("Auditoria", P + "auditoria"), ("Conexões", P + "conexoes"), ("Presença e votação", P + "votacoes"),
                                 ("Eleições e patrimônio", P + "eleicoes"), ("Evolução", P + "evolucao"), ("Termômetro", "/termometro-da-transparencia/")]),
    ("Brasil", "#2bb3a3", [("Presidência", P + "presidencia"), ("Senado Brasil", P + "senado-brasil"), ("Dep. Federais Brasil", P + "deputados-brasil"),
                           ("STF", P + "stf")]),
    ("Publicações", "#e0679f", [("Boletim semanal", "/boletim/"), ("Empresas", "/empresa/"), ("Órgãos", "/orgao/"), ("Perguntas frequentes", "/perguntas/")]),
    ("Sobre o projeto", "#7aa2c8", [("Início", "/"), ("Painel", "/cofre-aberto-ms.html"), ("Sobre", P + "sobre"), ("Metodologia e dados", "/metodologia.html"),
                                    ("Imprensa", "/press.html"), ("Apoie", "/apoie/"),
                                    ("Contato", "CONTATO")]),
]

CSS = (".mapa-site{width:100%;box-sizing:border-box;display:grid;grid-template-columns:repeat(auto-fill,minmax(90px,1fr));align-items:start;gap:12px 14px;border-top:1px solid var(--border,#2a2a2a);"
       "padding:16px 0 4px;margin-top:24px;font-size:.7rem;line-height:1.45}"
       ".mapa-site h4{margin:0 0 4px;font-size:.62rem;letter-spacing:.06em;text-transform:uppercase;color:var(--cor);font-weight:700}"
       ".mapa-site ul{list-style:none;margin:0;padding:0}.mapa-site li{margin:1px 0}"
       ".mapa-site a{color:var(--ink-caption,#888);text-decoration:none}.mapa-site a:hover{color:var(--cor);text-decoration:underline}"
       "@media(max-width:520px){.mapa-site{grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;font-size:.66rem}}"
       ".mapa-site details,.mapa-site summary{font:inherit;margin:0;padding:0;border:0;background:none}"
       ".mapa-contato summary{cursor:pointer;color:var(--ink-caption,#888);list-style:none}.mapa-contato summary::-webkit-details-marker{display:none}"
       ".mapa-contato summary::after{content:\" ▾\";font-size:.8em}.mapa-contato[open] summary::after{content:\" ▴\"}.mapa-contato summary:hover{color:var(--cor)}"
       ".mapa-contato a{display:block;margin-top:3px;color:#25D366!important;overflow-wrap:anywhere}")

def item(n, u):
    if u == "CONTATO":  # só "Contato"; ao abrir, mostra o WhatsApp
        return (f'<li><details class="mapa-contato"><summary>{n}</summary>'
                f'<a href="{WHATS}" target="_blank" rel="noopener">💬 WhatsApp: (67) 98209-5384</a></details></li>')
    return f'<li><a href="{u}">{n}</a></li>'


MAPA_HTML = (f'<style>{CSS}</style><nav class="mapa-site" aria-label="Mapa do site">'
             + "".join(f'<div style="--cor:{cor}"><h4>{g}</h4><ul>' + "".join(item(n, u) for n, u in itens) + "</ul></div>"
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
