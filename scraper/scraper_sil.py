#!/usr/bin/env python3
"""
SCOPE — Scraper SIL (Sistema de Información Legislativa — Gobernación)
Fuente: https://sil.gobernacion.gob.mx
Output: data/sil.json

Busca iniciativas de la LXVI Legislatura con contenido ambiental,
extrae el detalle de seguimiento y guarda el historial legislativo.
"""

import hashlib
import json
import re
import sys
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

import requests
import urllib3
from bs4 import BeautifulSoup

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ---------------------------------------------------------------------------
OUTPUT_FILE = Path(__file__).parent.parent / "data" / "sil.json"
MAX_TOTAL   = 500          # items máximos en el JSON
PER_TERM    = 40           # links máximos extraídos por término de búsqueda
DELAY_SEARCH = 1.0         # segundos entre búsquedas
DELAY_DETAIL = 1.2         # segundos entre páginas de detalle
LEGISLATURA  = "LXVI"     # solo iniciativas de esta legislatura

BASE_SEARCH = "https://sil.gobernacion.gob.mx/Librerias/Search/search_UTF.php"
BASE_DETAIL = "http://sil.gobernacion.gob.mx/Librerias/pp_ReporteSeguimiento.php"

# ---------------------------------------------------------------------------
# Términos de búsqueda ambiental
# ---------------------------------------------------------------------------
TERMINOS = [
    "cambio climatico",
    "medio ambiente",
    "agua potable",
    "residuos peligrosos",
    "energia renovable",
    "energia solar",
    "energia eolica",
    "biodiversidad",
    "deforestacion",
    "reforestacion",
    "areas naturales protegidas",
    "contaminacion",
    "calidad del aire",
    "mineria",
    "litio",
    "transgenico",
    "glifosato",
    "pemex refineria",
    "emisiones gases",
    "economia circular",
    "reciclaje",
    "manglar",
]

# ---------------------------------------------------------------------------
# Categorías ambientales (para clasificar por título + aspectos)
# ---------------------------------------------------------------------------
KEYWORDS_AMBIENTAL = {
    "agua":             ["agua","cuenca","rio","lago","acuifero","hidric",
                         "conagua","sequia","inundacion","presa",
                         "agua potable","escasez de agua"],
    "energia_renovable":["solar","eolica","fotovoltaic","hidroelectric",
                         "renovable","cfe","sener","geotermia",
                         "energia limpia","transicion energetica"],
    "hidrocarburos":    ["pemex","refineria","ducto","oleoducto","gasoducto",
                         "fracking","hidrocarburos","petroleo","gas natural"],
    "biodiversidad":    ["semarnat","conanp","area natural","reserva",
                         "especie","extincion","jaguar","vida silvestre",
                         "corredor biologico","parque nacional"],
    "deforestacion":    ["bosque","selva","tala","deforest","incendio forestal",
                         "conafor","manglar","reforest","cambio de uso de suelo"],
    "calidad_aire":     ["contingencia","ozono","pm2.5","pm10","emision",
                         "calidad del aire","contaminacion atmosferica","smog"],
    "residuos":         ["basura","residuo","relleno sanitario","reciclaj",
                         "plastico","incinerador","economia circular",
                         "desecho peligroso","residuo toxico"],
    "cambio_climatico": ["cambio climatico","calentamiento global",
                         "carbono","gei","co2","inecc","mitigacion",
                         "lgcc","cop","paris","descarbonizacion",
                         "gases de efecto invernadero"],
    "mineria":          ["mineria","cianuro","tajo","concesion minera",
                         "litio","camimex"],
    "transgenico":      ["transgenico","glifosato","bayer","monsanto",
                         "semilla","soberania alimentaria","maiz nativo",
                         "plaguicida"],
}

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

