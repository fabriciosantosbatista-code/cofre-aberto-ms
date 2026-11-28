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
| `scripts/icp_metodologia.py` | metodologia 2.0: cobertura, nível de evidência, limite estatístico (hipergeométrico/binomial), dimensões P e I, nota e tetos |
| `scripts/gerar_monitoramento.py` | registro das 21 bases (fonte, endpoint, método, período, intervalo, atraso normal, contagem de registros, total, identificador do registro original) e classificação |
| `scripts/registrar_execucao.py` | lê pela API do GitHub os jobs desta execução e o log de cada um; `JOB_BASES` liga cada robô às bases que ele coleta |
| `scripts/validar_fontes.py` | conferências independentes na fonte (8 bases hoje) |
| `scripts/validar_camara_cg.py` | conferência da leitura dos PDFs da Câmara de CG (marca, nunca altera valores) |
| `tests/_bases.py` | a qual base pertence cada conferência dos testes |
| `tests/test_icp.py` | checagens do ICP publicado (status, notas 2.0 e 1.0, indicadores, histórico, páginas) |
| `tests/test_icp_metodologia.py` | cenários da metodologia 2.0 e regressão das 21 bases |
| `tests/icp_pagina.js` | teste no navegador: filtros, busca, clique, selo do painel, celular (42 checagens) |

## 2. Metodologia (versão 2.0, em vigor desde 18/11/2026)

**Princípio:** uma base com poucos registros conferidos não pode transmitir a mesma confiança de uma base integralmente
verificada. A nota passa a medir também **quanto** da base foi conferido na fonte oficial, e com que qualidade — não só
se as contas fecham. As seis dimensões e os seus pesos foram mantidos; o que mudou foi como Precisão (P) e Integridade (I)
são medidas, como as dimensões ausentes entram na conta, e três tetos novos. O cálculo está em `scripts/icp_metodologia.py`
(funções puras, testadas em `tests/test_icp_metodologia.py`). A metodologia anterior está no **Anexo A**.

### 2.1 Cobertura da conferência (por base)

Cada conferência na fonte (`scripts/validar_fontes.py`) grava, no histórico permanente `dados/icp_verificacoes.jsonl`:
data e hora, base, fonte usada (`fonteUrl`), método, **granularidade**, unidade, total de unidades e de registros da base,
unidades conferidas (com os identificadores, sem repetição), registros abrangidos, seleção da amostra, resultado,
divergências, itens comparados (site × fonte × diferença), responsável (o robô) e versão da metodologia.

| Granularidade | O que é comparado | Registros abrangidos | Bases hoje |
|---|---|---|---|
| `registro` | cada registro, um a um | os registros conferidos | Shows e Aluguéis (amostra aleatória de 8 contratações por dia no PNCP) |
| `unidade` | o total de cada unidade (parlamentar, órgão, mês) | todos os registros das unidades conferidas | ALEMS (25 deputados), Câmara (8), Senado (3), Governo de MS (66 órgãos + 2 totais), Siconfi (12 de 20 meses), Supersalários (TJMS: 2 de 14 itens) |
| `total` | um único total da base | todos, mas sem localizar erros | nenhuma (o Governo de MS deixou de ser só o total em 18/11) |

- **Cobertura (%)** = registros abrangidos ÷ registros da base. Se o total da base é desconhecido, a cobertura fica
  **"não calculada"** — nunca 100%.
- **Amostras repetidas não inflam a cobertura:** na conferência registro a registro, a cobertura é a união das unidades
  *distintas* conferidas nos últimos 30 dias (a mesma contratação conferida em dois dias conta uma vez). Nunca passa do
  total da base.
- Conferência com mais de 30 dias não vale. Conferência antiga (metodologia 1.0, sem cobertura gravada) vale como
  "cobertura não calculada".
- **Conferência acumulada em janela móvel de 30 dias, com hash** (em vigor desde **19/11/2026**; os pesos e a fórmula
  70 + 30 × fração conferida não mudaram): na conferência registro a registro (shows, aluguéis, entidades e as que vierem
  por amostra), cada conferência grava um hash curto dos campos comparados de cada registro que bateu com a fonte
  (`hashes` em `icp_verificacoes.jsonl`). Um registro só conta como conferido se a conferência tem ≤ 30 dias **e** o hash
  de hoje é igual ao gravado: se o registro mudou no site, volta a "não conferido"; registro novo só conta depois de
  sorteado e conferido; conferência sem hash gravado não conta. A amostra diária usa semente = data (reproduzível).
  Registro sem o dado no site para comparar (lacuna da coleta) não conta e aparece como pendência da base.

### 2.2 Níveis de evidência (automáticos)

| Nível | Nome | Regra (calculada, nunca preenchida à mão) |
|---|---|---|
| 0 | Sem evidência | sem testes da base e sem conferência na fonte |
| 1 | Integridade interna | testes da base sem erro, sem conferência válida na fonte |
| 2 | Conferência parcial | conferência válida (≤ 30 dias, compatível) que **não** cobre todas as unidades — amostra, recorte, ou um único total |
| 3 | Conferência abrangente | todas as unidades da base conferidas (registro a registro ou pelos totais de cada unidade), com pelo menos 2 unidades e denominador conhecido |
| 4 | Abrangente reforçada | nível 3 repetido: ≥ 3 conferências abrangentes compatíveis em ≥ 2 dias diferentes, com **pelo menos 20 horas** entre a primeira e a última, nos últimos 30 dias, com itens comparados e endereço da fonte gravados |

