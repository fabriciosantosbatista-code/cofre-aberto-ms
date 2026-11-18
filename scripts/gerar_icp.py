#!/usr/bin/env python3
"""
Cofre Aberto MS — ICP | Índice de Confiabilidade Pública

Metodologia independente da própria plataforma (não é certificação do governo). Mede, para cada base de dados do site,
o quanto o número publicado pode ser comprovado: se foi conferido direto na fonte oficial, se está atualizado, se as
contas internas fecham, se a origem está documentada, se cada registro aponta para o documento original e se a coleta
automática está funcionando.

ENTRADAS (todas produzidas pelos robôs já existentes)
  dados/status_fontes.json           data da coleta e do dado mais recente de cada fonte (gerar_dados_abertos.py)
  dados/validacao_fontes.json        conferência independente na fonte oficial (validar_fontes.py)
  dados/icp_verificacoes.jsonl       histórico PERMANENTE das conferências (só acrescenta)
  dados/icp_execucoes*.json(l)       o que cada robô fez em cada coleta, com os avisos do log (registrar_execucao.py)
  dados/icp_testes_*.json            resultado dos testes por base (tests/test_integridade_dados.py, tests/test_variacoes.py)
  dados/camara_cg_revisao.json       conferência da leitura dos PDFs da Câmara de CG (validar_camara_cg.py)
  metodologia.html                   histórico público de correções (tabela "o que foi corrigido")

DIMENSÕES (0–100 cada; None = não avaliado)
  P precisão e validação   última conferência na fonte: confere 100 · mudou na fonte depois da coleta 90 ·
                           diverge 100×(1 − divergentes/conferidos), no máximo 40. Até 8 dias vale inteira; de 8 a 30
                           dias ×0,8; mais de 30 dias = não avaliado
  A atualização            falha de coleta 0. Senão: dado mais recente até o atraso normal da fonte = 100; acima,
                           cai até 20 quando chega a 2× o atraso normal
  I integridade matemática conferências da base nos testes: 100 × ok ÷ (ok + erros) − 2 por aviso (máx. −20)
  T transparência          5 critérios × 20: fonte oficial nomeada · link oficial · período de referência · método
                           documentado · arquivo de dados público
  R rastreabilidade        % dos registros que trazem o identificador do documento original (link, nº, hash do PDF)
  F integrações            % das últimas 14 coletas em que o robô da base terminou sem falha atribuída a ela

NOTA DA BASE = média ponderada das dimensões avaliadas (P 30 · A 20 · I 20 · T 10 · R 10 · F 10), só se houver ao menos
4 avaliadas; senão "Não avaliado". TETOS (um problema grave não some na média): divergência 40 · falha de coleta 50 ·
revisão manual pendente 70 · sem conferência na fonte 80.
ICP GERAL = média das notas das bases avaliadas, com peso pela importância (3 = gasto principal de governo ou
parlamentar, 2 = recorte relevante, 1 = complementar). Problemas críticos aparecem destacados à parte, qualquer que seja a média.

SAÍDAS: dados/icp.json, dados/monitoramento.json (compatibilidade), dados/monitoramento_historico.json,
        /confiabilidade/ (página do ICP), /confiabilidade/<base>/ (uma por base), /monitoramento/ (redireciona).
"""

import html, json, re, sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import gerar_monitoramento as gm  # noqa: E402  (registro das fontes, datas, classificação base)
from registrar_execucao import JOB_BASES, BOM, RUIM, DESCONHECIDO, bases_da_linha  # noqa: E402

ROOT, DADOS = gm.ROOT, gm.DADOS
AGORA = gm.AGORA
PESOS_DIM = {"P": 30, "A": 20, "I": 20, "T": 10, "R": 10, "F": 10}
NOME_DIM = {"P": "Precisão e validação", "A": "Atualização", "I": "Integridade matemática", "T": "Transparência das fontes",
            "R": "Rastreabilidade", "F": "Funcionamento das integrações"}
TETO = {"divergencia": 40, "falha_coleta": 50, "revisao_manual": 70}
TETO_SEM_VERIFICACAO = 80

# base: (órgão/governo, peso de importância, função de rastreabilidade → (com identificador, total) ou None, limitações conhecidas)
def _rast(arq, lista, campo_lista, teste):
    def f():
        d = gm.J(arq)
        regs = [r for p in (d.get(lista) or []) for r in (p.get(campo_lista) or [])] if campo_lista else (d.get(lista) or [])
        return (sum(1 for r in regs if teste(r)), len(regs)) if regs else None
    return f


def _rast_alugueis():
    lst = (gm.J("alugueis.json").get("pncp") or {}).get("lista") or []
    return (sum(1 for c in lst if c.get("link")), len(lst)) if lst else None


