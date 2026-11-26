# Design da capa — cofre aberto

Material de criação da nova capa do site (novembro de 2026). Esta pasta fica em `docs/`, então **não é publicada** no site (veja `.github/site.txt`).

## O que tem aqui

| Pasta | Conteúdo |
| --- | --- |
| `prototipos/` | Protótipos em HTML que abrem direto no navegador. `cofre-3d.html` é a porta 3D que abre com a rolagem (Three.js), `cofre-foto.html` é a capa com a foto realista, e `cofre-cinema.html` e `cofre-premium-claro.html` são variações que não foram adiante. |
| `renders/` | Imagens finais em 1920×1080. `cofre-aberto-capa.jpg` é a que está no site, sem placa na porta. `cofre-aberto-com-placa.jpg` é a primeira versão, com o logo numa placa no mecanismo. |
| `blender/` | Cena 3D gerada por código (`vault.py`), o acabamento de foto (`post.py`) e as texturas: logo, cédula ilustrativa e a iluminação HDRI `lobby.exr`, da Poly Haven, de licença CC0. |

As cédulas são ilustrativas e não reproduzem o desenho das notas reais.

## Como renderizar de novo

Requer Python 3.13 e o pacote `bpy` (Blender 5.3 como módulo): `pip install bpy`.

```bash
cd docs/design-cofre/blender
NOPLATE=1 LENS=24 SHIFTX=0.12 Q=final OUT=$PWD/capa.png python3 vault.py
python3 post.py capa.png capa.jpg
```

Variáveis:

- `Q`: `tiny`, `preview` (960×540) ou `final` (1920×1080, cerca de 15 min em 4 núcleos).
- `NOPLATE=1`: tira a placa com o logo de dentro da porta.
- `LENS` e `SHIFTX`: lente e deslocamento da câmera. Com `24` e `0.12`, a parede da direita fica livre para o texto.

As imagens publicadas ficam em `capa/`, em WebP para 1920 px e 1280 px, mais um recorte 4:3 para celular e um JPG de reserva.
