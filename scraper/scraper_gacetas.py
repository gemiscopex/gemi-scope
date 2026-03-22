"""
SCOPE - Scraper Legislativo Federal
Adaptado de gaceta.py + gaceta_senado.py + clasificador.py originales.

Arquitectura:
  Diputados: 3 niveles (dia -> Anexos II/III -> subpaginas -> documentos)
  Senado: AJAX calendario -> paginas diarias -> secciones -> documentos

Filtros: solo iniciativas, proposiciones con punto de acuerdo, dictamenes.
Clasifica en 8 categorias SCOPE. Max 10 por camara, acumula el mes.
"""

import re
import time
import json
import math
import logging
import warnings
import argparse
import base64
import unicodedata
import urllib.request
from datetime import datetime, timedelta
from collections import Counter

import requests
from bs4 import BeautifulSoup

warnings.filterwarnings("ignore")
logging.basicConfig(level=logging.WARNING)

# ─── CATEGORIAS SCOPE ──────────────────────────────────────────────────────────

SCOPE_CATEGORIAS = {
    "energia": {
        "nombre": "Energia",
        "keywords": [
            "pemex","petroleo","hidrocarburo","refineria","fracking",
            "gasolina","huachicol","mezcla mexicana","plataforma petrolera",
            "toma clandestina","octavio romero","barriles",
            "cfe","electricidad","apagon","corte de luz","falla electrica",
            "generacion electrica","subsidio energetico","tarifa domestica",
            "tarifas electricas",
            "energia limpia","eolica","solar","transicion energetica","renovable",
            "litio","gas natural","gas lp","gasoducto","mineria",
            "concesion minera","reforma energetica","soberania energetica",
            "secretaria de energia","rocio nahle","industria electrica",
        ],
    },
    "agua": {
        "nombre": "Agua",
        "keywords": [
            "agua","acuifero","cuenca","conagua","ley de aguas",
            "aguas nacionales","sequia hidrica","tratamiento de agua",
            "saneamiento","agua potable","alcantarillado",
            "riego","distrito de riego","zona de veda","acuacultura",
            "gestion hidrica","infraestructura hidraulica","contaminacion del agua",
        ],
    },
    "medio_ambiente": {
        "nombre": "Medio Ambiente",
        "keywords": [
            "medio ambiente","lgeepa","semarnat","ecologia",
            "proteccion ambiental","equilibrio ecologico",
            "area natural protegida","biodiversidad","vida silvestre","lgvs",
            "forestal","lgdfs","deforestacion","tala ilegal","incendio forestal",
            "contaminacion","impacto ambiental","manifestacion de impacto",
            "ordenamiento ecologico","profepa","auditoria ambiental",
            "responsabilidad ambiental","manglar","humedal","arrecife",
        ],
    },
    "residuos_circular": {
        "nombre": "Residuos / Economia Circular",
        "keywords": [
            "residuos","lgpgir","plasticos","reciclaje","reciclado",
            "relleno sanitario","desechos","residuo peligroso",
            "residuo solido","manejo de residuos","economia circular",
            "ecodiseno","responsabilidad extendida","productor responsable",
            "unicel","poliestireno","bolsa plastica","popote","envase",
        ],
    },
    "cambio_climatico": {
        "nombre": "Cambio Climatico",
        "keywords": [
            "cambio climatico","lgcc","gases de efecto invernadero",
            "gei","carbono","huella de carbono","net zero",
            "emisiones de co2","reduccion de emisiones","adaptacion climatica",
            "mitigacion","compromisos climaticos","acuerdo de paris",
            "cop","ipcc","crisis climatica",
        ],
    },
    "agro_rural": {
        "nombre": "Agro y Desarrollo Rural",
        "keywords": [
            "sader","segalmex","agricultura","cosecha","fertilizante",
            "glifosato","maiz","maiz transgenico","transgenico",
            "importacion de maiz","precio del maiz","precio del frijol",
            "sequia agricola","soberania alimentaria","tortilla",
            "temporal agricola","perdida de cosecha","plaga","granizada",
            "helada","semilla","campo mexicano","desarrollo rural",
            "ganaderia","ganado","pesca","zona pesquera","veda pesquera",
        ],
    },
    "impuestos_ambientales": {
        "nombre": "Impuestos Ambientales",
        "keywords": [
            "impuesto ambiental","impuesto verde","impuesto ecologico",
            "impuesto sobre emisiones","cuota ambiental","ieps combustibles",
            "derechos mineros","derecho de extraccion","impuesto al carbono",
            "bono de carbono","mercado de carbono","ley federal de derechos",
            "lfd","derechos de agua","pago por servicios ambientales",
        ],
    },
    "industria_quimica": {
        "nombre": "Industria Quimica",
        "keywords": [
            "industria quimica","aniq","petroquimica","planta quimica",
            "sustancia quimica","solvente","aditivo","registro sanitario",
            "norma oficial mexicana","nom","cofepris","licencia ambiental",
            "manufactura",
        ],
    },
}