# Labels exactos del detalle de seguimiento → clave en el dict resultado
DETAIL_LABELS = {
    "Camara Origen":        "camara_origen",
    "Camara Revisora":      "camara_revisora",
    "Fecha de Presentacion":"fecha_presentacion",
    "Legislatura":          "legislatura",
    "Periodo de sesiones":  "periodo",
    "Iniciativa":           "titulo",
    "Presentador":          "presentador",
    "Aspectos Relevantes":  "aspectos",
    "Ultimo Tramite":       "ultimo_tramite",
    "Ultimo Estatus":       "ultimo_estatus",
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def normalize(text: str) -> str:
    t = text.lower().strip()
    t = unicodedata.normalize("NFD", t)
    return "".join(c for c in t if unicodedata.category(c) != "Mn")

def _kw_match(kw_norm: str, text_norm: str) -> bool:
    if len(kw_norm) <= 6:
        return bool(re.search(r"\b" + re.escape(kw_norm) + r"\b", text_norm))
    return kw_norm in text_norm

def detect_categories(titulo: str, aspectos: str = "") -> list:
    t = normalize(f"{titulo} {aspectos}")
    return [cat for cat, kws in KEYWORDS_AMBIENTAL.items()
            if any(_kw_match(normalize(kw), t) for kw in kws)]

def make_id(asunto_id: str) -> str:
    return hashlib.md5(f"sil:{asunto_id}".encode()).hexdigest()[:12]

def parse_fecha(s: str) -> str:
    """Convierte DD/MM/YYYY → YYYY-MM-DD"""
    s = s.strip()
    m = re.match(r"(\d{2})/(\d{2})/(\d{4})", s)
    if m:
        return f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
    return s

SESSION = requests.Session()
SESSION.verify = False
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
})

# ---------------------------------------------------------------------------
# Búsqueda
# ---------------------------------------------------------------------------
def search_term(term: str, limit: int = PER_TERM) -> list:
    """
    Busca `term` en SIL. Devuelve lista de dicts
    [{"seg": str, "asu": str, "titulo_raw": str}]
    """
    try:
        r = SESSION.get(BASE_SEARCH, params={"Valor": term}, timeout=20)
        r.encoding = "latin-1"
    except Exception as e:
        print(f"  [ERR search '{term}']: {e}")
        return []

    if r.status_code != 200:
        print(f"  [HTTP {r.status_code} search '{term}']")
        return []

    soup = BeautifulSoup(r.text, "lxml")
    results = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        m = re.search(r"Seguimiento=(\d+)&Asunto=(\d+)", href)
        if not m:
            continue
        results.append({
            "seg":        m.group(1),
            "asu":        m.group(2),
            "titulo_raw": a.get_text(" ", strip=True)[:200],
        })
        if len(results) >= limit:
            break

    return results

# ---------------------------------------------------------------------------
# Detalle
# ---------------------------------------------------------------------------
def fetch_detail(seg: str, asu: str) -> dict | None:
    """
    Obtiene el reporte de seguimiento de un asunto.
    Devuelve dict con campos normalizados o None si falla.
    """
    try:
        r = SESSION.get(BASE_DETAIL, params={"Seguimiento": seg, "Asunto": asu}, timeout=20)
        r.encoding = "latin-1"
    except Exception as e:
        print(f"    [ERR detail Asu={asu}]: {e}")
        return None

    if r.status_code != 200:
        return None

    soup = BeautifulSoup(r.text, "lxml")
    all_tds = soup.find_all("td")

    # Label-based extraction
    detail = {}
    for i, td in enumerate(all_tds):
        txt_norm = normalize(td.get_text(" ", strip=True))
        for label, key in DETAIL_LABELS.items():
            if normalize(label) == txt_norm and i + 1 < len(all_tds):
                val = all_tds[i + 1].get_text(" ", strip=True)
                detail[key] = val
                break

    # Filtro: solo LXVI legislatura
    if detail.get("legislatura", "").strip() != LEGISLATURA:
        return None

    # Normalizar fecha
    if "fecha_presentacion" in detail:
        detail["fecha_presentacion"] = parse_fecha(detail["fecha_presentacion"])

    # Categorías (título + aspectos)
    titulo  = detail.get("titulo", "")
    aspectos = detail.get("aspectos", "")
    cats = detect_categories(titulo, aspectos)

    detail["asunto_id"]   = asu
    detail["seguimiento"] = seg
    detail["url"]         = f"{BASE_DETAIL}?Seguimiento={seg}&Asunto={asu}"
    detail["categorias"]  = cats
    detail["categoria"]   = cats[0] if cats else "medio_ambiente"
    detail["categoria_nombre"] = CAT_LABEL.get(cats[0], "Medio Ambiente") if cats else "Medio Ambiente"
    detail["id"]          = make_id(asu)

    return detail

