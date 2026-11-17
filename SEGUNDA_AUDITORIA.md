# Segunda auditoria — confiabilidade, rastreabilidade e monitoramento contínuo

**Data:** 17/11/2026 · **Escopo:** itens 1 a 8 da segunda etapa e implantação do ICP (Índice de Confiabilidade Pública).
**Base de comparação:** `AUDITORIA_COMPLETA.md` (primeira auditoria, mesma data).

Neste relatório, **comprovado** significa que foi conferido na fonte oficial ou reproduzido por teste. **Suspeito** significa que o sistema marcou o item, mas ninguém conferiu manualmente. Nenhum valor publicado foi alterado por esta etapa: os validadores só **marcam**.

---

## 1. Melhorias implementadas

| # | Item | O que foi feito | Arquivos |
|---|---|---|---|
| 1 | PDFs da Câmara de CG | Cada PDF ganha hash SHA-256 num manifesto (`dados/camara_cg_pdfs.json`). Cada nota grava a origem: PDF, página e o trecho de texto lido. Os PDFs ficam guardados 90 dias como artefato do robô. Há uma versão do leitor, para reler quando a regra muda. As leituras descartadas são registradas com motivo. Um validador novo confere a cobertura (notas ÷ total declarado), o CNPJ (dígito, cadastro e nome na Receita), valores impossíveis, datas fora do ano, duplicatas e meses faltando. Ele também compara cada mudança com a coleta anterior | `coletar_verba_camara_cg.py`, `validar_camara_cg.py`, `limpar_notas_camara_cg.py` |
| 2 | Monitoramento das fontes | Registro de 24 bases com fonte, endpoint, método, período, intervalo, atraso normal e identificador do registro original. A classificação separa "aguardando a fonte" (a coleta funciona, mas não há dado novo) de "falha de coleta" (o robô não atualizou). Um retrato diário guarda os registros e o total de cada base | `gerar_monitoramento.py` |
| 3 | LGPD | Varredura de CPF em `dados/`, CSV, páginas, artefatos e logs. Máscara antes de cada upload de artefato (10 pontos do workflow). Máscara nos avisos de log gravados pelo ICP. Teste que falha se aparecer CPF completo ou termo de credencial | `mascarar_cpf.py`, `atualizar.yml`, `test_variacoes.py` |
| 4 | Rastreabilidade | Origem por registro onde a fonte permite. Página por base com endpoint, método, arquivos e identificador. Histórico público de correções, atribuído à base | `gerar_icp.py` |
| 5 | Classificação | Cada base fica em um de 7 status públicos. O verde só aparece com conferência na fonte registrada | `gerar_icp.py` |
| 6 | Testes | Novos: `test_variacoes.py` (variação, formato, versões de meses fechados, PDFs, exposição), `test_icp.py` (460), `icp_pagina.js` (42), `tela_x_dados.js` (15) e `filtros.js` (8). Os testes produzem saída por base para o ICP | `tests/` |
| 7 | Conferência independente | `validar_fontes.py` consulta de novo 8 fontes, por um caminho diferente do coletor, e grava cada conferência num histórico permanente | `validar_fontes.py`, `dados/icp_verificacoes.jsonl` |
| 8 | Registro de execução | A cada coleta, a conclusão e os avisos do log de cada robô são gravados. Assim a falha técnica aparece mesmo quando o job termina "success" | `registrar_execucao.py`, `dados/icp_execucoes*.json(l)` |
| — | ICP | Página `/confiabilidade/`, 24 páginas de base, selos clicáveis no painel, menu, mapa do site e capa. Documentação em `ICP_DOCUMENTACAO.md` | `gerar_icp.py`, `cofre-aberto-ms.html` |

## 2. Problemas encontrados nesta etapa