TIPOS_VALIDOS = re.compile(
    r"iniciativa|proposicion|proposicion|punto\s+de\s+acuerdo|proyecto\s+de\s+decreto|"
    r"proyecto\s+de\s+ley|dictamen|que\s+reforma|que\s+adiciona|"
    r"que\s+expide|que\s+abroga|que\s+modifica|que\s+deroga",
    re.IGNORECASE,
)

TIPOS_EXCLUIR = re.compile(
    r"convocatoria|reunion\s+de\s+comision|junta\s+directiva|"
    r"sesion\s+ordinaria\s+de\s+la\s+comision|informe\s+de\s+actividades|"
    r"citatorio|acta\s+de\s+la\s+reunion|invitacion|programa\s+de\s+trabajo",
    re.IGNORECASE,
)

SENALES_LEG = [
    "iniciativa", "proyecto de decreto", "punto de acuerdo", "dictamen",
    "reforma constitucional", "proposicion con punto de acuerdo",
    "gaceta parlamentaria",
]

STOPWORDS = {
    "de","la","que","el","en","y","a","los","del","se","las","por","un",
    "para","con","no","una","su","al","lo","como","mas","pero","sus","le",
    "ya","o","este","porque","esta","entre","cuando","muy","sin","sobre",
    "tambien","me","hasta","hay","donde","quien","desde","todo","nos",
    "durante","todos","uno","les","ni","contra","otros","ese","eso","ante",
    "ellos","e","esto","antes","algunos","unos","yo","otro",
    "fue","ser","es","son","ha","han","era","sera","sido",
}


def _sin_acentos(texto):
    if not texto:
        return ""
    nfd = unicodedata.normalize("NFD", texto.lower())
    return "".join(c for c in nfd if unicodedata.category(c) != "Mn" or c == "\u0303")


def _norm(texto):
    t = re.sub(r"https?://\S+", "", _sin_acentos(texto))
    t = re.sub(r"[^\w\s]", " ", t)
    return [x for x in t.split() if x not in STOPWORDS and len(x) > 2]


def _tf(tokens):
    c = Counter(tokens)
    total = len(tokens) or 1
    return {k: v / total for k, v in c.items()}


def clasificar(titulo, resumen=""):
    texto = _sin_acentos(f"{titulo} {resumen}")
    hits_leg = sum(1 for s in SENALES_LEG if s in texto)
    tf_t = _tf(_norm(titulo))
    tf_r = _tf(_norm(resumen))
    scores = {}
    for key, cat in SCOPE_CATEGORIAS.items():
        score = 0.0
        for kw in cat["keywords"]:
            kl = kw.lower()
            if kl in texto:
                score += 2.5 if kl in _sin_acentos(titulo) else 1.0
            else:
                for tok in _norm(kw):
                    score += tf_t.get(tok, 0) * 3.0 + tf_r.get(tok, 0) * 1.0
        if score > 0:
            score = score / math.sqrt(len(cat["keywords"]))
            if hits_leg > 0 and score > 0.1:
                score *= min(1.0 + hits_leg * 0.35, 2.5)
            scores[key] = round(score, 4)
    if not scores:
        return None, None
    best = max(scores, key=scores.get)
    return best, SCOPE_CATEGORIAS[best]["nombre"]


