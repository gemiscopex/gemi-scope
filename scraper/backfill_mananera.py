"""
backfill_mananera.py
====================
Backfill completo de estenográficas de mañaneras desde el 1 oct 2024
(inicio del mandato de Claudia Sheinbaum).

Itera día a día, omite fines de semana, construye URL predecible y
extrae únicamente las intervenciones ambientales de la Presidenta.

Uso:
    python scraper/backfill_mananera.py
    python scraper/backfill_mananera.py --desde 2025-01-01 --hasta 2025-06-30
    python scraper/backfill_mananera.py --delay 2.0

Fuente: https://www.gob.mx/presidencia/es/articulos/
"""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import unicodedata
from datetime import datetime, date, timedelta
from collections import defaultdict

import requests
import urllib3
from bs4 import BeautifulSoup

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ---------------------------------------------------------------------------
BASE_DIR    = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_FILE = os.path.join(BASE_DIR, "data", "presidencia.json")

SHEINBAUM_START = date(2024, 10, 1)

# ---------------------------------------------------------------------------
URL_BASE = "https://www.gob.mx/presidencia/es/articulos/"
MESES    = ["enero","febrero","marzo","abril","mayo","junio",
            "julio","agosto","septiembre","octubre","noviembre","diciembre"]

def build_url(d: date) -> str:
    return (
        f"{URL_BASE}version-estenografica-conferencia-de-prensa-"
        f"de-la-presidenta-claudia-sheinbaum-pardo-del-"
        f"{d.day}-de-{MESES[d.month-1]}-de-{d.year}"
    )

# ---------------------------------------------------------------------------
RE_CSP_LABEL = re.compile(
    r"PRESIDENTA(?:\s+DE\s+(?:LA\s+REP[ÚU]BLICA|M[ÉE]XICO))?"
    r"[,:]?\s*(?:CLAUDIA\s+SHEINBAUM\s+PARDO)?[:\s]",
    re.IGNORECASE,
)
RE_OTHER_SPEAKER = re.compile(
    r"^(?:SECRETARI[OA]|MINISTR[OA]|PRESIDENTE|DIPUTAD[OA]|"
    r"SENADOR[A]?|GOBERNADOR[A]?|FISCAL|PROCURADOR[A]?|"
    r"ALMIRANTE|GENERAL|COMANDANTE|DIRECTOR[A]?|PERIODISTA|"
    r"PREGUNTA|INTERLOCUTOR)\b",
    re.IGNORECASE | re.MULTILINE,
)

# ---------------------------------------------------------------------------
KEYWORDS_AMBIENTAL = {
    "agua":             ["agua","cuenca","río","rio","lago","acuífero","acuifero",
                         "hídric","hidric","conagua","sequía","sequia","inundación","inundacion",
                         "presa","tratamiento de aguas","agua potable","escasez de agua"],
    "energia_renovable":["solar","eólica","eolica","fotovoltaic","hidroelectric",
                         "renovable","cfe","sener","geotermia","parque eólico","parque eolico"],
    "hidrocarburos":    ["pemex","refinería","refineria","ducto","oleoducto","gasoducto",
                         "fracking","exploración","sondeo","hidrocarburos","petróleo","petroleo"],
    "biodiversidad":    ["semarnat","conanp","área natural","area natural","reserva",
                         "especie","extinción","extincion","jaguar","ballena","manatí","manati",
                         "vida silvestre","corredor biológico","corredor biologico"],
    "deforestacion":    ["bosque","selva","tala","deforesta","incendio forestal",
                         "conafor","manglar","reforest"],
    "calidad_aire":     ["contingencia","ozono","pm2.5","pm10","emisiones",
                         "calidad del aire","contaminación atmosférica","contaminacion atmosferica"],
    "residuos":         ["basura","residuo","relleno sanitario","reciclaj",
                         "plástico","plastico","incinerador","economía circular","economia circular"],
    "cambio_climatico": ["cambio climático","cambio climatico","carbono","gei","co2",
                         "calentamiento","inecc","mitigación","mitigacion","lgcc","cop","paris"],
    "mineria":          ["minería","mineria","cianuro","tajo","concesión minera",
                         "concesion minera","litio"],
    "transgenico":      ["transgénico","transgenico","glifosato","bayer","monsanto",
                         "semilla","cofepris","maíz","maiz"],
}
ALL_KW = [kw for kws in KEYWORDS_AMBIENTAL.values() for kw in kws]