Um único total geral fica no nível 2 porque uma só equação não localiza erros que se compensam. Na conferência pelos totais
de cada unidade (nível 3), os registros individuais entram nos totais mas não são comparados um a um — essa limitação
aparece na página da base.

### 2.3 Dimensões e fórmulas

| Dim. | Peso | Fórmula 2.0 | O que mudou |
|---|---|---|---|
| P · Precisão e validação | 30 | `100 × (1 − LS95) × fr × fi`. **LS95** = limite superior de 95% da proporção de unidades divergentes na base, pela distribuição **hipergeométrica exata** (amostra sem reposição de uma base finita de *N* unidades, *n* conferidas, *d* divergentes); com *N* desconhecido, limite binomial de Clopper–Pearson. **fr** = 1 (confere) ou 0,9 (mudou na fonte depois da coleta). **fi** = 1 até 8 dias, 0,8 até 30 dias. Divergência: no máximo 40. Sem conferência válida: não avaliada | antes, "confere" = 100 com qualquer amostra |
| A · Atualização | 20 | falha de coleta = 0; dado até o atraso normal da fonte = 100; acima, max(20, 100 − 80 × (*d* − *a*) ÷ *a*) | igual |
| I · Integridade matemática | 20 | `100 × ok ÷ (ok + erros) × (tipos cobertos ÷ 5) − min(20, 2 × avisos)`. Tipos: estrutura/campos, totais, contagens, duplicidade, faixa de valores. Sem testes: não avaliada | antes, 1 teste aprovado = 100 |
| T · Transparência | 10 | 20 por critério (fonte, link, período, método, arquivo) | igual |
| R · Rastreabilidade | 10 | % dos registros com identificador do documento original | igual |
| F · Integrações | 10 | % das últimas 14 coletas com log legível em que o robô funcionou; sem log legível = não medida | igual (corrigida em 17/11) |

**Exemplos do limite LS95** (sem divergência): 8 de 206 → 30,6% (P = 69); 16 de 206 → 16,0% (P = 84); 12 de 20 → 10% (P = 90);
2 de 30 → 73% (P = 27); 206 de 206 → 0 (P = 100). Ou seja: conferir 8 contratos sem erro ainda deixa possível, com 95% de
confiança, que até ~31% dos 206 estejam errados.

### 2.4 Nota da base

```
nota = 0,30 × P' + 0,20 × I' + 0,50 × M
  P' = P, ou 0 sem conferência válida      I' = I, ou 0 sem testes        (dimensões de EVIDÊNCIA: ausência vale 0)
  M  = média ponderada de A (20), T (10), R (10), F (10) entre as medidas  (dimensões de PROPRIEDADE: ausência sai da conta)
nota = min(nota, tetos)
```

**Por que P e I valem 0 quando faltam:** o ICP mede o quanto o dado pode ser comprovado. Sem conferência, não há comprovação
na fonte — isso não diz que o dado está errado, mas não pode render pontos de comprovação. Antes (1.0), a dimensão ausente saía
da conta e as outras "subiam" para ocupar o lugar dela; daí o teto *ad hoc* de 80. Agora o máximo sem conferência sai da própria
fórmula: **70** (todas as outras dimensões cheias). A, T, R e F descrevem propriedades da base que nem sempre o site consegue
medir (ex.: rastreabilidade de uma série mensal); quando não medidas, saem da conta, como antes.

**Tetos** (o que a média não pode esconder):

| Teto | Valor | Justificativa | Efeito |
|---|---|---|---|
| Cobertura (nível 2) | 70 + 30 × fração conferida | 70 é o máximo possível sem nenhuma conferência; os 30 pontos do peso da conferência só são ganhos na proporção da base efetivamente comparada com a fonte (pelos registros quando o total é conhecido, senão pelas unidades, senão 0) | amostra de 0,76% ≤ 70; 60% ≤ 88; base inteira, sem teto. Nível 2 nunca passa de um nível 3 equivalente |
| Divergência na fonte | 40 | a fonte contradiz o site: o dado não pode parecer confiável | mantido da 1.0 |
| Falha de coleta | 50 | o dado publicado é o anterior e não foi atualizado | mantido da 1.0 |
| Integração instável (F < 50) | 50 | mais da metade das coletas recentes falhou: equivalente a uma falha de coleta recorrente | novo — evita nota alta com integração quebrada |
| Revisão manual pendente | 70 | itens marcados para conferência humana | mantido da 1.0 |
| ~~Sem conferência na fonte: 80~~ | — | substituído pela fórmula (máximo 70) | removido |

### 2.5 ICP geral e indicadores

```
ICP = Σ(nota × importância) ÷ Σ(importância)      (as 21 bases — nenhuma fica de fora)
```

