"""
scraper_presidencia.py
======================
Scrapes real Mañanera transcripts (estenográficas) from gob.mx/presidencia.
Extracts only Sheinbaum's own words on environmental topics.

Source:  https://www.gob.mx/presidencia/es/articulos/
Output:  data/presidencia.json

Pattern: /version-estenografica-...-del-{D}-de-{mes}-de-{YYYY}
UA note:  default requests UA bypasses gob.mx WAF (confirmed). Curl fallback included.
"""

import hashlib
import json
import os
import re
import subprocess
import sys
import time
import unicodedata
from datetime import datetime, date, timedelta

import requests
import urllib3
from bs4 import BeautifulSoup

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ---------------------------------------------------------------------------
BASE_DIR    = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_FILE = os.path.join(BASE_DIR, "data", "presidencia.json")

# ---------------------------------------------------------------------------
# URL pattern (FIAT production — day NOT zero-padded)
# ---------------------------------------------------------------------------
URL_BASE = "https://www.gob.mx/presidencia/es/articulos/"
MESES    = ["enero","febrero","marzo","abril","mayo","junio",
            "julio","agosto","septiembre","octubre","noviembre","diciembre"]

def build_url(d: date, pad: bool = True) -> str:
    # gob.mx pasó a día con cero a la izquierda (…-del-04-de-agosto-…).
    # Se prueba primero el formato con cero (canónico actual) y luego sin cero
    # como respaldo para meses/URLs históricas.
    dd = f"{d.day:02d}" if pad else str(d.day)
    return (
        f"{URL_BASE}version-estenografica-conferencia-de-prensa-"
        f"de-la-presidenta-claudia-sheinbaum-pardo-del-"
        f"{dd}-de-{MESES[d.month-1]}-de-{d.year}"
    )

# ---------------------------------------------------------------------------
# Speaker-extraction regexes (from FIAT)
# ---------------------------------------------------------------------------
RE_CSP_LABEL = re.compile(
    r"PRESIDENTA(?:\s+DE\s+(?:LA\s+REP[ÚU]BLICA|M[ÉE]XICO))?"
    r"[,:]?\s*(?:CLAUDIA\s+SHEINBAUM\s+PARDO)?[:\s]",
    re.IGNORECASE,
)

RE_OTHER_SPEAKER = re.compile(
    r"^(?:SECRETARI[OA]|MINISTR[OA]|PRESIDENTE|DIPUTAD[OA]|"
    r"SENADOR[A]?|GOBERNADOR[A]?|FISCAL|PROCURADOR[A]?|"
    r"ALMIRANTE|GENERAL|COMANDANTE|DIRECTOR[A]?|PERIODISTA|"
    r"PREGUNTA|INTERLOCUTOR)\b",
    re.IGNORECASE | re.MULTILINE,
)

# ---------------------------------------------------------------------------
# Environmental keywords (FIAT + SCOPE extensions)
# ---------------------------------------------------------------------------
    # ── Alineado a los 13 temas del Radar de Scope (superconjunto: cubre todos)
    #    + granularidad extra útil (hidrocarburos, minería, calidad de aire, transgénicos)
    #    + temas económicos de los socios. ──
