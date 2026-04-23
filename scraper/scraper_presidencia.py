"""
scraper_presidencia.py
======================
Scrapes mentions of Claudia Sheinbaum on environmental topics.

Source: Google News RSS (no JS captcha, no auth needed)
Output: data/presidencia.json
"""

import email.utils
import hashlib
import json
import os
import re
import sys
import time
import unicodedata
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
# Google News RSS — fuente principal (sin captcha)
# ---------------------------------------------------------------------------
GNEWS_BASE = "https://news.google.com/rss/search?hl=es-MX&gl=MX&ceid=MX:es-419"

QUERIES = [
    "Sheinbaum ambiente OR ambiental OR semarnat OR profepa OR ecologia",
    "Sheinbaum energia OR renovable OR solar OR eolica OR cfe OR pemex",
    "Sheinbaum agua OR conagua OR hidrica OR acuifero OR sequia",
    "Sheinbaum cambio climatico OR carbono OR emisiones OR cop",
    "Sheinbaum bosque OR forestal OR biodiversidad OR conafor OR conanp",
    "Sheinbaum residuos OR contaminacion OR aire OR basura OR reciclaje",
    "Sheinbaum plan ambiental OR agenda ambiental OR politica ambiental",
]

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; curl/7.68.0)", "Accept": "*/*"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def normalize(text: str) -> str:
    t = text.lower()
    t = unicodedata.normalize("NFD", t)
    return "".join(c for c in t if unicodedata.category(c) != "Mn")


def detect_topics(text: str) -> list:
    t = normalize(text)
    return [topic for topic, kws in TOPIC_KW.items()
            if any(normalize(kw) in t for kw in kws)]


def is_relevant(text: str) -> bool:
    t = normalize(text)
    return any(normalize(kw) in t for kw in ALL_KW)


def make_id(url: str) -> str:
    return hashlib.md5(url.encode()).hexdigest()[:10]


def parse_rfc2822(raw: str) -> str:
    try:
        dt = email.utils.parsedate_to_datetime(raw)
        return dt.strftime("%Y-%m-%d")
    except Exception:
        return ""


def clean_snippet(html: str) -> str:
    if not html:
        return ""
    return BeautifulSoup(html, "html.parser").get_text(" ", strip=True)[:300]


# ---------------------------------------------------------------------------
# Scraper — Google News RSS
# ---------------------------------------------------------------------------
def scrape_articles(window_days: int = 3) -> list:
    """Fetch articles from the last `window_days` days via Google News RSS."""
    all_raw = []
    seen_titles = set()

    for i, q in enumerate(QUERIES, 1):
        url = f"{GNEWS_BASE}&q={requests.utils.quote(q)}+when:{window_days}d"
        print(f"  [{i}/{len(QUERIES)}] {q[:65]}")
        try:
            resp = requests.get(url, headers=HEADERS, timeout=20, verify=False)
            if resp.status_code != 200:
                print(f"    [HTTP {resp.status_code}]")
                continue
        except Exception as exc:
            print(f"    [ERR] {exc}")
            continue

        soup = BeautifulSoup(resp.content, "xml")
        found = 0
        for item in soup.find_all("item"):
            title_tag   = item.find("title")
            link_tag    = item.find("link")
            pubdate_tag = item.find("pubDate")
            desc_tag    = item.find("description")
            source_tag  = item.find("source")

            titulo  = title_tag.text.strip()  if title_tag  else ""
            link    = link_tag.text.strip()   if link_tag   else ""
            pubdate = pubdate_tag.text.strip() if pubdate_tag else ""
            snippet = clean_snippet(desc_tag.text if desc_tag else "")
            fuente  = source_tag.text.strip() if source_tag else ""

            if fuente and titulo.endswith(f" - {fuente}"):
                titulo = titulo[:-(len(fuente) + 3)]

            fecha = parse_rfc2822(pubdate)
            tkey  = normalize(titulo)[:60]
            if tkey in seen_titles:
                continue

            full_text = titulo + " " + snippet
            if not is_relevant(full_text):
                continue

            seen_titles.add(tkey)
            all_raw.append({
                "id":         make_id(link or titulo),
                "titulo":     titulo,
                "fecha":      fecha,
                "url":        link,
                "fuente":     fuente,
                "categorias": detect_topics(full_text),
            })
            found += 1

        print(f"    → {found} relevantes")
        time.sleep(0.8)

    return all_raw


# ---------------------------------------------------------------------------
# Load existing data
# ---------------------------------------------------------------------------
def load_existing() -> list:
    if not os.path.exists(OUTPUT_FILE):
        return []
    try:
        with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
            return json.load(f).get("articulos", [])
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    print("=== Scraper Presidencia (Sheinbaum) — Google News RSS ===")
    print(f"Fecha: {date.today().isoformat()}")
    print()

    existing     = load_existing()
    existing_ids = {a["id"] for a in existing}
    print(f"Artículos existentes: {len(existing)}")

    print("Scrapeando artículos recientes (últimos 3 días)...")
    nuevos_raw = scrape_articles(window_days=3)

    added = 0
    for art in nuevos_raw:
        if art["id"] not in existing_ids:
            existing.append(art)
            existing_ids.add(art["id"])
            added += 1

    existing.sort(key=lambda a: a.get("fecha", ""), reverse=True)
    existing = existing[:300]

    output = {
        "articulos": existing,
        "_meta": {
            "fuente":    "Google News RSS / menciones Sheinbaum temas ambientales",
            "total":     len(existing),
            "nuevos_hoy": added,
            "actualizado": datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
                           if hasattr(datetime, "UTC")
                           else datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
    }

    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\nTotal guardados: {len(existing)}  |  Nuevos: {added}")
    print(f"Archivo: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
