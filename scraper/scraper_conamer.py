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
SIGLAS = {"ASEA","SEMARNAT","CONAGUA","CONAFOR","PROFEPA","CRE","SENER",
          "CONANP","INECC","SADER","CFE","CONUEE"}
KW = ["ambient","residuo","reciclaje","plastic","agua","hidric","energ","hidrocarbur",
      "petrol","combustible"," gas","emision","carbono","clima","forestal","biodivers",
      "envase","empaque","contaminante","sustancia","quimic","ecolog","sustentab",
      "renovable","eolic","solar","fotovoltaic","pesca","agricol","agropecuar",
      "fertilizante","plaguicida","mineria","minero","vida silvestre","impacto ambiental",
      "uso eficiente de la energia"]

# JS que corre DENTRO de la página (mismo origen → pasa Akamai) y devuelve las tarjetas
JS_SCRAPE = r"""
async () => {
  const seen = {}, all = [];
  for (let p = 1; p <= 8; p++) {
    const t = await fetch('/Buscador/SearchRegulacionResult?propuesta=propuesta-todos&tab=tab1&p='+p+'&s=9',
      {headers:{'X-Requested-With':'XMLHttpRequest'}}).then(r=>r.text()).catch(()=>'' );
    const d = document.createElement('div'); d.innerHTML = t;
    const cards = [].filter.call(d.querySelectorAll('.card'), c => c.querySelector('a[href*="IdAir"]'));
    if (!cards.length) break;
    let fresh = false;
    cards.forEach(c => {
      const id = (c.querySelector('a[href*="IdAir"]').getAttribute('href').match(/IdAir=(\d+)/)||[])[1];
      if (!id || seen[id]) return; seen[id] = 1; fresh = true;
      const title = c.querySelector('.card-title'); const tt = title ? title.textContent.replace(/\s+/g,' ').trim() : '';
      const txts = [].map.call(c.querySelectorAll('.text'), e => e.textContent.replace(/\s+/g,' ').trim());
      const tags = [].map.call(c.querySelectorAll('.tag'), e => e.textContent.replace(/\s+/g,' ').trim());
      const depEl = c.querySelector('.pt-3'); const dep = depEl ? depEl.textContent.replace(/\s+/g,' ').trim() : (tags[1]||'');
      all.push({
        id: id,
        siglas: (txts.find(x=>/Siglas:/.test(x))||'').replace('Siglas:','').trim(),
        fecha: (txts.find(x=>/Actualizaci/.test(x))||'').replace(/Actualizaci[^:]*:/,'').trim(),
        titulo: tt, dependencia: dep, tipo: tags[0]||'', subtipo: tags[2]||''
      });
    });
    if (!fresh) break;
  }
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
        rid = r.get("id")
        if not rid or rid in seen or not es_sector(r):
            continue
        seen.add(rid)
        items.append({
            "id": rid, "siglas": r.get("siglas",""), "fecha": r.get("fecha",""),
            "titulo": r.get("titulo",""), "dependencia": r.get("dependencia",""),
            "tipo": r.get("tipo",""), "subtipo": r.get("subtipo",""),
            "url": f"{BASE}/AirConstancia?IdAir={rid}&tab=tab1",
        })

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
