"""
Ano de referência do Cofre Aberto MS — regra única para coletores, análises e páginas.

O ano exibido vira em 1º de FEVEREIRO, não em 1º de janeiro: em janeiro ainda
chegam às fontes as notas fiscais de dezembro, então o ano anterior só fecha
completo no fim do mês. Em fevereiro os coletores passam a buscar o ano novo
(desde janeiro) e o ano que fechou vira histórico (dados/historico_AAAA.json).

O painel (cofre-aberto-ms.html, função anoReferencia) usa exatamente a mesma regra.
"""
from datetime import date


def ano_referencia(hoje=None):
    hoje = hoje or date.today()
    return hoje.year if hoje.month >= 2 else hoje.year - 1


if __name__ == "__main__":
    for d in (date(2026, 11, 10), date(2026, 12, 31), date(2027, 1, 1), date(2027, 1, 31), date(2027, 2, 1)):
        print(d, "->", ano_referencia(d))