KEYWORDS_AMBIENTAL = {
    "agua":             ["agua","hidric","cuenca","acuifero","sequia","conagua","presa",
                         "potable","saneamiento","drenaje","desabasto","rio","lago","laguna",
                         "inundacion","escasez de agua","agua potable","tratamiento de aguas"],
    "residuos":         ["residuo","basura","reciclaj","relleno sanitario","tiradero",
                         "vertedero","desecho","recolec","organico","incinerador",
                         "residuo peligroso"],
    "circular":         ["economia circular","circularidad","ecodiseno","valorizac","reutiliz",
                         "envase","empaque","simbiosis industrial","parque industrial",
                         "desarrollo circular","podecibi","basura cero","acopio",
                         "aprovechamiento de residuos","responsabilidad extendida","chatarra",
                         "compost","reincorpora"],
    "cambio_climatico": ["cambio climatic","carbono","gases de efecto","gei","co2",
                         "calentamiento global","inecc","mitigacion","descarboniz",
                         "neutralidad de carbono","huella de carbono","transicion energetica",
                         "metano","acuerdo de paris","lgcc"],
    "fiscal":           ["impuesto ambiental","impuesto verde","impuesto ecologic",
                         "tasa ecologic","bono de carbono","bono carbono","impuesto al carbono",
                         "impuesto a emisiones"],
    "plasticos":        ["plastic","unicel","poliestireno","monouso","un solo uso","popote",
                         "desechable","bolsa de plastico","poliet"],
    "energia":          ["energia solar","energia renovable","energia limpia","renovable",
                         "fotovoltaic","eolic","cfe","sener","hidrogeno","panel solar",
                         "parque eolico","geotermia","biogas","hidroelectric","litio"],
    "hidrocarburos":    ["pemex","refineria","ducto","oleoducto","gasoducto","fracking",
                         "hidrocarburo","petroleo","combustible fosil","gas natural"],
    "sanciones":        ["profepa","sancion","multa","clausura","infraccion","inspeccion",
                         "verificacion ambiental","denuncia ambiental","delito ambiental",
                         "procedimiento administrativo"],
    "biodiversidad":    ["semarnat","conanp","area natural protegida","reserva natural",
                         "reserva de la biosfera","especie en peligro","extincion","biodivers",
                         "vida silvestre","corredor biologic","parque nacional","manglar",
                         "arrecife","jaguar","ballena","manati"],
    "infra":            ["planta de tratamiento","alcantarillado","acueducto","colector",
                         "obra hidraulica","infraestructura hidrica"],
    "agricultura":      ["agricultura","agropecuari","ganaderi","ganader","fertilizante",
                         "cultivo","pecuari","riego","agroindustria","agroquimic","plaguicida"],
    "procesos":         ["proceso industrial","cemento","clinker","siderurgi","acero",
                         "industria quimica","petroquimica","cementera","fundidora",
                         "metalurgi","refrigerante"],
    "uso_suelo":        ["uso de suelo","deforestac","reforestac","silvicultura","bosque",
                         "selva","cambio de uso de suelo","incendio forestal","conafor",
                         "tala ilegal"],
    "calidad_aire":     ["ozono","pm2.5","pm10","emisiones de gases","calidad del aire",
                         "contaminacion atmosferica","smog","contingencia ambiental"],
    "mineria":          ["mineria","concesion minera","extraccion minera","minera","cianuro"],
    "transgenico":      ["transgenico","glifosato","semilla nativa","soberania alimentaria",
                         "maiz nativo"],
    # ── SCOPE: temas económicos relevantes para los socios ──
    "inversion":        ["inversion","nearshoring","relocalizacion","plan mexico",
                         "polo de desarrollo","polos de desarrollo","polos del bienestar",
                         "parque industrial","inversion extranjera","nueva planta",
                         "planta armadora","armadora","ensambladora","empleos directos",
                         "genera empleos","anuncio de inversion","millones de dolares",
                         "mil millones","capital extranjero","kia","nissan","tesla",
                         "planta de","complejo industrial"],
    "comercio_tmec":    ["t-mec","tmec","t mec","usmca","tratado de libre comercio",
                         "tratado comercial","aranceles","arancel","reglas de origen",
                         "comercio exterior","exportaciones","revision del tratado",
                         "socios comerciales","america del norte","barreras arancelarias"],
}

ALL_KW = [kw for kws in KEYWORDS_AMBIENTAL.values() for kw in kws]

# ---------------------------------------------------------------------------
# Frases que indican que el fragmento es de seguridad/crimen, no ambiental
# ---------------------------------------------------------------------------
EXCLUIR_FRAGS = [
    "secretario de seguridad",
    "secretaria de seguridad",
    "guardia nacional",
    "crimen organizado",
    "ministerio publico",
    "fiscal general",
    "ley de seguridad nacional",
    "colaboracion en seguridad",
    "agencia de inteligencia",
    "agencias de estados unidos",
    "fuerza armada",
    "fuerzas armadas",
    "operativo policial",
    "narcotrafico",
    "cartel",
    "homicidio",
    "feminicidio",
    "desaparicion forzada",
    "extorsion",
    "delincuencia organizada",
    "antisecuestro",
    "detencion de presuntos",
    "presunto culpable",
]

