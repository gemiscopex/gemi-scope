#!/usr/bin/env python3
"""
SCOPE — Scraper de noticias ambientales y regulatorias para México
Fuentes: RSS directos de medios mexicanos (sin Google News)
Output:  data/noticias.json

Fuentes verificadas y activas:
  Especializadas: Mongabay Latam, Causa Natura, Pie de Página, CEMDA, Greenpeace MX
  Generales:      La Jornada, El Financiero, Expansión, Reforma, Gaceta UNAM
"""

import feedparser
import hashlib
import json
import os
import re
import sys
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import requests
import urllib3
from bs4 import BeautifulSoup

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

OUTPUT_FILE = Path(__file__).parent.parent / "data" / "noticias.json"
MAX_TOTAL   = 600

# ---------------------------------------------------------------------------
# RSS feeds verificados y activos
# ---------------------------------------------------------------------------
RSS_FEEDS = {
    # ── Especializadas en medio ambiente ─────────────────────────────────────
    "Mongabay Latam":   "https://es.mongabay.com/feed/",
    "Causa Natura":     "https://causanatura.org/feed",
    "Pie de Pagina":    "https://piedepagina.mx/feed/",
    "CEMDA":            "https://www.cemda.org.mx/feed/",
    "Greenpeace MX":    "https://www.greenpeace.org/mexico/feed/",
    # ── Medios generales de calidad ──────────────────────────────────────────
    "La Jornada":       "https://www.jornada.com.mx/rss/edicion.xml",
    "El Financiero":    "https://www.elfinanciero.com.mx/rss/feed.xml",
    "Expansion":        "https://expansion.mx/rss",
    "Reforma":          "https://www.reforma.com/rss/portada.xml",
    "Gaceta UNAM":      "https://www.gaceta.unam.mx/feed/",
}

UA  = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
HDR = {"User-Agent": UA, "Accept": "application/rss+xml, application/xml, text/xml, */*"}

# ---------------------------------------------------------------------------
# Keywords ambientales (alineadas con scraper_presidencia.py)
# ---------------------------------------------------------------------------
KEYWORDS_AMBIENTAL = {
    "agua":             ["agua","cuenca","rio","lago","acuifero","hidric",
                         "conagua","sequia","inundacion","presa",
                         "agua potable","escasez de agua","descarga de aguas"],
    "energia_renovable":["solar","eolica","fotovoltaic","hidroelectric",
                         "renovable","cfe","sener","geotermia",
                         "parque eolico","parque solar","energia limpia",
                         "transicion energetica"],
    "hidrocarburos":    ["pemex","refineria","ducto","oleoducto","gasoducto",
                         "fracking","hidrocarburos","petroleo","gas natural",
                         "combustible","combustibles fosiles"],
    "biodiversidad":    ["semarnat","conanp","area natural","reserva",
                         "especie","extincion","jaguar","ballena","manati",
                         "vida silvestre","corredor biologico","parque nacional",
                         "zona protegida"],
    "deforestacion":    ["bosque","selva","tala","deforest","incendio forestal",
                         "conafor","manglar","reforest","cambio de uso de suelo"],
    "calidad_aire":     ["contingencia","ozono","pm2.5","pm10","emision",
                         "calidad del aire","contaminacion atmosferica",
                         "smog","calidad del aire"],
    "residuos":         ["basura","residuo","relleno sanitario","reciclaj",
                         "plastico","incinerador","economia circular",
                         "desecho peligroso","residuo toxico"],
    "cambio_climatico": ["cambio climatico","calentamiento global",
                         "carbono","gei","co2","inecc","mitigacion",
                         "lgcc","cop","paris","descarbonizacion",
                         "gases de efecto invernadero","neutralidad de carbono"],
    "mineria":          ["mineria","cianuro","tajo","concesion minera",
                         "litio","minera","camimex","royalty minero",
                         "extraccion minera"],
    "transgenico":      ["transgenico","glifosato","bayer","monsanto",
                         "semilla","soberania alimentaria","maiz nativo",
                         "plaguicida","glifo"],
}

# Fuentes especializadas: todos sus artículos pasan aunque no tengan keyword explícito
FUENTES_ESPECIALIZADAS = {"Mongabay Latam", "Causa Natura", "Pie de Pagina",
                           "CEMDA", "Greenpeace MX"}

ALL_KW = [kw for kws in KEYWORDS_AMBIENTAL.values() for kw in kws]

CAT_LABEL = {
    "agua":             "Agua",
    "energia_renovable":"Energía Renovable",
    "hidrocarburos":    "Hidrocarburos",
    "biodiversidad":    "Biodiversidad",
    "deforestacion":    "Forestal",
    "calidad_aire":     "Calidad del Aire",
    "residuos":         "Residuos",
    "cambio_climatico": "Cambio Climático",
    "mineria":          "Minería",
    "transgenico":      "Transgénico",
}

