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

import html, json, os, re, sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import gerar_monitoramento as gm  # noqa: E402
import validar_fontes as vf  # noqa: E402  (hash dos registros para a janela de 30 dias)
import icp_metodologia as met  # noqa: E402  (registro das fontes, datas, classificação base)
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
STATUS = {  # rótulo, cor — metodologia 2.0: verde só com conferência ABRANGENTE na fonte (nível 3 ou 4)
    "verificado_reforcado": ("Conferência abrangente reforçada", "verde"), "verificado": ("Conferido na fonte (abrangente)", "verde"),
    "parcial": ("Conferido em parte na fonte", "amarelo"), "consistente": ("Só testes internos", "cinza"),
    "aguardando_fonte": ("Aguardando atualização da fonte", "amarelo"), "revisao_manual": ("Pendente de revisão manual", "amarelo"),
    "divergencia": ("Divergência identificada", "vermelho"), "falha_coleta": ("Falha na coleta", "vermelho"),
    "pendente": ("Sem evidência", "cinza")}
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
                if fid in bases_da_linha(l, j.get("bases") or [], j.get("origemLinhas")) and l not in out:
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
    # metodologia 2.0: P pela cobertura da conferência; I pela aprovação × profundidade dos testes
    hist_b = [h for h in hist_ver_global if h.get("base") == fid]
    if v and v.get("em") and not any(h.get("em") == v.get("em") for h in hist_b):
        hist_b.append(v)
    cob = met.cobertura(hist_b, AGORA, f.get("registros"), vf.hashes_atuais(fid))
    dims2 = dict(dims)
    dims2["P"] = met.dim_P(cob)
    dims2["I"], cats = met.dim_I(itens)
    return dims, {"ok": ok, "avisos": av, "erros": er, "itens": itens}, dims2, cob, cats, hist_b


hist_ver_global = []


def fmt_n(x):
    return f"{x:,}".replace(",", ".") if isinstance(x, int) else str(x)


def avisos_metodologicos(nivel, cob, classe, estado, f, dims, cats):
    """Explicações em linguagem simples do que a nota significa (nunca transformam ausência de evidência em erro ou acerto)."""
    a = []
    if classe == "falha_coleta" or estado == "fonte_indisponivel":
        a.append("A fonte oficial está indisponível ou a coleta falhou. A última versão válida dos dados foi preservada.")
    if classe == "aguardando_fonte":
        a.append("A coleta funciona, mas a fonte oficial não publicou dado novo. A coleta está desatualizada por causa da fonte.")
    if estado == "leitura_indisponivel":
        a.append("Não foi possível ler o registro do robô nesta coleta; o funcionamento da integração não foi confirmado.")
    if nivel <= 1:
        a.append("Os testes internos passaram, mas os dados ainda não foram conferidos na fonte oficial." if nivel == 1
                 else "Ainda não há testes nem conferência na fonte para esta base.")
    elif nivel == 2 and cob:
        if cob["granularidade"] == "registro":
            a.append(f"A conferência foi feita por amostragem: {fmt_n(cob['unidadesConferidas'])} de {fmt_n(cob['unidadesBase'])} registros "
                     f"({str(round(cob['percentual'], 2)).replace('.', ',')}%). Nem todos os registros foram examinados." if cob.get("percentual") is not None
                     else "A conferência foi feita por amostragem. Nem todos os registros foram examinados.")
        else:
            a.append(f"Só uma parte da base foi conferida: {fmt_n(cob['unidadesConferidas'])} de {fmt_n(cob['unidadesBase'] or '?')} {cob.get('unidade') or 'unidades'}."
                     + (f" Seleção: {cob['selecao']}." if cob.get("selecao") else ""))
    elif nivel >= 3 and cob and cob["granularidade"] == "unidade":
        a.append(f"Foram conferidos na fonte os totais de todas as unidades ({cob.get('unidade')}). Os registros individuais entram nesses totais, "
                 "mas não foram comparados um a um; erros que se compensam dentro de uma mesma unidade não seriam detectados.")
    if cob and not cob["calculavel"]:
        a.append("A quantidade total de registros não permite calcular a cobertura desta conferência.")
    if dims.get("I") is not None and len(cats) < met.N_CATEGORIAS:
        a.append(f"Os testes internos cobrem {len(cats)} de {met.N_CATEGORIAS} tipos de conferência ({', '.join(sorted(cats)) or 'nenhum'}).")
    if dims.get("F") is not None and dims["F"] < 50:
        a.append("Mais da metade das coletas recentes desta base falhou; a nota fica limitada a 50.")
    a.append(f"A nota considera apenas as evidências disponíveis até {AGORA:%d/%m/%Y}.")
    return a


