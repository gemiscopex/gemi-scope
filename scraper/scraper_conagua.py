#!/usr/bin/env python3
"""
SCOPE — Monitor regulatorio de CONAGUA / REPDA (agua).

El registro de concesiones (REPDA) es un formulario ASP.NET sin feed abierto y el
portal de CONAGUA en gob.mx está tras el reto de Imperva. Por eso la actividad
regulatoria del agua (vedas, decretos, concesiones, disponibilidad de acuíferos,
REPDA, reglamentos) se rastrea por dos vías reales y estables:

  1. Google News RSS acotado a CONAGUA/REPDA  → fusionado en data/noticias.json
  2. Datasets abiertos de CONAGUA en datos.gob.mx → integrados por scraper_datosgob.py
     (organization:conagua) al tema "Agua" de la parrilla de datos abiertos.

Relevante para: Rotoplas (concesiones, disponibilidad, saneamiento) y Cerveceros
de México (agua para producción, vedas y cuencas).
"""
import sys, json, time, urllib.parse
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import warnings
warnings.filterwarnings("ignore")
import feedparser

sys.path.insert(0, str(Path(__file__).resolve().parent))
from scraper import (es_ruido, detect_categories, detect_state, make_id,
                     normalize, parse_date_str, CAT_LABEL)

ROOT        = Path(__file__).resolve().parent.parent
OUTPUT_FILE = ROOT / "data" / "noticias.json"
MAX_TOTAL   = 600
MAX_NEW     = 30            # tope por corrida: complementa el feed, no lo inunda
FUENTE_TAG  = "Conagua"

QUERIES = [
    'CONAGUA (veda OR concesión OR REPDA OR "título de concesión" OR "derechos de agua")',
    'CONAGUA (decreto OR reglamento OR "disponibilidad de agua" OR acuífero OR cuenca)',
    'CONAGUA (sequía OR PRONACOSE OR "reserva de agua" OR "zona de veda")',
    '"agua" México (concesión industrial OR "impuesto al agua" OR tandeo OR REPDA)',
]


def gnews_url(q):
    return ("https://news.google.com/rss/search?q="
            + urllib.parse.quote(q) + "&hl=es-419&gl=MX&ceid=MX:es-419")


def clean_title(t, src):
    t = (t or "").strip()
    if src and t.endswith(" - " + src):
        t = t[: -(len(src) + 3)].strip()
    return t


def load_existing():
    if not OUTPUT_FILE.exists():
        return []
    try:
        with open(OUTPUT_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def scrape_news():
    existing = load_existing()
    seen = {a.get("id", "") for a in existing}
    nuevos = []
    for q in QUERIES:
        try:
            feed = feedparser.parse(gnews_url(q))
        except Exception as e:
            print(f"  ERROR feed {q[:40]!r}: {str(e)[:80]}")
            continue
        add = 0
        for e in feed.entries:
            src = ""
            if hasattr(e, "source") and hasattr(e.source, "title"):
                src = e.source.title
            titulo = clean_title(e.get("title", ""), src)
            if len(titulo) < 20:
                continue
            tnorm = normalize(titulo)
            cats = detect_categories(titulo, "")
            # Debe mencionar CONAGUA/REPDA o el agua, y cruzar la taxonomía
            if "conagua" not in tnorm and "repda" not in tnorm and "agua" not in cats:
                if "agua" not in tnorm and "acuifero" not in tnorm and "cuenca" not in tnorm:
                    continue
            if es_ruido(titulo, "", len(cats)):
                continue
            aid = make_id(titulo, FUENTE_TAG)
            if aid in seen:
                continue
            seen.add(aid)
            cat = "agua" if "agua" in cats or not cats else cats[0]
            fecha = parse_date_str(e.get("published", "")) or \
                datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            nuevos.append({
                "id": aid,
                "titulo": titulo,
                "url": e.get("link", ""),
                "fuente": src or "Google News",
                "autoridad": "CONAGUA",
                "resumen": "",
                "fecha_publicacion": fecha,
                "categoria": cat,
                "categoria_nombre": CAT_LABEL.get(cat, cat),
                "categorias": cats or [cat],
                "estado": detect_state(titulo, ""),
                "scrapeado_en": datetime.now(timezone.utc).isoformat(),
            })
            add += 1
        print(f"  {q[:48]!r}: +{add}")
        time.sleep(0.4)
    nuevos.sort(key=lambda x: x.get("fecha_publicacion", ""), reverse=True)
    if len(nuevos) > MAX_NEW:
        print(f"  (tope: {len(nuevos)} → {MAX_NEW} más recientes)")
        nuevos = nuevos[:MAX_NEW]
    return nuevos, existing


def main():
    print(f"CONAGUA/REPDA monitor — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    nuevos, existing = scrape_news()
    print(f"Nuevos de CONAGUA: {len(nuevos)}")
    combined = nuevos + existing
    combined.sort(key=lambda x: x.get("fecha_publicacion", ""), reverse=True)
    combined = combined[:MAX_TOTAL]
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(combined, f, ensure_ascii=False, indent=2)
    print(f"Guardado {OUTPUT_FILE.name}  |  total {len(combined)}  |  nuevas CONAGUA {len(nuevos)}")


if __name__ == "__main__":
    main()
