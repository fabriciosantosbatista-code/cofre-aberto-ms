#!/usr/bin/env python3
"""
Cofre Aberto MS — registro do que cada robô de coleta fez nesta execução (insumo do ICP)

Para cada job de coleta do workflow "Atualizar dados diariamente" (atualizar.yml), lê pela API do GitHub:
  - a conclusão do job e de cada etapa (steps), início e fim;
  - o LOG do job, e extrai avisos (⚠️, ##[warning]), erros (❌, ##[error], Traceback, Error/Exception) e falhas de
    etapa ("… falhou — dados anteriores mantidos", que os coletores imprimem com "|| echo" para não derrubar a coleta).

Por que o log importa: o job termina "success" mesmo quando um coletor falha (o "|| echo" engole o erro). Só o log mostra.

AUSÊNCIA DE INFORMAÇÃO NÃO É AUSÊNCIA DE PROBLEMA. Se a API não responde, o token não tem permissão, o log não existe
ou veio vazio/ilegível, o job fica com leitura "indisponivel"/"vazio" e avisos/erros = None (não 0), e o estado é
"leitura_indisponivel". O ICP trata isso como não verificado, nunca como coleta sem problemas.

Como o log é baixado: GET /repos/{repo}/actions/jobs/{id}/logs responde 302 com um link temporário para o
armazenamento do GitHub. O link é seguido SEM o cabeçalho de autorização (o armazenamento recusa o token do GitHub).
Antes, o "gh api" falhava em silêncio no robô e o registro saía com "0 avisos" em todos os jobs.

Estados de cada job (e de cada base que ele coleta):
  sem_avisos            coleta concluída sem avisos
  com_avisos            coleta concluída com avisos
  com_erros             coleta concluída, mas o log tem erros
  parcial               alguma etapa falhou ou um coletor falhou e manteve o dado anterior
  falha_execucao        o job falhou, foi cancelado ou estourou o tempo
  leitura_indisponivel  não foi possível ler o log (API, permissão, log vazio ou inexistente)
  fonte_indisponivel    (por base) o log mostra que a fonte não respondeu (conexão recusada, timeout, HTTP 5xx)
  sem_publicacao_nova   (por base) a coleta funcionou, mas a fonte não publicou dado novo (monitoramento)

Saídas: dados/icp_execucoes.json (esta execução) e uma linha em dados/icp_execucoes_historico.jsonl (só acrescenta).
Uso no robô: GITHUB_REPOSITORY, GITHUB_RUN_ID e GH_TOKEN no ambiente.
       python3 scripts/registrar_execucao.py --run ID --comparar   lê uma execução e compara com o log bruto (não grava)
"""

import json, os, re, subprocess, sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from mascarar_cpf import CPF, mascarar_nomes  # noqa: E402

ROOT = Path(__file__).parent.parent
DADOS = ROOT / "dados"
API = os.environ.get("GITHUB_API_URL", "https://api.github.com")
WORKFLOW = "atualizar.yml"
# job do workflow → bases do ICP que ele coleta
JOB_BASES = {
    "coletar_dados": ["deputados", "deputados-estaduais", "senadores", "prefeitura", "camaras-ms", "deputados-brasil", "senado-brasil"],
    "coletar_verba_camara": ["camara"],
    "coletar_contratos_cg": ["contratos-cg", "shows", "alugueis"],
    "coletar_governo_ms": ["governo-ms", "obras"],
    "coletar_fontes_federais": ["eleicoes", "presidencia", "stf", "votacoes", "producao", "arrecadacao"],
    "coletar_emendas_alems": ["emendas"],
    "coletar_tjms": ["judiciario", "supersalarios"], "coletar_trt24": ["judiciario"], "coletar_tre_ms": ["judiciario"],
    "coletar_fontes_auditoria": ["auditoria", "supersalarios"],
}
# a qual base pertence uma linha de aviso (pela palavra-chave); sem palavra-chave, vale para todas as bases do job
BASE_TXT = [("camara", r"relatórios|Câmara Municipal de Campo Grande|45\.225\.6\.93|gabinete|verba indenizat"),
            ("camaras-ms", r"Sonora|[Cc]âmara de (?!Campo Grande)|[Cc]âmaras|camaras/|Fiorilli|SAPL"),
            ("judiciario", r"TJMS|TRT|TRE"), ("supersalarios", r"teto|supersal|zerados"), ("prefeitura", r"Prefeitura|SIG"),
            ("governo-ms", r"Estado|sgi\.ms"), ("emendas", r"emendas|CGU"), ("deputados-estaduais", r"ALEMS|Assembleia"),
            ("deputados", r"Câmara dos Deputados|CEAP|camara\.leg"), ("senadores", r"Senado"), ("shows", r"show"),
            ("alugueis", r"alugu|locaç|PNCP"), ("auditoria", r"pagadores|Receita|CEIS|CNEP|sinais")]
