#!/usr/bin/env python3
"""
SCOPE — Actualización automática de datos.

Actualiza (sin intervención manual):
  1. Fechas de última/próxima sesión de cada comisión
       - Diputados: API GraphQL (getReunionesComision)
       - Senado:    micrositios comisiones.senado.gob.mx/{slug}/reuniones
  2. Fotos de legisladores
       - Diputados: API GraphQL (getPartidosComision → SFTPFotografia),
         descargadas y embebidas como base64 64x64 (el SSL de portalhcd
         es inválido y los navegadores bloquean las URLs directas)
       - Senado:    URLs directas de senado.gob.mx (SSL válido),
         extraídas de las páginas de comisión vía Playwright

Uso:
  python scraper/auto_update.py               # todo
  python scraper/auto_update.py --skip-photos # solo fechas de sesión

Corre diario en GitHub Actions (.github/workflows/auto-update.yml).
"""
import sys, os, io, re, json, time, base64, argparse, unicodedata
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import warnings
warnings.filterwarnings("ignore")
import requests

ROOT       = Path(__file__).resolve().parent.parent
COMISIONES = ROOT / "data" / "comisiones.json"
FOTOS      = ROOT / "data" / "fotos_legisladores.json"

GRAPHQL = "https://micrositios.diputados.gob.mx:4001/graphql"
GQL_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "*/*",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Origin": "https://web.diputados.gob.mx",
    "Referer": "https://web.diputados.gob.mx/",
}
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

CDMX = timezone(timedelta(hours=-6))

def now_cdmx():
    return datetime.now(CDMX)

def parse_ddmmyyyy(s):
    try:
        return datetime.strptime(s or "", "%d/%m/%Y").date()
    except ValueError:
        return None

def norm(s):
    s = re.sub(r"^(sen\.|dip\.)\s*", "", (s or "").strip(), flags=re.IGNORECASE)
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return s.lower().strip()

def word_set(s):
    return frozenset(norm(s).split())

def slug_words(url):
    fname = url.split("/")[-1].rsplit(".", 1)[0]
    fname = re.sub(r"^\d+-", "", fname)
    fname = re.sub(r"-\d{8}-\d{6}$", "", fname)
    return frozenset(fname.replace("_", " ").split())

# ── Diputados: GraphQL ───────────────────────────────────────────────────────

def gql(query, retries=3):
    for i in range(retries):
        try:
            r = requests.post(GRAPHQL, headers=GQL_HEADERS, json={"query": query},
                              timeout=25, verify=False)
            if r.status_code == 200:
                return r.json().get("data", {})
            print(f"    GraphQL HTTP {r.status_code} (intento {i+1})")
        except Exception as e:
            print(f"    GraphQL error: {str(e)[:100]} (intento {i+1})")
        time.sleep(2 * (i + 1))
    return {}

def dip_sesiones(oid):
    """Devuelve (ultima 'DD/MM/YYYY' | None, proxima | None)."""
    data = gql("""{
      getReunionesComision(Oid: "%s") { Fecha NombreReunion }
    }""" % oid)
    reuniones = data.get("getReunionesComision") or []
    hoy = now_cdmx().date()
    pasadas, futuras = [], []
    for r in reuniones:
        f = (r.get("Fecha") or "")[:10]
        try:
            d = datetime.strptime(f, "%Y-%m-%d").date()
        except ValueError:
            continue
        (pasadas if d <= hoy else futuras).append(d)
    ultima  = max(pasadas).strftime("%d/%m/%Y") if pasadas else None
    proxima = min(futuras).strftime("%d/%m/%Y") if futuras else None
    return ultima, proxima

def dip_fotos_api(oid):
    """Devuelve lista de (nombre_api, foto_url) de una comisión."""
    data = gql("""{
      getPartidosComision(Oid: "%s") {
        Integrantes { Diputado SFTPFotografia }
      }
    }""" % oid)
    out = []
    for partido in (data.get("getPartidosComision") or []):
        for m in (partido.get("Integrantes") or []):
            n, f = m.get("Diputado"), m.get("SFTPFotografia")
            if n and f:
                out.append((n, f))
    return out

# ── Senado: micrositios (fechas) ─────────────────────────────────────────────

