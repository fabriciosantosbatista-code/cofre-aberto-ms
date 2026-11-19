#!/usr/bin/env python3
"""
Cofre Aberto MS — conferência da leitura dos PDFs da verba indenizatória da Câmara de Campo Grande

Os PDFs são documentos digitalizados; o texto vem da camada de OCR do próprio PDF e o robô monta as notas a partir
dele (coletar_verba_camara_cg.py). Este script NÃO muda nenhum valor: só marca o que precisa de conferência manual.

Por vereador e por ato (027 e 028):
  cobertura      soma das notas lidas ÷ total declarado no resumo do PDF (o site exibe o declarado). Fora de 98–102%:
                 notas faltando (leitura incompleta) ou sobrando (possível duplicata ou nota de outro mês)
  meses          mês faltando no meio do ano; mês cujo total foi calculado pelos itens (linha TOTAL ilegível)
  descartes      o que a leitura não pôde usar (sem valor, data ilegível, total acima do limite) — registrado pelo coletor
Por nota:
  CNPJ com dígito verificador inválido · CNPJ válido cujo nome na Receita não confere com o lido (CNPJ lido errado?)
  valor acima de R$ 12.500 (o limite do mês inteiro) · valor zero · data fora do ano · possível duplicata
Entre coletas (dados/camara_cg_snapshot.json):
  total de um mês já publicado que mudou · notas que sumiram

Grava dados/camara_cg_revisao.json, marca cada nota com "revisar" (lista de motivos) e cada vereador com
"conferenciaLeitura". Roda no fim da coleta, antes das páginas.
"""

import hashlib, json, re, unicodedata
from collections import Counter
from datetime import date, datetime
from pathlib import Path

DADOS = Path(__file__).parent.parent / "dados"
M = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]
LIMITE_NOTA = 12500.0
GENERICAS = {"LTDA", "COMERCIO", "SERVICOS", "EIRELI", "EMPRESA", "BRASIL", "GRANDE", "CAMPO", "POSTO", "AUTO", "DISTRIBUIDORA", "COMUNICACAO", "PUBLICIDADE"}


def dig(t):
    return re.sub(r"\D", "", str(t or ""))


def cnpj_valido(c):
    if len(c) != 14 or len(set(c)) == 1:
        return False
    def dv(s, w):
        r = sum(int(x) * y for x, y in zip(s, w)) % 11
        return "0" if r < 2 else str(11 - r)
    return dv(c[:12], [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]) == c[12] and dv(c[:13], [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]) == c[13]


def palavras(t):
    t = "".join(ch for ch in unicodedata.normalize("NFD", (t or "").upper()) if unicodedata.category(ch) != "Mn")
    return {w for w in re.findall(r"[A-Z]{4,}", t) if w not in GENERICAS}

def nome_confere(lido, razao, fantasia=None):
    """O nome lido no PDF tem alguma palavra do nome na Receita? Também aceita palavra grudada pelo OCR ("APNLOCACOES")."""
    oficiais = palavras(razao) | palavras(fantasia)
    if palavras(lido) & oficiais:
        return True
    comp = "".join(ch for ch in unicodedata.normalize("NFD", (lido or "").upper()) if unicodedata.category(ch) != "Mn")
    comp = re.sub(r"[^A-Z]", "", comp)
    return any(len(w) >= 5 and w in comp for w in oficiais)



def chave_nota(d):
    return hashlib.sha1(f"{d.get('data')}|{d.get('valor')}|{d.get('nf') or ''}|{dig(d.get('cnpj'))}".encode()).hexdigest()[:12]


def carregar(nome, padrao=None):
    try:
        return json.load(open(DADOS / nome, encoding="utf-8"))
    except Exception:
        return padrao if padrao is not None else {}


