#!/usr/bin/env python3
"""
Cofre Aberto MS — Prestação de contas de campanha dos parlamentares de MS (TSE)

Baixa do Portal de Dados Abertos do TSE, só a parte de Mato Grosso do Sul (lida
por "range" dentro dos zips nacionais, que têm até 1,2 GB):
  - consulta_cand: quem é cada candidato (nome de urna, nome completo, cargo)
  - receitas: quem doou para a campanha (pessoas físicas)
  - despesas contratadas: quem a campanha contratou (fornecedores)

Eleições usadas: 2024 (vereadores de Campo Grande), 2022 (deputados estaduais,
federais e a senadora eleita em 2022) e 2018 (senadores eleitos em 2018).

Gera dados/tse_campanhas.json, usado por gerar_auditoria.py para dois testes:
sócio da empresa que doou para a campanha do parlamentar que paga a empresa, e
fornecedor da campanha que depois passou a receber da cota/verba.

Os doadores ficam guardados pelo nome e pelos 6 dígitos do meio do CPF (o trecho que a
Receita já publica no quadro de sócios), não pelo CPF inteiro; e só os de quem tem mandato hoje.
"""

import csv, io, json, re, sys, time, unicodedata, zipfile
from datetime import datetime
from pathlib import Path

import requests

ROOT = Path(__file__).parent.parent
DADOS = ROOT / "dados"
BASE = "https://cdn.tse.jus.br/estatistica/sead/odsele"
UA = {"User-Agent": "Mozilla/5.0 (CofreAbertoMS; +https://cofreabertoms.com.br)"}
csv.field_size_limit(10**7)

# (grupo no site, arquivo, chave da lista, eleição, cargos no TSE, unidade eleitoral)
GRUPOS = [
    ("vereador", "camara_municipal.json", "vereadores", 2024, {"VEREADOR"}, "CAMPO GRANDE"),
    ("estadual", "deputados_estaduais_ms.json", "vereadores", 2022, {"DEPUTADO ESTADUAL"}, None),
    ("federal", "deputados_federais_ms.json", "deputados", 2022, {"DEPUTADO FEDERAL"}, None),
    ("senador", "senadores_ms.json", "senadores", 2022, {"SENADOR"}, None),
    ("senador", "senadores_ms.json", "senadores", 2018, {"SENADOR"}, None),
]


class ArquivoRemoto(io.RawIOBase):
    """Arquivo HTTP lido por pedaços (Range), para abrir um zip sem baixá-lo inteiro."""
    def __init__(self, url):
        self.url, self.pos = url, 0
        self.size = int(requests.head(url, headers=UA, timeout=60).headers["content-length"])

    def seekable(self):
        return True

    def readable(self):
        return True

    def seek(self, off, whence=0):
        self.pos = off if whence == 0 else self.pos + off if whence == 1 else self.size + off
        return self.pos

    def tell(self):
        return self.pos

    def readinto(self, b):
        if self.pos >= self.size:
            return 0
        fim = min(self.pos + len(b), self.size) - 1
        esperado = fim - self.pos + 1
        for t in range(6):
            try:
                r = requests.get(self.url, headers={**UA, "Range": f"bytes={self.pos}-{fim}"}, timeout=120)
                d = r.content
                if r.status_code == 206 and len(d) == esperado:  # pedaço completo; senão, tenta de novo
                    break
            except requests.RequestException:
                pass
            if t == 5:
                raise IOError(f"leitura parcial falhou em {self.url} ({self.pos}-{fim})")
            time.sleep(2 * (t + 1))
        b[:len(d)] = d
        self.pos += len(d)
        return len(d)


_zips = {}


def ler_csv(zip_url, membro):
    if zip_url not in _zips:
        _zips[zip_url] = zipfile.ZipFile(io.BufferedReader(ArquivoRemoto(zip_url), buffer_size=1 << 20))
    z = _zips[zip_url]
    nomes = {i.filename.split("/")[-1]: i.filename for i in z.infolist()}
    if membro not in nomes:
        raise FileNotFoundError(f"{membro} não está em {zip_url}")
    return csv.DictReader(io.TextIOWrapper(z.open(nomes[membro]), encoding="latin1"), delimiter=";")


def norm(t):
    return re.sub(r"\s+", " ", re.sub(r"[^A-Z ]", " ", unicodedata.normalize("NFD", str(t or "")).encode("ascii", "ignore").decode().upper())).strip()


def cpf6(t):
    """Só os 6 dígitos do meio do CPF — o mesmo trecho que a Receita mostra no quadro de sócios (***123456**)."""
    d = re.sub(r"\D", "", str(t or ""))
    return d[3:9] if len(d) == 11 else None