# ---------------------------------------------------------------------------
# Detección de estados
# ---------------------------------------------------------------------------
ESTADOS_KW = {
    "Aguascalientes":    ["Aguascalientes"],
    "Baja California":   ["Baja California","Tijuana","Mexicali","Ensenada"],
    "Baja California Sur":["Baja California Sur","La Paz BCS","Los Cabos"],
    "Campeche":          ["Campeche"],
    "Chiapas":           ["Chiapas","Tuxtla Gutierrez","San Cristobal"],
    "Chihuahua":         ["Chihuahua","Ciudad Juarez"],
    "Ciudad de Mexico":  ["Ciudad de Mexico","CDMX","capitalina"],
    "Coahuila":          ["Coahuila","Saltillo","Torreon"],
    "Colima":            ["Colima"],
    "Durango":           ["Durango"],
    "Guanajuato":        ["Guanajuato","Leon Guanajuato","Irapuato","Celaya"],
    "Guerrero":          ["Guerrero","Acapulco","Chilpancingo"],
    "Hidalgo":           ["Hidalgo","Pachuca"],
    "Jalisco":           ["Jalisco","Guadalajara","Zapopan"],
    "Mexico":            ["Estado de Mexico","Edomex","Toluca","Ecatepec"],
    "Michoacan":         ["Michoacan","Morelia","Uruapan"],
    "Morelos":           ["Morelos","Cuernavaca"],
    "Nayarit":           ["Nayarit","Tepic"],
    "Nuevo Leon":        ["Nuevo Leon","Monterrey","regiomontano"],
    "Oaxaca":            ["Oaxaca"],
    "Puebla":            ["Puebla","Angelopolis"],
    "Queretaro":         ["Queretaro"],
    "Quintana Roo":      ["Quintana Roo","Cancun","Playa del Carmen","Tulum"],
    "San Luis Potosi":   ["San Luis Potosi","SLP"],
    "Sinaloa":           ["Sinaloa","Culiacan","Mazatlan"],
    "Sonora":            ["Sonora","Hermosillo","Guaymas"],
    "Tabasco":           ["Tabasco","Villahermosa"],
    "Tamaulipas":        ["Tamaulipas","Matamoros","Tampico","Reynosa"],
    "Tlaxcala":          ["Tlaxcala"],
    "Veracruz":          ["Veracruz","Xalapa","Coatzacoalcos"],
    "Yucatan":           ["Yucatan","Merida"],
    "Zacatecas":         ["Zacatecas"],
}

# ---------------------------------------------------------------------------
# Spanish month abbrev → English (for feedparser date fallback)
_MESES_ES = {"ene":"Jan","feb":"Feb","mar":"Mar","abr":"Apr","may":"May",
             "jun":"Jun","jul":"Jul","ago":"Aug","sep":"Sep","oct":"Oct",
             "nov":"Nov","dic":"Dec"}

def normalize(text: str) -> str:
    t = text.lower()
    t = unicodedata.normalize("NFD", t)
    return "".join(c for c in t if unicodedata.category(c) != "Mn")

def _kw_match(kw_norm: str, text_norm: str) -> bool:
    """Word-boundary match for short keywords, substring for long ones."""
    if len(kw_norm) <= 6:
        return bool(re.search(r"\b" + re.escape(kw_norm) + r"\b", text_norm))
    return kw_norm in text_norm

def detect_categories(titulo: str, resumen: str = "") -> list:
    t = normalize(f"{titulo} {resumen}")
    return [cat for cat, kws in KEYWORDS_AMBIENTAL.items()
            if any(_kw_match(normalize(kw), t) for kw in kws)]

def is_relevant(titulo: str, resumen: str = "") -> bool:
    t = normalize(f"{titulo} {resumen}")
    return any(_kw_match(normalize(kw), t) for kw in ALL_KW)

def detect_state(titulo: str, resumen: str = "") -> str | None:
    t = normalize(f"{titulo} {resumen}")
    for estado, kws in ESTADOS_KW.items():
        for kw in kws:
            if normalize(kw) in t:
                return estado
    return None

def parse_date_str(raw: str) -> str:
    """Parse date strings including Spanish month abbrevs."""
    if not raw:
        return ""
    s = raw.lower()
    for es, en in _MESES_ES.items():
        s = s.replace(es, en)
    # Try RFC2822
    try:
        from email.utils import parsedate_to_datetime
        dt = parsedate_to_datetime(s.title())
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        pass
    # Try ISO
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        pass
    return ""

def make_id(titulo: str, fuente: str) -> str:
    return hashlib.md5(f"{titulo.lower()}|{fuente}".encode()).hexdigest()[:12]

