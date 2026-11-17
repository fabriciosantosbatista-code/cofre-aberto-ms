# Auditoria completa — Cofre Aberto MS

**Data:** 17/11/2026 (dados da coleta das 13h14 de Campo Grande)
**Escopo:** painel (`cofre-aberto-ms.html`), página inicial, ~2.200 páginas geradas, 60+ scripts de coleta e geração (`scripts/`), 28 conjuntos de dados (`dados/`), robôs do GitHub Actions (`.github/workflows/`).
**Como foi feita:** recalculando os números a partir dos registros individuais, comparando com as fontes oficiais que foi possível acessar, abrindo o site no navegador (computador, tablet e celular) e lendo o código. Onde algo **não** foi verificado, isso está dito.

Legenda: **[COMPROVADO]** = erro confirmado com evidência · **[SUSPEITA]** = indício, sem prova · **[NÃO VERIFICADO]** = não foi possível checar.

---

## A. Resumo geral

O site está, no geral, **matematicamente consistente**. As 570 conferências automáticas de soma, total, contagem e percentual fecham. Os 15 números principais da tela batem com os arquivos de dados. Onde comparei com a fonte oficial, os valores bateram centavo por centavo: Governo de MS, Assembleia, Senado, Tesouro/Siconfi, CGU, PNCP e TJMS/DadosJusBr.

A auditoria encontrou, porém, **um erro financeiro grave que estava no ar o ano todo**:
- O gasto da cota dos deputados federais estava **subestimado em 4% a 33%**, porque as passagens aéreas do SIGEPA não eram somadas.
- Também havia **CPF completo de cerca de 12 mil pessoas físicas** publicado.

Os dois foram corrigidos. Também havia números com rótulo errado e totais que misturavam coisas diferentes, por exemplo compra de imóvel somada como aluguel.

Confiabilidade geral depois das correções: **boa**. Há duas limitações estruturais:
1. A verba indenizatória dos vereadores de CG vem de leitura automática (OCR) de PDFs e não pôde ser conferida com a fonte.
2. A Prefeitura de CG não publica empenhos novos desde 02/10/2026.

---

## B. Erros críticos (números financeiros errados ou dado pessoal exposto)

| # | Erro | Evidência | Situação |
|---|---|---|---|
| B1 | **CEAP dos deputados federais subestimada** (MS e Brasil) [COMPROVADO]. O arquivo anual da Câmara (`Ano-2026.csv.zip`) deixou de trazer as passagens do SIGEPA, que contam na cota e estão na API. | Marcos Pollon: site R$ 223.347,92 (204 notas) = CSV; API: 319 notas, R$ 110.762,93 só em passagens. Vander Loubet: faltavam R$ 82.663,86. | **Corrigido** em `scripts/coletar_dados.py` (`sigepa_pela_api`, chamada em `carregar_ceap_bulk`). Hoje 5 dos 8 batem centavo por centavo com a API; os 3 restantes têm diferença de 2 centavos (arredondamento) ou de estornos lançados depois da coleta. |
| B2 | **API da Câmara devolve `valorLiquido` com sinal trocado** [COMPROVADO]. R$ 20.000 aparece como −20.000 nas despesas comuns. O plano B do coletor e o do painel somariam totais negativos. | Resposta da API para o deputado 204358, mês 1. | **Corrigido**: regra única `_valor_api` (`coletar_dados.py`) e `valorCamara` (painel). Nas passagens o sinal da API está certo (negativo = estorno). |
| B3 | **CPF completo de pessoas físicas publicado** (LGPD) [COMPROVADO]. Cerca de 12 mil ocorrências em 46 arquivos: fornecedores PF dos deputados federais e estaduais, 4.283 pagamentos da Prefeitura a pessoas (a aba mostrava o número), uma linha de credor do Estado e 1 página de deputado. | Busca por padrão de CPF nos dados e nas páginas. | **Corrigido**: `scripts/mascarar_cpf.py` (formato `***.123.456-**`), que roda em toda coleta. O teste `tests/test_integridade_dados.py` falha se aparecer CPF completo. A primeira versão do script mascarou por engano um número de fatura e um código no formato de CNPJ; foi restrita às colunas de CPF/CNPJ e revertida antes de publicar. |
| B4 | **Aluguéis somava compra de imóvel** [COMPROVADO]. O art. 74, V da Lei 14.133 vale para alugar **e** comprar; entravam a compra da sede do CREF (R$ 3.985.000) e de 50% de um imóvel em Paranaíba (R$ 2.150.136). | PNCP, objeto "Aquisição de imóvel…". | **Corrigido** em `scripts/coletar_alugueis.py` (filtro `COMPRA`): R$ 45,6 mi / 208 → **R$ 39,4 mi / 206**. |