def num(t):
    try:
        return float(str(t).replace(".", "").replace(",", "."))
    except ValueError:
        return 0.0


APELIDO = {"CEL": "CORONEL", "DR": "DOUTOR", "DRA": "DOUTORA", "PROF": "PROFESSOR", "SGT": "SARGENTO", "TEN": "TENENTE"}


def urna(t):
    return " ".join(APELIDO.get(w, w) for w in norm(t).split())


def casar(v, cands):
    """Acha a candidatura pelo nome de urna (o nome do site); o nome completo só desempata."""
    eleitos = [c for c in cands if re.search(r"ELEITO|SUPLENTE|M[EÉ]DIA", c.get("DS_SIT_TOT_TURNO", ""), re.I)
               and not re.search(r"N[ÃA]O ELEITO", c.get("DS_SIT_TOT_TURNO", ""), re.I)]
    n = urna(v.get("nome"))
    civil = {norm(v.get("nome")), norm(v.get("nomeCompleto"))} - {""}
    for regra in (lambda c: urna(c["NM_URNA_CANDIDATO"]) == n,
                  lambda c: norm(c["NM_CANDIDATO"]) in civil,
                  lambda c: urna(c["NM_URNA_CANDIDATO"]).startswith(n + " "),
                  lambda c: set(n.split()) <= set(urna(c["NM_URNA_CANDIDATO"]).split())):
        for lista in (eleitos, cands):
            achou = [c for c in lista if regra(c)]
            if len(achou) > 1 and v.get("nomeCompleto"):
                achou = [c for c in achou if norm(c["NM_CANDIDATO"]) == norm(v["nomeCompleto"])] or achou
            if len({c["SQ_CANDIDATO"] for c in achou}) == 1:
                return achou
    return []


def carregar(nome):
    try:
        return json.load(open(DADOS / nome, encoding="utf-8"))
    except Exception:
        return {}


