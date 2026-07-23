#!/usr/bin/env python3
"""
SCOPE — Perfil de estados con datos reales de Data México (Secretaría de Economía).

API: https://www.economia.gob.mx/apidatamexico/tesseract/
  - inegi_population_total  → población por estado (último año disponible)
  - inegi_enoe              → PEA (Workforce con corte Economically Active
                              Population=1) por estado, último trimestre
  - inegi_economic_census   → producción bruta total por sector y estado
                              (Censos Económicos, último año)

Genera/actualiza data/perfil-estados.json conservando la capital de cada estado.
"""
import sys, json
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import warnings
warnings.filterwarnings("ignore")
import requests

ROOT = Path(__file__).resolve().parent.parent
OUT  = ROOT / "data" / "perfil-estados.json"
BASE = "https://www.economia.gob.mx/apidatamexico/tesseract/"
UA   = {"User-Agent": "Mozilla/5.0 (compatible; SCOPE-GEMI/1.0)",
        "Referer": "https://www.economia.gob.mx/datamexico"}

# Nombres Data México → nombres SCOPE
STATE_MAP = {
    "Coahuila de Zaragoza": "Coahuila",
    "Michoacán de Ocampo": "Michoacán",
    "Veracruz de Ignacio de la Llave": "Veracruz",
    "Estado de México": "México",
    "Distrito Federal": "Ciudad de México",
}
SKIP_STATES = {"No Informado"}

# Sector SCIAN → etiqueta corta
SECTOR_SHORT = {
    "11": "Agro y pesca", "21": "Minería", "22": "Energía y agua",
    "23": "Construcción", "31-33": "Manufactura", "43": "Comercio mayoreo",
    "46": "Comercio menudeo", "48-49": "Logística y transporte",
    "51": "Medios", "52": "Finanzas", "53": "Inmobiliario",
    "54": "Serv. profesionales", "55": "Corporativos",
    "56": "Apoyo a negocios y residuos", "61": "Educación", "62": "Salud",
    "71": "Esparcimiento", "72": "Hospitalidad", "81": "Otros servicios",
    "93": "Gobierno",
}

def get(path, **params):
    r = requests.get(BASE + path, params=params, headers=UA, timeout=40, verify=False)
    r.raise_for_status()
    return r.json()

def norm_state(name):
    return STATE_MAP.get(name, name)

def main():
    # Capitales del archivo existente
    try:
        prev = json.loads(OUT.read_text(encoding="utf-8"))
        capitales = {k: v.get("capital") for k, v in (prev.get("estados") or {}).items()}
    except Exception:
        capitales = {}

    out = {}

    # ── Población (último año) ──
    recs = get("data.jsonrecords", cube="inegi_population_total",
               drilldowns="State,Year", measures="Population")["data"]
    last_year = max(r["Year"] for r in recs)
    n = 0
    for r in recs:
        if r["Year"] != last_year or r["State"] in SKIP_STATES:
            continue
        s = norm_state(r["State"])
        out.setdefault(s, {})["poblacion"] = int(r["Population"])
        out[s]["poblacion_periodo"] = str(last_year)
        n += 1
    print(f"  Población: {n} estados · año {last_year}")

    # ── PEA (último trimestre, solo población económicamente activa) ──
    recs = get("data.jsonrecords", cube="inegi_enoe",
               drilldowns="State,Quarter", measures="Workforce",
               **{"Economically Active Population": "1"})["data"]
    last_q = max(r["Quarter ID"] for r in recs)
    q_label = next(r["Quarter"] for r in recs if r["Quarter ID"] == last_q)
    total_pea = 0
    n = 0
    for r in recs:
        if r["Quarter ID"] != last_q or r["State"] in SKIP_STATES:
            continue
        s = norm_state(r["State"])
        out.setdefault(s, {})["pea"] = int(r["Workforce"])
        out[s]["pea_periodo"] = q_label
        total_pea += int(r["Workforce"])
        n += 1
    print(f"  PEA: {n} estados · {q_label} · nacional {total_pea:,}")
    if not (45_000_000 < total_pea < 80_000_000):
        print("  ⚠ PEA nacional fuera de rango esperado — revisar corte ENOE")

    # ── Sectores (censo económico; el cubo "additional" trae 2019) ──
    recs = get("data.jsonrecords", cube="inegi_economic_census_additional",
               drilldowns="State,Sector,Year", measures="Total Gross Production")["data"]
    last_year_ce = max(r["Year"] for r in recs)
    por_estado = {}
    for r in recs:
        if r["Year"] != last_year_ce or r["State"] in SKIP_STATES:
            continue
        s = norm_state(r["State"])
        sid = str(r["Sector ID"])
        raw = r["Sector"] or sid
        if raw.startswith("Sectores Agrupados") or raw.startswith("Grouped"):
            nombre = "Agrupado (confidencial)"
        else:
            nombre = SECTOR_SHORT.get(sid, raw[:28])
        por_estado.setdefault(s, []).append((nombre, float(r["Total Gross Production"] or 0)))
    for s, rows in por_estado.items():
        total = sum(v for _, v in rows) or 1
        top = sorted(rows, key=lambda x: -x[1])[:8]
        out.setdefault(s, {})["sectores"] = [
            {"n": nombre, "pct": round(v / total * 100, 1)} for nombre, v in top
        ]
        out[s]["sectores_periodo"] = f"Censos Económicos {last_year_ce}"
    print(f"  Sectores: {len(por_estado)} estados · censo {last_year_ce}")

    # ── Merge capitales + salida ──
    for s in out:
        if capitales.get(s):
            out[s]["capital"] = capitales[s]
    missing = [s for s in capitales if s not in out]
    if missing:
        print(f"  ⚠ Estados sin datos nuevos (se conserva lo previo): {missing}")
        for s in missing:
            out[s] = (prev.get("estados") or {}).get(s, {})

    doc = {
        "_meta": {
            "fuente": "Data México (economia.gob.mx/datamexico) · INEGI",
            "poblacion": f"inegi_population_total · {last_year}",
            "pea": f"inegi_enoe · {q_label}",
            "sectores": f"inegi_economic_census · {last_year_ce} · % de producción bruta total",
        },
        "estados": out,
    }
    OUT.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"Guardado {OUT.name} ({len(out)} estados)")

if __name__ == "__main__":
    main()
