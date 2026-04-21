"""
scraper_presidencia.py
======================
Scrapes press releases and articles from Presidencia de la República
(Claudia Sheinbaum) filtered by environmental topics.

Source: https://www.gob.mx/presidencia/es/archivo/articulos
Output: data/presidencia.json
"""

import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime, date

import requests
import urllib3
from bs4 import BeautifulSoup

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BASE_DIR    = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_FILE = os.path.join(BASE_DIR, "data", "presidencia.json")

# ---------------------------------------------------------------------------
# Environmental topic keyword sets
# ---------------------------------------------------------------------------
TOPIC_KW = {
    "agua":        ["agua", "hidric", "acuifer", "cuenca", "conagua", "sequía", "inundac"],
    "energia":     ["energía", "energia", "solar", "eólico", "eolico", "renovable", "geotermia", "hidroeléctric", "cfe", "pemex"],
    "residuos":    ["residuo", "basura", "reciclaj", "economía circular", "economia circular", "plástico", "plastico", "relleno sanitario"],
    "clima":       ["cambio climático", "cambio climatico", "clima", "temperatura", "carbono", "emisión", "emision", "lgcc", "cop", "paris"],
    "ambiente":    ["medio ambiente", "semarnat", "profepa", "ecológico", "ecologico", "ambiental", "contaminac", "aire"],
    "forestal":    ["forestal", "bosque", "selva", "reforest", "deforest", "conafor", "conanp", "biodiver"],
    "biodiversidad":["biodiversidad", "especie", "fauna", "flora", "área natural", "area natural", "reserva", "corredor biológico"],
    "fiscal":      ["impuesto ambiental", "carbono precio", "bono verde", "finanzas sostenible", "ieps combustible"],
    "industria":   ["industria sostenible", "manufactura verde", "economía verde", "economia verde", "ecoparque", "responsabilidad ambiental"],
    "mineria":     ["minería", "mineria", "extracción", "extraccion", "concesión minera", "concesion minera"],
}

ALL_KW = [kw for kws in TOPIC_KW.values() for kw in kws]

# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "es-MX,es;q=0.9",
}

def safe_get(url: str, timeout: int = 20):
    for attempt in range(3):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=timeout, verify=False)
            if resp.status_code == 200:
                return resp, True
            print(f"  [HTTP {resp.status_code}] {url}")
            return None, False
        except Exception as exc:
            print(f"  [ERR attempt {attempt+1}] {url} -> {exc}")
            if attempt < 2:
                time.sleep(2 ** attempt)
    return None, False


def soup_from_url(url: str):
    resp, ok = safe_get(url)
    if not ok or resp is None:
        return None
    try:
        return BeautifulSoup(resp.content, "html.parser")
    except Exception as exc:
        print(f"  [PARSE ERR] {url} -> {exc}")
        return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def normalize(text: str) -> str:
    """Lowercase + remove accents for keyword matching."""
    import unicodedata
    text = text.lower()
    text = unicodedata.normalize('NFD', text)
    text = ''.join(c for c in text if unicodedata.category(c) != 'Mn')
    return text


def detect_topics(text: str) -> list[str]:
    t = normalize(text)
    found = []
    for topic, kws in TOPIC_KW.items():
        if any(normalize(kw) in t for kw in kws):
            found.append(topic)
    return found


def is_relevant(text: str) -> bool:
    t = normalize(text)
    return any(normalize(kw) in t for kw in ALL_KW)


def make_id(url: str) -> str:
    return hashlib.md5(url.encode()).hexdigest()[:10]


def parse_date(raw: str) -> str:
    """Try to parse Spanish dates like '21 de abril de 2026' → '2026-04-21'."""
    MESES = {
        "enero": 1, "febrero": 2, "marzo": 3, "abril": 4,
        "mayo": 5, "junio": 6, "julio": 7, "agosto": 8,
        "septiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12,
    }
    raw = raw.strip().lower()
    m = re.search(r'(\d{1,2})\s+de\s+(\w+)\s+de\s+(\d{4})', raw)
    if m:
        day, mes_str, year = m.group(1), m.group(2), m.group(3)
        mes = MESES.get(mes_str)
        if mes:
            return f"{year}-{mes:02d}-{int(day):02d}"
    # fallback: return as-is
    return raw


