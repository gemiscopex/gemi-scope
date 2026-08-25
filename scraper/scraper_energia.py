#!/usr/bin/env python3
"""
SCOPE — Monitor regulatorio del sector energía (SENER / CNE / CENACE).

La Comisión Nacional de Energía (CNE, que sustituyó a CRE y CNH en 2025), SENER y
CENACE no exponen feeds abiertos y su portal gob.mx está tras el reto de Imperva,
así que su actividad regulatoria (permisos, certificados de energía limpia,
contratos de cobertura, PRODESEN, almacenamiento/BESS, interconexión, contenido
nacional, subastas) se rastrea vía Google News RSS acotado al sector. Los
resultados se fusionan en data/noticias.json.

Los datasets del mercado eléctrico (CENACE) y de SENER se integran aparte, en
scraper_datosgob.py (organization:cenace / organization:sener), al tema "Energía".

Relevante para: Siemens Energy (generación, almacenamiento, red, transición).
"""
import sys, json, time, urllib.parse
from datetime import datetime, timezone
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import feedparser

sys.path.insert(0, str(Path(__file__).resolve().parent))
from scraper import (es_ruido, detect_categories, detect_state, make_id,
                     normalize, parse_date_str, CAT_LABEL)

OUTPUT_FILE = Path(__file__).parent.parent / "data" / "noticias.json"
MAX_TOTAL   = 600
MAX_NEW     = 30
FUENTE_TAG  = "Energia"
DEFAULT_CAT = "energia_renovable"

QUERIES = [
    'CNE (permiso OR registro OR resolución OR clausura OR "certificado de energía limpia" OR "contrato de cobertura")',
    'SENER (PRODESEN OR planeación OR "contenido nacional" OR "transición energética" OR política energética)',
    '(almacenamiento OR BESS OR "baterías") energía México (CNE OR SENER OR CENACE OR red eléctrica OR renovable)',
    '(CENACE OR "mercado eléctrico") México (interconexión OR subasta OR "energía limpia" OR nodo OR despacho OR renovable)',
    '(solar OR eólico OR fotovoltaico OR geotermia OR hidrógeno) México (CNE OR SENER OR permiso OR inversión OR proyecto)',
]

# Debe cruzar el dominio energético-regulatorio (no notas operativas de CFE)
TOPIC_KW = ["cne", "sener", "cenace", "energia limpia", "certificado de energia limpia",
            "cel", "almacenamiento", "bess", "bateria", "renovable", "solar", "eolico",
            "fotovoltaic", "geotermia", "hidrogeno", "interconexion", "prodesen",
            "contrato de cobertura", "contenido nacional", "subasta", "mercado electrico",
            "nodo", "despacho", "permiso", "transicion energetica", "cofece energia",
            "generacion distribuida", "autoconsumo", "cogeneracion"]

# Ruido operativo típico del sector que NO es regulación (apagones, tarifas domésticas)
EXCLUDE_KW = ["suspension del servicio", "a que hora", "corte de luz", "cortes de luz",
              "recibo de luz", "apagon", "sin luz", "restablece el servicio",
              "megacorte", "bajon de luz"]

# CNE también es el Consejo Nacional Electoral en Ecuador/Colombia: descarta lo electoral
ELECTORAL_KW = ["electoral", "elector", "comicios", "candidat", "votante", "escrutinio",
                "cpccs", "promocion electoral", "seccionales", "campana", "reposicion de gastos",
                "consejo nacional electoral", "urnas", "boletas", "claudia lopez", "sufragio",
                "tutela"]

# Marcadores de que la nota es de México (para no confundir CNE MX con CNE extranjero)
MX_MARK = ["mexic", "cdmx", "sener", "cenace", "cfe", "pemex", "cofece", "prodesen",
           "petroliferos", "comision nacional de energia", "sheinbaum"]
FOREIGN_MARK = ["ecuador", "colombia", "venezuela", "bolivia", "peru", "chile",
                "argentina", "honduras", "nicaragua", "guatemala", "panama", "quito", "bogota",
                "espana", "soria", "madrid", "sevilla", "andalucia", "chileno", "colombiano"]


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
            tnorm = normalize(titulo)
            if any(normalize(k) in tnorm for k in EXCLUDE_KW):
                continue
            if any(normalize(k) in tnorm for k in ELECTORAL_KW):
                continue  # CNE electoral (Ecuador/Colombia), no energético
            mx = any(k in tnorm for k in MX_MARK) or bool(detect_state(titulo))
            if not mx and any(k in tnorm for k in FOREIGN_MARK):
                continue  # nota de otro país sin ancla mexicana
            if not any(normalize(k) in tnorm for k in TOPIC_KW):
                continue
            cats = detect_categories(titulo, "")
            if es_ruido(titulo, "", len(cats)):
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
                "autoridad": "SENER/CNE",
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
    print(f"Energía (SENER/CNE/CENACE) monitor — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    nuevos, existing = scrape()
    print(f"Nuevos de energía: {len(nuevos)}")
    combined = nuevos + existing
    combined.sort(key=lambda x: x.get("fecha_publicacion", ""), reverse=True)
    combined = combined[:MAX_TOTAL]
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(combined, f, ensure_ascii=False, indent=2)
    print(f"Guardado {OUTPUT_FILE.name}  |  total {len(combined)}  |  nuevas energía {len(nuevos)}")


if __name__ == "__main__":
    main()
