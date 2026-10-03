#!/usr/bin/env python3
"""
SCOPE — Legisladores con actividad en temas GEMI.

Solo entra quien ha PRESENTADO al menos 1 iniciativa o punto de acuerdo propio en
temas GEMI. Los exhortos firmados por 5+ legisladores (bancada completa) cuentan como
firma de bancada, no como autoría.

Fuentes (ya filtradas a temas GEMI por sus scrapers):
  data/sil.json                 iniciativas y proposiciones del SIL (Gobernación)
  data/congreso-historico.json  instrumentos de las gacetas de Diputados y Senado
Apoyo estático:
  scraper/datos/padron-legisladores.json  foto oficial, entidad y ficha (SITL / senado.gob.mx)
  scraper/datos/leyes-federales.json      índice de leyes federales vigentes + cuáles están en Scope

Append-only: los instrumentos ya registrados se conservan aunque salgan de la ventana
del SIL (últimos 500 asuntos) o de la gaceta.
Salida: data/legisladores-gemi.json
"""
import json, re, sys, difflib, unicodedata, collections
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).resolve().parent))
from scraper_gacetas import is_relevant

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
AUX = Path(__file__).resolve().parent / "datos"
OUT = DATA / "legisladores-gemi.json"
FIRMAS_BANCADA = 5


def norm(s):
    s = unicodedata.normalize("NFD", str(s or "")).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"\(.*?\)", " ", s)
    s = re.sub(r"\b(dip|sen)\b\.?", " ", s)
    return re.sub(r"\s+", " ", re.sub(r"[^a-z ]", " ", s)).strip()