Importância: 3 gasto principal de governo ou parlamentar · 2 recorte relevante · 1 complementar. Na 1.0, bases com menos de 4
dimensões ficavam fora da média (6 bases), o que elevava a nota. Junto da nota, o painel mostra: bases monitoradas, conferidas
por inteiro (nível ≥ 3), conferidas em parte (nível 2), sem conferência oficial (nível ≤ 1), **cobertura dos registros**
(registros cobertos por conferências ÷ registros de todas as bases) e problemas críticos.

### 2.6 Problemas críticos (fora da média)

Uma base aparece em **"Problemas que a média não esconde"** quando: o status é divergência ou falha de coleta; ou a importância é
≥ 2 e Atualização, Precisão, Rastreabilidade ou Integrações estão em 40 ou menos, ou a nota está abaixo de 50; ou a importância é 3
e há revisão manual pendente. Testes rasos (I baixa) **não** entram aqui sozinhos — aparecem nos avisos da própria base.

## 3. Status (selos)

| Status | Cor | Quando |
|---|---|---|
| Conferência abrangente reforçada | 🟢 verde | nível 4 |
| Conferido na fonte (abrangente) | 🟢 verde | nível 3 |
| Conferido em parte na fonte | 🟡 amarelo | nível 2 — o selo do painel mostra o percentual conferido |
| Só testes internos | ⚪ cinza | nível 1 |
| Sem evidência | ⚪ cinza | nível 0 |
| Aguardando atualização da fonte | 🟡 amarelo | a coleta funciona, mas a fonte não publicou dado novo (**não é falha do site**) |
| Pendente de revisão manual | 🟡 amarelo | itens marcados para conferência humana |
| Divergência identificada | 🔴 vermelho | a conferência na fonte encontrou valor diferente |
| Falha na coleta | 🔴 vermelho | o robô não atualizou, as duas últimas coletas legíveis falharam, ou os registros caíram mais de 10% de uma coleta para a outra; o dado anterior é mantido |

**Regra do verde (2.0):** só com a base **inteira** conferida na fonte (nível 3 ou 4). Uma base com nota alta e amostra pequena
fica amarela. Os quatro status de problema têm prioridade sobre o nível na cor.

**Avisos em linguagem simples** (em cada base): "Os testes internos passaram, mas os dados ainda não foram conferidos na fonte
oficial." · "A conferência foi feita por amostragem: X de Y registros (Z%). Nem todos os registros foram examinados." · "A fonte
oficial está indisponível ou a coleta falhou. A última versão válida dos dados foi preservada." · "A coleta funciona, mas a fonte
oficial não publicou dado novo." · "A quantidade total de registros não permite calcular a cobertura." · "Os testes internos cobrem
X de 5 tipos de conferência." · "A nota considera apenas as evidências disponíveis até DD/MM/AAAA."

### 3.0 Mudanças de aplicação (sem mudar pesos nem fórmula)

