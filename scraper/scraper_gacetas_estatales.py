"""
SCOPE - Scraper de Gacetas Legislativas Estatales
Monitorea los 32 congresos estatales de México buscando iniciativas y
proposiciones con punto de acuerdo relevantes a las categorías SCOPE.

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
import urllib.request
from datetime import datetime, timedelta
from collections import Counter

import requests
from bs4 import BeautifulSoup

warnings.filterwarnings("ignore")
logging.basicConfig(level=logging.WARNING)

# ─── DIRECTORIO DE ESTADOS ────────────────────────────────────────────────────
# Basado en el directorio legislativo proporcionado

ESTADOS = {
    "Aguascalientes": {
        "congreso": "https://congresoags.gob.mx",
        "iniciativas": "https://congresoags.gob.mx/agenda_legislativa/iniciativas",
        "periodico": "https://eservicios2.aguascalientes.gob.mx/periodicooficial/",
    },
    "Baja California": {
        "congreso": "https://www.congresobc.gob.mx",
        "iniciativas": "https://www.congresobc.gob.mx/TrabajoLegislativo/Iniciativas",
        "periodico": "https://periodicooficial.ebajacalifornia.gob.mx/oficial/inicioConsulta.jsp",
    },
    "Baja California Sur": {
        "congreso": "https://www.cbcs.gob.mx",
        "iniciativas": "https://www.cbcs.gob.mx/index.php/iniciativas-ley-pes",
        "periodico": "https://finanzas.bcs.gob.mx/boletines-oficiales/",
    },
    "Campeche": {
        "congreso": "https://www.congresocam.gob.mx",
        "iniciativas": "https://www.congresocam.gob.mx",
        "periodico": "http://periodicooficial.campeche.gob.mx/sipoec/public/",
    },
    "Chiapas": {
        "congreso": "https://web.congresochiapas.gob.mx",
        "iniciativas": "https://www.congresochiapas.gob.mx/new/Info-Parlamentaria/iniciativas/",
        "periodico": "https://www.sgg.chiapas.gob.mx/periodico/",
    },
    "Chihuahua": {
        "congreso": "https://www.congresochihuahua.gob.mx",
        "iniciativas": "https://www.congresochihuahua.gob.mx/biblioteca/iniciativas/",
        "periodico": "https://chihuahua.gob.mx/periodicooficial/buscador",
    },
    "Ciudad de México": {
        "congreso": "https://www.congresocdmx.gob.mx",
        "iniciativas": "https://www.congresocdmx.gob.mx/iniciativas-213-6.html",
        "iniciativas_alt": "https://ciudadana.congresocdmx.gob.mx/Iniciativa/iniciativas",
        "periodico": "https://consejeria.cdmx.gob.mx/gaceta-oficial",
    },
    "Coahuila": {
        "congreso": "https://www.congresocoahuila.gob.mx",
        "iniciativas": "https://www.congresocoahuila.gob.mx/portal/iniciativas/",
        "periodico": "https://periodico.segobcoahuila.gob.mx/",
    },
    "Colima": {
        "congreso": "https://congresocol.gob.mx/web/www/",
        "iniciativas": "https://congresocol.gob.mx/web/www/",
        "periodico": "https://periodicooficial.col.gob.mx/",
    },
    "Durango": {
        "congreso": "https://congresodurango.gob.mx/",
        "iniciativas": "https://congresodurango.gob.mx/",
        "periodico": "https://periodicooficial.durango.gob.mx/",
    },
    "México": {
        "congreso": "https://legislacion.legislativoedomex.gob.mx/asuntos/",
        "iniciativas": "https://legislacion.legislativoedomex.gob.mx/asuntos/",
        "periodico": "https://legislacion.edomex.gob.mx/ve_periodico_oficial",
    },
    "Guanajuato": {
        "congreso": "https://www.congresogto.gob.mx",
        "iniciativas": "https://www.congresogto.gob.mx/gaceta/iniciativas",
        "periodico": "https://periodico.guanajuato.gob.mx/",
    },
    "Guerrero": {
        "congreso": "https://congresogro.gob.mx/",
        "iniciativas": "https://congresogro.gob.mx/",
        "periodico": "https://periodicooficial.guerrero.gob.mx/",
    },
    "Hidalgo": {
        "congreso": "https://www.congreso-hidalgo.gob.mx/",
        "iniciativas": "https://www.congreso-hidalgo.gob.mx/",
        "periodico": "https://periodico.hidalgo.gob.mx/",
    },
    "Jalisco": {
        "congreso": "https://www.congresojal.gob.mx/",
        "iniciativas": "https://www.congresojal.gob.mx/",
        "periodico": "https://periodicooficial.jalisco.gob.mx/",
    },
    "Michoacán": {
        "congreso": "https://congresomich.site",
        "iniciativas": "https://congresomich.site/iniciativas/",
        "periodico": "https://periodicooficial.michoacan.gob.mx/",
    },
    "Morelos": {
        "congreso": "https://congresomorelos.gob.mx/",
        "iniciativas": "https://congresomorelos.gob.mx/category/iniciativas-legislativas/",
        "periodico": "https://periodico.morelos.gob.mx/",
    },
    "Nayarit": {
        "congreso": "https://congresonayarit.gob.mx/",
        "iniciativas": "https://procesolegislativo.congresonayarit.gob.mx/iniciativas/",
        "periodico": "https://periodicooficial.nayarit.gob.mx/",
    },
    "Nuevo León": {
        "congreso": "https://www.hcnl.gob.mx/",
        "iniciativas": "https://www.hcnl.gob.mx/trabajo_legislativo/iniciativas/",
        "periodico": "https://sistec.nl.gob.mx/Transparencia_2015_LYPOE/Acciones/PeriodicoOficial.aspx",
    },
    "Oaxaca": {
        "congreso": "https://www.congresooaxaca.gob.mx/",
        "iniciativas": "https://www.congresooaxaca.gob.mx/",
        "periodico": "https://periodicooficial.oaxaca.gob.mx/",
    },
    "Puebla": {
        "congreso": "https://www.congresopuebla.gob.mx/",
        "iniciativas": "https://micrositios.congresopuebla.gob.mx/buscadores/iniciativas/index.php",
        "periodico": "https://periodicooficial.puebla.gob.mx/",
    },
    "Querétaro": {
        "congreso": "http://legislaturaqueretaro.gob.mx/",
        "iniciativas": "http://legislaturaqueretaro.gob.mx/iniciativas/",
        "periodico": "https://lasombradearteaga.segobqueretaro.gob.mx/",
    },
    "Quintana Roo": {
        "congreso": "https://www.congresoqroo.gob.mx/",
        "iniciativas": "https://www.congresoqroo.gob.mx/iniciativas/",
        "periodico": "http://po.segob.qroo.gob.mx/sitiopo/",
    },
    "San Luis Potosí": {
        "congreso": "https://congresosanluis.gob.mx/",
        "iniciativas": "https://congresosanluis.gob.mx/trabajo/trabajo-legislativo/iniciativas",
        "periodico": "https://periodicooficial.slp.gob.mx/",
    },
    "Sinaloa": {
        "congreso": "https://www.congresosinaloa.gob.mx/",
        "iniciativas": "https://www.congresosinaloa.gob.mx/iniciativas/",
        "puntos_acuerdo": "https://www.congresosinaloa.gob.mx/puntos-de-acuerdo/",
        "periodico": "https://iip.congresosinaloa.gob.mx/poes.html",
    },
    "Sonora": {
        "congreso": "https://congresoson.gob.mx/",
        "iniciativas": "https://congresoson.gob.mx/iniciativas",
        "periodico": "https://boletinoficial.sonora.gob.mx/",
    },
    "Tabasco": {
        "congreso": "https://congresotabasco.gob.mx/",
        "iniciativas": "https://congresotabasco.gob.mx/iniciativas/",
        "puntos_acuerdo": "https://congresotabasco.gob.mx/puntos-de-acuerdo/",
        "gaceta_parl": "https://congresotabasco.gob.mx/gaceta-legislativa/",
        "periodico": "https://tabasco.gob.mx/PeriodicoOficial",
    },
    "Tamaulipas": {
        "congreso": "https://www.congresotamaulipas.gob.mx/",
        "iniciativas": "https://www.congresotamaulipas.gob.mx/Parlamentario/Archivos/Iniciativas/",
        "periodico": "https://po.tamaulipas.gob.mx/",
    },
    "Tlaxcala": {
        "congreso": "https://congresodetlaxcala.gob.mx/",
        "iniciativas": "https://congresodetlaxcala.gob.mx/iniciativas/",
        "gaceta_parl": "https://congresodetlaxcala.gob.mx/gacetas-parlamentarias/",
        "periodico": "https://periodico.tlaxcala.gob.mx/",
    },
    "Veracruz": {
        "congreso": "https://www.legisver.gob.mx/",
        "iniciativas": "https://www.legisver.gob.mx/",
        "periodico": "https://editoraveracruz.gob.mx/",
    },
    "Yucatán": {
        "congreso": "https://www.congresoyucatan.gob.mx/",
        "iniciativas": "https://www.congresoyucatan.gob.mx/gaceta/iniciativas",
        "periodico": "https://www.yucatan.gob.mx/gobierno/diario_oficial.php",
    },
    "Zacatecas": {
        "congreso": "https://www.congresozac.gob.mx/",
        "iniciativas": "https://www.congresozac.gob.mx/64/gaceta",
        "periodico": "https://periodico.zacatecas.gob.mx/",
        "nota": "El /64/ es la legislatura actual; detectar dinámicamente si cambia",
    },
}

# ─── CLASIFICADOR SCOPE (mismo que scraper federal) ───────────────────────────

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
    "iniciativa","proyecto de decreto","punto de acuerdo","dictamen",
    "reforma constitucional","proposicion con punto de acuerdo",
]

STOPWORDS = {
    "de","la","que","el","en","y","a","los","del","se","las","por","un",
    "para","con","no","una","su","al","lo","como","mas","pero","sus","le",
    "ya","o","este","porque","esta","entre","cuando","muy","sin","sobre",
    "tambien","me","hasta","hay","donde","quien","desde","todo","nos",
    "durante","todos","uno","les","ni","contra","otros","ese","eso","ante",
    "ellos","e","esto","antes","algunos","unos","yo","otro",
    "fue","ser","es","son","ha","han","era","sera","sido",
    # Palabras legislativas genéricas que causan falsos positivos
    "ley","reforma","codigo","articulo","fraccion","parrafo","decreto",
    "estado","estados","municipio","municipios","federal","nacional",
}

# Umbral mínimo de score para considerar un documento relevante a SCOPE
MIN_SCORE_ESTATAL = 0.35


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
    """
    Clasificador estricto para portales estatales:
    - Solo coincidencias de frase completa (no tokens individuales)
    - Umbral de score más alto que el scraper federal
    - Evita falsos positivos por palabras genéricas como 'ley', 'reforma'
    """
    texto = _sin_acentos(f"{titulo} {resumen}")
    titulo_n = _sin_acentos(titulo)
    hits_leg = sum(1 for s in SENALES_LEG if s in texto)
    scores = {}
    for key, cat in SCOPE_CATEGORIAS.items():
        score = 0.0
        for kw in cat["keywords"]:
            kl = kw.lower()
            # Solo coincidencia de frase completa — sin fallback a tokens individuales
            if kl in texto:
                # Bonus extra si aparece en el título (no solo en el resumen)
                score += 3.0 if kl in titulo_n else 1.5
        if score > 0:
            score = score / math.sqrt(len(cat["keywords"]))
            if hits_leg > 0 and score > 0.2:
                score *= min(1.0 + hits_leg * 0.35, 2.5)
            if score >= MIN_SCORE_ESTATAL:
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


def fetch(url, verify=False):
    """Descarga una página. verify=False por defecto: muchos portales estatales
    tienen certificados SSL vencidos o autofirmados."""
    try:
        r = get_session().get(url, timeout=20, verify=verify)
        if r.status_code == 200 and len(r.text) > 300:
            return r.text
    except Exception:
        pass
    return None


# ─── SCRAPER GENÉRICO ESTATAL ─────────────────────────────────────────────────

def _extraer_docs_genericos(html, base_url, estado, max_docs=5):
    """
    Extrae iniciativas/proposiciones de cualquier portal estatal.
    Estrategia: buscar links con texto largo que contengan palabras clave
    de tipo legislativo y sean relevantes a SCOPE.
    """
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
            # Extraer base del dominio
            from urllib.parse import urlparse
            parsed = urlparse(base_url)
            url = f"{parsed.scheme}://{parsed.netloc}{href}"
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
        })

        if len(docs) >= max_docs:
            break

    return docs


def _inferir_tipo(titulo):
    t = titulo.lower()
    if re.search(r"iniciativa|que\s+reforma|que\s+adiciona|proyecto\s+de\s+decreto", t):
        return "iniciativa"
    if re.search(r"proposicion|punto\s+de\s+acuerdo", t):
        return "proposicion"
    if re.search(r"dictamen", t):
        return "dictamen"
    return "iniciativa"


def scrape_estado(nombre, config):
    """
    Scrapea las URLs de iniciativas de un estado.
    Intenta la URL principal y opcionalmente la alternativa.
    Retorna lista de docs relevantes a SCOPE.
    """
    docs = []
    urls_a_intentar = []

    if config.get("iniciativas"):
        urls_a_intentar.append(config["iniciativas"])
    if config.get("iniciativas_alt"):
        urls_a_intentar.append(config["iniciativas_alt"])
    if config.get("puntos_acuerdo"):
        urls_a_intentar.append(config["puntos_acuerdo"])
    if config.get("gaceta_parl"):
        urls_a_intentar.append(config["gaceta_parl"])

    seen_urls = set()
    for url in urls_a_intentar:
        html = fetch(url)
        time.sleep(0.8)
        if html:
            nuevos = _extraer_docs_genericos(html, url, nombre, max_docs=5)
            for d in nuevos:
                if d["url"] not in seen_urls:
                    seen_urls.add(d["url"])
                    docs.append(d)

        if len(docs) >= 5:
            break

    return docs[:5]


# ─── SCRAPER PRINCIPAL ────────────────────────────────────────────────────────

def scrape_todos_estados():
    """
    Scrapea todos los estados y retorna resultados organizados por estado.
    """
    resultados = {}
    total_docs = 0
    estados_con_actividad = 0

    print(f"  Scrapeando {len(ESTADOS)} congresos estatales...")

    for i, (nombre, config) in enumerate(ESTADOS.items(), 1):
        print(f"  [{i:02d}/{len(ESTADOS)}] {nombre}...", end=" ", flush=True)
        try:
            docs = scrape_estado(nombre, config)
            if docs:
                resultados[nombre] = docs
                total_docs += len(docs)
                estados_con_actividad += 1
                print(f"{len(docs)} docs SCOPE")
            else:
                print("sin resultados")
        except Exception as e:
            print(f"error: {e}")
            resultados[nombre] = []

    print(f"\n  Total: {total_docs} iniciativas en {estados_con_actividad} estados")
    return resultados


# ─── MERGE CON JSON EXISTENTE ─────────────────────────────────────────────────

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
        # Filtrar existentes del mes actual
        del_mes = [d for d in docs_existentes if str(d.get("fecha", "")).startswith(mes_actual)]
        urls_ex = {d["url"] for d in del_mes}
        agregados = [d for d in docs_nuevos if d["url"] not in urls_ex]
        combinados = del_mes + agregados
        combinados.sort(key=lambda x: x.get("fecha", ""), reverse=True)
        if combinados:
            estados_merged[nombre] = combinados[:5]

    # Resumen por estado para el widget
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
        "resumen": resumen[:15],
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
    parser.add_argument("--token", required=True, help="GitHub token")
    parser.add_argument("--no-upload", action="store_true")
    parser.add_argument("--estado", help="Scrapear solo un estado específico")
    args = parser.parse_args()

    mes = datetime.now().strftime("%Y-%m")
    print(f"\n{'-'*50}")
    print(f"  SCOPE - Scraper Gacetas Estatales")
    print(f"  Mes: {mes}")
    print(f"{'-'*50}\n")

    if args.estado:
        # Modo: solo un estado
        if args.estado not in ESTADOS:
            print(f"Estado no encontrado: {args.estado}")
            print(f"Disponibles: {', '.join(ESTADOS.keys())}")
            return
        config = ESTADOS[args.estado]
        docs = scrape_estado(args.estado, config)
        print(f"\n[{args.estado}] {len(docs)} docs SCOPE:")
        for d in docs:
            print(f"  [{d['tipo']}] [{d['categoria']}] {d['titulo'][:80]}")
        return

    # Modo completo: todos los estados
    nuevos = scrape_todos_estados()
    resultado = merge_con_existentes(nuevos)

    json_path = "data/gaceta-estatal.json"
    contenido = json.dumps(resultado, ensure_ascii=False, indent=2).encode("utf-8")
    with open(json_path, "wb") as f:
        f.write(contenido)

    n_estados = resultado["_meta"]["estados_con_actividad"]
    n_docs = sum(len(d) for d in resultado["estados"].values())
    print(f"\nGuardado en {json_path}")
    print(f"   Estados con actividad SCOPE: {n_estados}")
    print(f"   Total iniciativas: {n_docs}")

    if not args.no_upload:
        print("\nSubiendo a GitHub Pages...")
        status = subir_github(args.token, contenido, "data/gaceta-estatal.json",
                              f"Gacetas estatales SCOPE {mes}: {n_estados} estados, {n_docs} docs")
        if status in (200, 201):
            print("OK - Subido a GitHub (gemiscopex/gemi-scope)")
        else:
            print(f"Status: {status}")

    # Mostrar resumen
    print("\n--- Estados con actividad SCOPE ---")
    for r in resultado.get("resumen", []):
        print(f"  {r['estado']}: {r['total']} docs | {r['categoria_principal']}")


if __name__ == "__main__":
    main()