| Problema | Situação | Evidência |
|---|---|---|
| **Câmara de CG: a lista de notas lida dos PDFs não fecha com o total declarado** na maioria dos vereadores | **Comprovado** (conta interna). O site exibe o total declarado; as notas foram marcadas para revisão manual, e nenhum valor foi alterado | `dados/camara_cg_revisao.json`: 2 vereadores conferidos, 2 parciais, 25 a revisar; 93 itens a revisar e 355 de atenção. Motivos: 179 possíveis notas repetidas, 144 nomes que não conferem com o CNPJ na Receita, 34 sem CNPJ legível, 21 CNPJ com dígito inválido, 3 valores zero ou ilegíveis |
| **Câmara de CG: o portal recusou conexão na última coleta** | **Comprovado** (log) | Run 44150284739, job `coletar_verba_camara`: 8 avisos "Connection refused" em 45.225.6.93:8079. O dado anterior foi mantido |
| **Câmara dos Deputados: passagens do SIGEPA ausentes do arquivo anual de 2026** | **Comprovado e corrigido** (somadas a partir da API, com a regra de sinal conferida) | `validar_fontes.py`: 7 de 8 deputados conferem; Rodolfo difere em R$ 1.362,99 por reembolso lançado depois da coleta (`mudou_na_fonte`) |
| **CPF completo em versões antigas do Git** | **Comprovado, não corrigido** (exige reescrever o histórico, que é uma ação destrutiva) | 172 versões de `prefeitura.json` desde 02/07/2026, 4.666 CPFs antes da máscara, ainda acessíveis por commit (GitHub raw, jsDelivr). O site no ar está limpo |
| **Artefatos do robô com dado sem máscara por 1 dia** | **Corrigido** | máscara antes de cada upload. Nos logs das Actions não há CPF |
| **Prefeitura de CG: nenhum empenho novo desde 02/10/2026** | **Comprovado, problema da fonte** | 46 dias. O alerta do robô abriu a issue; o pedido de LAI está pronto na aba |
| **Página de base do ICP rolava para o lado no celular** | **Corrigido** (achado pelo teste novo) | `icp_pagina.js`: 485 px num viewport de 390 px, por linhas de log longas |

## 3. Testes executados e resultados (17/11/2026)

| Teste | Resultado |
|---|---|
| `test_integridade_dados.py` | ✅ 570 OK · ⚠️ 2 avisos (notas repetidas de Camila Jara, que são assim na fonte; Prefeitura 46 dias) · ❌ 0 |
| `test_variacoes.py` | ✅ 41 OK · ⚠️ 7 avisos (Câmara em revisão, Prefeitura e publicidade aguardando a fonte, itens dos PDFs) · ❌ 0. Com falhas injetadas: 4 erros detectados |
| `test_icp.py` | ✅ 460 OK · ❌ 0. Com falhas injetadas (verde sem conferência, nota adulterada, indicador errado): 5 erros detectados |
| `icp_pagina.js` | ✅ 42/42 (filtros dos 7 status, busca, clique, selo do painel, 25 páginas no celular, link antigo, sem erro JS) |
| `tela_x_dados.js` | ✅ 15 números iguais · 0 diferentes |
| `filtros.js` | ✅ 8 filtros certos · 0 errados · 0 erros JS |
| `validar_fontes.py` | 8 de 8 bases: 7 `confere`, 1 `mudou_na_fonte` |
| `registrar_execucao.py` (run real 44150284739) | Câmara de CG 8 avisos (conexão recusada), coletar_dados 3 (Câmara de Sonora), TJMS 1 (timeout), emendas ALEMS 1 |

### Conferências na fonte oficial (comprovado)

| Base | Comparado | Resultado |
|---|---|---|
| Governo de MS | pago e empenhado do ano | igual ao centavo (R$ 21.246.162.434,07 pago) |
| ALEMS | 25 de 25 deputados | igual |
| Senado | 3 senadores | igual |
| Câmara dos Deputados | 8 deputados | 7 iguais, 1 mudou na fonte (reembolso posterior) |
| Siconfi (ICMS) | 12 meses | igual |
| DadosJusBr (TJMS) | 2 itens | igual |
| PNCP (shows, aluguéis) | 8 + 8 contratos por amostra | igual |

## 4. Fontes ainda não validadas na origem

**16 de 24 bases** não têm conferência automática na fonte e ficam com selo cinza ou amarelo e teto de 80. As mais importantes:

