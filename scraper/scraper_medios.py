#!/usr/bin/env python3
"""
SCOPE — Corpus de medios estatales (patrón FIAT).

Lee data/medios.csv (96 medios, 32 estados; método detectado por sondeo:
wp_api / rss / sitemap / no_accesible) y scrapea los accesibles:
  - wp_api: /wp-json/wp/v2/posts?after=…  (paginado, filtrable por fecha)
  - rss:    /feed  (solo lo reciente)
  - Si el WP-API responde 401/403, cae a RSS.

Cada nota se filtra con las keywords ambientales (mismas categorías que el
frontend) y se le asigna estado + categoría. Salida: data/noticias-estatales.json
con ventana de 7 días (merge con lo previo; incremental de últimos 3 días).
Costo $0: sin IA, sin base de datos.
"""
import sys, csv, json, re, html, unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import warnings
warnings.filterwarnings("ignore")
import requests

ROOT   = Path(__file__).resolve().parent.parent
MEDIOS = ROOT / "data" / "medios.csv"
OUT    = ROOT / "data" / "noticias-estatales.json"
UA     = {"User-Agent": "Mozilla/5.0 (compatible; SCOPE-GEMI/1.0; monitoreo ambiental)"}
CDMX   = timezone(timedelta(hours=-6))

VENTANA_DIAS = 7      # ventana publicada
INCREMENTAL_DIAS = 3  # lo que se scrapea por corrida

# Mismas categorías que CATS en el frontend (ids idénticos)
KEYWORDS = {
    "circular": ["economia circular", "circularidad", "reutilizacion", "ecodiseno",
                 "responsabilidad extendida del productor"],
    "agua": ["sequia", "conagua", "acuifero", "agua potable", "escasez de agua",
             "planta tratadora", "saneamiento", "agua contaminada", "rio contaminado",
             "corte de agua", "desabasto de agua", "presa "],
    "energia": ["pemex", "cfe", "apagon", "tarifas electricas", "gasoducto",
                "refineria", "huachicol", "energia solar", "energia eolica",
                "fotovoltaica", "transicion energetica", "litio", "gas natural",
                "hidrocarburos", "parque solar", "energia limpia"],
    "impuestos": ["impuesto ambiental", "impuesto verde", "ecotasa",
                  "impuesto a emisiones", "bono de carbono"],
    "residuos": ["residuos", "relleno sanitario", "tiradero", "reciclaje",
                 "contingencia ambiental", "calidad del aire", "contaminacion",
                 "derrame", "residuos peligrosos", "unicel", "popote",
                 "bolsas de plastico", "plastico de un solo uso"],
    "ambiente": ["semarnat", "profepa", "medio ambiente", "cambio climatico",
                 "deforestacion", "area natural protegida", "biodiversidad",
                 "vida silvestre", "manglar", "arrecife", "incendio forestal",
                 "tala ilegal", "tala clandestina", "reforestacion", "conafor",
                 "impacto ambiental", "ecocidio", "ambientalista", "ola de calor"],
    "agro": ["agricultura", "campesino", "ejido", "distrito de riego",
             "fertilizante", "cosecha", "ganaderia", "acuacultura",
             "sanidad vegetal", "sanidad animal", "sader", "glifosato",
             "perdida de cosecha", "sequia agricola"],
}

def norm(s):
    s = unicodedata.normalize("NFD", s or "")
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return s.lower()

def clasifica(texto):
    t = norm(texto)
    mejor, hits_max = None, 0
    for cat, kws in KEYWORDS.items():
        hits = sum(1 for k in kws if k in t)
        if hits > hits_max:
            hits_max, mejor = hits, cat
    return mejor  # None si no hay señal ambiental

def limpia(s):
    s = html.unescape(re.sub(r"<[^>]+>", " ", s or ""))
    return re.sub(r"\s+", " ", s).strip()

def scrape_wp(url, desde):
    api = url.rstrip("/") + "/wp-json/wp/v2/posts"
    r = requests.get(api, params={"per_page": 30, "after": desde.strftime("%Y-%m-%dT%H:%M:%S")},
                     headers=UA, timeout=12, verify=False)
    if r.status_code in (401, 403):
        return None  # cae a RSS
    if r.status_code != 200:
        return []
    try:
        posts = r.json()
    except Exception:
        return []
    if not isinstance(posts, list):
        return []
    out = []
    for p in posts:
        out.append({
            "titulo": limpia((p.get("title") or {}).get("rendered", "")),
            "resumen": limpia((p.get("excerpt") or {}).get("rendered", ""))[:280],
            "url": p.get("link", ""),
            "fecha": (p.get("date") or "")[:10],
        })
    return out