# ---------------------------------------------------------------------------
def normalize(text: str) -> str:
    t = text.lower()
    t = unicodedata.normalize("NFD", t)
    return "".join(c for c in t if unicodedata.category(c) != "Mn")

def _kw_match(kw_norm: str, text_norm: str) -> bool:
    """Frase (con espacio) → substring; palabra suelta → prefijo anclado a inicio de
    palabra (\\bstem), igual que el Radar de Scope: 'residuo' casa 'residuo/residuos'."""
    if " " in kw_norm:
        return kw_norm in text_norm
    return bool(re.search(r"\b" + re.escape(kw_norm), text_norm))

def is_relevant(text: str) -> bool:
    """True si el texto contiene al menos un keyword ambiental (con límite de palabra)."""
    t = normalize(text)
    return any(_kw_match(normalize(kw), t) for kw in ALL_KW)

def _env_hit_count(text_norm: str) -> int:
    """Cuenta cuántos keywords ambientales distintos aparecen en el texto."""
    return sum(1 for kw in ALL_KW if _kw_match(normalize(kw), text_norm))

def is_env_fragment(line: str) -> bool:
    """
    True si el fragmento tiene contenido ambiental genuino:
    - Al menos 1 keyword ambiental con word-boundary
    - Sin frases de seguridad/crimen (o con ellas pero con 3+ hits ambientales)
    """
    t = normalize(line)
    hits = _env_hit_count(t)
    if hits == 0:
        return False
    has_security = any(normalize(d) in t for d in EXCLUIR_FRAGS)
    if has_security and hits < 3:
        return False
    return True

def classify(text: str) -> list:
    """Devuelve lista de categorías ambientales detectadas."""
    t = normalize(text)
    return [cat for cat, kws in KEYWORDS_AMBIENTAL.items()
            if any(_kw_match(normalize(kw), t) for kw in kws)]

def make_id(url: str) -> str:
    return hashlib.md5(url.encode()).hexdigest()[:10]

# ---------------------------------------------------------------------------
# Downloader with curl fallback (FIAT pattern)
# ---------------------------------------------------------------------------
def fetch_html(url: str, retries: int = 2) -> str | None:
    sess = requests.Session()
    for _ in range(retries):
        try:
            r = sess.get(url, timeout=30)
            if r.status_code == 404:
                return None
            if r.status_code == 200 and "Challenge" not in r.text[:300]:
                r.encoding = "utf-8"
                return r.text
        except Exception:
            pass
        time.sleep(2.0)
    # Curl fallback
    try:
        out = subprocess.run(
            ["curl", "-sL", "--max-time", "30", url],
            capture_output=True, text=True, timeout=35, encoding="utf-8"
        )
        if out.returncode == 0 and "Challenge" not in out.stdout[:300]:
            return out.stdout
    except Exception:
        pass
    return None

# ---------------------------------------------------------------------------
# Extract Sheinbaum's own words, split into paragraphs
# ---------------------------------------------------------------------------
def extraer_intervenciones_csp(html: str) -> list:
    """Return list of CSP intervention strings."""
    soup = BeautifulSoup(html, "html.parser")
    body = soup.find("div", class_="article-body") or soup
    parrafos = [p.get_text("\n", strip=True) for p in body.find_all(["p", "div"])]
    intervenciones = []
    capturando = False
    actual = []
    for parr in parrafos:
        if RE_CSP_LABEL.search(parr):
            capturando = True
            actual = [parr]
        elif capturando and RE_OTHER_SPEAKER.match(parr.strip()):
            if actual:
                intervenciones.append("\n".join(actual))
            capturando = False
            actual = []
        elif capturando:
            actual.append(parr)
    if actual:
        intervenciones.append("\n".join(actual))
    return intervenciones