# linhas que são o eco do comando do script (não a saída dele)
ECO = re.compile(r"\x1b\[36;1m|\[36;1m|echo \"|\|\| echo|^\s*#|^##\[group\]Run |^shell: ")
AVISO = re.compile(r"⚠️|##\[warning\]|::warning")
ERRO = re.compile(r"❌|##\[error\]|::error|Traceback \(most recent call last\)|^\s*\w*(Error|Exception):|\bErro\b:")
FALHA = re.compile(r"falhou|não rodou|interrompid|mantid[oa]s? (os |as )?(dados |valores )?anterior|mantendo (os )?dados anteriores|"
                   r"dados? anteriores? mantid|(dados|valores) da coleta anterior|mantém o anterior", re.I)
# avisos da própria plataforma do GitHub (ex.: versão do Node das actions): ficam registrados à parte, não contam para a base
PLATAFORMA = re.compile(r"Node\.js \d+ (is|are) deprecated|deprecated.*(set-output|save-state)|actions are deprecated", re.I)
FONTE_FORA = re.compile(r"Connection (refused|reset|aborted)|timed? ?out|Timeout|Max retries|Name or service not known|"
                        r"Temporary failure in name|HTTP ?5\d\d|\b50[234]\b|indispon|não respondeu|fora do ar|sem resposta", re.I)
TS = re.compile(r"^﻿?\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z ?")
RUIM = {"falha_execucao", "parcial", "com_erros", "fonte_indisponivel"}
BOM = {"sem_avisos", "com_avisos", "sem_publicacao_nova"}
DESCONHECIDO = {"leitura_indisponivel"}


# ─────────────────────────────── API do GitHub ───────────────────────────────
def _token():
    return os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")


def http_get(url, autenticar=True, timeout=90):
    """(status, bytes, erro). Segue redirecionamento à mão, sem levar o token para o outro servidor."""
    import requests
    h = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "cofre-aberto-ms-icp"}
    if autenticar and _token():
        h["Authorization"] = f"Bearer {_token()}"
    try:
        r = requests.get(url, headers=h, timeout=timeout, allow_redirects=False)
        saltos = 0
        while r.status_code in (301, 302, 303, 307, 308) and saltos < 3:
            loc = r.headers.get("Location")
            if not loc:
                return r.status_code, None, "redirecionamento sem destino"
            r = requests.get(loc, headers={"User-Agent": h["User-Agent"]}, timeout=timeout, allow_redirects=False)
            saltos += 1
        if r.status_code != 200:
            return r.status_code, None, f"HTTP {r.status_code}: {r.text[:160]!r}"
        return 200, r.content, None
    except Exception as e:  # rede, DNS, timeout
        return None, None, f"{type(e).__name__}: {str(e)[:160]}"


def ler_jobs(repo, run, get=http_get):
    """Lista de jobs da execução (todas as páginas) ou (None, erro)."""
    jobs, pag = [], 1
    while True:
        st, corpo, erro = get(f"{API}/repos/{repo}/actions/runs/{run}/jobs?per_page=100&page={pag}")
        if erro:
            return None, erro
        try:
            d = json.loads(corpo)
        except ValueError:
            return None, "resposta da API de jobs não é JSON"
        jobs += d.get("jobs") or []
        if len(jobs) >= (d.get("total_count") or 0) or not d.get("jobs"):
            return jobs, None
        pag += 1


def ler_log(repo, job_id, get=http_get):
    """(texto, leitura, detalhe): leitura = ok | vazio | indisponivel."""
    st, corpo, erro = get(f"{API}/repos/{repo}/actions/jobs/{job_id}/logs")
    if erro:
        return None, "indisponivel", erro
    try:
        texto = corpo.decode("utf-8")
    except (UnicodeDecodeError, AttributeError):
        return None, "indisponivel", "log em formato inesperado (não é texto UTF-8)"
    if not texto.strip():
        return "", "vazio", "o GitHub devolveu um log vazio"
    return texto, "ok", None


