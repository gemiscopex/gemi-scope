#!/usr/bin/env python3
"""
SCOPE — Sondeo de medios (patrón FIAT).

Detecta automáticamente el método de acceso de cada medio en data/medios.csv:
  wp_api  → expone /wp-json/wp/v2/posts (lo mejor: paginado + filtro por fecha)
  rss     → expone /feed
  sitemap → expone sitemap.xml / news-sitemap
  no_accesible → bloqueo, JS o Cloudflare

Uso:
  python scraper/scraper_sondeo.py              # reverifica los 96 y actualiza el CSV
  python scraper/scraper_sondeo.py --check      # solo reporta, no escribe
  python scraper/scraper_sondeo.py URL "Medio" Estado   # sondea un medio nuevo y lo sugiere

Sube la prioridad de un medio: sitemap/no_accesible que resulten wp_api o rss
entran de inmediato al scraping diario.
"""
import sys, csv, re, time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import warnings
warnings.filterwarnings("ignore")
import requests

ROOT   = Path(__file__).resolve().parent.parent
MEDIOS = ROOT / "data" / "medios.csv"
# UA de navegador real: muchos medios bloquean bots pero no un Chrome normal.
UA_BOT = {"User-Agent": "Mozilla/5.0 (compatible; SCOPE-GEMI/1.0; sondeo)"}
UA_BROWSER = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
              "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"}
_ORDEN = {"wp_api": 3, "rss": 2, "sitemap": 1, "no_accesible": 0}  # ranking de calidad

def _get(u, ua, timeout=12):
    return requests.get(u, headers=ua, timeout=timeout, verify=False, allow_redirects=True)

def _probe_una_vez(url, ua):
    base = url.rstrip("/")
    try:
        r = _get(base + "/wp-json/wp/v2/posts?per_page=1", ua)
        if r.status_code == 200 and isinstance(r.json(), list) and r.json():
            return "wp_api"
    except Exception:
        pass
    for path in ("/feed", "/feed/", "/rss", "/?feed=rss2"):
        try:
            r = _get(base + path, ua)
            head = r.text[:6000]
            if r.status_code == 200 and ("<rss" in head or "<item" in head or "<feed" in head):
                return "rss"
        except Exception:
            pass
    for path in ("/news-sitemap.xml", "/sitemap-news.xml", "/sitemap_index.xml", "/sitemap.xml"):
        try:
            r = _get(base + path, ua)
            head = r.text[:3000]
            if r.status_code == 200 and ("<urlset" in head or "<sitemapindex" in head):
                return "sitemap"
        except Exception:
            pass
    return "no_accesible"

def probe(url):
    """Sondea con reintentos: bot → navegador → navegador (con esperas).
    Un solo fallo puede ser bloqueo temporal de Cloudflare; por eso reintentamos."""
    intentos = [UA_BOT, UA_BROWSER, UA_BROWSER]
    for i, ua in enumerate(intentos):
        res = _probe_una_vez(url, ua)
        if res != "no_accesible":
            return res
        if i < len(intentos) - 1:
            time.sleep(1.5)
    return "no_accesible"

def main():
    check_only = "--check" in sys.argv
    # Sondeo de un medio nuevo: URL "Medio" Estado
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if args and args[0].startswith("http"):
        url = args[0]
        metodo = probe(url)
        nombre = args[1] if len(args) > 1 else "?"
        estado = args[2] if len(args) > 2 else "?"
        print(f"Sondeo de {url}")
        print(f"  método detectado: {metodo}")
        print(f"  fila CSV sugerida: {estado},{nombre},{metodo},{url}")
        return

    force = "--force" in sys.argv  # permite degradar accesible → no_accesible
    rows = list(csv.DictReader(open(MEDIOS, encoding="utf-8")))
    print(f"Sondeando {len(rows)} medios… (conservador: no degrada sin --force)")
    cambios, conservados = [], []
    for row in rows:
        viejo = row["metodo"]
        nuevo = probe(row["url"])
        # Regla conservadora: si el sondeo falla pero el medio funcionaba,
        # conservamos el método viejo (probable bloqueo temporal, no lo matamos).
        if nuevo == "no_accesible" and viejo != "no_accesible" and not force:
            conservados.append((row["medio"], viejo))
            print(f"  · {row['medio']}: sondeo falló, se conserva '{viejo}' (posible bloqueo temporal)")
            continue
        if nuevo != viejo:
            cambios.append((row["medio"], viejo, nuevo))
            flecha = "↑" if _ORDEN[nuevo] > _ORDEN[viejo] else "↓"
            print(f"  {flecha} {row['medio']}: {viejo} → {nuevo}")
        row["metodo"] = nuevo

    from collections import Counter
    tot = dict(Counter(r["metodo"] for r in rows))
    print(f"\nResumen: {tot}")
    print(f"Cambios aplicados: {len(cambios)} · conservados por bloqueo temporal: {len(conservados)}")
    accesibles = tot.get("wp_api", 0) + tot.get("rss", 0) + tot.get("sitemap", 0)
    print(f"Accesibles (wp_api+rss+sitemap) para el scraping: {accesibles}/{len(rows)}")

    if check_only:
        print("\n(--check: no se escribió el CSV)")
        return
    with open(MEDIOS, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["estado", "medio", "metodo", "url"])
        w.writeheader()
        for row in rows:
            w.writerow({k: row[k] for k in ["estado", "medio", "metodo", "url"]})
    print(f"Actualizado {MEDIOS.name}")

if __name__ == "__main__":
    main()
