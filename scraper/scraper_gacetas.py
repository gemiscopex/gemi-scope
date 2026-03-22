#!/usr/bin/env python3
"""
SCOPE - Scraper de Actividad Legislativa Federal
Fuentes: Gaceta Parlamentaria (Diputados) + Gaceta del Senado
Filtro:  Solo iniciativas relevantes a los temas SCOPE
Salida:  data/gaceta-federal.json
"""

import json
import re
import time
import os
from datetime import datetime, timedelta
from urllib.parse import urljoin

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:
    print("Instala dependencias: pip install requests beautifulsoup4")
    raise

# ──────────────────────────────────────────────
# KEYWORDS SCOPE (temas que monitoreamos)
# ──────────────────────────────────────────────
SCOPE_KEYWORDS = [
    # Agua
    "agua", "hidrico", "hídrico", "acuifero", "acuífero", "cuenca", "riego",
    "saneamiento", "potable", "aguanacional", "ley de aguas",
    # Energía y emisiones
    "energia", "energía", "electrica", "eléctrica", "electricidad",
    "renovable", "solar", "eolica", "eólica", "geotermia", "hidrogeno",
    "hidrogeno verde", "cfe", "pemex", "hidrocarburo", "petroleo", "petróleo",
    "gas natural", "gas lp", "carbon", "carbono", "emision", "emisión",
    "huella de carbono", "transicion energetica", "transición energética",
    "generacion electrica", "generación eléctrica",
    # Medio ambiente / ecología
    "medio ambiente", "ambiental", "ecologia", "ecología", "ecologico",
    "ecosistema", "biodiversidad", "flora", "fauna", "vida silvestre",
    "areas naturales protegidas", "áreas naturales protegidas",
    "lgeepa", "semarnat", "profepa",
    # Residuos y economía circular
    "residuos", "basura", "reciclaje", "reciclado", "plastico", "plástico",
    "plasticos", "plásticos", "envase", "embalaje", "relleno sanitario",
    "economia circular", "economía circular", "reutilizacion", "reutilización",
    "residuo solido", "residuo sólido", "lgpgir",
    # Cambio climático
    "cambio climatico", "cambio climático", "climatico", "climático",
    "calentamiento global", "carbono", "ndc", "paris", "cop",
    "lgcc", "adaptacion", "adaptación", "mitigacion", "mitigación",
    # Contaminación
    "contaminacion", "contaminación", "contaminante", "tóxico", "toxico",
    "quimico", "químico", "sustancia peligrosa", "cromo", "plomo", "mercurio",
    "gei", "gases efecto invernadero",
    # Forestal / suelo
    "forestal", "bosque", "selva", "deforestacion", "deforestación",
    "reforestacion", "reforestación", "suelo", "erosion", "erosión",
    "lgdfs", "conafor",
    # Minería
    "mineria", "minería", "minero", "litio", "concesion minera",
    "concesión minera", "extraccion", "extracción",
    # Agricultura / agro
    "agricultura", "agricola", "agrícola", "agro", "campo", "campesino",
    "fertilizante", "plaguicida", "pesticida", "glifosato", "transgenico",
    "transgénico", "maiz", "maíz", "sader", "segalmex", "cosecha",
    "sequía", "sequia", "temporal", "ganaderia", "ganadería",
    # Fiscal / impuestos ambientales
    "impuesto ambiental", "impuesto verde", "derecho ambiental",
    "isan", "ieps", "carbon tax", "impuesto ecologico", "impuesto ecológico",
    # Industria química / procesos
    "industria quimica", "industria química", "aniq", "quimico",
    "clorofluorocarbono", "biocombustible",
]

SCOPE_KEYWORDS_LOWER = [k.lower() for k in SCOPE_KEYWORDS]

# Excluir iniciativas claramente fuera de scope
EXCLUDE_KEYWORDS = [
    "reforma judicial", "poder judicial", "suprema corte", "magistrado",
    "electoral", "partidos politicos", "partidos políticos", "candidato",
    "eleccion", "elección", "guardia nacional", "seguridad publica",
    "seguridad pública", "fuerzas armadas", "ejercito", "ejército",
    "pension", "pensión", "imss", "issste", "seguro social",
    "educacion basica", "educación básica",
]

EXCLUDE_LOWER = [k.lower() for k in EXCLUDE_KEYWORDS]

MES_ACTUAL = datetime.now().strftime("%Y-%m")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "es-MX,es;q=0.9,en;q=0.8",
}


def es_relevante(texto):
    """Devuelve True si el texto contiene al menos un keyword SCOPE
       y ninguno de exclusión dominante."""
    t = texto.lower()
    # Excluir primero
    if any(ex in t for ex in EXCLUDE_LOWER):
        return False
    return any(kw in t for kw in SCOPE_KEYWORDS_LOWER)