EXTRA = {
    "camara": ("Câmara Municipal de Campo Grande", 3, _rast("camara_municipal.json", "vereadores", "despesas", lambda r: bool((r.get("origem") or {}).get("pdf"))),
               ["A origem de cada nota (hash do PDF e página) passa a ser gravada a partir da coleta com o leitor versão 2; até lá a rastreabilidade das notas fica em 0.",
                "Os PDFs são digitalizados: o texto vem da camada de OCR e a lista de notas pode ter falhas ou repetições.",
                "O portal da Câmara só responde aos servidores do GitHub; não há conferência independente do total declarado.",
                "A folha dos gabinetes vem de uma API JSON da própria Câmara (não de PDF)."]),
    "deputados-estaduais": ("Assembleia Legislativa de MS", 3, _rast("deputados_estaduais_ms.json", "vereadores", "despesas", lambda r: bool(r.get("urlPdf"))),
                            ["Só a CEAP (verba de gabinete); salários dos servidores estão em outra base."]),
    "deputados": ("Câmara dos Deputados", 3, _rast("deputados_federais_ms.json", "deputados", "despesas", lambda r: bool(r.get("urlNotaFiscal") or r.get("doc"))),
                  ["Em 2026 o arquivo anual da Câmara não traz as passagens do SIGEPA; elas vêm da API.",
                   "A API devolve o valor líquido com o sinal invertido nas despesas comuns; o site detecta e corrige."]),
    "senadores": ("Senado Federal", 3, _rast("senadores_ms.json", "senadores", "notasCeaps", lambda r: bool(r.get("id") or r.get("documento") or r.get("doc"))), []),
    "prefeitura": ("Prefeitura de Campo Grande", 3, _rast("prefeitura.json", "despesas", None, lambda r: bool(r.get("urlDetalhe"))),
                   ["O SIG-Transparência não publica empenhos novos desde 02/10/2026; os pagos dos empenhos antigos são lidos empenho a empenho.",
                    "O total inclui despesas intraorçamentárias (ex.: contribuição patronal ao IMPCG)."]),
    "contratos-cg": ("Prefeitura de Campo Grande", 2, _rast("prefeitura_contratos.json", "contratos", None, lambda r: bool(r.get("registro"))), []),
    "governo-ms": ("Governo do Estado de MS (Poder Executivo)", 3, _rast("governo_ms_credores.json", "credores", None, lambda r: bool(r and r[0])),
                   ["Só o Poder Executivo: TJ, Assembleia, MP e TCE têm portais próprios.", "O total inclui despesas intraorçamentárias (ex.: AGEPREV)."]),
    "emendas": ("Governo Federal (CGU)", 3, None, ["Arquivo completo da CGU; a conferência independente é manual (o arquivo tem 47 MB)."]),
    "supersalarios": ("Vários órgãos de MS", 2, _rast("supersalarios.json", "ranking", None, lambda r: bool(r.get("orgao") and r.get("mes"))),
                      ["Diárias ficam fora do bruto (padrão CNJ). Pagamentos eventuais (rescisão) são marcados."]),
    "arrecadacao": ("Tesouro Nacional (Siconfi)", 2, None, ["O contador ao vivo é estimativa; os valores mês a mês são oficiais."]),
    "shows": ("Órgãos de MS (PNCP)", 2, _rast("shows.json", "shows", None, lambda r: bool(r.get("link"))), ["Artista e evento são lidos do texto publicado pelo órgão."]),
    "alugueis": ("Órgãos de MS (PNCP) e Prefeitura de CG", 2, lambda: _rast_alugueis(),
                 ["Ligação política só pelo que TSE e Receita publicam (nome + dígitos do CPF)."]),
    "beneficios": ("SEFAZ-MS", 1, None, ["A SEFAZ não publica o valor do benefício por empresa.", "O site da SEFAZ só responde aos servidores do GitHub."]),
    "producao": ("Câmara e Senado", 1, _rast("producao_legislativa.json", "parlamentares", "todos", lambda r: bool(r.get("link"))), []),
    "votacoes": ("Câmara e Senado", 1, None, []),
    "obras": ("Governo do Estado de MS", 2, _rast("obras.json", "obras", None, lambda r: bool(r.get("numero"))), ["% executado e datas são os que o Estado publica."]),
    "publicidade": ("Governo de MS e Prefeitura de CG", 2, None, ["Derivada de outras bases; herda o atraso da Prefeitura."]),
    "entidades": ("Governo de MS, Prefeitura de CG e CGU", 2, None, ["Derivada de outras bases e do cadastro da Receita."]),
    "camaras-ms": ("Câmaras municipais do interior", 1,
                   lambda: (lambda ds: (sum(1 for d in ds if d.get("data") and isinstance(d.get("valor"), (int, float))), len(ds)) if ds else None)(
                       [d for a in gm.CAMARAS_INTERIOR for v in gm.J(a).get("vereadores") or [] for d in v.get("diarias") or []]),
                   ["Cada câmara tem portal próprio; quando um portal sai do ar, o robô mantém o último dado daquela câmara.",
                    "Valores negativos são estornos (empenho anulado) publicados pela própria câmara e já descontados do total.",
                    "Dourados (SAPL/Interlegis) não publica dados financeiros no mesmo formato das demais."]),
    "judiciario": ("TJMS, TRT24, TRE-MS", 2, None, []),
    "presidencia": ("Presidência da República (CGU)", 1, None, []),
    "stf": ("Supremo Tribunal Federal", 1, None, []),
    "eleicoes": ("TSE", 1, None, []),
    "auditoria": ("Cofre Aberto MS (cruzamentos)", 1, None, ["Sinais de atenção calculados pelo site; não são dados oficiais."]),
}
STATUS = {  # rótulo, cor
    "verificado": ("Verificado na fonte oficial", "verde"), "consistente": ("Consistência interna aprovada", "cinza"),
    "aguardando_fonte": ("Aguardando atualização", "amarelo"), "revisao_manual": ("Pendente de revisão manual", "amarelo"),
    "divergencia": ("Divergência identificada", "vermelho"), "falha_coleta": ("Falha na coleta", "vermelho"),
    "pendente": ("Pendente de verificação", "cinza")}
COR = {"verde": "#1f9d6b", "amarelo": "#c98500", "vermelho": "#d9363e", "cinza": "#7b8494"}
# estado de cada base em cada coleta (calculado por registrar_execucao.py a partir do log real do robô)
ROTULO_EXEC = {"sem_avisos": "coleta concluída sem avisos", "com_avisos": "coleta concluída com avisos", "com_erros": "coleta concluída com erros",
               "parcial": "coleta parcialmente concluída (dado anterior mantido em parte)", "falha_execucao": "falha na execução do robô",
               "leitura_indisponivel": "falha na leitura dos logs (monitoramento indisponível)", "fonte_indisponivel": "fonte indisponível",
               "sem_publicacao_nova": "coleta funcionou; fonte sem publicação nova"}


def jsonl(nome):
    out = []
    try:
        for l in open(DADOS / nome, encoding="utf-8"):
            l = l.strip()
            if l:
                try:
                    out.append(json.loads(l))
                except ValueError:
                    pass
    except FileNotFoundError:
        pass
    return out


def estado_exec(h, fid):
    """Estado da base numa coleta registrada. Registros antigos (sem estado por base, de antes da leitura correta dos
    logs) valem como desconhecidos — não contam a favor nem contra."""
    return (h.get("bases") or {}).get(fid) if isinstance(h.get("bases"), dict) else None


def dimensao_F(exec_hist, fid):
    """% das últimas 14 coletas registradas em que a base terminou sem falha; coletas sem log legível não entram;
    nenhuma coleta com log legível = None (não avaliado — falta de informação não vira nota)."""
    estados = [e for e in (estado_exec(h, fid) for h in exec_hist) if e is not None][-14:]
    conhecidos = [e for e in estados if e not in DESCONHECIDO]
    return round(100 * sum(e in BOM for e in conhecidos) / len(conhecidos), 1) if conhecidos else None


def linhas_da_base(execucao, fid):
    """Linhas do log da última coleta que dizem respeito à base (falhas, fonte fora do ar, erros e avisos)."""
    out = []
    for job, j in (execucao.get("jobs") or {}).items():
        if fid not in (j.get("bases") or []):
            continue
        for chave in ("falhas", "fonteFora", "erros", "avisos"):
            for l in j.get(chave) or []:
                if fid in bases_da_linha(l, j.get("bases") or []) and l not in out:
                    out.append(l)
        if j.get("erroLeitura"):
            out.append(f"não foi possível ler o log do robô {job}: {j['erroLeitura']}")
    return out


