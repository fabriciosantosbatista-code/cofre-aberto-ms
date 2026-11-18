# Terceira auditoria — metodologia do ICP (Índice de Confiabilidade Pública)

**Data:** 18/11/2026 · **Metodologia nova:** ICP 2.0 (`scripts/icp_metodologia.py`, documentada em `ICP_DOCUMENTACAO.md`)
**Base de comparação:** ICP 1.0 publicado em 17/11/2026 (nota 83), preservado em `dados/icp_notas_historico.jsonl` e no Anexo A da documentação.

Resumo: a nota geral passou de **83 para 66**. Não houve piora dos dados. A nota 1.0 premiava consistência interna e
conferências por amostra como se fossem verificação completa; a 2.0 mede quanto de cada base foi de fato comparado com
a fonte oficial. Hoje **4 de 24 bases** foram conferidas por inteiro, 4 em parte e 16 dependem só dos testes internos —
e cerca de **20% dos registros** do site passaram por alguma conferência na fonte.

---

## 1. Problemas encontrados na metodologia anterior (1.0)

| # | Problema | Evidência | Efeito |
|---|---|---|---|
| 1 | **Precisão ignorava o tamanho da amostra**: "confere" = 100 com qualquer número de itens | Aluguéis: 8 de 206 contratos → P 100 (nota 100 antes da falha de coleta); Shows: 8 de 1.053 → 100; Supersalários: 2 itens (só TJMS) de 92.796 registros → 100 | nota máxima sem verificação abrangente |
| 2 | **Integridade com um único teste valia 100** | Judiciário, Eleições, Auditoria: 1 teste ("registros não caíram") → I = 100 | "consistência aprovada" sem testar somas, duplicidades ou valores |
| 3 | **Dimensão ausente saía da conta** e as outras "subiam" | sem conferência na fonte, a média das outras 5 valia até 100; o teto *ad hoc* de 80 corrigia em parte | 80 sem nenhuma comprovação na fonte |
| 4 | **Bases não avaliadas fora da média** | 5–6 bases com menos de 4 dimensões não entravam no ICP geral | média maior do que a do conjunto (contando-as como 0, seria 74) |
| 5 | **Integração quebrada sem limite** | Judiciário com F = 0 mantinha nota 80 | robô falhando com nota de base saudável |
| 6 | **Verde com conferência parcial** | o selo verde exigia só uma conferência recente, de qualquer tamanho | o cidadão não distinguia 8 contratos de 206 de uma base inteira |
| 7 | **Governo de MS conferido só pelo total** | 2 números (pago e empenhado do ano) para 24.252 credores | erros que se compensam entre órgãos não seriam detectados |
| 8 | **Conferências não registravam a cobertura** | o histórico guardava itens comparados, mas não o total da base nem a seleção | impossível calcular "quanto foi conferido" |

## 2. Mudanças realizadas

1. **Cobertura registrada em cada conferência** (`validar_fontes.py`): granularidade, unidade, total de unidades e de
   registros, unidades conferidas (identificadores, sem repetição), registros abrangidos, seleção da amostra, responsável
   e versão da metodologia — no histórico permanente `dados/icp_verificacoes.jsonl`.
2. **Governo de MS passou a conferir cada um dos 66 órgãos** (mais os 2 totais), em vez de só o total: mais evidência em
   vez de um teto arbitrário.
3. **Níveis de evidência 0–4**, calculados automaticamente (seção 3).
4. **Precisão estatística**: limite superior de 95% da taxa de divergência (hipergeométrico exato).
5. **Integridade = aprovação × profundidade** (tipos de teste cobertos ÷ 5).
6. **P e I ausentes valem 0** (evidência); A, T, R, F ausentes saem da conta (propriedades).
7. **Teto de cobertura** para conferência parcial e **teto de integração instável**; o teto *ad hoc* de 80 saiu.
8. **Nota geral com as 24 bases**.
9. **Verde só com a base inteira conferida** (nível ≥ 3); amostra = amarelo com o percentual no selo.
10. **Interface**: resumo "o que esta nota significa", cobertura dos registros, conferidas por inteiro/em parte/sem
    conferência e críticos junto da nota; coluna "Evidência" na tabela; bloco "Evidência que sustenta a nota" e avisos em
    linguagem simples em cada base (painel e páginas próprias).
