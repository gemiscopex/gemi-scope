#!/usr/bin/env python3
"""
SCOPE — Monitor regulatorio de COFEPRIS.

COFEPRIS (Comisión Federal para la Protección contra Riesgos Sanitarios) no
expone RSS ni datos abiertos y su portal en gob.mx está tras el reto de Imperva,
así que su actividad regulatoria (etiquetado, publicidad de bebidas y alimentos,
alertas sanitarias, NOMs, permisos) se rastrea vía Google News RSS acotado a la
autoridad. Los resultados se fusionan en data/noticias.json para que aparezcan en
el Radar, Mi Terminal y el feed de prensa como cualquier otra fuente.

Relevante para: Cerveceros de México (publicidad/horarios de alcohol, etiquetado)
y Rotoplas (contacto con agua/alimentos, materiales sanitarios).

Output: fusionado en data/noticias.json
"""
import sys, json, time, urllib.parse
from datetime import datetime, timezone
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import feedparser

# Helpers compartidos con el scraper principal (misma taxonomía y anti-ruido)
sys.path.insert(0, str(Path(__file__).resolve().parent))
from scraper import (es_ruido, detect_categories, detect_state, make_id,
                     normalize, parse_date_str, CAT_LABEL)

OUTPUT_FILE = Path(__file__).parent.parent / "data" / "noticias.json"
MAX_TOTAL   = 600
MAX_NEW     = 30            # tope por corrida: complementa el feed, no lo inunda
FUENTE_TAG  = "Cofepris"

# COFEPRIS toca muchos temas de salud (medicamentos falsificados, clínicas) que
# NO son del alcance de Scope. Solo entran los items que cruzan estos temas
# regulatorios relevantes para el producto y sus empresas.
TOPIC_KW = ["etiquetado", "etiquetado frontal", "publicidad", "envase", "empaque",
            "plastico", "plastico de un solo uso", "contacto con alimentos",
            "pfas", "bebida", "alcohol", "cerveza", "alimento", "cosmetico",
            "suplemento", "aditivo", "edulcorante", "norma oficial", "nom-",
            "microplastico", "material reciclado", "agua embotellada", "garrafon"]

# Consultas acotadas a la autoridad (la autoridad ES el filtro de relevancia)
QUERIES = [
    'COFEPRIS (etiquetado OR "etiquetado frontal" OR publicidad OR NOM OR norma)',
    'COFEPRIS ("alerta sanitaria" OR regulación OR permiso OR "aviso de funcionamiento")',
    'COFEPRIS (bebidas OR alcohol OR alimentos OR suplementos OR cosméticos)',
    'COFEPRIS ("plásticos de un solo uso" OR envase OR "contacto con alimentos" OR PFAS)',
]
DEFAULT_CAT = "residuos"  # el frontend recategoriza vía CATS; sirve de respaldo


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


def scrape():
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
            resumen = ""
            tnorm = normalize(f"{titulo} {resumen}")
            cats = detect_categories(titulo, resumen)
            # Debe tocar un tema regulatorio del alcance (no alertas de fármacos, etc.)
            if not any(normalize(k) in tnorm for k in TOPIC_KW):
                continue
            if es_ruido(titulo, resumen, len(cats)):
                continue
            aid = make_id(titulo, FUENTE_TAG)
            if aid in seen:
                continue
            seen.add(aid)
            cat = cats[0] if cats else DEFAULT_CAT
            fecha = parse_date_str(e.get("published", "")) or \
                datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            nuevos.append({
                "id": aid,
                "titulo": titulo,
                "url": e.get("link", ""),
                "fuente": src or "Google News",
                "autoridad": "COFEPRIS",
                "resumen": resumen,
                "fecha_publicacion": fecha,
                "categoria": cat,
                "categoria_nombre": CAT_LABEL.get(cat, cat),
                "categorias": cats or [cat],
                "estado": detect_state(titulo, resumen),
                "scrapeado_en": datetime.now(timezone.utc).isoformat(),
            })
            add += 1
        print(f"  {q[:48]!r}: +{add}")
        time.sleep(0.4)
    # Los más recientes primero y tope por corrida
    nuevos.sort(key=lambda x: x.get("fecha_publicacion", ""), reverse=True)
    if len(nuevos) > MAX_NEW:
        print(f"  (tope: {len(nuevos)} → {MAX_NEW} más recientes)")
        nuevos = nuevos[:MAX_NEW]
    return nuevos, existing


def main():
    print(f"COFEPRIS monitor — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    nuevos, existing = scrape()
    print(f"Nuevos de COFEPRIS: {len(nuevos)}")
    combined = nuevos + existing
    combined.sort(key=lambda x: x.get("fecha_publicacion", ""), reverse=True)
    combined = combined[:MAX_TOTAL]
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(combined, f, ensure_ascii=False, indent=2)
    print(f"Guardado {OUTPUT_FILE.name}  |  total {len(combined)}  |  nuevas COFEPRIS {len(nuevos)}")


if __name__ == "__main__":
    main()
