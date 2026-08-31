#!/usr/bin/env python3
"""
SCOPE — Eventualidades: restricciones a la venta de alcohol ("ley seca").

Capa de PRENSA (rápida). La ley seca es sobre todo municipal y temporal, y casi
siempre se anuncia en prensa local días antes del bando/decreto. No hay una base
nacional de bandos municipales al día, así que la detección arranca por medios vía
Google News RSS (accesible; gob.mx está tras Imperva). Cada nota se normaliza a un
EVENTO con estado, ámbito y motivo, con su fuente ligada.

Output: data/ley-seca.json  ·  se corre a diario.
Relevante para: Cerveceros de México y todo el sector bebidas (vinícolas,
destiladoras, retail, restauranteros).
"""
import sys, json, time, re, urllib.parse
from datetime import datetime, timezone
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import feedparser

sys.path.insert(0, str(Path(__file__).resolve().parent))
from scraper import es_ruido, detect_state, make_id, normalize, parse_date_str

OUTPUT_FILE = Path(__file__).parent.parent / "data" / "ley-seca.json"
MAX_TOTAL = 200
MAX_NEW   = 60

QUERIES = [
    '"ley seca" (municipio OR ayuntamiento OR alcaldía OR estado OR decreto OR bando OR aplicará OR habrá)',
    '"ley seca" (venta de alcohol OR bebidas alcohólicas OR cerveza)',
    '"prohibición de venta de alcohol" México',
    '"restricción" "venta de bebidas alcohólicas" México',
    '"ley seca" (elecciones OR jornada electoral OR grito OR fiestas patrias OR feria OR festividad)',
]

# La nota debe cruzar el dominio de restricción de venta de alcohol
TOPIC_KW = ["ley seca", "venta de alcohol", "venta de bebidas alcoholicas",
            "bebidas alcoholicas", "prohibicion de alcohol", "restriccion de alcohol",
            "prohibicion de venta", "restriccion de venta", "consumo de alcohol",
            "expendio de alcohol", "cerveza"]

# Ruido: usos NO regulatorios de "ley seca" (Prohibición de EUA, historia, béisbol,
# clima "seca", metáforas) y contextos extranjeros
EXCLUDE_KW = ["prohibition", "estados unidos ley seca", "al capone", "los intocables",
              "temporada seca", "ley seca en el beisbol", "sin hits", "no hit",
              "juego sin", "ponche", "pelicula", "serie de tv", "resena"]
FOREIGN_MARK = ["colombia", "venezuela", "bolivia", "peru", "chile", "argentina",
                "honduras", "nicaragua", "guatemala", "panama", "el salvador",
                "costa rica", "ecuador", "espana", "estados unidos", "eeuu"]
MX_MARK = ["mexic", "cdmx", "municipio", "ayuntamiento", "alcaldia", "estado de"]

# Clasificación de motivo (determinista)
MOTIVOS = [
    ("Electoral",       ["eleccion", "electoral", "jornada electoral", "comicios", "votacion", "casilla", "veda electoral"]),
    ("Festividad",      ["grito", "fiestas patrias", "fiestas patrias 2026", "independencia", "feria", "festividad",
                         "patronal", "fiestas patron", "carnaval", "semana santa", "dia de muertos", "guadalupe",
                         "verbena", "kermes", "aniversario", "fiestas de septiembre", "mes patrio", "septiembre"]),
    ("Emergencia",      ["emergencia", "proteccion civil", "huracan", "contingencia", "desastre", "inundacion", "sismo", "seguridad publica"]),
    ("Orden público",   ["operativo", "orden publico", "manifestacion", "bloqueo", "marcha", "disturbios", "partido", "clasico", "concierto", "evento masivo"]),
    ("Religioso",       ["peregrinacion", "procesion", "religios", "santo patrono", "virgen"]),
]

# Alcaldías de la CDMX (para inferir estado + ámbito cuando el título las nombra)
ALCALDIAS_CDMX = ["alvaro obregon", "azcapotzalco", "benito juarez", "coyoacan",
                  "cuajimalpa", "cuauhtemoc", "gustavo a. madero", "gustavo a madero",
                  "iztacalco", "iztapalapa", "magdalena contreras", "miguel hidalgo",
                  "milpa alta", "tlahuac", "tlalpan", "venustiano carranza", "xochimilco"]

def _motivo(t):
    tn = normalize(t)
    for nombre, kws in MOTIVOS:
        if any(k in tn for k in kws):
            return nombre
    return "Otro"

