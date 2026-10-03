#!/usr/bin/env python3
"""
SCOPE — Finanzas sostenibles e impuestos ambientales.

Los medios que lee scraper.py (portadas de El Financiero, Expansión, etc.) casi no
etiquetan estas notas con palabras ambientales, así que nunca entraban a Scope y el
Radar marcaba cero en "Finanzas Sostenibles" e "Impuestos Ambientales". Aquí se
buscan directo en Google News RSS (mismo patrón que scraper_conagua.py) y se fusionan
en data/noticias.json. Solo pasan notas cuyo TÍTULO cruza la taxonomía del tema.
"""
import sys, json, time, urllib.parse
from datetime import datetime, timezone
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import warnings
warnings.filterwarnings("ignore")
import feedparser

sys.path.insert(0, str(Path(__file__).resolve().parent))
from scraper import (es_ruido, detect_categories, detect_state, make_id,
                     normalize, parse_date_str, CAT_LABEL)

ROOT        = Path(__file__).resolve().parent.parent
OUTPUT_FILE = ROOT / "data" / "noticias.json"
MAX_TOTAL   = 600
MAX_NEW     = 30            # tope por corrida para cada tema: complementa el feed, no lo inunda

TEMAS = {
    "finanzas_sostenibles": [
        '"finanzas sostenibles" OR "finanzas verdes" OR "finanzas climáticas" México',
        '"bonos verdes" OR "bono verde" OR "bonos sostenibles" OR "bonos sustentables" México',
        '"taxonomía sostenible" OR "taxonomía sustentable" OR greenwashing México',
        '"créditos sostenibles" OR "financiamiento verde" OR "financiamiento sostenible" México',
        '"mercado de carbono" OR "bonos de carbono" OR "créditos de carbono" México',
        '"criterios ASG" OR "criterios ESG" OR "IFRS S1" OR "IFRS S2" México',
    ],
    "fiscal_ambiental": [
        '"impuestos ambientales" OR "impuesto ambiental" México',
        '"impuestos verdes" OR "impuesto verde" OR "impuestos ecológicos" OR "impuesto ecológico"',
        '"impuesto al carbono" OR "impuestos al carbono" OR "IEPS al carbono" México',
        '"impuesto a la extracción de materiales" OR "impuesto por remediación" OR "impuesto a la emisión de gases"',
        '"Ley Federal de Derechos" (agua OR "aguas nacionales" OR descargas OR ambiental OR minería)',
    ],
}
# Solo México: el título debe traer un marcador mexicano o venir de un medio mexicano,
# y no mencionar otro país/bloque (Google News mezcla Perú, UE, España, etc.).
_MX_TITULO = ("mexic", "cdmx", "ciudad de mexico", "hacienda", "shcp", "banxico", "bancomext",
              "nafin", "semarnat", "cnbv", "bmv", "biva", "sheinbaum", "senado", "diputados",
              "mdp", "mmdp", "femsa", "cemex", "pemex", "cfe", "nuevo leon", "jalisco", "durango",
              "coahuila", "zacatecas", "tamaulipas", "queretaro", "guanajuato", "yucatan",
              "estado de mexico", "edomex", "monterrey", "sonora", "chihuahua", "puebla", "veracruz")
_MX_MEDIO = ("el economista", "el financiero", "expansion", "reforma", "el norte", "milenio",
             "la jornada", "el universal", "excelsior", "forbes mexico", "el sol de mexico",
             "elsoldemexico", "telediario", "la razon de mexico", "expoknews", "el siglo de torreon",
             "cluster industrial", "energia hoy", "obras", "adn40", "animal politico", "proceso",
             "infobae mexico", "mundo ejecutivo", "valor-compartido", "transporteinformativo", ".mx")
_EXTRANJERO = ("peru", "bolivia", "argentina", "chile", "colombia", "ecuador", "brasil", "uruguay",
               "paraguay", "venezuela", "espana", "union europea", "europa", "italia", "francia",
               "alemania", "misiones", "amazonia", "estados unidos", "canada", "china", "india")


