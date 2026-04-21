"""
scraper_gacetas.py
==================
Scrapes recent legislative activity with environmental relevance from:
  - Cámara de Diputados: https://gaceta.diputados.gob.mx/
  - Senado de la República: https://www.senado.gob.mx/66/gaceta_del_senado

Outputs to: data/gaceta-federal.json
"""

import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime, date, timedelta

import requests
import urllib3
from bs4 import BeautifulSoup

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BASE_DIR   = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_FILE = os.path.join(BASE_DIR, "data", "gaceta-federal.json")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
MONTH3 = {
    1: "ene", 2: "feb", 3: "mar", 4: "abr", 5: "may", 6: "jun",
    7: "jul", 8: "ago", 9: "sep", 10: "oct", 11: "nov", 12: "dic",
}

# Palabras clave de alta confianza: una sola basta para incluir el título
STRONG_KW = [
    "medio ambiente", "cambio climatico", "cambio clim",
    "semarnat", "profepa", "conagua", "conafor", "conanp",
    "lgeepa", "lgcc", "lgpgir", "lgdfs", "lgvs", "lfra", "lan ",
    "lte ", "lie ", "lgec",
    "nom-", "norma oficial mexicana",
    "residuo", "contaminac", "biodiver",
    "forestal", "reforest", "deforest",
    "hidric", "acuifer", "cuenca hidro",
    "emision", "gases de efecto",
    "sustentabilidad", "sostenibilidad",
    "responsabilidad ambiental",
    "impuesto ecolog", "tasa ecolog", "impuesto ambient",
    "area natural protegida", "anp ",
    "ecosis", "habitat",
]

# Palabras clave débiles: se requieren al menos 2 coincidencias en el título
WEAK_KW = [
    "agua", "energi", "renova", "solar", "eolic", "clima",
    "carbon", "ambient", "ecol", "mineri", "pesca", "acuacultura",
    "natural", "sustentabl", "verde", "green",
]

# Términos que invalidan el resultado aunque haya keyword match (falsos positivos comunes)
EXCLUDE_KW = [
    "derechos de agua",        # trámites de concesión, no política ambiental
    "agua potable municipal",  # infraestructura, no regulación ambiental
    "seguridad social",
    "pension", "pensión",
    "educacion", "educación",
    "salud publica",
    "violencia",
    "derechos humanos",
    "genero", "género",
    "cultura",
    "deporte",
    "turismo",
    "vivienda",
    "transporte",
]


def is_relevant(titulo: str) -> bool:
    """True si el título tiene relación genuina con medio ambiente / sostenibilidad."""
    t = titulo.lower()
    # Exclusión directa: si contiene algún término típico de falso positivo, descarta
    if any(ex in t for ex in EXCLUDE_KW):
        return False
    # Una palabra clave fuerte basta
    if any(k in t for k in STRONG_KW):
        return True
    # Palabras débiles: se necesitan al menos dos ocurrencias distintas
    weak_hits = [k for k in WEAK_KW if k in t]
    return len(weak_hits) >= 2


# Alias para compatibilidad con código existente
ENV_KW = STRONG_KW + WEAK_KW

