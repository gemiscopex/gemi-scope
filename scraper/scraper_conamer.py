#!/usr/bin/env python3
"""
SCOPE — Propuestas regulatorias en consulta (CONAMER).

herramientasregulatorias.gob.mx está protegido por Akamai: un request "pelón"
(requests/curl) recibe 403. La ÚNICA forma de leerlo es con un navegador real, así
que usamos Playwright/Chromium: cargamos la página (pasa el reto de Akamai) y desde
el contexto de la página hacemos fetch al endpoint de resultados, que devuelve un
fragmento HTML con las tarjetas. Filtramos a nuestros sectores y guardamos el espejo.

Output: data/conamer-propuestas.json  ·  se corre cada 2 semanas.
"""
import sys, json, re, unicodedata
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = Path(__file__).resolve().parent.parent
OUT  = ROOT / "data" / "conamer-propuestas.json"
BASE = "https://www.herramientasregulatorias.gob.mx"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

# Siglas de dependencias de nuestros sectores + keywords de filtrado
SIGLAS = {"ASEA","SEMARNAT","CONAGUA","CONAFOR","PROFEPA","CRE","CNE","SENER",
          "CONANP","INECC","SADER","CFE","CONUEE"}
KW = ["ambient","residuo","reciclaje","plastic","agua","hidric","energ","hidrocarbur",
      "petrol","combustible"," gas","emision","carbono","clima","forestal","biodivers",
      "envase","empaque","contaminante","sustancia","quimic","ecolog","sustentab",
      "renovable","eolic","solar","fotovoltaic","pesca","agricol","agropecuar",
      "fertilizante","plaguicida","mineria","minero","vida silvestre","impacto ambiental",
      "uso eficiente de la energia"]

# JS que corre DENTRO de la página (mismo origen → pasa Akamai). El buscador tiene
# botones de categoría (Todos / Exención / Análisis de Impacto Regulatorio). Los AIR
# (anteproyectos sustantivos: NOMs SEMARNAT/ASEA/ENER, resoluciones) NO aparecen en la
# vista por defecto (Exención). Hay que hacer CLIC en cada categoría y recolectar las
# tarjetas que renderiza (AJAX). Cada tarjeta enlaza a /AirConstancia?IdAir=NN (exención)
# o /AirConstancia/AirConvencional?IdAirgeneral=NN&air=NN (AIR).
JS_SCRAPE = r"""
async () => {
  const wait = ms => new Promise(r => setTimeout(r, ms));
  const seen = {}, all = [];
  const collect = (cat) => {
    const cards = [].filter.call(document.querySelectorAll('.card'), c => c.querySelector('a[href*="IdAir"]'));
    cards.forEach(c => {
      const a = c.querySelector('a[href*="IdAir"]');
      const href = a ? a.getAttribute('href') : '';
      const key = href || (a && a.textContent);
      if (!href || seen[href]) return; seen[href] = 1;
      const title = c.querySelector('.card-title'); const tt = title ? title.textContent.replace(/\s+/g,' ').trim() : '';
      const txts = [].map.call(c.querySelectorAll('.text'), e => e.textContent.replace(/\s+/g,' ').trim());
      const tags = [].map.call(c.querySelectorAll('.tag'), e => e.textContent.replace(/\s+/g,' ').trim());
      const depEl = c.querySelector('.pt-3'); const dep = depEl ? depEl.textContent.replace(/\s+/g,' ').trim() : (tags[1]||'');
      all.push({
        href: href, categoria: cat,
        siglas: (txts.find(x=>/Siglas:/.test(x))||'').replace('Siglas:','').trim(),
        fecha: (txts.find(x=>/Actualizaci/.test(x))||'').replace(/Actualizaci[^:]*:/,'').trim(),
        // Cualquier texto que hable de comentarios/cierre/plazo de la consulta pública
        plazo: (txts.find(x=>/coment|cierre|vence|plazo|periodo|per[ií]odo|consulta\s+p[uú]blica|fecha\s+l[ií]mite|env[ií]o de comentarios/i.test(x))||''),
        textos: txts,
        titulo: tt, dependencia: dep, tipo: tags[0]||'', subtipo: tags[2]||''
      });
    });
  };
  // Recorre cada botón de categoría; si no existe, hace fallback a lo que ya esté en pantalla
  const cats = [['btnExencion','exencion'], ['btnAirConvencional','air'], ['btnairexpost','airexpost']];
  let clicked = false;
  for (const [bid, cat] of cats) {
    const b = document.getElementById(bid);
    if (!b) continue;
    clicked = true;
    b.click(); await wait(2800);
    collect(cat);
  }
  if (!clicked) collect('todos');   // fallback: vista por defecto
  return all;
}
"""

def cdmx_now():
    return datetime.now(timezone(timedelta(hours=-6)))