# ─────────────────────────────── leitura do log ───────────────────────────────
def limpa(l):
    l = TS.sub("", l.rstrip("\r"))
    l = CPF.sub(lambda m: f"***.{m.group(2)}.{m.group(3)}-**", l)
    return mascarar_nomes(l)[:300]


def analisar_log(texto):
    """Extrai avisos, erros, falhas de coletor e sinais de fonte fora do ar. Formato inesperado = poucas linhas
    reconhecíveis: devolve formatoReconhecido=False para o chamador não tratar como 'sem avisos'."""
    avisos, erros, falhas, fora, plataforma = [], [], [], [], []
    linhas = texto.splitlines()
    com_ts = sum(1 for l in linhas[:200] if TS.match(l))
    reconhecido = bool(linhas) and (com_ts >= min(5, len(linhas)) * 0.5 or any("##[group]" in l for l in linhas[:400]))
    for bruta in linhas:
        if ECO.search(bruta):
            continue
        l = limpa(bruta)
        if not l.strip():
            continue
        e_erro, e_aviso = bool(ERRO.search(l)), bool(AVISO.search(l))
        if (e_aviso or e_erro) and PLATAFORMA.search(l):
            if l not in plataforma:
                plataforma.append(l)
            continue
        if (e_aviso or e_erro) and FALHA.search(l):
            if l not in falhas:
                falhas.append(l)
        if e_erro and l not in erros:
            erros.append(l)
        elif e_aviso and l not in avisos:
            avisos.append(l)
        if (e_aviso or e_erro) and FONTE_FORA.search(l) and l not in fora:
            fora.append(l)
    return {"avisos": avisos, "erros": erros, "falhas": falhas, "fonteFora": fora, "plataforma": plataforma, "linhas": len(linhas), "formatoReconhecido": reconhecido}


def etapas(job):
    out = {"concluidas": [], "falharam": [], "canceladas": [], "puladas": []}
    for s in job.get("steps") or []:
        c = s.get("conclusion")
        k = "concluidas" if c == "success" else "falharam" if c == "failure" else "canceladas" if c == "cancelled" else "puladas" if c == "skipped" else None
        if k:
            out[k].append(s.get("name"))
    return out


def classificar(job, leitura, analise):
    c = job.get("conclusion")
    if c in ("failure", "cancelled", "timed_out", "startup_failure") or job.get("status") not in (None, "completed"):
        return "falha_execucao", f"o job terminou com '{c or job.get('status')}'"
    if leitura != "ok":
        return "leitura_indisponivel", "não foi possível ler o log deste job"
    if not analise["formatoReconhecido"]:
        return "leitura_indisponivel", "o log veio num formato inesperado"
    if analise["falhas"] or etapas(job)["falharam"]:
        return "parcial", "uma etapa ou um coletor falhou e o dado anterior foi mantido"
    if analise["erros"]:
        return "com_erros", f"{len(analise['erros'])} erro(s) no log"
    if analise["avisos"]:
        return "com_avisos", f"{len(analise['avisos'])} aviso(s) no log"
    return "sem_avisos", "coleta concluída sem avisos"


def bases_da_linha(l, bases_job):
    alvo = [b for b, rx in BASE_TXT if re.search(rx, l) and b in bases_job]
    return alvo or list(bases_job)


def estado_bases(nome, estado, analise, monit):
    """Estado de cada base coletada pelo job."""
    bases = JOB_BASES.get(nome, [])
    out = {}
    for b in bases:
        if estado in ("falha_execucao", "leitura_indisponivel"):
            out[b] = estado
            continue
        meus = lambda xs: [l for l in xs if b in bases_da_linha(l, bases)]
        if meus(analise["fonteFora"]) and (meus(analise["falhas"]) or meus(analise["erros"])):
            out[b] = "fonte_indisponivel"
        elif meus(analise["falhas"]):
            out[b] = "parcial"
        elif meus(analise["erros"]):
            out[b] = "com_erros"
        elif ((monit.get(b) or {}).get("classe")) == "aguardando_fonte":
            out[b] = "sem_publicacao_nova"
        elif meus(analise["avisos"]):
            out[b] = "com_avisos"
        else:
            out[b] = "sem_avisos"
    return out


