#!/usr/bin/env python3
"""
SCOPE — Datos abiertos ambientales (datos.gob.mx, CKAN API v3).

Consulta el catálogo oficial de datos abiertos del Gobierno de México y guarda
los datasets más recientes de los temas que monitorea SCOPE en
data/datosgob.json. Se ejecuta dentro del auto_update diario.
"""
import sys, json, time, re
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import warnings
warnings.filterwarnings("ignore")
import requests

ROOT = Path(__file__).resolve().parent.parent
OUT  = ROOT / "data" / "datosgob.json"
API  = "https://datos.gob.mx/api/3/action/package_search"
UA   = {"User-Agent": "Mozilla/5.0 (compatible; SCOPE-GEMI/1.0)"}

TEMAS = {
    "Agua":               "agua calidad OR conagua",
    "Residuos":           "residuos",
    "Emisiones / Aire":   "emisiones contaminantes aire",
    "Medio Ambiente":     "medio ambiente semarnat",
    "Energía":            "energia renovable",
    "Forestal":           "forestal conafor",
}

def cdmx_now():
    return datetime.now(timezone(timedelta(hours=-6)))

def buscar(query, rows=8):
    try:
        r = requests.get(API, params={"q": query, "rows": rows, "sort": "metadata_modified desc"},
                         headers=UA, timeout=25, verify=False)
        if r.status_code != 200:
            return []
        return (r.json().get("result") or {}).get("results") or []
    except Exception as e:
        print(f"  ERROR {query!r}: {str(e)[:100]}")
        return []

def main():
    out = {"_meta": {"actualizado": cdmx_now().strftime("%Y-%m-%dT%H:%M CDMX"),
                     "fuente": "datos.gob.mx · CKAN API"},
           "temas": {}}
    vistos = set()
    total = 0
    for tema, q in TEMAS.items():
        items = []
        for p in buscar(q):
            pid = p.get("id")
            if not pid or pid in vistos:
                continue
            vistos.add(pid)
            org = (p.get("organization") or {}).get("title") or ""
            fecha = (p.get("metadata_modified") or "")[:10]
            items.append({
                "titulo": (p.get("title") or "").strip(),
                "org": org,
                "fecha": fecha,
                "url": f"https://datos.gob.mx/busca/dataset/{p.get('name','')}" if p.get("name")
                       else "https://datos.gob.mx/",
                "recursos": len(p.get("resources") or []),
            })
            if len(items) >= 5:
                break
        out["temas"][tema] = items
        total += len(items)
        print(f"  {tema}: {len(items)} datasets")
        time.sleep(0.4)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"Guardado {OUT.name} ({total} datasets)")

if __name__ == "__main__":
    main()
