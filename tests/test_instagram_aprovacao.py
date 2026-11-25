#!/usr/bin/env python3
"""
Cofre Aberto MS — Instagram: modo aprovação e regras de conteúdo (casos simulados, sem rede)

25/11/2026: nas primeiras 4 semanas, rascunho numa issue e publicação só com o rótulo "aprovado"; só temas com a base
"confere" no ICP; nenhum nome em sinal de atenção ou com divergência sem resposta; no máximo 1 post por dia.
Uso: python3 tests/test_instagram_aprovacao.py   (código 1 se algum teste falhar)
"""
import io, json, os, sys, tempfile
from contextlib import redirect_stdout
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import instagram_aprovacao as ap  # noqa: E402
import gerar_posts_instagram as gp  # noqa: E402
import publicar_instagram as pi  # noqa: E402

oks, erros = [], []
check = lambda c, m: (oks if c else erros).append(m)
rot = lambda *n: [{"name": x} for x in n]

# modo aprovação
check(ap.decidir([], aprovacao=True) == ("gerar_rascunho", None), "sem rascunho aberto: gera o rascunho (não publica)")
check(ap.decidir([{"number": 7, "labels": rot("instagram-rascunho")}], aprovacao=True) == ("aguardar", 7), "rascunho esperando: não gera outro")
check(ap.decidir([{"number": 7, "labels": rot("instagram-rascunho", "aprovado")}], aprovacao=True) == ("publicar_aprovado", 7), "com o rótulo 'aprovado': publica")
check(ap.decidir([], aprovacao=False) == ("publicar_direto", None), "depois das 4 semanas: publica direto")
cfg = json.load(open(ROOT / "instagram" / "config.json", encoding="utf-8"))
check(cfg["aprovacaoAte"] == "2026-12-23" and ap.em_aprovacao(date(2026, 11, 26)) and not ap.em_aprovacao(date(2026, 12, 24)), "aprovação até 23/12/2026 (4 semanas)")

# regras de conteúdo
icp = {"bases": {"shows": {"status": "verificado", "ultimaVerificacao": {"resultado": "confere", "em": "2026-11-25T10:00"}},
                 "obras": {"status": "divergencia", "ultimaVerificacao": {"resultado": "diverge"}},
                 "camara": {"status": "consistente", "ultimaVerificacao": {}},
                 "supersalarios": {"status": "parcial", "ultimaVerificacao": {"resultado": "confere", "em": "2026-11-25"}}}}
aud = {"sinais": [{"quem": "Fulano de Tal", "titulo": "sinal"}]}
conf = {"divergenciasFonte": [{"nome": "Ademar De Souza Freitas", "orgaoId": "trt24", "mes": "08/2026"}]}
esc = {"pedidos": [{"orgaoId": "trt24", "mes": "08/2026", "protocolo": None, "resposta": None}]}
gp.carregar = lambda n: {"icp.json": icp, "auditoria.json": aud, "verificacao/conferencia_supersalarios.json": conf,
                         "../config/esclarecimentos_fonte.json": esc}.get(n, {})
check(gp.tema_liberado("shows")[0], "Shows (verificado, confere) liberado")
check(not gp.tema_liberado("obras")[0], f"Obras com divergência no ICP: bloqueado ({gp.tema_liberado('obras')[1]})")
check(not gp.tema_liberado("vereadores")[0], "Vereadores sem conferência 'confere' no ICP: bloqueado")
b = gp.nomes_bloqueados()
check("FULANO DE TAL" in b and "ADEMAR DE SOUZA FREITAS" in b, "bloqueados: pessoa em sinal de atenção e divergência sem resposta")
p, m = gp.aplicar_regras({"lista": [("Artista A", "", ""), ("Fulano de Tal", "", ""), ("Artista B", "", "")]})
check(p and [x[0] for x in p["lista"]] == ["Artista A", "Artista B"] and "1 item" in m, "nome bloqueado sai da lista")
p, m = gp.aplicar_regras({"lista": [("Fulano de Tal", "", ""), ("Artista B", "", "")]})
check(p is None, "o citado na legenda está bloqueado: o tema é pulado")
esc["pedidos"][0]["resposta"] = "respondido em 10/12"
check("ADEMAR DE SOUZA FREITAS" not in gp.nomes_bloqueados(), "com resposta ao pedido de esclarecimento, o nome deixa de ser bloqueado")

