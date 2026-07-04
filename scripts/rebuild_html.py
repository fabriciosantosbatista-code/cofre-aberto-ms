#!/usr/bin/env python3
"""
Cofre Aberto MS — Rebuild do HTML com dados atualizados
Roda após coletar_dados.py para embutir os JSONs no HTML
"""

import json, re
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).parent.parent
DADOS = ROOT / "dados"
hoje = datetime.now().strftime("%d/%m/%Y %H:%M")

def log(msg): print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

def carregar_json(nome):
    path = DADOS / nome
    if path.exists():
        return json.load(open(path, encoding="utf-8"))
    log(f"⚠️ {nome} não encontrado")
    return {}

def embutir_const(html, nome_const, dados):
    """Substitui uma constante JS no HTML pelos dados atualizados."""
    novo_js = f"const {nome_const} = " + json.dumps(dados, ensure_ascii=False, separators=(',', ':')) + ";"
    # Regex: captura a constante do início até o fechamento do objeto/array raiz
    pattern = rf'const {re.escape(nome_const)} = \{{.*?\n\}};'
    if re.search(pattern, html, re.S):
        html = re.sub(pattern, novo_js, html, flags=re.S)
        log(f"✅ {nome_const} atualizado ({len(novo_js)//1024}KB)")
    else:
        log(f"⚠️ {nome_const} não encontrado no HTML")
    return html

if __name__ == "__main__":
    log("=" * 50)
    log(f"Cofre Aberto MS — Rebuild HTML {hoje}")
    log("=" * 50)

    html = open(ROOT / "cofre-aberto-ms.html", encoding="utf-8").read()

    # Carregar todos os JSONs
    camara          = carregar_json("camara_municipal.json")
    dep_est         = carregar_json("deputados_estaduais_ms.json")
    sen_brasil      = carregar_json("senadores_brasil.json")
    dep_fed_ms      = carregar_json("deputados_federais_ms.json")
    dep_fed_brasil  = carregar_json("deputados_federais_brasil.json")
    notas_est       = carregar_json("ceap_notas_estaduais.json")
    status          = carregar_json("status.json")

    # Embutir cada constante no HTML
    if camara:
        html = embutir_const(html, "DADOS_CAMARA_MUNICIPAL", camara)

    if dep_est:
        html = embutir_const(html, "DADOS_DEPUTADOS_ESTADUAIS", dep_est)

    if sen_brasil:
        html = embutir_const(html, "DADOS_SENADORES_BRASIL", sen_brasil)

    if dep_fed_brasil:
        html = embutir_const(html, "DADOS_DEP_FEDERAIS_BRASIL", dep_fed_brasil)

    # Notas fiscais estaduais (formato compacto)
    if notas_est:
        notas_compact = {}
        for nome, lista in notas_est.items():
            notas_compact[nome] = [
                [n.get('data',''), n.get('categoria',''), n.get('fornecedor',''),
                 n.get('cnpj',''), n.get('valor',0), n.get('nf',''), n.get('urlPdf','') or '']
                for n in lista
            ]
        notas_js = "const CEAP_NOTAS_ESTADUAIS_RAW=" + json.dumps(notas_compact, ensure_ascii=False, separators=(',',':')) + ";"
        expand_js = "\nconst CEAP_NOTAS_ESTADUAIS={};\nfor(const[n,l]of Object.entries(CEAP_NOTAS_ESTADUAIS_RAW)){CEAP_NOTAS_ESTADUAIS[n]=l.map(r=>({data:r[0],categoria:r[1],fornecedor:r[2],cnpj:r[3],valor:r[4],nf:r[5],urlPdf:r[6]}));}"
        old_block = re.search(r'// Notas fiscais CEAP estaduais.*?for\(const\[n,l\].*?\}\}', html, re.S)
        if old_block:
            html = html[:old_block.start()] + "// Notas fiscais CEAP estaduais (formato compacto)\n" + notas_js + expand_js + html[old_block.end():]
            log(f"✅ CEAP_NOTAS_ESTADUAIS atualizado")

    # Salvar HTML atualizado
    open(ROOT / "cofre-aberto-ms.html", "w", encoding="utf-8").write(html)
    log(f"✅ cofre-aberto-ms.html salvo ({len(html)//1024}KB)")

    log("✅ Rebuild concluído!")