def categoria(texto):
    """Devuelve la categoría principal del texto."""
    t = texto.lower()
    if any(k in t for k in ["agua", "hidrico", "acuifero", "cuenca", "riego", "potable"]):
        return "Agua"
    if any(k in t for k in ["energia", "energía", "electrica", "renovable", "solar", "eolica", "cfe", "pemex", "gas"]):
        return "Energía"
    if any(k in t for k in ["residuo", "basura", "reciclaje", "plastico", "plástico", "economia circular"]):
        return "Residuos"
    if any(k in t for k in ["cambio climatico", "cambio climático", "carbon", "emisión", "emision"]):
        return "Clima"
    if any(k in t for k in ["mineria", "minería", "litio", "concesion minera"]):
        return "Minería"
    if any(k in t for k in ["agricol", "agro", "campo", "ganaderia", "maiz", "cosecha"]):
        return "Agro"
    if any(k in t for k in ["quimico", "industria quimica", "contaminacion", "contaminación"]):
        return "Industria"
    return "Ambiental"


# ──────────────────────────────────────────────
# DIPUTADOS
# ──────────────────────────────────────────────
def scrape_diputados(max_paginas=3):
    """Scraping de gaceta.diputados.gob.mx — usa el frame gp_hoy.html del día actual."""
    base = "https://gaceta.diputados.gob.mx/"
    resultados = []
    session = requests.Session()
    session.headers.update(HEADERS)

    # La Gaceta usa frames — el contenido real está en gp_hoy.html
    # También revisamos los últimos días del mes actual
    now = datetime.now()
    urls_a_probar = ["https://gaceta.diputados.gob.mx/gp_hoy.html"]
    for dias_atras in range(1, 22):
        d = now - timedelta(days=dias_atras)
        # Solo días de lunes a viernes
        if d.weekday() < 5:
            urls_a_probar.append(
                f"https://gaceta.diputados.gob.mx/PDF/66/{d.year}/{d.strftime('%b').lower()}/"
                f"{d.strftime('%Y%m%d')}.html"
            )

    vistos = set()
    for url in urls_a_probar[:8]:
        try:
            r = session.get(url, timeout=12)
            if not r.ok:
                continue
            # Decodificar correctamente (la gaceta usa iso-8859-1)
            r.encoding = "iso-8859-1"
            soup = BeautifulSoup(r.text, "html.parser")

            # Extraer todos los textos con links
            for a in soup.find_all("a", href=True):
                texto_a = a.get_text(separator=" ", strip=True)
                if len(texto_a) < 15:
                    continue
                full_url = urljoin(base, a["href"])
                if es_relevante(texto_a):
                    titulo_clean = re.sub(r"\s+", " ", texto_a).strip()[:300]
                    if titulo_clean not in vistos:
                        vistos.add(titulo_clean)
                        resultados.append({
                            "titulo": titulo_clean,
                            "url": full_url,
                            "fecha": now.strftime("%Y-%m-%d"),
                            "categoria": categoria(titulo_clean),
                            "camara": "diputados",
                        })

            # También textos de párrafos sin link directo
            for tag in soup.find_all(["p", "li", "td"]):
                texto = tag.get_text(separator=" ", strip=True)
                if len(texto) < 20 or len(texto) > 500:
                    continue
                if not es_relevante(texto):
                    continue
                link_tag = tag.find("a", href=True)
                url_item = urljoin(base, link_tag["href"]) if link_tag else url
                titulo_clean = re.sub(r"\s+", " ", texto).strip()[:300]
                if titulo_clean not in vistos:
                    vistos.add(titulo_clean)
                    resultados.append({
                        "titulo": titulo_clean,
                        "url": url_item,
                        "fecha": now.strftime("%Y-%m-%d"),
                        "categoria": categoria(titulo_clean),
                        "camara": "diputados",
                    })
        except Exception as e:
            continue

    print(f"  [Diputados] {len(resultados)} iniciativas SCOPE encontradas")
    return resultados[:20]