def nota_base(dims, classe):
    """Nota da METODOLOGIA 1.0 (até 18/11/2026), mantida para comparação: média ponderada das dimensões avaliadas
    (mín. 4) com os tetos; None = não avaliado."""
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
    hist_ver_global[:] = hist_ver
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
        dims1, tst, dims, cob, cats, hist_b = nota_dimensoes(fid, {**f, "classe": classe}, ver, testes, rev, exec_hist, falhas_agora)
        nota_v1 = nota_base(dims1, classe)
        nivel = met.nivel(cob, dims["I"] is not None and tst["erros"] == 0, hist_b, AGORA)
        # status 2.0: problema conhecido primeiro; senão, o nível de evidência decide a cor (verde só com conferência abrangente)
        if classe in ("falha_coleta", "divergencia", "aguardando_fonte", "revisao_manual"):
            status = classe
        else:
            status = {4: "verificado_reforcado", 3: "verificado", 2: "parcial", 1: "consistente", 0: "pendente"}[nivel]
        nota = met.nota(dims, classe, cob, nivel)
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
        if dims["P"] is None:
            pend.append("sem conferência independente na fonte oficial nos últimos 30 dias")
        indep = (ver_auto.get(fid) or {}).get("independencia")
        lac = (ver_auto.get(fid) or {}).get("lacunas") or []
        if lac:
            pend.append(f"{len(lac)} registro(s) sem o dado no site para comparar com a fonte (lacuna da coleta) — não contam como conferidos")
        avisos = avisos_metodologicos(nivel, cob, classe, estado_atual, f, dims, cats)
        if indep:  # a reconsulta usa a mesma fonte da coleta: confirma a leitura, não é fonte independente
            avisos.insert(0, f"Reconsulta na {indep}.")
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
                      "pendencias": pend, "nivel": nivel, "nivelNome": met.NOME_NIVEL[nivel], "cobertura": cob,
                      "categoriasTeste": sorted(cats), "avisosMetodologicos": avisos, "notaV1": nota_v1,
                      "dimensoesV1": {k: dims1.get(k) for k in PESOS_DIM}}
    aval = [b for b in bases.values() if b["nota"] is not None]
    peso = sum(b["importancia"] for b in aval)
    geral = round(sum(b["nota"] * b["importancia"] for b in aval) / peso) if peso else None
    dim_geral = {}
    for k in PESOS_DIM:
        xs = [(b["dimensoes"][k], b["importancia"]) for b in bases.values() if b["dimensoes"][k] is not None]
        dim_geral[k] = round(sum(v * w for v, w in xs) / sum(w for _, w in xs)) if xs else None
    criticos = []  # o que a média geral não pode esconder
    for b in bases.values():
        # dimensão crítica: dado parado (A), integração falhando (F), sem rastro (R) ou conferência que contradiz/quase nada afirma (P).
        # Testes rasos (I baixa) aparecem nos avisos da base, mas não entram aqui — não são, sozinhos, um problema do dado.
        fracas = [NOME_DIM[k].lower() + f" {v:g}" for k, v in b["dimensoes"].items() if k != "I" and v is not None and v <= 40]
        if b["status"] in ("divergencia", "falha_coleta"):
            b["alerta"] = b["motivo"]
        elif b["importancia"] >= 2 and (fracas or (b["nota"] is not None and b["nota"] < 50)):
            b["alerta"] = "nota baixa em " + ", ".join(fracas) if fracas else f"nota {b['nota']}"
        elif b["importancia"] == 3 and b["status"] == "revisao_manual":
            b["alerta"] = b["motivo"]
        if b.get("alerta"):
            criticos.append(b)
    conhecidas = [b for b in bases.values() if b["cobertura"] and b["cobertura"]["calculavel"]]
    reg_base = sum(b["cobertura"]["registrosBase"] or 0 for b in conhecidas)
    reg_conf = sum(b["cobertura"]["registrosAbrangidos"] or 0 for b in conhecidas)
    todos_reg = sum(b["registros"] or 0 for b in bases.values() if isinstance(b.get("registros"), (int, float)))
    ind = {"total": len(bases), "verificadas": sum(1 for b in bases.values() if b["nivel"] >= 3),
           "conferenciaAbrangente": sum(1 for b in bases.values() if b["nivel"] >= 3),
           "conferenciaReforcada": sum(1 for b in bases.values() if b["nivel"] == 4),
           "conferenciaParcial": sum(1 for b in bases.values() if b["nivel"] == 2),
           "semVerificacaoOficial": sum(1 for b in bases.values() if b["nivel"] <= 1),
           "semEvidencia": sum(1 for b in bases.values() if b["nivel"] == 0),
           "consistenciaAprovada": sum(1 for b in bases.values() if b["testes"]["ok"] and not b["testes"]["erros"]),
           "aguardando": sum(1 for b in bases.values() if b["status"] == "aguardando_fonte"),
           "divergencias": sum(1 for b in bases.values() if b["status"] == "divergencia"),
           "falhas": sum(1 for b in bases.values() if b["status"] == "falha_coleta"),
           "revisaoManual": sum(1 for b in bases.values() if b["status"] == "revisao_manual"),
           "pendentesVerificacao": sum(1 for b in bases.values() if b["dimensoes"]["P"] is None),
           "naoAvaliadas": sum(1 for b in bases.values() if b["nota"] is None),
           "criticos": len(criticos), "porNivel": {str(n): sum(1 for b in bases.values() if b["nivel"] == n) for n in range(5)},
           # cobertura dos registros: só onde a base informa o total (denominador conhecido); senão, "não calculada"
           "coberturaRegistros": {"conferidos": reg_conf, "base": reg_base, "percentual": round(100 * reg_conf / reg_base, 2) if reg_base else None,
                                  "basesComDenominador": len(conhecidas), "registrosTodasAsBases": todos_reg,
                                  "percentualDoTotal": round(100 * reg_conf / todos_reg, 2) if todos_reg else None}}
    aval1 = [b for b in bases.values() if b["notaV1"] is not None]
    geral_v1 = round(sum(b["notaV1"] * b["importancia"] for b in aval1) / sum(b["importancia"] for b in aval1)) if aval1 else None
    icp = {"nome": "ICP — Índice de Confiabilidade Pública", "geradoEm": AGORA.strftime("%Y-%m-%dT%H:%M:%S"), "ultimaTentativa": mon["ultimaTentativa"],
           "nota": geral, "dimensoes": dim_geral, "nomeDimensoes": NOME_DIM, "pesosDimensoes": PESOS_DIM, "tetos": met.TETO,
           "metodologia": {"versao": met.VERSAO, "desde": met.DESDE, "documentacao": "ICP_DOCUMENTACAO.md",
                           "niveis": met.NOME_NIVEL, "confianca": met.CONFIANCA, "categoriasTeste": list(met.CATEGORIAS_TESTE),
                           "anterior": {"versao": "1.0", "nota": geral_v1, "formula": "média das dimensões avaliadas (mín. 4); tetos: divergência 40, falha 50, revisão 70, sem conferência 80; bases com menos de 4 dimensões fora da média"}},
           "aviso": f"A nota considera apenas as evidências disponíveis até {AGORA:%d/%m/%Y}.",
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
    if os.environ.get("GITHUB_RUN_ID") or "--registrar-historico" in sys.argv:  # só as gerações do robô entram no histórico
      with open(DADOS / "icp_notas_historico.jsonl", "a", encoding="utf-8") as h:  # histórico PERMANENTE das notas (só acrescenta)
        h.write(json.dumps({"em": icp["geradoEm"], "metodologia": met.VERSAO, "nota": geral, "notaMetodologia1": geral_v1,
                            "runId": exec_atual.get("runId"), "indicadores": {k: ind[k] for k in ("conferenciaAbrangente", "conferenciaParcial", "semVerificacaoOficial", "criticos")},
                            "bases": {k: {"nota": b["nota"], "notaV1": b["notaV1"], "nivel": b["nivel"], "status": b["status"],
                                          "cobertura": (b["cobertura"] or {}).get("percentual")} for k, b in bases.items()}},
                           ensure_ascii=False) + "\n")
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
    # a página principal do ICP é a aba do painel (com o menu lateral); /confiabilidade/ leva para lá
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
{evid_html(b, e, num, dt)}
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


def evid_html(b, e, num, dt):
    """Bloco 'Evidência que sustenta a nota' das páginas próprias de cada base."""
    c = b.get("cobertura")
    pct = lambda v: ("não calculada" if v is None else (f"{v:.2f}" if 0 < v < 1 else f"{round(v, 1):g}").replace(".", ",") + "%")
    linhas = [("Nível de evidência", f"<b>{b['nivel']} · {e(b['nivelNome'])}</b>"), ("Total de registros da base", num(b.get("registros")))]
    if c:
        linhas += [("Registros cobertos pela conferência", f"{num(c['registrosAbrangidos'])} de {num(c['registrosBase'])} — <b>{pct(c['percentual'])}</b>" if c["calculavel"] else "cobertura não calculada (total desconhecido)"),
                   ("Unidades conferidas", f"{num(c['unidadesConferidas'])} de {num(c['unidadesBase'])} {e(c.get('unidade') or '')}"),
                   ("Seleção", e(c.get("selecao") or "—")), ("Resultado", e(c["resultado"]) + (f" · {c['divergentes']} com divergência" if c["divergentes"] else " · nenhuma divergência")),
                   ("Data da conferência", dt(c["em"])), ("Fonte usada", e(c.get("fonteUrl") or "—")), ("Responsável", e(c.get("responsavel") or "—"))]
    else:
        linhas.append(("Conferência na fonte oficial", "nenhuma nos últimos 30 dias"))
    linhas.append(("Testes internos", f"{b['testes']['ok']} aprovados · {b['testes']['erros']} erros · tipos cobertos: {e(', '.join(b.get('categoriasTeste') or []) or 'nenhum')} ({len(b.get('categoriasTeste') or [])} de {met.N_CATEGORIAS})"))
    linhas.append(("Metodologia", f"ICP {met.VERSAO} · pela metodologia 1.0 a nota era {b['notaV1'] if b.get('notaV1') is not None else 'não avaliada'}"))
    return ("<h2>Evidência que sustenta a nota</h2><dl>" + "".join(f"<dt>{k}</dt><dd>{v}</dd>" for k, v in linhas) + "</dl><ul>"
            + "".join(f"<li>{e(a)}</li>" for a in b.get("avisosMetodologicos") or []) + "</ul>")


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
