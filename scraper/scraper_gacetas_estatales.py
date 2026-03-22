"""
SCOPE - Scraper de Gacetas Legislativas Estatales
Estrategia de dos niveles:
  Nivel 1 (rápido):  requests + BeautifulSoup para portales HTML estáticos
  Nivel 2 (completo): Playwright (Chromium headless) para portales con JavaScript

Cubre los 32 congresos estatales de México.
Salida: data/gaceta-estatal.json
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
import csv, io
import urllib.request
from datetime import datetime, timedelta
from collections import Counter

import requests
from bs4 import BeautifulSoup

warnings.filterwarnings("ignore")
logging.basicConfig(level=logging.WARNING)

# ─── DIRECTORIO DE ESTADOS ─────────────────────────────────────────────────────

ESTADOS = {
    "Aguascalientes": {
        "iniciativas": "https://congresoags.gob.mx/agenda_legislativa/iniciativas",
        "periodico": "https://eservicios2.aguascalientes.gob.mx/periodicooficial/",
        "js": True,
    },
    "Baja California": {
        "iniciativas": "https://www.congresobc.gob.mx/TrabajoLegislativo/Iniciativas",
        "periodico": "https://periodicooficial.ebajacalifornia.gob.mx/oficial/inicioConsulta.jsp",
        "js": True,
    },
    "Baja California Sur": {
        "iniciativas": "https://www.cbcs.gob.mx/index.php/iniciativas-ley-pes",
        "periodico": "https://finanzas.bcs.gob.mx/boletines-oficiales/",
        "js": False,
    },
    "Campeche": {
        "iniciativas": "https://www.congresocam.gob.mx",
        "periodico": "http://periodicooficial.campeche.gob.mx/sipoec/public/",
        "js": True,
    },
    "Chiapas": {
        "iniciativas": "https://www.congresochiapas.gob.mx/new/Info-Parlamentaria/iniciativas/",
        "periodico": "https://www.sgg.chiapas.gob.mx/periodico/",
        "js": True,
    },
    "Chihuahua": {
        "iniciativas": "https://www.congresochihuahua.gob.mx/biblioteca/iniciativas/",
        "periodico": "https://chihuahua.gob.mx/periodicooficial/buscador",
        "js": True,
    },
    "Ciudad de México": {
        "iniciativas": "https://www.congresocdmx.gob.mx/iniciativas-213-6.html",
        "iniciativas_alt": "https://ciudadana.congresocdmx.gob.mx/Iniciativa/iniciativas",
        "periodico": "https://consejeria.cdmx.gob.mx/gaceta-oficial",
        "js": True,
    },
    "Coahuila": {
        "iniciativas": "https://www.congresocoahuila.gob.mx/portal/iniciativas/",
        "periodico": "https://periodico.segobcoahuila.gob.mx/",
        "js": True,
    },
    "Colima": {
        "iniciativas": "https://congresocol.gob.mx/web/www/",
        "periodico": "https://periodicooficial.col.gob.mx/",
        "js": False,
    },
    "Durango": {
        "iniciativas": "https://congresodurango.gob.mx/",
        "periodico": "https://periodicooficial.durango.gob.mx/",
        "js": False,
    },
    "México": {
        "iniciativas": "https://legislacion.congresoedomex.gob.mx/asuntosparlamentarios/iniciativas",
        "periodico": "https://legislacion.edomex.gob.mx/ve_periodico_oficial",
        "js": True,
    },
    "Guanajuato": {
        "iniciativas": "https://www.congresogto.gob.mx/gaceta/iniciativas",
        "periodico": "https://periodico.guanajuato.gob.mx/",
        "js": False,
    },
    "Guerrero": {
        "iniciativas": "https://congresogro.gob.mx/",
        "periodico": "https://periodicooficial.guerrero.gob.mx/",
        "js": True,
    },
    "Hidalgo": {
        "iniciativas": "https://www.congreso-hidalgo.gob.mx/",
        "periodico": "https://periodico.hidalgo.gob.mx/",
        "js": True,
    },
    "Jalisco": {
        "iniciativas": "https://www.congresojal.gob.mx/",
        "periodico": "https://periodicooficial.jalisco.gob.mx/",
        "js": True,
    },
    "Michoacán": {
        "iniciativas": "https://congresomich.site/iniciativas/",
        "periodico": "https://periodicooficial.michoacan.gob.mx/",
        "js": True,
    },
    "Morelos": {
        "iniciativas": "https://congresomorelos.gob.mx/category/iniciativas-legislativas/",
        "periodico": "https://periodico.morelos.gob.mx/",
        "js": False,
    },
    "Nayarit": {
        "iniciativas": "https://procesolegislativo.congresonayarit.gob.mx/iniciativas/",
        "periodico": "https://periodicooficial.nayarit.gob.mx/",
        "js": True,
    },
    "Nuevo León": {
        "iniciativas": "https://www.hcnl.gob.mx/trabajo_legislativo/iniciativas/",
        "periodico": "https://sistec.nl.gob.mx/Transparencia_2015_LYPOE/Acciones/PeriodicoOficial.aspx",
        "js": True,
    },
    "Oaxaca": {
        "iniciativas": "https://www.congresooaxaca.gob.mx/",
        "periodico": "https://periodicooficial.oaxaca.gob.mx/",
        "js": True,
    },
    "Puebla": {
        "iniciativas": "https://micrositios.congresopuebla.gob.mx/buscadores/iniciativas/index.php",
        "periodico": "https://periodicooficial.puebla.gob.mx/",
        "js": False,
    },
    "Querétaro": {
        "iniciativas": "http://legislaturaqueretaro.gob.mx/iniciativas/",
        "periodico": "https://lasombradearteaga.segobqueretaro.gob.mx/",
        "js": True,
    },
    "Quintana Roo": {
        "iniciativas": "https://www.congresoqroo.gob.mx/iniciativas/",
        "periodico": "http://po.segob.qroo.gob.mx/sitiopo/",
        "js": False,
    },
    "San Luis Potosí": {
        "iniciativas": "https://congresosanluis.gob.mx/trabajo/trabajo-legislativo/iniciativas",
        "periodico": "https://periodicooficial.slp.gob.mx/",
        "js": True,
    },
    "Sinaloa": {
        "iniciativas": "https://www.congresosinaloa.gob.mx/iniciativas/",
        "puntos_acuerdo": "https://www.congresosinaloa.gob.mx/puntos-de-acuerdo/",
        "periodico": "https://iip.congresosinaloa.gob.mx/poes.html",
        "js": True,
    },
    "Sonora": {
        "iniciativas": "https://congresoson.gob.mx/iniciativas",
        "periodico": "https://boletinoficial.sonora.gob.mx/",
        "js": True,
    },
    "Tabasco": {
        "iniciativas": "https://congresotabasco.gob.mx/iniciativas/",
        "puntos_acuerdo": "https://congresotabasco.gob.mx/puntos-de-acuerdo/",
        "gaceta_parl": "https://congresotabasco.gob.mx/gaceta-legislativa/",
        "periodico": "https://tabasco.gob.mx/PeriodicoOficial",
        "js": False,
    },
    "Tamaulipas": {
        "iniciativas": "https://www.congresotamaulipas.gob.mx/Parlamentario/Archivos/Iniciativas/",
        "periodico": "https://po.tamaulipas.gob.mx/",
        "js": True,
    },
    "Tlaxcala": {
        "iniciativas": "https://congresodetlaxcala.gob.mx/iniciativas/",
        "gaceta_parl": "https://congresodetlaxcala.gob.mx/gacetas-parlamentarias/",
        "periodico": "https://periodico.tlaxcala.gob.mx/",
        "js": False,
    },
    "Veracruz": {
        "iniciativas": "https://www.legisver.gob.mx/",
        "periodico": "https://editoraveracruz.gob.mx/",
        "js": True,
    },
    "Yucatán": {
        "iniciativas": "https://www.congresoyucatan.gob.mx/gaceta/iniciativas",
        "periodico": "https://www.yucatan.gob.mx/gobierno/diario_oficial.php",
        "js": True,
    },
    "Zacatecas": {
        "iniciativas": "https://www.congresozac.gob.mx/64/gaceta",
        "periodico": "https://periodico.zacatecas.gob.mx/",
        "js": True,
        "nota": "El /64/ es la legislatura actual; puede variar",
    },
}

# ─── CLASIFICADOR SCOPE ─────────────────────────────────────────────────────────

SCOPE_CATEGORIAS = {
    "energia": {
        "nombre": "Energia",
        "keywords": [
            "pemex","petroleo","hidrocarburo","refineria","fracking",
            "gasolina","huachicol","cfe","electricidad","apagon",
            "generacion electrica","subsidio energetico","tarifas electricas",
            "energia limpia","eolica","solar","transicion energetica","renovable",
            "litio","gas natural","gas lp","gasoducto","mineria",
            "concesion minera","reforma energetica","soberania energetica",
            "secretaria de energia","industria electrica",
        ],
    },
    "agua": {
        "nombre": "Agua",
        "keywords": [
            "agua","acuifero","cuenca","conagua","ley de aguas",
            "aguas nacionales","sequia","tratamiento de agua",
            "saneamiento","agua potable","alcantarillado",
            "riego","distrito de riego","acuacultura",
            "gestion hidrica","contaminacion del agua","cuerpo de agua",
        ],
    },
    "medio_ambiente": {
        "nombre": "Medio Ambiente",
        "keywords": [
            "medio ambiente","lgeepa","semarnat","ecologia",
            "proteccion ambiental","equilibrio ecologico",
            "area natural protegida","biodiversidad","vida silvestre",
            "forestal","deforestacion","tala ilegal","incendio forestal",
            "contaminacion","impacto ambiental","ordenamiento ecologico",
            "profepa","auditoria ambiental","manglar","humedal","arrecife",
        ],
    },
    "residuos_circular": {
        "nombre": "Residuos / Economia Circular",
        "keywords": [
            "residuos","plasticos","reciclaje","reciclado",
            "relleno sanitario","residuo peligroso","residuo solido",
            "manejo de residuos","economia circular","ecodiseno",
            "responsabilidad extendida","unicel","poliestireno",
            "bolsa plastica","popote","envase",
        ],
    },
    "cambio_climatico": {
        "nombre": "Cambio Climatico",
        "keywords": [
            "cambio climatico","gases de efecto invernadero",
            "gei","carbono","huella de carbono","net zero",
            "emisiones de co2","reduccion de emisiones","adaptacion climatica",
            "mitigacion","compromisos climaticos","acuerdo de paris",
        ],
    },
    "agro_rural": {
        "nombre": "Agro y Desarrollo Rural",
        "keywords": [
            "sader","segalmex","agricultura","cosecha","fertilizante",
            "glifosato","maiz","transgenico","importacion de maiz",
            "soberania alimentaria","tortilla","temporal agricola",
            "perdida de cosecha","plaga","granizada","helada","semilla",
            "campo mexicano","desarrollo rural",
            "ganaderia","ganado","pesca","zona pesquera","veda pesquera",
        ],
    },
    "impuestos_ambientales": {
        "nombre": "Impuestos Ambientales",
        "keywords": [
            "impuesto ambiental","impuesto verde","impuesto ecologico",
            "impuesto sobre emisiones","cuota ambiental","ieps combustibles",
            "derechos mineros","impuesto al carbono","bono de carbono",
            "mercado de carbono","ley federal de derechos","derechos de agua",
            "pago por servicios ambientales",
        ],
    },
    "industria_quimica": {
        "nombre": "Industria Quimica",
        "keywords": [
            "industria quimica","aniq","petroquimica","planta quimica",
            "sustancia quimica","solvente","aditivo","registro sanitario",
            "norma oficial mexicana","nom","cofepris","manufactura",
        ],
    },
}

TIPOS_VALIDOS = re.compile(
    r"iniciativa|proposicion|punto\s+de\s+acuerdo|proyecto\s+de\s+decreto|"
    r"proyecto\s+de\s+ley|dictamen|que\s+reforma|que\s+adiciona|"
    r"que\s+expide|que\s+abroga|que\s+modifica|que\s+deroga",
    re.IGNORECASE,
)

TIPOS_EXCLUIR = re.compile(
    r"convocatoria|reunion\s+de\s+comision|junta\s+directiva|"
    r"sesion\s+ordinaria\s+de\s+la\s+comision|informe\s+de\s+actividades|"
    r"citatorio|acta\s+de\s+la\s+reunion|invitacion|programa\s+de\s+trabajo|"
    r"reconocimiento\s+a|felicitacion|condolencia",
    re.IGNORECASE,
)

SENALES_LEG = [
    "iniciativa", "proyecto de decreto", "punto de acuerdo", "dictamen",
    "reforma constitucional", "proposicion con punto de acuerdo",
]

STOPWORDS = {
    "de","la","que","el","en","y","a","los","del","se","las","por","un",
    "para","con","no","una","su","al","lo","como","mas","pero","sus","le",
    "ya","o","este","porque","esta","entre","cuando","muy","sin","sobre",
    "tambien","me","hasta","hay","donde","quien","desde","todo","nos",
    "durante","todos","uno","les","ni","contra","otros","ese","eso","ante",
    "ellos","e","esto","antes","algunos","unos","yo","otro",
    "fue","ser","es","son","ha","han","era","sera","sido",
    "ley","reforma","codigo","articulo","fraccion","parrafo","decreto",
    "estado","estados","municipio","municipios","federal","nacional",
}

MIN_SCORE = 0.35


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
    titulo_n = _sin_acentos(titulo)
    hits_leg = sum(1 for s in SENALES_LEG if s in texto)
    scores = {}
    for key, cat in SCOPE_CATEGORIAS.items():
        score = 0.0
        for kw in cat["keywords"]:
            kl = kw.lower()
            if kl in texto:
                score += 3.0 if kl in titulo_n else 1.5
        if score > 0:
            score = score / math.sqrt(len(cat["keywords"]))
            if hits_leg > 0 and score > 0.2:
                score *= min(1.0 + hits_leg * 0.35, 2.5)
            if score >= MIN_SCORE:
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


def _inferir_tipo(titulo):
    t = titulo.lower()
    if re.search(r"iniciativa|que\s+reforma|que\s+adiciona|proyecto\s+de\s+decreto", t):
        return "iniciativa"
    if re.search(r"proposicion|punto\s+de\s+acuerdo", t):
        return "proposicion"
    if re.search(r"dictamen", t):
        return "dictamen"
    return "iniciativa"


# ─── SCRAPERS PERSONALIZADOS ───────────────────────────────────────────────────

def _exp_num(url):
    """Extrae número de expediente del nombre del PDF para ordenamiento."""
    m = re.search(r'EXP(\d+)', url, re.IGNORECASE)
    return int(m.group(1)) if m else 0


def scrape_chihuahua_csv():
    """
    Chihuahua: descarga CSV completo de la LXVIII Legislatura y filtra SCOPE.
    Endpoint: /biblioteca/iniciativas/generarCSV.php?idlegislatura=68
    """
    url = "https://www.congresochihuahua.gob.mx/biblioteca/iniciativas/generarCSV.php?idlegislatura=68"
    mes_actual = datetime.now().strftime("%Y-%m")
    try:
        r = get_session().get(url, timeout=30, verify=False)
        if r.status_code != 200:
            return []
        content = r.content.decode("utf-8-sig")   # elimina BOM si existe
        reader = csv.DictReader(io.StringIO(content))
        docs = []
        seen = set()
        for row in reader:
            # Normalizar nombres de columnas con posibles caracteres raros
            resumen = ""
            fecha_str = ""
            tipo_ini = ""
            for k, v in row.items():
                kn = _sin_acentos(k or "")
                if "resumen" in kn:
                    resumen = v or ""
                elif "fecha" in kn and "presentacion" in kn:
                    fecha_str = v or ""
                elif "tipo" in kn and "iniciativa" in kn:
                    tipo_ini = v or ""

            # Filtrar mes actual
            if not fecha_str.startswith(mes_actual):
                continue
            if not resumen or len(resumen) < 20:
                continue

            # Aplicar clasificador SCOPE
            cat, cat_nombre = clasificar(resumen)
            if not cat:
                continue

            # Construir URL del documento (enlace a la página de búsqueda con filtro)
            num = row.get("N\xfamero") or row.get("Numero") or ""
            key = resumen[:80]
            if key in seen:
                continue
            seen.add(key)

            docs.append({
                "titulo": resumen[:400],
                "tipo": "iniciativa" if "iniciativa" in resumen.lower() else "proposicion",
                "fecha": fecha_str[:10],
                "url": f"https://www.congresochihuahua.gob.mx/biblioteca/iniciativas/index.php",
                "categoria": cat_nombre,
                "estado": "Chihuahua",
                "metodo": "csv",
            })
            if len(docs) >= 5:
                break
        return docs
    except Exception as e:
        logging.debug(f"Chihuahua CSV error: {e}")
        return []


def scrape_nl_partidos():
    """
    Nuevo León: scrapea subpáginas por grupo parlamentario.
    Las páginas exponen PDFs con títulos completos de iniciativas.
    """
    base = "https://www.hcnl.gob.mx/iniciativas_lxxvii/"
    grupos = ["glpan", "glpri", "glmorena", "glpvem", "glprd"]
    año_actual = str(datetime.now().year)
    seen_urls = set()
    all_docs = []

    for grupo in grupos:
        url = base + grupo + "/"
        html = fetch_html(url)
        if not html:
            continue
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        for a in soup.find_all("a", href=True):
            href = a.get("href", "")
            titulo = a.get_text(strip=True)
            # Solo PDFs de iniciativas (patrón LXXVII-YEAR-EXP)
            if ".pdf" not in href.lower() or "hcnl.gob.mx" not in href:
                continue
            if len(titulo) < 30:
                continue
            if href in seen_urls:
                continue
            # Filtrar por año actual
            if año_actual not in href:
                continue
            if TIPOS_EXCLUIR.search(titulo):
                continue
            cat, cat_nombre = clasificar(titulo)
            if not cat:
                continue
            seen_urls.add(href)
            all_docs.append({
                "titulo": titulo[:400],
                "tipo": _inferir_tipo(titulo),
                "fecha": datetime.now().strftime("%Y-%m-%d"),
                "url": href,
                "categoria": cat_nombre,
                "estado": "Nuevo León",
                "metodo": "requests",
                "exp": _exp_num(href),
            })

    # Ordenar por número de expediente descendente (más reciente primero)
    all_docs.sort(key=lambda x: x.get("exp", 0), reverse=True)
    # Limpiar campo auxiliar
    for d in all_docs:
        d.pop("exp", None)
    return all_docs[:5]


# ─── NIVEL 1: requests + BeautifulSoup ─────────────────────────────────────────

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


def fetch_html(url):
    try:
        r = get_session().get(url, timeout=20, verify=False)
        if r.status_code == 200 and len(r.text) > 300:
            return r.text
    except Exception:
        pass
    return None


def _extraer_docs_html(html, base_url, estado, max_docs=5):
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    docs = []
    seen = set()
    for a in soup.find_all("a", href=True):
        titulo = a.get_text(strip=True)
        if not titulo or len(titulo) < 20:
            continue
        tk = titulo[:80]
        if tk in seen:
            continue
        if not es_tipo_valido(titulo):
            continue
        if not es_relevante(titulo):
            continue
        seen.add(tk)
        href = a["href"]
        if href.startswith("http"):
            url = href
        elif href.startswith("/"):
            from urllib.parse import urlparse
            p = urlparse(base_url)
            url = f"{p.scheme}://{p.netloc}{href}"
        else:
            url = f"{base_url.rstrip('/')}/{href}"
        _, cat = clasificar(titulo)
        docs.append({
            "titulo": titulo[:400],
            "tipo": _inferir_tipo(titulo),
            "fecha": datetime.now().strftime("%Y-%m-%d"),
            "url": url,
            "categoria": cat or "General",
            "estado": estado,
            "metodo": "requests",
        })
        if len(docs) >= max_docs:
            break
    return docs


# ─── NIVEL 2: Playwright (navegador headless) ───────────────────────────────────

_playwright_instance = None
_browser_instance = None


def get_browser():
    global _playwright_instance, _browser_instance
    if _browser_instance is None:
        from playwright.sync_api import sync_playwright
        _playwright_instance = sync_playwright().start()
        _browser_instance = _playwright_instance.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
        )
    return _browser_instance


def close_browser():
    global _playwright_instance, _browser_instance
    try:
        if _browser_instance:
            _browser_instance.close()
        if _playwright_instance:
            _playwright_instance.stop()
    except Exception:
        pass
    _browser_instance = None
    _playwright_instance = None


def fetch_playwright(url, wait_selector=None, timeout=25000):
    """Descarga una página con Playwright, esperando a que el JS renderice."""
    browser = get_browser()
    try:
        page = browser.new_page()
        page.set_extra_http_headers({"Accept-Language": "es-MX,es;q=0.9"})
        page.goto(url, timeout=timeout, wait_until="domcontentloaded")
        # Esperar a que cargue el contenido dinámico
        if wait_selector:
            try:
                page.wait_for_selector(wait_selector, timeout=8000)
            except Exception:
                pass
        else:
            page.wait_for_timeout(6000)
        html = page.content()
        page.close()
        return html
    except Exception as e:
        logging.debug(f"Playwright error {url}: {e}")
        try:
            page.close()
        except Exception:
            pass
        return None


def _extraer_docs_playwright(url, estado, max_docs=5):
    """Extrae documentos usando Playwright para portales con JavaScript."""
    html = fetch_playwright(url)
    if not html:
        return []
    return _extraer_docs_html(html, url, estado, max_docs)


# ─── SCRAPER PRINCIPAL POR ESTADO ──────────────────────────────────────────────

CUSTOM_SCRAPERS = {
    "Chihuahua": scrape_chihuahua_csv,
    "Nuevo León": scrape_nl_partidos,
}


def scrape_estado(nombre, config, usar_playwright=True):
    """
    Scrapea un estado con estrategia de dos niveles:
    1. Si existe scraper personalizado, lo usa primero
    2. Intenta con requests (rápido)
    3. Si no encuentra nada y el portal usa JS, usa Playwright
    """
    # Scraper personalizado
    if nombre in CUSTOM_SCRAPERS:
        try:
            docs = CUSTOM_SCRAPERS[nombre]()
            if docs:
                return docs
        except Exception as e:
            logging.debug(f"Custom scraper {nombre} error: {e}")

    docs = []
    urls = []

    if config.get("iniciativas"):
        urls.append(config["iniciativas"])
    if config.get("iniciativas_alt"):
        urls.append(config["iniciativas_alt"])
    if config.get("puntos_acuerdo"):
        urls.append(config["puntos_acuerdo"])
    if config.get("gaceta_parl"):
        urls.append(config["gaceta_parl"])

    seen_urls = set()

    for url in urls:
        # Nivel 1: requests
        html = fetch_html(url)
        time.sleep(0.5)
        if html:
            nuevos = _extraer_docs_html(html, url, nombre, max_docs=5)
            for d in nuevos:
                if d["url"] not in seen_urls:
                    seen_urls.add(d["url"])
                    docs.append(d)

        # Nivel 2: Playwright si no encontramos nada y el portal usa JS
        if not docs and usar_playwright and config.get("js", False):
            nuevos_pw = _extraer_docs_playwright(url, nombre, max_docs=5)
            for d in nuevos_pw:
                if d["url"] not in seen_urls:
                    seen_urls.add(d["url"])
                    docs.append(d)

        if len(docs) >= 5:
            break

    return docs[:5]


# ─── SCRAPER TODOS LOS ESTADOS ─────────────────────────────────────────────────

def scrape_todos_estados(usar_playwright=True):
    resultados = {}
    total_docs = 0
    estados_con_actividad = 0

    print(f"  Scrapeando {len(ESTADOS)} congresos estatales "
          f"({'con' if usar_playwright else 'sin'} Playwright)...")

    for i, (nombre, config) in enumerate(ESTADOS.items(), 1):
        print(f"  [{i:02d}/{len(ESTADOS)}] {nombre}...", end=" ", flush=True)
        try:
            docs = scrape_estado(nombre, config, usar_playwright=usar_playwright)
            if docs:
                resultados[nombre] = docs
                total_docs += len(docs)
                estados_con_actividad += 1
                metodo = docs[0].get("metodo", "?")
                print(f"{len(docs)} docs [{metodo}]")
            else:
                print("sin resultados")
        except Exception as e:
            print(f"error: {e}")

    print(f"\n  Total: {total_docs} iniciativas SCOPE en {estados_con_actividad} estados")

    if usar_playwright:
        close_browser()

    return resultados


# ─── MERGE CON JSON EXISTENTE ──────────────────────────────────────────────────

def merge_con_existentes(nuevos, json_path="data/gaceta-estatal.json"):
    mes_actual = datetime.now().strftime("%Y-%m")
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            existente = json.load(f)
        estados_existentes = existente.get("estados", {})
    except Exception:
        estados_existentes = {}

    estados_merged = {}
    for nombre, docs_nuevos in nuevos.items():
        docs_existentes = estados_existentes.get(nombre, [])
        del_mes = [d for d in docs_existentes if str(d.get("fecha", "")).startswith(mes_actual)]
        urls_ex = {d["url"] for d in del_mes}
        agregados = [d for d in docs_nuevos if d["url"] not in urls_ex]
        combinados = del_mes + agregados
        combinados.sort(key=lambda x: x.get("fecha", ""), reverse=True)
        if combinados:
            estados_merged[nombre] = combinados[:5]

    resumen = []
    for nombre, docs in estados_merged.items():
        if docs:
            cats = {}
            for d in docs:
                cat = d.get("categoria", "General")
                cats[cat] = cats.get(cat, 0) + 1
            cat_principal = max(cats, key=cats.get)
            resumen.append({
                "estado": nombre,
                "total": len(docs),
                "categoria_principal": cat_principal,
                "ultima_fecha": docs[0].get("fecha", ""),
            })

    resumen.sort(key=lambda x: (x["ultima_fecha"], x["total"]), reverse=True)

    return {
        "estados": estados_merged,
        "resumen": resumen[:20],
        "_meta": {
            "ultima_actualizacion": datetime.now().isoformat(),
            "mes": mes_actual,
            "estados_con_actividad": len(estados_merged),
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
    parser = argparse.ArgumentParser(description="SCOPE Scraper Gacetas Estatales")
    parser.add_argument("--token", required=True)
    parser.add_argument("--no-upload", action="store_true")
    parser.add_argument("--no-playwright", action="store_true",
                        help="Usar solo requests (sin navegador)")
    parser.add_argument("--estado", help="Scrapear solo un estado")
    args = parser.parse_args()

    usar_playwright = not args.no_playwright
    mes = datetime.now().strftime("%Y-%m")

    print(f"\n{'-'*50}")
    print(f"  SCOPE - Scraper Gacetas Estatales")
    print(f"  Mes: {mes} | Playwright: {'SI' if usar_playwright else 'NO'}")
    print(f"{'-'*50}\n")

    if args.estado:
        if args.estado not in ESTADOS:
            print(f"Estado no encontrado. Disponibles:")
            print(", ".join(ESTADOS.keys()))
            return
        docs = scrape_estado(args.estado, ESTADOS[args.estado], usar_playwright=usar_playwright)
        if usar_playwright:
            close_browser()
        print(f"\n[{args.estado}] {len(docs)} docs SCOPE:")
        for d in docs:
            print(f"  [{d['tipo']}] [{d['categoria']}] {d['titulo'][:80]}")
        return

    nuevos = scrape_todos_estados(usar_playwright=usar_playwright)
    resultado = merge_con_existentes(nuevos)

    json_path = "data/gaceta-estatal.json"
    contenido = json.dumps(resultado, ensure_ascii=False, indent=2).encode("utf-8")
    with open(json_path, "wb") as f:
        f.write(contenido)

    n_estados = resultado["_meta"]["estados_con_actividad"]
    n_docs = sum(len(d) for d in resultado["estados"].values())
    print(f"\nGuardado: {n_estados} estados, {n_docs} iniciativas")

    if not args.no_upload:
        print("Subiendo a GitHub...")
        status = subir_github(args.token, contenido, "data/gaceta-estatal.json",
                              f"Gacetas estatales SCOPE {mes}: {n_estados} estados")
        print("OK" if status in (200, 201) else f"Status: {status}")

    print("\n--- Resumen ---")
    for r in resultado.get("resumen", []):
        print(f"  {r['estado']}: {r['total']} docs | {r['categoria_principal']}")


if __name__ == "__main__":
    main()
