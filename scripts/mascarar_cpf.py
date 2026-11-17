#!/usr/bin/env python3
"""
Cofre Aberto MS — mascara CPF completo de pessoa física nos dados publicados (LGPD)

Várias fontes oficiais (cota parlamentar da Câmara e do Senado, notas da ALEMS, credores do Estado, despesas da
Prefeitura, PNCP, emendas) trazem o CPF inteiro de fornecedores, locadores e favorecidos pessoa física. O site publica
só o formato do Portal da Transparência, ***.123.456-**, que mantém os 6 dígitos do meio (usados nos cruzamentos com
TSE e Receita) e esconde o resto.

O que é mascarado, em dados/**/*.json|jsonl|csv|xml:
  1. todo CPF com pontuação (000.000.000-00), em qualquer lugar;
  2. "CPF" seguido de 11 dígitos dentro de um texto;
  3. em campos de DOCUMENTO DE PESSOA — chave com "cpf" ou "cnpj", ou doc/ni/documento quando o registro não tem
     outro campo de CPF/CNPJ —, o valor de 11 dígitos (com ou sem pontos, traços e espaços) e o de 14 dígitos com "000"
     na frente que não seja CNPJ válido (como a Prefeitura de CG e o Senado exportam o CPF);
  4. NÚMERO DO DOCUMENTO FISCAL: nas notas da cota parlamentar, "doc"/"documento" é o número da nota, e o documento do
     fornecedor fica em cnpjCpfFornecedor/cnpjCpf. Esse número só é mascarado quando é o próprio CPF do fornecedor
     (recibo de pessoa física numerado pelo CPF). Números de nota, guia, contrato e processo ficam como a fonte publica
     — um número de 11 dígitos pode passar no dígito verificador do CPF por coincidência (guias municipais usam módulo 11);
  5. CPF colado no nome (razão social de MEI na Receita: "NOME COMPLETO 12345678901"), em qualquer texto — campos de
     fornecedor, leitura dos PDFs, chaves internas, páginas — quando os 11 dígitos passam no dígito verificador do CPF;
  6. nas planilhas CSV, as mesmas regras por coluna (cnpj_cpf = documento de pessoa; documento = número da nota quando
     há a coluna cnpj_cpf ao lado).

A decisão é tomada pela estrutura do registro, mas a troca é feita no texto, só no par "campo": valor exato — o
arquivo mantém o formato original. Roda no fim de cada coleta. Uso: python3 scripts/mascarar_cpf.py [pasta ...]
"""

import json
import re
import sys
from pathlib import Path

DADOS = Path(__file__).parent.parent / "dados"
CPF = re.compile(r"(?<![\d*.])(\d{3})\.(\d{3})\.(\d{3})-(\d{2})(?![\d])")
CPF_TEXTO = re.compile(r"(?i)(\bCPF\b[^\d\n\"<]{0,6})(\d{11})(?!\d)")
# nome de MEI (empresário individual): a Receita registra a razão social como "NOME COMPLETO 12345678901"
NOME_CPF = re.compile(r"(?<=[A-Za-zÀ-ÿ.])([ \t\-–]{1,4})(\d{11})(?![\d/])")
PAR = re.compile(r'("([A-Za-z_]\w*)"\s*:\s*)(?:"([\d][\d ./-]{9,22})"|(\d{11,14}))(?=\s*[,}\]\n])')
NUMERO_DOC = {"doc", "ni", "documento", "nrdocumento", "numdocumento"}  # número da nota quando há fornecedor ao lado
OUTRAS_DOC = {"nifornecedor", "docfornecedor", "documentofornecedor"}


def cnpj_valido(c):
    if len(c) != 14 or len(set(c)) == 1:
        return False
    def dv(s, w):
        r = sum(int(x) * y for x, y in zip(s, w)) % 11
        return "0" if r < 2 else str(11 - r)
    return dv(c[:12], [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]) == c[12] and dv(c[:13], [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]) == c[13]


def mascara(c11):
    return f"***.{c11[3:6]}.{c11[6:9]}-**"


def cpf_do_valor(v):
    """Os 11 dígitos se o valor for um CPF sem máscara (11 dígitos, ou "000"+11 que não é CNPJ); senão None."""
    s = str(v).strip()
    if not s or "*" in s or "/" in s or not re.fullmatch(r"[\d .\-]+", s):
        return None
    d = re.sub(r"\D", "", s)
    if len(d) == 11:
        return d
    if len(d) == 14 and d.startswith("000") and not cnpj_valido(d):
        return d[3:]
    return None


def chave_pessoa(k):
    k = k.lower()
    return "cpf" in k or "cnpj" in k or k in OUTRAS_DOC


def mesmo_cpf(c11, fornecedor):
    """O número do documento é o CPF do fornecedor (mascarado ou não)?"""
    f = str(fornecedor or "")
    m = re.fullmatch(r"\*\*\*\.(\d{3})\.(\d{3})-\*\*", f.strip())
    if m:
        return c11[3:9] == m.group(1) + m.group(2)
    fd = cpf_do_valor(f)
    return fd == c11


def alvos_json(o, alvos):
    """Percorre o JSON e junta os pares (chave, valor) que são CPF de pessoa."""
    if isinstance(o, dict):
        forn = [k for k in o if chave_pessoa(k)]
        for k, v in o.items():
            if isinstance(v, bool) or not isinstance(v, (str, int)):
                continue
            kl = k.lower()
            c = cpf_do_valor(v)
            if not c:
                continue
            if chave_pessoa(k):
                alvos.add((k, str(v)))
            elif kl in NUMERO_DOC:
                outros = [x for x in forn if x != k]
                if not outros or any(mesmo_cpf(c, o[x]) for x in outros):
                    alvos.add((k, str(v)))
            elif kl.startswith("documento") and "numero" not in kl:
                alvos.add((k, str(v)))
        for v in o.values():
            alvos_json(v, alvos)
    elif isinstance(o, list):
        for v in o:
            alvos_json(v, alvos)
    return alvos