# publicador: 1 por dia e aprovação
tmp = Path(tempfile.mkdtemp())
pi.PASTA = tmp
(tmp / "proximo.json").write_text(json.dumps({"tema": "shows", "imagens": ["b.jpg"], "urls": [], "legenda": "x"}))
os.environ["IG_TOKEN"] = "x"
(tmp / "historico.json").write_text(json.dumps({"publicados": [{"imagens": ["a.jpg"], "data": datetime.now().strftime("%Y-%m-%dT%H:%M:%S")}]}))
buf = io.StringIO()
with redirect_stdout(buf):
    pi.main()
check("no máximo 1 por dia" in buf.getvalue(), "já houve post hoje: não publica outro")
(tmp / "historico.json").write_text(json.dumps({"publicados": []}))
ap.em_aprovacao = lambda hoje=None: True
os.environ.pop("IG_APROVADO", None)
buf = io.StringIO()
with redirect_stdout(buf):
    pi.main()
check("modo aprovação" in buf.getvalue(), "modo aprovação sem IG_APROVADO=1: não publica")

# rascunho sem resposta por 3 dias: expira
from datetime import timezone, timedelta  # noqa: E402
agora = datetime(2026, 11, 29, 16, 0, tzinfo=timezone.utc)
ab = [{"number": 1, "labels": rot("instagram-rascunho"), "createdAt": "2026-11-26T15:50:00Z"},
      {"number": 2, "labels": rot("instagram-rascunho"), "createdAt": "2026-11-27T15:50:00Z"},
      {"number": 3, "labels": rot("instagram-rascunho", "aprovado"), "createdAt": "2026-11-20T15:50:00Z"}]
check([i["number"] for i in ap.expirados(ab, agora)] == [1], "rascunho há 3 dias sem aprovação expira; o de 2 dias e o aprovado não")

# checagem diária da chave (só leitura)
os.environ["IG_TOKEN"] = "x"
pi.conta = lambda t: (pi.API_FB, "17841400153468200", "cofre_abertoms", "facebook")
buf = io.StringIO()
with redirect_stdout(buf):
    r = pi.conferir()
check(r == 0 and "✅ chave do Instagram válida: @cofre_abertoms" in buf.getvalue(), "chave válida: ✅ com a conta")
def recusa(t):
    raise RuntimeError("Error validating access token: Session has expired")
pi.conta = recusa
buf = io.StringIO()
with redirect_stdout(buf):
    r = pi.conferir()
check(r == 1 and "❌ chave do Instagram recusada pela Meta" in buf.getvalue(), "Meta recusou: ❌ e o job falha (GitHub avisa)")

# formatação brasileira
check(gp.mil(1074) == "1.074" and gp.mil(2701) == "2.701" and gp.mil(12) == "12", "contagens com separador de milhar (1.074)")
check(gp.brl(1500000) == "R$ 1.500.000" and gp.brl(10.29, True) == "R$ 10,29", "R$ no padrão brasileiro")
src = (ROOT / "scripts/gerar_posts_instagram.py").read_text(encoding="utf-8")
check("{d['totalShows']}" not in src and "{mil(d['totalShows'])}" in src, "a legenda de Shows usa o separador (1.074 shows)")

wf = (ROOT / ".github/workflows/instagram.yml").read_text(encoding="utf-8")
check("publicar_instagram.py --conferir" in wf, "workflow confere a chave todo dia, antes do resto")
check("types: [labeled]" in wf and "instagram_aprovacao.py abrir" in wf and "IG_APROVADO" in wf, "workflow: issue de rascunho, rótulo dispara a publicação")
for e in erros:
    print("❌", e)
print(f"✅ {len(oks)} checagens OK · ❌ {len(erros)} erros")
sys.exit(1 if erros else 0)
