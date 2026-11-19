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
| `pdfs-camara-cg-<run>` | atualizar · coletar_verba_camara | 30 dias | PDFs originais da Câmara CG | **sim: CPF impresso** | envio **suspenso**; nenhum existia |
| `folha-supersalarios-<run>` | atualizar · coletar_emendas_alems | 90 dias | folha completa de Supersalários (nomes e contracheques; sem CPF) | **sim: nome + remuneração; decidido que é privada** | envio **suspenso**; 4 apagados |
| `camara-cg-dupla-extracao-<run>` | teste-camara-cg | 1 dia | imagens de páginas + notas não resolvidas | **sim: CPF impresso nas imagens** | envio removido; 5 apagados |
| `coleta-bloqueada-<run>` | atualizar · commit_e_push | 30 dias | relatório dos testes e cópia dos dados rejeitados (só quando o teste de CPF passou) | não (mesmo tipo de dado já publicado no Git, com CPF mascarado) | continua |
| `dados-portal`, `dados-verba-camara`, `dados-trt24`, `dados-tre-ms`, `dados-tjms`, `dados-governo-ms`, `dados-contratos-cg`, `dados-emendas-alems`, `dados-federais`, `dados-auditoria` | atualizar · coletar_* | 1 dia | JSON de `dados/` passados de um job para o outro, depois de `mascarar_cpf.py && tests/test_cpf.py` | não (os mesmos arquivos são publicados no Git; contracheques de magistrados são públicos pela Res. CNJ 102/2009) | continuam |
| `github-pages` | publicar-site | — | o site | público por definição | continua |

Workflows sem artefato: `releitura-camara-cg.yml`, `leitura-camara-cg.yml` (entrega só ao repositório privado
`cofre-aberto-leitura`), `teste-alcance-fontes.yml`, `teste-api-cgu.yml`, `testar-site.yml`.

Enquanto a guarda criptografada não existe:
- os PDFs originais da Câmara CG ficam só no runner durante a coleta (o hash de cada um continua no manifesto
  `dados/camara_cg_pdfs.json`, e o PDF pode ser baixado de novo do portal da Câmara);
- a folha completa de Supersalários não é passada ao job de conferência, e a conferência automática de Supersalários
  mantém a última publicada.

## Proposta (a decidir)

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
