#!/usr/bin/env python3
"""
SCOPE — Etiquetado de empresas en las noticias (post-proceso de los scrapers).

Corre DESPUÉS de los scrapers y agrega el campo `empresas` (lista de nombres
canónicos) a cada nota de data/noticias.json y data/noticias-estatales.json
cuando el título o el resumen mencionan a una empresa de
data/empresas-monitoreo.json.

Es una CAPA PRIVADA: el tag lo consume la terminal por empresa (Mi Terminal /
inteligencia por dominio de correo), NO el Radar público ni el Observatorio.
La clasificación temática de cada nota NO cambia; el tag es aditivo.

Match con frontera de palabra sobre el texto normalizado (sin acentos, minúsculas)
para no activar por subcadena. Costo $0, sin IA, sin base de datos.
"""
import sys, json, re, unicodedata
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT  = Path(__file__).resolve().parent.parent
LISTA = ROOT / "data" / "empresas-monitoreo.json"
ARCHIVOS = ["noticias.json", "noticias-estatales.json", "noticias-estatales-historico.json"]

def norm(s):
    s = unicodedata.normalize("NFD", s or "")
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return s.lower()

def cargar_empresas():
    try:
        d = json.loads(LISTA.read_text(encoding="utf-8"))
    except Exception:
        return []
    out = []
    for e in d.get("empresas", []):
        nombre = e.get("nombre")
        alias = [a for a in ([nombre] + (e.get("alias") or [])) if a]
        rxs = [re.compile(r"(?<![a-z0-9])" + re.escape(norm(a)) + r"(?![a-z0-9])") for a in alias]
        if nombre and rxs:
            out.append((nombre, rxs))
    return out

def texto_nota(n):
    return norm(
        (n.get("titulo") or n.get("title") or "") + " " +
        (n.get("resumen") or n.get("descripcion") or n.get("description") or "")
    )

def _items(d):
    """Devuelve (lista_de_items, contenedor_para_reescribir)."""
    if isinstance(d, list):
        return d, d
    if isinstance(d, dict):
        for k in ("items", "noticias"):
            if isinstance(d.get(k), list):
                return d[k], d
    return None, None

def main():
    empresas = cargar_empresas()
    if not empresas:
        print("  empresas-monitoreo.json vacío o ausente — nada que etiquetar")
        return
    print(f"  Empresas monitoreadas: {len(empresas)}")
    for fn in ARCHIVOS:
        p = ROOT / "data" / fn
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        items, cont = _items(d)
        if items is None:
            continue
        n_tag = 0
        for it in items:
            if not isinstance(it, dict):
                continue
            t = texto_nota(it)
            hits = [nombre for (nombre, rxs) in empresas if any(rx.search(t) for rx in rxs)]
            if hits:
                it["empresas"] = hits
                n_tag += 1
            elif "empresas" in it:
                del it["empresas"]  # re-evaluación: purga tags previos que ya no aplican
        p.write_text(json.dumps(cont, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        print(f"  {fn}: {n_tag} notas etiquetadas con empresa")

if __name__ == "__main__":
    main()