## C. Erros importantes (rótulo, contagem, apresentação que induz a erro)

| # | Erro | Evidência | Situação |
|---|---|---|---|
| C1 | **Emendas: "1.363 pagamentos" ao lado do total de MS** contava também pagamentos de parlamentares de MS **em outros estados** [COMPROVADO]. | CGU (arquivo por favorecido): 1.054 linhas em MS em 2026, 2 com valor zero. | **Corrigido** (`coletar_emendas_municipios.py`): **1.052**. O total (R$ 624.237.391,36) já estava certo. |
| C2 | **Governo de MS chamado de "todas as secretarias"** sem dizer que é só o Poder Executivo [COMPROVADO]. | Siconfi RREO (jan–ago): Tesouro R$ 18,39 bi pagos (todos os Poderes) × site R$ 16,12 bi. TJ, ALEMS, MP e TCE não estão no portal do Estado. | **Corrigido o texto** da aba: Poder Executivo + Defensoria; diz que os outros Poderes ficam de fora e que o total inclui despesas intraorçamentárias. |
| C3 | **Despesas intraorçamentárias sem aviso** [COMPROVADO, metodologia]. A Prefeitura paga R$ 279 mi de contribuição patronal ao IMPCG, que depois paga aposentadorias (o mesmo dinheiro aparece duas vezes no total). No Estado, a AGEPREV é o maior órgão (R$ 4,3 bi). | `prefeitura.json`, categoria "08 - CONTRIBUIÇÕES PREVIDENCIÁRIAS - RPPS" paga ao CNPJ do IMPCG; RREO Anexo 1 separa "intra" (R$ 1,65 bi pagos até ago no Estado). | **Texto corrigido** nas duas abas. O total continua igual ao do portal oficial. Separar o valor fica como melhoria (J2). |
| C4 | **Prefeitura: "Notas fiscais pagas" (12.951)** eram empenhos com pagamento, não notas fiscais [COMPROVADO]. | Estrutura de `prefeitura.json`. | **Corrigido o rótulo**: "Empenhos com pagamento". |
| C5 | **Senadores: nº de notas fiscais** contava o campo de resumo antigo (8, 9, 0) em vez das notas CEAPS (105, 238, 166) [COMPROVADO]. | `senadores_ms.json`: `despesas` × `notasCeaps`. | **Corrigido** no painel. |
| C6 | **Data de corte escondida**: Publicidade e Entidades usam dados da Prefeitura parados em 02/10, sem dizer isso [COMPROVADO]. | `ultimoEmpenho` = 2026-10-02. | **Corrigido**: as duas abas mostram "pagamentos até 02/10/2026". |
| C7 | **Texto do OCR nas notas dos vereadores de CG** [COMPROVADO]: 504 nomes de fornecedor ("/26 ROSENEIDE GOULART") e 1.142 descrições ("“+ — NFOO617/U «|") com sujeira. | `camara_municipal.json`. | **Corrigido** por `scripts/limpar_notas_camara_cg.py`. Usa a razão social da Receita só quando ela tem palavra em comum com o nome lido (protege contra CNPJ lido errado). O texto original fica em `fornecedorOCR` / `descricaoOCR`. Restam 53 nomes e 149 descrições com resíduos. |
| C8 | **Regressão evitada durante a auditoria**: a limpeza dos nomes e a inclusão das passagens fariam o boletim semanal anunciar **2.513 "notas novas"** (eram notas antigas com nome corrigido e passagens de janeiro a novembro). | Execução local de `gerar_boletim.py`. | **Corrigido antes de publicar**: o boletim compara pelo nome original; as 703 passagens foram marcadas como já vistas. O boletim ficou com 60 notas novas (R$ 92.798,07). |
| C9 | **Post de supersalários no Instagram** listava pagamento eventual (rescisão, sem salário-base: R$ 298 mil a um auditor da SES) como se fosse salário. | `supersalarios.json`, ranking[0]: base 0, descontos 0. | **Corrigido** em `gerar_posts_instagram.py`. O painel já marcava esse caso como "pagamento eventual no mês". |

## D. Erros menores

