import feedparser
import json
import unicodedata
from datetime import datetime
from pathlib import Path

def quitar_acentos(texto):
    return ''.join(
        c for c in unicodedata.normalize('NFD', texto)
        if unicodedata.category(c) != 'Mn'
    )

FUENTES = [
    {
        "nombre": "Google News - Medio Ambiente MX",
        "rss": "https://news.google.com/rss/search?q=medio+ambiente+Mexico+semarnat&hl=es-419&gl=MX&ceid=MX:es-419",
        "categoria": "circular"
    },
    {
        "nombre": "Google News - Energia MX",
        "rss": "https://news.google.com/rss/search?q=energia+renovable+solar+eolica+Mexico&hl=es-419&gl=MX&ceid=MX:es-419",
        "categoria": "energia"
    },
    {
        "nombre": "Google News - Agua MX",
        "rss": "https://news.google.com/rss/search?q=agua+Mexico+sequia+contaminacion+conagua&hl=es-419&gl=MX&ceid=MX:es-419",
        "categoria": "agua"
    },
    {
        "nombre": "Google News - Residuos MX",
        "rss": "https://news.google.com/rss/search?q=residuos+reciclaje+plastico+basura+Mexico&hl=es-419&gl=MX&ceid=MX:es-419",
        "categoria": "residuos"
    },
    {
        "nombre": "Google News - Impuestos Ambientales MX",
        "rss": "https://news.google.com/rss/search?q=impuesto+ambiental+carbono+economia+circular+Mexico&hl=es-419&gl=MX&ceid=MX:es-419",
        "categoria": "impuestos"
    },
    {
        "nombre": "SEMARNAT",
        "rss": "https://www.gob.mx/semarnat/rss.xml",
        "categoria": None
    },
    {
        "nombre": "Presidencia",
        "rss": "https://www.gob.mx/presidencia/rss.xml",
        "categoria": None
    },
]

PALABRAS_CLAVE = [
    "medio ambiente", "ambiental", "sostenibilidad", "sustentabilidad",
    "agua", "sequia", "inundacion", "contaminacion",
    "cambio climatico", "clima", "calentamiento global", "emisiones", "carbono",
    "energia", "energia renovable", "solar", "eolica", "hidroelectrica",
    "biodiversidad", "ecosistema", "deforestacion", "bosque",
    "semarnat", "conagua", "inecc", "residuos", "reciclaje", "plastico",
    "naturaleza", "flora", "fauna", "parque nacional", "reserva",
    "contaminante", "toxico", "vertido", "derrame"
]

def es_relevante(titulo, descripcion=""):
    texto = quitar_acentos(f"{titulo} {descripcion}".lower())
    return any(quitar_acentos(palabra) in texto for palabra in PALABRAS_CLAVE)

def scrape():
    noticias_nuevas = []
    for fuente in FUENTES:
        try:
            feed = feedparser.parse(fuente["rss"])
            print(f"{fuente['nombre']}: {len(feed.entries)} entradas encontradas en RSS")
            for entrada in feed.entries:
                titulo = entrada.get("title", "")
                descripcion = entrada.get("summary", "")
                url = entrada.get("link", "")
                fecha = entrada.get("published", str(datetime.now()))
                # Google News feeds already filtered by search query; gob.mx needs keyword check
                if fuente.get("categoria") or es_relevante(titulo, descripcion):
                    noticias_nuevas.append({
                        "titulo": titulo,
                        "descripcion": descripcion,
                        "url": url,
                        "fuente": fuente["nombre"],
                        "fecha_publicacion": fecha,
                        "fecha_scraping": str(datetime.now())
                    })
        except Exception as e:
            print(f"Error en {fuente['nombre']}: {e}")
    return noticias_nuevas

def main():
    data_file = Path("data/noticias.json")
    data_file.parent.mkdir(exist_ok=True)
    if data_file.exists():
        with open(data_file, "r", encoding="utf-8") as f:
            noticias_existentes = json.load(f)
    else:
        noticias_existentes = []
    urls_existentes = {n["url"] for n in noticias_existentes}
    noticias_nuevas = scrape()
    noticias_nuevas = [n for n in noticias_nuevas if n["url"] not in urls_existentes]
    todas = noticias_nuevas + noticias_existentes
    # Keep only latest 300 articles to control file size
    todas = todas[:300]
    with open(data_file, "w", encoding="utf-8") as f:
        json.dump(todas, f, ensure_ascii=False, indent=2)
    print(f"{len(noticias_nuevas)} noticias nuevas encontradas")
    print(f"Total en archivo: {len(todas)}")

if __name__ == "__main__":
    main()