# ─────────────────────────────── contexto da coleta ───────────────────────────────
def registros_por_base():
    try:
        import gerar_monitoramento as gm
    except Exception:
        return {}
    out = {}
    for fid, reg in gm.FONTES.items():
        try:
            out[fid] = reg[7]()
        except Exception:
            out[fid] = None
    return out


def arquivos_atualizados():
    try:
        p = subprocess.run(["git", "-C", str(ROOT), "status", "--porcelain", "--", "dados/"], capture_output=True, text=True, timeout=60)
        return sorted(l[3:].strip() for l in p.stdout.splitlines() if l.strip())
    except Exception:
        return None


def resultado_testes():
    out = {}
    for nome, arq in (("integridade", "icp_testes_integridade.json"), ("variacoes", "icp_testes_variacoes.json"), ("cpf", "icp_testes_cpf.json")):
        try:
            d = json.load(open(DADOS / arq, encoding="utf-8"))
            out[nome] = {k: d.get(k) for k in ("ok", "avisos", "erros")}
        except Exception:
            out[nome] = None  # não rodou nesta coleta
    return out


def J(nome):
    try:
        return json.load(open(DADOS / nome, encoding="utf-8"))
    except Exception:
        return {}


# ─────────────────────────────── principal ───────────────────────────────
def montar_registro(repo, run, get=http_get):
    jobs, erro = ler_jobs(repo, run, get)
    monit = (J("monitoramento.json").get("fontes") or {})
    reg = {"runId": str(run), "workflow": WORKFLOW, "registradoEm": datetime.now(__import__("zoneinfo").ZoneInfo("America/Campo_Grande")).strftime("%Y-%m-%dT%H:%M:%S"), "jobs": {}, "bases": {}}
    if jobs is None:
        reg.update({"leitura": "indisponivel", "erroLeitura": erro, "bases": {b: "leitura_indisponivel" for bs in JOB_BASES.values() for b in bs}})
        return reg
    inicio = min((j.get("started_at") for j in jobs if j.get("started_at")), default=None)
    fim = max((j.get("completed_at") for j in jobs if j.get("completed_at")), default=None)
    leituras = []
    for j in jobs:
        nome = j.get("name")
        if nome not in JOB_BASES:
            continue
        if j.get("conclusion") == "skipped":
            texto, leitura, detalhe = None, "sem_log", "job pulado"
        else:
            texto, leitura, detalhe = ler_log(repo, j["id"], get)
        analise = analisar_log(texto) if texto else {"avisos": [], "erros": [], "falhas": [], "fonteFora": [], "plataforma": [], "linhas": 0, "formatoReconhecido": False}
        estado, motivo = classificar(j, leitura, analise)
        conhecido = leitura == "ok" and analise["formatoReconhecido"]
        leituras.append(conhecido)
        reg["jobs"][nome] = {
            "estado": estado, "motivo": motivo, "conclusao": j.get("conclusion"), "inicio": j.get("started_at"), "fim": j.get("completed_at"),
            "bases": JOB_BASES[nome], "leitura": leitura if leitura != "ok" or analise["formatoReconhecido"] else "formato_inesperado",
            "erroLeitura": detalhe if not conhecido else None, "linhasLog": analise["linhas"],
            "nAvisos": len(analise["avisos"]) if conhecido else None, "nErros": len(analise["erros"]) if conhecido else None,
            "nFalhas": len(analise["falhas"]) if conhecido else None,
            "avisos": analise["avisos"][:25], "erros": analise["erros"][:25], "falhas": analise["falhas"][:15], "fonteFora": analise["fonteFora"][:10],
            "avisosPlataforma": analise["plataforma"][:3],
            "etapas": {k: v for k, v in etapas(j).items() if v and k != "concluidas"} | {"nConcluidas": len(etapas(j)["concluidas"])},
        }
        for b, e in estado_bases(nome, estado, analise, monit).items():
            # uma base coletada por mais de um job fica com o pior estado
            ordem = ["leitura_indisponivel", "sem_avisos", "sem_publicacao_nova", "com_avisos", "com_erros", "parcial", "fonte_indisponivel", "falha_execucao"]
            if b not in reg["bases"] or ordem.index(e) > ordem.index(reg["bases"][b]):
                reg["bases"][b] = e
    reg["inicio"], reg["fim"] = inicio, fim
    reg["leitura"] = "ok" if leituras and all(leituras) else "parcial" if any(leituras) else "indisponivel"
    return reg