- **D1.** Notas repetidas em Camila Jara (7 grupos com mesma data, fornecedor, valor e número). Na API da Câmara são registros distintos (códigos de documento diferentes): reflete a fonte, não é duplicação do site. Fica como aviso no teste.
- **D2.** As notas antigas dos vereadores ainda têm 53 nomes e 149 descrições com restos do OCR.
- **D3.** A página do empenho da Prefeitura (SIG) mostra um bloco de depuração do sistema dela ("#escapeWhenCastingToString"). É problema da fonte, não do site.
- **D4.** O painel baixa ~1 MB ao abrir (548 KB de HTML sem compressão); a aba Deputados federais do Brasil baixa 603 KB. Está aceitável.

## E. Dados divergentes das fontes oficiais

| Informação | Site | Fonte oficial | Fonte / data | Diferença | Causa |
|---|---|---|---|---|---|
| CEAP dep. federais MS (antes da correção) | ex.: Pollon R$ 223.347,92 | R$ 334.110,85 | API Câmara, 17/11 | −R$ 110.762,93 | Passagens SIGEPA fora do arquivo anual (B1). **Corrigido.** |
| CEAP Rodolfo Nogueira (depois da correção) | R$ 467.645,30 | R$ 466.282,31 | API Câmara, 17/11 tarde | +R$ 1.362,99 | Estornos de passagem lançados depois da coleta das 13h14; a próxima coleta atualiza. |
| CEAPS Tereza Cristina (antes da coleta de hoje) | R$ 279.461,87 | R$ 287.414,80 | adm.senado.gov.br | −R$ 7.952,93 | Notas novas no Senado depois da coleta anterior. **Já atualizado.** |
| Despesa paga Governo MS × RREO (jan–ago) | R$ 16,12 bi | R$ 18,39 bi (todos os Poderes) / R$ 16,74 bi (sem intra) | Siconfi RREO Anexo 1, 4º bim. | — | Métodos diferentes: o portal do Estado só tem o Executivo; o RREO conta todos os Poderes e só os empenhos do ano. **Não é erro**; texto esclarecido (C2). |
| Emendas: nº de pagamentos | 1.363 | 1.054 (1.052 com valor) | CGU, arquivo por favorecido | +309 | Contava pagamentos fora de MS (C1). **Corrigido.** |
| Supersalários TJMS: "outras verbas" | R$ 10.158.515,57 | R$ 10.581.229,78 | DadosJusBr, 09/2026 | −R$ 422.714,21 | Igual ao valor das diárias, que o site tira de propósito (reembolso, padrão CNJ), como explica a metodologia. **Não é erro.** |

**Conferências que bateram exatamente** (valor do site = fonte):
- **Governo de MS:** pago R$ 21.246.162.434,07 e empenhado R$ 23.289.268.323,60, consulta nova ao portal do Estado.
- **ALEMS:** os 25 deputados, total R$ 13.075.996,43.
- **Senado:** Nelsinho Trad e Soraya Thronicke, centavo por centavo.
- **Câmara dos Deputados:** 5 de 8 deputados federais (os outros 3 com diferença explicada acima).
- **Siconfi (ICMS do Estado):** os 12 meses de set/2025 a ago/2026.
- **CGU (emendas):** total de MS (R$ 624.237.391,36) e Campo Grande (R$ 147.671.236,98).
- **PNCP:** 12 de 12 amostras (7 shows e 5 aluguéis).
- **DadosJusBr (TJMS):** quantidade de magistrados (227), salário-base total (R$ 8.910.028,25) e maior líquido (R$ 102.153,16).
- **Prefeitura de CG:** o maior empenho do ano, R$ 430.384.145,43 pagos (página oficial do empenho).

## F. Dados desatualizados ou atrasados

| Dado | Último dado disponível | Situação |
|---|---|---|
| **Prefeitura de CG — empenhos** | 02/10/2026 (46 dias) | **Atrasado na fonte.** O SIG não publica empenhos novos desde então; o site continua atualizando o "pago" dos empenhos antigos. Pedido de LAI pronto na aba. Afeta também Publicidade, Entidades e Aluguéis (parte da Prefeitura). |
| Câmara de Sonora | 27/10/2026 | Portal fora do ar (fonte). |
| Verba indenizatória dos vereadores de CG | até set/2026 | Atraso normal da Câmara na publicação dos PDFs. |
| Arrecadação (Siconfi) | ago/2026 | Normal: o RREO é bimestral; o de set–out sai até 30/11. |
| Supersalários / Judiciário | folhas de 08 a 10/2026 | Normal: as folhas saem com 1 a 2 meses de atraso. |
| STF | contracheques até 08/2026 | Atraso do DadosJusBr. |
| Benefícios fiscais | lista de 2025 | Normal: a SEFAZ publica o ano anterior (a de 2025 saiu em maio/2026). |
| Todas as demais (Câmara, Senado, ALEMS, Governo MS, PNCP, emendas, votações, produção) | 12 a 17/11/2026 | Em dia. |

