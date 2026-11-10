# Cofre Aberto MS 🔓

**Transparência pública de Mato Grosso do Sul**

Fiscalize os gastos de vereadores, deputados estaduais, deputados federais e senadores de MS — com notas fiscais reais, CEAP 2026 e folha de pessoal.

🌐 **Site:** https://cofreabertoms.com.br

---

## O que está catalogado

| Fonte | Dados | Atualização |
|---|---|---|
| Câmara Municipal CG | 29 vereadores, verba indenizatória, 150 notas fiscais | Manual |
| ALEMS | 26 dep. estaduais, CEAP + 2.623 notas fiscais | **Automática** (diária) |
| Câmara Federal | 8 dep. federais de MS + 513 nacionais, CEAP ao vivo | **Automática** (diária) |
| Senado Federal | 3 senadores de MS + 81 nacionais, CEAPS | **Automática** (diária) |

---

## Atualização automática

O GitHub Actions roda todo dia às **4h23 de Brasília** (07:23 UTC — horário escolhido para fugir da fila do GitHub) e:
1. Coleta dados das APIs públicas da Câmara e do Senado
2. Baixa o CSV de CEAP da ALEMS
3. Atualiza os JSONs em `dados/`
4. Rebuilda o HTML com os dados novos
5. Commita e faz push — o Netlify detecta e faz deploy automático

### Análises geradas a cada coleta (`scripts/gerar_analises.py`)

- **Conexões entre fornecedores** (`dados/conexoes_fornecedores.json`, aba *Conexões*):
  empresas que receberam de 2+ pagadores públicos de MS (vereadores de CG,
  deputados estaduais e federais, senadores, Prefeitura). Só pessoa jurídica com
  CNPJ válido (dígito verificador) — CPFs ficam de fora —, filiais agrupadas pela
  raiz do CNPJ. Enquadramento sempre de **conexão**, não de suspeita.
- **Evolução mensal** (`dados/evolucao_mensal.json`, aba *Evolução*): gasto mês a
  mês em 2026 x 2025 e ranking de quem acelerou os gastos. O ano anterior vem de
  `dados/historico_2025.json`, gerado uma vez por `scripts/gerar_historico.py 2025`
  (Câmara/Senado/ALEMS; a Câmara CG não tem histórico em formato aproveitável).
- **Feeds RSS** (`dados/feeds/<grupo>-<nome>.xml` + `todas.xml`): notas fiscais mais
  recentes de cada parlamentar de MS. No painel, o botão **🔔 Seguir notas novas**
  mostra o endereço para leitor de RSS ou serviço de RSS por e-mail.
- **Links diretos**: `cofre-aberto-ms.html#aba=deputados-estaduais&p=Zeca%20do%20PT`
  abre o parlamentar (é o que o botão "Copiar link" gera).

### Página de cada parlamentar (`scripts/gerar_paginas_parlamentares.py`)

Uma página estática por parlamentar — boa para o Google e com prévia (foto,
nome e valor gasto) ao compartilhar no WhatsApp/redes:

| Endereço | Quem |
|---|---|
| `/vereador/<nome>/` | 29 vereadores de Campo Grande |
| `/deputado-estadual/<nome>/` | deputados estaduais de MS |
| `/deputado-federal/<nome>/` | 513 deputados federais |
| `/senador/<nome>/` | 81 senadores |

Cada página tem: totais do ano, % da cota, comparação com o ano anterior,
gráfico mês a mês, gastos por categoria, últimas notas fiscais, fornecedores em
comum com outros políticos, botões de WhatsApp, painel e RSS. Há um índice por
grupo (`/vereador/` etc.), o `sitemap.xml` é regenerado com todas as páginas e
as fotos embutidas nos JSONs viram arquivos em `fotos/p/` (a prévia precisa de
URL de imagem). Roda no job de commit da coleta diária; só reescreve o que mudou.

### Monitoramento (alerta quando algo para)

Os coletores mantêm o dado anterior quando uma fonte falha — então o Actions
pode ficar ✅ com o site desatualizado. Por isso, ao fim de cada coleta, o job
`verificar` roda:

- **`scripts/verificar_dados.py`** — olha o conteúdo dos JSONs: data da nota/
  empenho mais recente de cada fonte, mês de referência da folha dos tribunais,
  contagens esperadas (29 vereadores, 8 deputados federais, 3 senadores…) e
  quedas bruscas em relação à coleta anterior. ❌ erro = fonte principal parada;
  ⚠️ aviso = fonte secundária (câmaras do interior).
- **`tests/smoke.js`** — abre o site num navegador (desktop e celular), clica em
  todas as abas e em todos os parlamentares de MS e falha com erro de
  JavaScript, `NaN`/`undefined` na tela, detalhe que não abre ou rolagem lateral.

Se houver erro, o run fica vermelho (o GitHub envia e-mail) e a issue
**"⚠️ Alerta de dados"** (label `alerta-dados`) é aberta com o relatório; ela é
atualizada a cada coleta e fecha sozinha quando tudo volta ao normal. O teste
do painel também roda a cada push que muda HTML ou scripts (workflow
*Testar site*). Para rodar localmente:

```bash
python3 scripts/verificar_dados.py
python3 -m http.server 8000 & node tests/smoke.js http://localhost:8000/
```

### Como configurar do zero

#### 1. Fork / Clone este repositório
```bash
git clone https://github.com/SEU_USUARIO/cofre-aberto-ms.git
cd cofre-aberto-ms
```

#### 2. Configurar Netlify
- Acesse [app.netlify.com](https://app.netlify.com)
- **Add new site → Import from Git → GitHub**
- Selecione este repositório
- Build command: *(vazio)*
- Publish directory: `.`
- **Deploy site**

A partir daí, todo `git push` faz deploy automático no Netlify.

#### 3. Ativar o GitHub Actions
O workflow já está em `.github/workflows/atualizar.yml`.
Acesse **Actions** no repositório e clique em **Enable**.

Para rodar manualmente: Actions → "Atualizar dados" → **Run workflow**.

#### 4. Rodar localmente
```bash
pip install requests
python scripts/coletar_dados.py   # coleta dados das APIs
python scripts/rebuild_html.py    # atualiza o HTML
```

---

## Estrutura do projeto

```
cofre-aberto-ms/
├── index.html                    ← Landing page
├── cofre-aberto-ms.html          ← Painel completo
├── netlify.toml                  ← Configuração do Netlify
├── favicon.svg / favicon.ico     ← Ícones
├── og-image.png                  ← Imagem para compartilhamento
├── logo.svg                      ← Logo vetorial
│
├── dados/                        ← JSONs atualizados automaticamente
│   ├── camara_municipal.json     ← Vereadores CG (manual)
│   ├── deputados_estaduais_ms.json ← ALEMS (automático)
│   ├── deputados_federais_ms.json  ← API Câmara (automático)
│   ├── deputados_federais_brasil.json ← API Câmara (automático)
│   ├── senadores_ms.json         ← API Senado (automático)
│   ├── senadores_brasil.json     ← API Senado (automático)
│   ├── ceap_notas_estaduais.json ← Notas ALEMS (manual)
│   └── status.json               ← Última atualização
│
├── fotos/                        ← Fotos dos vereadores (TSE 2024)
│
└── scripts/
    ├── coletar_dados.py          ← Coleta das APIs públicas
    └── rebuild_html.py           ← Atualiza o HTML com novos dados
│
└── .github/workflows/
    └── atualizar.yml             ← GitHub Actions (roda todo dia 6h BRT)
```

---

## Fontes de dados

| Dado | Fonte | API |
|---|---|---|
| Dep. Federais | dadosabertos.camara.leg.br | ✅ REST pública |
| Senadores | adm.senado.gov.br/ergon-ng-reports | ✅ REST pública |
| CEAP ALEMS | consulta.transparencia.al.ms.gov.br/ceap | ✅ CSV público |
| Vereadores CG | 45.225.6.93:8079 (Fiorilli) | ❌ Sem API — coleta manual |
| Fotos candidatos | divulgacandcontas.tse.jus.br | ✅ REST pública |

---

## Licença

Dados públicos. Código sob licença MIT.

Desenvolvido com ❤️ para a transparência pública de Mato Grosso do Sul.