EXCLUIR_FRAGS = [
    "secretario de seguridad","secretaria de seguridad",
    "guardia nacional","crimen organizado","ministerio publico",
    "fiscal general","ley de seguridad nacional",
    "colaboracion en seguridad","agencia de inteligencia",
    "agencias de estados unidos","fuerza armada","fuerzas armadas",
    "operativo policial","narcotrafico","cartel","homicidio",
    "feminicidio","desaparicion forzada","extorsion",
    "delincuencia organizada",
]

# ---------------------------------------------------------------------------
def normalize(text: str) -> str:
    t = text.lower()
    t = unicodedata.normalize("NFD", t)
    return "".join(c for c in t if unicodedata.category(c) != "Mn")

def _kw_match(kw_norm: str, text_norm: str) -> bool:
    if len(kw_norm) <= 6:
        return bool(re.search(r"\b" + re.escape(kw_norm) + r"\b", text_norm))
    return kw_norm in text_norm

def is_relevant(text: str) -> bool:
    t = normalize(text)
    return any(_kw_match(normalize(kw), t) for kw in ALL_KW)

def _env_hit_count(text_norm: str) -> int:
    return sum(1 for kw in ALL_KW if _kw_match(normalize(kw), text_norm))

def is_env_fragment(line: str) -> bool:
    t = normalize(line)
    hits = _env_hit_count(t)
    if hits == 0:
        return False
    has_security = any(normalize(d) in t for d in EXCLUIR_FRAGS)
    if has_security and hits < 3:
        return False
    return True

def classify(text: str) -> list:
    t = normalize(text)
    return [cat for cat, kws in KEYWORDS_AMBIENTAL.items()
            if any(_kw_match(normalize(kw), t) for kw in kws)]

def make_id(url: str) -> str:
    return hashlib.md5(url.encode()).hexdigest()[:10]

# ---------------------------------------------------------------------------
def fetch_html(url: str, retries: int = 2) -> str | None:
    sess = requests.Session()
    for _ in range(retries):
        try:
            r = sess.get(url, timeout=30)
            if r.status_code == 404:
                return None
            if r.status_code == 200 and "Challenge" not in r.text[:300]:
                r.encoding = "utf-8"
                return r.text
        except Exception:
            pass
        time.sleep(2.0)
    # Curl fallback (sometimes passes when requests fails)
    try:
        out = subprocess.run(
            ["curl", "-sL", "--max-time", "30", url],
            capture_output=True, text=True, timeout=35, encoding="utf-8",
        )
        if out.returncode == 0 and out.stdout and "Challenge" not in out.stdout[:300]:
            return out.stdout
    except Exception:
        pass
    return None

def extraer_intervenciones_csp(html: str) -> list:
    """Extract Sheinbaum's own speaking turns as a list of text blocks."""
    soup = BeautifulSoup(html, "html.parser")
    body = soup.find("div", class_="article-body") or soup
    parrafos = [p.get_text("\n", strip=True) for p in body.find_all(["p", "div"])]
    intervenciones = []
    capturando = False
    actual = []
    for parr in parrafos:
        if RE_CSP_LABEL.search(parr):
            capturando = True
            actual = [parr]
        elif capturando and RE_OTHER_SPEAKER.match(parr.strip()):
            if actual:
                intervenciones.append("\n".join(actual))
            capturando = False
            actual = []
        elif capturando:
            actual.append(parr)
    if actual:
        intervenciones.append("\n".join(actual))
    return intervenciones

def extract_env_fragments(html: str, max_frags: int = 6) -> list:
    """De las palabras de la Presidenta, devuelve párrafos con contenido ambiental genuino."""
    intervenciones = extraer_intervenciones_csp(html)
    if not intervenciones:
        return []   # sin turnos identificados, no incluir fragmentos

    fragments = []
    for bloque in intervenciones:
        for line in bloque.split("\n"):
            line = line.strip()
            if len(line) < 80:
                continue
            if is_env_fragment(line):
                fragments.append(line[:500])
            if len(fragments) >= max_frags:
                return fragments
    return fragments