11. **Versões**: `metodologia.versao` no `icp.json`, nota 1.0 de cada base (`notaV1`) e retrato 1.0 + uma linha por coleta
    em `dados/icp_notas_historico.jsonl` (só acrescenta; protegido pela proteção da publicação).
12. **Problemas críticos**: testes rasos sozinhos deixaram de entrar no quadro crítico (vão para os avisos da base); o
    limite de nota baixa passou de 60 para 50, porque a escala 2.0 é mais baixa. Regra documentada e testada.

## 3. Fórmulas e critérios novos

**Níveis:** 0 sem evidência · 1 integridade interna (testes sem erro) · 2 conferência parcial (amostra, recorte ou um
único total) · 3 conferência abrangente (todas as unidades, ≥ 2 unidades, denominador conhecido) · 4 reforçada (nível 3
repetido ≥ 3 vezes em ≥ 2 dias, com ≥ 20 h entre a primeira e a última, evidências gravadas).

```
P  = 100 × (1 − LS95(N, n, d)) × fr × fi        (≤ 40 se houver divergência; 0 sem conferência)
I  = 100 × ok/(ok+erros) × tipos/5 − min(20, 2 × avisos)        (0 sem testes)
nota = 0,30 P + 0,20 I + 0,50 × média ponderada(A 20, T 10, R 10, F 10 medidas)
tetos: nível 2 → 70 + 30 × fração conferida · divergência 40 · falha de coleta 50 · F < 50 → 50 · revisão manual 70
ICP = Σ nota × importância ÷ Σ importância      (24 bases)
```

## 4. Justificativa dos limites adotados

| Limite | Valor | Justificativa | Efeito esperado (e observado) |
|---|---|---|---|
| Confiança do limite estatístico | 95% | padrão em amostragem de auditoria; hipergeométrico exato porque a amostra é sem reposição e a base é finita | 8 de 206 → até 30,6% de erro ainda possível → P 69 |
| Validade da conferência | 30 dias (inteira até 8) | mantido da 1.0 | — |
| Máximo sem conferência na fonte | 70 | **não é escolhido**: é a soma dos pesos das dimensões que não dependem da fonte (100 − 30) | 16 bases ≤ 70 |
| Teto de cobertura (nível 2) | 70 + 30 × fração | os 30 pontos da conferência só são ganhos na proporção da base comparada | Shows e Supersalários 100 → 70; Siconfi 100 → 81 |
| Nível 3 exige ≥ 2 unidades | 2 | um único total não localiza erros que se compensam | Governo de MS só alcança o 3 conferindo os 66 órgãos |
| Nível 4: ≥ 3 conferências, ≥ 2 dias, ≥ 20 h | 3 / 2 / 20 h | repetição independente no tempo; as 20 h evitam contar como "dias diferentes" conferências feitas com horas de diferença perto da meia-noite ou gravadas em fusos diferentes (caso real desta etapa, ver seção 9) | nenhuma base no nível 4 ainda (as conferências 2.0 começaram hoje) |
| Integridade: 5 tipos de teste | 5 | as cinco categorias da metodologia de testes: estrutura, totais, contagens, duplicidade, faixa de valores | 1 teste → I 20; 5 tipos → I 100 |
| Integração instável | F < 50 → 50 | mais da metade das coletas recentes falhou: equivale a uma falha de coleta recorrente (mesmo teto) | Aluguéis, Câmaras do interior e Auditoria limitados a 50 |
| Divergência / falha / revisão | 40 / 50 / 70 | mantidos da 1.0 | — |

## 5. Comparação das 24 bases (dados publicados pelo robô em 17/11/2026 21h46, horário de MS)

Ordem: importância, depois nota 2.0. "Nota 1.0 (mesmos dados)" aplica a fórmula antiga aos dados de hoje; a diferença para
a coluna anterior vem dos dados novos (não da metodologia).

