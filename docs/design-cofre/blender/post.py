import sys, random
from PIL import Image, ImageChops, ImageFilter
src, dst = sys.argv[1], sys.argv[2]
im = Image.open(src).convert('RGB')
W, H = im.size
# vinheta suave (bordas ~18% mais escuras)
mask = Image.new('L', (W, H), 0)
small = Image.new('L', (160, 90), 0)
px = small.load()
for y in range(90):
    for x in range(160):
        dx, dy = (x - 79.5) / 80, (y - 44.5) / 45
        d = (dx * dx * 0.85 + dy * dy) ** 0.5
        px[x, y] = int(255 * max(0, min(1, (d - 0.55) / 0.75)) ** 1.6 * 0.5)
mask = small.resize((W, H), Image.BICUBIC).filter(ImageFilter.GaussianBlur(8))
dark = Image.new('RGB', (W, H), (0, 0, 0))
im = Image.composite(dark, im, mask)
# grão fino de câmera
noise = Image.effect_noise((W, H), 9).convert('RGB')
im = ImageChops.add(im, noise, scale=1.0, offset=-128) if False else Image.blend(im, ImageChops.overlay(im, noise), 0.18)
im.save(dst, quality=93)
print('ok', dst)
