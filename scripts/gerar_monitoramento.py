#!/usr/bin/env python3
"""
Cofre Aberto MS — monitoramento das fontes de dados e classificação de confiabilidade

Para cada fonte: nome, fonte oficial, arquivo e endpoint de origem, método de processamento, período de referência,
última tentativa de coleta, última coleta bem-sucedida, data do dado mais recente, quantidade de registros, total
principal, erros registrados, dias desde a última atualização, resultado da conferência na fonte oficial e a
CLASSIFICAÇÃO (uma só, na ordem de prioridade):

  falha_coleta        o robô tentou e o arquivo não foi atualizado (a coleta falhou — o dado antigo foi mantido)
  divergencia         a conferência direta na fonte oficial (validar_fontes.py) encontrou valor diferente
  revisao_manual      há itens marcados para conferência manual (ex.: leitura dos PDFs da Câmara de CG)
  aguardando_fonte    a coleta funcionou, mas a fonte oficial não publica dado novo há mais que o normal
  verificado          conferido direto na fonte oficial há até 8 dias (o valor do site = o da fonte)
  importado           importado da fonte oficial, consistente nas contas internas, mas sem conferência independente

"verificado" exige a conferência na fonte; somas que fecham (tests/test_integridade_dados.py) são consistência
matemática e aparecem à parte, nunca como verificação.

Entradas: dados/status_fontes.json (gerar_dados_abertos.py), dados/validacao_fontes.json, dados/camara_cg_revisao.json,
          os arquivos de cada fonte. Variável COLETA_INICIO (ISO) = início da execução do robô (última tentativa).
Saídas:   dados/monitoramento.json, dados/monitoramento_historico.json (um retrato por coleta, últimas 800) e /monitoramento/.
"""

import json, os, re, subprocess, sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
ROOT = Path(__file__).parent.parent
DADOS = ROOT / "dados"
from zoneinfo import ZoneInfo
FUSO = ZoneInfo("America/Campo_Grande")  # todos os horários do ICP no horário de Campo Grande (o robô e as execuções manuais)
AGORA = datetime.now(FUSO).replace(tzinfo=None)
def _tentativa():
    """Início da execução do robô (a API do GitHub dá em UTC, 'Z'); as datas de coleta estão no horário local."""
    t = (os.environ.get("COLETA_INICIO") or "").strip()
    if not t:
        return AGORA.strftime("%Y-%m-%dT%H:%M:%S")
    try:
        return datetime.fromisoformat(t.replace("Z", "+00:00")).astimezone().replace(tzinfo=None).strftime("%Y-%m-%dT%H:%M:%S")
    except ValueError:
        return AGORA.strftime("%Y-%m-%dT%H:%M:%S")


TENTATIVA = _tentativa()


def J(n):
    try:
        return json.load(open(DADOS / n, encoding="utf-8"))
    except Exception:
        return {}


def soma(xs):
    return round(sum(x or 0 for x in xs), 2)


def n_notas(arq, chave, campo="despesas"):
    return sum(len(p.get(campo) or []) for p in J(arq).get(chave) or [])