def correcoes():
    """Histórico público de correções (tabela de metodologia.html), atribuído à base pelo título."""
    try:
        t = open(ROOT / "metodologia.html", encoding="utf-8").read()
    except FileNotFoundError:
        return []
    mapa = [("deputados", r"Deputados federais|CEAP da Câmara"), ("deputados-estaduais", r"Deputados estaduais"), ("senadores", r"Senador"),
            ("camara", r"Câmara de CG|vereadores|Câmara Municipal"), ("prefeitura", r"Prefeitura"), ("governo-ms", r"Governo MS|Governo de MS|Estado"),
            ("emendas", r"[Ee]mendas"), ("supersalarios", r"Supersal"), ("judiciario", r"Judiciário|TRE|TJMS"), ("alugueis", r"Alugu"),
            ("entidades", r"[Ee]ntidades|ONG"), ("shows", r"Shows"), ("publicidade", r"Publicidade"), ("obras", r"Obras")]
    out = []
    for data, corpo in re.findall(r'<tr><td style="white-space:nowrap">(\d{2}/\d{2}/\d{4})</td><td>(.*?)</td></tr>', t, re.S):
        titulo = re.search(r"<b>(.*?)</b>", corpo)
        tit = re.sub("<[^>]+>", "", titulo.group(1)) if titulo else ""
        texto = html.unescape(re.sub("<[^>]+>", "", corpo)).strip()
        bases = sorted({b for b, rx in mapa if re.search(rx, tit)}) or ["geral"]
        out.append({"data": f"{data[6:]}-{data[3:5]}-{data[:2]}", "titulo": tit.strip(" :"), "texto": texto, "bases": bases})
    return out


def nota_dimensoes(fid, f, ver, testes, rev, exec_hist, falhas_agora):
    reg, extra = gm.FONTES[fid], EXTRA.get(fid, ("—", 1, None, []))
    dims = {}
    # P — precisão/validação (última conferência na fonte, automática ou manual registrada no histórico)
    v = ver.get(fid)
    if v:
        idade = (AGORA - datetime.fromisoformat(v["em"][:19])).days
        r = v["resultado"]
        base = 100 if r == "confere" else 90 if r == "mudou_na_fonte" else (min(40, 100 * (1 - len(v.get("divergentes") or []) / max(1, v.get("conferidos") or 1))) if r == "diverge" else None)
        if base is not None and idade <= 30:
            dims["P"] = round(base * (1 if idade <= 8 else 0.8), 1)
    # A — atualização
    if f["classe"] == "falha_coleta":
        dims["A"] = 0
    elif f["diasDesdeDado"] is not None:
        d, at = f["diasDesdeDado"], f["atrasoNormalDias"]
        dims["A"] = 100 if d <= at else round(max(20, 100 - 80 * (d - at) / max(1, at)), 1)
    elif f["ultimaColeta"]:
        dims["A"] = 100
    # I — integridade matemática (testes da base, sem as linhas de classificação de fonte)
    itens = [x for x in testes if x["base"] == fid and not x["texto"].startswith("fonte ")
             and "Aguardando atualização" not in x["texto"] and "Pendente de revisão" not in x["texto"]]
    ok, av, er = (sum(1 for x in itens if x["nivel"] == n) for n in ("ok", "aviso", "erro"))
    if ok + er:
        dims["I"] = round(max(0, 100 * ok / (ok + er) - min(20, 2 * av)), 1)
    # T — transparência
    crit = [bool(f.get("fonteOficial")), bool(f.get("url")), bool(reg[4]), bool(reg[3]), bool(reg[1])]
    dims["T"] = 20 * sum(crit)
    # R — rastreabilidade
    fr = extra[2]
    try:
        r_ = fr() if fr else None
    except Exception:
        r_ = None
    if r_ and r_[1]:
        dims["R"] = round(100 * r_[0] / r_[1], 1)
    # F — integrações: % das últimas 14 coletas (com log lido) em que o robô da base terminou sem falha atribuída a ela.
    # Coleta sem log legível não conta a favor; sem nenhuma coleta com log legível, F = não avaliado.
    f_ = dimensao_F(exec_hist, fid)
    if f_ is not None:
        dims["F"] = f_
    return dims, {"ok": ok, "avisos": av, "erros": er, "itens": itens}


def nota_base(dims, classe):
    """Média ponderada das dimensões avaliadas (mín. 4) com os tetos; None = não avaliado."""
    av = {k: v for k, v in dims.items() if v is not None}
    if len(av) < 4:
        return None
    nota = sum(v * PESOS_DIM[k] for k, v in av.items()) / sum(PESOS_DIM[k] for k in av)
    if classe in TETO:
        nota = min(nota, TETO[classe])
    if "P" not in av:
        nota = min(nota, TETO_SEM_VERIFICACAO)
    return round(nota)


