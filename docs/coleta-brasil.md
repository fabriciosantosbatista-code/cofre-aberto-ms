# Coleta pelo Brasil (TJMS, Sonora e Itaporã)

Algumas fontes **recusam conexões de fora do Brasil**, inclusive dos servidores
do GitHub Actions, que ficam nos EUA:

| Fonte | Sem a coleta pelo Brasil |
|---|---|
| TJMS (portal oficial) | a folha vem do DadosJusBr, que publica o mesmo Anexo VIII do CNJ, mas com cerca de 1 mês a mais de atraso |
| Câmara de Sonora | o painel mostra os últimos dados obtidos, com o aviso "⚠️ dados de dd/mm" |
| Câmara de Itaporã | idem; o portal também mudou de endereço (já atualizado no coletor) |

A coleta pelo Brasil é um **agendamento (cron)** numa máquina no Brasil. Ele roda
só essas fontes (`scripts/coleta_brasil.py`) e publica os arquivos no
repositório. O resto continua na coleta diária do GitHub. As duas coletas não se
atropelam:
- o TJMS vindo do GitHub nunca substitui uma folha mais nova;
- as câmaras que falham no GitHub mantêm o arquivo como está.

> **Por que não um "runner" próprio do GitHub?** O repositório é público. Um
> runner próprio num repositório público pode acabar executando código de pull
> requests de terceiros dentro da sua máquina. O cron com uma chave de
> deploy só tem permissão de publicar neste repositório, e nada de fora executa
> nada na máquina.

## 1. Escolher a máquina (precisa estar no Brasil)

- **Opção grátis:** uma VM "Always Free" da Oracle Cloud na região **São Paulo**
  (`sa-saopaulo-1`), com Ubuntu, 1 GB de RAM. É suficiente.
- **Opção paga barata:** qualquer VPS com data center em São Paulo (AWS
  `sa-east-1`, Magalu Cloud, etc.).
- **Seu computador:** funciona se ficar ligado no horário agendado (Linux ou
  macOS; no Windows, use o WSL).

## 2. Instalar (uma vez)

Abra o terminal da máquina e copie um comando de cada vez.

1. Instale o Python, o git e as dependências:

   ```bash
   sudo apt-get update && sudo apt-get install -y python3 python3-pip git
   ```

   ```bash
   pip3 install --user requests pypdf Pillow
   ```

2. Crie uma **chave de deploy** só para este repositório:

   ```bash
   ssh-keygen -t ed25519 -f ~/.ssh/cofre_deploy -N "" -C "coleta-brasil"
   ```

   ```bash
   cat ~/.ssh/cofre_deploy.pub
   ```

   No GitHub, abra o repositório → **Settings → Deploy keys → Add deploy key**.
   Cole o conteúdo que apareceu, marque **Allow write access** e salve.

3. Configure o git para usar essa chave:

   ```bash
   printf 'Host github.com\n  IdentityFile ~/.ssh/cofre_deploy\n  IdentitiesOnly yes\n' >> ~/.ssh/config
   ```

4. Clone o repositório:

   ```bash
   git clone git@github.com:fabriciosantosbatista-code/cofre-aberto-ms.git ~/cofre-aberto-ms
   ```

## 3. Testar

```bash
cd ~/cofre-aberto-ms && bash scripts/coleta_brasil.sh
```

Deve aparecer "Coletando remuneração de magistrados do TJMS…" **sem** "Portal do
TJMS indisponível", e "✅ Publicado." (ou "Sem mudanças…", se nada mudou). Se a
máquina não estiver mesmo no Brasil, o TJMS continua indisponível.

## 4. Agendar (todo dia às 06:10)

O horário é depois da coleta do GitHub (04:23), para as duas não publicarem ao
mesmo tempo. Abra o agendador:

```bash
crontab -e
```

e acrescente esta linha no final:

```
10 6 * * *  cd ~/cofre-aberto-ms && bash scripts/coleta_brasil.sh >> ~/coleta_brasil.log 2>&1
```

Para ver o que aconteceu nos últimos dias:

```bash
tail -50 ~/coleta_brasil.log
```

## Observações

- A pasta `~/cofre-aberto-ms` **só serve para a coleta**: o script descarta
  qualquer alteração local e sempre começa do `main`. Não edite nada nela.
- Se uma câmara mudar de endereço, o script tenta descobrir o novo link no site
  oficial da câmara e avisa no log para atualizar `FIORILLI_CAMARAS` em
  `scripts/coletar_dados.py`.
- O monitoramento (`scripts/verificar_dados.py`) continua avisando, pela issue
  "⚠️ Alerta de dados", se o TJMS ou alguma câmara ficar parada.
