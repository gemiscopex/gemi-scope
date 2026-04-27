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
# Senado scraper — AJAX calendar (FIAT pattern)
# ---------------------------------------------------------------------------
SENADO_BASE = "https://www.senado.gob.mx"
SENADO_CAL  = "https://www.senado.gob.mx/66/app/gaceta/functions/calendarioMes.php"

SENADO_SESSION = requests.Session()
SENADO_SESSION.verify = False
SENADO_SESSION.headers.update({
    "User-Agent":      "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "es-MX,es;q=0.9",
    "Referer":         "https://www.senado.gob.mx/",
})


def _gacetas_del_mes(anio: int, mes: int) -> list:
    """
    AJAX calendar endpoint → list of (fecha_iso, gaceta_id, gaceta_url).
    Rate: 1 call per month, very fast.
    """
    try:
        r = SENADO_SESSION.get(
            SENADO_CAL,
            params={"action": "ajax", "anio": anio, "mes": mes, "dia": 1},
            timeout=30,
        )
        if r.status_code != 200:
            print(f"  [Senado cal] HTTP {r.status_code} for {anio}-{mes:02d}")
            return []
    except Exception as e:
        print(f"  [Senado cal] ERR {anio}-{mes:02d}: {e}")
        return []

    # Response contains hrefs like: gaceta_del_senado/2026_04_15/12345
    matches = re.findall(
        r"gaceta_del_senado/(\d{4})_(\d{2})_(\d{2})/(\d+)",
        r.text,
    )
    results = []
    seen_ids: set = set()
    for y, m, d, gid in matches:
        if gid in seen_ids:
            continue
        seen_ids.add(gid)
        fecha = f"{y}-{m}-{d}"
        url   = f"{SENADO_BASE}/66/gaceta_del_senado/{y}_{m}_{d}/{gid}"
        results.append((fecha, gid, url))
    return results


def _parse_senado_gaceta(gaceta_url: str, fecha_str: str) -> list:
    """
    Parse one Senado gaceta page.
    Strategy:
      1. Try SUMARIO div with anchor-based sections (FIAT primary).
      2. Fallback: scan all /gaceta_del_senado/documento/{id} links directly.
    Rate: caller must sleep 2.5s between calls (Incapsula WAF).
    """
    try:
        r = SENADO_SESSION.get(gaceta_url, timeout=30)
        if r.status_code != 200:
            print(f"    [HTTP {r.status_code}] {gaceta_url}")
            return []
    except Exception as e:
        print(f"    [ERR] {gaceta_url}: {e}")
        return []

    soup     = BeautifulSoup(r.content, "html.parser")
    items    = []
    seen_ids = set()

    # ── Strategy 1: SUMARIO div with anchor sections ──────────────────────
    sumario = soup.find("div", id="sumario")
    if sumario:
        secciones = []
        for a in sumario.find_all("a", href=re.compile(r"^#\d+")):
            anchor_id = a["href"].lstrip("#")
            tipo_raw  = a.get_text(strip=True).lower()
            secciones.append({"anchor_id": anchor_id, "tipo_raw": tipo_raw})

        html_str = str(soup)
        for i, sec in enumerate(secciones):
            ini = html_str.find(f'name="{sec["anchor_id"]}"')
            fin = (
                html_str.find(f'name="{secciones[i+1]["anchor_id"]}"')
                if i + 1 < len(secciones) else len(html_str)
            )
            if ini < 0:
                continue
            chunk = BeautifulSoup(html_str[ini:fin], "html.parser")
            tipo  = detect_tipo(sec["tipo_raw"])
            for link in chunk.find_all("a", href=re.compile(r"/gaceta_del_senado/documento/\d+")):
                doc_id  = re.search(r"documento/(\d+)", link["href"]).group(1)
                titulo  = link.get_text(" ", strip=True)
                if doc_id in seen_ids or not is_relevant(titulo):
                    continue
                seen_ids.add(doc_id)
                full_url = SENADO_BASE + link["href"]
                items.append({
                    "titulo":    titulo[:400],
                    "tipo":      tipo,
                    "fecha":     fecha_str,
                    "autor":     _extract_autor(titulo),
                    "partido":   _extract_partido(titulo),
                    "categoria": detect_cat(titulo),
                    "url":       full_url,
                    "id":        make_id(full_url),
                })

    # ── Strategy 2 (fallback / supplement): all documento links ───────────
    # Also catches pages without sumario div (most current gacetas)
    for link in soup.find_all("a", href=re.compile(r"/gaceta_del_senado/documento/\d+")):
        doc_id  = re.search(r"documento/(\d+)", link["href"]).group(1)
        titulo  = link.get_text(" ", strip=True)
        if doc_id in seen_ids:
            continue
        if not is_relevant(titulo):
            continue
        seen_ids.add(doc_id)
        full_url = SENADO_BASE + link["href"]
        items.append({
            "titulo":    titulo[:400],
            "tipo":      detect_tipo(titulo),
            "fecha":     fecha_str,
            "autor":     _extract_autor(titulo),
            "partido":   _extract_partido(titulo),
            "categoria": detect_cat(titulo),
            "url":       full_url,
            "id":        make_id(full_url),
        })

    return items


def scrape_senado(months: int = 2, max_items: int = 120) -> list:
    """
    Scrape Senado gacetas for the last `months` months via AJAX calendar.
    Uses 2.5s delay between gaceta pages (Incapsula rate limit).
    """
    print("\n=== Scraping Senado — AJAX calendar ===")
    all_items: list = []
    seen_ids: set   = set()

    # Build list of (year, month) to query
    today = date.today()
    month_targets = []
    for delta in range(months):
        m = today.month - delta
        y = today.year
        while m <= 0:
            m += 12
            y -= 1
        month_targets.append((y, m))

    # Collect all gacetas across months
    all_gacetas = []
    for anio, mes in month_targets:
        gacetas = _gacetas_del_mes(anio, mes)
        print(f"  {anio}-{mes:02d}: {len(gacetas)} gacetas en calendario AJAX")
        all_gacetas.extend(gacetas)
        time.sleep(0.5)

    # Sort newest first, deduplicate
    all_gacetas.sort(key=lambda x: x[0], reverse=True)
    seen_gaceta_ids: set = set()
    unique_gacetas = []
    for fecha, gid, url in all_gacetas:
        if gid not in seen_gaceta_ids:
            seen_gaceta_ids.add(gid)
            unique_gacetas.append((fecha, gid, url))

    print(f"  Total gacetas únicas: {len(unique_gacetas)}")

    for fecha_str, gid, gaceta_url in unique_gacetas:
        if len(all_items) >= max_items:
            break
        print(f"  [Senado] {fecha_str}  gaceta={gid}", end=" ", flush=True)

        page_items = _parse_senado_gaceta(gaceta_url, fecha_str)

        new_for_page = 0
        for item in page_items:
            if item["id"] not in seen_ids:
                seen_ids.add(item["id"])
                all_items.append(item)
                new_for_page += 1
                if len(all_items) >= max_items:
                    break

        print(f"→ {new_for_page} relevantes (total: {len(all_items)})")
        time.sleep(2.5)   # Incapsula rate limit

    print(f"\n  Senado total: {len(all_items)} items")
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