# id: (nome, arquivo(s), endpoint/método de coleta, processamento, período de referência, intervalo de coleta (dias),
#      atraso normal de publicação da fonte (dias), registros(), total(), identificador do registro original)
# Câmaras do interior: um arquivo por cidade em dados/camaras/ (coletar_dados.py)
CAMARAS_INTERIOR = sorted(f"camaras/{p.name}" for p in (DADOS / "camaras").glob("*.json"))
FONTES = {
    "camara": ("Câmara Municipal de Campo Grande — verba indenizatória e pessoal dos gabinetes", ["camara_municipal.json", "camara_cg_pdfs.json", "camara_cg_revisao.json"],
               "PDFs das prestações de contas (Atos 027/028) do portal SCPI Fiorilli; folha em /VersaoJson/Pessoal",
               "texto da camada de OCR dos PDFs digitalizados; o gasto exibido é o TOTAL DECLARADO no resumo de cada mês; notas montadas por CNPJ; conferência automática da leitura (validar_camara_cg.py)",
               "ano corrente, por mês de prestação de contas", 1, 80,
               lambda: n_notas("camara_municipal.json", "vereadores"),
               lambda: (J("camara_municipal.json").get("resumo") or {}).get(f"totalVerbaIndenizatoriaPaga{J('camara_municipal.json').get('ano')}"),
               "hash do PDF + página (campo origem de cada nota)"),
    "deputados-estaduais": ("Assembleia Legislativa de MS (ALEMS) — CEAP", ["deputados_estaduais_ms.json"], "transparencia2.al.ms.gov.br/ceap (JSON)",
                            "soma das notas por deputado", "ano corrente", 1, 45, lambda: n_notas("deputados_estaduais_ms.json", "vereadores"),
                            lambda: (J("deputados_estaduais_ms.json").get("resumo") or {}).get(f"totalVerbaIndenizatoriaPaga{J('deputados_estaduais_ms.json').get('ano')}"),
                            "PDF de cada nota (urlPdf)"),
    "deputados": ("Câmara dos Deputados — CEAP dos deputados federais de MS", ["deputados_federais_ms.json"],
                  "camara.leg.br/cotas/Ano-AAAA.csv.zip + API /deputados/{id}/despesas (passagens SIGEPA)",
                  "valor líquido do arquivo anual + passagens SIGEPA da API (o arquivo anual de 2026 não as traz)", "ano corrente", 1, 45,
                  lambda: n_notas("deputados_federais_ms.json", "deputados"), lambda: soma(p.get("cotaGastaAno") for p in J("deputados_federais_ms.json").get("deputados") or []),
                  "urlDocumento / nº do documento de cada nota"),
    "senadores": ("Senado Federal — CEAPS dos senadores de MS", ["senadores_ms.json"], "adm.senado.gov.br/adm-dadosabertos/api/v1/senadores/despesas_ceaps/{ano}",
                  "soma do valor reembolsado por senador", "ano corrente", 1, 45, lambda: n_notas("senadores_ms.json", "senadores", "notasCeaps"),
                  lambda: soma(p.get("cotaGastaAno") for p in J("senadores_ms.json").get("senadores") or []), "id de cada despesa (notasCeaps)"),
    "prefeitura": ("Prefeitura de Campo Grande — despesas pagas", ["prefeitura.json"], "sig-transparencia.campogrande.ms.gov.br/despesas (exportação + página de cada empenho)",
                   "valor pago de cada empenho do ano (lido na página do empenho quando a exportação está parada)", "ano corrente", 1, 15,
                   lambda: len(J("prefeitura.json").get("despesas") or []), lambda: J("prefeitura.json").get("totalDespesas"), "link do empenho (urlDetalhe)"),
    "contratos-cg": ("Prefeitura de Campo Grande — contratos e licitações", ["prefeitura_contratos.json"], "SIG-Transparência (contratos) + PNCP",
                     "lista de contratos do ano", "ano corrente", 1, 30, lambda: len(J("prefeitura_contratos.json").get("contratos") or []),
                     lambda: soma(c.get("valor") for c in J("prefeitura_contratos.json").get("contratos") or []), "nº do registro do contrato"),
    "governo-ms": ("Governo de MS (Poder Executivo) — despesas", ["governo_ms.json", "governo_ms_credores.json", "governo_ms_contratos.json"],
                   "gw.sgi.ms.gov.br (API pública do Portal da Transparência de MS, token anônimo)", "totais do portal por órgão; credores; contratos",
                   "ano corrente até a data da coleta", 1, 7, lambda: len(J("governo_ms_credores.json").get("credores") or []),
                   lambda: (J("governo_ms.json").get("totais") or {}).get("pago"), "código do órgão / CPF-CNPJ do credor"),
    "emendas": ("Portal da Transparência (CGU) — emendas parlamentares pagas em MS", ["emendas_municipios.json"],
                "portaldatransparencia.gov.br/download-de-dados/emendas-parlamentares/UNICO (tabela por favorecido)",
                "soma do valor recebido em MS no ano, por município, autor e favorecido", "ano corrente, mês do pagamento", 1, 45,
                lambda: J("emendas_municipios.json").get("pagamentos"), lambda: J("emendas_municipios.json").get("totalMS"), "código da emenda + favorecido"),
    "supersalarios": ("Folhas de pagamento (Governo do Estado, TJMS, TCE-MS, TRT24 e Câmara CG)", ["supersalarios.json"], "portais de folha + DadosJusBr",
                      "remuneração bruta e líquida do mês; diárias fora do bruto (padrão CNJ)", "último mês publicado de cada órgão", 1, 75,
                      lambda: J("supersalarios.json").get("totalPessoas"), lambda: J("supersalarios.json").get("valorAcimaTeto"), "órgão + mês + nome"),
    "arrecadacao": ("Tesouro Nacional (Siconfi) — arrecadação do Estado e de CG", ["receitas.json"], "apidatalake.tesouro.gov.br/ords/siconfi/tt/rreo (RREO Anexo 3)",
                    "receita mês a mês; o contador ao vivo é ESTIMATIVA (ritmo dos últimos 12 meses)", "até o último bimestre publicado (o RREO sai até 30 dias depois do bimestre)", 1, 95,
                    lambda: len(((J("receitas.json").get("entes") or {}).get("estado") or {}).get("meses") or {}), lambda: None, "ente + mês + conta do RREO"),
    "shows": ("PNCP — shows contratados por órgãos de MS", ["shows.json"], "pncp.gov.br/api/consulta/v1/contratacoes/publicacao (inexigibilidade, art. 74, II)",
              "valor homologado (ou estimado) de cada contratação", "ano corrente", 1, 20, lambda: len(J("shows.json").get("shows") or []),
              lambda: J("shows.json").get("valorShows"), "nº de controle PNCP (link)"),
    "alugueis": ("PNCP e Prefeitura de CG — aluguel de imóveis", ["alugueis.json"], "PNCP (art. 74, V e dispensas de locação) + SIG-Transparência (categorias de locação de imóveis)",
                 "valor do contrato (PNCP) e pagamentos do ano (Prefeitura); compras de imóvel excluídas", "ano corrente", 1, 20,
                 lambda: (J("alugueis.json").get("pncp") or {}).get("contratacoes"), lambda: (J("alugueis.json").get("pncp") or {}).get("total"), "nº de controle PNCP / link do empenho"),
    "producao": ("Câmara e Senado — produção legislativa", ["producao_legislativa.json"], "dadosabertos.camara.leg.br/api/v2/proposicoes + legis.senado.leg.br/dadosabertos/processo",
                 "projetos por autoria (principal/coautor) e situação", "legislatura atual (desde 02/2023)", 1, 30,
                 lambda: sum(p.get("projetos") or 0 for p in J("producao_legislativa.json").get("parlamentares") or []), lambda: None, "id da proposição (link)"),
    "votacoes": ("Câmara e Senado — votações nominais", ["votacoes.json"], "APIs de votações da Câmara e do Senado", "participação = votou ÷ votações nominais",
                 "ano corrente", 1, 30, lambda: len((J("votacoes.json").get("quadroCamara") or {}).get("votacoes") or []), lambda: None, "id da votação"),
    "obras": ("Governo de MS — obras (contratos)", ["obras.json"], "portal do Estado (contratos de obras)", "% executado e datas publicados pelo Estado",
              "contratos em andamento", 1, 30, lambda: (J("obras.json").get("abertas") or {}).get("obras"), lambda: (J("obras.json").get("abertas") or {}).get("valor"), "nº do contrato"),
    "publicidade": ("Publicidade (Estado e Prefeitura)", ["publicidade.json"], "derivado de governo_ms_credores + prefeitura (categoria 88)", "soma por agência",
                    "ano corrente", 1, 30, lambda: len(J("publicidade.json").get("agencias") or []), lambda: soma([(J("publicidade.json").get("estado") or {}).get("total"), (J("publicidade.json").get("prefeitura") or {}).get("total")]), "CNPJ da agência"),
    "entidades": ("Entidades sem fins lucrativos (Estado, Prefeitura, emendas)", ["entidades.json"], "derivado + cadastro da Receita (natureza jurídica)", "soma por entidade",
                  "ano corrente", 1, 30, lambda: J("entidades.json").get("quantidade"), lambda: J("entidades.json").get("total"), "CNPJ"),
    "camaras-ms": ("Câmaras municipais do interior — remuneração e diárias dos vereadores", CAMARAS_INTERIOR,
                   "portais de transparência de cada câmara (Fiorilli SCPI; SAPL/Interlegis em Dourados), coletados por coletar_dados.py",
                   "diárias e remuneração por vereador; despesas institucionais quando o portal publica", "ano corrente", 1, 30,
                   lambda: sum(len(v.get("diarias") or []) for a in CAMARAS_INTERIOR for v in J(a).get("vereadores") or []),
                   lambda: soma(v.get(f"totalDiarias{J(a).get('ano') or datetime.now().year}") or v.get("totalDiarias2026") for a in CAMARAS_INTERIOR for v in J(a).get("vereadores") or []),
                   "câmara + vereador + diária (data e destino)"),
    "judiciario": ("TJMS, TRT24 e TRE-MS — remuneração", ["tjms_magistrados.json"], "DadosJusBr e portais dos tribunais", "bruto, descontos, líquido; diárias à parte",
                   "último mês publicado", 1, 75, lambda: len(J("tjms_magistrados.json").get("magistrados") or []), lambda: None, "tribunal + mês + nome"),
    "eleicoes": ("TSE — eleitos 2026 e patrimônio declarado", ["eleicoes.json"], "dadosabertos.tse.jus.br", "bens declarados por eleição", "eleições", 7, 400,
                 lambda: len(J("eleicoes.json").get("eleitos2026") or []), lambda: None, "sequencial do candidato no TSE"),
    "auditoria": ("Sinais de atenção (gerados pelo site)", ["auditoria.json"], "cruzamento das fontes acima + Receita, CEIS/CNEP, TSE", "~30 testes automáticos",
                  "dados mais recentes de cada fonte", 1, 3, lambda: len(J("auditoria.json").get("sinais") or []), lambda: None, "id do sinal"),
}
ROTULO = {"falha_coleta": "Falha de coleta", "divergencia": "Divergência na fonte", "revisao_manual": "Pendente de revisão manual",
          "aguardando_fonte": "Aguardando atualização da fonte", "verificado": "Verificado na fonte oficial", "importado": "Importado, não conferido na fonte"}