# ---------------------------------------------------------------------------
# RSS fetcher
# ---------------------------------------------------------------------------
def fetch_feed(nombre: str, url: str) -> list:
    """Fetch one RSS feed. Returns list of normalized article dicts."""
    try:
        r = requests.get(url, headers=HDR, timeout=20, allow_redirects=True)
        if r.status_code not in (200, 301, 302):
            print(f"  [HTTP {r.status_code}] {nombre}")
            return []
        feed = feedparser.parse(r.content)
    except Exception as e:
        print(f"  [ERR] {nombre}: {e}")
        return []

    if feed.bozo and not feed.entries:
        print(f"  [BOZO/EMPTY] {nombre}")
        return []

    items = []
    for e in feed.entries:
        titulo = (e.get("title") or "").strip()
        if not titulo:
            continue

        # Fecha — feedparser parsed → raw string → fallback hoy
        fecha = ""
        for key in ("published_parsed", "updated_parsed"):
            val = e.get(key)
            if val:
                try:
                    fecha = datetime(*val[:6], tzinfo=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                except Exception:
                    pass
                if fecha:
                    break
        if not fecha:
            for key in ("published", "updated"):
                fecha = parse_date_str(e.get(key, ""))
                if fecha:
                    break
        if not fecha:
            # Fallback: fecha actual (para especializadas sin fecha en RSS)
            fecha = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        # Resumen — limpia HTML
        raw = (e.get("summary") or e.get("description") or
               (e.get("content", [{}])[0].get("value", "") if e.get("content") else ""))
        resumen = BeautifulSoup(raw, "html.parser").get_text(" ", strip=True)[:500] if raw else ""

        items.append({
            "fuente":  nombre,
            "titulo":  titulo,
            "fecha":   fecha,
            "resumen": resumen,
            "url":     e.get("link", ""),
        })

    return items

# ---------------------------------------------------------------------------
def load_existing() -> list:
    if not OUTPUT_FILE.exists():
        return []
    try:
        with open(OUTPUT_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []

# ---------------------------------------------------------------------------
def main():
    print(f"SCOPE Noticias — RSS Directo — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"Fuentes: {len(RSS_FEEDS)}")

    existing = load_existing()
    existing_ids = {a.get("id", "") for a in existing}
    print(f"Artículos existentes: {len(existing)}")

    # Fetch all feeds in parallel
    raw_all = []
    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = {pool.submit(fetch_feed, nombre, url): nombre
                   for nombre, url in RSS_FEEDS.items()}
        for fut in as_completed(futures):
            nombre = futures[fut]
            try:
                items = fut.result()
                print(f"  {nombre:22} {len(items):3} entradas")
                raw_all.extend(items)
            except Exception as e:
                print(f"  {nombre:22} ERROR: {e}")

    print(f"\nTotal bruto: {len(raw_all)} artículos")

    # Filter, categorize, deduplicate
    nuevos = []
    for item in raw_all:
        titulo  = item["titulo"]
        resumen = item["resumen"]
        fuente  = item["fuente"]

        especializada = fuente in FUENTES_ESPECIALIZADAS
        cats = detect_categories(titulo, resumen)

        # Las fuentes especializadas pasan siempre; las generales necesitan keyword
        if not cats and not especializada:
            continue
        if not cats and especializada:
            # Fuente especializada sin keyword → categoría genérica
            cats = ["biodiversidad"]

        art_id = make_id(titulo, fuente)
        if art_id in existing_ids:
            continue

        estado = detect_state(titulo, resumen)
        cat_primary = cats[0]

        nuevos.append({
            "id":               art_id,
            "titulo":           titulo,
            "url":              item["url"],
            "fuente":           fuente,
            "resumen":          resumen,
            "fecha_publicacion": item["fecha"],
            "categoria":        cat_primary,
            "categoria_nombre": CAT_LABEL.get(cat_primary, cat_primary),
            "categorias":       cats,
            "estado":           estado,
            "scrapeado_en":     datetime.now(timezone.utc).isoformat(),
        })
        existing_ids.add(art_id)

    print(f"Nuevos con relevancia ambiental: {len(nuevos)}")

    # Breakdown por fuente
    from collections import Counter
    cnt = Counter(a["fuente"] for a in nuevos)
    for src, n in cnt.most_common():
        print(f"  {src:22} {n}")

    # Merge and sort
    combined = nuevos + existing
    combined.sort(key=lambda x: x.get("fecha_publicacion", ""), reverse=True)
    combined = combined[:MAX_TOTAL]

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(combined, f, ensure_ascii=False, indent=2)

    print(f"\nGuardado: {OUTPUT_FILE}")
    print(f"Total: {len(combined)} artículos  |  Nuevos: {len(nuevos)}")


if __name__ == "__main__":
    main()