def es_relevante(titulo, resumen=""):
    cat, _ = clasificar(titulo, resumen)
    return cat is not None


def es_tipo_valido(titulo):
    if TIPOS_EXCLUIR.search(titulo):
        return False
    return bool(TIPOS_VALIDOS.search(titulo))


# ─── HTTP ──────────────────────────────────────────────────────────────────────

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "es-MX,es;q=0.9,en;q=0.8",
}
_session = None


def get_session():
    global _session
    if _session is None:
        _session = requests.Session()
        _session.headers.update(HEADERS)
    return _session


def fetch(url, verify=True):
    try:
        r = get_session().get(url, timeout=25, verify=verify)
        if r.status_code == 200 and len(r.text) > 200:
            return r.text
    except Exception:
        pass
    return None


# ─── DIPUTADOS — 3 niveles ─────────────────────────────────────────────────────

BASE_DIP = "https://gaceta.diputados.gob.mx"
MESES_URL = {
    1: "ene", 2: "feb", 3: "mar", 4: "abr", 5: "may", 6: "jun",
    7: "jul", 8: "ago", 9: "sep", 10: "oct", 11: "nov", 12: "dic",
}
ANEXOS_SCOPE = {"II": "iniciativa", "III": "proposicion"}

TIPO_RE = {
    "iniciativa": re.compile(r"iniciativa|que\s+reforma|que\s+adiciona|que\s+expide|que\s+abroga", re.IGNORECASE),
    "proposicion": re.compile(r"proposicion|proposicion|punto\s+de\s+acuerdo", re.IGNORECASE),
}


def _url_dia_dip(fecha):
    s = fecha.strftime("%Y%m%d")
    return f"{BASE_DIP}/PDF/66/{fecha.year}/{MESES_URL[fecha.month]}/{s}/{s}.html"


def _descubrir_anexos(html):
    soup = BeautifulSoup(html, "html.parser")
    anexos = []
    for a in soup.find_all("a", href=True):
        m = re.search(r"(\d{8})-([IVX]+)\.html", a["href"], re.IGNORECASE)
        if m and m.group(2) in ANEXOS_SCOPE:
            url = a["href"] if a["href"].startswith("http") else f"{BASE_DIP}{a['href']}"
            if (m.group(2), url) not in anexos:
                anexos.append((m.group(2), url))
    return anexos


def _descubrir_subpaginas(html, base_url):
    soup = BeautifulSoup(html, "html.parser")
    subs = []
    for a in soup.find_all("a", href=True):
        if re.search(r"\d{8}-[IVX]+-\d+\.html", a["href"], re.IGNORECASE):
            url = a["href"] if a["href"].startswith("http") else f"{BASE_DIP}/{a['href']}"
            if url not in subs:
                subs.append(url)
    return subs if subs else [base_url]


def _extraer_docs_pagina(html, tipo_doc, fecha_str):
    soup = BeautifulSoup(html, "html.parser")
    docs = []
    seen = set()
    for a in soup.find_all("a", href=True):
        titulo = a.get_text(strip=True)
        if not titulo or len(titulo) < 15:
            continue
        tk = titulo[:80]
        if tk in seen:
            continue
        if not es_tipo_valido(titulo):
            continue
        if not es_relevante(titulo):
            continue
        seen.add(tk)
        tipo_real = tipo_doc
        for t, pat in TIPO_RE.items():
            if pat.search(titulo):
                tipo_real = t
                break
        href = a["href"]
        url = href if href.startswith("http") else f"{BASE_DIP}/{href}"
        _, cat = clasificar(titulo)
        docs.append({
            "titulo": titulo[:400],
            "tipo": tipo_real,
            "fecha": fecha_str,
            "url": url,
            "categoria": cat or "General",
            "camara": "Diputados",
        })
    return docs


