#!/usr/bin/env python3
"""
Cofre Aberto MS — número das licitações da Prefeitura de CG e textos da auditoria (sem rede)

26/11/2026: o portal manda "numero" com o número repetido no lugar do ano ("102/102", "4/004") e "anoedital" vazio;
o número certo sai dos campos da própria fonte (numeroedital + ano): "102/2026". O número como veio fica em
"numeroFonte", e a chave do sinal "sócios em comum na mesma licitação" usa esse valor, para o id do sinal não mudar.
Uso: python3 tests/test_licitacao_numero.py   (código 1 se algum teste falhar)
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import coletar_contratos_cg as cc  # noqa: E402

oks, erros = [], []
check = lambda c, m: (oks if c else erros).append(m)
casos = [({"numero": "102/102", "numeroedital": 102, "anoedital": None, "ano": 2026}, ("102/2026", "102/102")),
         ({"numero": "4/004", "numeroedital": 4, "ano": 2026}, ("4/2026", "4/004")),
         ({"numero": "31/2026", "numeroedital": 31, "ano": 2026}, ("31/2026", "31/2026")),
         ({"numero": "45/054", "numeroedital": 45, "ano": 2026}, ("45/054", "45/054")),
         ({"numero": "1/001/2026", "ano": 2026}, ("1/001/2026", "1/001/2026")),
         ({"numero": "", "ano": 2026}, ("", ""))]
for x, esperado in casos:
    check(cc.numero_licitacao(x) == esperado, f"{x['numero']!r} → {cc.numero_licitacao(x)} (esperado {esperado})")
src = (ROOT / "scripts" / "gerar_auditoria.py").read_text(encoding="utf-8")
check('l.get("numeroFonte") or l["numero"]' in src, "o id do sinal usa o número como veio da fonte")
check("pagada" not in src.replace("apagada", ""), "texto da auditoria: 'paga em MS', não 'pagada'")
for e in erros:
    print("❌", e)
print(f"✅ {len(oks)} checagens OK · ❌ {len(erros)} erros")
sys.exit(1 if erros else 0)