def fim_mes(y, m):
    """Dado mensal cobre o mês inteiro: vale o último dia do mês (sem passar de hoje)."""
    prox = date(y + (m == 12), m % 12 + 1, 1)
    return min(prox - timedelta(days=1), AGORA.date())


def data_do_texto(t):
    """'empenho de 02/10/2026' → 2026-10-02; 'até set/2026' → 2026-09-30; '08/2026' → 2026-08-31 (mês: último dia)."""
    t = t or ""
    m = re.search(r"(\d{2})/(\d{2})/(\d{4})", t)
    if m:
        return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    meses = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]
    m = re.search(r"(" + "|".join(meses) + r")/(\d{4})", t, re.I)
    if m:
        mi = meses.index(m.group(1).lower()) + 1
        return fim_mes(int(m.group(2)), mi)
    ms = re.findall(r"\b(\d{2})/(\d{4})\b", t)
    if ms:
        y, mi = max((int(b), int(a)) for a, b in ms)
        return fim_mes(y, mi)
    return None


def erros_do_arquivo(d):
    out = []
    for k in ("falhas", "erros", "naoEncontrados"):
        v = d.get(k)
        if isinstance(v, list) and v:
            out += [str(x)[:160] for x in v[:5]]
        elif isinstance(v, str) and v:
            out.append(v[:160])
    return out


