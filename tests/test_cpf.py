#!/usr/bin/env python3
"""
Cofre Aberto MS — nenhum CPF completo nos arquivos publicados (LGPD)

Implementação própria (não importa scripts/mascarar_cpf.py), para que um erro na máscara não passe também no teste.

Procura, em tudo o que o site publica (dados/**/*.json|jsonl|csv e as páginas .html/.js/.xml/.txt):
  A. CPF com pontuação (000.000.000-00) com dígito verificador válido, em qualquer lugar;
  B. em campos de documento de JSON (chave com cpf/cnpj/documento, ou doc/ni/niFornecedor/docFornecedor), valor de
     11 dígitos sem pontuação, ou de 14 dígitos com "000" na frente que não seja CNPJ válido — em qualquer nível;
  C. a palavra "CPF" seguida de 11 dígitos num texto;
  D. colunas de CPF/CNPJ/documento das planilhas CSV;
  F. CPF colado no nome (razão social de MEI: "NOME COMPLETO 12345678901"), em qualquer arquivo;
  E. nas páginas, CPF disfarçado de CNPJ (00.0XX.XXX/XXXX-XX com "000" + CPF) e 11 dígitos logo depois de "CPF"/"CNPJ".
  ("doc"/"documento" ao lado do CPF/CNPJ do fornecedor é o NÚMERO DA NOTA: só conta se for o CPF do próprio fornecedor.)

Antes de varrer, o teste se testa: monta CPFs sintéticos (gerados na hora, nunca gravados) em cada formato e confere
que todos são achados, e que CPF mascarado e CNPJ válido NÃO são acusados.

Uso:
  python3 tests/test_cpf.py                      varre os arquivos locais
  python3 tests/test_cpf.py --site URL [--lista arquivo]   baixa e varre os arquivos publicados no site
Código de saída 1 se achar CPF. Nunca imprime o CPF: só o arquivo, o tipo e a quantidade.
"""

import json, random, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def dv_cpf(d):
    if len(d) != 11 or d == d[0] * 11:
        return False
    for n in (9, 10):
        s = sum(int(d[i]) * (n + 1 - i) for i in range(n))
        if (s * 10) % 11 % 10 != int(d[n]):
            return False
    return True


def dv_cnpj(d):
    if len(d) != 14 or d == d[0] * 14:
        return False
    for n in (12, 13):
        w = [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2][13 - n:]
        r = sum(int(d[i]) * w[i] for i in range(n)) % 11
        if (0 if r < 2 else 11 - r) != int(d[n]):
            return False
    return True


def eh_chave_doc(k):
    k = k.lower()
    return "cpf" in k or "cnpj" in k or k in {"doc", "ni", "nifornecedor", "docfornecedor", "documento", "documentofornecedor", "nrdocumento"} \
        or (k.startswith("documento") and "numero" not in k)


NUMERO = {"doc", "ni", "documento", "nrdocumento", "numdocumento"}


def digitos_cpf(v):
    d = re.sub(r"\D", "", str(v))
    return d if len(d) == 11 else d[3:] if len(d) == 14 and d.startswith("000") and not dv_cnpj(d) else None


def igual_ao_fornecedor(numero, fornecedor):
    n, f = digitos_cpf(numero), str(fornecedor or "").strip()
    m = re.fullmatch(r"\*\*\*\.(\d{3})\.(\d{3})-\*\*", f)
    if m:
        return bool(n) and n[3:9] == m.group(1) + m.group(2)
    return bool(n) and cpf_em_valor(f) and digitos_cpf(f) == n


def cpf_em_valor(v):
    s = str(v)
    if "*" in s or "/" in s or not re.fullmatch(r"[\d.\-\s]+", s.strip() or "x"):
        return False
    d = re.sub(r"\D", "", s)
    return len(d) == 11 or (len(d) == 14 and d.startswith("000") and not dv_cnpj(d))


FMT = re.compile(r"(?<![\d*.])(\d{3})\.(\d{3})\.(\d{3})-(\d{2})(?!\d)")
TXT = re.compile(r"(?i)\bCPF\b[^\d\n\"<]{0,6}(\d{11})(?!\d)")
CNPJ_FMT = re.compile(r"(?<![\d.])(\d{2})\.(\d{3})\.(\d{3})/(\d{4})-(\d{2})(?!\d)")
NOME11 = re.compile(r"[A-Za-zÀ-ÿ.][ \t\-–]{1,4}(\d{11})(?![\d/])")  # razão social de MEI: "NOME 12345678901"
ROTULO11 = re.compile(r"(?i)(?:\bcpf|\bcnpj)\W{0,12}(\d{11})(?!\d)")