| Desde | Mudança |
|---|---|
| 28/11/2026 | **Emendas: pagamento feito junto com outras despesas.** **O que mudou:** quando a conferência encontra, na fonte oficial, um documento de pagamento maior que o valor mostrado no site, e o documento não diz quanto daquele valor veio da emenda, o pagamento passa a ficar como "não verificado", e não mais como divergência. **Por quê:** a fonte oficial mostra só o valor total de cada pagamento, que muitas vezes inclui outras despesas além da emenda (por exemplo, um contrato de transporte pago em parte com a emenda). Assim não dá para saber se a parte da emenda está certa. As 3 divergências de 28/11 eram desse tipo. **Para quem lê o site:** o valor publicado continua o do arquivo oficial do Portal da Transparência. Se o site mostrar um valor maior que o pagamento inteiro, continua aparecendo como divergência, porque a parte de uma emenda nunca pode passar do total. A conferência de 28/11 foi reavaliada com essa regra, sem nova consulta, e ganhou uma nota no histórico. **Detalhe técnico:** API da CGU (emendas/documentos não traz valor por emenda; despesas/documentos traz o total da ordem bancária); validar_fontes.py (PAGA_OUTRAS, --reavaliar-emendas no job conferir_emendas, semParteNaObservacao); config/emendas_reavaliacao.json; testes test_emendas_paga_outras.py e test_emendas_reavaliacao.py; casos Denteck 02/2026, VBTur 07/2026, Transportes Moderna 08/2026. |
| 25/11/2026 | **A conferência compara o que está no ar.** **O que mudou:** a conferência com a fonte oficial passa a ser feita sobre a versão dos dados que realmente vai ao ar. Se uma parte dos dados de um dia foi barrada e o site manteve a versão anterior, é essa versão que é conferida. Conferências feitas sobre dados que nunca foram publicados ficam no histórico, com o motivo, mas não contam para o índice. **Por quê:** em 25/11 o arquivo da Câmara dos Deputados veio incompleto, o site bloqueou a publicação, mas a conferência comparou os dados rejeitados, e o índice mostrou uma divergência que não estava no site. **Para quem lê o site:** o índice de confiabilidade passa a falar sempre do que você está vendo. **Detalhe técnico:** conferência roda depois de proteger_publicacao.py e antes do ICP; Supersalários fica "versão: conferência não aplicada" quando a base é mantida; execucoesInvalidas em dados/icp_anotacoes.json (45624667052, 45639387411, 45649872489); teste test_protecao_conferencia.py. |
| 25/11/2026 | **Tempo máximo para cada base na conferência.** **O que mudou:** cada base de dados ganhou um tempo máximo próprio para ser conferida. Se passar desse tempo, ela para e fica como "tempo esgotado", sem atrasar as outras. A ordem de conferência começa sempre pela base conferida há mais tempo, e uma base que passa 3 coletas seguidas sem conferência gera um aviso. **Por quê:** em 25/11 a conferência dos deputados federais demorou 27 minutos, porque o sistema da Câmara estava lento, e 12 bases ficaram sem conferência naquele dia. **Para quem lê o site:** uma base lenta não impede as outras de serem conferidas, e nenhuma fica esquecida por muito tempo. **Detalhe técnico:** tetos por base em validar_fontes.py (TETO_BASE_SEG: Shows 14 min, Aluguéis e Emendas 5 — Emendas passou a job próprio de 18 min em 28/11 —, Supersalários 3, Entidades e Deputados 2,5, Votações e Obras 1,5, demais 1); coletasSemConferencia em validacao_fontes.json; Governo MS, Senado, TJMS e Judiciário só respeitam o teto entre consultas; teste test_conferencia_orcamento.py. |
| 25/11/2026 | **Prefeitura de Campo Grande: órgão certo para os empenhos da SEMADI.** **O que mudou:** o arquivo que a Prefeitura exporta coloca na Secretaria de Gestão todos os gastos lançados por uma unidade chamada SEMADI, que lança a folha de pagamento e despesas de várias secretarias. Agora o site usa o órgão que aparece na página de cada gasto no portal da Prefeitura. **Por quê:** em 2026 foram 1.344 gastos, um terço de todo o valor; numa amostra de 514, só 39 eram mesmo da Secretaria de Gestão. **Para quem lê o site:** o total gasto pela Prefeitura não muda; muda quanto aparece em cada secretaria (a Educação, por exemplo, sobe R$ 1,25 bilhão). Enquanto um gasto não tem o órgão confirmado, ele aparece como "órgão não confirmado", nunca na Secretaria de Gestão. **Detalhe técnico:** unidade gestora 0505F; até 450 leituras por coleta, 3 em paralelo, guardadas no cache dos valores pagos; página com erro: nova tentativa a cada 7 dias, até 3; fonte de recurso acerta 38% e elemento de despesa 30%; teste test_prefeitura_semadi.py. |
| 22/11/2026 | **Emendas: pagamento dividido entre várias emendas.** **O que mudou:** quando um mesmo documento de pagamento serve para mais de uma emenda, a conferência passa a usar a parte de cada emenda escrita no próprio documento. Se o documento não diz a parte de cada uma, o pagamento fica "não verificado". **Por quê:** a fonte oficial mostra o valor total do documento. Na conferência de 19/11, 2 das 3 divergências eram documentos divididos entre emendas: o erro era da conferência, não do site. **Para quem lê o site:** o valor publicado continua o do arquivo oficial. Quando o arquivo oficial traz exatamente o dobro do pagamento, o site mostra uma nota neutra junto ao favorecido, sem mudar o número. **Detalhe técnico:** observação do documento lida por parte_da_emenda ("R$ 5.000,00 EMENDA 202528620007"); casos Bohn Gass 05/2026 e FAPEC 11/2026; dobroDownload no log; nota em config/notas_fonte_emendas.json (Denteck 04/2026); teste test_emendas_compartilhado.py. |
| 21/11/2026 | **Divergência já registrada não trava os testes do site.** **O que mudou:** uma divergência com a fonte oficial que já está registrada no histórico deixa de reprovar os testes automáticos do site; ela vira um aviso. Continua aparecendo no site, no status da base e no índice. **Por quê:** as 3 divergências de Emendas de 19/11 deixaram os testes reprovados por 40 execuções seguidas, e isso esconderia um erro de verdade no código. **Para quem lê o site:** nada fica escondido: a divergência continua à vista. A nota de Emendas no índice cai um pouco (de 99,5 para 98 na dimensão de integridade), porque o aviso desconta mais que o erro descontava. **Detalhe técnico:** registro = itens site × fonte gravados e a mesma conferência em dados/icp_verificacoes.jsonl; o teste só falha por erro de código, dado corrompido, CPF ou divergência sem registro; teste test_divergencia_registrada.py. |
| 21/11/2026 | **Supersalários: campo que a fonte não informa.** **O que mudou:** quando a fonte oficial não traz um dos valores comparados de um contracheque, esse valor fica "não verificado", em vez de ser completado com o número do próprio site. O contracheque só fica "confere" quando todos os valores comparados batem. **Por quê:** completar com o número do site seria comparar o site com ele mesmo. O documento do TRT24 não traz os descontos diversos (como consignado e pensão), e 5 contracheques de agosto tinham o bruto igual e só o líquido diferente. **Para quem lê o site:** quando a publicação oficial de um órgão diverge de outra publicação oficial, a pessoa ganha o selo "diverge da fonte original", com os dois valores lado a lado e uma frase neutra. O número publicado continua o do painel do CNJ. **Detalhe técnico:** vale para Anexo VIII, folha do Estado e TCE; coluna campos do CSV; divergenciasFonte em conferencia_supersalarios.json; pedidos em config/esclarecimentos_fonte.json ("em preparação" sem protocolo; "enviado (protocolo nº X)" só com protocolo); teste test_conferencia_campos.py. |
| 19/11/2026 | **Arquivos internos de trabalho protegidos com senha.** **O que mudou:** alguns arquivos de trabalho do robô ficavam guardados no GitHub, como a folha completa de salários (já sem CPF) e os PDFs originais da Câmara de Campo Grande. Agora eles só são guardados protegidos com senha, e os antigos sem proteção foram apagados. **Por quê:** os textos do site diziam que esses arquivos eram privados, mas, num projeto aberto, qualquer pessoa com conta no GitHub podia baixá-los. A informação estava errada e foi corrigida. **Para quem lê o site:** os dados publicados não mudam. Os arquivos de trabalho, com mais detalhes que o site, deixam de estar abertos. **Detalhe técnico:** artefatos do Actions cifrados com GPG simétrico (AES-256), senha num secret; imagens de páginas não viram artefato; teste no Testar site barra artefato sensível sem cifra; SEGURANCA_ARTEFATOS.md. |
| 19/11/2026 | **Conferência vale por 30 dias enquanto o dado não mudar.** **O que mudou:** um registro conferido com a fonte oficial continua contando como conferido por até 30 dias, desde que não tenha mudado desde a conferência. **Por quê:** não dá para reconferir tudo todos os dias; assim, as conferências diárias se somam ao longo do mês. **Para quem lê o site:** se um registro muda, ele volta a ser "não conferido" até a próxima conferência, e conferência com mais de 30 dias não conta mais. **Detalhe técnico:** janela móvel de 30 dias com hash do registro (seção 2.1). |
| 19/11/2026 | **Conferência só vale se feita logo depois da coleta.** **O que mudou:** a conferência com a fonte oficial só conta para o índice de confiabilidade se for feita pelo robô diário, logo depois da coleta, até 2 horas depois do início dela. **Por quê:** em 18/11 uma conferência do Governo de MS foi feita à mão 11 horas depois da coleta; nesse meio-tempo o Governo já tinha lançado novos pagamentos, e a diferença apareceu como erro do site sem ser. **Para quem lê o site:** uma divergência no índice compara os mesmos dados, no mesmo momento. A conferência de 18/11 continua no histórico, com uma nota explicando o que houve. **Detalhe técnico:** mesmo ID de execução do workflow (cujos artefatos trouxeram os dados); fora da janela, só relatório em dados/verificacao/relatorios/. |
| 19/11/2026 | **Coleta disparada à mão vale como a agendada.** **O que mudou:** nada mudou no funcionamento; a regra ficou escrita. Uma coleta completa conta do mesmo jeito para o índice, seja a agendada, seja uma iniciada à mão, desde que coleta e conferência sejam a mesma execução e a conferência fique dentro das 2 horas. **Por quê:** deixar claro que o que importa é a conferência ser da mesma coleta, não quem a iniciou. **Para quem lê o site:** uma coleta de reserva, feita quando a automática falha, tem o mesmo valor que a normal. **Detalhe técnico:** workflow "Atualizar dados diariamente" via schedule ou workflow_dispatch; a trava não filtra pelo evento; coberta por teste. |
| 19/11/2026 | **Deputados federais: nota sem data na fonte.** **O que mudou:** quando o sistema da Câmara não informa a data de uma nota fiscal, a nota é comparada pelo número, pelo valor e pelo fornecedor, dentro do mesmo deputado. Se mais de uma nota se encaixa, ela não conta como conferida e fica marcada como "ambígua". **Por quê:** sem a data, comparar por menos informações poderia confundir uma nota com outra. **Para quem lê o site:** uma nota só aparece como conferida quando não há dúvida de que é a mesma nas duas fontes. **Detalhe técnico:** chave nº da nota + valor + CNPJ/CPF; ambiguasNaFonte no histórico. |
| 19/11/2026 | **Deputados federais: CPF escondido no site.** **O que mudou:** o site esconde parte do CPF de fornecedores pessoa física, como manda a lei de proteção de dados, e a fonte oficial mostra o CPF inteiro. A conferência passa a comparar pelos dígitos visíveis junto com o número da nota e o valor, e nunca só pelos dígitos. **Por quê:** só os dígitos visíveis não bastam para ter certeza de que é a mesma pessoa. **Para quem lê o site:** o CPF continua protegido, e a nota só conta como conferida quando não há dúvida; se houver mais de uma possibilidade, ela fica "ambígua". **Detalhe técnico:** chave composta: 6 dígitos visíveis + nº da nota + valor, dentro do mesmo deputado (LGPD). |
| 19/11/2026 | **Deputados federais: fim da tolerância de 1%.** **O que mudou:** a conferência dos deputados federais aceitava diferenças de até 1% no total de cada deputado como "mudou na fonte". Essa tolerância acabou. **Por quê:** qualquer diferença de total pode ser dado faltando no site e precisa aparecer. **Para quem lê o site:** diferença no total de um deputado aparece como divergência, igual às outras bases. **Detalhe técnico:** regra removida do conferidor da Câmara. |
| 19/11/2026 | **Nota repetida pela própria fonte oficial.** **O que mudou:** quando a própria fonte oficial repete a mesma nota fiscal (mesmo número, valor, fornecedor, data e deputado), a cópia extra sai da comparação e não vira divergência. **Por quê:** a repetição é um problema da publicação oficial, não do site; notas que se repetem todo mês de forma legítima, como o aluguel do escritório, não entram nessa regra, porque a data é diferente. **Para quem lê o site:** o site segue o arquivo anual oficial da Câmara. Se o próprio arquivo traz a nota duas vezes, o site soma as duas, como o arquivo, e marca cada uma como "sinal de atenção: possível reembolso em duplicidade". O site sinaliza a repetição, mas nunca a corrige por conta própria. **Detalhe técnico:** status de registro "problema na fonte"; ficam fora as notas sem número e as passagens do SIGEPA; nota repetida só na API: o site soma uma vez e mostra os dois códigos. |
| 19/11/2026 | **Fim do "mudou na fonte" em Produção e Entidades.** **O que mudou:** duas exceções acabaram. A produção dos parlamentares aceitava até 3 projetos a mais na fonte, e as entidades aceitavam diferenças só na situação cadastral na Receita; as duas eram marcadas como "mudou na fonte". Agora qualquer diferença aparece como divergência. **Por quê:** como a conferência é feita logo depois da coleta, diferença significa dado faltando ou desatualizado no site. **Para quem lê o site:** nenhuma base marca mais "mudou na fonte"; esse termo só aparece em registros antigos do histórico, que não são alterados. **Detalhe técnico:** regras removidas dos conferidores de Produção e Entidades. |
| 19/11/2026 | **"Tempo esgotado" na conferência.** **O que mudou:** se uma base não termina de ser conferida no tempo da conferência, ela não grava um resultado pela metade. Fica valendo a última conferência completa, e o site mostra "tempo esgotado" com a data da tentativa. **Por quê:** um resultado pela metade poderia parecer melhor ou pior do que é. **Para quem lê o site:** você vê quando foi a última conferência completa de cada base. Se ela tiver mais de 30 dias, a base deixa de aparecer como conferida e fica como "vencida". **Detalhe técnico:** prazo total da conferência de 28 min, valendo dentro de cada base. |
| 19/11/2026 | **Shows e Aluguéis conferidos por amostra diária.** **O que mudou:** os contratos de shows e de aluguéis passam a ser conferidos por sorteio diário: 150 shows e 50 aluguéis por dia, começando pelos que ainda não foram conferidos no mês. **Por quê:** reconferir todos os contratos (mais de mil shows) todos os dias não cabe no tempo da conferência. **Para quem lê o site:** em cerca de um mês todos os contratos passam pela conferência. Um contrato novo ou alterado volta a "não conferido" até ser sorteado. **Detalhe técnico:** PNCP; semente = data; janela de 30 dias com hash; Shows 1.053 e Aluguéis 208 contratações (~9 min). |
| 19/11/2026 | **Câmara de Campo Grande: leitura dupla dos PDFs.** **O que mudou:** a Câmara de Campo Grande só publica os gastos dos vereadores em PDF. Cada página passa a ser lida duas vezes, de dois jeitos diferentes, no lugar da revisão manual. Se as duas leituras concordam, a nota está certa; se discordam, vale a que bate com o total impresso na página; se nenhuma bate, a nota fica "não verificada", com a página de origem. **Por quê:** a revisão manual criava uma fila que nunca acabava; a leitura dupla com a conta do total resolve quase tudo sozinha. **Para quem lê o site:** quando uma leitura corrige um valor já publicado, a nota antiga sai e entra uma correção com data. A Câmara deixa de aparecer como "pendente de revisão manual". **Detalhe técnico:** camada de texto do PDF + OCR (tesseract) da página; "resolvida automaticamente (2 extratores)"; conta de fechamento com o total impresso; correções em dados/camara_cg_correcoes.json; pesos e fórmula do ICP não mudam. |
| 19/11/2026 | **Supersalários: conferência automática de cada contracheque.** **O que mudou:** a conferência à mão dos supersalários foi trocada por uma reconsulta automática a cada coleta. Entram todos os contracheques com líquido acima do teto, mais uma amostra dos que estão perto e abaixo dele, e cada um fica "confere", "diverge" ou "não verificado", com o motivo. Quando possível, a comparação é com o documento original do próprio órgão. **Por quê:** a conferência manual não dava conta do volume e dependia de alguém fazer. **Para quem lê o site:** cada contracheque mostra o resultado da conferência e de onde ela veio. O teto e a classificação das verbas seguem a regra oficial de cada órgão, e o teto muda na data prevista em lei. **Detalhe técnico:** Governo MS: nova consulta à folha do Estado (mesma fonte); TRT24: Anexo VIII do portal do tribunal; TJMS: DadosJusBr (portal bloqueia acesso de fora do Brasil); TCE-MS: portal do TCE e PDF dos membros (camada de texto + OCR; só subsídio e VPNI visíveis, por isso "não verificado"); 100 intermediários (semente 42) e 100 abaixo do teto (semente = data, janela de 30 dias + hash); teto em config/teto.json; Anexo VIII pela Res. CNJ 102/2009; config/rubricas.json para rubricas fora do Anexo VIII; Clopper–Pearson sobre a amostra; saem conferencia_manual.csv e o workflow manual. |
| 19/11/2026 | **Conferido é só o que foi comparado um a um.** **O que mudou:** em todas as bases, um registro (uma nota, um contracheque, um projeto) só conta como conferido se foi comparado individualmente com a fonte oficial. Quando só o total de um órgão ou de um parlamentar bate, isso aparece num indicador separado, "cobertos por totais conferidos". **Por quê:** um total igual não garante que cada item dentro dele esteja certo. **Para quem lê o site:** a porcentagem de dados conferidos fica mais exigente e mais honesta, e uma divergência registro a registro aparece no site. **Detalhe técnico:** fração conferida só com comparação um a um; unidades inteiras comparadas um a um valem por 30 dias enquanto o hash da unidade não mudar. |
| 19/11/2026 | **Supersalários: total do órgão não é o mesmo que cada contracheque.** **O que mudou:** quando o total de salários de um órgão bate com a fonte, isso passa a contar como "total do órgão conferido", e não como se cada contracheque tivesse sido conferido. **Por quê:** o total pode bater mesmo com erros que se compensam entre pessoas. **Para quem lê o site:** só contam como conferidos os contracheques comparados um a um. Uma reconsulta na mesma fonte da coleta aparece como confirmação da leitura, não como fonte independente. **Detalhe técnico:** amostra diária com janela de 30 dias e hash. |