def consistencia():
    try:
        p = subprocess.run([sys.executable, str(ROOT / "tests" / "test_integridade_dados.py")], capture_output=True, text=True, timeout=300)
        primeira = (p.stdout.strip().splitlines() or [""])[0]
        m = re.search(r"(\d+) conferências OK · ⚠️ (\d+) avisos · ❌ (\d+) erros", primeira)
        return {"resultado": "ok" if p.returncode == 0 else "erro", "resumo": primeira,
                "ok": int(m.group(1)) if m else None, "avisos": int(m.group(2)) if m else None, "erros": int(m.group(3)) if m else None,
                "detalhes": [l for l in p.stdout.splitlines()[1:] if l.startswith(("❌", "⚠️"))][:40]}
    except Exception as e:
        return {"resultado": "indisponivel", "resumo": str(e)}


def execucoes_invalidas():
    """Execuções cujas conferências não valem (dados/icp_anotacoes.json → execucoesInvalidas; regra de 25/11/2026)."""
    return {str(x.get("runId")): x.get("motivo") for x in (J("icp_anotacoes.json").get("execucoesInvalidas") or [])}


def conferencias_validas(val, invalidas):
    """validacao_fontes.json sem as conferências de execuções inválidas: no lugar, a mais recente válida do histórico
    permanente da base (ou nenhuma)."""
    if not invalidas or not any(str(v.get("coletaRunId")) in invalidas for v in val.values()):
        return val
    hist = []
    try:
        hist = [json.loads(l) for l in open(DADOS / "icp_verificacoes.jsonl", encoding="utf-8") if l.strip()]
    except Exception:
        pass
    out = dict(val)
    for b, v in val.items():
        if str(v.get("coletaRunId")) not in invalidas:
            continue
        ok = [h for h in hist if h.get("base") == b and str(h.get("coletaRunId")) not in invalidas
              and h.get("resultado") in ("confere", "mudou_na_fonte", "diverge")]
        out[b] = max(ok, key=lambda h: h.get("em") or "") if ok else {"resultado": "indisponivel", "nota": "sem conferência válida"}
    return out


