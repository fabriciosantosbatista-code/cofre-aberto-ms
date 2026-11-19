#!/usr/bin/env python3
"""
Cofre Aberto MS — exceção temporária ao alerta "Prefeitura CG sem empenho novo" (scripts/verificar_dados.py +
config/excecoes_alertas.json): vira aviso com o texto do pedido de LAI e volta a ser erro sozinha.

Uso: python3 tests/test_excecoes_alertas.py   (código 1 se algum teste falhar)
"""
import json, sys, tempfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import verificar_dados as vd  # noqa: E402

oks, falhas = [], []


def check(c, m):
    (oks if c else falhas).append(m)


ERRO = "**Prefeitura CG**: empenho mais recente é de 2026-10-02 (47 dias, limite 45) — a fonte pode ter parado"
cfg = Path(tempfile.mkdtemp()) / "excecoes.json"
cfg.write_text(json.dumps({"prefeitura_empenhos": {"fonteParadaDesde": "2026-10-02", "laiProtocoladoEm": "20/11/2026",
                                                    "laiNumero": "123", "validoAte": "2026-12-19"}}), encoding="utf-8")
vd.EXCECOES = cfg


def roda(hoje, ultimo="2026-10-02", outros_erros=(), outros_avisos=()):
    vd.erros[:], vd.avisos[:] = [ERRO, *outros_erros], list(outros_avisos)
    vd.ULTIMO_EMPENHO = ultimo
    vd.aplicar_excecoes(hoje)
    return list(vd.erros), list(vd.avisos)


e, a = roda(date(2026, 11, 19))
check(ERRO not in e and any("fonte parada desde 02/10/2026; pedido de LAI protocolado em 20/11/2026 (nº 123)" in x for x in a),
      "dentro do prazo, fonte ainda parada em 02/10 e sem outro alerta → aviso com o texto do pedido de LAI")
e, a = roda(date(2026, 12, 19))
check(ERRO not in e, "no último dia da exceção (19/12) ainda é aviso")
e, a = roda(date(2026, 12, 20))
check(ERRO in e, "30 dias depois (20/12) → volta a ser erro")
e, a = roda(date(2026, 11, 25), ultimo="2026-10-20")
check(len(e) == 1 and e[0] == ERRO, "a Prefeitura voltou a publicar e parou de novo (empenho mais recente mudou) → erro")
e, a = roda(date(2026, 11, 25), outros_erros=("**Prefeitura CG**: total pago caiu de R$ 10 para R$ 5 — voltou a ler um arquivo antigo?",))
check(ERRO in e, "outro alerta da Prefeitura (erro) → continua erro")
e, a = roda(date(2026, 11, 25), outros_avisos=("**Aditivos da Prefeitura**: última coleta é de ... — a fonte pode ter parado",))
check(ERRO in e, "outro alerta da Prefeitura (aviso de aditivos) → continua erro")
e, a = roda(date(2026, 11, 25), outros_avisos=("**Contratos/licitações CG**: última coleta é de ...",))
check(ERRO in e, "outro alerta da Prefeitura (contratos/licitações CG) → continua erro")
e, a = roda(date(2026, 11, 25), outros_avisos=("**Câmara de Sonora**: última coleta ...", "**Câmara CG**: x"))
check(ERRO not in e, "alerta de outra fonte (Câmaras) não derruba a exceção")
for em, num in ((None, None), ("DD/MM/AAAA", "XXXX"), ("20/11/2026", ""), ("", "123")):
    cfg2 = Path(tempfile.mkdtemp()) / "excecoes.json"
    cfg2.write_text(json.dumps({"prefeitura_empenhos": {"fonteParadaDesde": "2026-10-02", "laiProtocoladoEm": em, "laiNumero": num,
                                                         "validoAte": "2026-12-19"}}), encoding="utf-8")
    vd.EXCECOES = cfg2
    e, a = roda(date(2026, 11, 19))
    check(any("fonte parada desde 02/10/2026; pedido de acesso à informação em preparação" in x for x in a)
          and not any("DD/MM" in x or "XXXX" in x for x in a), f"data/número do pedido não preenchidos ({em!r}, {num!r}) → 'em preparação', nunca o modelo")
vd.EXCECOES = Path(tempfile.mkdtemp()) / "nao_existe.json"
e, a = roda(date(2026, 11, 19))
check(ERRO in e, "sem arquivo de configuração → erro")
real = json.load(open(ROOT / "config" / "excecoes_alertas.json", encoding="utf-8"))["prefeitura_empenhos"]
check(real["validoAte"] == "2026-12-19" and real["fonteParadaDesde"] == "2026-10-02", "configuração: 30 dias a partir de 19/11/2026, parada desde 02/10")

print(f"✅ {len(oks)} checagens OK · ❌ {len(falhas)} erros")
for f in falhas:
    print("❌", f)
sys.exit(1 if falhas else 0)