### 3.1 Versões da metodologia e histórico das notas

`dados/icp.json` traz `metodologia.versao` (2.0), a data de início e a nota geral pela metodologia anterior; cada base traz
`nota` (2.0), `notaV1` (fórmula 1.0 aplicada aos mesmos dados) e `dimensoesV1`, para explicar por que a nota mudou.
`dados/icp_notas_historico.jsonl` é **permanente** (só acrescenta): a primeira linha é o retrato da metodologia 1.0 como estava
publicado (nota 83, fórmula e notas das 24 bases); depois, uma linha por coleta do robô com a nota 2.0, a 1.0 recalculada,
o nível, o status e a cobertura de cada base. Nenhuma nota antiga é sobrescrita. Em `dados/icp.json`, `serieHistorica` traz a nota geral de cada geração recalculada só com as bases que o ICP tem hoje (notas por base registradas, pesos atuais).

## 4. Bases monitoradas (24)

| id | Base | Órgão | Import. | Conferência automática na fonte |
|---|---|---|---|---|
| camara | Câmara Municipal de CG — verba e gabinetes | Câmara de CG | 3 | não (portal só responde ao GitHub; conferência da leitura dos PDFs) |
| deputados-estaduais | Deputados estaduais — CEAP | ALEMS | 3 | sim (25 de 25) |
| deputados | Deputados federais de MS — CEAP | Câmara dos Deputados | 3 | sim (8, API com regra de sinal) |
| senadores | Senadores de MS — CEAPS | Senado | 3 | sim |
| prefeitura | Prefeitura de CG — despesas pagas | Prefeitura de CG | 3 | não |
| governo-ms | Governo de MS — Poder Executivo | Estado | 3 | sim (pago de cada um dos 66 órgãos + totais do ano) |
| emendas | Emendas parlamentares | CGU | 3 | não (manual, arquivo de 47 MB) |
| contratos-cg, supersalarios, arrecadacao, shows, alugueis, obras, publicidade, entidades, judiciario | recortes | vários | 2 | supersalários (DadosJusBr), arrecadação (Siconfi), shows e aluguéis (amostra PNCP) |
| producao, votacoes, camaras-ms, eleicoes, auditoria | complementares | vários | 1 | não |

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
| `tests/test_icp_metodologia.py` | `testar-site.yml` e job `verificar` | 2 em 92 mil não dá nota máxima · 10 de 206 = parcial (4,85%) · base inteira = nível 3, repetida em dias diferentes = 4 · sem conferência ≤ 70 e sem verde · integração quebrada ≤ 50 · sem publicação nova ≠ falha de coleta · denominador desconhecido nunca 100% · amostras repetidas não inflam · divergência reduz P e nota · 1 teste não vale I = 100 · estatística do limite · **regressão das 21 bases** (nota reproduzível, cobertura reconstruída do histórico, nível, verde, tetos, nota geral com as 24) · histórico das notas preservado |
| `tests/test_icp.py` | `testar-site.yml` e job `verificar` | status e cores; verde só com nível ≥ 3; nota 2.0 e 1.0 recalculadas; indicadores; críticos; histórico só cresce; páginas; integração |
| `tests/icp_pagina.js` | `testar-site.yml` | filtros, busca, detalhe; **nível e cobertura da tabela = dados nas 21 bases**; resumo de cobertura no topo = dados; selo por amostra não verde e com o percentual; celular |
| `tests/test_monitoramento_robos.py` | `testar-site.yml` e `verificar` | leitura dos logs, estados, proteção da publicação com falhas intencionais |
| `tests/test_cpf.py`, `test_integridade_dados.py`, `test_variacoes.py`, `tela_x_dados.js`, `filtros.js`, `smoke.js` | coleta e site | CPF, contas, variações, tela × dados, filtros, todas as abas |

