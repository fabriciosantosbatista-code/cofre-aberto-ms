#!/usr/bin/env python3
"""
Cofre Aberto MS — imagem de compartilhamento (og:image) de cada página: 1200×630, com o nome, o número principal e,
quando houver, a foto. É a imagem que aparece quando alguém manda o link no WhatsApp, no Facebook ou no X.

Uso (pelos geradores de página):  url = cartao("vereador-papy", "Papy", "Vereador(a) de Campo Grande · PSDB",
                                              "R$ 123,4 mil", "em verba de gabinete em 2026", foto="/fotos/p/vereador-papy.jpg")
Grava em cartoes/<nome>.jpg só quando a imagem muda. Fonte: Inter (licença OFL, em fonts/).
"""

import io, re
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont, ImageOps
except ImportError:  # sem Pillow: as páginas saem sem cartão (usam a imagem padrão do site)
    Image = None

ROOT = Path(__file__).parent.parent
PASTA = ROOT / "cartoes"
FONTES = ROOT / "fonts"
W, H = 1200, 630
OURO, OURO2, FUNDO, TINTA, CINZA = (245, 200, 66), (232, 160, 32), (11, 13, 20), (240, 243, 250), (150, 160, 182)
_cache = {}


def fonte(peso, tam):
    k = (peso, tam)
    if k not in _cache:
        nome = {"x": "Inter-ExtraBold.otf", "s": "Inter-SemiBold.otf", "r": "Inter-Regular.otf"}[peso]
        try:
            _cache[k] = ImageFont.truetype(str(FONTES / nome), tam)
        except OSError:
            _cache[k] = ImageFont.load_default(size=tam)
    return _cache[k]


def quebra(d, txt, f, largura, max_linhas):
    pal, linhas, atual = (txt or "").split(), [], ""
    for p in pal:
        t = (atual + " " + p).strip()
        if d.textlength(t, font=f) <= largura:
            atual = t
        else:
            if atual:
                linhas.append(atual)
            atual = p
    if atual:
        linhas.append(atual)
    if len(linhas) > max_linhas:
        linhas = linhas[:max_linhas]
        while linhas[-1] and d.textlength(linhas[-1] + "…", font=f) > largura:
            linhas[-1] = linhas[-1][:-1]
        linhas[-1] = linhas[-1].rstrip() + "…"
    return linhas


def cadeado(d, x, y, s):
    """cadeado aberto, como no logo (s = altura do corpo)"""
    w = s * 1.57
    lw = max(3, int(s * 0.2))
    d.arc([x + s * 0.3, y - s * 0.72, x + w * 0.8, y + s * 0.38], 180, 330, fill=OURO, width=lw)
    d.line([x + s * 0.3 + lw / 2, y - s * 0.17, x + s * 0.3 + lw / 2, y + s * 0.15], fill=OURO, width=lw)
    d.rounded_rectangle([x, y, x + w, y + s], radius=s * 0.25, fill=OURO)
    cx, cy = x + w / 2, y + s * 0.4
    d.ellipse([cx - s * 0.16, cy - s * 0.16, cx + s * 0.16, cy + s * 0.16], fill=FUNDO)
    d.rounded_rectangle([cx - s * 0.07, cy, cx + s * 0.07, cy + s * 0.34], radius=s * 0.06, fill=FUNDO)


def cartao(nome, titulo, sub, numero=None, rotulo=None, foto=None):
    if Image is None:
        return None
    img = Image.new("RGB", (W, H), FUNDO)
    d = ImageDraw.Draw(img)
    for i in range(H):  # leve degradê
        c = int(6 * i / H)
        d.line([(0, i), (W, i)], fill=(FUNDO[0] + c, FUNDO[1] + c, FUNDO[2] + c + 4))
    d.rectangle([0, 0, 14, H], fill=OURO)
    # marca
    cadeado(d, 70, 62, 34)
    d.text((136, 52), "COFRE", font=fonte("x", 34), fill=OURO)
    d.text((136 + d.textlength("COFRE ", font=fonte("x", 34)), 52), "ABERTO MS", font=fonte("x", 34), fill=TINTA)
    # foto (círculo, à direita)
    larg_txt = 1060
    if foto:
        p = ROOT / foto.lstrip("/")
        if p.exists():
            try:
                f = ImageOps.fit(Image.open(p).convert("RGB"), (300, 300), centering=(0.5, 0.3))
                m = Image.new("L", (300, 300), 0)
                ImageDraw.Draw(m).ellipse([0, 0, 299, 299], fill=255)
                d.ellipse([W - 400, 150, W - 80, 470], fill=OURO)
                img.paste(f, (W - 390, 160), m)
                larg_txt = W - 70 - 440
            except Exception:
                pass
    y = 150
    for ln in quebra(d, titulo, fonte("x", 64), larg_txt, 2):
        d.text((70, y), ln, font=fonte("x", 64), fill=TINTA)
        y += 76
    if sub:
        for ln in quebra(d, sub, fonte("r", 30), larg_txt, 2):
            d.text((70, y + 4), ln, font=fonte("r", 30), fill=CINZA)
            y += 40
    if numero:
        y = max(y + 30, 330)
        tam = 92
        while d.textlength(numero, font=fonte("x", tam)) > larg_txt and tam > 50:
            tam -= 4
        d.text((70, y), numero, font=fonte("x", tam), fill=OURO)
        y += tam + 14
        for ln in quebra(d, rotulo or "", fonte("s", 32), larg_txt, 2):
            d.text((70, y), ln, font=fonte("s", 32), fill=TINTA)
            y += 42
    d.line([(70, H - 78), (W - 70, H - 78)], fill=(40, 45, 60), width=2)
    d.text((70, H - 62), "cofreabertoms.com.br", font=fonte("s", 26), fill=OURO)
    t = "dados oficiais, atualizados todo dia"
    d.text((W - 70 - d.textlength(t, font=fonte("r", 26)), H - 62), t, font=fonte("r", 26), fill=CINZA)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=74, optimize=True, progressive=True, subsampling=2)
    nome = re.sub(r"[^a-z0-9-]+", "-", nome.lower()).strip("-")
    PASTA.mkdir(exist_ok=True)
    arq = PASTA / f"{nome}.jpg"
    if not arq.exists() or arq.read_bytes() != buf.getvalue():
        arq.write_bytes(buf.getvalue())
    return f"/cartoes/{nome}.jpg"


if __name__ == "__main__":
    print(cartao("teste", "Papy", "Vereador(a) de Campo Grande · PSDB", "R$ 123.456", "em verba indenizatória em 2026", "/fotos/p/vereador-papy.jpg"))