def sen_sesiones(slug):
    """Parsea comisiones.senado.gob.mx/{slug}/reuniones → (ultima, proxima)."""
    try:
        r = requests.get(f"https://comisiones.senado.gob.mx/{slug}/reuniones",
                         headers=UA, timeout=20, verify=False)
        if r.status_code != 200:
            return None, None
    except Exception:
        return None, None
    fechas = set(re.findall(r"\d{2}/\d{2}/\d{4}", r.text))
    hoy = now_cdmx().date()
    pasadas, futuras = [], []
    for f in fechas:
        try:
            d = datetime.strptime(f, "%d/%m/%Y").date()
        except ValueError:
            continue
        # Descarta fechas absurdas (fuera de la legislatura)
        if not (2024 <= d.year <= 2030):
            continue
        (pasadas if d <= hoy else futuras).append(d)
    ultima  = max(pasadas).strftime("%d/%m/%Y") if pasadas else None
    proxima = min(futuras).strftime("%d/%m/%Y") if futuras else None
    return ultima, proxima

# ── Senado: fotos vía Playwright ─────────────────────────────────────────────

def sen_fotos(commission_ids, target_names, existing):
    """Extrae fotos de senadores de las páginas de comisión. Merge, nunca borra."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("  Playwright no disponible — se omiten fotos del Senado")
        return existing
    out = dict(existing)
    with sync_playwright() as pw:
        for com_id in commission_ids:
            url = f"https://www.senado.gob.mx/66/comisiones/ordinarias/{com_id}"
            browser = pw.chromium.launch(headless=True)
            ctx = browser.new_context(user_agent=UA["User-Agent"], locale="es-MX")
            page = ctx.new_page()
            try:
                page.goto(url, timeout=60000, wait_until="domcontentloaded")
                time.sleep(8)
                for _ in range(12):
                    page.evaluate("window.scrollBy(0, 300)")
                    time.sleep(0.4)
                time.sleep(4)
                photo_urls = page.evaluate(
                    "() => Array.from(document.querySelectorAll('img'))"
                    ".map(i => i.src)"
                    ".filter(s => s.includes('images/senadores/66/') && !s.includes('blanco'))"
                )
                nuevos = 0
                for pu in photo_urls:
                    uws = slug_words(pu)
                    if not uws:
                        continue
                    best, best_score = None, 0
                    for (orig, nk, ws) in target_names:
                        ov = len(uws & ws) / len(uws | ws) if (uws | ws) else 0
                        if ov > best_score:
                            best_score, best = ov, nk
                    if best and best_score >= 0.6 and out.get(best) != pu:
                        out[best] = pu
                        nuevos += 1
                print(f"  Senado comisión {com_id}: {len(photo_urls)} fotos, {nuevos} nuevas/actualizadas")
            except Exception as e:
                print(f"  Senado comisión {com_id}: ERROR {str(e)[:100]}")
            finally:
                page.close()
                browser.close()
    return out

# ── Diputados: fotos → base64 ────────────────────────────────────────────────

def foto_a_b64(url):
    """Descarga, recorta al centro, redimensiona a 64x64, devuelve data URI."""
    from PIL import Image
    r = requests.get(url, headers=UA, timeout=15, verify=False)
    if r.status_code != 200:
        return None
    img = Image.open(io.BytesIO(r.content)).convert("RGB")
    w, h = img.size
    sq = min(w, h)
    img = img.crop(((w - sq) // 2, (h - sq) // 2,
                    (w - sq) // 2 + sq, (h - sq) // 2 + sq))
    img = img.resize((64, 64), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=75, optimize=True)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("ascii")

# ── main ─────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-photos", action="store_true",
                    help="solo actualizar fechas de sesión")
    args = ap.parse_args()

    with open(COMISIONES, encoding="utf-8") as f:
        coms_data = json.load(f)

    OID_RE  = re.compile(r"comision/([0-9a-f-]{36})")
    SLUG_RE = re.compile(r"comisiones\.senado\.gob\.mx/([^/]+)/")
    SEN_ID_RE = re.compile(r"ordinarias/(\d+)")

    cambios_fechas = 0
    dip_api_fotos = {}   # word_set → url
    sen_com_ids   = []

    print("── Fechas de sesión ──")
    for c in coms_data["comisiones"]:
        cam = (c.get("camara") or "").lower()
        nombre = c.get("nombre", "?")
        ultima = proxima = None
        if cam == "diputados":
            m = OID_RE.search(c.get("url", ""))
            if m:
                ultima, proxima = dip_sesiones(m.group(1))
                if not args.skip_photos:
                    for (n, foto) in dip_fotos_api(m.group(1)):
                        dip_api_fotos[word_set(n)] = foto
        elif cam == "senado":
            m = SLUG_RE.search(c.get("at", ""))
            if m:
                ultima, proxima = sen_sesiones(m.group(1))
            m2 = SEN_ID_RE.search(c.get("url", ""))
            if m2:
                sen_com_ids.append(m2.group(1))
        # "Última sesión" solo avanza — los micrositios a veces van atrasados
        # respecto a datos capturados de otras fuentes; nunca retrocedemos.
        d_new, d_old = parse_ddmmyyyy(ultima), parse_ddmmyyyy(c.get("ur"))
        if d_new and (not d_old or d_new > d_old):
            print(f"  {nombre}: última {c.get('ur')} → {ultima}")
            c["ur"] = ultima
            cambios_fechas += 1
        if proxima != c.get("pr"):
            if proxima or c.get("pr"):
                print(f"  {nombre}: próxima {c.get('pr')} → {proxima}")
            c["pr"] = proxima
            cambios_fechas += 1

    coms_data.setdefault("_meta", {})["ultima_actualizacion"] = \
        now_cdmx().strftime("%Y-%m-%d")

    with open(COMISIONES, "w", encoding="utf-8") as f:
        json.dump(coms_data, f, ensure_ascii=False, indent=2)
    print(f"  {cambios_fechas} fechas actualizadas")

    if args.skip_photos:
        print("\n(fotos omitidas por --skip-photos)")
        return

    # ── Fotos ──
    print("\n── Fotos de legisladores ──")
    try:
        with open(FOTOS, encoding="utf-8") as f:
            fotos = json.load(f)
    except FileNotFoundError:
        fotos = {"senado": {}, "diputados": {}}

    # Nombres objetivo por cámara
    dip_names, sen_names = [], []
    for c in coms_data["comisiones"]:
        cam = (c.get("camara") or "").lower()
        for m in c.get("integrantes", []):
            n = m["n"]; nk = norm(n)
            lst = dip_names if cam == "diputados" else sen_names
            if not any(x[1] == nk for x in lst):
                lst.append((n, nk, word_set(n)))

    # Diputados: match nombre → URL de la API, base64 solo para nuevos
    dip_out = dict(fotos.get("diputados", {}))
    nuevos_dip = 0
    for (orig, nk, ws) in dip_names:
        url = dip_api_fotos.get(ws)
        if not url:
            best, best_score = None, 0
            for aws, u in dip_api_fotos.items():
                ov = len(ws & aws) / len(ws | aws) if (ws | aws) else 0
                if ov > best_score:
                    best_score, best = ov, u
            if best_score >= 0.75:
                url = best
        if url and nk not in dip_out:
            try:
                b64 = foto_a_b64(url)
                if b64:
                    dip_out[nk] = b64
                    nuevos_dip += 1
                time.sleep(0.05)
            except Exception as e:
                print(f"  foto {nk}: ERROR {str(e)[:80]}")
    print(f"  Diputados: {len(dip_out)}/{len(dip_names)} con foto ({nuevos_dip} nuevas)")

    # Senado: merge de URLs desde páginas de comisión
    sen_out = sen_fotos(sen_com_ids, sen_names, fotos.get("senado", {}))
    con_foto_sen = sum(1 for (_, nk, _) in sen_names if nk in sen_out)
    print(f"  Senado: {con_foto_sen}/{len(sen_names)} con foto")

    fotos_new = {
        "_meta": {
            "actualizado": now_cdmx().strftime("%Y-%m-%dT%H:%M CDMX"),
            "senado": con_foto_sen,
            "diputados": len(dip_out),
        },
        "senado": sen_out,
        "diputados": dip_out,
    }
    with open(FOTOS, "w", encoding="utf-8") as f:
        json.dump(fotos_new, f, ensure_ascii=False, separators=(",", ":"))
    print(f"  Guardado {FOTOS.name}")

    # Datos abiertos ambientales (datos.gob.mx)
    print("\n── Datos abiertos (datos.gob.mx) ──")
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import scraper_datosgob
        scraper_datosgob.main()
    except Exception as e:
        print(f"  ERROR datosgob: {str(e)[:120]}")

    # Perfil de estados (Data México: población, PEA, sectores)
    print("\n── Perfil de estados (Data México) ──")
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import scraper_datamexico
        scraper_datamexico.main()
    except Exception as e:
        print(f"  ERROR datamexico: {str(e)[:120]}")

    # Drift de integrantes (informativo)
    print("\n── Verificación de integrantes (informativo) ──")
    for c in coms_data["comisiones"]:
        if (c.get("camara") or "").lower() != "diputados":
            continue
        m = OID_RE.search(c.get("url", ""))
        if not m:
            continue
        data = gql('{ getIntComision(Oid: "%s") { Oid } }' % m.group(1))
        api_n = len(data.get("getIntComision") or [])
        local_n = len(c.get("integrantes", []))
        flag = " ⚠ REVISAR" if api_n and api_n != local_n else ""
        print(f"  {c['nombre']}: local {local_n} vs API {api_n}{flag}")

if __name__ == "__main__":
    main()
