import json, urllib.request, base64
from PIL import Image
from io import BytesIO

FOTOS = {
    "Ana Portela":           "https://www.camara.ms.gov.br/news/2026/03/2026030411320617726347267aa860.jpg",
    "André Salineiro":       "https://www.camara.ms.gov.br/news/2026/03/202603041132581772634778ce3370.jpg",
    "Beto Avelar":           "https://www.camara.ms.gov.br/news/2026/03/202603041134201772634860c4dbc0.jpg",
    "Carlão":                "https://www.camara.ms.gov.br/news/2026/03/202603041136081772634968cd3a70.jpg",
    "Clodoilson Pires":      "https://www.camara.ms.gov.br/news/2026/03/202603041137181772635038241cb0.jpg",
    "Delei Pinheiro":        "https://www.camara.ms.gov.br/news/2026/03/202603041137591772635079bfbd20.jpg",
    "Dr. Jamal":             "https://www.camara.ms.gov.br/news/2026/03/202603041139111772635151fca8c0.jpg",
    "Dr. Livio":             "https://www.camara.ms.gov.br/news/2026/03/202603041140561772635256ecc8c0.jpg",
    "Dr. Victor Rocha":      "https://www.camara.ms.gov.br/news/2026/03/202603041144061772635446ff3180.jpg",
    "Fábio Rocha":           "https://www.camara.ms.gov.br/news/2026/03/202603041146201772635580bf63a0.jpg",
    "Flávio Cabo Almi":      "https://www.camara.ms.gov.br/news/2026/03/202603041147111772635631383220.jpg",
    "Herculano Borges":      "https://www.camara.ms.gov.br/news/2026/03/2026030411474717726356671ec230.jpg",
    "Jean Ferreira":         "https://www.camara.ms.gov.br/news/2026/03/202603041148241772635704ea94e0.jpg",
    "Junior Coringa":        "https://www.camara.ms.gov.br/news/2026/03/202603041150431772635843561270.jpg",
    "Landmark":              "https://www.camara.ms.gov.br/news/2026/03/2026030411522717726359473478e0.jpg",
    "Leinha":                "https://www.camara.ms.gov.br/news/2026/03/202603041153201772636000ae49f0.jpg",
    "Luiza Ribeiro":         "https://www.camara.ms.gov.br/news/2026/03/202603041154161772636056f82c80.jpg",
    "Maicon Nogueira":       "https://www.camara.ms.gov.br/news/2026/03/202603041154481772636088d4d6b0.jpg",
    "Marquinhos Trad":       "https://www.camara.ms.gov.br/news/2026/03/202603041158111772636291fba460.jpg",
    "Neto Santos":           "https://www.camara.ms.gov.br/news/2026/03/202603041325391772641539705af0.jpg",
    "Otávio Trad":           "https://www.camara.ms.gov.br/news/2026/03/2026030413263817726415980cbc10.jpg",
    "Papy":                  "https://www.camara.ms.gov.br/news/2026/03/202603041327311772641651671fe0.jpg",
    "Professor Juari":       "https://www.camara.ms.gov.br/news/2026/03/2026030413315117726419114b30b0.jpg",
    "Professor Riverton":    "https://www.camara.ms.gov.br/news/2026/03/202603041334551772642095ad2340.jpg",
    "Rafael Tavares":        "https://www.camara.ms.gov.br/news/2026/03/20260304133536177264213617cf80.jpg",
    "Ronilço Guerreiro":     "https://www.camara.ms.gov.br/news/2026/03/202603041336301772642190afee10.jpg",
    "Silvio Pitu":           "https://www.camara.ms.gov.br/news/2026/03/202603041337121772642232373920.jpg",
    "Veterinário Francisco": "https://www.camara.ms.gov.br/news/2026/03/20260304133916177264235662ddf0.jpg",
    "Wilson Lands":          "https://www.camara.ms.gov.br/news/2026/03/202603041339541772642394d44280.jpg",
}

def baixar_b64(url, size=120):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=15) as r:
        data = r.read()
    img = Image.open(BytesIO(data)).convert("RGB")
    w, h = img.size
    m = min(w, h)
    img = img.crop(((w-m)//2,(h-m)//2,(w-m)//2+m,(h-m)//2+m))
    img = img.resize((size, size), Image.LANCZOS)
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=75, optimize=True)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()

data = json.load(open("dados/camara_municipal.json", encoding="utf-8"))
ok = 0
for v in data["vereadores"]:
    nome = v["nome"]
    if nome in FOTOS:
        try:
            v["foto"] = baixar_b64(FOTOS[nome])
            print(f"✅ {nome}")
            ok += 1
        except Exception as e:
            print(f"❌ {nome}: {e}")
            v["foto"] = None

print(f"\n{ok}/29 fotos baixadas da Câmara Municipal")
with open("dados/camara_municipal.json", "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)
print("✅ Salvo!")
