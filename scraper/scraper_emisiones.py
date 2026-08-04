#!/usr/bin/env python3
"""
SCOPE — Inventario Nacional de Emisiones de GEI (INEGYCEI · INECC, datos.gob.mx).

Ingesta REAL: baja los CSV anuales del inventario nacional (uno por año), extrae la
emisión nacional total (tCO2e, brutas y netas) para la serie de tiempo, y el desglose
por sector IPCC del último año. Nacional/sectorial (no por estado).

Output: data/emisiones-gei.json
"""
import sys, json, csv, io, re
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import warnings; warnings.filterwarnings("ignore")
import requests
requests.packages.urllib3.disable_warnings()

ROOT = Path(__file__).resolve().parent.parent
OUT  = ROOT / "data" / "emisiones-gei.json"
UA   = {"User-Agent": "Mozilla/5.0 (compatible; SCOPE-GEMI/1.0)"}
PKG  = "inventario_nacional_emisiones_gases_compuestos_efecto_invernadero_inegycei"

# Ojo: el CSV trae DOS filas "EMISIONES NETAS": la real con absorciones forestales
# ("(Emisiones + Absorciones)" = netas) y una "(t de CO2e)" que en realidad es el
# bruto sin UTCUTS. Usamos el bruto SIN UTCUTS como headline (= suma de sectores).
ROW_SINU  = "emisiones sin utcuts"                  # bruto sin UTCUTS (headline)
ROW_NETAS = "emisiones netas (emisiones"            # netas reales (con absorciones)
ROW_BRUTAS = "emisiones brutas"                     # brutas con UTCUTS (respaldo)

def cdmx_now():
    return datetime.now(timezone(timedelta(hours=-6)))

def _num(s):
    try:
        return float(str(s).strip())
    except Exception:
        return None

def year_of(url):
    m = re.search(r"(\d{4})", url.split("/")[-1])
    return int(m.group(1)) if m else None

def fetch_csv(url):
    raw = requests.get(url, headers=UA, timeout=90, verify=False).content
    return list(csv.DictReader(io.StringIO(raw.decode("utf-8", "replace"))))

def main():
    print("SCOPE — INEGYCEI (emisiones GEI) —", cdmx_now().strftime("%Y-%m-%d %H:%M CDMX"))
    try:
        r = requests.get("https://www.datos.gob.mx/api/3/action/package_show",
                         params={"id": PKG}, headers=UA, timeout=40, verify=False)
        res = (r.json().get("result") or {}).get("resources") or []
    except Exception as e:
        print("ERROR package_show:", str(e)[:120]); return

    years = {}
    for x in res:
        u = x.get("url") or ""
        y = year_of(u)
        if y and u.lower().endswith(".csv"):
            years[y] = u
    if not years:
        print("Sin recursos anuales; se conserva el archivo previo."); return
    print(f"  años disponibles: {min(years)}–{max(years)} ({len(years)})")

    serie = []
    ultimo = max(years)
    sec_series = {}   # nombre de sector -> {anio: tco2e}
    sec_order = []
    for y in sorted(years):
        try:
            rows = fetch_csv(years[y])
        except Exception as e:
            print(f"  {y}: ERROR {str(e)[:60]}"); continue
        bruto = netas = brutas_utcuts = None
        for row in rows:
            cat = (row.get("categoria_fuente_subfuente_emision") or "").strip()
            catl = cat.lower()
            v = _num(row.get("emisiones_tCO2e"))
            if catl.startswith(ROW_SINU):
                bruto = v
            elif catl.startswith(ROW_NETAS):
                netas = v
            elif catl.startswith(ROW_BRUTAS):
                brutas_utcuts = v
            # Sector IPCC de nivel superior: [1] Energía, [2] Procesos…, [3] Agricultura, etc.
            m = re.match(r"^\[(\d)\]\s*(.+)$", cat)
            if m and v is not None:
                name = m.group(2).strip()
                if name not in sec_series:
                    sec_series[name] = {}; sec_order.append(name)
                sec_series[name][y] = v
        if bruto is None:
            bruto = brutas_utcuts
        serie.append({"anio": y, "bruto_tco2e": bruto, "netas_tco2e": netas})
        print(f"  {y}: bruto {bruto}  netas {netas}")

    ult = next((s for s in serie if s["anio"] == ultimo), {})
    base = ult.get("bruto_tco2e") or 0
    sectores = []
    for name in sec_order:
        yr = sec_series[name]
        val = yr.get(ultimo)
        if val is None:
            continue
        sectores.append({
            "nombre": name,
            "tco2e": val,
            "pct": round(val / base * 100, 1) if base else 0,
            "serie": [{"anio": yy, "tco2e": yr[yy]} for yy in sorted(yr)],
        })
    sectores.sort(key=lambda s: s["tco2e"], reverse=True)

    out = {
        "_meta": {
            "actualizado": cdmx_now().strftime("%Y-%m-%dT%H:%M CDMX"),
            "fuente": "INECC · Inventario Nacional de Emisiones de Gases y Compuestos de Efecto Invernadero (INEGYCEI · datos.gob.mx)",
            "url": "https://www.datos.gob.mx/dataset/" + PKG,
            "unidad": "toneladas de CO2 equivalente (tCO2e)",
        },
        "ultimo_anio": ultimo,
        "total_bruto": ult.get("bruto_tco2e"),
        "total_netas": ult.get("netas_tco2e"),
        "serie": serie,
        "sectores": sectores,
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"Guardado {OUT.name}  |  {len(serie)} años · {len(sectores)} sectores")

if __name__ == "__main__":
    main()