## 8. Limitações

1. **O ICP mede comprovação, não honestidade do gasto.** Uma base "verificada" significa que o site reproduz fielmente o que o órgão publicou, não que o gasto foi regular.
2. **A conferência automática cobre 8 de 21 bases.** As outras ficam com o teto de 80 e o selo cinza. Prefeitura, emendas e Câmara de CG são bases importantes ainda sem conferência automática.
3. **A conferência é por amostra ou agregado** (ex.: 8 contratos do PNCP, total do ano do Estado). Um erro num registro fora da amostra pode passar.
4. **A dimensão F depende do histórico de execuções**, que começou em 17/11/2026. Até haver 14 coletas, ela reflete poucas execuções.
5. **A atribuição de avisos do log a bases** usa palavras-chave (`BASE_TXT`). Um aviso genérico vai para todas as bases do robô.
6. **A rastreabilidade da Câmara de CG está em 0** até a próxima coleta com o leitor de PDFs versão 2, que grava hash e página de cada nota.
7. **Pesos, tetos e importâncias são escolhas editoriais** do projeto. Estão publicados para que qualquer pessoa possa discordar e recalcular.
8. **Sem conferência humana periódica registrada:** conferências manuais só entram no histórico quando feitas e documentadas, e nenhuma foi inventada para preencher lacunas.