def main():
    cm = carregar("camara_municipal.json")
    if not cm.get("vereadores"):
        print("⚠️ sem camara_municipal.json")
        return
    cad = carregar("cnpj_cache.json")
    snap_ant = carregar("camara_cg_snapshot.json")
    rev_ant = carregar("camara_cg_revisao.json")
    ano = int(cm.get("ano") or date.today().year)
    hoje = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    itens, snap, mudancas = [], {}, list(rev_ant.get("mudancas") or [])
    resumo_v = []

    for v in cm["vereadores"]:
        nome, vi, ds = v["nome"], v.get("verbaIndenizatoria") or {}, v.get("despesas") or []

        def marca(d, motivo, gravidade="revisar"):
            d.setdefault("revisar", [])
            if motivo not in d["revisar"]:
                d["revisar"].append(motivo)
            if gravidade == "revisar":  # só o que impede a nota de ser dada como lida certa (atenção é sinal, não bloqueia)
                d.setdefault("_bloqueia", []).append(motivo)
            itens.append({"vereador": nome, "tipo": "nota", "gravidade": gravidade, "motivo": motivo, "data": d.get("data"),
                          "fornecedor": d.get("fornecedor"), "valor": d.get("valor"), "ato": d.get("ato"),
                          "origem": d.get("origem")})

        for d in ds:
            d.pop("revisar", None)
            d.pop("statusLeitura", None)
        # ── notas ──
        dup = Counter((d.get("data"), d.get("valor"), dig(d.get("cnpj"))) for d in ds)
        dup_nf = Counter((d.get("valor"), d.get("nf"), dig(d.get("cnpj"))) for d in ds if d.get("nf"))
        for d in ds:
            c = dig(d.get("cnpj"))
            if not c:
                marca(d, "sem CNPJ legível")
            elif not cnpj_valido(c):
                marca(d, "CNPJ com dígito verificador inválido (lido com erro)")
            elif c in cad:
                k = cad[c]
                if not nome_confere(d.get("fornecedorOCR") or d.get("fornecedor"), k.get("razao"), k.get("fantasia")):
                    marca(d, f"o nome lido não confere com o CNPJ na Receita ({(k.get('razao') or '')[:60]}) — CNPJ pode ter sido lido errado", "atencao")
            val = d.get("valor")
            if not val or val <= 0:
                marca(d, "valor zero ou ilegível")
            elif val > LIMITE_NOTA:
                marca(d, f"valor de uma nota acima de R$ {LIMITE_NOTA:,.0f}, o limite do mês inteiro".replace(",", "."))
            if not str(d.get("data") or "").startswith(str(ano)):
                marca(d, f"data fora de {ano} ({d.get('data')})")
            if dup[(d.get("data"), d.get("valor"), c)] > 1 or (d.get("nf") and dup_nf[(d.get("valor"), d.get("nf"), c)] > 1):
                marca(d, "possível nota repetida (mesmo fornecedor e valor, mesma data ou mesmo nº de documento)", "atencao")

        # ── status de cada nota: confere / não verificado (motivo) — sem fila manual ──
        for d in ds:
            ex = d.get("extracao") or {}
            motivos = list(d.pop("_bloqueia", None) or [])
            if not ex:
                motivos.append("ainda sem dupla extração (PDF não relido desde a mudança)")
            elif ex.get("status") != "confere":
                motivos.append(ex.get("metodo") or "os dois extratores discordam")
            d["statusLeitura"] = ({"status": "confere", "metodo": ex.get("metodo")} if not motivos
                                  else {"status": "nao_verificado", "motivos": motivos})

        # ── por ato: cobertura e meses ──
        conf = {}
        for ato, campo in (("027", "mesesAto027"), ("028", "mesesAto028")):
            declarado = round(sum((vi.get(campo) or {}).values()), 2)
            somadas = round(sum(d.get("valor") or 0 for d in ds if d.get("ato") == f"ATO {ato}"), 2)
            cob = round(somadas / declarado * 100, 1) if declarado else None
            conf[ato] = {"declarado": declarado, "notasLidas": somadas, "cobertura": cob}
            if cob is not None and not (98 <= cob <= 102):
                motivo = (f"Ato {ato}: as notas lidas somam {cob:.0f}% do total declarado nos resumos do PDF — "
                          + ("faltam notas na leitura" if cob < 98 else "há notas a mais (possível repetição ou nota de outro mês)"))
                itens.append({"vereador": nome, "tipo": "ato", "gravidade": "revisar" if abs(cob - 100) > 10 else "atencao", "motivo": motivo,
                              "ato": f"ATO {ato}", "declarado": declarado, "notasLidas": somadas})
            mm = [M.index(m) for m in (vi.get(campo) or {}) if m in M]
            if mm:
                faltam = [M[i] for i in range(min(mm), max(mm) + 1) if i not in mm]
                if faltam:
                    itens.append({"vereador": nome, "tipo": "ato", "gravidade": "atencao", "ato": f"ATO {ato}",
                                  "motivo": f"Ato {ato}: sem total lido para {', '.join(faltam)} (mês faltando no meio do ano)"})
            for m in vi.get(f"mesesTotalPelosItens{ato}") or []:
                itens.append({"vereador": nome, "tipo": "ato", "gravidade": "atencao", "ato": f"ATO {ato}",
                              "motivo": f"Ato {ato} {m}: linha TOTAL ilegível no PDF — total do mês calculado pela soma dos itens"})
        for x in vi.get("leituraDescartada") or []:
            itens.append({"vereador": nome, "tipo": "descarte", "gravidade": "revisar", "ato": f"ATO {x.get('ato')}",
                          "motivo": f"{x.get('competencia')}: {x.get('motivo')}", "origem": {k: x.get(k) for k in ("pdf", "pagina", "trecho")}})

        # ── entre coletas ──
        s_ant = snap_ant.get(nome) or {}
        for campo in ("mesesAto027", "mesesAto028"):
            for m, val in (s_ant.get(campo) or {}).items():
                novo = (vi.get(campo) or {}).get(m)
                if novo is None:
                    mudancas.append({"em": hoje, "vereador": nome, "campo": campo, "mes": m, "antes": val, "depois": None, "motivo": "total do mês sumiu"})
                elif abs(novo - val) > 0.01:
                    mudancas.append({"em": hoje, "vereador": nome, "campo": campo, "mes": m, "antes": val, "depois": novo,
                                     "motivo": "total de um mês já publicado mudou"})
        chaves = {chave_nota(d) for d in ds}
        sumiram = len(set(s_ant.get("chaves") or []) - chaves)
        if sumiram:
            mudancas.append({"em": hoje, "vereador": nome, "campo": "notas", "antes": len(s_ant.get("chaves") or []), "depois": len(chaves),
                             "motivo": f"{sumiram} nota(s) da coleta anterior não estão mais nos dados"})
        snap[nome] = {"mesesAto027": vi.get("mesesAto027") or {}, "mesesAto028": vi.get("mesesAto028") or {}, "chaves": sorted(chaves)}

        n_rev = sum(1 for i in itens if i["vereador"] == nome and i["gravidade"] == "revisar")
        n_at = sum(1 for i in itens if i["vereador"] == nome and i["gravidade"] == "atencao")
        cobs = [c["cobertura"] for c in conf.values() if c["cobertura"] is not None]
        status = "conferida" if cobs and all(98 <= c <= 102 for c in cobs) and n_rev == 0 else ("revisar" if n_rev else "parcial")
        vi["conferenciaLeitura"] = {"status": status, "atos": conf, "itensRevisar": n_rev, "itensAtencao": n_at, "em": hoje}
        resumo_v.append({"vereador": nome, "status": status, "itensRevisar": n_rev, "itensAtencao": n_at, **{f"cobertura{a}": c["cobertura"] for a, c in conf.items()}})

    mudancas = [m for m in mudancas if m.get("em")][-300:]
    (DADOS / "camara_municipal.json").write_text(json.dumps(cm, ensure_ascii=False, indent=2), encoding="utf-8")
    (DADOS / "camara_cg_snapshot.json").write_text(json.dumps({k: v for k, v in snap.items()}, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    man = carregar("camara_cg_pdfs.json")
    cont = Counter(i["motivo"].split(" (")[0].split(" —")[0] if i["tipo"] == "nota" else i["tipo"] for i in itens)
    (DADOS / "camara_cg_revisao.json").write_text(json.dumps({
        "geradoEm": hoje, "ano": ano,
        "metodo": "Dupla extração de cada página dos PDFs (camada de texto + OCR da página renderizada), com desempate pela conta de fechamento "
                  "(total impresso da página). O que a automação não resolve com segurança fica \"não verificado\", com o motivo e o link do PDF — "
                  "não conta como conferido e não vai para fila manual.",
        "pdfsRegistrados": len(man), "resumo": {
            "vereadores": len(resumo_v), "conferidas": sum(1 for r in resumo_v if r["status"] == "conferida"),
            "parciais": sum(1 for r in resumo_v if r["status"] == "parcial"), "aRevisar": sum(1 for r in resumo_v if r["status"] == "revisar"),
            "itensRevisar": sum(1 for i in itens if i["gravidade"] == "revisar"), "itensAtencao": sum(1 for i in itens if i["gravidade"] == "atencao"),
            "notasComOrigem": sum(1 for v in cm["vereadores"] for d in v.get("despesas") or [] if d.get("origem")),
            "notas": sum(len(v.get("despesas") or []) for v in cm["vereadores"]), "porMotivo": cont.most_common(),
            "statusNotas": dict(Counter((d.get("statusLeitura") or {}).get("status") for v in cm["vereadores"] for d in v.get("despesas") or [])),
            "naoVerificadoPorMotivo": Counter(m.split(" (")[0] for v in cm["vereadores"] for d in v.get("despesas") or []
                                              for m in (d.get("statusLeitura") or {}).get("motivos") or []).most_common(),
            "metodosConfere": Counter((d.get("statusLeitura") or {}).get("metodo") for v in cm["vereadores"] for d in v.get("despesas") or []
                                      if (d.get("statusLeitura") or {}).get("status") == "confere").most_common()},
        "vereadores": resumo_v, "itens": itens, "mudancas": mudancas}, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    r = resumo_v
    print(f"✅ conferência da leitura (Câmara CG): {sum(1 for x in r if x['status'] == 'conferida')} vereadores conferidos, "
          f"{sum(1 for x in r if x['status'] == 'parcial')} parciais, {sum(1 for x in r if x['status'] == 'revisar')} a revisar · "
          f"{sum(1 for i in itens if i['gravidade'] == 'revisar')} itens não verificados, "
          f"{sum(1 for i in itens if i['gravidade'] == 'atencao')} de atenção · {len(mudancas)} mudanças registradas entre coletas")


if __name__ == "__main__":
    main()