# ---------------------------------------------------------------------------
# Scraper
# ---------------------------------------------------------------------------
PRESIDENCIA_URL = "https://www.gob.mx/presidencia/es/archivo/articulos"

def scrape_articles(max_pages: int = 5) -> list[dict]:
    articulos = []
    seen_ids = set()

    for page in range(1, max_pages + 1):
        url = PRESIDENCIA_URL if page == 1 else f"{PRESIDENCIA_URL}?page={page}"
        print(f"  Página {page}: {url}")
        soup = soup_from_url(url)
        if soup is None:
            print(f"  [SKIP] No se pudo cargar página {page}")
            break

        # Articles appear as <article> or <li> with class containing 'articulo' / card items
        # The gob.mx archive uses a list with class 'items-wrap' or similar
        items = soup.select("article") or soup.select(".item") or soup.select(".items-wrap li")

        if not items:
            # Try generic link scan
            items = soup.select("a[href*='/articulos/']")

        found_on_page = 0
        for item in items:
            # Title
            title_tag = (
                item.select_one("h2") or
                item.select_one("h3") or
                item.select_one(".title") or
                item.select_one("a")
            )
            if title_tag is None:
                continue
            titulo = title_tag.get_text(strip=True)
            if not titulo or len(titulo) < 8:
                continue

            # URL
            link_tag = item.select_one("a") or (title_tag if title_tag.name == "a" else None)
            if link_tag:
                href = link_tag.get("href", "")
                if href.startswith("http"):
                    art_url = href
                elif href.startswith("/"):
                    art_url = "https://www.gob.mx" + href
                else:
                    art_url = ""
            else:
                art_url = ""

            # Date
            date_tag = item.select_one("time") or item.select_one(".date") or item.select_one(".post-date")
            fecha_raw = ""
            if date_tag:
                fecha_raw = date_tag.get("datetime", "") or date_tag.get_text(strip=True)
            fecha = parse_date(fecha_raw) if fecha_raw else ""

            # Relevance check — title + any snippet text
            snippet_tag = item.select_one("p") or item.select_one(".excerpt") or item.select_one(".description")
            snippet = snippet_tag.get_text(strip=True) if snippet_tag else ""
            full_text = titulo + " " + snippet

            if not is_relevant(full_text):
                continue

            art_id = make_id(art_url or titulo)
            if art_id in seen_ids:
                continue
            seen_ids.add(art_id)

            topics = detect_topics(full_text)
            articulos.append({
                "id": art_id,
                "titulo": titulo,
                "fecha": fecha,
                "url": art_url,
                "categorias": topics,
            })
            found_on_page += 1

        print(f"    → {found_on_page} artículos relevantes encontrados")

        # If first page found nothing, don't continue
        if page == 1 and found_on_page == 0 and len(items) == 0:
            print("  No se encontraron artículos. Verificar estructura de la página.")
            break

        time.sleep(0.8)

    return articulos


# ---------------------------------------------------------------------------
# Load existing data
# ---------------------------------------------------------------------------
def load_existing() -> list[dict]:
    if not os.path.exists(OUTPUT_FILE):
        return []
    try:
        with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("articulos", [])
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    print("=== Scraper Presidencia (Sheinbaum) ===")
    print(f"Fecha: {date.today().isoformat()}")
    print()

    existing = load_existing()
    existing_ids = {a["id"] for a in existing}
    print(f"Artículos existentes en JSON: {len(existing)}")

    print("Scrapeando nuevos artículos...")
    nuevos = scrape_articles(max_pages=5)

    # Merge: add only truly new items
    added = 0
    for art in nuevos:
        if art["id"] not in existing_ids:
            existing.append(art)
            existing_ids.add(art["id"])
            added += 1

    # Sort by date descending (articles without date go to the end)
    existing.sort(key=lambda a: a.get("fecha", ""), reverse=True)

    # Keep last 200
    existing = existing[:200]

    output = {
        "articulos": existing,
        "_meta": {
            "fuente": "https://www.gob.mx/presidencia/es/archivo/articulos",
            "total": len(existing),
            "nuevos_hoy": added,
            "actualizado": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
    }

    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\nTotal guardados: {len(existing)}  |  Nuevos: {added}")
    print(f"Archivo: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
