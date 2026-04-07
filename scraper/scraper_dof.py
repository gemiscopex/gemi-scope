#!/usr/bin/env python3
"""
SCOPE — Scraper del Diario Oficial de la Federación
Fuente: dof.gob.mx (edicion matutina, vespertina)
Output: data/dof.json  (acumulativo, ultimas MAX_SEMANAS semanas)
Corre: 8:00 AM y 2:30 PM hora Ciudad de Mexico (lunes-viernes)
"""

import json
import re
import hashlib
import time
import warnings
import unicodedata
from datetime import datetime, timezone, date, timedelta
from pathlib import Path

import requests
from bs4 import BeautifulSoup

warnings.filterwarnings("ignore")  # suprimir advertencias SSL

OUTPUT_FILE = Path(__file__).parent.parent / "data" / "dof.json"
MAX_SEMANAS = 16   # conservar ~4 meses de historial
SLEEP      = 0.8  # segundos entre requests

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 SCOPE-Monitor/1.0",
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "es-MX,es;q=0.9",
}

# ── Dependencias CORE: siempre relevantes para SCOPE ─────────────────────────
CORE_DEPS = {
    "SEMARNAT":  "agua_medioambiente",
    "PROFEPA":   "agua_medioambiente",
    "CONAGUA":   "agua_medioambiente",
    "CONAFOR":   "agua_medioambiente",
    "INECC":     "cambio_climatico",
    "SENER":     "energia",
    "CNH":       "energia",
    "CRE":       "energia",
    "PEMEX":     "energia",
    "CFE":       "energia",
    "SADER":     "agro_rural",
    "SENASICA":  "agro_rural",
    "CONAPESCA": "agro_rural",
    "SICT":      "transporte_logistica",
    "SCT":       "transporte_logistica",
}

# ── Dependencias condicionales: solo relevantes si el título tiene palabras clave ──
COND_DEPS = {
    "SHCP":   "fiscal_regulatorio",
    "SAT":    "fiscal_regulatorio",
    "SE":     "comercio_inversion",
    "SEDATU": "economia_circular",
    "COFEPRIS": "salud_publica",
}

# Palabras clave que califican una publicación de SHCP/SAT/SE/etc. como relevante
SCOPE_KW = re.compile(
    r"ambiental|ecol|agua|residuo|energ|renovable|forestal|biodiver|"
    r"clim|carbono|emision|contamin|hidric|acuifer|cuenca|"
    r"nom-|norma oficial|proy-nom|economia circular|reciclaj|"
    r"impuesto.*ambiental|tasa.*ecol|bono.*carbono|"
    r"agr|ganad|pesca|siembra|fitosanit|sanidad animal|"
    r"transporte.*peligros|residuo.*peligros|sustanci.*peligros"
)

# Tipo de instrumento basado en el titulo
TIPOS_KEYWORDS = [
    ("NOM",        ["norma oficial mexicana", "nom-", "proy-nom"]),
    ("DECRETO",    ["decreto"]),
    ("ACUERDO",    ["acuerdo"]),
    ("LEY",        ["ley ", "reforma.*ley", "codigo "]),
    ("REGLAMENTO", ["reglamento"]),
    ("CONVENIO",   ["convenio"]),
    ("CIRCULAR",   ["circular"]),
    ("RESOLUCION", ["resoluci\u00f3n", "resolucion"]),
    ("PROGRAMA",   ["programa "]),
    ("AVISO",      ["aviso"]),
    ("EXTRACTO",   ["extracto"]),
]