def main():
    args = sys.argv[1:]
    repo = os.environ.get("GITHUB_REPOSITORY")
    run = args[args.index("--run") + 1] if "--run" in args else os.environ.get("GITHUB_RUN_ID")
    if not (repo and run):
        print("ℹ️ fora do robô (sem GITHUB_RUN_ID) — registro de execução não gerado")
        return 0
    reg = montar_registro(repo, run)
    reg["registros"] = registros_por_base()
    reg["arquivosAtualizados"] = arquivos_atualizados()
    reg["testes"] = resultado_testes()
    reg["publicacao"] = J("icp_publicacao.json") or None
    if (reg["publicacao"] or {}).get("resultado") == "bloqueado":  # a base falhou nos testes e a coleta não foi publicada
        ordem = ["leitura_indisponivel", "sem_avisos", "sem_publicacao_nova", "com_avisos", "com_erros", "parcial", "fonte_indisponivel", "falha_execucao"]
        for b in reg["publicacao"].get("basesAfetadas") or []:
            if b in reg["bases"] and ordem.index(reg["bases"][b]) < ordem.index("com_erros"):
                reg["bases"][b] = "com_erros"
    if "--comparar" in args:
        return comparar(repo, reg)
    (DADOS / "icp_execucoes.json").write_text(json.dumps(reg, ensure_ascii=False, indent=1), encoding="utf-8")
    linha = {"runId": reg["runId"], "inicio": reg.get("inicio"), "fim": reg.get("fim"), "leitura": reg["leitura"], "bases": reg["bases"],
             "publicacao": (reg["publicacao"] or {}).get("resultado"),
             "jobs": {k: {"estado": v["estado"], "conclusao": v["conclusao"], "nAvisos": v["nAvisos"], "nErros": v["nErros"], "avisos": v["avisos"][:5]}
                      for k, v in reg["jobs"].items()}}
    with open(DADOS / "icp_execucoes_historico.jsonl", "a", encoding="utf-8") as h:
        h.write(json.dumps(linha, ensure_ascii=False) + "\n")
    resumo = ", ".join(f"{k} {v['estado']} ({'?' if v['nAvisos'] is None else v['nAvisos']} avisos, {'?' if v['nErros'] is None else v['nErros']} erros)" for k, v in reg["jobs"].items())
    icone = "✅" if reg["leitura"] == "ok" else "⚠️"
    print(f"{icone} execução {run} — leitura dos logs: {reg['leitura']}" + (f" ({reg.get('erroLeitura')})" if reg.get("erroLeitura") else "") + f" · {resumo}")
    return 0


def comparar(repo, reg):
    """Confere o que foi registrado com o log bruto: conta à mão as linhas ⚠️/❌ de cada job."""
    jobs, _ = ler_jobs(repo, reg["runId"])
    print(f"execução {reg['runId']} · leitura {reg['leitura']}" + (f" · {reg.get('erroLeitura')}" if reg.get("erroLeitura") else ""))
    divergentes = 0
    for j in jobs or []:
        if j["name"] not in reg["jobs"]:
            continue
        r = reg["jobs"][j["name"]]
        texto, leitura, det = ler_log(repo, j["id"])
        bruto = [l for l in (texto or "").splitlines() if ("⚠️" in l or "❌" in l) and not ECO.search(l)]
        bruto_unicos = len({limpa(l) for l in bruto})
        reg_n = (r["nAvisos"] or 0) + (r["nErros"] or 0) if r["nAvisos"] is not None else None
        ok = reg_n is not None and reg_n >= bruto_unicos
        divergentes += not ok
        print(f"  {'✅' if ok else '❌'} {j['name']:26s} estado {r['estado']:20s} registrado {reg_n} · linhas ⚠️/❌ distintas no log bruto {bruto_unicos} · leitura {r['leitura']}")
    return 1 if divergentes else 0


if __name__ == "__main__":
    sys.exit(main())