def achar(texto, tipo_arq):
    """{tipo: quantidade} de CPFs completos no texto."""
    out = {}
    def soma(k, n=1):
        out[k] = out.get(k, 0) + n
    for m in FMT.finditer(texto):
        if dv_cpf("".join(m.groups())):
            soma("A: CPF com pontuação")
    for m in TXT.finditer(texto):
        soma("C: 'CPF' + 11 dígitos")
    for m in NOME11.finditer(texto):
        if dv_cpf(m.group(1)):
            soma("F: CPF colado no nome (MEI)")
    if tipo_arq in ("json", "jsonl"):
        objs = []
        if tipo_arq == "jsonl":
            for l in texto.splitlines():
                try:
                    objs.append(json.loads(l))
                except ValueError:
                    pass
        else:
            try:
                objs = [json.loads(texto)]
            except ValueError:
                objs = []
        def walk(o):
            if isinstance(o, dict):
                for k, v in o.items():
                    if isinstance(v, (str, int)) and not isinstance(v, bool) and eh_chave_doc(k) and cpf_em_valor(v):
                        # número da nota (doc/documento) ao lado do documento do fornecedor: só é CPF se for o do fornecedor
                        forn = [x for x in o if x != k and ("cpf" in x.lower() or "cnpj" in x.lower())]
                        if k.lower() in NUMERO and forn and not any(igual_ao_fornecedor(v, o[x]) for x in forn):
                            continue
                        soma(f"B: campo '{k}' sem máscara")
                    walk(v)
            elif isinstance(o, list):
                for x in o:
                    walk(x)
        for o in objs:
            walk(o)
    elif tipo_arq == "csv":
        linhas = texto.split("\n")
        for h, l in enumerate(linhas[:3]):
            sep = ";" if ";" in l and l.count(";") >= l.count(",") else ","
            cab = [c.strip().strip('"').lower() for c in l.split(sep)]
            pes = [i for i, c in enumerate(cab) if "cpf" in c or "cnpj" in c]
            num = [i for i, c in enumerate(cab) if re.fullmatch(r"documento|doc|num_documento|numero_documento", c)]
            if pes or num:
                for row in linhas[h + 1:]:
                    cel = [x.strip().strip('"') for x in row.split(sep)]
                    for i in pes:
                        if i < len(cel) and cpf_em_valor(cel[i]):
                            soma("D: coluna de CPF/CNPJ do CSV")
                    for i in num:
                        if i < len(cel) and cpf_em_valor(cel[i]) and (not pes or any(j < len(cel) and igual_ao_fornecedor(cel[i], cel[j]) for j in pes)):
                            soma("D: coluna de documento do CSV")
                break
    else:  # páginas
        for m in CNPJ_FMT.finditer(texto):
            d = "".join(m.groups())
            if d.startswith("000") and not dv_cnpj(d) and dv_cpf(d[3:]):
                soma("E: CPF disfarçado de CNPJ")
        for m in ROTULO11.finditer(texto):
            d = m.group(1)
            if dv_cpf(d) and not dv_cnpj(d.zfill(14)):
                soma("E: 11 dígitos depois de cpf/cnpj/doc")
    return out


def cpf_sintetico(rng):
    while True:
        b = [rng.randint(0, 9) for _ in range(9)]
        for n in (9, 10):
            s = sum(b[i] * (n + 1 - i) for i in range(n))
            b.append((s * 10) % 11 % 10)
        d = "".join(map(str, b))
        if dv_cpf(d) and not dv_cnpj(d.zfill(14)) and not dv_cnpj("000" + d):
            return d


def autoteste():
    rng = random.Random(20261117)
    c = cpf_sintetico(rng)
    f = f"{c[:3]}.{c[3:6]}.{c[6:9]}-{c[9:]}"
    mas = f"***.{c[3:6]}.{c[6:9]}-**"
    casos = [  # (texto, tipo, deve achar?)
        (f'{{"x":"{f}"}}', "json", True), (f'{{"doc":"{c}"}}', "json", True), (f'{{"a":[{{"doc":"000{c}"}}]}}', "json", True),
        (f'{{"cnpjFornecedor":"{c}"}}', "json", True), (f'{{"cpfCnpj":{int(c) if c[0] != "0" else c}}}', "json", True),
        (f'{{"descricao":"pago ao CPF {c}"}}', "json", True), (f'{{"doc":"{c}"}}\n', "jsonl", True),
        (f"nome;cpf_cnpj;valor\nFulano;{c};10,00", "csv", True), (f'"nome","documento"\n"Fulano","000{c}"', "csv", True),
        (f"<td>{c[:2]}.{c[2:5]}.{c[5:8]}/{c[8:]}</td>".replace(f"{c[:2]}.{c[2:5]}.{c[5:8]}/{c[8:]}", f"00.0{c[:2]}.{c[2:5]}/{c[5:9]}-{c[9:]}"), "html", True),
        (f"<span>CPF: {c}</span>", "html", True), (f'{{"fornecedor":"FULANO DE TAL {c}"}}', "json", True),
        (f"<td>FULANO DE TAL {c}</td>", "html", True), (f'{{"x":"FULANO {mas}"}}', "json", False),
        (f'{{"doc":"{mas}"}}', "json", False), (f'{{"x":"{mas}"}}', "json", False), ('{"cnpj":"00360305000104"}', "json", False),
        ('{"numero":"' + c + '"}', "json", False), (f'{{"cnpjCpf":"12.345.678/0001-95","doc":"{c}"}}', "json", False),
        (f'{{"cnpjCpf":"{c}","doc":"{c}"}}', "json", True), (f'{{"cnpjCpf":"{mas}","doc":"{c}"}}', "json", True),
        (f"cnpj_cpf;documento\n12.345.678/0001-95;{c}", "csv", False), (f"cnpj_cpf;documento\n{mas};{c}", "csv", True), (f"nome;cpf;valor\nFulano;{mas};10,00", "csv", False), ("<td>00.360.305/0001-04</td>", "html", False),
    ]
    falhas = [i for i, (t, tp, deve) in enumerate(casos) if bool(achar(t, tp)) != deve]
    return len(casos), falhas