# Dependencias en texto largo del DOF (nombre completo -> sigla)
DEP_ALIAS = {
    "SECRETAR\u00cdA DE MEDIO AMBIENTE":                     "SEMARNAT",
    "SEMARNAT":                                               "SEMARNAT",
    "PROCURADUR\u00cdA FEDERAL DE PROTECCI\u00d3N AL AMBIENTE": "PROFEPA",
    "COMISI\u00d3N NACIONAL DEL AGUA":                        "CONAGUA",
    "COMISI\u00d3N NACIONAL FORESTAL":                        "CONAFOR",
    "INSTITUTO NACIONAL DE ECOLOG\u00cdA":                    "INECC",
    "SECRETAR\u00cdA DE ENERG\u00cdA":                        "SENER",
    "COMISI\u00d3N NACIONAL DE HIDROCARBUROS":                "CNH",
    "COMISI\u00d3N REGULADORA DE ENERG\u00cdA":               "CRE",
    "PETR\u00d3LEOS MEXICANOS":                               "PEMEX",
    "COMISI\u00d3N FEDERAL DE ELECTRICIDAD":                  "CFE",
    "SECRETAR\u00cdA DE HACIENDA":                            "SHCP",
    "SERVICIO DE ADMINISTRACI\u00d3N TRIBUTARIA":             "SAT",
    "SECRETAR\u00cdA DE ECONOM\u00cdA":                       "SE",
    "COMISI\u00d3N FEDERAL PARA LA PROTECCI\u00d3N":          "COFEPRIS",
    "SECRETAR\u00cdA DE AGRICULTURA":                         "SADER",
    "SERVICIO NACIONAL DE SANIDAD":                          "SENASICA",
    "COMISI\u00d3N NACIONAL DE ACUACULTURA":                  "CONAPESCA",
    "SECRETAR\u00cdA DE INFRAESTRUCTURA":                     "SICT",
    "SECRETAR\u00cdA DE COMUNICACIONES":                      "SCT",
    "SECRETAR\u00cdA DE DESARROLLO AGRARIO":                  "SEDATU",
    "SECRETAR\u00cdA DE GOBERNACI\u00d3N":                    "SEGOB",
    "PODER EJECUTIVO":                                        "EJECUTIVO",
    "PODER LEGISLATIVO":                                      "LEGISLATIVO",
    "PODER JUDICIAL":                                         "JUDICIAL",
    "BANCO DE M\u00c9XICO":                                   "BANXICO",
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def iso_week(d: date) -> str:
    iso = d.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def make_id(codigo: str, fecha: str) -> str:
    return hashlib.md5(f"{codigo}|{fecha}".encode()).hexdigest()[:12]


def detect_tipo(titulo: str) -> str:
    t = titulo.lower()
    for tipo, patterns in TIPOS_KEYWORDS:
        if any(re.search(p, t) for p in patterns):
            return tipo
    return "OTRO"


def _norm(s: str) -> str:
    """Normaliza a mayúsculas sin acentos para comparación robusta."""
    return unicodedata.normalize("NFD", s.upper()).encode("ascii", "ignore").decode()


def resolve_dep(raw: str) -> str:
    """Convierte nombre largo de dependencia a sigla."""
    upper = _norm(raw.strip())
    for alias, sigla in DEP_ALIAS.items():
        if _norm(alias) in upper:
            return sigla
    # Si es texto corto y ya parece sigla
    if len(upper) <= 12 and re.match(r'^[A-Z\s]+$', upper):
        return upper.strip()
    return "OTRO"


def detect_categoria(dep: str, titulo: str) -> tuple[str, bool]:
    """Returns (categoria, es_relevante)."""
    t = titulo.lower()

    # Dependencias core: siempre relevantes
    if dep in CORE_DEPS:
        return CORE_DEPS[dep], True

    # Dependencias condicionales: solo si el título contiene palabras clave SCOPE
    if dep in COND_DEPS:
        if SCOPE_KW.search(t):
            return COND_DEPS[dep], True
        return COND_DEPS[dep], False

    # Dependencias no relevantes para SCOPE (avisos administrativos, financieros, etc.)
    if dep in ("SEGOB", "BANXICO", "EJECUTIVO", "JUDICIAL", "LEGISLATIVO", "OTRO"):
        return "general", False

    # Resto: inferir por palabras clave en el título
    if re.search(r'agua|ambiental|ecol|residuo|forestal|biodiver', t):
        return "agua_medioambiente", True
    if re.search(r'energ|petrole|gas natural|electric|hidrocarburo', t):
        return "energia", True
    if re.search(r'clim|carbono|emision|gei', t):
        return "cambio_climatico", True
    if re.search(r'agr|ganad|pesca|siembra', t):
        return "agro_rural", True

    return "general", False


# ── Scraper principal ─────────────────────────────────────────────────────────

def fetch_dof_dia(target_date: date) -> list[dict]:
    """Scrapea el indice del DOF para una fecha dada. Devuelve lista de notas."""
    y, m, d = target_date.year, target_date.month, target_date.day
    fecha_str = f"{d:02d}/{m:02d}/{y}"
    fecha_iso = target_date.isoformat()
    url = f"https://www.dof.gob.mx/index.php?year={y}&month={m:02d}&day={d:02d}"

    try:
        resp = requests.get(url, headers=HEADERS, timeout=20, verify=False)
        resp.raise_for_status()
        resp.encoding = "utf-8"
    except Exception as e:
        print(f"  ERROR {url}: {e}")
        return []

    soup = BeautifulSoup(resp.text, "html.parser")

    # Verificar que haya edicion ese dia
    if not soup.find("a", href=re.compile(r"nota_detalle")):
        print(f"  Sin publicaciones en DOF para {fecha_iso}")
        return []

    notas = []
    seen_codigos: set[str] = set()
    current_dep = "OTRO"

    # DOF page structure (verified):
    #   <td class="txt_blanco2">  → top-level section (PODER EJECUTIVO, etc.)
    #   <td class="subtitle_azul">→ dependencia header (SECRETARIA DE MEDIO AMBIENTE, etc.)
    #   <td><a href="/nota_detalle.php?...">título</a></td>  → actual publication
    #
    # We iterate all <tr>s in document order, updating current_dep when we hit headers.
    for tr in soup.find_all("tr"):
        # Check for section / dependencia header cells
        for td in tr.find_all("td"):
            css = " ".join(td.get("class") or [])
            if "txt_blanco2" in css or "subtitle_azul" in css:
                raw_text = td.get_text(" ", strip=True)
                candidate = resolve_dep(raw_text)
                if candidate != "OTRO":
                    current_dep = candidate

        # Check for nota_detalle links in this row
        for a in tr.find_all("a", href=True):
            href = a.get("href", "")
            if "nota_detalle" not in href:
                continue
            titulo = a.get_text(" ", strip=True)
            if not titulo or len(titulo) < 8:
                continue

            m_cod = re.search(r"codigo=(\d+)", href)
            if not m_cod:
                continue
            codigo = m_cod.group(1)
            if codigo in seen_codigos:
                continue
            seen_codigos.add(codigo)

            tipo               = detect_tipo(titulo)
            categoria, relevante = detect_categoria(current_dep, titulo)
            nota_id            = make_id(codigo, fecha_iso)
            full_url           = f"https://www.dof.gob.mx/nota_detalle.php?codigo={codigo}&fecha={fecha_str}"

            notas.append({
                "id":           nota_id,
                "fecha":        fecha_iso,
                "semana":       iso_week(target_date),
                "titulo":       titulo,
                "dependencia":  current_dep,
                "tipo":         tipo,
                "codigo":       codigo,
                "url":          full_url,
                "categoria":    categoria,
                "relevante":    relevante,
                "scrapeado_en": datetime.now(timezone.utc).isoformat(),
            })

    print(f"  {fecha_iso}: {len(notas)} notas ({len([n for n in notas if n['relevante']])} relevantes)")
    return notas


def main():
    # Fecha de hoy en CDMX (UTC-6)
    now_cdmx = datetime.now(timezone.utc) - timedelta(hours=6)
    today = now_cdmx.date()

    print(f"DOF Scraper — {today}  semana {iso_week(today)}")

    # Cargar datos existentes
    existing: list[dict] = []
    existing_ids: set[str] = set()
    if OUTPUT_FILE.exists():
        try:
            with open(OUTPUT_FILE, encoding="utf-8") as f:
                existing = json.load(f)
            existing_ids = {a.get("id", "") for a in existing}
            print(f"  {len(existing)} publicaciones en archivo")
        except Exception:
            existing = []

    # Scrape del dia de hoy
    nuevas = [n for n in fetch_dof_dia(today) if n["id"] not in existing_ids]
    print(f"  {len(nuevas)} nuevas publicaciones")

    if not nuevas and existing:
        print("  Sin cambios, saliendo sin sobrescribir")
        return

    # Combinar y conservar solo MAX_SEMANAS semanas
    combined = nuevas + existing
    combined.sort(key=lambda x: x.get("fecha", ""), reverse=True)

    cutoff = (today - timedelta(weeks=MAX_SEMANAS)).isoformat()
    combined = [n for n in combined if n.get("fecha", "9999") >= cutoff]

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(combined, f, ensure_ascii=False, indent=2)

    semanas_unicas = len({n["semana"] for n in combined})
    print(f"  Guardado: {len(combined)} publicaciones en {semanas_unicas} semanas -> {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
