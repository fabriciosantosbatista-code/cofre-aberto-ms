import json, urllib.request, base64
from PIL import Image
from io import BytesIO

MAPA = {
    "Ana Portela":           "https://divulgacandcontas.tse.jus.br/divulga/rest/arquivo/img/2045202024/120002030414/90514",
    "André Salineiro":       "https://divulgacandcontas.tse.jus.br/divulga/rest/arquivo/img/2045202024/120002030403/90514",
    "Beto Avelar":           "https://divulgacandcontas.tse.jus.br/divulga/rest/arquivo/img/2045202024/120002170815/90514",
    "Carlão":                "https://divulgacandcontas.tse.jus.br/divulga/rest/arquivo/img/2045202024/120002026985/90514",
    "Clodoilson Pires":      "https://divulgacandcontas.tse.jus.br/divulga/rest/arquivo/img/2045202024/120001919752/90514",
    "Delei Pinheiro":        "https://divulgacandcontas.tse.jus.br/divulga/rest/arquivo/img/2045202024/120002170820/90514",
    "Dr. Jamal":             "https://divulgacandcontas.tse.jus.br/divulga/rest/arquivo/img/2045202024/120001994132/90514",
    "Dr. Livio":             "https://divulgacandcontas.tse.jus.br/divulga/rest/arquivo/img/2045202024/120002173605/90514",
    "Dr. Victor Rocha":      "https://divulgacandcontas.tse.jus.br/divulga/rest/arquivo/img/2045202024/120002058937/90514",
    "Fábio Rocha":           "https://divulgacandcontas.tse.jus.br/divulga/rest/arquivo/img/2045202024/120002173589/90514",
    "Flávio Cabo Almi":      "https://divulgacandcontas.tse.jus.br/divulga/rest/arquivo/img/2045202024/120002058914/90514",
    "Herculano Borges":      "https://divulgacandcontas.tse.jus.br/divulga/rest/arquivo/img/2045202024/120002173592/90514",
    "Jean Ferreira":         "https://divulgacandcontas.tse.jus.br/divulga/rest/arquivo/img/2045202024/120002030398/90514",
    "Junior Coringa":        "https://divulgacandcontas.tse.jus.br/divulga/rest/arquivo/img/2045202024/120002173602/90514",
    "Landmark":              "https://divulgacandcontas.tse.jus.br/divulga/rest/arquivo/img/2045202024/120002058944/90514",
    "Leinha":                "https://divulgacandcontas.tse.jus.br/divulga/rest/arquivo/img/2045202024/120002058930/90514",
    "Luiza Ribeiro":         "https://divulgacandcontas.tse.jus.br/divulga/rest/arquivo/img/2045202024/120002170825/90514",
    "Maicon Nogueira":       "https://divulgacandcontas.tse.jus.br/divulga/rest/arquivo/img/2045202024/120002173598/90514",
    "Marquinhos Trad":       "https://divulgacandcontas.tse.jus.br/divulga/rest/arquivo/img/2045202024/120001994127/90514",
    "Neto Santos":           "https://divulgacandcontas.tse.jus.br/divulga/rest/arquivo/img/2045202024/120002058920/90514",
    "Otávio Trad":           "https://divulgacandcontas.tse.jus.br/divulga/rest/arquivo/img/2045202024/120002058923/90514",
    "Papy":                  "https://divulgacandcontas.tse.jus.br/divulga/rest/arquivo/img/2045202024/120002026980/90514",
    "Professor Juari":       "https://divulgacandcontas.tse.jus.br/divulga/rest/arquivo/img/2045202024/120002173608/90514",
    "Professor Riverton":    "https://divulgacandcontas.tse.jus.br/divulga/rest/arquivo/img/2045202024/120002173611/90514",
    "Veterinário Francisco": "https://divulgacandcontas.tse.jus.br/divulga/rest/arquivo/img/2045202024/120002173595/90514",
    "Wilson Lands":          "https://divulgacandcontas.tse.jus.br/divulga/rest/arquivo/img/2045202024/120002030409/90514",
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
    if nome in MAPA:
        try:
            v["foto"] = baixar_b64(MAPA[nome])
            print(f"✅ {nome}")
            ok += 1
        except Exception as e:
            print(f"❌ {nome}: {e}")
            v["foto"] = None
    else:
        v["foto"] = None

print(f"\n{ok}/{len(data['vereadores'])} fotos baixadas")
with open("dados/camara_municipal.json", "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)
print("✅ camara_municipal.json salvo!")