def main():
    if "--se-velho" in sys.argv:  # no robô diário: o TSE só muda com retificações, basta 1 vez por semana
        try:
            ult = json.load(open(DADOS / "tse_campanhas.json", encoding="utf-8"))["ultimaAtualizacao"]
            if (datetime.now() - datetime.fromisoformat(ult)).days < 7:
                print(f"  tse_campanhas.json de {ult[:10]} — ainda vale (refaz a cada 7 dias)")
                return
        except Exception:
            pass
    saida, faltam = {}, []
    candidatos = {}  # ano → lista de candidatos de MS
    for grupo, arq, chave, ano, cargos, ue in GRUPOS:
        if ano not in candidatos:
            candidatos[ano] = [r for r in ler_csv(f"{BASE}/consulta_cand/consulta_cand_{ano}.zip", f"consulta_cand_{ano}_MS.csv")]
            print(f"  {ano}: {len(candidatos[ano])} candidaturas em MS")
        cands = [c for c in candidatos[ano] if c["DS_CARGO"].upper() in cargos and (not ue or c["NM_UE"].upper() == ue)]
        for v in carregar(arq).get(chave, []):
            k = f"{grupo}|{v['nome']}"
            if k in saida:
                continue
            achou = casar(v, cands)
            sq = {c["SQ_CANDIDATO"] for c in achou}
            if len(sq) == 1:
                c = achou[0]
                saida[k] = {"ano": ano, "cargo": c["DS_CARGO"].title(), "nomeCompleto": c["NM_CANDIDATO"].title(),
                            "urna": c["NM_URNA_CANDIDATO"], "situacao": c.get("DS_SIT_TOT_TURNO", "").title(), "sq": c["SQ_CANDIDATO"],
                            "cpf6": cpf6(c.get("NR_CPF_CANDIDATO")),
                            "doadores": {}, "fornecedores": {}, "totalReceitas": 0.0, "totalDespesas": 0.0}
    for grupo, arq, chave, ano, cargos, ue in GRUPOS:
        for v in carregar(arq).get(chave, []):
            if f"{grupo}|{v['nome']}" not in saida and grupo != "senador":
                faltam.append(f"{grupo}|{v['nome']}")
    for k in [f"senador|{v['nome']}" for v in carregar("senadores_ms.json").get("senadores", [])]:
        if k not in saida:
            faltam.append(k)

    # chefes do Executivo: governador eleito em 2022 e prefeito(a) de Campo Grande eleito(a) em 2024
    for chave, ano_e, cargo_e, ue_e in (("executivo|Governador(a) de MS", 2022, "GOVERNADOR", None),
                                        ("executivo|Prefeito(a) de Campo Grande", 2024, "PREFEITO", "CAMPO GRANDE")):
        eleitos = [c for c in candidatos.get(ano_e, []) if c["DS_CARGO"].upper() == cargo_e and (not ue_e or c["NM_UE"].upper() == ue_e)
                   and re.match(r"ELEITO", c.get("DS_SIT_TOT_TURNO", "").upper())]
        if len({c["SQ_CANDIDATO"] for c in eleitos}) == 1:
            c = eleitos[0]
            saida[chave] = {"ano": ano_e, "cargo": c["DS_CARGO"].title(), "nomeCompleto": c["NM_CANDIDATO"].title(),
                            "urna": c["NM_URNA_CANDIDATO"], "situacao": c.get("DS_SIT_TOT_TURNO", "").title(), "sq": c["SQ_CANDIDATO"],
                            "cpf6": cpf6(c.get("NR_CPF_CANDIDATO")), "doadores": {}, "fornecedores": {}, "totalReceitas": 0.0, "totalDespesas": 0.0}
        else:
            print(f"  ⚠️ {chave}: {len(eleitos)} candidaturas eleitas encontradas")

    # eleição de 2026: todos os eleitos de MS (governador, senadores, deputados federais e estaduais)
    if 2026 not in candidatos:
        try:
            candidatos[2026] = [r for r in ler_csv(f"{BASE}/consulta_cand/consulta_cand_2026.zip", "consulta_cand_2026_MS.csv")]
            print(f"  2026: {len(candidatos[2026])} candidaturas em MS")
        except Exception as e:
            print(f"  ⚠️ 2026: {e}")
            candidatos[2026] = []
    ELEITO = re.compile(r"^ELEITO", re.I)
    for c in candidatos.get(2026, []):
        if c["DS_CARGO"].upper() in ("GOVERNADOR", "SENADOR", "DEPUTADO FEDERAL", "DEPUTADO ESTADUAL") and ELEITO.match(c.get("DS_SIT_TOT_TURNO", "")):
            k = f"eleito2026|{c['DS_CARGO'].title()}|{c['NM_URNA_CANDIDATO'].title()}"
            saida[k] = {"ano": 2026, "cargo": c["DS_CARGO"].title(), "nomeCompleto": c["NM_CANDIDATO"].title(),
                        "urna": c["NM_URNA_CANDIDATO"], "partido": c.get("SG_PARTIDO"), "situacao": c.get("DS_SIT_TOT_TURNO", "").title(),
                        "sq": c["SQ_CANDIDATO"], "cpf6": cpf6(c.get("NR_CPF_CANDIDATO")), "doadores": {}, "fornecedores": {},
                        "totalReceitas": 0.0, "totalDespesas": 0.0}
            if c["DS_CARGO"].upper() == "GOVERNADOR":
                saida["executivo|Governador(a) de MS (campanha de 2026)"] = saida[k]  # o mesmo registro: doadores de 2026
    print(f"  2026: {sum(1 for k in saida if k.startswith('eleito2026|'))} eleitos")

    # eleição anterior de quem se reelegeu (vereadores: 2020; deputados: 2018), pelo CPF + nome civil
    for ano_ant, grupos_ant in ((2020, ("vereador",)), (2018, ("estadual", "federal"))):
        if ano_ant not in candidatos:
            candidatos[ano_ant] = [r for r in ler_csv(f"{BASE}/consulta_cand/consulta_cand_{ano_ant}.zip", f"consulta_cand_{ano_ant}_MS.csv")]
            print(f"  {ano_ant}: {len(candidatos[ano_ant])} candidaturas em MS")
        idx = {(cpf6(c.get("NR_CPF_CANDIDATO")), norm(c["NM_CANDIDATO"])): c for c in candidatos[ano_ant]}
        so_nome = {}
        for c in candidatos[ano_ant]:
            so_nome.setdefault(norm(c["NM_CANDIDATO"]), []).append(c)
        for k, d in saida.items():
            if k.split("|")[0] in grupos_ant:
                # o arquivo de 2024 não traz o CPF: aí vale o nome civil completo, se for único no estado
                c = idx.get((d.get("cpf6"), norm(d["nomeCompleto"]))) if d.get("cpf6") else \
                    (so_nome.get(norm(d["nomeCompleto"])) or [None, None])[0] if len(so_nome.get(norm(d["nomeCompleto"]), [])) == 1 else None
                if c:
                    d["cpf6"] = d.get("cpf6") or cpf6(c.get("NR_CPF_CANDIDATO"))
                    d.setdefault("anteriores", []).append({"ano": ano_ant, "sq": c["SQ_CANDIDATO"], "cargo": c["DS_CARGO"].title(),
                                                           "situacao": c.get("DS_SIT_TOT_TURNO", "").title()})
    # frequência dos sobrenomes entre todos os candidatos de MS (pessoas únicas), para o teste de parentes
    pessoas = {}
    for lst in candidatos.values():
        for c in lst:
            pessoas[cpf6(c.get("NR_CPF_CANDIDATO")) or c["SQ_CANDIDATO"]] = norm(c["NM_CANDIDATO"])
    freq = {}
    for nm in pessoas.values():
        for w in set(nm.split()[1:]):
            if len(w) > 3:
                freq[w] = freq.get(w, 0) + 1
    sobrenomes = {w: freq.get(w, 0) for d in saida.values() for w in norm(d["nomeCompleto"]).split()[1:] if len(w) > 3}

    por_sq = {(d["ano"], d["sq"]): d for d in saida.values() if d.get("sq")}
    for d in saida.values():
        for a in d.get("anteriores", []):
            por_sq[(a["ano"], a["sq"])] = d
    for ano in sorted({a for (a, _) in por_sq}):
        zurl = f"{BASE}/prestacao_contas/prestacao_de_contas_eleitorais_candidatos_{ano}.zip"
        n = 0
        for r in ler_csv(zurl, f"receitas_candidatos_{ano}_MS.csv"):
            d = por_sq.get((ano, r["SQ_CANDIDATO"]))
            if not d:
                continue
            val = num(r["VR_RECEITA"])
            d["totalReceitas"] += val
            if "pessoas f" in r["DS_ORIGEM_RECEITA"].lower():
                nm = norm(r.get("NM_DOADOR_RFB") or r["NM_DOADOR"])
                if len(nm.split()) >= 2:
                    x = d["doadores"].setdefault(nm, [(r.get("NM_DOADOR_RFB") or r["NM_DOADOR"]).title(), 0.0, cpf6(r["NR_CPF_CNPJ_DOADOR"]), []])
                    x[1] = round(x[1] + val, 2)
                    if ano not in x[3]:
                        x[3].append(ano)
                    n += 1
        m = 0
        for r in ler_csv(zurl, f"despesas_contratadas_candidatos_{ano}_MS.csv"):
            d = por_sq.get((ano, r["SQ_CANDIDATO"]))
            if not d:
                continue
            val = num(r["VR_DESPESA_CONTRATADA"])
            d["totalDespesas"] += val
            doc = re.sub(r"\D", "", r["NR_CPF_CNPJ_FORNECEDOR"])
            if len(doc) == 14:
                x = d["fornecedores"].setdefault(doc, [(r.get("NM_FORNECEDOR_RFB") or r["NM_FORNECEDOR"]).strip(), 0.0, r["DS_DESPESA"][:80], []])
                x[1] = round(x[1] + val, 2)
                if ano not in x[3]:
                    x[3].append(ano)
                m += 1
        print(f"  {ano}: {n} doações de pessoas físicas e {m} despesas com empresas dos parlamentares atuais")
    # bens declarados ao TSE em cada candidatura (2018 a 2026), para a evolução do patrimônio
    bens = {}
    for ano_b in (2018, 2020, 2022, 2024, 2026):
        try:
            for r in ler_csv(f"{BASE}/bem_candidato/bem_candidato_{ano_b}.zip", f"bem_candidato_{ano_b}_MS.csv"):
                b = bens.setdefault((ano_b, r["SQ_CANDIDATO"]), [0.0, 0])
                b[0] += num(r["VR_BEM_CANDIDATO"])
                b[1] += 1
        except Exception as e:
            print(f"  ⚠️ bens {ano_b}: {e}")
        if ano_b not in candidatos:
            try:
                candidatos[ano_b] = [r for r in ler_csv(f"{BASE}/consulta_cand/consulta_cand_{ano_b}.zip", f"consulta_cand_{ano_b}_MS.csv")]
            except Exception:
                candidatos[ano_b] = []
    print(f"  bens: {len(bens)} candidaturas com bens declarados")
    idx_cpf, idx_nome = {}, {}
    for ano_b in (2018, 2020, 2022, 2024, 2026):
        for c in candidatos.get(ano_b, []):
            idx_cpf.setdefault((ano_b, cpf6(c.get("NR_CPF_CANDIDATO")), norm(c["NM_CANDIDATO"])), []).append(c)
            idx_nome.setdefault((ano_b, norm(c["NM_CANDIDATO"])), []).append(c)
    for d in {id(v): v for v in saida.values()}.values():
        serie = []
        for ano_b in (2018, 2020, 2022, 2024, 2026):
            achou = idx_cpf.get((ano_b, d.get("cpf6"), norm(d["nomeCompleto"]))) if d.get("cpf6") else None
            if not achou:  # 2024 não traz CPF: vale o nome civil completo, se for único no estado
                achou = idx_nome.get((ano_b, norm(d["nomeCompleto"])))
                achou = achou if achou and len({c["SQ_CANDIDATO"] for c in achou}) == 1 else None
            if achou:
                c = achou[0]
                b = bens.get((ano_b, c["SQ_CANDIDATO"]))
                serie.append({"ano": ano_b, "cargo": c["DS_CARGO"].title(), "situacao": c.get("DS_SIT_TOT_TURNO", "").title(),
                              "patrimonio": round(b[0], 2) if b else 0.0, "itens": b[1] if b else 0})
        d["patrimonio"] = serie
    for d in {id(v): v for v in saida.values()}.values():
        d["totalReceitas"], d["totalDespesas"] = round(d["totalReceitas"], 2), round(d["totalDespesas"], 2)
        d.pop("sq", None)
        for a in d.get("anteriores", []):
            a.pop("sq", None)
    # arquivo público (sem CPF parcial dos doadores): eleitos de 2026 e evolução do patrimônio
    def pessoa_pub(k, d):
        return {"chave": k, "nome": k.split("|")[-1] if not k.startswith("eleito2026|") else d["urna"].title(), "nomeCompleto": d["nomeCompleto"],
                "cargo": d.get("cargo"), "partido": d.get("partido"), "patrimonio": d.get("patrimonio", [])}
    eleitos = []
    for k, d in saida.items():
        if k.startswith("eleito2026|"):
            eleitos.append({**pessoa_pub(k, d), "situacao": d["situacao"], "receitas": d["totalReceitas"], "despesas": d["totalDespesas"],
                            "doadores": [{"nome": v[0], "valor": v[1]} for v in sorted(d["doadores"].values(), key=lambda v: -v[1])[:10]],
                            "fornecedores": [{"cnpj": c, "nome": v[0], "valor": v[1], "descricao": v[2]}
                                             for c, v in sorted(d["fornecedores"].items(), key=lambda kv: -kv[1][1])[:10]]})
    atuais = [pessoa_pub(k, d) for k, d in saida.items() if not k.startswith(("eleito2026|", "executivo|"))]
    doad26, forn26 = {}, {}
    for k, d in saida.items():
        if k.startswith("eleito2026|"):
            for nm, v in d["doadores"].items():
                x = doad26.setdefault(nm, {"nome": v[0], "valor": 0.0, "candidatos": []})
                x["valor"] += v[1]
                x["candidatos"].append(d["urna"].title())
            for c, v in d["fornecedores"].items():
                x = forn26.setdefault(c, {"cnpj": c, "nome": v[0], "valor": 0.0, "candidatos": []})
                x["valor"] += v[1]
                x["candidatos"].append(d["urna"].title())
    (DADOS / "eleicoes.json").write_text(json.dumps({
        "ultimaAtualizacao": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "fonte": "TSE — Portal de Dados Abertos (candidaturas, bens declarados e prestação de contas)",
        "eleitos2026": sorted(eleitos, key=lambda x: ("GDSF".find(x["cargo"][0]), -x["receitas"])),
        "atuais": atuais,
        "maioresDoadores2026": sorted(({**v, "valor": round(v["valor"], 2)} for v in doad26.values()), key=lambda v: -v["valor"])[:40],
        "maioresFornecedores2026": sorted(({**v, "valor": round(v["valor"], 2)} for v in forn26.values()), key=lambda v: -v["valor"])[:40]},
        ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"✅ eleicoes.json — {len(eleitos)} eleitos em 2026, patrimônio de {len(atuais)} parlamentares atuais")
    if len([k for k in saida if not k.startswith(("executivo|", "eleito2026|"))]) < 40:
        print(f"❌ só {len(saida)} parlamentares encontrados no TSE — arquivo mantido")
        sys.exit(1)
    (DADOS / "tse_campanhas.json").write_text(json.dumps({
        "ultimaAtualizacao": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "fonte": "TSE — Portal de Dados Abertos (prestação de contas eleitorais de candidatos)",
        "naoEncontrados": faltam, "candidatosMS": len(pessoas), "sobrenomes": sobrenomes, "parlamentares": saida}, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"✅ tse_campanhas.json — {len(saida)} parlamentares; sem correspondência no TSE: {', '.join(faltam) or 'nenhum'}")


if __name__ == "__main__":
    main()