def nz(s):
    s = unicodedata.normalize("NFD", str(s or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", s)).strip()


def cargar(p, defecto):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return defecto


# ── Leyes: cuál reforma cada instrumento (título + aspectos), la más larga gana ──
LEYES = cargar(AUX / "leyes-federales.json", [])
PATS = sorted(((p, l["nombre"]) for l in LEYES for p in l["pats"] if len(p) > 12), key=lambda x: -len(x[0]))
SIG = [(re.compile(r"\b" + s + r"\b"), l["nombre"]) for l in LEYES for s in l.get("siglas", [])]
EN_SCOPE = {l["nombre"] for l in LEYES if l["en_scope"]}


def leyes_de(texto):
    t = " " + nz(texto) + " "
    hall = []
    for p, n in PATS:
        q = " " + p + " "
        if q in t:
            hall.append(n)
            t = t.replace(q, " # ")
    for rx, n in SIG:
        if rx.search(texto or "") and n not in hall:
            hall.append(n)
    return hall


# ── Instrumentos por legislador ──
L = {}


def add(nombre, camara, partido, inst):
    k = norm(nombre)
    if len(k.split()) < 2:
        return
    p = L.setdefault(k, {"nombre": re.sub(r"\s+", " ", nombre).strip(), "camara": camara, "partido": partido, "instrumentos": {}})
    if partido and not p["partido"]:
        p["partido"] = partido
    p["instrumentos"][inst["id"]] = inst


def tipo_sil(x):
    t = x.get("titulo") or x.get("aspectos") or ""
    return "Punto de acuerdo" if re.search(r"(?i)propone[n]?:?\s*(\d\)\s*)?(exhortar|solicitar)|punto de acuerdo", t) else "Iniciativa"


sil = cargar(DATA / "sil.json", {}).get("iniciativas", [])
for x in sil:
    firm = re.findall(r"(Dip|Sen)\.\s*([^()]+?)\s*\(([^)]+)\)", x.get("presentador") or "")
    for cam, nom, par in firm:
        add(nom, "Diputados" if cam == "Dip" else "Senado", par.strip(),
            {"id": "sil-" + str(x.get("id")), "firmantes": len(firm), "fecha": x.get("fecha_presentacion", ""),
             "tipo": tipo_sil(x), "titulo": x.get("titulo") or x.get("aspectos") or "", "url": x.get("url", ""),
             "estatus": x.get("ultimo_estatus", ""), "_leyes_txt": (x.get("titulo") or "") + " " + (x.get("aspectos") or "")})

ch = cargar(DATA / "congreso-historico.json", {}).get("items", [])
for x in ch:
    if not (x.get("autor") or "").strip() or not is_relevant(x.get("titulo") or ""):
        continue
    noms = [n for n in re.split(r",|\by\b", x["autor"]) if n.strip()]
    for nom in noms:
        add(nom, "Diputados" if x.get("camara") == "DIP" else "Senado", x.get("partido") or "",
            {"id": "gac-" + str(x.get("id")), "firmantes": len(noms), "fecha": (x.get("fecha") or "")[:10],
             "tipo": "Punto de acuerdo" if x.get("tipo") == "punto_acuerdo" else "Iniciativa",
             "titulo": x.get("titulo") or "", "url": x.get("url", ""), "estatus": "", "_leyes_txt": x.get("titulo") or ""})

# mismo legislador escrito distinto en cada fuente ("Aracely" / "Aracelly")
ks = sorted(L)
for i, a in enumerate(ks):
    if a not in L:
        continue
    for b in ks[i + 1:]:
        if b in L and L[a]["camara"] == L[b]["camara"] and difflib.SequenceMatcher(None, a, b).ratio() >= 0.92:
            L[a]["instrumentos"].update(L[b]["instrumentos"])
            L[a]["partido"] = L[a]["partido"] or L[b]["partido"]
            del L[b]

# ── Acumulado previo (append-only) ──
previo = {norm(l["nombre"]): l for l in cargar(OUT, {}).get("legisladores", [])}
for k, l in previo.items():
    dest = L.get(k)
    if dest is None:
        dest = L[k] = {"nombre": l["nombre"], "camara": l["camara"], "partido": l.get("partido", ""), "instrumentos": {}}
    for i in l.get("instrumentos", []):
        if i["id"] in dest["instrumentos"]:
            # conserva las leyes ya vinculadas (p. ej. por lectura del texto completo)
            if i.get("leyes"):
                dest["instrumentos"][i["id"]]["leyes"] = i["leyes"]
            continue
        if True:
            i = dict(i)
            i["firmantes"] = FIRMAS_BANCADA if i.get("adhesion") else 1
            i["_leyes_txt"] = i.get("titulo", "")
            dest["instrumentos"][i["id"]] = i

# ── Foto oficial y entidad ──
padron = collections.defaultdict(dict)
for f in cargar(AUX / "padron-legisladores.json", []):
    padron[f["camara"]][norm(f["nombre"])] = f


def ficha(nombre, camara):
    k = norm(nombre); pool = padron[camara]
    if k in pool:
        return pool[k]
    m = difflib.get_close_matches(k, list(pool), n=1, cutoff=0.85)
    if m:
        return pool[m[0]]
    ws = set(k.split())
    best = max(pool, key=lambda p: len(ws & set(p.split())), default=None)
    if best and (len(ws & set(best.split())) >= 3 or (len(ws) >= 2 and ws <= set(best.split()))):
        return pool[best]
    return {}


out = []
for k, p in L.items():
    ins = sorted(p["instrumentos"].values(), key=lambda i: i.get("fecha", ""), reverse=True)
    leyes = collections.Counter()
    limpios = []
    for i in ins:
        adh = i.get("firmantes", 1) >= FIRMAS_BANCADA
        obj = i.get("leyes") or leyes_de(i.get("_leyes_txt", ""))
        if not adh:
            leyes.update(n for n in obj if n in EN_SCOPE)
        limpios.append({"id": i["id"], "fecha": i.get("fecha", ""), "tipo": i.get("tipo", ""), "titulo": i.get("titulo", ""),
                        "url": i.get("url", ""), "estatus": i.get("estatus", ""), "adhesion": adh, "leyes": obj,
                        "en_compendio": any(n in EN_SCOPE for n in obj)})
    propios = [i for i in limpios if not i["adhesion"]]
    if not propios:
        continue
    f = ficha(p["nombre"], p["camara"])
    out.append({"nombre": p["nombre"], "camara": p["camara"], "partido": p["partido"], "entidad": f.get("entidad", ""),
                "foto": f.get("foto", ""), "ficha_url": f.get("ficha_url", ""),
                "total": len(propios), "iniciativas": sum(i["tipo"] == "Iniciativa" for i in propios),
                "puntos_acuerdo": sum(i["tipo"] == "Punto de acuerdo" for i in propios),
                "adhesiones": len(limpios) - len(propios), "ultimo": limpios[0]["fecha"] if limpios else "",
                "leyes": [{"ley": n, "n": c} for n, c in leyes.most_common(6)], "instrumentos": limpios})
out.sort(key=lambda r: (-r["total"], r["nombre"]))
for i, r in enumerate(out):
    r["id"] = "lg" + str(i)

ahora = datetime.now(timezone(timedelta(hours=-6))).strftime("%Y-%m-%dT%H:%M:%S-06:00")
res = {"_meta": {"actualizado": ahora,
                 "criterio": "Legisladores federales con al menos 1 iniciativa o punto de acuerdo PROPIO en temas GEMI. "
                             "Exhortos firmados por 5 o más legisladores cuentan como firma de bancada, no como autoría.",
                 "fuentes": "SIL (Gobernación), Gaceta Parlamentaria de Diputados y Gaceta del Senado; fotos de SITL y senado.gob.mx",
                 "total": len(out)},
       "legisladores": out}
with open(OUT, "w", encoding="utf-8") as f:
    json.dump(res, f, ensure_ascii=False, separators=(",", ":"))
print(f"Legisladores GEMI: {len(out)} | Diputados {sum(r['camara']=='Diputados' for r in out)} | Senado {sum(r['camara']=='Senado' for r in out)}"
      f" | con foto {sum(bool(r['foto']) for r in out)} | con leyes del compendio {sum(bool(r['leyes']) for r in out)}")