def extract_env_fragments(html: str, max_frags: int = 6) -> list:
    """
    De las palabras de Sheinbaum únicamente, devuelve párrafos con
    contenido ambiental genuino (sin seguridad, sin menciones de paso).
    Si no se pueden aislar los turnos de la Presidenta, devuelve [].
    """
    intervenciones = extraer_intervenciones_csp(html)
    if not intervenciones:
        # Sin turnos identificados: no incluimos fragmentos para evitar ruido
        return []

    fragments = []
    for bloque in intervenciones:
        for line in bloque.split("\n"):
            line = line.strip()
            if len(line) < 80:           # párrafos muy cortos son poco informativos
                continue
            if is_env_fragment(line):
                fragments.append(line[:500])
            if len(fragments) >= max_frags:
                return fragments
    return fragments

# ---------------------------------------------------------------------------
def scrape_date(d: date) -> dict | None:
    # Prueba día con cero (formato actual) y sin cero (respaldo histórico)
    url = html = None
    for pad in (True, False):
        u = build_url(d, pad)
        html = fetch_html(u)
        if html is not None:
            url = u
            break
    if html is None:
        return None

    soup = BeautifulSoup(html, "html.parser")
    title_tag = soup.find("h1") or soup.find("title")
    titulo = title_tag.get_text(strip=True) if title_tag else f"Mañanera {d.isoformat()}"

    # Extraer fragmentos ambientales de los turnos de la Presidenta
    fragmentos = extract_env_fragments(html)
    if not fragmentos:
        return None   # sin contenido ambiental en sus propias palabras

    # Categorías derivadas de los fragmentos (no del texto completo)
    texto_frags = " ".join(fragmentos)
    categorias  = classify(texto_frags)
    if not categorias:
        categorias = ["cambio_climatico"]   # fallback genérico

    return {
        "id":         make_id(url),
        "titulo":     titulo,
        "fecha":      d.isoformat(),
        "url":        url,
        "fuente":     "Presidencia de México — Estenográfica",
        "categorias": categorias,
        "fragmentos": fragmentos,
    }

# ---------------------------------------------------------------------------
def load_existing() -> list:
    if not os.path.exists(OUTPUT_FILE):
        return []
    try:
        with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
            return json.load(f).get("articulos", [])
    except Exception:
        return []

def save(articulos: list, nuevos: int):
    output = {
        "articulos": articulos,
        "_meta": {
            "fuente":      "Presidencia de México — Estenográficas mañanera",
            "total":       len(articulos),
            "nuevos_hoy":  nuevos,
            "actualizado": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        },
    }
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

# ---------------------------------------------------------------------------
def main():
    print("=== Scraper Presidencia — Mañaneras Estenográficas ===")
    today = date.today()
    print(f"Fecha: {today.isoformat()}")

    existing     = load_existing()
    existing_ids = {a["id"] for a in existing}
    print(f"Artículos existentes: {len(existing)}")

    # Ventana de 8 días para recuperar mañaneras que se hayan quedado atrás
    # (p. ej. tras un cambio de formato de URL). Se salta fines de semana y las
    # que ya existan (probando ambos formatos de id: con y sin cero).
    added = 0
    for delta in range(0, 8):
        d = today - timedelta(days=delta)
        if d.weekday() >= 5:  # skip weekends
            continue
        ids_try = {make_id(build_url(d, True)), make_id(build_url(d, False))}
        if ids_try & existing_ids:
            print(f"  {d}: ya existe")
            continue
        print(f"  Scrapeando {d}...", end=" ", flush=True)
        art = scrape_date(d)
        if art:
            existing.append(art)
            existing_ids.add(art["id"])
            added += 1
            print(f"✓ temas: {art['categorias']} | {len(art['fragmentos'])} fragmentos")
        else:
            print("— sin contenido ambiental o no publicada aún")
        time.sleep(1.5)

    existing.sort(key=lambda a: a.get("fecha", ""), reverse=True)
    existing = existing[:500]

    save(existing, added)
    print(f"\nTotal: {len(existing)}  |  Nuevos: {added}")
    print(f"Archivo: {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