O site distingue atraso da fonte de falha de coleta (`dados/status_fontes.json`), e o robô de verificação abre alerta quando passa do limite.

## G. Problemas técnicos

1. **Injeção de HTML (XSS)** [COMPROVADO o risco, sem exploração encontrada]:
   - cerca de 120 pontos do painel montam HTML com texto vindo das fontes (nomes de fornecedor, descrições, cidades) sem tratar.
   - **Corrigido** com `neutralizarTexto` aplicado a todo JSON carregado pelo painel (arquivos do site e APIs ao vivo): "<" e ">" viram caracteres inofensivos.
   - As páginas estáticas já tratavam o texto (`e()` / `html.escape`).
2. **Permissões do robô:** o workflow principal não declarava permissões e herdava o padrão do repositório. **Corrigido**: `permissions: contents: write` (a verificação mantém `issues: write` só no próprio job).
3. **Senhas e chaves:** nenhuma encontrada no código ou nos dados. A chave da API da CGU vem de Secret. A chave Pix aleatória do Apoie aparece em comentário; não é segredo.
4. **Precisão monetária:** os valores são `float` (Python/JS) arredondados a 2 casas na gravação. Nas somas conferidas não houve diferença acima de 1 centavo. Risco baixo; ver J5.
5. **Plano B do painel para a Câmara:** se o arquivo do site falhar, o painel consulta a API ao vivo. Agora usa a regra de sinal corrigida (B2).
6. **Links internos:** 2.232 páginas varridas, nenhum link interno quebrado (os 2 apontados eram modelos montados por programa).

## H. Correções realizadas

**Arquivos alterados:**
- **Coletores:** `scripts/coletar_dados.py` (passagens SIGEPA, valor da API), `scripts/coletar_emendas_municipios.py` (contagem em MS), `scripts/coletar_alugueis.py` (fora as compras; CPF mascarado), `scripts/coletar_cnpj.py` (locadores).
- **Geradores:** `scripts/gerar_entidades.py` (data de corte), `scripts/gerar_analises.py`, `scripts/gerar_boletim.py`, `scripts/gerar_atividade.py` (comparação estável), `scripts/gerar_posts_instagram.py` (sem pagamento eventual).
- **Scripts novos:** `scripts/mascarar_cpf.py` e `scripts/limpar_notas_camara_cg.py`.
- **Painel:** `cofre-aberto-ms.html`. Textos de Governo MS, Prefeitura, Publicidade e Entidades; rótulo "Empenhos com pagamento"; nº de notas dos senadores; `valorCamara`; `neutralizarTexto`.
- **Robôs:** `.github/workflows/atualizar.yml` (passos de mascaramento, limpeza e teste; permissões) e `.github/workflows/testar-site.yml` (teste de integridade a cada mudança).
- **Dados:** regenerados a partir dos dados oficiais. Nenhum registro foi apagado; o texto original do OCR fica guardado.

**Testes criados e executados** (todos depois das correções):

| Teste | O que faz | Resultado |
|---|---|---|
| `tests/test_integridade_dados.py` (novo) | Refaz as somas e totais de todos os conjuntos; procura duplicatas, negativos, CPF completo, NaN | **570 OK, 0 erros**, 2 avisos (D1 e o atraso da Prefeitura) |
| `tests/tela_x_dados.js` (novo) | Compara 15 números da tela com o recalculado do JSON | **15/15 iguais** |
| `tests/filtros.js` (novo) | Filtros e buscas (Aluguéis, Benefícios, Shows, Votos e projetos, busca global) contra contagem direta nos dados | **8/8 certos** |
| `tests/smoke.js` (existente) | Teste de fumaça do painel | **OK** |
| Varredura das 35 abas (Playwright) | Erros de programa, números vazios, "undefined"/"NaN" | **35/35 OK** |
| Celular (iPhone 13) e tablet (iPad Mini) | Página estoura para o lado? | **Nenhuma aba** (tabelas largas rolam dentro da própria caixa) |
| Comparação com fontes oficiais | Seção E | ver seção E |

## I. Pendências (não foi possível corrigir ou validar)