def scrape_diputados(dias=30):
    resultados = []
    hoy = datetime.now()
    fechas = [hoy - timedelta(days=i) for i in range(dias) if (hoy - timedelta(days=i)).weekday() < 5]
    print(f"  Revisando {len(fechas)} dias habiles en Diputados...")
    for fecha in fechas:
        fecha_str = fecha.strftime("%Y-%m-%d")
        html_dia = fetch(_url_dia_dip(fecha))
        if not html_dia:
            continue
        time.sleep(0.6)
        anexos = _descubrir_anexos(html_dia)
        if not anexos:
            resultados.extend(_extraer_docs_pagina(html_dia, "iniciativa", fecha_str))
            continue
        for anexo_num, anexo_url in anexos:
            tipo_doc = ANEXOS_SCOPE[anexo_num]
            html_anexo = fetch(anexo_url)
            if not html_anexo:
                continue
            time.sleep(0.4)
            subs = _descubrir_subpaginas(html_anexo, anexo_url)
            for sub_url in subs:
                html_sub = html_anexo if sub_url == anexo_url else fetch(sub_url)
                if not html_sub:
                    continue
                time.sleep(0.3)
                resultados.extend(_extraer_docs_pagina(html_sub, tipo_doc, fecha_str))
    seen = set()
    dedup = []
    for d in resultados:
        k = d["titulo"][:80]
        if k not in seen:
            seen.add(k)
            dedup.append(d)
    dedup.sort(key=lambda x: x["fecha"], reverse=True)
    print(f"  [Diputados] {len(dedup)} iniciativas/proposiciones SCOPE encontradas")
    return dedup[:10]


# ─── SENADO — AJAX calendario ──────────────────────────────────────────────────

BASE_SEN = "https://www.senado.gob.mx"
LEG_SEN = "66"

SECCIONES_SENADO = {
    "iniciativas": "iniciativa",
    "proposiciones": "proposicion",
    "dictamenes": "dictamen",
    "poder ejecutivo federal": "iniciativa",
}


def _gacetas_senado_mes(year, month):
    ajax = f"{BASE_SEN}/{LEG_SEN}/app/gaceta/functions/calendarioMes.php"
    try:
        r = get_session().get(ajax, params={"action": "ajax", "anio": year, "mes": month, "dia": 1},
                              timeout=25, verify=False)
        if r.status_code != 200 or len(r.text) < 50:
            return []
    except Exception:
        return []
    gacetas = []
    for m in re.finditer(r"gaceta_del_senado/(\d{4})_(\d{2})_(\d{2})/(\d+)", r.text):
        y, mo, d, gid = m.groups()
        fecha = f"{y}-{mo}-{d}"
        url = f"{BASE_SEN}/{LEG_SEN}/gaceta_del_senado/{y}_{mo}_{d}/{gid}"
        if not any(g["fecha"] == fecha for g in gacetas):
            gacetas.append({"fecha": fecha, "url": url})
    return gacetas


def _tipo_titulo(titulo):
    t = titulo.lower()
    if re.search(r"iniciativa|que\s+reforma|proyecto\s+de\s+decreto", t):
        return "iniciativa"
    if re.search(r"proposicion|punto\s+de\s+acuerdo", t):
        return "proposicion"
    if re.search(r"dictamen", t):
        return "dictamen"
    return "iniciativa"


