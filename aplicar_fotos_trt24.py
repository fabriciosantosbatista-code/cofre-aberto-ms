import json, re, unicodedata, urllib.request, base64
from PIL import Image
from io import BytesIO

URL_MEMORIAL = "https://www.trt24.jus.br/web/memorial/desembargadores-tribunal-pleno"

def normaliza(nome):
    nome = unicodedata.normalize("NFKD", nome)
    nome = "".join(c for c in nome if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", nome).strip().upper()

def baixar_b64(url, size=120):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        data = r.read()
    img = Image.open(BytesIO(data)).convert("RGB")
    w, h = img.size
    m = min(w, h)
    img = img.crop(((w - m) // 2, (h - m) // 2, (w - m) // 2 + m, (h - m) // 2 + m))
    img = img.resize((size, size), Image.LANCZOS)
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=75, optimize=True)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()

req = urllib.request.Request(URL_MEMORIAL, headers={"User-Agent": "Mozilla/5.0"})
with urllib.request.urlopen(req, timeout=30) as r:
    html = r.read().decode("utf-8", errors="ignore")

# isola cada <img class="img_juiz"> e o texto até a PRÓXIMA ocorrência do mesmo
# marcador (ou 400 chars, se for a última) — evita capturar a tag seguinte.
matches = list(re.finditer(r'<img class="img_juiz" src="([^"]+)"[^>]*>', html))
pares = []
for i, m in enumerate(matches):
    url_foto = m.group(1)
    if not url_foto.startswith("http"):
        url_foto = "https://www.trt24.jus.br" + url_foto
    fim_zona = matches[i + 1].start() if i + 1 < len(matches) else m.end() + 400
    trecho = html[m.end():fim_zona]
    texto = re.sub(r"<[^>]+>", " ", trecho)
    texto = re.sub(r"\s+", " ", texto).strip()
    nome_m = re.search(r"Exmo\.?\s+Sr\.?\s+Des\.?\s+([A-Za-zÀ-ÿ\s]+?)(?:\s*$)", texto)
    if not nome_m:
        print(f"⚠️ Não achei nome para {url_foto} — texto: {texto[:150]!r}")
        continue
    nome = nome_m.group(1).strip()
    pares.append((nome, url_foto))

print(f"{len(pares)} desembargador(es) encontrados na galeria:")
for nome, url in pares:
    print(f"  {nome!r} -> {url}")

MAPA_NORMALIZADO = {normaliza(nome): url for nome, url in pares}

data = json.load(open("dados/trt24_magistrados.json", encoding="utf-8"))
ok = 0
for mag in data["magistrados"]:
    chave = normaliza(mag["nome"])
    url_foto = MAPA_NORMALIZADO.get(chave)
    if url_foto:
        try:
            mag["foto"] = baixar_b64(url_foto)
            print(f"✅ {mag['nome']}")
            ok += 1
        except Exception as e:
            print(f"❌ {mag['nome']}: {e}")

print(f"\n{ok}/{len(pares)} fotos aplicadas")
with open("dados/trt24_magistrados.json", "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)
print("✅ trt24_magistrados.json salvo!")