---

## Anexo A — Metodologia 1.0 (17/11/2026 a 18/11/2026), preservada

Texto original da metodologia que produziu a nota 83. A fórmula continua calculada (`nota_base` em `scripts/gerar_icp.py`, campo `notaV1`) para comparação.

### A.1 Metodologia

Cada base recebe seis notas parciais (dimensões), de 0 a 100. Quando não há dado suficiente para medir uma dimensão, ela fica **não avaliada** (`null`). Uma dimensão sem dado nunca vira 0 nem 100.

#### A.1 Dimensões e fórmulas

| Dim. | Nome | Peso | Fórmula |
|---|---|---|---|
| P | Precisão e validação | 30 | Última conferência na fonte (automática ou manual registrada no histórico). `confere` = 100; `mudou_na_fonte` (todas as diferenças ≤ 1%, explicadas por lançamentos posteriores à coleta) = 90; `diverge` = min(40, 100 × (1 − divergentes ÷ conferidos)). Até 8 dias vale inteira; de 8 a 30 dias, × 0,8; mais de 30 dias = não avaliado |
| A | Atualização | 20 | Falha de coleta = 0. Senão, com *d* = dias desde o dado mais recente e *a* = atraso normal da fonte: *d* ≤ *a* → 100; acima, max(20, 100 − 80 × (*d* − *a*) ÷ *a*) |
| I | Integridade matemática | 20 | Conferências dos testes atribuídas à base: 100 × ok ÷ (ok + erros) − min(20, 2 × avisos). As linhas de classificação da própria fonte são excluídas, para não contar duas vezes |
| T | Transparência das fontes | 10 | 20 pontos por critério: fonte oficial nomeada · link oficial · período de referência · método documentado · arquivo de dados público |
| R | Rastreabilidade | 10 | % dos registros com o identificador do documento original: link do empenho (Prefeitura), `urlPdf` (ALEMS), nota/documento (Câmara, Senado), nº de controle PNCP (shows, aluguéis), hash e página do PDF (Câmara de CG) |
| F | Funcionamento das integrações | 10 | % das últimas 14 coletas registradas em que o robô da base terminou sem falha atribuída a ela |

#### A.2 Nota da base

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

#### A.3 ICP geral

```
ICP = Σ(nota × importância) ÷ Σ(importância)     (só bases avaliadas)
```

A importância é 3 para o gasto principal de governo ou parlamentar, 2 para um recorte relevante e 1 para uma base complementar. As dimensões gerais usam a mesma ponderação.

#### A.4 Problemas críticos (fora da média)

Uma base aparece no quadro **"Problemas que a média não esconde"** quando acontece qualquer um destes casos:
- o status é *Divergência identificada* ou *Falha na coleta*;
- a importância é 2 ou mais e alguma dimensão está em 40 ou menos, ou a nota está abaixo de 60;
- a importância é 3 e há *revisão manual pendente*.

### A.2 Status (selos)

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