- **Câmara Municipal de CG:** o portal só responde aos servidores do GitHub e os PDFs são digitalizados. Só há conferência interna (notas × total declarado).
- **Prefeitura de CG:** uma conferência manual de um empenho foi feita na primeira auditoria, mas não entra no ICP como verificação, porque é uma amostra de 1.
- **Emendas (CGU):** o total foi conferido manualmente na primeira auditoria. Não há conferência automática, porque o arquivo tem 47 MB.
- **Contratos da Prefeitura, obras, publicidade, entidades, judiciário, câmaras do interior, Presidência, STF, eleições, produção legislativa, votações, benefícios fiscais e auditoria:** sem conferência na fonte.

## 5. Riscos restantes

1. **A Câmara de CG depende de OCR e de um portal instável.** Erros de leitura podem existir em 25 dos 29 vereadores; o total exibido é o declarado.
2. **O histórico do Git ainda contém CPFs.** O site no ar está limpo, mas os commits antigos continuam acessíveis. Remover exige `git filter-repo` e um push forçado, e **aguarda sua autorização**.
3. **A conferência automática é por amostra ou agregado.** Um erro fora da amostra pode passar.
4. **A dimensão F do ICP começou com 1 execução registrada.** Ela só ganha significado depois de cerca de 14 coletas.
5. **A atribuição de avisos do log a bases usa palavras-chave**, e pode atribuir um aviso genérico a mais de uma base.
6. **Ainda faltam CSP e dependências fixadas por hash** (vindo da primeira auditoria).

## 6. Recomendações

1. Autorizar, ou não, a limpeza do histórico do Git. É destrutiva: muda todos os hashes de commit e invalida links antigos para commits.
2. Fazer a revisão manual dos 93 itens da Câmara de CG, começando pelos 4 vereadores com a maior diferença entre notas e total declarado, e registrar o resultado.
3. Acrescentar a conferência automática da Prefeitura (amostra de empenhos pelo link `urlDetalhe`) e das emendas (total por município numa consulta da API da CGU).
4. Mandar o pedido de LAI à Prefeitura sobre os empenhos parados desde 02/10.
5. Revisar os pesos e tetos do ICP depois de 30 dias de histórico.

## 7. Nova avaliação (0 a 100), comparada com a primeira

| Área | 1ª | 2ª | Justificativa (evidência) |
|---|---|---|---|
| Precisão dos dados | 78 | **80** | 8 bases agora são reconferidas na fonte a cada coleta, com histórico permanente, e todas conferem. Não sobe mais porque a Câmara de CG tem 25 de 29 vereadores com notas que não fecham, e Prefeitura e emendas continuam sem conferência automática. |
| Atualização | 80 | **82** | O log de cada robô agora separa a falha técnica (Câmara de CG: conexão recusada) da falta de publicação (Prefeitura). A Prefeitura continua 46 dias atrasada na fonte. |
| Integridade dos cálculos | 90 | **91** | Novos testes de variação, formato e versões; os testes pegaram as falhas injetadas (4 e 5 erros). Nenhum erro novo de soma foi encontrado. |
| Funcionamento técnico | 86 | **88** | Registro de execução por robô, alertas que incluem os testes novos e o ICP, e um defeito de layout no celular achado e corrigido pelo teste. Desconta: o portal da Câmara de CG fora do ar na última coleta. |
| Transparência das fontes | 85 | **91** | Página pública por base com endpoint, método, período, identificador, testes, histórico de verificações e correções, e limitações. Metodologia do ICP publicada com fórmulas. |
| Rastreabilidade (nova) | — | **72** | 100% dos registros têm link ou identificador na ALEMS, no Governo de MS, na Prefeitura, nos shows e nos aluguéis, e 97–99% no Senado e na Câmara dos Deputados. A Câmara de CG está em 0 até a próxima coleta com o leitor v2. |
| Segurança e LGPD | 75 | **79** | Máscara nos artefatos e logs, e um teste de exposição que roda a cada coleta. Não sobe mais porque o histórico do Git ainda tem CPFs (depende de autorização) e não há CSP. |

**ICP calculado pelo próprio sistema nesta data: 90/100.** Ele foi calculado sobre as 15 bases avaliadas; 9 não foram avaliadas por falta de dimensões suficientes. Problemas críticos destacados: Câmara de CG (revisão manual e rastreabilidade 0), Prefeitura (atualização 20) e Judiciário (uma integração com falha). A nota do ICP mede o quanto o dado publicado pode ser comprovado. Ela não é a média das notas desta tabela, e não é uma certificação oficial.
