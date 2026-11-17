# ICP — Índice de Confiabilidade Pública

Documentação técnica do índice publicado na aba **Confiabilidade dos Dados** do painel (https://cofreabertoms.com.br/cofre-aberto-ms.html#aba=confiabilidade; o endereço curto /confiabilidade/ leva para lá).

> O ICP é uma **metodologia independente do Cofre Aberto MS**. **Não é uma certificação oficial** do governo, de tribunal de contas ou de qualquer órgão de controle. Ele mede o quanto cada número publicado no site pode ser comprovado, com critérios públicos e recalculáveis por qualquer pessoa a partir dos arquivos em `dados/`.

---

## 1. Arquitetura

O ICP não é uma estrutura paralela. Ele reaproveita o monitoramento das fontes (`gerar_monitoramento.py`) e acrescenta as notas, as páginas e o histórico.

```
coletores (jobs do workflow)                       ← já existiam
   │
   ├─ validar_camara_cg.py   conferência da leitura dos PDFs da Câmara de CG  → dados/camara_cg_revisao.json
   ├─ validar_fontes.py      nova consulta à fonte oficial, por outro caminho  → dados/validacao_fontes.json
   │                                                                           → dados/icp_verificacoes.jsonl  (permanente)
   ├─ registrar_execucao.py  conclusão + avisos do log de cada robô            → dados/icp_execucoes.json
   │                                                                           → dados/icp_execucoes_historico.jsonl (permanente)
   ├─ tests/test_integridade_dados.py --json   570 conferências, por base      → dados/icp_testes_integridade.json
   ├─ gerar_monitoramento.py classificação de cada fonte                       → dados/monitoramento.json (+ _historico)
   ├─ tests/test_variacoes.py --json           variação, formato, exposição    → dados/icp_testes_variacoes.json
   └─ gerar_icp.py           notas, status, alertas e páginas                  → dados/icp.json
                                                                               → aba do painel (lê icp.json)  e  /confiabilidade/<base>/ (página própria por base)
                                                                               → /monitoramento/ (redireciona)
   └─ gerar_icp.py --sitemap (depois dos geradores que refazem o sitemap)
```

Tudo roda no passo **"ICP — Índice de Confiabilidade Pública"** do job `commit_e_push` de `.github/workflows/atualizar.yml`, a cada coleta. Depois do commit, o job `verificar` roda `tests/test_icp.py`; se falhar, abre ou atualiza a issue de alerta (sem e-mail).

| Arquivo | Papel |
|---|---|
| `scripts/gerar_icp.py` | cálculo do ICP e páginas |
| `scripts/gerar_monitoramento.py` | registro das 24 bases (fonte, endpoint, método, período, intervalo, atraso normal, contagem de registros, total, identificador do registro original) e classificação |
| `scripts/registrar_execucao.py` | lê pela API do GitHub os jobs desta execução e o log de cada um; `JOB_BASES` liga cada robô às bases que ele coleta |
| `scripts/validar_fontes.py` | conferências independentes na fonte (8 bases hoje) |
| `scripts/validar_camara_cg.py` | conferência da leitura dos PDFs da Câmara de CG (marca, nunca altera valores) |
| `tests/_bases.py` | a qual base pertence cada conferência dos testes |
| `tests/test_icp.py` | 460 checagens do ICP |
| `tests/icp_pagina.js` | teste no navegador: filtros, busca, clique, selo do painel, celular (42 checagens) |

## 2. Metodologia

Cada base recebe seis notas parciais (dimensões), de 0 a 100. Quando não há dado suficiente para medir uma dimensão, ela fica **não avaliada** (`null`). Uma dimensão sem dado nunca vira 0 nem 100.

### 2.1 Dimensões e fórmulas

| Dim. | Nome | Peso | Fórmula |
|---|---|---|---|
| P | Precisão e validação | 30 | Última conferência na fonte (automática ou manual registrada no histórico). `confere` = 100; `mudou_na_fonte` (todas as diferenças ≤ 1%, explicadas por lançamentos posteriores à coleta) = 90; `diverge` = min(40, 100 × (1 − divergentes ÷ conferidos)). Até 8 dias vale inteira; de 8 a 30 dias, × 0,8; mais de 30 dias = não avaliado |
| A | Atualização | 20 | Falha de coleta = 0. Senão, com *d* = dias desde o dado mais recente e *a* = atraso normal da fonte: *d* ≤ *a* → 100; acima, max(20, 100 − 80 × (*d* − *a*) ÷ *a*) |
| I | Integridade matemática | 20 | Conferências dos testes atribuídas à base: 100 × ok ÷ (ok + erros) − min(20, 2 × avisos). As linhas de classificação da própria fonte são excluídas, para não contar duas vezes |
| T | Transparência das fontes | 10 | 20 pontos por critério: fonte oficial nomeada · link oficial · período de referência · método documentado · arquivo de dados público |
| R | Rastreabilidade | 10 | % dos registros com o identificador do documento original: link do empenho (Prefeitura), `urlPdf` (ALEMS), nota/documento (Câmara, Senado), nº de controle PNCP (shows, aluguéis), hash e página do PDF (Câmara de CG) |
| F | Funcionamento das integrações | 10 | % das últimas 14 coletas registradas em que o robô da base terminou sem falha atribuída a ela |

### 2.2 Nota da base

```
nota = Σ(dimensão × peso) ÷ Σ(pesos das dimensões avaliadas)     (só com ≥ 4 dimensões avaliadas; senão "Não avaliado")
nota = min(nota, teto)
```

Os **tetos** impedem que uma boa média esconda um problema grave:

| Situação | Teto |
|---|---|
| Divergência na fonte oficial | 40 |
| Falha de coleta | 50 |
| Revisão manual pendente | 70 |
| Sem conferência na fonte oficial (P não avaliada) | 80 |

O último teto deixa claro que **consistência matemática não prova exatidão**: uma base sem conferência na fonte nunca passa de 80, por melhores que sejam as somas.

### 2.3 ICP geral

```
ICP = Σ(nota × importância) ÷ Σ(importância)     (só bases avaliadas)
```

A importância é 3 para o gasto principal de governo ou parlamentar, 2 para um recorte relevante e 1 para uma base complementar. As dimensões gerais usam a mesma ponderação.

### 2.4 Problemas críticos (fora da média)

Uma base aparece no quadro **"Problemas que a média não esconde"** quando acontece qualquer um destes casos:
- o status é *Divergência identificada* ou *Falha na coleta*;
- a importância é 2 ou mais e alguma dimensão está em 40 ou menos, ou a nota está abaixo de 60;
- a importância é 3 e há *revisão manual pendente*.

## 3. Status (selos)

| Status | Cor | Quando |
|---|---|---|
| Verificado na fonte oficial | 🟢 verde | o robô consultou a fonte de novo, por caminho independente, há até 8 dias, e o valor confere (ou só mudou por lançamento posterior) |
| Consistência interna aprovada | ⚪ cinza | os testes da base passam sem erro, mas não houve conferência na fonte |
| Aguardando atualização | 🟡 amarelo | a coleta funciona, mas o órgão não publicou dado novo dentro do atraso normal. **Não é falha do site** |
| Pendente de revisão manual | 🟡 amarelo | a leitura automática marcou itens para conferência humana (ex.: PDFs da Câmara de CG) |
| Divergência identificada | 🔴 vermelho | a conferência na fonte encontrou valor diferente |
| Falha na coleta | 🔴 vermelho | o robô não atualizou (arquivo velho além do intervalo de coleta, ou as **duas últimas** execuções registraram falha da base no log), **ou** os registros caíram mais de 10% de uma coleta para a outra (coleta incompleta); o dado anterior é mantido |
| Pendente de verificação | ⚪ cinza | sem conferência na fonte e sem testes específicos da base |

**Regra do verde:** o selo verde só aparece com uma conferência registrada (`ultimaVerificacao` com resultado `confere` ou `mudou_na_fonte`). Se a classificação disser "verificado" e não houver o registro, o ICP rebaixa o status para cinza. `tests/test_icp.py` checa isso em toda base.

**Falta de publicação × falha técnica:** quando o arquivo é recente mas o dado é velho, a base fica em *Aguardando atualização*. Quando o arquivo é velho ou o log do robô mostra erro de conexão ou timeout, ela vai para *Falha na coleta*. Um aviso isolado (uma tentativa) não muda o status: ele baixa a dimensão F e aparece em "Pendências". O status muda depois de duas execuções seguidas com falha.

## 4. Bases monitoradas (24)

| id | Base | Órgão | Import. | Conferência automática na fonte |
|---|---|---|---|---|
| camara | Câmara Municipal de CG — verba e gabinetes | Câmara de CG | 3 | não (portal só responde ao GitHub; conferência da leitura dos PDFs) |
| deputados-estaduais | Deputados estaduais — CEAP | ALEMS | 3 | sim (25 de 25) |
| deputados | Deputados federais de MS — CEAP | Câmara dos Deputados | 3 | sim (8, API com regra de sinal) |
| senadores | Senadores de MS — CEAPS | Senado | 3 | sim |
| prefeitura | Prefeitura de CG — despesas pagas | Prefeitura de CG | 3 | não |
| governo-ms | Governo de MS — Poder Executivo | Estado | 3 | sim (pago e empenhado do ano) |
| emendas | Emendas parlamentares | CGU | 3 | não (manual, arquivo de 47 MB) |
| contratos-cg, supersalarios, arrecadacao, shows, alugueis, obras, publicidade, entidades, judiciario | recortes | vários | 2 | supersalários (DadosJusBr), arrecadação (Siconfi), shows e aluguéis (amostra PNCP) |
| beneficios, producao, votacoes, camaras-ms, presidencia, stf, eleicoes, auditoria | complementares | vários | 1 | não |

O registro completo de cada base (endpoint, método, período, intervalo, atraso, identificador) está em `FONTES` (`scripts/gerar_monitoramento.py`). As limitações conhecidas estão em `EXTRA` (`scripts/gerar_icp.py`) e aparecem na página de cada base.

## 5. Histórico e proteção dos registros

| Arquivo | Conteúdo | Regra |
|---|---|---|
| `dados/icp_verificacoes.jsonl` | cada conferência na fonte: data, base, método, URL, itens comparados (site × fonte × diferença), divergentes | **só acrescenta**. `validar_fontes.py` grava uma linha só quando a conferência é nova |
| `dados/icp_execucoes_historico.jsonl` | cada execução do robô: conclusão e até 5 avisos por job | **só acrescenta** |
| `dados/monitoramento_historico.json` | retrato diário de registros e total por base | uma chave por dia |
| `metodologia.html` (tabela de correções) | correções públicas com data | o ICP lê e atribui cada uma à base |

`tests/test_icp.py` confere que a versão anterior (git `HEAD`) de cada `.jsonl` é **prefixo** da atual: se alguém apagar ou reescrever uma linha, o teste falha e o alerta é aberto. Correções nunca apagam uma conferência antiga. Uma nova conferência é acrescentada e a anterior continua no histórico da base.

Os avisos de log passam pela máscara de CPF antes de serem gravados. Os registros de auditoria não contêm dado pessoal.

## 6. Páginas

- **Aba "Confiabilidade dos Dados" do painel** (`cofre-aberto-ms.html#aba=confiabilidade`, com o menu lateral, grupo "Sobre o projeto"):
  - o que é o ICP, o aviso de metodologia independente, a nota geral, quantas bases são monitoradas, a última atualização e a última conferência;
  - o quadro de problemas críticos e o painel de indicadores (os cartões filtram a tabela);
  - as notas por dimensão;
  - a tabela de bases com filtro por status e busca sem acento; no celular, cada linha vira um cartão;
  - ao clicar numa base, o detalhe abre na própria aba: o que foi verificado (site × fonte), notas por dimensão, transparência técnica, pendências, testes, históricos de verificações, divergências e correções, e limitações;
  - critérios, fórmulas, legenda dos status e links para os dados.
- **Link direto:** `#aba=confiabilidade&p=<base>` abre a aba já no detalhe da base. `/confiabilidade/` e o antigo `/monitoramento/` (inclusive `#camara-cg`) levam para a aba.
- **/confiabilidade/<base>/:** uma página própria por base, para compartilhar e para os buscadores, com o mesmo conteúdo do detalhe. Está no sitemap.
- **Selos no painel:** na barra de fonte de cada aba, o selo mostra o status, a cor e a nota ICP; ao clicar, abre o detalhe da base na aba do ICP. O botão "De onde vem este número" faz o mesmo.
- **Menu:** a aba fica no menu lateral do painel, no mapa do rodapé de todas as páginas e na capa.

## 7. Testes

| Teste | Onde roda | O que cobre |
|---|---|---|
| `tests/test_icp.py` (440) | `testar-site.yml` e job `verificar` | status públicos e cores; verde só com conferência ≤ 30 dias; notas recalculadas por base; ICP e dimensões gerais recalculados; tetos simulados; indicadores = contagem; críticos; falhas simuladas (conexão recusada, job `failure`, aviso informativo); histórico só cresce e é JSON válido; páginas, seções, link oficial, viewport, filtros; redirecionamento; integração painel/robô |
| `tests/icp_pagina.js` (27) | `testar-site.yml` | /confiabilidade/ abre a aba com o menu lateral; nota = icp.json; filtros de cada status e cartões = dados; busca sem acento; clique abre o detalhe com todas as seções; selo de outra aba abre o detalhe certo; base sem conferência não fica verde; link antigo; aba e 24 páginas de base sem rolagem horizontal no celular (iPhone 13); sem erro JS |
| `tests/test_integridade_dados.py` (570) | coleta e site | somas e totais (alimenta a dimensão I) |
| `tests/test_variacoes.py` | coleta e site | variação, formato, versões, PDFs, exposição de dados |
| `tests/tela_x_dados.js`, `tests/filtros.js`, `tests/smoke.js` | site | tela = dados, filtros do painel, todas as abas |

O teste foi conferido com falhas injetadas: verde sem conferência, nota adulterada e indicador errado deram 5 erros. Os testes também acharam defeitos reais, todos corrigidos: a página da Câmara de CG rolava para o lado no celular; o teste tela × dados lia "R$ 949,4 mil" como milhões; e a coleta de aluguéis do PNCP vinha incompleta no robô (10 em vez de 206 contratações) sem ninguém perceber. A comparação entre coletas passou a ser feita por coleta, não por dia, e uma queda brusca agora vira "Falha na coleta". O caso foi simulado de ponta a ponta: a base fica vermelha, com nota 50, e aparece nos problemas críticos.

## 8. Limitações

1. **O ICP mede comprovação, não honestidade do gasto.** Uma base "verificada" significa que o site reproduz fielmente o que o órgão publicou, não que o gasto foi regular.
2. **A conferência automática cobre 8 de 24 bases.** As outras ficam com o teto de 80 e o selo cinza. Prefeitura, emendas e Câmara de CG são bases importantes ainda sem conferência automática.
3. **A conferência é por amostra ou agregado** (ex.: 8 contratos do PNCP, total do ano do Estado). Um erro num registro fora da amostra pode passar.
4. **A dimensão F depende do histórico de execuções**, que começou em 17/11/2026. Até haver 14 coletas, ela reflete poucas execuções.
5. **A atribuição de avisos do log a bases** usa palavras-chave (`BASE_TXT`). Um aviso genérico vai para todas as bases do robô.
6. **A rastreabilidade da Câmara de CG está em 0** até a próxima coleta com o leitor de PDFs versão 2, que grava hash e página de cada nota.
7. **Pesos, tetos e importâncias são escolhas editoriais** do projeto. Estão publicados para que qualquer pessoa possa discordar e recalcular.
8. **Sem conferência humana periódica registrada:** conferências manuais só entram no histórico quando feitas e documentadas, e nenhuma foi inventada para preencher lacunas.
