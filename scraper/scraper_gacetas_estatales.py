#!/usr/bin/env python3
"""
SCOPE — Ediciones oficiales recientes de gacetas/periódicos oficiales estatales.

NO existe una base nacional de gacetas estatales; cada estado publica su Periódico
u Boletín Oficial en su propio sitio. Este scraper trae, por ETAPAS, las ediciones
recientes de los estados cuyo portal es raspable con requests+BeautifulSoup (sin
navegador headless). Etapa 1 = estados "fáciles" verificados en vivo.

Salida: data/gaceta-estatal.json  →  {_meta, items:[{estado,fecha,titulo,url,tipo}]}
Se surte en la vista Gacetas ("Ediciones oficiales recientes"). Corre a diario.
"""
import sys, json, re, unicodedata
from datetime import datetime, date, timedelta, timezone
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import warnings
warnings.filterwarnings("ignore")
import requests
import urllib3
urllib3.disable_warnings()
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent.parent
OUT  = ROOT / "data" / "gacetas-oficiales-recientes.json"
UA   = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"}
DIAS_ATRAS = 21   # ventana de ediciones recientes

MESES = {"enero":1,"febrero":2,"marzo":3,"abril":4,"mayo":5,"junio":6,"julio":7,
         "agosto":8,"septiembre":9,"setiembre":9,"octubre":10,"noviembre":11,"diciembre":12}
MES3 = ["","ene","feb","mar","abr","may","jun","jul","ago","sep","oct","nov","dic"]


def cdmx_now():
    return datetime.now(timezone(timedelta(hours=-6)))

def get(url, **kw):
    try:
        return requests.get(url, headers=UA, timeout=25, verify=False, **kw)
    except Exception as e:
        print(f"    [ERR] {url} -> {str(e)[:80]}")
        return None

def head_ok(url):
    try:
        r = requests.head(url, headers=UA, timeout=15, verify=False, allow_redirects=True)
        if r.status_code == 200:
            return True
        # algunos servidores no soportan HEAD; confirma con GET ligero
        r = requests.get(url, headers=UA, timeout=20, verify=False, stream=True)
        ok = r.status_code == 200 and "pdf" in (r.headers.get("Content-Type","").lower() or "")
        r.close()
        return ok
    except Exception:
        return False

def fecha_iso(d):
    return d.strftime("%Y-%m-%d")

def dentro_ventana(iso):
    try:
        d = datetime.strptime(iso[:10], "%Y-%m-%d").date()
        return (date.today() - d).days <= 365 and d <= date.today() + timedelta(days=2)
    except Exception:
        return False

# ── Adaptadores por estado (cada uno devuelve lista de {estado,fecha,titulo,url}) ──

def scrape_yucatan():
    est, out = "Yucatán", []
    for i in range(DIAS_ATRAS):
        d = date.today() - timedelta(days=i)
        for ss, et in [("1","matutina"),("2","vespertina")]:
            u = f"https://www.yucatan.gob.mx/docs/diario_oficial/diarios/{d.year}/{fecha_iso(d)}_{ss}.pdf"
            if head_ok(u):
                out.append({"estado":est,"fecha":fecha_iso(d),
                            "titulo":f"Diario Oficial · edición {et}","url":u})
    return out

def scrape_guerrero():
    est, out, seen = "Guerrero", [], set()
    r = get("https://periodicooficial.guerrero.gob.mx/publicaciones/")
    if not r or r.status_code != 200:
        r = get("https://periodicooficial.guerrero.gob.mx/")
    if not r or r.status_code != 200:
        return out
    for m in re.finditer(r'https://periodicooficial\.guerrero\.gob\.mx/wp-content/uploads/(\d{4})/(\d{2})/([^"\']+?\.pdf)', r.text):
        url = m.group(0)
        if url in seen: continue
        seen.add(url)
        fname = m.group(3)
        # fecha del nombre: 21-AGOSTO-2026
        fm = re.search(r'(\d{1,2})[-_ ]([A-Za-zÁÉÍÓÚáéíóú]+)[-_ ](\d{4})', fname)
        iso = None
        if fm and fm.group(2).lower() in MESES:
            iso = f"{fm.group(3)}-{MESES[fm.group(2).lower()]:02d}-{int(fm.group(1)):02d}"
        else:
            iso = f"{m.group(1)}-{m.group(2)}-01"
        if not dentro_ventana(iso): continue
        num = re.search(r'P\.?O[.\- ]*(\d+)', fname, re.I)
        tit = "Periódico Oficial" + (f" No. {num.group(1)}" if num else "") + (" · alcance" if "alcance" in fname.lower() else "")
        out.append({"estado":est,"fecha":iso,"titulo":tit,"url":url})
    return out

def _mes_abbr(s):
    s = s.lower()[:3]
    for i in range(1, 13):
        if MES3[i] == s or (s == "set" and i == 9):
            return i
    return None