def arquivos_locais():
    for f in sorted(list((ROOT / "dados").rglob("*.json")) + list((ROOT / "dados").rglob("*.jsonl")) + list((ROOT / "dados").rglob("*.csv"))):
        yield f.relative_to(ROOT).as_posix(), f.suffix[1:], lambda f=f: f.read_text(encoding="utf-8", errors="ignore")
    for ext in ("html", "js", "xml", "txt"):
        for f in sorted(ROOT.glob(f"**/*.{ext}")):
            r = f.relative_to(ROOT).as_posix()
            if r.startswith(("node_modules/", ".git/", "tests/")) or "/node_modules/" in r:
                continue
            yield r, "html", lambda f=f: f.read_text(encoding="utf-8", errors="ignore")


def varrer(itens):
    achados, n = [], 0
    for nome, tipo, ler in itens:
        n += 1
        r = achar(ler(), tipo)
        for k, q in r.items():
            achados.append((nome, k, q))
    return n, achados


def main():
    total, falhas = autoteste()
    print(f"{'✅' if not falhas else '❌'} autoteste do detector: {total - len(falhas)}/{total} casos sintéticos certos")
    if "--site" in sys.argv:
        import urllib.request
        site = sys.argv[sys.argv.index("--site") + 1].rstrip("/")
        caminhos = [l.strip() for l in open(sys.argv[sys.argv.index("--lista") + 1])] if "--lista" in sys.argv else [r for r, _, _ in arquivos_locais()]
        def baixa(c):
            req = urllib.request.Request(f"{site}/{c}?nc=1", headers={"User-Agent": "cofre-aberto-teste-lgpd"})
            try:
                return urllib.request.urlopen(req, timeout=60).read().decode("utf-8", "ignore")
            except Exception:
                return ""
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(12) as ex:
            conteudo = dict(zip(caminhos, ex.map(baixa, caminhos)))
        vazios = [c for c in caminhos if not conteudo[c]]
        if vazios:
            print(f"⚠️ {len(vazios)} arquivo(s) não baixado(s) do site (ex.: {vazios[:3]})")
        itens = [(c, (c.rsplit(".", 1)[-1] if c.endswith((".json", ".jsonl", ".csv")) else "html"), (lambda c=c: conteudo[c])) for c in caminhos]
        origem = site
    else:
        itens, origem = list(arquivos_locais()), "arquivos locais"
    n, achados = varrer(itens)
    q = sum(x[2] for x in achados)
    print(f"{'✅' if not achados else '❌'} {origem}: {n} arquivos varridos · {q} CPF(s) completo(s) em {len({a for a, _, _ in achados})} arquivo(s)")
    for a, k, qq in achados[:40]:
        print(f"   ❌ {a} — {k}: {qq}")
    if "--json" in sys.argv:  # resultado por arquivo, para a proteção da publicação e o ICP
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from _bases import base_de
        itens = [{"base": base_de(a), "nivel": "erro", "texto": f"CPF completo em {a} ({k}: {q})"} for a, k, q in achados]
        if falhas:
            itens.append({"base": "geral", "nivel": "erro", "texto": f"detector de CPF falhou no autoteste ({len(falhas)} de {total} casos)"})
        itens.append({"base": "geral", "nivel": "ok", "texto": f"CPF: {n} arquivos varridos sem CPF completo"} if not achados else {"base": "geral", "nivel": "aviso", "texto": "CPF encontrado"})
        json.dump({"teste": "cpf", "ok": int(not achados and not falhas), "avisos": 0, "erros": len(achados) + bool(falhas), "itens": itens},
                  open(sys.argv[sys.argv.index("--json") + 1], "w", encoding="utf-8"), ensure_ascii=False)
    sys.exit(1 if (achados or falhas) else 0)


if __name__ == "__main__":
    main()
