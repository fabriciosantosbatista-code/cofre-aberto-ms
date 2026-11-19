"""Cofre Aberto MS — a qual base do ICP pertence cada conferência dos testes (pelo texto da conferência)."""
import json, re

# (base, padrão no nome/mensagem da conferência). O primeiro que casar vence.
REGRAS = [
    ("camaras-ms", r"^Câmaras do interior|camaras/|Câmaras municipais do interior|camaras-ms"),
    ("camara", r"^CG[ :]|Câmara CG|camara_municipal|Câmara Municipal de Campo Grande|camara_cg|Painel leve da Câmara|^camara\b"),
    ("deputados-estaduais", r"^ALEMS|deputados_estaduais|Assembleia Legislativa|deputados-estaduais"),
    ("deputados", r"deputados_federais_ms|Câmara dos Deputados — CEAP|Evolução .*:|^deputados\b|Dep\. federais"),
    ("senadores", r"senadores_ms|Senado Federal — CEAPS|^senadores\b"),
    ("prefeitura", r"^Prefeitura[ :]|prefeitura\.json|Prefeitura de Campo Grande — despesas|^prefeitura\b"),
    ("contratos-cg", r"prefeitura_contratos|contratos e licitações|contratos-cg"),
    ("governo-ms", r"^Governo MS|governo_ms|Governo de MS \(Poder Executivo\)|governo-ms|versões governo"),
    ("emendas", r"^Emendas|emendas_municipios|emendas parlamentares pagas|^emendas\b"),
    ("shows", r"^Shows|shows\.json|shows contratados|^shows\b"),
    ("obras", r"^Obras|obras\.json|obras \(contratos\)|^obras\b"),
    ("publicidade", r"^Publicidade|publicidade\.json|^publicidade\b"),
    ("entidades", r"^Entidades|entidades\.json|^entidades\b"),
    ("alugueis", r"^Aluguéis|alugueis\.json|aluguel de imóveis|^alugueis\b"),
    ("supersalarios", r"^Supersalários|supersalarios\.json|Folhas de pagamento|^supersalarios\b"),
    ("producao", r"^Produção|producao_legislativa|produção legislativa|^producao\b"),
    ("votacoes", r"^Votações|votacoes\.json|votações nominais|^votacoes\b"),
    ("arrecadacao", r"^Receitas|receitas\.json|Siconfi|versões receitas|^arrecadacao\b"),
    ("judiciario", r"tjms_magistrados|TJMS, TRT24|^judiciario\b"),
    ("eleicoes", r"eleicoes|TSE —"),
    ("auditoria", r"auditoria\.json|Sinais de atenção|^auditoria\b"),
]


IDS = {b for b, _ in REGRAS} | {"deputados-brasil", "senado-brasil", "conexoes", "evolucao"}


def base_de(texto):
    t = texto or ""
    m = re.match(r"^(?:fonte|registros|total) ([\w-]+)$", t) or re.match(r"^([\w-]+): (?:registros|total)", t)
    if m and m.group(1) in IDS:
        return m.group(1)
    for b, rx in REGRAS:
        if re.search(rx, t):
            return b
    return "geral"


def grava_json(caminho, teste, oks, avisos, erros):
    itens = [{"base": base_de(x), "nivel": "ok", "texto": x} for x in oks] + \
            [{"base": base_de(x), "nivel": "aviso", "texto": x} for x in avisos] + \
            [{"base": base_de(x), "nivel": "erro", "texto": x} for x in erros]
    with open(caminho, "w", encoding="utf-8") as f:
        json.dump({"teste": teste, "ok": len(oks), "avisos": len(avisos), "erros": len(erros), "itens": itens}, f, ensure_ascii=False)