def qa(s):
    return "".join(c for c in unicodedata.normalize("NFD", (s or "").lower())
                   if unicodedata.category(c) != "Mn")

def es_sector(r):
    if (r.get("siglas") or "").upper() in SIGLAS:
        return True
    hay = qa((r.get("titulo") or "") + " " + (r.get("dependencia") or ""))
    return any(k in hay for k in KW)

_MESES_C = {"enero":1,"febrero":2,"marzo":3,"abril":4,"mayo":5,"junio":6,"julio":7,
            "agosto":8,"septiembre":9,"setiembre":9,"octubre":10,"noviembre":11,"diciembre":12}

def _fecha_cierre(r):
    """Deriva la fecha de cierre de la consulta desde el texto de la tarjeta.
    Devuelve (ISO 'YYYY-MM-DD' | '', texto_plazo). Si hay un rango, toma la fecha
    MÁS TARDÍA (el cierre). Best-effort: si la plataforma no la expone, queda vacío."""
    blobs = []
    if r.get("plazo"):
        blobs.append(r["plazo"])
    for t in (r.get("textos") or []):
        if re.search(r"coment|cierre|vence|plazo|per[ií]odo|consulta\s+p[uú]blica|fecha\s+l[ií]mite", t, re.I):
            blobs.append(t)
    plazo_txt = " · ".join(dict.fromkeys([b for b in blobs if b]))[:200]
    fechas = []
    for b in blobs:
        for m in re.finditer(r"(\d{1,2})[/\-](\d{1,2})[/\-](\d{4})", b):
            try:
                fechas.append(datetime(int(m.group(3)), int(m.group(2)), int(m.group(1))).date())
            except ValueError:
                pass
        for m in re.finditer(r"(\d{4})-(\d{2})-(\d{2})", b):
            try:
                fechas.append(datetime(int(m.group(1)), int(m.group(2)), int(m.group(3))).date())
            except ValueError:
                pass
        for m in re.finditer(r"(\d{1,2})\s+de\s+([A-Za-zÁÉÍÓÚáéíóú]+)\s+de\s+(\d{4})", b, re.I):
            mes = _MESES_C.get(m.group(2).lower())
            if mes:
                try:
                    fechas.append(datetime(int(m.group(3)), mes, int(m.group(1))).date())
                except ValueError:
                    pass
    if not fechas:
        return "", plazo_txt
    return max(fechas).strftime("%Y-%m-%d"), plazo_txt


def main():
    print("SCOPE — CONAMER propuestas —", cdmx_now().strftime("%Y-%m-%d %H:%M CDMX"))
    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:
        print("Playwright no disponible:", str(e)[:100]); return

    raw = []
    try:
        with sync_playwright() as pw:
            b = pw.chromium.launch(headless=True, args=["--no-sandbox","--disable-blink-features=AutomationControlled"])
            ctx = b.new_context(user_agent=UA, locale="es-MX", viewport={"width":1366,"height":900})
            page = ctx.new_page()
            page.goto(BASE + "/", wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(3500)  # deja que Akamai asiente cookies/sensor
            raw = page.evaluate(JS_SCRAPE) or []
            b.close()
    except Exception as e:
        print("ERROR navegador:", str(e)[:160])

    print(f"  propuestas leídas: {len(raw)}")
    if not raw:
        print("Sin datos (¿Akamai bloqueó?); se conserva el archivo previo."); return

    seen, items = set(), []
    for r in raw:
        href = r.get("href") or ""
        if not href or href in seen or not es_sector(r):
            continue
        seen.add(href)
        url = href if href.startswith("http") else BASE + ("" if href.startswith("/") else "/") + href
        cierre_iso, plazo_txt = _fecha_cierre(r)
        items.append({
            "id": href, "siglas": r.get("siglas",""), "fecha": r.get("fecha",""),
            "titulo": r.get("titulo",""), "dependencia": r.get("dependencia",""),
            "tipo": r.get("tipo",""), "subtipo": r.get("subtipo",""),
            "categoria": r.get("categoria",""), "url": url,
            "fecha_cierre": cierre_iso, "plazo": plazo_txt,
        })
    # AIR (anteproyectos sustantivos) primero, luego exenciones
    items.sort(key=lambda x: 0 if str(x.get("tipo","")).startswith("Análisis") else 1)

    out = {
        "_meta": {
            "actualizado": cdmx_now().strftime("%Y-%m-%dT%H:%M CDMX"),
            "fuente": "CONAMER · Plataforma Integral de Gobernanza Regulatoria (herramientasregulatorias.gob.mx)",
            "url": BASE + "/",
            "nota": "Espejo de propuestas regulatorias en consulta que impactan sectores ambiental, energía, agua y residuos. Se actualiza cada 2 semanas.",
        },
        "items": items,
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"Guardado {OUT.name}  |  {len(items)} de {len(raw)} en nuestros sectores")

if __name__ == "__main__":
    main()