# ──────────────────────────────────────────────
# SENADO
# ──────────────────────────────────────────────
def scrape_senado(max_paginas=3):
    """Scraping de senado.gob.mx/66/gaceta_del_senado — iniciativas del mes."""
    base_url = "https://www.senado.gob.mx/66/gaceta_del_senado"
    resultados = []
    session = requests.Session()
    session.headers.update(HEADERS)

    try:
        r = session.get(base_url, timeout=15)
        if not r.ok:
            print(f"  [Senado] HTTP {r.status_code}")
            return []

        soup = BeautifulSoup(r.text, "html.parser")

        links = []
        # Buscar links en la página principal
        for a in soup.find_all("a", href=True):
            href = a["href"]
            texto_a = a.get_text(strip=True)
            if not href or len(texto_a) < 8:
                continue
            full_url = urljoin("https://www.senado.gob.mx", href)
            if es_relevante(texto_a):
                links.append((texto_a, full_url))

        for tag in soup.find_all(["p", "li", "td", "h3", "h4", "div"]):
            texto = tag.get_text(strip=True)
            link_tag = tag.find("a", href=True)
            url_item = urljoin("https://www.senado.gob.mx", link_tag["href"]) if link_tag else base_url
            if 15 < len(texto) < 500 and es_relevante(texto):
                links.append((texto, url_item))

        vistos = set()
        for titulo, url in links:
            titulo_clean = re.sub(r"\s+", " ", titulo).strip()[:300]
            if titulo_clean in vistos or len(titulo_clean) < 15:
                continue
            vistos.add(titulo_clean)
            resultados.append({
                "titulo": titulo_clean,
                "url": url,
                "fecha": datetime.now().strftime("%Y-%m-%d"),
                "categoria": categoria(titulo_clean),
                "camara": "senado",
            })

    except Exception as e:
        print(f"  [Senado] Error: {e}")

    print(f"  [Senado] {len(resultados)} iniciativas SCOPE encontradas")
    return resultados[:20]


# ──────────────────────────────────────────────
# GUARDAR JSON
# ──────────────────────────────────────────────
def guardar(diputados, senado):
    os.makedirs("data", exist_ok=True)
    ruta = "data/gaceta-federal.json"

    # Cargar datos previos del mes si existen
    previo = {"diputados": [], "senado": []}
    if os.path.exists(ruta):
        try:
            with open(ruta, "r", encoding="utf-8") as f:
                previo = json.load(f)
            # Solo conservar del mes actual
            previo["diputados"] = [
                x for x in previo.get("diputados", [])
                if (x.get("fecha", "") or "").startswith(MES_ACTUAL)
            ]
            previo["senado"] = [
                x for x in previo.get("senado", [])
                if (x.get("fecha", "") or "").startswith(MES_ACTUAL)
            ]
        except Exception:
            pass

    # Combinar: nuevos primero, evitar duplicados por título
    def merge(existentes, nuevos):
        titulos = {x["titulo"] for x in existentes}
        for n in nuevos:
            if n["titulo"] not in titulos:
                existentes.append(n)
                titulos.add(n["titulo"])
        return existentes

    data = {
        "ultima_actualizacion": datetime.now().isoformat(),
        "mes": MES_ACTUAL,
        "diputados": merge(diputados, previo["diputados"]),
        "senado": merge(senado, previo["senado"]),
    }

    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"\nGuardado en {ruta}")
    print(f"   Diputados: {len(data['diputados'])} iniciativas")
    print(f"   Senado:    {len(data['senado'])} iniciativas")
    return ruta


# ──────────────────────────────────────────────
# SUBIR A GITHUB
# ──────────────────────────────────────────────
def subir_github(ruta_local, token, repo="gemiscopex/gemi-scope"):
    """Sube el JSON a GitHub Pages via REST API."""
    import base64
    api = f"https://api.github.com/repos/{repo}/contents/data/gaceta-federal.json"
    hdrs = {
        "Authorization": f"token {token}",
        "Content-Type": "application/json",
    }

    with open(ruta_local, "rb") as f:
        contenido_b64 = base64.b64encode(f.read()).decode()

    # Obtener SHA actual si existe
    sha = None
    try:
        r = requests.get(api, headers=hdrs, timeout=10)
        if r.ok:
            sha = r.json().get("sha")
    except Exception:
        pass

    payload = {
        "message": f"Gacetas federales SCOPE — {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "content": contenido_b64,
    }
    if sha:
        payload["sha"] = sha

    r = requests.put(api, headers=hdrs, json=payload, timeout=30)
    if r.ok:
        print(f"OK - Subido a GitHub ({repo})")
    else:
        print(f"ERROR GitHub: {r.status_code} - {r.text[:200]}")


# ──────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Scraper Gacetas Federales SCOPE")
    parser.add_argument(
        "--token",
        default=os.environ.get("GITHUB_TOKEN", ""),
        help="Token de GitHub (o set GITHUB_TOKEN env var)",
    )
    parser.add_argument("--no-upload", action="store_true", help="Solo guardar local, no subir")
    args = parser.parse_args()

    print("-----------------------------------")
    print("  SCOPE - Scraper Legislativo Federal")
    print(f"  Mes: {MES_ACTUAL}")
    print("-----------------------------------\n")

    print("[1/2] Scraping Camara de Diputados...")
    dip = scrape_diputados()
    time.sleep(2)

    print("\n[2/2] Scraping Senado de la Republica...")
    sen = scrape_senado()

    ruta = guardar(dip, sen)

    if not args.no_upload:
        if args.token:
            print("\nSubiendo a GitHub Pages...")
            subir_github(ruta, args.token)
        else:
            print("\nSin token GitHub. Usa --token o GITHUB_TOKEN para subir automaticamente.")
            print("Archivo guardado localmente en:", ruta)
