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
| 21/11/2026 | **Divergência registrada não deixa o "Testar site" vermelho:** uma divergência na fonte registrada na conferência (itens site × fonte gravados e a mesma conferência no histórico permanente `dados/icp_verificacoes.jsonl`) passa a ser **aviso** no log e no teste de integridade do ICP; continua no site, no status da base ("Divergência identificada") e na precisão (P). O teste só falha por erro de código, dado corrompido, CPF ou divergência **sem** esse registro. Motivo: as 3 divergências de Emendas da conferência de 19/11 deixaram o "Testar site" vermelho em 40 execuções seguidas, o que esconderia um erro de código real. Efeito na nota de Emendas: dimensão I de 99,5 para 98,0 (aviso desconta 2 pontos; o erro descontava 0,5); status e nível não mudam. Teste: `tests/test_divergencia_registrada.py`. |
| 21/11/2026 | **Supersalários — campo que a fonte não informa:** quando a fonte não traz o campo comparado, esse campo fica **"não verificado — <fonte> não informa <campo>"**; nunca é completado com o número do próprio site (seria comparar o site com ele mesmo). O contracheque só fica "confere" se todos os campos comparados batem; com algum campo não verificado e nenhum divergente, fica "não verificado" (o motivo diz o que conferiu; coluna `campos` do CSV). Vale para toda fonte (Anexo VIII, folha do Estado, TCE). Caso que motivou: o Anexo VIII do TRT24 não informa os "descontos diversos" (consignados, pensão), que o painel do CNJ informa; em 08/2026, 5 contracheques com o bruto igual divergiam só no líquido e passaram a **bruto = confere; líquido = não verificado**. **Divergência com o Anexo VIII:** cada pessoa ganha no site o selo "diverge da fonte original", com os dois valores lado a lado (painel do CNJ × Anexo VIII do órgão) e uma frase neutra sobre a publicação do órgão (`divergenciasFonte` em `conferencia_supersalarios.json`; pedidos de esclarecimento em `config/esclarecimentos_fonte.json`: a frase diz "pedido de esclarecimento em preparação" enquanto não houver número de protocolo, e "enviado (protocolo nº X)" só depois de registrado). O número publicado continua o do painel do CNJ. Teste: `tests/test_conferencia_campos.py`. |
| 19/11/2026 | **Artefatos não são privados:** artefato do Actions num repositório público pode ser baixado por qualquer usuário logado no GitHub. Os textos que falavam em "artefato privado" estavam errados. A folha completa de Supersalários (sem CPF) e os PDFs originais da Câmara CG só viram artefato cifrados (GPG simétrico, AES-256, senha num secret); as imagens de páginas não viram artefato; os que existiam sem cifra foram apagados. Um teste no "Testar site" falha se algum workflow enviar como artefato um arquivo sensível sem criptografia (`SEGURANCA_ARTEFATOS.md`). |
| 19/11/2026 | Conferência acumulada em janela móvel de 30 dias com hash do registro (seção 2.1). |
| 19/11/2026 | **Trava de procedimento:** a conferência na fonte só entra no histórico e na nota se rodar dentro do robô diário, na mesma coleta (mesmo ID de execução, cujos artefatos trouxeram os dados) e até **2 h** depois do início dela. Fora dessa janela (rodada manual, por exemplo), gera só um relatório em `dados/verificacao/relatorios/`. Motivo: em 18/11 uma conferência manual do Governo MS rodou ~11 h depois da coleta; a fonte já tinha pagamentos lançados depois e a divergência entrou no ICP sem indicar erro nos dados (a linha continua no histórico, com anotação). |
| 19/11/2026 | **Trava de procedimento — quem disparou não importa:** uma execução completa do workflow "Atualizar dados diariamente" (coleta e conferência na mesma execução) conta igual, seja agendada ou disparada pela aba Actions (`workflow_dispatch`), desde que tenha o mesmo ID de execução e a conferência caia dentro das 2 h. A trava já funcionava assim (não filtra pelo evento); a regra ficou escrita aqui e coberta por teste. |
| 19/11/2026 | **Deputados — nota sem data na API:** quando a API da Câmara não informa a data da nota, a nota do site é comparada por nº da nota + valor + CNPJ/CPF, dentro do mesmo deputado. Se essa chave casar com mais de uma nota, não conta como conferida e fica registrada como **ambígua** (`ambiguasNaFonte` no histórico). |
| 19/11/2026 | **Deputados — CPF mascarado:** o site mostra o CPF de fornecedor pessoa física mascarado (LGPD) e a fonte tem o CPF completo; a nota é comparada pela chave composta 6 dígitos visíveis + nº da nota + valor, dentro do mesmo deputado (nunca só pelos 6 dígitos). Mais de um par possível → **ambígua**, não conferida. |
| 19/11/2026 | **Deputados — fim da regra de 1%:** o conferidor da Câmara marcava como "mudou na fonte" quando todas as diferenças de total por deputado ficavam até 1%. A regra foi removida: diferença de total aparece como **divergência**, igual às outras bases. |
| 19/11/2026 | **Novo status de registro, "problema na fonte":** quando a própria fonte repete a mesma nota — mesmo número, valor, CNPJ/CPF, data e deputado, com código de documento diferente (a data entra porque notas legítimas se repetem todo mês com o mesmo número e valor, como o recibo de aluguel do escritório; ficam fora as notas sem número e as passagens do SIGEPA, em que o mesmo bilhete tem várias linhas legítimas) —, a nota sai da comparação um a um: não conta como conferida (como "não verificado"), não vira divergência e não derruba a base; a cópia extra também sai do total da fonte. O site segue o arquivo anual oficial da Câmara: se a nota repetida está só na API, o site a soma uma vez e mostra os dois códigos; se o próprio arquivo anual traz as duas cópias, o site soma as duas, como o arquivo, e marca cada uma como "sinal de atenção: possível reembolso em duplicidade". Duplicidade da fonte é sinalizada, nunca corrigida pelo site. Qualquer outro caso continua divergência. |
| 19/11/2026 | **Produção e Entidades — fim das regras de "mudou na fonte":** Produção marcava "mudou na fonte" quando a fonte tinha até 3 projetos a mais por parlamentar; Entidades, quando só a situação cadastral diferia da Receita. As duas regras foram removidas: com a trava de 2 h, diferença é dado faltando ou desatualizado no site e aparece como **divergência**. Nenhum conferidor marca mais "mudou na fonte"; o valor só existe em registros antigos do histórico, que não são alterados. |
| 19/11/2026 | **"Tempo esgotado":** o prazo da conferência (28 min) passa a valer dentro de cada base. A base que não termina no prazo não grava resultado parcial: fica a última conferência válida, e o painel e a página da base mostram "tempo esgotado" com a data da tentativa, ao lado da data da última conferência válida. Pela regra da janela, conferência com mais de 30 dias não conta (a base perde o status de conferida e aparece como "vencida"). |
| 19/11/2026 | **Shows e Aluguéis por amostra diária:** a reconsulta de todas as contratações no PNCP não cabe no prazo da conferência (Shows: 1.053; Aluguéis: 208, ~9 min). Passam a ser conferidas por amostra diária — 150 em Shows, 50 em Aluguéis —, com semente = data, sorteando primeiro o que ainda não vale na janela de 30 dias e depois renovando as conferências mais antigas; o registro novo ou alterado (hash diferente) volta para "não conferido". |
| 19/11/2026 | **Câmara CG: revisão manual substituída por dupla extração + conta de fechamento.** Cada página dos PDFs é lida duas vezes — a camada de texto do próprio PDF e o OCR (tesseract) da página renderizada. Se as duas leituras concordam (data, valor e CNPJ), a nota fica "resolvida automaticamente (2 extratores)"; se discordam, vence a leitura que fecha com o total impresso da página, desde que a outra não feche ("conta de fechamento"). O resto fica "não verificado", com o motivo e a origem (PDF e página) — não conta como conferido e não vai para fila manual. Quando a conta de fechamento corrige um valor já publicado, sai a nota antiga e entra uma correção datada (dados/camara_cg_correcoes.json). A Câmara CG deixa de ser classificada como "pendente de revisão manual", porque essa fila não existe mais; pesos e fórmula não mudam. |
| 19/11/2026 | **Conferência manual de Supersalários substituída por reconsulta automática.** A cada coleta o robô reconsulta cada contracheque com líquido acima do teto, 100 intermediários (bruto acima e líquido abaixo; semente 42) e 100 abaixo do teto (semente = data; janela de 30 dias + hash), e cada um fica "confere", "diverge" ou "não verificado (motivo)": Governo MS — nova consulta à folha do Estado (mesma fonte, confirma a leitura); TRT24 — comparado com o Anexo VIII do portal do próprio tribunal (arquivo original do órgão); TJMS — conferido no DadosJusBr (o portal do TJMS bloqueia acesso de fora do Brasil; não conta como arquivo original do órgão); TCE-MS — servidores reconsultados no portal do TCE; membros (contracheque em PDF): releitura da camada de texto (difere do site = diverge) e OCR da página; como a página do PDF só mostra o subsídio e a VPNI (as demais rubricas ficam fora da área visível, só na camada de texto), o contracheque fica "não verificado" mesmo com as duas leituras de acordo nessas colunas. Teto versionado em config/teto.json (valor, início, lei), aplicado pelo mês do contracheque; Judiciário classificado pelas colunas do Anexo VIII (Res. CNJ 102/2009), a classificação oficial do órgão: remuneratório = subsídio + vantagens pessoais + vantagens eventuais + gratificações; indenizações ficam fora; a coluna de retenção por teto confere se o abate foi aplicado sobre o excedente do subsídio + vantagens pessoais (VPNI, ATS etc. entram no teto). config/rubricas.json fica só para rubricas fora de uma coluna do Anexo VIII (hoje, as dos membros do TCE-MS): rubrica fora da tabela deixa o contracheque "não verificado". Clopper–Pearson calculado sobre o resultado automático da amostra. Saem a lista manual (conferencia_manual.csv) e o workflow de conferência manual. |
| 19/11/2026 | **Todas as bases:** registro só conta como conferido se foi comparado um a um com a fonte (matrícula, nota, reembolso, projeto…), usando a resposta que a reconsulta já traz. Registros dentro de unidades (órgão, parlamentar, total) cujo total bateu formam um indicador à parte, "registros cobertos por totais conferidos", que não entra na fração conferida. Divergência registro a registro aparece no site. Unidades inteiras comparadas um a um valem por 30 dias enquanto o hash da unidade não mudar. |
| 19/11/2026 | Supersalários: total de órgão que bate com a fonte conta como "total do órgão conferido", não como registros conferidos; só contam os contracheques comparados um a um (amostra diária, janela de 30 dias com hash). Reconsulta marcada como "mesma fonte da coleta — confirma a leitura, não é fonte independente". |

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