def _parsear_gaceta_senado(html, fecha):
    soup = BeautifulSoup(html, "html.parser")
    docs = []

    # Mapa de secciones desde el SUMARIO
    seccion_map = {}
    for a in soup.find_all("a", href=lambda h: h and h.startswith("#") and len(h) > 1):
        aid = a["href"][1:]
        txt = a.get_text(strip=True)
        if txt and len(txt) > 3 and not txt.isdigit():
            seccion_map[aid] = txt

    html_str = str(soup)
    anchor_ids = list(seccion_map.keys())

    for i, anchor_id in enumerate(anchor_ids):
        nombre_sec = seccion_map[anchor_id]
        nombre_lower = nombre_sec.lower()
        tipo_doc = None
        for sec_key, sec_tipo in SECCIONES_SENADO.items():
            if sec_key in nombre_lower:
                tipo_doc = sec_tipo
                break
        if tipo_doc is None:
            continue

        start = html_str.find(f'name="{anchor_id}"')
        if start < 0:
            continue
        next_id = anchor_ids[i + 1] if i + 1 < len(anchor_ids) else None
        end = html_str.find(f'name="{next_id}"', start) if next_id else len(html_str)
        if end < 0:
            end = len(html_str)

        sec_soup = BeautifulSoup(html_str[start:end], "html.parser")
        seen = set()
        for a in sec_soup.find_all("a", href=re.compile(r"gaceta_del_senado/documento/\d+")):
            m = re.search(r"documento/(\d+)", a["href"])
            if not m:
                continue
            doc_id = m.group(1)
            if doc_id in seen:
                continue
            titulo = a.get_text(strip=True)
            if not titulo or len(titulo) < 15:
                continue
            if TIPOS_EXCLUIR.search(titulo):
                continue
            if not es_relevante(titulo):
                continue
            seen.add(doc_id)
            _, cat = clasificar(titulo)
            docs.append({
                "titulo": titulo[:400],
                "tipo": tipo_doc,
                "fecha": fecha,
                "url": f"{BASE_SEN}/{LEG_SEN}/gaceta_del_senado/documento/{doc_id}",
                "categoria": cat or "General",
                "camara": "Senado",
            })

    # Fallback: sin sumario
    if not docs:
        seen = set()
        for a in soup.find_all("a", href=re.compile(r"gaceta_del_senado/documento/\d+")):
            m = re.search(r"documento/(\d+)", a["href"])
            if not m:
                continue
            doc_id = m.group(1)
            if doc_id in seen:
                continue
            titulo = a.get_text(strip=True)
            if not titulo or len(titulo) < 15:
                continue
            if TIPOS_EXCLUIR.search(titulo):
                continue
            if not TIPOS_VALIDOS.search(titulo):
                continue
            if not es_relevante(titulo):
                continue
            seen.add(doc_id)
            _, cat = clasificar(titulo)
            docs.append({
                "titulo": titulo[:400],
                "tipo": _tipo_titulo(titulo),
                "fecha": fecha,
                "url": f"{BASE_SEN}/{LEG_SEN}/gaceta_del_senado/documento/{doc_id}",
                "categoria": cat or "General",
                "camara": "Senado",
            })
    return docs


def scrape_senado(dias=30):
    hoy = datetime.now()
    meses = {((hoy - timedelta(days=i)).year, (hoy - timedelta(days=i)).month) for i in range(dias)}
    gacetas = {}
    for year, month in meses:
        for g in _gacetas_senado_mes(year, month):
            gacetas[g["fecha"]] = g["url"]
    fecha_limite = (hoy - timedelta(days=dias)).strftime("%Y-%m-%d")
    gacetas_rango = {f: u for f, u in gacetas.items() if f >= fecha_limite}
    print(f"  Gacetas del Senado encontradas: {len(gacetas_rango)}")
    resultados = []
    for fecha in sorted(gacetas_rango.keys(), reverse=True):
        html = fetch(gacetas_rango[fecha], verify=False)
        time.sleep(1.0)
        if html:
            resultados.extend(_parsear_gaceta_senado(html, fecha))
    seen = set()
    dedup = []
    for d in resultados:
        k = d["url"]
        if k not in seen:
            seen.add(k)
            dedup.append(d)
    dedup.sort(key=lambda x: x["fecha"], reverse=True)
    print(f"  [Senado] {len(dedup)} iniciativas/proposiciones SCOPE encontradas")
    return dedup[:10]


# ─── MERGE ─────────────────────────────────────────────────────────────────────