# Normaliza el nombre del estado para display consistente y con acentos
_EDO_DISPLAY = {
    "ciudad de mexico": "Ciudad de México", "cdmx": "Ciudad de México",
    "estado de mexico": "Estado de México", "mexico": "Estado de México",
    "nuevo leon": "Nuevo León", "queretaro": "Querétaro",
    "san luis potosi": "San Luis Potosí", "yucatan": "Yucatán",
    "michoacan": "Michoacán", "nayarit": "Nayarit", "cdmx.": "Ciudad de México",
}
def _edo(estado):
    if not estado:
        return ""
    return _EDO_DISPLAY.get(normalize(estado), estado)

def _ambito(t):
    tn = normalize(t)
    if "alcaldia" in tn:
        return "Alcaldía"
    if any(k in tn for k in ["estado de", "estatal", "en todo el estado", "gobierno del estado"]):
        return "Estatal"
    if any(k in tn for k in ["municipio", "ayuntamiento", "alcalde", "presidente municipal", "cabildo"]):
        return "Municipal"
    return "Municipal"  # la mayoría de las ley secas son municipales

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
            return json.load(f).get("eventos", [])
    except Exception:
        return []

def scrape():
    existing = load_existing()
    seen = {e.get("id", "") for e in existing}
    nuevos = []
    for q in QUERIES:
        try:
            feed = feedparser.parse(gnews_url(q))
        except Exception as e:
            print(f"  ERROR feed {q[:34]!r}: {str(e)[:70]}")
            continue
        add = 0
        for e in feed.entries:
            src = ""
            if hasattr(e, "source") and hasattr(e.source, "title"):
                src = e.source.title
            titulo = clean_title(e.get("title", ""), src)
            if len(titulo) < 18:
                continue
            tn = normalize(titulo)
            if any(k in tn for k in EXCLUDE_KW):
                continue
            if not any(k in tn for k in TOPIC_KW):
                continue
            estado = detect_state(titulo, "")
            alcaldia_cdmx = next((a for a in ALCALDIAS_CDMX if a in tn), None)
            if not estado and alcaldia_cdmx:
                estado = "Ciudad de México"
            mx = any(k in tn for k in MX_MARK) or bool(estado) or bool(alcaldia_cdmx)
            if not mx and any(k in tn for k in FOREIGN_MARK):
                continue
            aid = make_id(titulo, "LeySeca")
            if aid in seen:
                continue
            seen.add(aid)
            fecha = parse_date_str(e.get("published", "")) or \
                datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            nuevos.append({
                "id": aid,
                "titulo": titulo,
                "url": e.get("link", ""),
                "fuente": src or "Google News",
                "fecha_publicacion": fecha,
                "estado": _edo(estado),
                "ambito": "Alcaldía" if alcaldia_cdmx else _ambito(titulo),
                "motivo": _motivo(titulo),
            })
            add += 1
        print(f"  {q[:46]!r}: +{add}")
        time.sleep(0.4)
    nuevos.sort(key=lambda x: x.get("fecha_publicacion", ""), reverse=True)
    if len(nuevos) > MAX_NEW:
        print(f"  (tope: {len(nuevos)} -> {MAX_NEW})")
        nuevos = nuevos[:MAX_NEW]
    return nuevos, existing

def main():
    print(f"Ley seca (restricciones de venta) — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    nuevos, existing = scrape()
    print(f"Nuevos: {len(nuevos)}")
    combined = nuevos + existing
    # dedup por id conservando el más reciente
    vistos, out = set(), []
    for ev in combined:
        if ev.get("id") in vistos:
            continue
        vistos.add(ev.get("id"))
        out.append(ev)
    out.sort(key=lambda x: x.get("fecha_publicacion", ""), reverse=True)
    out = out[:MAX_TOTAL]
    data = {
        "_meta": {
            "actualizado": datetime.now(timezone.utc).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "fuente": "Prensa nacional y local vía Google News",
            "nota": "Capa de prensa (Beta). Detección de restricciones a la venta de alcohol. La vigencia exacta se confirma en el bando o periódico oficial de cada plaza.",
            "total": len(out),
        },
        "eventos": out,
    }
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    print(f"Guardado {OUTPUT_FILE.name}  |  total {len(out)}  |  nuevos {len(nuevos)}")

if __name__ == "__main__":
    main()
