#!/usr/bin/env python3
"""
Diagnóstico da leitura dos PDFs de verba indenizatória da Câmara de CG.

Para cada vereador/ato pedido, baixa o PDF e imprime, página a página, o que
o leitor reconhece: mês/ano, tipo de página (resumo / combustível / notas) e
se achou o TOTAL — para descobrir por que um mês não entra no site (PDF sem o
mês vs. falha de leitura). Só lê; não altera nenhum dado.

Uso: python3 scripts/diagnostico_pdf_cg.py "CARLÃO:027" "FLÁVIO CABO ALMI:028"
"""
import re, sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import requests
import coletar_verba_camara_cg as cg
from pypdf import PdfReader


def norm(t):
    return cg.normaliza_nome(t)


def main(alvos_txt):
    s = requests.Session()
    s.headers.update({"User-Agent": cg.HEADERS_AJAX["User-Agent"]})
    lista = None
    for tentativa in range(4):
        try:
            lista = cg.obter_lista_relatorios(s)
            break
        except Exception as e:
            print(f"lista: tentativa {tentativa + 1} falhou: {e}")
    if not lista:
        sys.exit("não foi possível obter a lista de relatórios")
    for alvo_txt in alvos_txt:
        nome, ato = alvo_txt.rsplit(":", 1)
        item = next((x for x in lista[f"ato{ato}"] if norm(x["nome"]) == norm(nome)), None)
        print(f"\n{'=' * 70}\n{nome} — Ato {ato}")
        if not item:
            print("  não encontrado na lista; nomes disponíveis:", [x["nome"] for x in lista[f"ato{ato}"]][:40])
            continue
        r1 = s.post(f"{cg.BASE_URL}/HomeDocumentosPublicados.aspx/SalvarCodigoLinhaRelatorio",
                    json={"strCodigoLinhaRelatorio": item["codigoLinhaPDF"], "strChaveAcesso": item["chaveAcesso"]},
                    headers=cg.HEADERS_AJAX, timeout=90)
        r2 = s.get(f"{cg.BASE_URL}/MostrarPDF.aspx", timeout=180)
        print(f"  PDF: HTTP {r1.status_code}/{r2.status_code}, {len(r2.content) // 1024} KB, {r2.headers.get('Content-Type')}")
        with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
            f.write(r2.content); f.flush()
            reader = PdfReader(f.name)
            print(f"  {len(reader.pages)} páginas")
            mes_atual = None
            despejos = 0
            for i, pg in enumerate(reader.pages, 1):
                try:
                    bruto = pg.extract_text() or ""
                except Exception as e:
                    print(f"  p{i:>3}: erro ao extrair texto: {e}")
                    continue
                t = cg.normaliza_texto(bruto)
                m, a = cg.extrai_mes_ano_confiavel(t)
                if m:
                    mes_atual = f"{m}/{a}"
                tipo = ("RESUMO" if cg.eh_pagina_resumo(t) else "COMBUSTÍVEL" if cg.eh_pagina_combustivel(t)
                        else "NOTAS" if cg.eh_pagina_notas(t) else "—")
                tot = cg.TOTAL_RESUMO_RE.search(t) if tipo == "RESUMO" else cg.TOTAL_PAGINA_RE.search(t)
                idx = t.find("Mês")
                trecho_mes = re.sub(r"\s+", " ", t[idx:idx + 40]) if idx >= 0 else "(sem 'Mês')"
                inicio = re.sub(r"[^\w ]", " ", t[:90])
                total_txt = tot.group(1) if tot else "-"
                extra = f" | início: {inicio!r}" if tipo == "—" else ""
                print(f"  p{i:>3}: mês={m or '-'}/{a or '-'} (contexto {mes_atual or '-'}) tipo={tipo:<11} "
                      f"total={total_txt:>12} | {trecho_mes!r} | {len(t)} chars{extra}")
                if tipo == "RESUMO" and (not tot or not m) and despejos < 4:
                    despejos += 1
                    print("      ---- texto da página (resumo sem total ou sem mês) ----")
                    for linha in t.splitlines()[:60]:
                        print("      | " + linha[:160])
            meses = cg.processa_pdf(f.name)
            print("  RESULTADO do leitor: " + ", ".join(f"{k}: total={v['totalDeclarado']}" for k, v in sorted(meses.items())))


if __name__ == "__main__":
    main(sys.argv[1:] or ["CARLÃO:027"])