def merge_con_existentes(nuevos_dip, nuevos_sen, json_path="data/gaceta-federal.json"):
    mes_actual = datetime.now().strftime("%Y-%m")
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            existente = json.load(f)
    except Exception:
        existente = {"diputados": [], "senado": [], "_meta": {}}

    def merge_camara(existentes, nuevos):
        del_mes = [d for d in existentes if str(d.get("fecha", "")).startswith(mes_actual)]
        urls_ex = {d["url"] for d in del_mes}
        agregados = [d for d in nuevos if d["url"] not in urls_ex]
        combinados = del_mes + agregados
        combinados.sort(key=lambda x: x["fecha"], reverse=True)
        return combinados[:10]

    return {
        "diputados": merge_camara(existente.get("diputados", []), nuevos_dip),
        "senado": merge_camara(existente.get("senado", []), nuevos_sen),
        "_meta": {
            "ultima_actualizacion": datetime.now().isoformat(),
            "mes": mes_actual,
        },
    }


# ─── GITHUB ────────────────────────────────────────────────────────────────────

def subir_github(token, contenido_bytes, path_repo, mensaje):
    api = f"https://api.github.com/repos/gemiscopex/gemi-scope/contents/{path_repo}"
    headers_api = {"Authorization": f"token {token}", "Content-Type": "application/json"}
    try:
        req = urllib.request.Request(api, headers={"Authorization": f"token {token}"})
        with urllib.request.urlopen(req) as r:
            sha = json.loads(r.read())["sha"]
    except Exception:
        sha = None
    payload = {"message": mensaje, "content": base64.b64encode(contenido_bytes).decode()}
    if sha:
        payload["sha"] = sha
    req2 = urllib.request.Request(api, data=json.dumps(payload).encode(), headers=headers_api, method="PUT")
    try:
        with urllib.request.urlopen(req2) as r:
            return r.status
    except urllib.error.HTTPError as e:
        print(f"  Error GitHub: {e.code} {e.reason}")
        return e.code


# ─── MAIN ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="SCOPE Scraper Legislativo Federal")
    parser.add_argument("--token", required=True, help="GitHub token")
    parser.add_argument("--dias", type=int, default=30, help="Dias a revisar (default: 30)")
    parser.add_argument("--no-upload", action="store_true", help="No subir a GitHub")
    args = parser.parse_args()

    mes = datetime.now().strftime("%Y-%m")
    print(f"\n{'-'*45}")
    print(f"  SCOPE - Scraper Legislativo Federal")
    print(f"  Mes: {mes}  |  Ventana: {args.dias} dias")
    print(f"{'-'*45}\n")

    print("[1/2] Scraping Camara de Diputados...")
    dip = scrape_diputados(dias=args.dias)

    print("\n[2/2] Scraping Senado de la Republica...")
    sen = scrape_senado(dias=args.dias)

    resultado = merge_con_existentes(dip, sen)

    json_path = "data/gaceta-federal.json"
    contenido = json.dumps(resultado, ensure_ascii=False, indent=2).encode("utf-8")
    with open(json_path, "wb") as f:
        f.write(contenido)

    n_dip = len(resultado["diputados"])
    n_sen = len(resultado["senado"])
    print(f"\nGuardado en {json_path}")
    print(f"   Diputados: {n_dip} iniciativas")
    print(f"   Senado:    {n_sen} iniciativas")

    if not args.no_upload:
        print("\nSubiendo a GitHub Pages...")
        status = subir_github(
            args.token, contenido, "data/gaceta-federal.json",
            f"Gacetas SCOPE {mes}: {n_dip} Dip + {n_sen} Sen",
        )
        if status in (200, 201):
            print("OK - Subido a GitHub (gemiscopex/gemi-scope)")
        else:
            print(f"Status: {status}")

    print("\n--- Detalle ---")
    for d in resultado["diputados"]:
        print(f"  [Dip/{d.get('tipo','?')}] [{d.get('categoria','?')}] {d['titulo'][:80]}")
    for d in resultado["senado"]:
        print(f"  [Sen/{d.get('tipo','?')}] [{d.get('categoria','?')}] {d['titulo'][:80]}")
    print()


if __name__ == "__main__":
    main()
