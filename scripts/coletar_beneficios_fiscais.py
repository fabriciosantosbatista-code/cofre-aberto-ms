#!/usr/bin/env python3
"""
Cofre Aberto MS — empresas com benefício fiscal de ICMS do Governo de MS

Fonte: SEFAZ-MS, página "Benefícios Fiscais <ano>" (sefaz.ms.gov.br/beneficios-fiscais-<ano>/), planilha "Lista Contemplados
por Benefícios Fiscais", publicada uma vez por ano com o ano anterior. Colunas: inscrição estadual, CNPJ, razão social,
seção da CNAE, espécie do benefício, contrapartida e prazo de vigência. A SEFAZ NÃO publica quanto cada empresa deixou de
pagar — só quem foi contemplado e por qual tipo de benefício.

Espécies (notas explicativas da própria página):
  1  atos normativos autoaplicáveis (valem para todos que se enquadram: Anexo I e VI do RICMS, decretos)
  2  atos de aplicação vinculada (regime especial ou autorização específica para a empresa)
  3  termo de acordo (incentivo negociado — LC 93/2001, MS-Indústria)
  4  programas de desenvolvimento (PROAPE e outros)
  5  REFIS (parcelamento com desconto de multa e juros)

O site destaca as espécies 2, 3 e 4 (benefício dado caso a caso) e cruza com: contratos e pagamentos do Estado à mesma
empresa, sócios que doaram para campanha (TSE) e sinais da auditoria.

Gera dados/beneficios_fiscais.json (só baixa de novo quando a planilha muda).
"""

import io, json, re, sys, unicodedata
from datetime import date, datetime
from pathlib import Path

import requests

DADOS = Path(__file__).parent.parent / "dados"
SAIDA = DADOS / "beneficios_fiscais.json"
H = {"User-Agent": "Mozilla/5.0 (CofreAbertoMS; +https://cofreabertoms.com.br)"}
ESPECIES = {1: "Ato normativo autoaplicável", 2: "Regime especial / autorização específica", 3: "Termo de acordo (incentivo negociado)",
            4: "Programa de desenvolvimento", 5: "REFIS (parcelamento com desconto)"}
CASO_A_CASO = {2, 3, 4}
SECOES = {"A": "Agropecuária", "B": "Indústrias extrativas", "C": "Indústria de transformação", "D": "Eletricidade e gás", "E": "Água, esgoto e resíduos",
          "F": "Construção", "G": "Comércio", "H": "Transporte e armazenagem", "I": "Alojamento e alimentação", "J": "Informação e comunicação",
          "K": "Finanças e seguros", "L": "Imobiliárias", "M": "Atividades profissionais e técnicas", "N": "Serviços administrativos",
          "O": "Administração pública", "P": "Educação", "Q": "Saúde e serviços sociais", "R": "Artes, cultura e esporte", "S": "Outros serviços",
          "T": "Serviços domésticos", "U": "Organismos internacionais"}


def dig(t):
    return re.sub(r"\D", "", str(t or ""))


def sa(t):
    return re.sub(r"\s+", " ", "".join(c for c in unicodedata.normalize("NFD", str(t or "").upper()) if unicodedata.category(c) != "Mn")).strip()


def carregar(nome):
    try:
        return json.load(open(DADOS / nome, encoding="utf-8"))
    except Exception:
        return {}


def achar_planilha():
    """(ano de referência, url da planilha) da página mais recente que existir."""
    for ano in range(date.today().year, date.today().year - 4, -1):
        try:
            r = requests.get(f"https://www.sefaz.ms.gov.br/beneficios-fiscais-{ano}/", headers=H, timeout=90)
        except requests.RequestException as e:
            print(f"  ⚠️ {ano}: {e}")
            continue
        if r.status_code != 200:
            continue
        links = re.findall(r"""href=["']([^"']+\.xlsx?)["']""", r.text, re.I)
        if links:
            return ano, links[0]
    return None, None


def ler(conteudo):
    from openpyxl import load_workbook
    wb = load_workbook(io.BytesIO(conteudo), read_only=True, data_only=True)
    linhas = []
    for ws in wb.worksheets:
        cab = None
        for row in ws.iter_rows(values_only=True):
            cel = [("" if v is None else str(v)).strip() for v in row]
            if cab is None:
                if any("CNPJ" in sa(c) for c in cel):
                    cab = [sa(c) for c in cel]
                    print(f"  cabeçalho ({ws.title}): {cab}")
                continue
            if not any(cel):
                continue
            linhas.append(dict(zip(cab, cel)))
    return linhas


def col(d, *nomes):
    for k, v in d.items():
        if any(n in k for n in nomes):
            return v
    return ""