MESES_RSS = {"Jan":1,"Feb":2,"Mar":3,"Apr":4,"May":5,"Jun":6,
             "Jul":7,"Aug":8,"Sep":9,"Oct":10,"Nov":11,"Dec":12}

def _fecha_rss(s):
    # "Tue, 22 Jul 2026 10:30:00 +0000"
    m = re.search(r"(\d{1,2})\s+([A-Za-z]{3})\s+(\d{4})", s or "")
    if not m:
        return ""
    d, mes, a = int(m.group(1)), MESES_RSS.get(m.group(2), 0), m.group(3)
    return f"{a}-{mes:02d}-{d:02d}" if mes else ""

def _tag(item, tag):
    m = re.search(r"<" + tag + r"[^>]*>([\s\S]*?)</" + tag + ">", item)
    if not m:
        return ""
    v = m.group(1)
    v = re.sub(r"^\s*<!\[CDATA\[([\s\S]*?)\]\]>\s*$", r"\1", v)
    return v.strip()

def scrape_rss(url, desde):
    feed = url.rstrip("/") + "/feed"
    try:
        r = requests.get(feed, headers=UA, timeout=12, verify=False)
    except Exception:
        return []
    if r.status_code != 200:
        return []
    out = []
    for m in re.finditer(r"<item>([\s\S]*?)</item>", r.text):
        it = m.group(1)
        fecha = _fecha_rss(_tag(it, "pubDate"))
        if fecha and fecha < desde.strftime("%Y-%m-%d"):
            continue
        out.append({
            "titulo": limpia(_tag(it, "title")),
            "resumen": limpia(_tag(it, "description"))[:280],
            "url": limpia(re.sub(r"<[^>]+>", "", _tag(it, "link"))),
            "fecha": fecha,
        })
    return out

def main():
    desde = datetime.now(CDMX) - timedelta(days=INCREMENTAL_DIAS)
    medios = []
    with open(MEDIOS, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["metodo"] in ("wp_api", "rss"):
                medios.append(row)
    print(f"  Medios accesibles: {len(medios)}")

    nuevos, fallidos = [], 0
    for mrow in medios:
        try:
            notas = None
            if mrow["metodo"] == "wp_api":
                notas = scrape_wp(mrow["url"], desde)
            if notas is None or mrow["metodo"] == "rss":
                notas = scrape_rss(mrow["url"], desde)
            cnt = 0
            for n in notas or []:
                if not n["titulo"] or not n["url"]:
                    continue
                cat = clasifica(n["titulo"] + " " + n["resumen"])
                if not cat:
                    continue
                n["estado"] = mrow["estado"]
                n["medio"] = mrow["medio"]
                n["categoria"] = cat
                nuevos.append(n)
                cnt += 1
            if cnt:
                print(f"  {mrow['medio']} ({mrow['estado']}): {cnt} ambientales")
        except Exception as e:
            fallidos += 1
    print(f"  Nuevas ambientales: {len(nuevos)} · medios con error: {fallidos}")

    # Merge con lo previo, dedup por URL, ventana de 7 días
    try:
        prev = json.loads(OUT.read_text(encoding="utf-8")).get("items", [])
    except Exception:
        prev = []
    corte = (datetime.now(CDMX) - timedelta(days=VENTANA_DIAS)).strftime("%Y-%m-%d")
    vistos, items = set(), []
    for n in nuevos + prev:
        u = n.get("url", "")
        if not u or u in vistos:
            continue
        if (n.get("fecha") or "") < corte:
            continue
        vistos.add(u)
        items.append(n)
    items.sort(key=lambda n: n.get("fecha", ""), reverse=True)
    items = items[:400]

    OUT.write_text(json.dumps({
        "_meta": {"actualizado": datetime.now(CDMX).strftime("%Y-%m-%dT%H:%M CDMX"),
                  "ventana_dias": VENTANA_DIAS, "medios": len(medios)},
        "items": items,
    }, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"  Guardado {OUT.name}: {len(items)} notas en ventana de {VENTANA_DIAS} días")

if __name__ == "__main__":
    main()
