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

O GitHub Actions roda todo dia às **6h BRT** e:
1. Coleta dados das APIs públicas da Câmara e do Senado
2. Baixa o CSV de CEAP da ALEMS
3. Atualiza os JSONs em `dados/`
4. Rebuilda o HTML com os dados novos
5. Commita e faz push — o Netlify detecta e faz deploy automático

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
