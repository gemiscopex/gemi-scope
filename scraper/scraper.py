import feedparser
import json
from datetime import datetime
from pathlib import Path

FUENTES = [
    {"nombre": "El Universal", "rss": "https://www.eluniversal.com.mx/rss.xml"},
    {"nombre": "La Jornada", "rss": "https://www.jornada.com.mx/rss.xml"},
    {"nombre": "El Financiero", "rss": "https://www.elfinanciero.com.mx/arc/outboundfeeds/rss/"},
    {"nombre": "SEMARNAT", "rss": "https://www.gob.mx/semarnat/rss.xml"},
    {"nombre": "Presidencia", "rss": "https://www.gob.mx/presidencia/rss.xml"}
]

PALABRAS_CLAVE = [
    "medio ambiente", "ambiental", "sostenibilidad", "sustentabilidad",
    "agua", "sequia", "inundacion", "contaminacion",
    "cambio climatico", "clima", "calentamiento global", "emisiones", "carbono",
    "energia", "energia renovable", "solar", "eolica", "hidroelectrica",
    "biodiversidad", "ecosistema", "deforestacion", "bosque",
    "semarnat", "conagua", "inecc", "residuos", "reciclaje", "plastico"
]

def es_relevante(titulo, descripcion=""):
    texto = f"{titulo} {descripcion}".lower()
    return any(palabra.lower() in texto for palabra in PALABRAS_CLAVE)

def scrape():
    noticias_nuevas = []
    for fuente in FUENTES:
        try:
            feed = feedparser.parse(fuente["rss"])
            for entrada in feed.entries:
                titulo = entrada.get("title", "")
                descripcion = entrada.get("summary", "")
                url = entrada.get("link", "")
                fecha = entrada.get("published", str(datetime.now()))
                if es_relevante(titulo, descripcion):
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
    with open(data_file, "w", encoding="utf-8") as f:
        json.dump(todas, f, ensure_ascii=False, indent=2)
    print(f"{len(noticias_nuevas)} noticias nuevas encontradas")
    print(f"Total en archivo: {len(todas)}")

if __name__ == "__main__":
    main()