SESSION = requests.Session()
SESSION.verify = False
SESSION.headers.update({
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_id(text: str) -> str:
    """MD5 hash truncated to 12 characters."""
    return hashlib.md5(text.encode("utf-8", errors="replace")).hexdigest()[:12]


def is_relevant(titulo: str) -> bool:
    t = titulo.lower()
    return any(k in t for k in ENV_KW)


def detect_cat(titulo: str) -> str:
    t = titulo.lower()
    if any(k in t for k in ["agua", "hídrico", "hidrico", "conagua", "acuífero", "cuenca"]):
        return "agua"
    if any(k in t for k in ["energía", "energia", "renovable", "solar", "eólico", "eolico", "cfe", "pemex", "hidrocarburo"]):
        return "energía"
    if any(k in t for k in ["residuo", "reciclaje", "plástico", "plastico", "basura", "relleno sanitario"]):
        return "residuos"
    if any(k in t for k in ["clima", "carbono", "emisión", "emision", "gei", "calentamiento"]):
        return "cambio_climatico"
    if any(k in t for k in ["ambiente", "ambiental", "ecológico", "ecologico", "semarnat", "profepa", "biodiversidad", "forestal"]):
        return "ambiental"
    return "general"


def detect_tipo(titulo: str) -> str:
    t = titulo.lower()
    if "iniciativa" in t:
        return "iniciativa"
    if "punto de acuerdo" in t or "proposicion" in t or "proposición" in t:
        return "punto_acuerdo"
    if "dictamen" in t:
        return "dictamen"
    if "decreto" in t:
        return "decreto"
    return "iniciativa"


def safe_get(url: str, timeout: int = 20):
    """GET with error handling; returns (response|None, ok:bool)."""
    try:
        resp = SESSION.get(url, timeout=timeout)
        if resp.status_code == 200:
            return resp, True
        print(f"  [HTTP {resp.status_code}] {url}")
        return None, False
    except Exception as exc:
        print(f"  [ERR] {url} -> {exc}")
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
# Diputados scraper
# ---------------------------------------------------------------------------
DIPUTADOS_BASE = "https://gaceta.diputados.gob.mx"
DIPUTADOS_TPL  = "{base}/Gaceta/66/{year}/{month3}/{date_str}.html"

# Annexes that contain env-relevant legislative items
ANNEX_PATTERNS = [
    # (pattern to match href/text, tipo)
    (re.compile(r"Anexo\s+II", re.I),  "iniciativa"),
    (re.compile(r"Anexo\s+III", re.I), "punto_acuerdo"),
    (re.compile(r"Anexo\s+IV",  re.I), "dictamen"),
]


def _weekdays_last_n(n: int = 30):
    """Yield date objects for the last n calendar days that are weekdays (Mon-Fri)."""
    today = date.today()
    current = today - timedelta(days=1)  # start from yesterday
    count = 0
    while count < n * 2:  # safety cap
        if current.weekday() < 5:  # Mon=0 … Fri=4
            yield current
            count += 1
            if count >= n:
                break
        current -= timedelta(days=1)


def _make_abs(href: str, base_url: str) -> str:
    if href.startswith("http"):
        return href
    if href.startswith("/"):
        return DIPUTADOS_BASE + href
    return base_url.rsplit("/", 1)[0] + "/" + href


def _extract_items_from_soup(soup, page_url: str, fecha_str: str, tipo: str, partido: str = "") -> list:
    """Extract env-relevant document titles from a Gaceta sub-page (TOC anchors)."""
    items = []
    seen = set()
    for a in soup.find_all("a", href=True):
        title = " ".join(a.get_text(" ", strip=True).split())
        href  = a["href"].strip()
        if len(title) < 25 or not is_relevant(title):
            continue
        # Internal anchors (#Iniciativa1) → build full URL
        if href.startswith("#"):
            full_url = page_url + href
        else:
            full_url = _make_abs(href, page_url)
        if full_url in seen:
            continue
        seen.add(full_url)
        items.append({
            "titulo":    title[:350],
            "tipo":      tipo,
            "fecha":     fecha_str,
            "autor":     _extract_autor(title),
            "partido":   partido,
            "categoria": detect_cat(title),
            "url":       full_url,
            "id":        make_id(full_url),
        })
    return items


def _parse_annex_page(annex_url: str, fecha_str: str, tipo: str) -> list:
    """
    Parse an Anexo index page (e.g. 20260408-II.html).
    Gaceta Diputados structure:
      - Anexo II/III page = index with links to sub-pages (II-1, II-2 ...)
      - Sub-pages contain the actual TOC of document titles as anchors
    """
    soup = soup_from_url(annex_url)
    if soup is None:
        return []

    items = []

    # Find sub-page links (e.g. 20260408-II-1.html, 20260408-III-2.html)
    # Ignore PDF links
    sub_links = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href.endswith(".pdf") or href.endswith(".PDF"):
            continue
        if re.search(r'-II-\d|III-\d|IV-\d', href):
            abs_url = _make_abs(href, annex_url)
            if abs_url not in sub_links:
                sub_links.append(abs_url)

    if sub_links:
        # Multi-level: follow sub-pages
        for sub_url in sub_links:
            # Detect party from the link text
            a_el = soup.find("a", href=lambda h: h and sub_url.endswith(h.lstrip("/")))
            partido = _extract_partido(a_el.find_parent().get_text(" ") if a_el and a_el.find_parent() else "")
            time.sleep(0.4)
            sub_soup = soup_from_url(sub_url)
            if sub_soup:
                found = _extract_items_from_soup(sub_soup, sub_url, fecha_str, tipo, partido)
                items.extend(found)
    else:
        # Single-level: this page itself has the items
        items = _extract_items_from_soup(soup, annex_url, fecha_str, tipo)

    return items


def _extract_autor(text: str) -> str:
    """Heuristically extract author name from title text."""
    patterns = [
        r"(?:Dip\.|Diputad[oa])\s+([A-ZÁÉÍÓÚÑ][a-záéíóúñ]+(?:\s+[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+){1,4})",
        r"(?:Sen\.|Senador[a]?)\s+([A-ZÁÉÍÓÚÑ][a-záéíóúñ]+(?:\s+[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+){1,4})",
        r"presentada\s+por\s+(?:el|la|los|las)?\s*(?:Dip\.|Sen\.|Diputad[oa]|Senador[a]?)?\s*([A-ZÁÉÍÓÚÑ][a-záéíóúñ]+(?:\s+[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+){1,4})",
    ]
    for pat in patterns:
        m = re.search(pat, text)
        if m:
            return m.group(1).strip()
    return ""


def _extract_partido(text: str) -> str:
    parties = {
        "MORENA": ["MORENA", "morena"],
        "PAN":    ["PAN", "Acción Nacional"],
        "PRI":    ["PRI", "Revolucionario Institucional"],
        "PT":     [r"\bPT\b"],
        "PVEM":   ["PVEM", "Verde Ecologista"],
        "MC":     [r"\bMC\b", "Movimiento Ciudadano"],
        "PRD":    ["PRD", "Revolución Democrática"],
    }
    for name, kws in parties.items():
        for kw in kws:
            if re.search(kw, text):
                return name
    return ""


def _scrape_day_diputados(day: date) -> list:
    """Scrape one day's Gaceta page and return env-relevant items."""
    date_str  = day.strftime("%Y%m%d")
    year      = day.year
    month_key = MONTH3[day.month]
    fecha_str = day.strftime("%Y-%m-%d")

    day_url = DIPUTADOS_TPL.format(
        base=DIPUTADOS_BASE, year=year, month3=month_key, date_str=date_str
    )

    soup = soup_from_url(day_url)
    if soup is None:
        return []

    print(f"  [Diputados] {fecha_str} -> {day_url}")

    items = []

    # Find links to Anexo pages on this day's index
    for a in soup.find_all("a", href=True):
        text = a.get_text(strip=True)
        href = a["href"]

        matched_tipo = None
        for pattern, tipo in ANNEX_PATTERNS:
            if pattern.search(text) or pattern.search(href):
                matched_tipo = tipo
                break

        if matched_tipo is None:
            continue

        # Build absolute URL for the annex
        if href.startswith("http"):
            annex_url = href
        elif href.startswith("/"):
            annex_url = DIPUTADOS_BASE + href
        else:
            base_path = day_url.rsplit("/", 1)[0]
            annex_url = base_path + "/" + href

        time.sleep(0.5)
        annex_items = _parse_annex_page(annex_url, fecha_str, matched_tipo)
        print(f"    -> {text}: {len(annex_items)} relevant items")
        items.extend(annex_items)

    return items


def scrape_diputados(days: int = 30, max_items: int = 100) -> list:
    print("\n=== Scraping Cámara de Diputados ===")
    all_items: list = []
    seen_ids: set   = set()

    for day in _weekdays_last_n(days):
        if len(all_items) >= max_items:
            break
        time.sleep(0.5)
        day_items = _scrape_day_diputados(day)
        for item in day_items:
            if item["id"] not in seen_ids:
                seen_ids.add(item["id"])
                all_items.append(item)
                if len(all_items) >= max_items:
                    break

    print(f"  Diputados total: {len(all_items)} items")
    return all_items


# ---------------------------------------------------------------------------
# Senado scraper
# ---------------------------------------------------------------------------
SENADO_BASE     = "https://www.senado.gob.mx"
SENADO_GACETA_URL = "https://www.senado.gob.mx/66/gaceta_del_senado"


def _parse_senado_gaceta_page(page_url: str, fecha_str: str) -> list:
    """Parse a single Senado gaceta page for env-relevant items."""
    soup = soup_from_url(page_url)
    if soup is None:
        return []

    items = []
    seen = set()

    for a in soup.find_all("a", href=True):
        title = a.get_text(separator=" ", strip=True)
        href  = a["href"].strip()

        if len(title) < 20:
            continue
        if not is_relevant(title):
            continue

        # Build absolute URL
        if href.startswith("http"):
            full_url = href
        elif href.startswith("/"):
            full_url = SENADO_BASE + href
        else:
            base_path = page_url.rsplit("/", 1)[0]
            full_url  = base_path + "/" + href

        if full_url in seen:
            continue
        seen.add(full_url)

        autor   = _extract_autor(title)
        partido = _extract_partido(title)

        items.append({
            "titulo":    title[:400],
            "tipo":      detect_tipo(title),
            "fecha":     fecha_str,
            "autor":     autor,
            "partido":   partido,
            "categoria": detect_cat(title),
            "url":       full_url,
            "id":        make_id(full_url or title),
        })

    return items


def _extract_senado_fecha(text: str, href: str) -> str:
    """Try to parse a date from a gaceta link's label or URL."""
    # Look for patterns like "14 de abril de 2026", "abril 14, 2026", or "20260414"
    months_es = {
        "enero": 1, "febrero": 2, "marzo": 3, "abril": 4,
        "mayo": 5, "junio": 6, "julio": 7, "agosto": 8,
        "septiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12,
    }
    # Pattern: "14 de abril de 2026"
    m = re.search(
        r"(\d{1,2})\s+de\s+(enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|noviembre|diciembre)\s+de\s+(\d{4})",
        text, re.I
    )
    if m:
        day   = int(m.group(1))
        month = months_es[m.group(2).lower()]
        year  = int(m.group(3))
        try:
            return date(year, month, day).strftime("%Y-%m-%d")
        except ValueError:
            pass

    # Pattern in URL: YYYYMMDD
    m2 = re.search(r"(\d{4})(\d{2})(\d{2})", href)
    if m2:
        try:
            return date(int(m2.group(1)), int(m2.group(2)), int(m2.group(3))).strftime("%Y-%m-%d")
        except ValueError:
            pass

    # Fall back to today
    return date.today().strftime("%Y-%m-%d")


def scrape_senado(max_items: int = 100) -> list:
    print("\n=== Scraping Senado de la República ===")
    all_items: list = []
    seen_ids: set   = set()

    # Fetch the main listing page
    soup = soup_from_url(SENADO_GACETA_URL)
    if soup is None:
        print("  Could not fetch Senado gaceta listing page.")
        return []

    cutoff = date.today() - timedelta(days=60)

    # Collect links to individual gaceta pages
    gaceta_links = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        text = a.get_text(separator=" ", strip=True)

        # Filter for links that look like gaceta entries
        if not href:
            continue

        is_gaceta = (
            "gaceta" in href.lower()
            or "gaceta" in text.lower()
            or re.search(r"\d{8}", href)  # date-stamped URLs
            or re.search(r"\d{4}/\d{2}/", href)  # year/month paths
        )
        if not is_gaceta:
            continue

        # Build absolute URL
        if href.startswith("http"):
            full_url = href
        elif href.startswith("/"):
            full_url = SENADO_BASE + href
        else:
            full_url = SENADO_GACETA_URL.rsplit("/", 1)[0] + "/" + href

        fecha_str = _extract_senado_fecha(text, href)

        # Filter to last 60 days
        try:
            entry_date = date.fromisoformat(fecha_str)
            if entry_date < cutoff:
                continue
        except ValueError:
            pass

        gaceta_links.append((full_url, fecha_str, text))

    # Deduplicate links
    seen_links: set = set()
    unique_links    = []
    for url, fecha, text in gaceta_links:
        if url not in seen_links:
            seen_links.add(url)
            unique_links.append((url, fecha, text))

    print(f"  Found {len(unique_links)} gaceta links on listing page")

    for gaceta_url, fecha_str, label in unique_links:
        if len(all_items) >= max_items:
            break
        print(f"  [Senado] {fecha_str} -> {gaceta_url}")
        time.sleep(0.5)
        page_items = _parse_senado_gaceta_page(gaceta_url, fecha_str)
        print(f"    -> {len(page_items)} relevant items")
        for item in page_items:
            if item["id"] not in seen_ids:
                seen_ids.add(item["id"])
                all_items.append(item)
                if len(all_items) >= max_items:
                    break

    print(f"  Senado total: {len(all_items)} items")
    return all_items


# ---------------------------------------------------------------------------
# Merge & persist
# ---------------------------------------------------------------------------

def load_existing() -> dict:
    if not os.path.exists(OUTPUT_FILE):
        return {"diputados": [], "senado": [], "_meta": {}}
    try:
        with open(OUTPUT_FILE, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception as exc:
        print(f"  [WARN] Could not load existing JSON: {exc}")
        return {"diputados": [], "senado": [], "_meta": {}}


def merge_and_save(new_diputados: list, new_senado: list) -> None:
    existing = load_existing()

    cutoff = (date.today() - timedelta(days=60)).strftime("%Y-%m-%d")

    def merge_chamber(new_items: list, old_items: list) -> list:
        seen_ids: set = set()
        merged: list  = []

        # New items first (prepend)
        for item in new_items:
            iid = item.get("id") or make_id(item.get("url", "") + item.get("titulo", ""))
            if iid not in seen_ids:
                seen_ids.add(iid)
                merged.append(item)

        # Then existing items
        for item in old_items:
            # Skip items older than 60 days
            fecha = item.get("fecha", "")
            if fecha and fecha < cutoff:
                continue
            iid = item.get("id") or make_id(item.get("url", "") + item.get("titulo", ""))
            if iid not in seen_ids:
                seen_ids.add(iid)
                merged.append(item)

        return merged

    merged_diputados = merge_chamber(new_diputados, existing.get("diputados", []))
    merged_senado    = merge_chamber(new_senado,    existing.get("senado",    []))

    now = datetime.utcnow()
    output = {
        "diputados": merged_diputados,
        "senado":    merged_senado,
        "_meta": {
            "ultima_actualizacion": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "mes": now.strftime("%Y-%m"),
        },
    }

    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as fh:
        json.dump(output, fh, ensure_ascii=False, indent=2)

    print(
        f"\n[SAVED] {OUTPUT_FILE}\n"
        f"  diputados: {len(merged_diputados)} items\n"
        f"  senado:    {len(merged_senado)} items"
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    print(f"[START] scraper_gacetas.py — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    new_diputados = scrape_diputados(days=30, max_items=100)
    new_senado    = scrape_senado(max_items=100)

    merge_and_save(new_diputados, new_senado)

    print("\n[DONE]")


if __name__ == "__main__":
    main()