def main():
    st = (J("status_fontes.json").get("fontes") or {})
    val = conferencias_validas(J("validacao_fontes.json").get("fontes") or {}, execucoes_invalidas())
    rev = J("camara_cg_revisao.json")
    tentativa = datetime.fromisoformat(TENTATIVA[:19])
    out = {}
    for fid, (nome, arqs, endpoint, metodo, periodo, intervalo, atraso, f_reg, f_tot, ident) in FONTES.items():
        s = st.get(fid) or {}
        coleta = s.get("coleta")
        dc = datetime.fromisoformat(coleta[:19]) if coleta else None
        dado = data_do_texto(s.get("dadoMaisRecente"))
        try:
            registros = f_reg()
        except Exception:
            registros = None
        try:
            total = f_tot()
        except Exception:
            total = None
        d0 = J(arqs[0])
        erros = erros_do_arquivo(d0)
        v = val.get(fid) or {}
        dias_coleta = (tentativa - dc).total_seconds() / 86400 if dc else None
        dias_dado = (tentativa.date() - dado).days if dado else None
        coleta_ok = dc is not None and dias_coleta <= intervalo + 1.2
        if not coleta_ok:
            classe, motivo = "falha_coleta", (f"a última coleta bem-sucedida foi há {dias_coleta:.0f} dias (esperado: a cada {intervalo})" if dc else "nunca coletado")
        elif v.get("resultado") == "diverge":
            classe, motivo = "divergencia", f"{len(v.get('divergentes') or [])} item(ns) com valor diferente do da fonte na conferência de {v.get('em', '')[:10]}"
        elif fid == "camara" and (rev.get("resumo") or {}).get("aRevisar") and not (rev.get("resumo") or {}).get("statusNotas"):
            r = rev["resumo"]
            classe, motivo = "revisao_manual", f"{r['itensRevisar']} itens da leitura dos PDFs para conferência manual ({r['aRevisar']} de {r['vereadores']} vereadores)"
        elif dias_dado is not None and dias_dado > atraso:
            classe, motivo = "aguardando_fonte", f"a coleta funciona (última em {coleta[:10]}), mas o dado mais recente publicado pela fonte é de {dado.strftime('%d/%m/%Y')} ({dias_dado} dias; o normal é até {atraso})"
        elif v.get("resultado") in ("confere", "mudou_na_fonte") and (tentativa - datetime.fromisoformat(v["em"][:19])).days <= 8:
            classe, motivo = "verificado", f"conferido direto na fonte em {v['em'][:10]}: {v.get('metodo', '')}" + (f" — {v['nota']}" if v.get("nota") else "")
        else:
            classe, motivo = "importado", "importado da fonte oficial e consistente nas contas internas, mas sem conferência independente na fonte"
        out[fid] = {"nome": nome, "fonteOficial": s.get("fonte"), "url": s.get("url"), "arquivos": [f"dados/{a}" for a in arqs], "endpoint": endpoint,
                    "metodo": metodo, "periodoReferencia": periodo, "identificadorOriginal": ident,
                    "ultimaTentativa": TENTATIVA[:19], "ultimaColeta": coleta, "diasDesdeColeta": round(dias_coleta, 1) if dias_coleta is not None else None,
                    "dadoMaisRecente": s.get("dadoMaisRecente"), "dataDadoMaisRecente": dado.isoformat() if dado else None, "diasDesdeDado": dias_dado,
                    "intervaloColetaDias": intervalo, "atrasoNormalDias": atraso, "registros": registros, "total": total, "erros": erros,
                    "mensagemFonte": s.get("mensagem"), "validacao": {k: v.get(k) for k in ("resultado", "em", "metodo", "conferidos", "divergentes", "nota") if k in v} or None,
                    "classe": classe, "classeRotulo": ROTULO[classe], "motivo": motivo}
    cons = consistencia()
    mon = {"geradoEm": AGORA.strftime("%Y-%m-%dT%H:%M:%S"), "ultimaTentativa": TENTATIVA[:19], "classes": ROTULO,
           "consistenciaInterna": cons, "fontes": out,
           "resumo": {c: sum(1 for f in out.values() if f["classe"] == c) for c in ROTULO}}
    (DADOS / "monitoramento.json").write_text(json.dumps(mon, ensure_ascii=False, indent=1), encoding="utf-8")
    # histórico (um retrato por coleta, chave = início da coleta) — base dos testes de variação.
    # Por coleta e não por dia: duas coletas no mesmo dia também são comparadas (uma queda entre elas não passa despercebida)
    hist = J("monitoramento_historico.json") or {}
    hist[TENTATIVA[:16]] = {fid: {k: f[k] for k in ("registros", "total", "dataDadoMaisRecente", "ultimaColeta", "classe")} for fid, f in out.items()}
    hist = dict(sorted(hist.items())[-800:])
    (DADOS / "monitoramento_historico.json").write_text(json.dumps(hist, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    pagina(mon, rev)
    print("✅ monitoramento.json — " + ", ".join(f"{ROTULO[c]}: {n}" for c, n in mon["resumo"].items() if n) + f" · consistência interna: {cons.get('resumo')}")


def pagina(mon, rev):
    from gerar_paginas_parlamentares import RODAPE, cabecalho, e, escreve_se_mudou, brl
    cor = {"falha_coleta": "#e5484d", "divergencia": "#e5484d", "revisao_manual": "#c98500", "aguardando_fonte": "#c98500", "verificado": "#2bb3a3", "importado": "#7aa2c8"}
    dt = lambda iso: (datetime.fromisoformat(iso[:19]).strftime("%d/%m/%Y %H:%M") if iso else "—")
    lin = []
    for fid, f in mon["fontes"].items():
        tot = brl(f["total"]) if isinstance(f["total"], (int, float)) and f["total"] > 1000 else "—"
        lin.append(f"<tr id='{fid}'><td><b>{e(f['nome'])}</b><br><small>{e(f['fonteOficial'] or '')}</small></td>"
                   f"<td><span class='cl' style='background:{cor[f['classe']]}'>{e(f['classeRotulo'])}</span><br><small>{e(f['motivo'])}</small></td>"
                   f"<td class='n'>{dt(f['ultimaColeta'])}<br><small>tentativa {dt(f['ultimaTentativa'])}</small></td>"
                   f"<td>{e(f['dadoMaisRecente'] or '—')}<br><small>{'' if f['diasDesdeDado'] is None else str(f['diasDesdeDado']) + ' dias'}</small></td>"
                   f"<td class='n'>{'' if f['registros'] is None else format(f['registros'], ',').replace(',', '.')}<br><small>{tot}</small></td>"
                   f"<td>{'<br>'.join(e(x) for x in f['erros']) or '—'}</td></tr>")
    proc = "".join(f"<tr><td><b>{e(f['nome'])}</b></td><td>{e(f['endpoint'])}<br><small>{' · '.join(e(a) for a in f['arquivos'])}</small></td>"
                   f"<td>{e(f['metodo'])}</td><td>{e(f['periodoReferencia'])}</td><td>{e(f['identificadorOriginal'])}</td>"
                   f"<td>{e((f['validacao'] or {}).get('em', '')[:10] or 'sem conferência na fonte')}</td></tr>" for f in mon["fontes"].values())
    r = rev.get("resumo") or {}
    vlin = "".join(f"<tr><td>{e(x['vereador'])}</td><td>{e({'conferida': 'notas conferem', 'parcial': 'parcial', 'revisar': 'conferir'}[x['status']])}</td>"
                   f"<td class='n'>{'—' if x.get('cobertura027') is None else str(x['cobertura027']).replace('.', ',') + '%'}</td>"
                   f"<td class='n'>{'—' if x.get('cobertura028') is None else str(x['cobertura028']).replace('.', ',') + '%'}</td>"
                   f"<td class='n'>{x['itensRevisar']}</td><td class='n'>{x['itensAtencao']}</td></tr>" for x in rev.get("vereadores") or [])
    mud = "".join(f"<li>{e(m['em'][:10])} · {e(m['vereador'])} · {e(m.get('campo', ''))} {e(m.get('mes') or '')}: {e(str(m.get('antes')))} → {e(str(m.get('depois')))} — {e(m['motivo'])}</li>"
                  for m in (rev.get("mudancas") or [])[-30:][::-1]) or "<li>nenhuma mudança inesperada registrada</li>"
    c = mon["consistenciaInterna"]
    corpo = f"""<main class='w'><h1>Monitoramento das fontes</h1>
<p>De onde vem cada número do site, quando foi coletado, quando a fonte oficial publicou o dado mais recente e se ele foi conferido
direto na fonte. Atualizado a cada coleta (última: {dt(mon['geradoEm'])}).</p>
<p><b>Consistência matemática não é a mesma coisa que confirmação na fonte.</b> As contas internas do site (somas, totais, contagens) são
conferidas a cada coleta: <b>{e(c.get('resumo', '—'))}</b>. Isso prova que os números fecham entre si — não que são iguais aos da fonte.
Só recebe "Verificado na fonte oficial" o conjunto que o robô consultou de novo, por um caminho independente, e encontrou o mesmo valor.</p>
<div class='leg'>{''.join(f"<span class='cl' style='background:{cor[k]}'>{e(v)}</span> " for k, v in mon['classes'].items())}</div>
<h2>Situação de cada fonte</h2><div class='tw'><table><thead><tr><th>Fonte</th><th>Classificação</th><th>Última coleta</th><th>Dado mais recente</th><th>Registros · total</th><th>Erros</th></tr></thead><tbody>{''.join(lin)}</tbody></table></div>
<p><small>"Falha de coleta" = o robô tentou e não conseguiu atualizar (o dado anterior foi mantido). "Aguardando atualização da fonte" = a coleta funcionou, mas o órgão
não publicou dado novo — não é erro do site. Exemplo: a Prefeitura de Campo Grande não publica empenhos novos desde 02/10/2026; o robô confere todos os dias.</small></p>
<h2 id='camara-cg'>Câmara de Campo Grande: conferência da leitura dos PDFs</h2>
<p>Os PDFs de prestação de contas da verba indenizatória são documentos digitalizados. O robô lê o texto, monta as notas e guarda, para cada nota, o hash do PDF,
a página e o trecho lido. O gasto exibido é o total declarado no resumo de cada mês. Cada página é lida duas vezes (camada de texto do PDF e OCR da
página renderizada); quando as leituras discordam, vale a que fecha com o total impresso da página. O que a automação não resolve com segurança fica
"não verificado", com o motivo — não há fila de conferência manual. PDFs registrados com hash: <b>{rev.get('pdfsRegistrados', 0)}</b> ·
notas com origem (PDF e página): <b>{r.get('notasComOrigem', 0)}</b> de {r.get('notas', 0)}.</p>
<p>Vereadores: <b>{r.get('conferidas', 0)}</b> com as notas conferindo com o declarado, <b>{r.get('parciais', 0)}</b> parciais e <b>{r.get('aRevisar', 0)}</b> com itens para conferir ·
<b>{r.get('itensRevisar', 0)}</b> itens não verificados e <b>{r.get('itensAtencao', 0)}</b> de atenção · notas:
<b>{(r.get('statusNotas') or {}).get('confere', 0)}</b> conferem, <b>{(r.get('statusNotas') or {}).get('nao_verificado', 0)}</b> não verificadas.</p>
<div class='tw'><table><thead><tr><th>Vereador</th><th>Situação</th><th>Notas ÷ declarado (Ato 027)</th><th>(Ato 028)</th><th>Não verificados</th><th>Atenção</th></tr></thead><tbody>{vlin}</tbody></table></div>
<h3>Mudanças entre coletas</h3><ul>{mud}</ul>
<h2>Procedência: como cada número é obtido</h2><div class='tw'><table><thead><tr><th>Conjunto</th><th>Origem</th><th>Processamento</th><th>Período</th><th>Identificador do registro</th><th>Última conferência na fonte</th></tr></thead><tbody>{proc}</tbody></table></div>
<p><small>Os arquivos de dados ficam públicos em <a href='/dados/monitoramento.json'>dados/monitoramento.json</a> e no histórico do repositório. Metodologia completa em <a href='/metodologia.html'>/metodologia.html</a>.</small></p>
</main>"""
    est = """<style>.w{max-width:1200px;margin:0 auto;padding:24px 16px}table{width:100%;border-collapse:collapse;font-size:.85rem}td,th{border-bottom:1px solid var(--border,#2a2a2a);padding:8px;text-align:left;vertical-align:top}
.n{text-align:right;white-space:nowrap}.tw{overflow-x:auto}.cl{display:inline-block;color:#fff;border-radius:6px;padding:2px 8px;font-size:.72rem;font-weight:700;margin:2px 0}
small{color:var(--ink-caption,#888)}.leg{margin:10px 0 18px}</style>"""
    html = cabecalho("Monitoramento das fontes de dados | Cofre Aberto MS", "Quando cada fonte foi coletada, o dado mais recente publicado, a conferência na fonte oficial e a classificação de confiabilidade de cada conjunto de dados.",
                     "/monitoramento/", None, None, tipo="website").replace("</head>", est + "</head>") + corpo + RODAPE
    (ROOT / "monitoramento").mkdir(exist_ok=True)
    escreve_se_mudou(ROOT / "monitoramento" / "index.html", html)


if __name__ == "__main__":
    main()