# ---------------------------------------------------------------------------
# Carga / guardado
# ---------------------------------------------------------------------------
def load_existing() -> list:
    if not OUTPUT_FILE.exists():
        return []
    try:
        data = json.loads(OUTPUT_FILE.read_text(encoding="utf-8"))
        return data.get("iniciativas", [])
    except Exception:
        return []

def save(iniciativas: list, nuevas: int):
    payload = {
        "iniciativas": iniciativas,
        "_meta": {
            "fuente":      "SIL — Sistema de Información Legislativa (Gobernación)",
            "legislatura": LEGISLATURA,
            "total":       len(iniciativas),
            "nuevas":      nuevas,
            "actualizado": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        },
    }
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nGuardado: {OUTPUT_FILE}")
    print(f"Total: {len(iniciativas)}  |  Nuevas: {nuevas}")

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    print(f"SCOPE SIL — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"Legislatura: {LEGISLATURA}  |  Términos: {len(TERMINOS)}")

    existing     = load_existing()
    existing_ids = {a["id"] for a in existing}
    asu_seen     = {a["asunto_id"] for a in existing}
    print(f"Iniciativas existentes: {len(existing)}")

    # Paso 1: recolectar candidatos únicos (Seguimiento, Asunto)
    candidates: dict[str, dict] = {}  # asu_id → {seg, asu, titulo_raw}
    for term in TERMINOS:
        results = search_term(term, limit=PER_TERM)
        nuevos_term = 0
        for res in results:
            asu = res["asu"]
            if asu not in asu_seen and asu not in candidates:
                candidates[asu] = res
                nuevos_term += 1
        print(f"  {term:35} {len(results):3} resultados  "
              f"→ {nuevos_term} candidatos nuevos")
        time.sleep(DELAY_SEARCH)

    print(f"\nCandidatos únicos a detallar: {len(candidates)}")

    # Paso 2: obtener detalle de cada candidato
    nuevas = []
    skip_no_lxvi = 0
    skip_no_env  = 0
    errores      = 0

    for i, (asu, cand) in enumerate(candidates.items(), 1):
        print(f"  [{i:>3}/{len(candidates)}] Asu={asu}", end=" ", flush=True)
        detail = fetch_detail(cand["seg"], asu)
        time.sleep(DELAY_DETAIL)

        if detail is None:
            # Puede ser legislatura diferente o error de red
            skip_no_lxvi += 1
            print("-- no LXVI / error")
            continue

        if not detail["categorias"]:
            skip_no_env += 1
            print("-- sin cat ambiental")
            continue

        detail["scrapeado_en"] = datetime.now(timezone.utc).isoformat()
        nuevas.append(detail)
        print(f"OK  {detail['categoria_nombre']:20} {detail.get('fecha_presentacion','?')}")

    print(f"\nResultados:")
    print(f"  Nuevas con contenido ambiental : {len(nuevas)}")
    print(f"  Fuera de LXVI / error          : {skip_no_lxvi}")
    print(f"  Sin categoría ambiental        : {skip_no_env}")

    # Paso 3: merge y ordenar
    combined = nuevas + existing
    combined.sort(
        key=lambda x: x.get("fecha_presentacion", ""), reverse=True
    )
    combined = combined[:MAX_TOTAL]

    save(combined, len(nuevas))


if __name__ == "__main__":
    main()
