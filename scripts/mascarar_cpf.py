#!/usr/bin/env python3
"""
Cofre Aberto MS — mascara CPF completo de pessoa física nos dados publicados (LGPD)

Algumas fontes oficiais (CSV da cota parlamentar da Câmara, notas da ALEMS, uma ou outra linha de credor do Estado)
trazem o CPF inteiro de fornecedores pessoa física. O site publica só o formato do Portal da Transparência,
***.123.456-**, que mantém os 6 dígitos do meio (usados nos cruzamentos com TSE e Receita) e esconde o resto.

Varre dados/**/*.json e dados/csv/*.csv e troca todo "000.000.000-00" por "***.000.000-**". Roda no fim da coleta,
antes de gerar as páginas.
"""

import re
from pathlib import Path

DADOS = Path(__file__).parent.parent / "dados"
CPF = re.compile(r"(?<![\d*.])(\d{3})\.(\d{3})\.(\d{3})-(\d{2})(?![\d])")
# CPF sem pontuação num campo de documento: 11 dígitos, ou 14 com "000" na frente (como a Prefeitura de CG exporta)
CAMPO = re.compile(r'("(?:cnpj|cpf|cpfCnpj|cnpjCpf|cnpjCpfFornecedor|niFornecedor|documento|cpfcnpj)"\s*:\s*")(000)?(\d{11})"')
CSV14 = re.compile(r"(?<![\d*])000(\d{11})(?!\d)")


def cnpj_valido(c):
    if len(c) != 14 or len(set(c)) == 1:
        return False
    def dv(s, w):
        r = sum(int(x) * y for x, y in zip(s, w)) % 11
        return "0" if r < 2 else str(11 - r)
    return dv(c[:12], [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]) == c[12] and dv(c[:13], [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]) == c[13]


def mascara(c11):
    return f"***.{c11[3:6]}.{c11[6:9]}-**"


def campo(m):
    if m.group(2) and cnpj_valido(m.group(2) + m.group(3)):
        return m.group(0)  # é CNPJ de verdade (começa com 000)
    return f'{m.group(1)}{mascara(m.group(3))}"'


def main():
    total, arqs = 0, 0
    for f in list(DADOS.rglob("*.json")) + list((DADOS / "csv").glob("*.csv")):
        try:
            t = f.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        novo, n = CPF.subn(lambda m: f"***.{m.group(2)}.{m.group(3)}-**", t)
        if f.suffix == ".json":
            novo, n2 = CAMPO.subn(campo, novo)
        else:
            novo, n2 = CSV14.subn(lambda m: m.group(0) if cnpj_valido(m.group(0)) else mascara(m.group(1)), novo)
        n = len(re.findall(r"\*\*\*\.\d{3}\.\d{3}-\*\*", novo)) - len(re.findall(r"\*\*\*\.\d{3}\.\d{3}-\*\*", t))
        if novo != t:
            f.write_text(novo, encoding="utf-8")
            total += n
            arqs += 1
    print(f"✅ CPF mascarado: {total} ocorrências em {arqs} arquivos" if total else "✅ nenhum CPF completo nos dados")


if __name__ == "__main__":
    main()