def main():
    gm_main_out = gm_classificar()
    mon = gm_main_out
    ver_auto = (gm.J("validacao_fontes.json").get("fontes") or {})
    hist_ver = jsonl("icp_verificacoes.jsonl")
    ver = {}
    for h in hist_ver:  # a conferência mais recente de cada base (automática ou manual)
        if h.get("resultado") in ("confere", "mudou_na_fonte", "diverge") and (h["base"] not in ver or h["em"] > ver[h["base"]]["em"]):
            ver[h["base"]] = h
    for b, v in ver_auto.items():
        if v.get("resultado") in ("confere", "mudou_na_fonte", "diverge") and (b not in ver or v["em"] > ver[b]["em"]):
            ver[b] = {**v, "base": b}
    testes = []
    for t in ("icp_testes_integridade.json", "icp_testes_variacoes.json"):
        testes += (gm.J(t) or {}).get("itens") or []
    rev = gm.J("camara_cg_revisao.json")
    exec_atual = gm.J("icp_execucoes.json") or {}
    exec_hist = jsonl("icp_execucoes_historico.jsonl")
    # uma coleta pode ter sido registrada mais de uma vez (ex.: releitura correta dos logs): vale o registro mais recente
    ultimo = {h.get("runId"): i for i, h in enumerate(exec_hist)}
    exec_hist = [h for i, h in enumerate(exec_hist) if ultimo.get(h.get("runId")) == i]
    falhas_agora = {fid: linhas_da_base(exec_atual, fid) for fid in mon["fontes"]}
    cors = correcoes()
    bases = {}
    for fid, f in mon["fontes"].items():
        extra = EXTRA.get(fid, ("—", 1, None, []))
        classe = f["classe"]
        # falha técnica: as duas últimas coletas com log legível falharam para a base → falha de coleta mesmo com arquivo recente
        ult = [e for e in (estado_exec(h, fid) for h in exec_hist) if e is not None and e not in DESCONHECIDO][-2:]
        if classe != "falha_coleta" and len(ult) == 2 and all(e in RUIM for e in ult):
            classe, f["motivo"] = "falha_coleta", (f"as duas últimas coletas falharam ({ROTULO_EXEC[ult[-1]]}"
                                                   + (f": {falhas_agora[fid][0]}" if falhas_agora.get(fid) else "") + ") — o dado anterior foi mantido")
        estado_atual = estado_exec(exec_atual, fid)
        queda = [x["texto"] for x in testes if x["nivel"] == "erro" and x["texto"].startswith(f"{fid}: registros caíram")]
        if queda and classe != "falha_coleta":  # a fonte "respondeu" mas veio pela metade: é falha técnica, não dado novo
            classe, f["motivo"] = "falha_coleta", queda[0] + " — provável coleta incompleta"
        dims, tst = nota_dimensoes(fid, {**f, "classe": classe}, ver, testes, rev, exec_hist, falhas_agora)
        if classe == "importado":
            status = "consistente" if "I" in dims and tst["erros"] == 0 else "pendente"
        else:
            status = classe
        if status == "verificado" and "P" not in dims:
            status = "consistente" if "I" in dims and tst["erros"] == 0 else "pendente"  # nunca verde sem conferência registrada
        nota = nota_base(dims, classe)
        pend = []
        if f["classe"] in ("aguardando_fonte", "revisao_manual", "divergencia", "falha_coleta") or classe != f["classe"]:
            pend.append(f["motivo"])
        if estado_atual in RUIM:
            pend.append(f"última coleta: {ROTULO_EXEC[estado_atual]}" + (f" — {falhas_agora[fid][0]}" if falhas_agora.get(fid) else ""))
        elif estado_atual == "leitura_indisponivel":
            pend.append("monitoramento indisponível: não foi possível ler o log do robô nesta coleta — a coleta não é contada como bem-sucedida")
        elif estado_atual is None:
            pend.append("execução do robô não registrada para esta base")
        pend += [f"teste: {x['texto']}" for x in tst["itens"] if x["nivel"] == "erro"][:5]
        if "P" not in dims:
            pend.append("sem conferência independente na fonte oficial nos últimos 30 dias")
        bases[fid] = {**f, "id": fid, "orgao": extra[0], "importancia": extra[1], "limitacoes": extra[3], "classe": classe,
                      "status": status, "statusRotulo": STATUS[status][0], "statusCor": STATUS[status][1],
                      "dimensoes": {k: dims.get(k) for k in PESOS_DIM}, "nota": nota, "testes": {k: tst[k] for k in ("ok", "avisos", "erros")},
                      "testesItens": [{"nivel": x["nivel"], "texto": x["texto"]} for x in tst["itens"]][:200],
                      "ultimaVerificacao": ({k: ver[fid].get(k) for k in ("em", "resultado", "metodo", "fonteUrl", "conferidos", "comparados", "divergentes", "nota", "tipo")} if fid in ver else None),
                      "historicoVerificacoes": [h for h in hist_ver if h.get("base") == fid][-50:],
                      "divergencias": [h for h in hist_ver if h.get("base") == fid and h.get("resultado") == "diverge"],
                      "correcoes": [c for c in cors if fid in c["bases"]], "falhasUltimaColeta": falhas_agora.get(fid, [])[:10],
                      "ultimaExecucao": {"estado": estado_atual, "rotulo": ROTULO_EXEC.get(estado_atual, "não registrada"), "runId": exec_atual.get("runId"),
                                         "inicio": exec_atual.get("inicio"), "fim": exec_atual.get("fim")},
                      "historicoExecucoes": [{"runId": h.get("runId"), "inicio": h.get("inicio"), "estado": estado_exec(h, fid)} for h in exec_hist[-14:]],
                      "pendencias": pend}
    aval = [b for b in bases.values() if b["nota"] is not None]
    peso = sum(b["importancia"] for b in aval)
    geral = round(sum(b["nota"] * b["importancia"] for b in aval) / peso) if peso else None
    dim_geral = {}
    for k in PESOS_DIM:
        xs = [(b["dimensoes"][k], b["importancia"]) for b in bases.values() if b["dimensoes"][k] is not None]
        dim_geral[k] = round(sum(v * w for v, w in xs) / sum(w for _, w in xs)) if xs else None
    criticos = []  # o que a média geral não pode esconder
    for b in bases.values():
        fracas = [NOME_DIM[k].lower() + f" {v:g}" for k, v in b["dimensoes"].items() if v is not None and v <= 40]
        if b["status"] in ("divergencia", "falha_coleta"):
            b["alerta"] = b["motivo"]
        elif b["importancia"] >= 2 and (fracas or (b["nota"] is not None and b["nota"] < 60)):
            b["alerta"] = "nota baixa em " + ", ".join(fracas) if fracas else f"nota {b['nota']}"
        elif b["importancia"] == 3 and b["status"] == "revisao_manual":
            b["alerta"] = b["motivo"]
        if b.get("alerta"):
            criticos.append(b)
    ind = {"total": len(bases), "verificadas": sum(1 for b in bases.values() if b["status"] == "verificado"),
           "consistenciaAprovada": sum(1 for b in bases.values() if b["testes"]["ok"] and not b["testes"]["erros"]),
           "aguardando": sum(1 for b in bases.values() if b["status"] == "aguardando_fonte"),
           "divergencias": sum(1 for b in bases.values() if b["status"] == "divergencia"),
           "falhas": sum(1 for b in bases.values() if b["status"] == "falha_coleta"),
           "revisaoManual": sum(1 for b in bases.values() if b["status"] == "revisao_manual"),
           "pendentesVerificacao": sum(1 for b in bases.values() if b["dimensoes"]["P"] is None),
           "naoAvaliadas": sum(1 for b in bases.values() if b["nota"] is None)}
    icp = {"nome": "ICP — Índice de Confiabilidade Pública", "geradoEm": AGORA.strftime("%Y-%m-%dT%H:%M:%S"), "ultimaTentativa": mon["ultimaTentativa"],
           "nota": geral, "dimensoes": dim_geral, "nomeDimensoes": NOME_DIM, "pesosDimensoes": PESOS_DIM, "tetos": {**TETO, "sem_verificacao": TETO_SEM_VERIFICACAO},
           "indicadores": ind, "criticos": [{"id": b["id"], "nome": b["nome"], "status": b["statusRotulo"], "motivo": b["alerta"], "nota": b["nota"]} for b in criticos],
           "status": {k: {"rotulo": v[0], "cor": v[1]} for k, v in STATUS.items()}, "bases": bases,
           "verificacoesRecentes": sorted(hist_ver, key=lambda h: h["em"])[-25:][::-1],
           "execucao": {"runId": exec_atual.get("runId"), "inicio": exec_atual.get("inicio"), "fim": exec_atual.get("fim"),
                        "leitura": exec_atual.get("leitura") or "nao_registrada", "erroLeitura": exec_atual.get("erroLeitura"),
                        "rotulos": ROTULO_EXEC, "testes": exec_atual.get("testes"), "publicacao": exec_atual.get("publicacao"),
                        "arquivosAtualizados": len(exec_atual.get("arquivosAtualizados") or []) if exec_atual.get("arquivosAtualizados") is not None else None,
                        "jobs": [{"nome": k, "estado": v.get("estado"), "rotulo": ROTULO_EXEC.get(v.get("estado"), v.get("estado")), "motivo": v.get("motivo"),
                                  "conclusao": v.get("conclusao"), "inicio": v.get("inicio"), "fim": v.get("fim"), "leitura": v.get("leitura"),
                                  "nAvisos": v.get("nAvisos"), "nErros": v.get("nErros"), "nFalhas": v.get("nFalhas"), "bases": v.get("bases"),
                                  "etapasFalharam": (v.get("etapas") or {}).get("falharam") or []}
                                 for k, v in sorted((exec_atual.get("jobs") or {}).items())],
                        "historico": len(exec_hist)}}
    (DADOS / "icp.json").write_text(json.dumps(icp, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    paginas(icp)
    print(f"✅ ICP — nota geral {geral if geral is not None else 'não avaliada'} · " + ", ".join(f"{k} {v}" for k, v in ind.items())
          + (f" · CRÍTICOS: {', '.join(b['nome'] for b in criticos)}" if criticos else ""))


def gm_classificar():
    """Roda a classificação do monitoramento (gerar_monitoramento.main) e devolve o resultado, sem a página antiga."""
    gm.pagina = lambda mon, rev: None
    gm.main()
    return gm.J("monitoramento.json")


# ─────────────────────────────────────────── páginas ───────────────────────────────────────────
def paginas(icp):
    from gerar_paginas_parlamentares import RODAPE, cabecalho, e, escreve_se_mudou, brl
    pasta = ROOT / "confiabilidade"
    pasta.mkdir(exist_ok=True)
    dt = lambda iso: datetime.fromisoformat(iso[:19]).strftime("%d/%m/%Y %H:%M") if iso else "—"
    dd = lambda iso: datetime.fromisoformat(iso[:10]).strftime("%d/%m/%Y") if iso else "—"
    num = lambda n: "—" if n is None else f"{n:,}".replace(",", ".")
    selo = lambda b: f"<span class='selo {b['statusCor']}'>{e(b['statusRotulo'])}</span>"
    nota_txt = lambda n: "Não avaliado" if n is None else str(n)
    est = """<style>
.w{max-width:1180px;margin:0 auto;padding:22px 16px 40px}.w h1{font-size:clamp(1.6rem,4vw,2.3rem);margin:.2em 0}.w h2{margin-top:34px}
.lead{color:var(--ink-soft,#c9cfdb);max-width:820px}.aviso{border:1px solid var(--border,#2a2a2a);border-left:4px solid #7b8494;border-radius:10px;padding:10px 14px;font-size:.88rem;margin:14px 0}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin:14px 0}
.card{border:1px solid var(--border,#2a2a2a);border-radius:12px;padding:14px;background:var(--surface,#11141c)}
.card b{display:block;font-size:1.7rem;font-variant-numeric:tabular-nums}.card span{font-size:.78rem;color:var(--ink-caption,#8a93a6)}
.card.verde{border-top:3px solid #1f9d6b}.card.amarelo{border-top:3px solid #c98500}.card.vermelho{border-top:3px solid #d9363e}.card.cinza{border-top:3px solid #7b8494}
.nota{display:flex;gap:22px;align-items:center;flex-wrap:wrap}.nota .n{font-size:4rem;font-weight:800;line-height:1}.dim{flex:1;min-width:260px}
.bar{display:flex;align-items:center;gap:8px;margin:5px 0;font-size:.85rem}.bar i{flex:1;height:8px;border-radius:6px;background:var(--border,#2a2a2a);overflow:hidden}
.bar i b{display:block;height:100%;background:#1f9d6b}.bar em{font-style:normal;width:84px;text-align:right;font-variant-numeric:tabular-nums}
.selo{display:inline-block;color:#fff;border-radius:999px;padding:2px 10px;font-size:.74rem;font-weight:700;white-space:nowrap}
.selo.verde{background:#1f9d6b}.selo.amarelo{background:#c98500}.selo.vermelho{background:#d9363e}.selo.cinza{background:#7b8494}
table{width:100%;border-collapse:collapse;font-size:.86rem}td,th{border-bottom:1px solid var(--border,#2a2a2a);padding:8px;text-align:left;vertical-align:top}
th{font-size:.72rem;text-transform:uppercase;letter-spacing:.05em;color:var(--ink-caption,#8a93a6)}.n{text-align:right;white-space:nowrap;font-variant-numeric:tabular-nums}
.tw{overflow-x:auto}small{color:var(--ink-caption,#8a93a6)}.crit{border:1px solid #d9363e;background:rgba(217,54,62,.08);border-radius:12px;padding:12px 16px;margin:16px 0}
.filtros{display:flex;gap:8px;flex-wrap:wrap;margin:10px 0}.filtros input,.filtros select{background:var(--surface,#11141c);color:inherit;border:1px solid var(--border,#2a2a2a);border-radius:8px;padding:8px 10px;font:inherit}
.filtros input{flex:1;min-width:200px}tr.base{cursor:pointer}tr.base:hover td{background:rgba(255,255,255,.03)}
.w li,.w dd,.w p{overflow-wrap:anywhere}td{overflow-wrap:break-word}
dl{display:grid;grid-template-columns:minmax(150px,240px) minmax(0,1fr);gap:6px 14px;font-size:.9rem}dt{color:var(--ink-caption,#8a93a6)}dd{margin:0}
@media(max-width:640px){dl{grid-template-columns:1fr}dt{margin-top:8px}.nota .n{font-size:3rem}.esconde-cel{display:none}}
</style>"""
    I = icp["indicadores"]
    cards = [("verde", I["verificadas"], "verificadas diretamente nas fontes oficiais"), ("cinza", I["consistenciaAprovada"], "com consistência interna aprovada"),
             ("amarelo", I["aguardando"], "aguardando atualização da fonte"), ("amarelo", I["revisaoManual"], "com revisão manual pendente"),
             ("vermelho", I["divergencias"], "com divergência"), ("vermelho", I["falhas"], "com falha de coleta"),
             ("cinza", I["pendentesVerificacao"], "pendentes de verificação na fonte")]
    dims = "".join(f"<div class='bar'><span style='width:210px'>{e(icp['nomeDimensoes'][k])} <small>(peso {icp['pesosDimensoes'][k]})</small></span>"
                   f"<i><b style='width:{v or 0}%'></b></i><em>{'Não avaliado' if v is None else v}</em></div>" for k, v in icp["dimensoes"].items())
    crit = ("<div class='crit'><b>Problemas que a média não esconde</b><ul>" + "".join(
        f"<li><a href='/confiabilidade/{c['id']}/'>{e(c['nome'])}</a> — {e(c['status'])}: {e(c['motivo'])}</li>" for c in icp["criticos"]) + "</ul></div>") if icp["criticos"] else \
        "<div class='aviso' style='border-left-color:#1f9d6b'>Nenhuma base com divergência na fonte ou falha de coleta nesta atualização.</div>"
    linhas = "".join(
        f"<tr class='base' data-status='{b['status']}' data-busca='{e((b['nome'] + ' ' + b['orgao'] + ' ' + (b['fonteOficial'] or '')).lower())}' onclick=\"location.href='/confiabilidade/{fid}/'\">"
        f"<td><a href='/confiabilidade/{fid}/'><b>{e(b['nome'])}</b></a><br><small>{e(b['orgao'])}</small></td>"
        f"<td class='esconde-cel'><small>{e(b['fonteOficial'] or '—')}</small></td><td>{selo(b)}</td>"
        f"<td class='n'><b>{nota_txt(b['nota'])}</b></td><td class='n'>{dt(b['ultimaColeta'])}</td>"
        f"<td class='esconde-cel'><small>{e(b['periodoReferencia'])}</small></td>"
        f"<td class='n'>{dd((b['ultimaVerificacao'] or {}).get('em')) if b['ultimaVerificacao'] else '<small>sem conferência</small>'}</td>"
        f"<td class='n'>{num(b['registros'])}</td><td class='n'>{len(b['pendencias'])}</td></tr>" for fid, b in sorted(icp["bases"].items(), key=lambda kv: (-kv[1]["importancia"], kv[1]["nome"])))
    recentes = "".join(f"<tr><td class='n'>{dt(h['em'])}</td><td><a href='/confiabilidade/{h['base']}/'>{e(icp['bases'].get(h['base'], {}).get('nome', h['base']))}</a></td>"
                       f"<td>{e({'confere': 'confere', 'mudou_na_fonte': 'mudou na fonte depois da coleta', 'diverge': 'diverge'}.get(h['resultado'], h['resultado']))}</td>"
                       f"<td class='n'>{h.get('conferidos', 0)}</td><td><small>{e(h.get('metodo') or '')}</small></td></tr>" for h in icp["verificacoesRecentes"])
    opcoes = "".join(f"<option value='{k}'>{e(v['rotulo'])}</option>" for k, v in icp["status"].items())
    corpo = f"""<main class='w'>
<p><small>Confiabilidade dos Dados</small></p><h1>ICP — Índice de Confiabilidade Pública</h1>
<p class='lead'>O ICP mostra, para cada base de dados do Cofre Aberto MS, o quanto os números publicados podem ser comprovados: se foram conferidos
direto na fonte oficial, se estão atualizados, se as contas fecham, se a origem está documentada e se cada registro aponta para o documento original.</p>
<div class='aviso'><b>O ICP é uma metodologia independente do próprio Cofre Aberto MS</b>, calculada automaticamente pelos robôs do site a cada coleta.
Não é uma certificação oficial do governo nem de qualquer órgão de controle. Consistência matemática (as somas fecham) <b>não</b> é tratada como prova de exatidão:
só recebe o selo verde a base que o robô consultou de novo na fonte oficial e encontrou o mesmo valor.</div>
<div class='grid'><div class='card'><b>{I['total']}</b><span>bases monitoradas</span></div>
<div class='card'><b>{dt(icp['geradoEm'])}</b><span>última atualização do índice</span></div>
<div class='card'><b>{len(icp['verificacoesRecentes']) and dt(icp['verificacoesRecentes'][0]['em'])}</b><span>última conferência na fonte oficial</span></div></div>
<h2>Nota geral</h2>
<div class='nota'><div><div class='n'>{nota_txt(icp['nota'])}</div><small>de 0 a 100 · {I['total'] - I['naoAvaliadas']} bases avaliadas, {I['naoAvaliadas']} não avaliadas</small></div><div class='dim'>{dims}</div></div>
{crit}
<h2>Painel</h2><div class='grid'>{''.join(f"<div class='card {c}'><b>{n}</b><span>{e(t)}</span></div>" for c, n, t in cards)}</div>
<h2>Todas as bases</h2>
<div class='filtros'><input id='busca' type='search' placeholder='buscar base, órgão ou fonte…' aria-label='Buscar base'/>
<select id='fstatus' aria-label='Filtrar por status'><option value=''>Todos os status</option>{opcoes}</select></div>
<div class='tw'><table id='tab'><thead><tr><th>Base</th><th class='esconde-cel'>Fonte oficial</th><th>Status</th><th class='n'>Nota</th><th class='n'>Última coleta</th>
<th class='esconde-cel'>Período</th><th class='n'>Conferência oficial</th><th class='n'>Registros</th><th class='n'>Pendências</th></tr></thead><tbody>{linhas}</tbody></table></div>
<p id='vazio' hidden>Nenhuma base encontrada.</p>
<h2>Como funciona a verificação</h2>
<ol><li><b>Coleta:</b> os robôs baixam os dados das fontes oficiais todos os dias e registram o que cada um conseguiu ou não (avisos do log).</li>
<li><b>Testes matemáticos:</b> a cada coleta, centenas de conferências refazem somas, totais, contagens e percentuais a partir dos registros, procuram duplicatas,
valores impossíveis, quedas ou saltos anormais, mudanças no formato das fontes e dados pessoais expostos.</li>
<li><b>Conferência na fonte oficial:</b> para as bases onde é possível, o robô consulta a fonte de novo, por um caminho independente da coleta, e compara valor a valor.
Cada conferência fica num histórico permanente (só acrescenta, nunca apaga).</li>
<li><b>Classificação e nota:</b> cada base recebe um status e uma nota de 0 a 100 pelos critérios abaixo.</li></ol>
<h2>Critérios e fórmulas</h2><div class='tw'><table><thead><tr><th>Dimensão</th><th>Peso</th><th>Como é calculada</th></tr></thead><tbody>
<tr><td>Precisão e validação</td><td class='n'>30</td><td>Última conferência na fonte oficial: confere = 100; mudou na fonte depois da coleta = 90; divergência = 100 × (1 − divergentes ÷ conferidos), no máximo 40. Até 8 dias vale inteira, de 8 a 30 dias vale 80%, mais de 30 dias = não avaliado.</td></tr>
<tr><td>Atualização</td><td class='n'>20</td><td>Falha de coleta = 0. Dado mais recente dentro do atraso normal da fonte = 100; acima disso cai até 20 quando chega ao dobro do atraso normal.</td></tr>
<tr><td>Integridade matemática</td><td class='n'>20</td><td>100 × conferências aprovadas ÷ (aprovadas + erros) − 2 por aviso (desconto máximo de 20).</td></tr>
<tr><td>Transparência das fontes</td><td class='n'>10</td><td>20 pontos para cada: fonte oficial nomeada, link oficial, período de referência, método documentado, arquivo de dados público.</td></tr>
<tr><td>Rastreabilidade</td><td class='n'>10</td><td>% dos registros que trazem o identificador do documento original (link do empenho, nº da nota, hash e página do PDF, nº de controle do PNCP).</td></tr>
<tr><td>Funcionamento das integrações</td><td class='n'>10</td><td>% das últimas 14 coletas em que o robô da base terminou sem falha atribuída a ela.</td></tr></tbody></table></div>
<p>Nota da base = média ponderada das dimensões avaliadas, só quando há ao menos 4; senão, <b>Não avaliado</b>. Tetos que a média não derruba:
divergência na fonte, no máximo {icp['tetos']['divergencia']}; falha de coleta, {icp['tetos']['falha_coleta']}; revisão manual pendente, {icp['tetos']['revisao_manual']};
sem conferência na fonte, {icp['tetos']['sem_verificacao']}. ICP geral = média das notas das bases avaliadas, com peso 3 para os gastos principais de governo e parlamentares,
2 para recortes relevantes e 1 para bases complementares. A documentação completa está em <a href='https://github.com/fabriciosantosbatista-code/cofre-aberto-ms/blob/main/ICP_DOCUMENTACAO.md'>ICP_DOCUMENTACAO.md</a>.</p>
<h2>Status</h2><p>{' '.join(f"<span class='selo {v['cor']}'>{e(v['rotulo'])}</span>" for v in icp['status'].values())}</p>
<p><small><b>Aguardando atualização</b> = a coleta funciona, mas o órgão não publicou dado novo (não é falha do site). <b>Falha na coleta</b> = o robô não conseguiu atualizar
(a fonte saiu do ar ou mudou) e o dado anterior foi mantido. <b>Consistência interna aprovada</b> = as contas fecham, mas o valor ainda não foi conferido na fonte.</small></p>
<h2>Conferências recentes na fonte oficial</h2><div class='tw'><table><thead><tr><th class='n'>Quando</th><th>Base</th><th>Resultado</th><th class='n'>Itens</th><th>Método</th></tr></thead><tbody>{recentes}</tbody></table></div>
<p><small>Dados do índice: <a href='/dados/icp.json'>dados/icp.json</a> · histórico permanente das conferências: <a href='/dados/icp_verificacoes.jsonl'>dados/icp_verificacoes.jsonl</a> ·
registro das coletas: <a href='/dados/icp_execucoes_historico.jsonl'>dados/icp_execucoes_historico.jsonl</a></small></p>
</main>
<script>(function(){{var b=document.getElementById('busca'),s=document.getElementById('fstatus'),v=document.getElementById('vazio');
function f(){{var q=(b.value||'').toLowerCase().normalize('NFD').replace(/[\\u0300-\\u036f]/g,''),st=s.value,n=0;
document.querySelectorAll('#tab tbody tr').forEach(function(r){{var ok=(!st||r.dataset.status===st)&&(!q||r.dataset.busca.normalize('NFD').replace(/[\\u0300-\\u036f]/g,'').indexOf(q)>=0);r.hidden=!ok;if(ok)n++}});v.hidden=n>0}}
b.addEventListener('input',f);s.addEventListener('change',f);var h=location.hash.match(/status=([a-z_]+)/);if(h){{s.value=h[1];f()}}}})();</script>"""
    html_ = cabecalho("Confiabilidade dos Dados — ICP | Cofre Aberto MS", "ICP — Índice de Confiabilidade Pública: quais bases do Cofre Aberto MS foram conferidas na fonte oficial, estão atualizadas e têm as contas consistentes.",
                      "/confiabilidade/", None, None, tipo="website").replace("</head>", est + "</head>") + corpo + RODAPE
    # a página principal do ICP é a aba do painel (com o menu lateral); /confiabilidade/ leva para lá
    del html_
    escreve_se_mudou(pasta / "index.html", "<!doctype html><html lang='pt-BR'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
                     "<title>Confiabilidade dos Dados — ICP | Cofre Aberto MS</title><meta name='description' content='ICP — Índice de Confiabilidade Pública do Cofre Aberto MS: o que foi conferido na fonte oficial, o que está atualizado e o que tem pendência.'>"
                     "<meta http-equiv='refresh' content='0; url=/cofre-aberto-ms.html#aba=confiabilidade'><link rel='canonical' href='https://cofreabertoms.com.br/cofre-aberto-ms.html#aba=confiabilidade'></head>"
                     "<body><p>Abrindo <a href='/cofre-aberto-ms.html#aba=confiabilidade'>Confiabilidade dos Dados (ICP)</a> no painel…</p>"
                     "<script>var m=location.hash.match(/status=([a-z_]+)/);location.replace('/cofre-aberto-ms.html#aba=confiabilidade');</script></body></html>")
    # uma página por base
    for fid, b in icp["bases"].items():
        d = b["dimensoes"]
        dimtab = "".join(f"<div class='bar'><span style='width:210px'>{e(icp['nomeDimensoes'][k])}</span><i><b style='width:{v or 0}%'></b></i><em>{'Não avaliado' if v is None else v}</em></div>" for k, v in d.items())
        uv = b["ultimaVerificacao"]
        comp = "".join(f"<tr><td>{e(str(c['item']))}</td><td class='n'>{brl(c['site']) if abs(c['site']) >= 100 else c['site']}</td><td class='n'>{brl(c['fonte']) if abs(c['fonte']) >= 100 else c['fonte']}</td>"
                       f"<td class='n'>{'0' if abs(c['diferenca']) < 0.005 else brl(c['diferenca'])}</td></tr>" for c in (uv or {}).get("comparados") or [])
        tst = "".join(f"<li class='{x['nivel']}'>{'✅' if x['nivel'] == 'ok' else '⚠️' if x['nivel'] == 'aviso' else '❌'} {e(x['texto'])}</li>" for x in b["testesItens"][:80])
        hv = "".join(f"<tr><td class='n'>{dt(h['em'])}</td><td>{e(h['resultado'])}</td><td class='n'>{h.get('conferidos', 0)}</td><td class='n'>{len(h.get('divergentes') or [])}</td>"
                     f"<td><small>{e(h.get('nota') or '')}</small></td></tr>" for h in b["historicoVerificacoes"][::-1])
        cor = "".join(f"<li><b>{dd(c['data'])}</b> — {e(c['texto'])}</li>" for c in b["correcoes"]) or "<li>Nenhuma correção registrada para esta base.</li>"
        div = "".join(f"<li>{dt(h['em'])}: {len(h.get('divergentes') or [])} item(ns) — {e(', '.join(str(x['item']) for x in (h.get('divergentes') or [])[:5]))}</li>" for h in b["divergencias"]) or "<li>Nenhuma divergência registrada nas conferências.</li>"
        pend = "".join(f"<li>{e(p)}</li>" for p in b["pendencias"]) or "<li>Nenhuma pendência.</li>"
        lim = "".join(f"<li>{e(x)}</li>" for x in b["limitacoes"]) or "<li>Nenhuma limitação específica registrada além das gerais da metodologia.</li>"
        verificado_txt = (f"Conferida em {dt(uv['em'])} ({e(uv.get('metodo') or '')}): resultado <b>{e(uv['resultado'])}</b>, {uv.get('conferidos', 0)} itens comparados."
                          if uv else "<b>Esta base ainda não foi conferida diretamente na fonte oficial.</b> As contas internas são testadas a cada coleta, mas isso prova só que os números fecham entre si.")
        corpo_b = f"""<main class='w'><p><small><a href='/cofre-aberto-ms.html#aba=confiabilidade'>Confiabilidade dos Dados</a> › base · <a href='/cofre-aberto-ms.html#aba=confiabilidade&p={fid}'>abrir no painel</a></small></p>
<h1>{e(b['nome'])}</h1><p>{selo(b)} <span style='font-size:1.4rem;font-weight:800;margin-left:10px'>{nota_txt(b['nota'])}</span><small> / 100</small></p>
<p class='lead'>{e(b['motivo'])}</p>
<h2>O que foi verificado</h2><p>{verificado_txt}</p>
{f"<div class='tw'><table><thead><tr><th>Item comparado</th><th class='n'>No site</th><th class='n'>Na fonte oficial</th><th class='n'>Diferença</th></tr></thead><tbody>{comp}</tbody></table></div>" if comp else ""}
<h2>Notas por dimensão</h2>{dimtab}
<h2>Transparência técnica</h2><dl>
<dt>Órgão / governo</dt><dd>{e(b['orgao'])}</dd>
<dt>Fonte oficial</dt><dd>{e(b['fonteOficial'] or '—')}{f" — <a href='{e(b['url'])}' target='_blank' rel='noopener'>{e(b['url'])}</a>" if b.get('url') else ''}</dd>
<dt>Origem (endpoint / arquivo)</dt><dd>{e(b['endpoint'])}</dd>
<dt>Método de coleta e processamento</dt><dd>{e(b['metodo'])}</dd>
<dt>Frequência de atualização</dt><dd>coleta a cada {b['intervaloColetaDias']} dia(s); atraso normal de publicação da fonte: até {b['atrasoNormalDias']} dias</dd>
<dt>Última coleta bem-sucedida</dt><dd>{dt(b['ultimaColeta'])} (última tentativa {dt(b['ultimaTentativa'])})</dd>
<dt>Período coberto</dt><dd>{e(b['periodoReferencia'])} · dado mais recente: {e(b['dadoMaisRecente'] or '—')}</dd>
<dt>Registros</dt><dd>{num(b['registros'])}{f" · total {brl(b['total'])}" if isinstance(b['total'], (int, float)) and b['total'] > 1000 else ''}</dd>
<dt>Identificador do registro original</dt><dd>{e(b['identificadorOriginal'])}</dd>
<dt>Arquivos de dados</dt><dd>{' · '.join(f"<a href='/{e(a)}'>{e(a)}</a>" for a in b['arquivos'])}</dd>
<dt>Última verificação oficial</dt><dd>{dt((uv or {}).get('em')) if uv else 'nunca'}</dd></dl>
{(lambda u: f"<h2>Última execução do robô</h2><p><b>{e(u.get('rotulo') or 'não registrada')}</b>" + (f" — coleta {e(str(u.get('runId')))}, {dt(u.get('inicio'))}" if u.get('runId') else "") + "</p>")(b.get('ultimaExecucao') or {})}
<h2>Pendências</h2><ul>{pend}</ul>
<h2>Testes matemáticos executados ({b['testes']['ok']} aprovados · {b['testes']['avisos']} avisos · {b['testes']['erros']} erros)</h2><ul style='font-size:.85rem'>{tst or '<li>Nenhum teste específico desta base.</li>'}</ul>
<h2>Histórico de verificações na fonte</h2>{f"<div class='tw'><table><thead><tr><th class='n'>Quando</th><th>Resultado</th><th class='n'>Itens</th><th class='n'>Divergentes</th><th>Observação</th></tr></thead><tbody>{hv}</tbody></table></div>" if hv else "<p>Nenhuma conferência registrada.</p>"}
<h2>Histórico de divergências</h2><ul>{div}</ul>
<h2>Histórico de correções</h2><ul>{cor}</ul>
<h2>Limitações conhecidas</h2><ul>{lim}</ul>
<p><small>O ICP é uma metodologia independente do Cofre Aberto MS, não uma certificação oficial. <a href='/cofre-aberto-ms.html#aba=confiabilidade'>Ver todas as bases</a> ·
<a href='/dados/icp.json'>dados do índice</a></small></p></main>"""
        (pasta / fid).mkdir(exist_ok=True)
        html_b = cabecalho(f"{b['nome']} — confiabilidade dos dados (ICP) | Cofre Aberto MS", f"Status de verificação, nota ICP, origem, testes e histórico de conferências da base {b['nome']}.",
                           f"/confiabilidade/{fid}/", None, None, tipo="website").replace("</head>", est + "</head>") + corpo_b + RODAPE
        escreve_se_mudou(pasta / fid / "index.html", html_b)
    # /monitoramento/ continua funcionando: leva para a página nova
    (ROOT / "monitoramento").mkdir(exist_ok=True)
    escreve_se_mudou(ROOT / "monitoramento" / "index.html", "<!doctype html><html lang='pt-BR'><head><meta charset='utf-8'><title>Confiabilidade dos Dados — Cofre Aberto MS</title>"
                     "<meta http-equiv='refresh' content='0; url=/cofre-aberto-ms.html#aba=confiabilidade'></head>"
                     "<body><p>Esta página mudou para <a href='/cofre-aberto-ms.html#aba=confiabilidade'>Confiabilidade dos Dados (ICP)</a>.</p>"
                     "<script>var h=location.hash.replace('#','');location.replace('/cofre-aberto-ms.html#aba=confiabilidade'+(h==='camara-cg'?'&p=camara':h?'&p='+h:''));</script></body></html>")


def sitemap():
    """Acrescenta /confiabilidade/ e as páginas das bases ao sitemap.xml (roda depois dos geradores que refazem o sitemap)."""
    from gerar_paginas_parlamentares import escreve_se_mudou
    sm, icp = ROOT / "sitemap.xml", gm.J("icp.json")
    if not (sm.exists() and icp):
        return
    hoje = icp["geradoEm"][:10]
    txt = re.sub(r"  <url><loc>[^<]*/(?:confiabilidade|monitoramento)/[^<]*</loc>.*?</url>\n", "", sm.read_text(encoding="utf-8"))
    novos = [f"  <url><loc>https://cofreabertoms.com.br/confiabilidade/{fid}/</loc><lastmod>{hoje}</lastmod><changefreq>daily</changefreq><priority>0.4</priority></url>" for fid in icp["bases"]]
    escreve_se_mudou(sm, txt.replace("</urlset>", "\n".join(novos) + "\n</urlset>"))
    print(f"✅ sitemap: {len(icp['bases'])} páginas de base do ICP")


if __name__ == "__main__":
    sitemap() if "--sitemap" in sys.argv else main()
