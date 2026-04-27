#!/usr/bin/env python3
"""
SCOPE — Scraper Legislación Ambiental Estatal
Fuente: ordenjuridico.gob.mx (Orden Jurídico Nacional — Gobernación)
Output: data/leyes-estatales.json

Para cada entidad federativa extrae las leyes, códigos y reglamentos
con contenido ambiental (medio ambiente, agua, forestal, residuos, clima,
minería, energía, biodiversidad) que están VIGENTES.

Estrategia:
  1. Para cada estado, obtiene la página del Poder Legislativo en ordenjuridico
  2. Filtra por keywords ambientales (título del ordenamiento)
  3. Obtiene la ficha individual de cada coincidencia
  4. Guarda metadata: nombre, tipo, temas, fecha, estatus, url_documento
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
OUTPUT_FILE = Path(__file__).parent.parent / "data" / "leyes-estatales.json"

BASE = "http://www.ordenjuridico.gob.mx"
DELAY_PAGE  = 0.5    # entre páginas de estado
DELAY_FICHA = 0.4    # entre fichas individuales

# ---------------------------------------------------------------------------
# Mapa estado → código numérico de ordenjuridico
# ---------------------------------------------------------------------------
ESTADOS = {
    "Aguascalientes":      {"id": 1,  "liberado": "si"},
    "Baja California":     {"id": 2,  "liberado": "no"},
    "Baja California Sur": {"id": 3,  "liberado": "si"},
    "Campeche":            {"id": 4,  "liberado": "no"},
    "Coahuila":            {"id": 5,  "liberado": "no"},
    "Colima":              {"id": 6,  "liberado": "no"},
    "Chiapas":             {"id": 7,  "liberado": "no"},
    "Chihuahua":           {"id": 8,  "liberado": "si"},
    "Ciudad de Mexico":    {"id": 9,  "liberado": "no"},
    "Durango":             {"id": 10, "liberado": "no"},
    "Guanajuato":          {"id": 11, "liberado": "si"},
    "Guerrero":            {"id": 12, "liberado": "si"},
    "Hidalgo":             {"id": 13, "liberado": "no"},
    "Jalisco":             {"id": 14, "liberado": "no"},
    "Mexico":              {"id": 15, "liberado": "si"},
    "Michoacan":           {"id": 16, "liberado": "si"},
    "Morelos":             {"id": 17, "liberado": "si"},
    "Nayarit":             {"id": 18, "liberado": "no"},
    "Nuevo Leon":          {"id": 19, "liberado": "si"},
    "Oaxaca":              {"id": 20, "liberado": "no"},
    "Puebla":              {"id": 21, "liberado": "no"},
    "Queretaro":           {"id": 22, "liberado": "si"},
    "Quintana Roo":        {"id": 23, "liberado": "no"},
    "San Luis Potosi":     {"id": 24, "liberado": "no"},
    "Sinaloa":             {"id": 25, "liberado": "no"},
    "Sonora":              {"id": 26, "liberado": "si"},
    "Tabasco":             {"id": 27, "liberado": "si"},
    "Tamaulipas":          {"id": 28, "liberado": "si"},
    "Tlaxcala":            {"id": 29, "liberado": "si"},
    "Veracruz":            {"id": 30, "liberado": "no"},
    "Yucatan":             {"id": 31, "liberado": "si"},
    "Zacatecas":           {"id": 32, "liberado": "no"},
}

# ---------------------------------------------------------------------------
# Keywords: solo leyes y códigos principales (no acuerdos administrativos)
# Se exige que el título empiece con "Ley", "Código" o "Reglamento"
# Y contenga al menos un término ambiental
# ---------------------------------------------------------------------------
TIPOS_PRINCIPALES = re.compile(
    r"^(ley|código|codigo|reglamento|norma)\b",
    re.IGNORECASE,
)

KEYWORDS_AMBIENTALES = [
    # Marco general
    "equilibrio ecologico", "proteccion al ambiente", "proteccion ambiental",
    "medio ambiente", "ambiental", "ecologic", "ecologia",
    "ambiente",        # captura "del ambiente", "al ambiente"
    "sustentab",       # sustentable / sustentabilidad
    # Agua
    "agua", "hidric", "acuifero", "cuenca", "conagua", "riego",
    # Forestal / biodiversidad
    "forestal", "bosque", "selva", "vida silvestre", "fauna", "flora",
    "biodiversidad", "areas naturales", "reserva ecol",
    # Residuos / suelos
    "residuo", "basura", "reciclaj", "suelo",
    # Clima / energía
    "cambio climatico", "energia renovable", "renovable",
    "solar", "eolic", "carbon", "emisiones",
    # Minería / hidrocarburos
    "mineria", "minero", "hidrocarburos", "petroleo",
    # Pesca / agro
    "pesca", "acuacultura", "agropecuario sustentable",
]

# Términos que INVALIDAN aunque haya keyword (falsos positivos)
EXCLUIR_TITULO = [
    "derechos de agua",      # concesiones
    "agua potable y saneamiento municipal",
    "seguridad social",
    "pension", "educacion", "salud publica", "violencia",
    "derechos humanos", "genero", "cultura", "deporte",
    "transporte publico", "vivienda", "hacienda", "presupuesto",
    "notarial", "catastro",
]

# Categorías para cada ley (basadas en keywords en el título)
CAT_MAP = {
    "agua":             ["agua", "hidric", "acuifero", "cuenca", "riego", "conagua"],
    "forestal":         ["forestal", "bosque", "selva", "conafor", "reforest"],
    "biodiversidad":    ["fauna", "flora", "vida silvestre", "biodiversidad",
                         "areas naturales", "reserva ecol", "parque", "especie"],
    "residuos":         ["residuo", "basura", "reciclaj", "suelo"],
    "cambio_climatico": ["cambio climatico", "carbon", "emisiones", "clima"],
    "energia_renovable":["energia renovable", "renovable", "solar", "eolic", "fotovoltaic"],
    "mineria":          ["mineria", "minero"],
    "hidrocarburos":    ["hidrocarburos", "petroleo"],
    "pesca":            ["pesca", "acuacultura"],
    "ambiental_general":["equilibrio ecologico", "proteccion.*ambiente",
                         "medio ambiente", "ambiental", "ecologic",
                         "ecologia", "ambiente", "sustentab"],
}

CAT_LABEL = {
    "agua":             "Agua",
    "forestal":         "Forestal",
    "biodiversidad":    "Biodiversidad",
    "residuos":         "Residuos",
    "cambio_climatico": "Cambio Climático",
    "energia_renovable":"Energía Renovable",
    "mineria":          "Minería",
    "hidrocarburos":    "Hidrocarburos",
    "pesca":            "Pesca",
    "ambiental_general":"Ambiental General",
}

# ---------------------------------------------------------------------------
SESSION = requests.Session()
SESSION.verify = False
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept-Language": "es-MX,es;q=0.9",
})


def normalize(text: str) -> str:
    t = text.lower()
    t = unicodedata.normalize("NFD", t)
    return "".join(c for c in t if unicodedata.category(c) != "Mn")


def detect_temas(titulo: str) -> list:
    t = normalize(titulo)
    temas = []
    for cat, kws in CAT_MAP.items():
        for kw in kws:
            if _kw_match_titulo(kw, t):
                temas.append(cat)
                break
    return temas if temas else ["ambiental_general"]


def _kw_match_titulo(kw: str, text_norm: str) -> bool:
    """
    Word-boundary solo para keywords muy cortos (≤5 chars) como 'agua', 'mar'.
    Esto evita que 'agua' matchee 'aguascalientes' sin bloquear plurales
    como 'residuos' (donde 'residuo' es >5 chars → substring OK).
    """
    if len(kw) <= 5:
        return bool(re.search(r"\b" + re.escape(kw) + r"\b", text_norm))
    return kw in text_norm


def is_env_titulo(titulo: str) -> bool:
    """True si el título es un ordenamiento ambiental principal."""
    t = normalize(titulo)
    # Debe comenzar con Ley / Código / Reglamento / Norma
    if not TIPOS_PRINCIPALES.match(titulo.strip()):
        return False
    # Sin términos de exclusión
    if any(normalize(ex) in t for ex in EXCLUIR_TITULO):
        return False
    # Con al menos un keyword ambiental (con word-boundary para los cortos)
    return any(_kw_match_titulo(kw, t) for kw in KEYWORDS_AMBIENTALES)


def detect_tipo(titulo: str) -> str:
    t = titulo.strip().lower()
    if t.startswith("ley"):
        return "Ley"
    if t.startswith("código") or t.startswith("codigo"):
        return "Código"
    if t.startswith("reglamento"):
        return "Reglamento"
    if t.startswith("norma"):
        return "Norma"
    if t.startswith("decreto"):
        return "Decreto"
    return "Ordenamiento"


# ---------------------------------------------------------------------------
# Fetch ordenamientos de un estado (Poder Legislativo, idPoder=2)
# ---------------------------------------------------------------------------
def _fetch_estado_page(edo_id: int, liberado: str) -> str | None:
    """Devuelve HTML de la página de ordenamientos del estado."""
    url = f"{BASE}/despliegaedo.php?edo={edo_id}&idPoder=2&liberado={liberado.capitalize()}"
    try:
        r = SESSION.get(url, timeout=30)
        r.encoding = "iso-8859-1"
        return r.text if r.status_code == 200 else None
    except Exception as e:
        print(f"    [ERR page] {url}: {e}")
        return None


def _extract_archivo_ids(html: str) -> list:
    """
    Extrae pares (titulo, idArchivo) de los links tipo:
    javascript:void(window.open("fichaOrdenamiento.php?idArchivo=XXXXX&ambito=ESTATAL",...))
    """
    soup = BeautifulSoup(html, "html.parser")
    results = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        m = re.search(r"fichaOrdenamiento\.php\?idArchivo=(\d+)", href)
        if not m:
            continue
        titulo = a.get_text(" ", strip=True)
        if not titulo or len(titulo) < 8:
            continue
        archivo_id = m.group(1)
        results.append((titulo, archivo_id))
    return results


# ---------------------------------------------------------------------------
# Fetch ficha individual
# ---------------------------------------------------------------------------
def _fetch_ficha(archivo_id: str) -> dict | None:
    """Obtiene metadata de un ordenamiento desde su ficha."""
    url = f"{BASE}/fichaOrdenamiento.php?idArchivo={archivo_id}&ambito=ESTATAL"
    try:
        r = SESSION.get(url, timeout=20)
        r.encoding = "iso-8859-1"
        if r.status_code != 200:
            return None
    except Exception as e:
        return None

    soup = BeautifulSoup(r.text, "html.parser")
    tds  = [td.get_text(" ", strip=True) for td in soup.find_all("td")
            if td.get_text(strip=True)]

    # Build label → value dict
    meta = {}
    for i in range(len(tds) - 1):
        lab = tds[i].rstrip(":").lower()
        val = tds[i + 1]
        if lab == "fecha de publicación":
            meta["fecha_publicacion"] = val
        elif lab == "estatus":
            meta["estatus"] = val
        elif lab in ("categoría", "categoria"):
            meta["categoria_oj"] = val

    # URL del documento (primer link .pdf o .doc)
    url_doc = ""
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if re.search(r"\.(pdf|doc|docx)$", href, re.I):
            url_doc = href if href.startswith("http") else BASE + "/" + href.lstrip("./")
            break

    meta["url"]      = url_doc
    meta["ficha_id"] = archivo_id
    return meta


# ---------------------------------------------------------------------------
# Proceso completo para un estado
# ---------------------------------------------------------------------------
def scrape_estado(nombre: str, cfg: dict) -> list:
    edo_id   = cfg["id"]
    liberado = cfg["liberado"]

    html = _fetch_estado_page(edo_id, liberado)
    if html is None:
        print(f"  {nombre}: no se pudo obtener la página")
        return []

    # Extraer todos los pares (título, idArchivo)
    pares = _extract_archivo_ids(html)
    # Filtrar por keyword ambiental
    env_pares = [(t, aid) for t, aid in pares if is_env_titulo(t)]

    print(f"  {nombre}: {len(pares)} ordenamientos totales → {len(env_pares)} ambientales")

    leyes = []
    seen_ids = set()

    for titulo, archivo_id in env_pares:
        if archivo_id in seen_ids:
            continue
        seen_ids.add(archivo_id)

        time.sleep(DELAY_FICHA)
        ficha = _fetch_ficha(archivo_id)

        # Solo incluir vigentes
        estatus = (ficha or {}).get("estatus", "Vigente")
        if ficha and "derog" in estatus.lower():
            continue

        temas = detect_temas(titulo)
        tipo  = detect_tipo(titulo)

        ley = {
            "nombre":           titulo,
            "tipo":             tipo,
            "temas":            temas,
            "temas_nombres":    [CAT_LABEL.get(t, t) for t in temas],
            "fecha_publicacion": (ficha or {}).get("fecha_publicacion", ""),
            "estatus":          estatus,
            "url":              (ficha or {}).get("url", ""),
            "ficha_url":        f"{BASE}/fichaOrdenamiento.php?idArchivo={archivo_id}&ambito=ESTATAL",
            "id":               hashlib.md5(f"{nombre}:{archivo_id}".encode()).hexdigest()[:10],
        }
        leyes.append(ley)

    # Ordenar: Leyes primero, luego por nombre
    leyes.sort(key=lambda x: (0 if x["tipo"] == "Ley" else
                               1 if x["tipo"] == "Código" else
                               2 if x["tipo"] == "Reglamento" else 3,
                               x["nombre"]))
    return leyes


# ---------------------------------------------------------------------------
# Carga / guardado
# ---------------------------------------------------------------------------
def load_existing() -> dict:
    if not OUTPUT_FILE.exists():
        return {}
    try:
        data = json.loads(OUTPUT_FILE.read_text(encoding="utf-8"))
        return data.get("estados", {})
    except Exception:
        return {}


def save(estados: dict, nuevos: int):
    # Resumen por estado
    resumen = {
        est: {
            "total":  len(leyes),
            "leyes":  sum(1 for l in leyes if l["tipo"] == "Ley"),
            "codigos":sum(1 for l in leyes if l["tipo"] == "Código"),
            "reglamentos": sum(1 for l in leyes if l["tipo"] == "Reglamento"),
            "temas":  sorted({t for l in leyes for t in l["temas"]}),
        }
        for est, leyes in estados.items()
        if leyes
    }

    payload = {
        "estados": estados,
        "resumen": resumen,
        "_meta": {
            "fuente":     "Orden Jurídico Nacional (ordenjuridico.gob.mx — Gobernación)",
            "total_leyes": sum(len(v) for v in estados.values()),
            "estados_con_datos": sum(1 for v in estados.values() if v),
            "nuevas_esta_ejecucion": nuevos,
            "actualizado": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        },
    }
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\nGuardado: {OUTPUT_FILE}")
    print(f"Total: {payload['_meta']['total_leyes']} ordenamientos "
          f"en {payload['_meta']['estados_con_datos']} estados")
    print(f"Nuevos esta ejecución: {nuevos}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    print(f"SCOPE Leyes Estatales — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"Estados a procesar: {len(ESTADOS)}")
    print()

    existing = load_existing()
    print(f"Datos previos: {sum(len(v) for v in existing.values())} ordenamientos "
          f"en {len(existing)} estados\n")

    estados_out = dict(existing)  # conservar datos previos
    total_nuevos = 0

    for nombre, cfg in ESTADOS.items():
        # Saltar si ya tiene datos (para el run diario — solo re-scrape si fuerzan)
        if nombre in existing and existing[nombre]:
            print(f"  {nombre}: ya tiene {len(existing[nombre])} → skip")
            continue

        time.sleep(DELAY_PAGE)
        leyes = scrape_estado(nombre, cfg)
        estados_out[nombre] = leyes
        total_nuevos += len(leyes)

    save(estados_out, total_nuevos)


if __name__ == "__main__":
    main()