def troca_pares(texto, alvos):
    def f(m):
        k, v = m.group(2), m.group(3) if m.group(3) is not None else m.group(4)
        if (k, v) in alvos:
            return f'{m.group(1)}"{mascara(cpf_do_valor(v))}"'
        return m.group(0)
    return PAR.sub(f, texto)


def mascarar_json(t):
    try:
        alvos = alvos_json(json.loads(t), set())
    except ValueError:  # JSON quebrado: só os campos que são sempre de pessoa
        alvos = {(m.group(2), m.group(3) or m.group(4)) for m in PAR.finditer(t)
                 if chave_pessoa(m.group(2)) and cpf_do_valor(m.group(3) or m.group(4))}
    return troca_pares(t, alvos) if alvos else t


def mascarar_jsonl(t):
    out = []
    for l in t.split("\n"):
        out.append(mascarar_json(l) if l.strip().startswith("{") else l)
    return "\n".join(out)


def csv_colunas(t):
    linhas = t.split("\n")
    for h, l in enumerate(linhas[:3]):
        sep = ";" if ";" in l and l.count(";") >= l.count(",") else ","
        cab = [c.strip().strip('"').strip("﻿").lower() for c in l.split(sep)]
        pessoa = [i for i, c in enumerate(cab) if "cpf" in c or "cnpj" in c]
        numero = [i for i, c in enumerate(cab) if c in ("documento", "doc", "num_documento", "numero_documento")]
        if pessoa or numero:
            break
    else:
        return t
    for j in range(h + 1, len(linhas)):
        cel = linhas[j].split(sep)
        mudou = False
        def troca(i):
            nonlocal mudou
            bruto = cel[i].strip()
            aspas = bruto.startswith('"')
            c = cpf_do_valor(bruto.strip('"'))
            if c:
                cel[i] = f'"{mascara(c)}"' if aspas else mascara(c)
                mudou = True
        for i in pessoa:
            if i < len(cel):
                troca(i)
        for i in numero:
            if i < len(cel):
                c = cpf_do_valor(cel[i].strip().strip('"'))
                if c and (not pessoa or any(i2 < len(cel) and mesmo_cpf(c, linhas[j].split(sep)[i2].strip().strip('"')) for i2 in pessoa)):
                    troca(i)
        if mudou:
            linhas[j] = sep.join(cel)
    return "\n".join(linhas)


def dv_cpf(d):
    if len(d) != 11 or len(set(d)) == 1:
        return False
    for n in (9, 10):
        if (sum(int(d[i]) * (n + 1 - i) for i in range(n)) * 10) % 11 % 10 != int(d[n]):
            return False
    return True


def mascarar_nomes(t):
    return NOME_CPF.sub(lambda m: m.group(1) + mascara(m.group(2)) if dv_cpf(m.group(2)) else m.group(0), t)


def mascarar_texto(t, tipo):
    novo = CPF.sub(lambda m: f"***.{m.group(2)}.{m.group(3)}-**", t)
    novo = CPF_TEXTO.sub(lambda m: m.group(1) + mascara(m.group(2)), novo)
    novo = mascarar_nomes(novo)
    if tipo == "json":
        novo = mascarar_json(novo) if novo == t else mascarar_json_com_original(t, novo)
    elif tipo == "jsonl":
        novo = mascarar_jsonl(novo)
    elif tipo == "csv":
        novo = csv_colunas(novo)
    return novo


def mascarar_json_com_original(original, novo):
    """Decide pelos valores ORIGINAIS (o fornecedor ainda sem máscara) e troca no texto já com os CPFs pontuados mascarados."""
    try:
        alvos = alvos_json(json.loads(original), set())
    except ValueError:
        return mascarar_json(novo)
    return troca_pares(novo, alvos) if alvos else novo


def main():
    """python3 scripts/mascarar_cpf.py [pasta ...]   (padrão: dados/)
       python3 scripts/mascarar_cpf.py --paginas    também as páginas .html/.xml do site (CPF pontuado e CPF no nome)"""
    total, arqs = 0, 0
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    alvos = [(Path(p), ("json", "jsonl", "csv", "xml")) for p in (args or [str(DADOS)])]
    if "--paginas" in sys.argv:
        alvos.append((DADOS.parent, ("html",)))
    for base, exts in alvos:
        for f in sorted(x for ext in exts for x in base.rglob(f"*.{ext}")
                        if not any(s in x.parts for s in ("node_modules", ".git", "tests"))):
            try:
                t = f.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            novo = mascarar_texto(t, f.suffix[1:]) if f.suffix != ".html" else mascarar_nomes(CPF.sub(lambda m: f"***.{m.group(2)}.{m.group(3)}-**", t))
            if novo != t:
                n = len(re.findall(r"\*\*\*\.\d{3}\.\d{3}-\*\*", novo)) - len(re.findall(r"\*\*\*\.\d{3}\.\d{3}-\*\*", t))
                f.write_text(novo, encoding="utf-8")
                total += n
                arqs += 1
                if f.suffix != ".html":
                    print(f"  {f.relative_to(base.parent)}: {n}")
    print(f"✅ CPF mascarado: {total} ocorrências em {arqs} arquivos" if total else "✅ nenhum CPF completo nos dados")


if __name__ == "__main__":
    main()
