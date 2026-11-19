# Artefatos do GitHub Actions e dados pessoais

**Artefato de repositório público não é privado.** Qualquer usuário logado no GitHub pode baixar os artefatos das
execuções de um repositório público durante a validade deles. Os textos antigos que falavam em "artefato privado"
estavam errados e foram corrigidos em 19/11/2026.

Regra: **nenhum artefato com dado pessoal no repositório público**, a não ser criptografado.
O teste `tests/test_artefatos.py`, no "Testar site", falha se algum workflow fizer `upload-artifact` de um caminho
marcado como sensível em `config/artefatos_sensiveis.json` sem que o arquivo enviado seja `.gpg`/`.age`
criptografado no mesmo job.

## Inventário (19/11/2026)

| Artefato | Workflow / job | Validade | Conteúdo | Dado pessoal? | Situação |
|---|---|---|---|---|---|
| `pdfs-camara-cg-<run>` | atualizar · coletar_verba_camara | 30 dias | PDFs originais NOVOS da Câmara CG, num `pdfs-camara-cg.tar.gpg` | **sim: CPF impresso** | só **cifrado** (AES-256); nenhum existia sem cifra quando a regra mudou |
| `folha-supersalarios-<run>` | atualizar · coletar_emendas_alems | 90 dias | folha completa de Supersalários (nomes e contracheques; sem CPF), num `folha-supersalarios.tar.gpg` | **sim: nome + remuneração; decidido que é privada** | só **cifrado** (AES-256); os 4 sem cifra foram apagados |
| `camara-cg-dupla-extracao-<run>` | teste-camara-cg | 1 dia | imagens de páginas + notas não resolvidas | **sim: CPF impresso nas imagens** | envio removido; 5 apagados |
| `coleta-bloqueada-<run>` | atualizar · commit_e_push | 30 dias | relatório dos testes e cópia dos dados rejeitados (só quando o teste de CPF passou) | não (mesmo tipo de dado já publicado no Git, com CPF mascarado) | continua |
| `dados-portal`, `dados-verba-camara`, `dados-trt24`, `dados-tre-ms`, `dados-tjms`, `dados-governo-ms`, `dados-contratos-cg`, `dados-emendas-alems`, `dados-federais`, `dados-auditoria` | atualizar · coletar_* | 1 dia | JSON de `dados/` passados de um job para o outro, depois de `mascarar_cpf.py && tests/test_cpf.py` | não (os mesmos arquivos são publicados no Git; contracheques de magistrados são públicos pela Res. CNJ 102/2009) | continuam |
| `github-pages` | publicar-site | — | o site | público por definição | continua |

Workflows sem artefato: `releitura-camara-cg.yml`, `leitura-camara-cg.yml` (entrega só ao repositório privado
`cofre-aberto-leitura`), `teste-alcance-fontes.yml`, `teste-api-cgu.yml`, `testar-site.yml`.

## Como funciona (decidido em 19/11/2026: GPG simétrico, AES-256)

- A senha fica só no secret `ARTEFATO_CHAVE` (cadastrada pelo dono; nunca passa por chat, log ou repositório).
- `scripts/cifrar_artefato.sh <pasta> <saída.gpg>`, no mesmo job e logo antes do upload: empacota a pasta (tar) e cifra
  com `gpg --symmetric --cipher-algo AES256`. A senha entra no gpg pelo descritor 3 (`--passphrase-fd 3`), lida da
  variável de ambiente — nunca na linha de comando (que apareceria em `ps` e no log) e nunca num arquivo.
- Depois de cifrar, o script confere: a pasta de saída só tem o `.gpg`; o `.gpg` é um pacote OpenPGP simétrico; e não
  há conteúdo legível dentro dele (`%PDF`, campos da folha). Se qualquer conferência falhar — ou se o secret estiver
  vazio — ele apaga a saída e **o job falha**: nada é enviado. Os dados de `dados/` desse job já foram entregues antes
  (com CPF mascarado), então a coleta e a publicação das outras bases seguem.
- O upload envia só o arquivo `.gpg` (`artefato_cifrado/…tar.gpg`), nunca a pasta original.
- A conferência de Supersalários (job `commit_e_push`) baixa o `.gpg` e decifra com `scripts/decifrar_artefato.sh`,
  com o mesmo secret.
- `tests/test_artefatos.py` e `tests/test_contencao.py` falham se algum upload de caminho sensível não for o `.gpg`
  feito por `cifrar_artefato.sh` no passo anterior, ou se o script passar a ler a senha de outro jeito.

## Como decifrar no seu computador

1. Baixe o artefato na página da execução (Actions → a execução → *Artifacts*) ou pelo terminal:
   ```bash
   gh run download <id da execução> -R fabriciosantosbatista-code/cofre-aberto-ms -n folha-supersalarios-<id da execução>
   ```
   (para os PDFs: `-n pdfs-camara-cg-<id da execução>`). Vem o arquivo `folha-supersalarios.tar.gpg`
   (ou `pdfs-camara-cg.tar.gpg`).
2. Decifre e desempacote:
   ```bash
   gpg -d folha-supersalarios.tar.gpg | tar -xf -
   ```
   O gpg pede a senha numa janela própria (a mesma do secret `ARTEFATO_CHAVE`). Não digite a senha na linha de
   comando (`--passphrase …`): ela ficaria no histórico do terminal.
3. Sai `folha_supersalarios.jsonl.gz` (ou os PDFs `<hash>.pdf`). Se a senha estiver errada, o gpg diz
   "decryption failed: Bad session key" e nada é gravado.

Trocar a senha: gere uma nova, atualize o secret. Os artefatos antigos continuam com a senha antiga até expirarem.

## Proposta original (registro)


**Criptografia simétrica com GnuPG (AES-256), chave num secret.** Recomendado para a folha de Supersalários e para os
PDFs originais.

- O dono gera uma senha aleatória longa no próprio computador (ex.: `openssl rand -base64 48`) e cadastra no secret
  `ARTEFATO_CHAVE`. A senha nunca passa por chat, log ou repositório.
- Antes do upload, no mesmo job: `gpg --batch --pinentry-mode loopback --passphrase-fd 0 --symmetric --cipher-algo AES256
  -o folha.tar.gpg folha.tar` (a senha entra pela entrada padrão, não pela linha de comando). Só o `.gpg` vira artefato.
- Quem baixa o artefato sem a senha só vê bytes cifrados. O job que precisa (conferência de Supersalários) baixa e
  decifra com o mesmo secret. O dono decifra no computador dele com `gpg -d`.
- O gpg já vem instalado no runner do GitHub; não depende de nada novo.

Por que não o repositório privado para isso: a folha (90 dias) e os PDFs (30 dias) seriam commits — ficariam no
histórico do Git para sempre (apagar o arquivo não apaga o histórico, e não reescrevemos histórico), e o repositório
cresceria a cada coleta. O repositório privado `cofre-aberto-leitura` fica só para a leitura temporária das páginas da
Câmara CG, e é apagado inteiro no fim.

Alternativa com `age` (chave pública/privada): o robô só teria a chave pública para cifrar; a privada ficaria só com o
dono e num secret apenas no job que decifra. É um pouco mais forte (o job que cifra não consegue decifrar), mas exige
instalar o `age` no runner e gerar o par de chaves. Pode ser adotada no lugar do gpg sem mudar o teste.