def scrape_tabasco():
    est, out = "Tabasco", []
    r = get("https://tabasco.gob.mx/periodicooficial")
    if not r or r.status_code != 200:
        return out
    soup = BeautifulSoup(r.text, "html.parser")
    for a in soup.find_all("a", href=re.compile(r"/documento/\d+/firmado_qr\.pdf")):
        url = a["href"]
        if not url.startswith("http"):
            url = "https://publicacionperiodico.tabasco.gob.mx" + url
        row = a.find_parent("tr")
        iso, cuerpo = None, ""
        if row:
            txt = row.get_text(" ", strip=True)
            # formato DD/Mmm/YYYY (ej. 22/Ago/2026)
            dm = re.search(r'(\d{1,2})/([A-Za-zÁÉÍÓÚáéíóú]{3,})/(\d{4})', txt)
            if dm and _mes_abbr(dm.group(2)):
                iso = f"{dm.group(3)}-{_mes_abbr(dm.group(2)):02d}-{int(dm.group(1)):02d}"
            else:
                dn = re.search(r'(\d{1,2})[/\-](\d{1,2})[/\-](\d{4})', txt)
                if dn:
                    iso = f"{dn.group(3)}-{int(dn.group(2)):02d}-{int(dn.group(1)):02d}"
            # cuerpo/tipo: lo que sigue al número de documento
            cm = re.search(r'\d{3,}\s+(.{6,110})', txt)
            if cm:
                cuerpo = re.sub(r'\s+', ' ', cm.group(1)).strip()
                cuerpo = re.sub(r'^\d+\s+', '', cuerpo)  # quita el número de documento sobrante
        if not iso or not dentro_ventana(iso):
            continue
        tit = "Periódico Oficial"
        if cuerpo:
            tit += " · " + (cuerpo[:70] + ("…" if len(cuerpo) > 70 else ""))
        out.append({"estado":est,"fecha":iso,"titulo":tit,"url":url})
    return out

def scrape_chihuahua():
    est, out = "Chihuahua", []
    r = get("http://www.chihuahua.gob.mx/atach2/periodicos/")
    if not r or r.status_code != 200:
        return out
    # índice Apache: <a href="poNN_YYYY.pdf">...</a>  DD-Mon-YYYY HH:MM  size
    for m in re.finditer(r'href="([^"]+\.pdf)"[^>]*>\s*[^<]*</a>\s*(\d{2})-([A-Za-z]{3})-(\d{4})', r.text):
        fname = m.group(1)
        mon = {"jan":1,"feb":2,"mar":3,"apr":4,"may":5,"jun":6,"jul":7,"aug":8,"sep":9,"oct":10,"nov":11,"dec":12}.get(m.group(3).lower())
        if not mon: continue
        iso = f"{m.group(4)}-{mon:02d}-{int(m.group(2)):02d}"
        if not dentro_ventana(iso): continue
        url = "http://www.chihuahua.gob.mx/atach2/periodicos/" + fname
        num = re.search(r'po[-_]?(\d+)', fname, re.I)
        out.append({"estado":est,"fecha":iso,
                    "titulo":"Periódico Oficial"+(f" No. {num.group(1)}" if num else ""),"url":url})
    return out

def scrape_colima():
    est, out = "Colima", []
    for i in range(DIAS_ATRAS):
        d = date.today() - timedelta(days=i)
        u = f"https://periodicooficial.col.gob.mx/p/{d.strftime('%d%m%Y')}/p{d.strftime('%y%m%d')}01.pdf"
        if head_ok(u):
            out.append({"estado":est,"fecha":fecha_iso(d),"titulo":"Periódico Oficial del Estado","url":u})
    return out

# Chihuahua queda fuera: su índice /atach2/periodicos/ solo tiene archivo viejo (2019-2022),
# sin ediciones recientes. Se reincorporará cuando se localice el índice vigente.
ADAPTADORES = [scrape_yucatan, scrape_guerrero, scrape_tabasco, scrape_colima]


def main():
    print(f"[START] gacetas estatales — {cdmx_now().strftime('%Y-%m-%d %H:%M CDMX')}")
    items, por_estado = [], {}
    for fn in ADAPTADORES:
        try:
            res = fn() or []
        except Exception as e:
            print(f"  {fn.__name__}: ERROR {str(e)[:100]}"); res = []
        # dedup por url dentro del estado
        seen = set(); clean = []
        for it in res:
            if it["url"] in seen: continue
            seen.add(it["url"]); clean.append(it)
        clean.sort(key=lambda x: x["fecha"], reverse=True)
        items.extend(clean)
        if clean:
            por_estado[clean[0]["estado"]] = len(clean)
        print(f"  {fn.__name__}: {len(clean)} ediciones")
    items.sort(key=lambda x: x["fecha"], reverse=True)
    out = {
        "_meta": {
            "ultima_actualizacion": cdmx_now().strftime("%Y-%m-%dT%H:%M:%S CDMX"),
            "estados_con_actividad": len(por_estado),
            "por_estado": por_estado,
            "nota": "Ediciones oficiales recientes raspadas por estado (etapa 1: estados con portal accesible). No es cobertura nacional completa.",
        },
        "items": items,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"[SAVED] {OUT.name}  |  {len(items)} ediciones · {len(por_estado)} estados")


if __name__ == "__main__":
    main()