| Base | Import. | Nota 1.0 publicada | Nota 1.0 (mesmos dados) | **Nota 2.0** | Nível | Cobertura oficial | Registros conferidos / total | Principal motivo da diferença |
|---|---|---|---|---|---|---|---|---|
| Câmara dos Deputados — CEAP dos deputados federais de MS | 3 | 95 | 96 | **96** | 3 · Conferência abrangente | 100% | 2.677 / 2.677 | sem mudança relevante |
| Senado Federal — CEAPS dos senadores de MS | 3 | 95 | 96 | **92** | 3 · Conferência abrangente | 100% | 509 / 509 | testes rasos: I 100→80 (4 de 5 tipos) |
| Governo de MS (Poder Executivo) — despesas | 3 | 100 | 100 | **92** | 3 · Conferência abrangente | 100% | 24.252 / 24.252 | testes rasos: I 100→60 (3 de 5 tipos) |
| Assembleia Legislativa de MS (ALEMS) — CEAP | 3 | 95 | 97 | **89** | 3 · Conferência abrangente | 100% | 5.707 / 5.707 | testes rasos: I 100→60 (3 de 5 tipos) |
| Portal da Transparência (CGU) — emendas parlamentares pagas  | 3 | 80 | 80 | **62** | 1 · Integridade interna | sem conferência | — | sem conferência na fonte: P vale 0 (máx. 70); testes rasos: I 100→60 (3 de 5 tipos) |
| Câmara Municipal de Campo Grande — verba indenizatória e pes | 3 | 70 | 70 | **51** | 1 · Integridade interna | sem conferência | — | sem conferência na fonte: P vale 0 (máx. 70); testes rasos: I 94→54 (3 de 5 tipos) |
| Prefeitura de Campo Grande — despesas pagas | 3 | 69 | 72 | **50** | 1 · Integridade interna | sem conferência | — | sem conferência na fonte: P vale 0 (máx. 70) |
| Tesouro Nacional (Siconfi) — arrecadação do Estado e de CG | 2 | 100 | 100 | **81** | 2 · Conferência parcial | 60% | 12 / 20 | conferência parcial (60%): teto de cobertura e P 90; testes rasos: I 100→20 (1 de 5 tipos) |
| Folhas de pagamento (Estado, TJMS, MPMS, TCE, Câmara CG e ou | 2 | 100 | 100 | **70** | 2 · Conferência parcial | 0,24% | 227 / 92.796 | conferência parcial (0,24%): teto de cobertura e P 28.6; testes rasos: I 100→80 (4 de 5 tipos) |
| PNCP — shows contratados por órgãos de MS | 2 | 100 | 100 | **70** | 2 · Conferência parcial | 1,5% | 16 / 1.053 | conferência parcial (1,5%): teto de cobertura e P 83.1 |
| Governo de MS — obras (contratos) | 2 | 80 | 80 | **66** | 1 · Integridade interna | sem conferência | — | sem conferência na fonte: P vale 0 (máx. 70); testes rasos: I 100→80 (4 de 5 tipos) |
| Prefeitura de Campo Grande — contratos e licitações | 2 | 80 | 80 | **58** | 1 · Integridade interna | sem conferência | — | sem conferência na fonte: P vale 0 (máx. 70); testes rasos: I 100→40 (2 de 5 tipos) |
| Entidades sem fins lucrativos (Estado, Prefeitura, emendas) | 2 | não avaliada | não avaliada | **58** | 1 · Integridade interna | sem conferência | — | sem conferência na fonte: P vale 0 (máx. 70); testes rasos: I 100→40 (2 de 5 tipos); não avaliada na 1.0 (fora da média); agora entra |
| TJMS, TRT24 e TRE-MS — remuneração | 2 | 80 | 80 | **54** | 1 · Integridade interna | sem conferência | — | sem conferência na fonte: P vale 0 (máx. 70); testes rasos: I 100→20 (1 de 5 tipos) |
| PNCP e Prefeitura de CG — aluguel de imóveis | 2 | 50 | 50 | **50** | 2 · Conferência parcial | 6,8% | 14 / 206 | conferência parcial (6,8%): teto de cobertura e P 81.6; testes rasos: I 100→60 (3 de 5 tipos); teto: falha na coleta; integração instável (F 0) |
| Publicidade (Estado e Prefeitura) | 2 | não avaliada | não avaliada | **44** | 1 · Integridade interna | sem conferência | — | sem conferência na fonte: P vale 0 (máx. 70); testes rasos: I 100→40 (2 de 5 tipos); não avaliada na 1.0 (fora da média); agora entra |
| SEFAZ-MS — empresas com benefício fiscal | 1 | não avaliada | não avaliada | **62** | 1 · Integridade interna | sem conferência | — | sem conferência na fonte: P vale 0 (máx. 70); testes rasos: I 100→60 (3 de 5 tipos); não avaliada na 1.0 (fora da média); agora entra |
| Câmara e Senado — produção legislativa | 1 | 80 | 80 | **62** | 1 · Integridade interna | sem conferência | — | sem conferência na fonte: P vale 0 (máx. 70); testes rasos: I 100→60 (3 de 5 tipos) |
| Câmara e Senado — votações nominais | 1 | 80 | 80 | **58** | 1 · Integridade interna | sem conferência | — | sem conferência na fonte: P vale 0 (máx. 70); testes rasos: I 100→40 (2 de 5 tipos) |
| TSE — eleitos 2026 e patrimônio declarado | 1 | 80 | 80 | **54** | 1 · Integridade interna | sem conferência | — | sem conferência na fonte: P vale 0 (máx. 70); testes rasos: I 100→20 (1 de 5 tipos) |
| Presidência da República (CGU) — cartão, viagens, remuneraçã | 1 | não avaliada | não avaliada | **50** | 0 · Sem evidência | sem conferência | — | sem conferência na fonte: P vale 0 (máx. 70); não avaliada na 1.0 (fora da média); agora entra |
| STF — contracheques e despesa com pessoal | 1 | não avaliada | não avaliada | **50** | 0 · Sem evidência | sem conferência | — | sem conferência na fonte: P vale 0 (máx. 70); não avaliada na 1.0 (fora da média); agora entra |
| Câmaras municipais do interior — remuneração e diárias dos v | 1 | 50 | 50 | **34** | 1 · Integridade interna | sem conferência | — | sem conferência na fonte: P vale 0 (máx. 70); testes rasos: I 98→78 (4 de 5 tipos); teto: falha na coleta; integração instável (F 0) |
| Sinais de atenção (gerados pelo site) | 1 | 50 | 50 | **16** | 1 · Integridade interna | sem conferência | — | sem conferência na fonte: P vale 0 (máx. 70); testes rasos: I 100→20 (1 de 5 tipos); teto: falha na coleta; integração instável (F 0) |

**Nota geral:** 1.0 publicada em 17/11 = 83 · 1.0 recalculada sobre os dados de 18/11 = 84 · **2.0 = 66** · níveis: {'0': 2, '1': 14, '2': 4, '3': 4, '4': 0} · conferidas por inteiro 4, em parte 4, sem conferência 16 · cobertura dos registros: 19,7% (33.414 de 169.294) · críticos 7


## 6. Cobertura e nível de evidência por base

- **Nível 3 (conferidas por inteiro):** Câmara dos Deputados (8 de 8 deputados, 2.677 notas), Senado (3 de 3, 509 notas),
  ALEMS (25 de 25, 5.707 notas) e Governo de MS (66 órgãos + 2 totais, 24.252 credores). Limitação: a conferência é pelos
  totais de cada unidade; registros individuais não são comparados um a um.
- **Nível 2 (em parte):** Siconfi (12 de 20 meses, só ICMS do Estado; Campo Grande e demais impostos não conferidos),
  Shows (16 de 1.053 contratações, 1,5%), Aluguéis (14 de 206, 6,8%) e Supersalários (só TJMS: 227 de 92.796 registros, 0,24%).
- **Nível 1 (só testes internos):** Câmara de CG, Prefeitura, emendas, contratos da Prefeitura, obras, publicidade,
  entidades, judiciário, benefícios fiscais, produção legislativa, votações, eleições, Câmaras do interior, auditoria.
- **Nível 0 (sem evidência):** Presidência e STF — não há testes de integridade específicos dessas bases.
- **Cobertura geral:** 33.414 de 169.294 registros (19,7%) entram em alguma conferência na fonte; nas 8 bases com
  denominador conhecido, 26%.

## 7. Resultado dos testes

| Teste | Resultado |
|---|---|
| `tests/test_icp_metodologia.py` (novo) | ✅ 93 checagens: 2 em 92 mil sem nota máxima; 10 de 206 = parcial 4,85%; base inteira = nível 3 / 4 com repetição; mesmo dia e horas de diferença não dão nível 4; sem conferência ≤ 70 e sem verde; integração quebrada ≤ 50; sem publicação ≠ falha; denominador desconhecido nunca 100%; amostras repetidas não inflam; divergência reduz; 1 teste não vale 100; regressão das 24 bases; histórico 1.0 preservado |
| `tests/test_icp.py` | ✅ 543 checagens (verde só com nível ≥ 3; notas 2.0 e 1.0 reproduzidas; indicadores) |
| `tests/icp_pagina.js` | ✅ 38/38 (nível e cobertura na tela = dados nas 24 bases; resumo; selo por amostra não verde e com percentual) |
| Integridade · variações · CPF · monitoramento | ✅ 1.057 · 77 · 2.550 arquivos sem CPF · 40 cenários (com falhas intencionais) |
| Tela × dados · filtros · smoke | ✅ 15/15 · 8/8 · todas as abas, computador e celular |
| Responsividade | ✅ sem rolagem lateral em computador (1366 px), tablet (iPad) e celular (iPhone 13) |

Nenhum teste existente foi desativado. Duas regras de teste mudaram junto com a metodologia, de forma documentada: a nota
recalculada agora é a 2.0 (a 1.0 continua testada como `notaV1`), e o quadro crítico deixou de exigir testes rasos
(passou a exigir que apareçam nos avisos da base).

## 8. Workflows e publicação

- Commit `3d5af9e06` (metodologia 2.0): "Testar site" ✅; coleta real do robô `44215605846`: as conferências 2.0 rodaram
  nas 8 fontes (todas compatíveis), a proteção liberou a publicação, os logs dos 10 robôs foram lidos, o ICP 2.0 foi
  publicado no commit `051c5a97a` (nota 66) e o detector de CPF aprovou os 2.550 arquivos.
- Correção do fuso e do nível 4 (seção 9): publicada em seguida; verificação do site ao vivo registrada no fim deste relatório.

## 9. Problemas encontrados durante a implementação (e corrigidos)

1. **Nível 4 atribuído indevidamente a 4 bases (chegou a ser publicado).** As conferências executadas manualmente nesta
   etapa gravaram o horário em UTC (18/11 01h) e as do robô no horário de MS (17/11 21h). Separadas por poucas horas, pareciam
   "dias diferentes". Correção: todos os scripts do ICP gravam no horário de Campo Grande, e o nível 4 exige também 20 h entre a
   primeira e a última conferência. Teste novo cobre o caso. As linhas antigas do histórico não foram alteradas.
2. **Conferência feita "hoje" não contava para o reforço** (`idade 0` tratada como ausente). Achado pelo teste; corrigido.
3. **Contagem de credores do Governo de MS**: a primeira versão contava só os 1.100 maiores; corrigido para os 24.252.

## 10. Problemas ainda pendentes

1. **16 de 24 bases sem conferência na fonte.** Prioridade: Prefeitura (12.951 empenhos; amostra pelo link de cada empenho),
   emendas (total por município na API da CGU) e Câmara de CG (portal só responde ao GitHub).
2. **Amostras pequenas**: Shows e Aluguéis conferem 8 contratações por dia; a cobertura cresce com os dias (união sem
   repetição), mas levaria meses para ser abrangente. Aumentar a amostra diária custa tempo de coleta.
3. **Supersalários confere só o TJMS**; os outros 13 itens (Estado, MPMS, TCE, Câmara de CG…) não têm fonte de conferência
   independente automatizada.
4. **Testes de integridade rasos** em 14 bases (I ≤ 60): faltam testes de duplicidade e de faixa de valores em várias.
5. **Bases de nível 0 (Presidência, STF) têm nota 50**, vinda só de atualização e transparência. O selo é cinza e o aviso diz
   "sem evidência", mas o número pode parecer razoável; avaliar na próxima etapa se o nível 0 deve ter teto próprio.
6. **Nível 4 ainda não alcançável** até haver conferências 2.0 em dias diferentes (a partir de 19/11).
7. **Conferência pelos totais (nível 3)** não detecta erros que se compensam dentro da mesma unidade.
8. O histórico do Git ainda contém CPFs antigos — etapa separada, que depende da sua autorização.