def main():
    ant = carregar("beneficios_fiscais.json")
    ano, url = achar_planilha()
    if not url:
        print("⚠️ planilha de benefícios fiscais não encontrada — dados anteriores mantidos")
        return
    if ant.get("planilha") == url and "--forcar" not in sys.argv:
        print(f"ℹ️ planilha de {ano} sem mudança ({url}) — nada a fazer")
        return
    r = requests.get(url, headers=H, timeout=180)
    r.raise_for_status()
    linhas = ler(r.content)
    print(f"  {len(linhas)} linhas")
    emp, anos_lista = {}, {}
    for d in linhas:
        a_ = d.get("ANO") or ""
        anos_lista[a_] = anos_lista.get(a_, 0) + 1
        cnpj = dig(col(d, "CNPJ"))
        if len(cnpj) != 14:
            continue
        esp_txt = col(d, "ESPECIE", "CODIGO")
        esp = {int(x) for x in re.findall(r"\d+", esp_txt) if 1 <= int(x) <= 9} or set()
        e = emp.setdefault(cnpj, {"cnpj": cnpj, "nome": re.sub(r"\s+", " ", col(d, "RAZAO", "NOME")).strip(), "secao": (col(d, "SECAO", "CNAE") or "")[:1].upper(),
                                  "especies": set(), "contrapartida": False, "vigencia": set(), "inscricoes": set()})
        e["especies"] |= esp
        e["contrapartida"] |= sa(col(d, "CONTRAPARTIDA")).startswith("SIM")
        v = col(d, "PRAZO", "VIGENCIA")
        if v:
            e["vigencia"].add(v[:80])
        ie = dig(col(d, "INSCRICAO"))
        if ie:
            e["inscricoes"].add(ie)
    # cruzamentos
    cred = {dig(c[0]): (c[2] or 0) for c in carregar("governo_ms_credores.json").get("credores") or [] if c and len(dig(c[0])) == 14}
    contr = {}
    for c in carregar("governo_ms_contratos.json").get("contratos") or []:
        k = dig(c.get("cnpj"))
        contr[k] = contr.get(k, 0) + (c.get("valor") or 0)
    cad = carregar("cnpj_cache.json")
    doad = {}
    for chave, p in (carregar("tse_campanhas.json").get("parlamentares") or {}).items():
        quem = (p.get("urna") or chave.split("|")[-1]).title()
        for nome_n, (nome, valor, c6, anos) in (p.get("doadores") or {}).items():
            v = f"R$ {valor:,.0f}".replace(",", ".")
            doad.setdefault((sa(nome_n), c6), []).append(f"{quem} ({(p.get('cargo') or '').lower()}, {', '.join(map(str, anos))}): {v}")
    sinais = {}
    for s in carregar("auditoria.json").get("sinais") or []:
        if s.get("cnpj") and s.get("rotulo"):
            sinais.setdefault(dig(s["cnpj"]), set()).add(s["rotulo"])
    paginas = carregar("empresas_index.json") or {}
    lista = []
    for e in emp.values():
        e["especies"] = sorted(e["especies"])
        e["vigencia"] = sorted(e["vigencia"])[:3]
        e["inscricoes"] = len(e["inscricoes"])
        e["casoACaso"] = bool(set(e["especies"]) & CASO_A_CASO)
        e["setor"] = SECOES.get(e["secao"], "—")
        e["pagoEstado"] = round(cred.get(e["cnpj"], 0), 2)
        e["contratosEstado"] = round(contr.get(e["cnpj"], 0), 2)
        socios = []
        for s in (cad.get(e["cnpj"]) or {}).get("socios") or []:
            for t in doad.get((sa(s.get("nome")), s.get("cpf")), []):
                socios.append(f"o sócio ou dirigente {s['nome'].title()} doou para {t}")
        e["sociosDoadores"] = socios
        e["sinais"] = sorted(sinais.get(e["cnpj"], []))
        e["pagina"] = f"/empresa/{e['cnpj'][:8]}/" if e["cnpj"][:8] in paginas else None
        lista.append(e)
    caso = [e for e in lista if e["casoACaso"]]
    caso.sort(key=lambda e: (-(bool(e["sociosDoadores"]) + bool(e["pagoEstado"] or e["contratosEstado"])), -(e["pagoEstado"] + e["contratosEstado"]), e["nome"]))
    por_esp = {str(k): sum(1 for e in lista if k in e["especies"]) for k in ESPECIES}
    por_setor = {}
    for e in caso:
        por_setor[e["setor"]] = por_setor.get(e["setor"], 0) + 1
    SAIDA.write_text(json.dumps({
        "anoReferencia": int(max(anos_lista, key=anos_lista.get)) if anos_lista and str(max(anos_lista, key=anos_lista.get)).isdigit() else ano, "pagina": ano, "planilha": url, "ultimaAtualizacao": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "fonte": f"SEFAZ-MS — Lista de contemplados por benefícios fiscais (publicada em {ano})",
        "fonteUrl": f"https://www.sefaz.ms.gov.br/beneficios-fiscais-{ano}/", "especies": {str(k): v for k, v in ESPECIES.items()},
        "total": len(lista), "porEspecie": por_esp, "casoACaso": len(caso),
        "porSetor": sorted(([k, v] for k, v in por_setor.items()), key=lambda t: -t[1]),
        "comDinheiroDoEstado": sum(1 for e in caso if e["pagoEstado"] or e["contratosEstado"]),
        "comSocioDoador": sum(1 for e in caso if e["sociosDoadores"]),
        "empresas": caso}, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"✅ beneficios_fiscais.json — {len(lista)} empresas na lista de {ano}; {len(caso)} com benefício caso a caso (espécies 2, 3, 4); "
          f"por espécie {por_esp}; {sum(1 for e in caso if e['sociosDoadores'])} com sócio doador; "
          f"{sum(1 for e in caso if e['pagoEstado'] or e['contratosEstado'])} que também recebem do Estado")


if __name__ == "__main__":
    main()
