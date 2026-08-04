#!/usr/bin/env python3
"""
SCOPE — Sitios contaminados y remediados (SEMARNAT · datos.gob.mx).

Ingesta REAL (no solo el link del catálogo): baja los CSV del Inventario Nacional
de Sitios Contaminados y de Sitios Remediados, y los agrega por entidad + tipo de
contaminante + modalidad, para nutrir el expediente estatal y el mapa de SCOPE.

Output: data/sitios-contaminados.json
"""
import sys, json, csv, io, re
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import warnings; warnings.filterwarnings("ignore")
import requests
requests.packages.urllib3.disable_warnings()

ROOT = Path(__file__).resolve().parent.parent
OUT  = ROOT / "data" / "sitios-contaminados.json"
UA   = {"User-Agent": "Mozilla/5.0 (compatible; SCOPE-GEMI/1.0)"}

CSV_CONTAMINADOS = "https://www.datos.gob.mx/dataset/e64bdd35-793a-4601-a17f-30c643b74f1a/resource/3279942f-a39e-4556-80ab-7d0b8813b2e5/download/sitios_contaminados_geoportal.csv"
CSV_REMEDIADOS   = "https://www.datos.gob.mx/dataset/e64bdd35-793a-4601-a17f-30c643b74f1a/resource/5194cd4a-35df-448f-ac83-69298fbc5b85/download/sitios_remediados_geoportal.csv"

# Normaliza nombres de entidad a los que usa SCOPE
ALIAS = {
    "distrito federal": "Ciudad de México",
    "ciudad de mexico": "Ciudad de México",
    "cdmx": "Ciudad de México",
    "estado de mexico": "México",
    "mexico": "México",
    "coahuila de zaragoza": "Coahuila",
    "michoacan de ocampo": "Michoacán",
    "veracruz de ignacio de la llave": "Veracruz",
    "veracruz de ignacio de la llave.": "Veracruz",
}

def cdmx_now():
    return datetime.now(timezone(timedelta(hours=-6)))

def _strip(s):
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFD", s or "") if unicodedata.category(c) != "Mn").lower().strip()

def norm_estado(s):
    s = (s or "").replace("_", " ").strip()
    key = _strip(s)
    if key in ALIAS:
        return ALIAS[key]
    return s

def fetch_csv(url):
    r = requests.get(url, headers=UA, timeout=90, verify=False)
    r.raise_for_status()
    # Los CSV del geoportal vienen en UTF-8 (verificado por bytes: 'é' = C3 A9)
    txt = r.content.decode("utf-8", "replace")
    return list(csv.DictReader(io.StringIO(txt)))

def top(counter, n=8):
    return dict(sorted(counter.items(), key=lambda kv: kv[1], reverse=True)[:n])

def main():
    from collections import defaultdict, Counter
    print("SCOPE — Sitios contaminados/remediados —", cdmx_now().strftime("%Y-%m-%d %H:%M CDMX"))

    try:
        cont = fetch_csv(CSV_CONTAMINADOS)
    except Exception as e:
        print("ERROR contaminados:", str(e)[:120]); cont = []
    try:
        reme = fetch_csv(CSV_REMEDIADOS)
    except Exception as e:
        print("ERROR remediados:", str(e)[:120]); reme = []

    if not cont and not reme:
        print("Sin datos; se conserva el archivo previo."); return
    print(f"  contaminados: {len(cont)}  |  remediados: {len(reme)}")

    est = defaultdict(lambda: {
        "contaminados": 0, "remediados": 0,
        "contaminante": Counter(), "modalidad": Counter(),
        "municipio": Counter(), "recientes": [],
    })
    nac_cont = Counter(); nac_mod = Counter()

    for r in cont:
        e = norm_estado(r.get("estado") or r.get("estado_etq"))
        if not e:
            continue
        d = est[e]
        d["contaminados"] += 1
        cg = (r.get("contaminante_generico") or "").strip() or "Otro"
        md = (r.get("modalidad_sitio_contaminado") or "").strip() or "—"
        mu = (r.get("municipio") or "").strip()
        d["contaminante"][cg] += 1; d["modalidad"][md] += 1
        if mu: d["municipio"][mu] += 1
        nac_cont[cg] += 1; nac_mod[md] += 1
        d["recientes"].append({
            "anio": (r.get("anio_identificacion") or "").strip(),
            "municipio": mu, "contaminante": cg, "modalidad": md,
            "evento": (r.get("tipo_evento") or "").strip(),
        })

    for r in reme:
        e = norm_estado(r.get("estado") or r.get("estado_etq"))
        if not e:
            continue
        est[e]["remediados"] += 1

    estados = {}
    for e, d in est.items():
        recientes = sorted([x for x in d["recientes"] if x["anio"].isdigit()],
                           key=lambda x: x["anio"], reverse=True)[:5]
        tot = d["contaminados"] + d["remediados"]
        estados[e] = {
            "contaminados": d["contaminados"],
            "remediados": d["remediados"],
            "pct_remediado": round(d["remediados"] / tot * 100) if tot else 0,
            "por_contaminante": top(d["contaminante"]),
            "por_modalidad": top(d["modalidad"], 5),
            "top_municipios": top(d["municipio"], 5),
            "recientes": recientes,
        }

    out = {
        "_meta": {
            "actualizado": cdmx_now().strftime("%Y-%m-%dT%H:%M CDMX"),
            "fuente": "SEMARNAT · Inventario Nacional de Sitios Contaminados y Remediados (datos.gob.mx)",
            "url": "https://www.datos.gob.mx/dataset/inventario_sitios_contaminados_remediados",
        },
        "nacional": {
            "contaminados": len(cont),
            "remediados": len(reme),
            "por_contaminante": top(nac_cont, 10),
            "por_modalidad": top(nac_mod, 6),
        },
        "estados": estados,
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"Guardado {OUT.name}  |  {len(estados)} entidades")

if __name__ == "__main__":
    main()