1. **[NÃO VERIFICADO] Verba indenizatória e folha da Câmara de CG** contra a fonte:
   - o portal (Fiorilli, 45.225.6.93) não abre deste ambiente, só pelos servidores do GitHub;
   - os valores vêm de OCR de PDFs. A conferência interna fecha (ato 27 + ato 28 = pago; meses = pago), mas o OCR pode ter lido algum valor errado.
   - **Recomendação:** conferir uma amostra de PDFs à mão ou pelo diagnóstico do GitHub.
2. **[NÃO VERIFICADO] Outras fontes:** contratos da Prefeitura, Presidência (cartão), TSE (eleições e patrimônio), TRT24/TRE, STF, câmaras do interior, obras do Estado e votações. Para essas, só a consistência interna foi checada.
3. **[NÃO VERIFICADO] Benefícios fiscais:** o site da SEFAZ é bloqueado neste ambiente; a planilha foi lida pelo robô no GitHub. Contagens internas conferidas.
4. **Regras da auditoria:** os ~30 testes de sinal (`gerar_auditoria.py`) não foram revalidados um a um nesta rodada.
5. **Intraorçamentárias:** o valor não foi separado em número próprio; só foi explicado no texto (C3).
6. **Prefeitura parada em 02/10:** depende da Prefeitura (LAI).

## J. Melhorias recomendadas

1. **J1.** Conferir por amostragem os PDFs da Câmara de CG e registrar a taxa de erro do OCR na metodologia.
2. **J2.** Mostrar ao lado dos totais do Estado e da Prefeitura o valor **sem as despesas intraorçamentárias** (pelo RREO do Tesouro), para comparar com o que é gasto de fato.
3. **J3.** Rodar `tests/tela_x_dados.js` e `tests/filtros.js` também no robô diário (hoje só o teste de integridade roda nele).
4. **J4.** Alertar quando o arquivo anual da Câmara e a API divergirem em número de notas, o que teria pegado o erro do SIGEPA em janeiro.
5. **J5.** Guardar valores monetários em centavos inteiros nos arquivos novos (sem risco hoje, mas elimina a classe de problema).
6. **J6.** Fixar as versões das bibliotecas Python do robô (`requests`, `openpyxl`, `Pillow`) e as actions do GitHub por SHA.
7. **J7.** Validar no painel que links vindos dos dados começam com `https://` (as fontes são oficiais; é defesa em profundidade).
8. **J8.** Separar em arquivo próprio os dados dos deputados federais do Brasil, que só são usados numa aba (603 KB).

## K. Nota de confiabilidade (0 a 100)

| Área | Nota | Justificativa |
|---|---|---|
| **Precisão dos dados** | **78** | Onde houve comparação com a fonte oficial, bateu centavo por centavo (Estado, ALEMS, Senado, Siconfi, CGU, PNCP, TJMS). Mas um erro grave (B1) ficou no ar o ano todo, e a Câmara de CG (OCR) e várias fontes não foram conferidas com a origem. |
| **Atualização** | **80** | A maioria das fontes está em dia e o site separa atraso da fonte de falha de coleta. A Prefeitura parada há 46 dias afeta 4 abas; o site agora avisa a data de corte. |
| **Integridade dos cálculos** | **90** | 570 conferências de soma e total fecham, tela = dados em 15 de 15, filtros corretos. Desconta: contagens com rótulo errado (C1, C4, C5) e somas que misturavam conceitos (B4, C3), todas encontradas só nesta auditoria. |
| **Funcionamento técnico** | **86** | 35 abas sem erro, responsivo, links internos íntegros, robôs com recuperação de falha e alerta. Desconta: dependência de OCR, plano B que usava a regra de sinal errada (corrigido) e a regressão do boletim, pega antes de publicar. |
| **Transparência das fontes** | **85** | Cada aba mostra fonte, link e data; a metodologia documenta as regras, e estimativas como o Impostômetro e a equipe estimada são marcadas. Desconta: Executivo × todos os Poderes e as intraorçamentárias só ficaram explícitos agora. |
| **Segurança** | **75** | Sem senhas expostas e sem servidor próprio (site estático, sem banco de dados ou SQL). Mas havia CPF completo publicado (corrigido hoje) e HTML montado com texto externo sem tratamento (corrigido hoje). Faltam política de segurança de conteúdo (CSP) e versões fixadas das dependências. |

**Observação sobre "banco de dados":** o projeto não usa banco de dados. Os dados ficam em arquivos JSON versionados no Git, o que deixa todo o histórico de cada número auditável e reversível. Por isso não se aplicam testes de SQL injection nem de relacionamento entre tabelas; foram feitas as checagens equivalentes (duplicatas, chaves, somas entre arquivos).