def scrape_date(d: date) -> dict | None:
    url  = build_url(d)
    html = fetch_html(url)
    if html is None:
        return None

    soup = BeautifulSoup(html, "html.parser")
    title_tag = soup.find("h1") or soup.find("title")
    titulo = title_tag.get_text(strip=True) if title_tag else f"Mañanera {d.isoformat()}"

    fragmentos = extract_env_fragments(html)
    if not fragmentos:
        return None   # sin contenido ambiental en palabras de la Presidenta

    categorias = classify(" ".join(fragmentos))

    return {
        "id":         make_id(url),
        "titulo":     titulo,
        "fecha":      d.isoformat(),
        "url":        url,
        "fuente":     "Presidencia de México — Estenográfica",
        "categorias": categorias,
        "fragmentos": fragmentos,
    }

# ---------------------------------------------------------------------------
def load_existing() -> list:
    if not os.path.exists(OUTPUT_FILE):
        return []
    try:
        with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
            return json.load(f).get("articulos", [])
    except Exception:
        return []

def save(articulos: list, nuevos: int):
    output = {
        "articulos": articulos,
        "_meta": {
            "fuente":      "Presidencia de México — Estenográficas mañanera",
            "total":       len(articulos),
            "nuevos":      nuevos,
            "actualizado": datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ") if hasattr(datetime, "UTC") else datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        },
    }
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\nGuardado: {OUTPUT_FILE}")
    print(f"Total: {len(articulos)}  |  Nuevos: {nuevos}")

# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Backfill mañaneras desde gob.mx — extrae menciones ambientales de Sheinbaum"
    )
    parser.add_argument(
        "--desde", default=SHEINBAUM_START.isoformat(),
        help=f"Fecha inicio YYYY-MM-DD (default: {SHEINBAUM_START})",
    )
    parser.add_argument(
        "--hasta", default=date.today().isoformat(),
        help="Fecha fin YYYY-MM-DD (default: hoy)",
    )
    parser.add_argument(
        "--delay", type=float, default=1.5,
        help="Segundos entre requests (default: 1.5)",
    )
    parser.add_argument(
        "--reset", action="store_true",
        help="Borrar articulos existentes de tipo estenografica antes de backfill",
    )
    args = parser.parse_args()

    desde = date.fromisoformat(args.desde)
    hasta = date.fromisoformat(args.hasta)

    print("=" * 60)
    print("  BACKFILL MAÑANERAS — Estenográficas gob.mx")
    print(f"  Rango: {desde} → {hasta}")
    print(f"  Delay: {args.delay}s entre requests")
    print("=" * 60)

    existing = load_existing()

    if args.reset:
        # Keep only non-estenografica articles (e.g. Google News fallback)
        before = len(existing)
        existing = [a for a in existing
                    if "Estenográfica" not in a.get("fuente", "")]
        print(f"Reset: eliminados {before - len(existing)} artículos previos de estenográfica")

    existing_ids = {a["id"] for a in existing}
    print(f"Artículos existentes: {len(existing)}")

    # Generate weekdays in range
    all_dates = []
    d = desde
    while d <= hasta:
        if d.weekday() < 5:   # Mon–Fri
            all_dates.append(d)
        d += timedelta(days=1)

    total = len(all_dates)
    print(f"Días hábiles a intentar: {total}\n")

    added      = 0
    not_found  = 0
    no_env     = 0
    by_month   = defaultdict(int)

    for i, d in enumerate(all_dates, 1):
        url    = build_url(d)
        art_id = make_id(url)

        if art_id in existing_ids:
            print(f"  [{i:>3}/{total}] {d} — ya existe, skip")
            continue

        print(f"  [{i:>3}/{total}] {d}", end=" ", flush=True)
        art = scrape_date(d)

        if art is None:
            html_check = fetch_html(url)
            if html_check is None:
                print("— 404 / no publicada")
            else:
                print("— publicada pero sin contenido ambiental")
                no_env += 1
            not_found += 1
        else:
            print(f"✓ {art['categorias']}  [{len(art['fragmentos'])} frags]")
            existing.append(art)
            existing_ids.add(art["id"])
            added += 1
            by_month[d.strftime("%Y-%m")] += 1

        time.sleep(args.delay)

    existing.sort(key=lambda a: a.get("fecha", ""), reverse=True)

    print(f"\n{'=' * 60}")
    print(f"  Con contenido ambiental : {added}")
    print(f"  Sin mañanera / sin env  : {not_found}")
    print(f"\n  Distribución mensual:")
    for month in sorted(by_month.keys()):
        print(f"    {month}: {by_month[month]} mañaneras con temas ambientales")

    save(existing, added)

if __name__ == "__main__":
    main()