def es_mexico(titulo, fuente):
    t, f = normalize(titulo), normalize(fuente)
    if any(x in t for x in _EXTRANJERO) and "mexic" not in t:
        return False
    return any(x in t for x in _MX_TITULO) or any(x in f for x in _MX_MEDIO)


# La LFD solo cuenta si el título trae un ancla ambiental (también cubre visas, pasaportes, etc.)
_LFD_ANCLA = ("agua", "descarga", "ambient", "miner", "ecolog", "residuo", "carbono")


def gnews_url(q):
    return ("https://news.google.com/rss/search?q="
            + urllib.parse.quote(q + " when:30d") + "&hl=es-419&gl=MX&ceid=MX:es-419")


def clean_title(t, src):
    t = (t or "").strip()
    if src and t.endswith(" - " + src):
        t = t[: -(len(src) + 3)].strip()
    return t


def load_existing():
    if not OUTPUT_FILE.exists():
        return []
    try:
        with open(OUTPUT_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def scrape_tema(tema, queries, seen):
    nuevos = []
    for q in queries:
        try:
            feed = feedparser.parse(gnews_url(q))
        except Exception as e:
            print(f"  ERROR feed {q[:40]!r}: {str(e)[:80]}")
            continue
        add = 0
        for e in feed.entries:
            src = e.source.title if hasattr(e, "source") and hasattr(e.source, "title") else ""
            titulo = clean_title(e.get("title", ""), src)
            if len(titulo) < 20:
                continue
            tnorm = normalize(titulo)
            cats = detect_categories(titulo, "")
            lfd = "ley federal de derechos" in tnorm and any(a in tnorm for a in _LFD_ANCLA)
            if tema not in cats and not (tema == "fiscal_ambiental" and lfd):
                continue
            if not es_mexico(titulo, src) or es_ruido(titulo, "", len(cats)):
                continue
            aid = make_id(titulo, "GNews-" + tema)
            if aid in seen:
                continue
            seen.add(aid)
            fecha = parse_date_str(e.get("published", "")) or \
                datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            nuevos.append({
                "id": aid,
                "titulo": titulo,
                "url": e.get("link", ""),
                "fuente": src or "Google News",
                "resumen": "",
                "fecha_publicacion": fecha,
                "categoria": tema,
                "categoria_nombre": CAT_LABEL.get(tema, tema),
                "categorias": [tema] + [c for c in cats if c != tema],
                "estado": detect_state(titulo, ""),
                "scrapeado_en": datetime.now(timezone.utc).isoformat(),
            })
            add += 1
        print(f"  [{tema}] {q[:60]!r}: +{add}")
        time.sleep(0.4)
    nuevos.sort(key=lambda x: x.get("fecha_publicacion", ""), reverse=True)
    if len(nuevos) > MAX_NEW:
        print(f"  (tope {tema}: {len(nuevos)} → {MAX_NEW} más recientes)")
        nuevos = nuevos[:MAX_NEW]
    return nuevos


def main():
    print(f"Finanzas sostenibles / impuestos ambientales — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    existing = load_existing()
    seen = {a.get("id", "") for a in existing}
    # también evita duplicar por título exacto (la misma nota puede venir de otro scraper)
    titulos = {normalize(a.get("titulo", "")) for a in existing}
    nuevos = []
    for tema, qs in TEMAS.items():
        for n in scrape_tema(tema, qs, seen):
            if normalize(n["titulo"]) not in titulos:
                titulos.add(normalize(n["titulo"]))
                nuevos.append(n)
    print(f"Nuevas: {len(nuevos)}")
    combined = sorted(nuevos + existing, key=lambda x: x.get("fecha_publicacion", ""), reverse=True)[:MAX_TOTAL]
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(combined, f, ensure_ascii=False, indent=2)
    print(f"Guardado {OUTPUT_FILE.name}  |  total {len(combined)}")


if __name__ == "__main__":
    main()
