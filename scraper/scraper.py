#!/usr/bin/env python3
"""
SCOPE 3 — Scraper de noticias ambientales y regulatorias para México
Fuentes: Google News RSS por keyword, agrupadas por categoría/subcategoría
Output:  data/noticias.json  (se despliega automáticamente en GitHub Pages)
"""

import json, re, hashlib, os, time
from datetime import datetime, timezone
from pathlib import Path
import urllib.request
import xml.etree.ElementTree as ET

# ── Configuración ──────────────────────────────────────────────────────────────
OUTPUT_FILE = Path(__file__).parent.parent / "data" / "noticias.json"
MAX_PER_KEYWORD = 5          # artículos máximo por keyword
MAX_TOTAL = 500              # límite total del archivo
SLEEP_BETWEEN_REQUESTS = 1.5 # segundos entre peticiones (respetar rate limit)

# ── Categorías y keywords (de categorias_monitoreo.json) ──────────────────────
CATEGORIAS = {
    "energia": {
        "nombre": "Energía",
        "color": "#f59e0b",
        "subcategorias": {
            "pemex_petroleo": ["Pemex", "petróleo México", "refinería Pemex", "gasolina México",
                               "hidrocarburos México", "huachicoleo", "producción petrolera México",
                               "fracking México", "mezcla mexicana petróleo"],
            "cfe_electricidad": ["CFE electricidad", "apagón México", "tarifas eléctricas México",
                                 "generación eléctrica México", "subsidio energético México",
                                 "falla eléctrica México", "corte de luz México"],
            "energias_renovables": ["energía solar México", "energía eólica México",
                                    "transición energética México", "energía renovable México",
                                    "parque solar México", "parque eólico México",
                                    "certificado energía limpia México"],
            "mineria_recursos": ["litio México", "minería México", "concesión minera México",
                                 "gas natural México", "gasoducto México", "reforma energética México",
                                 "gas LP México", "secretaría de energía México"]
        }
    },
    "agua_medioambiente": {
        "nombre": "Agua y Medio Ambiente",
        "color": "#06b6d4",
        "subcategorias": {
            "gestion_hidrica": ["Conagua México", "sequía México", "acuífero México",
                                "presa México agua", "escasez de agua México",
                                "Ley de Aguas México", "cuenca hidrológica México"],
            "regulacion_ambiental": ["Semarnat", "Profepa", "impacto ambiental México",
                                     "NOM ambiental México", "área natural protegida México",
                                     "licencia ambiental México", "auditoría ambiental México"],
            "contaminacion_residuos": ["contaminación ambiental México", "residuo peligroso México",
                                       "derrame tóxico México", "emergencia ambiental México",
                                       "contaminación río México", "jales mineros México"],
            "biodiversidad": ["deforestación México", "Conafor México", "incendio forestal México",
                              "especie en riesgo México", "veda forestal México",
                              "manglares México", "biodiversidad México"]
        }
    },
    "economia_circular": {
        "nombre": "Economía Circular",
        "color": "#10b981",
        "subcategorias": {
            "residuos_solidos": ["residuo sólido urbano México", "reciclaje México",
                                 "relleno sanitario México", "gestión de residuos México",
                                 "separación de residuos México"],
            "plasticos_envases": ["plástico de un solo uso México", "prohibición plástico México",
                                  "bolsa de plástico México", "unicel México",
                                  "economía circular México", "envase retornable México"],
            "residuos_industriales": ["residuo peligroso industrial México", "CRETIB México",
                                      "confinamiento residuos México", "manifiesto residuos México"]
        }
    },
    "cambio_climatico": {
        "nombre": "Cambio Climático",
        "color": "#6366f1",
        "subcategorias": {
            "politica_climatica": ["cambio climático México", "LGCC México", "NDC México",
                                   "descarbonización México", "cero emisiones México",
                                   "política climática México", "adaptación climática México"],
            "mercado_carbono": ["impuesto carbono México", "mercado carbono México",
                                "bono de carbono México", "GEI México", "RETC México",
                                "huella de carbono México", "IEPS combustibles México"],
            "fenomenos_hidromet": ["huracán México", "tormenta tropical México",
                                   "inundación México", "sequía extrema México",
                                   "ola de calor México", "ciclón México"]
        }
    },
    "fiscal_regulatorio": {
        "nombre": "Fiscal y Regulatorio",
        "color": "#ef4444",
        "subcategorias": {
            "impuestos_ambientales": ["impuesto ecológico México", "impuesto ambiental México",
                                      "impuesto verde México", "impuesto emisiones México",
                                      "reforma fiscal ambiental México", "IEPS plaguicidas México"],
            "noms_federales": ["NOM México ambiental", "Diario Oficial de la Federación ambiental",
                               "Conamer regulación", "Mejora Regulatoria México",
                               "norma oficial mexicana ambiental", "consulta pública NOM"],
            "legislacion_ambiental": ["LGEEPA reforma", "ley ambiental México",
                                      "decreto ambiental México", "Semarnat acuerdo",
                                      "reforma legal ambiental México"]
        }
    },
    "industria_manufactura": {
        "nombre": "Industria y Manufactura",
        "color": "#78716c",
        "subcategorias": {
            "quimica_petroquimica": ["ANIQ México", "industria química México",
                                     "petroquímica México", "plaguicida registro México",
                                     "sustancia química regulación México"],
            "manufactura_parques": ["parque industrial México", "IMMEX México",
                                    "manufactura avanzada México", "industria automotriz México",
                                    "nearshoring México", "relocalización empresas México"],
            "industria_extractiva": ["Camimex México", "concesión minera suspendida",
                                     "impugnación concesión minera", "royalty minero México",
                                     "Ley Minera reforma México"]
        }
    },
    "agro_rural": {
        "nombre": "Agro y Desarrollo Rural",
        "color": "#84cc16",
        "subcategorias": {
            "agricultura_cultivos": ["Sader México", "Segalmex", "maíz transgénico México",
                                     "glifosato México", "soberanía alimentaria México",
                                     "sequía agrícola México", "pérdida cosecha México",
                                     "precio maíz México", "fertilizante México",
                                     "importación maíz México"],
            "ganaderia_pesca": ["ganadería México", "pesca México veda",
                                "acuacultura México", "Conapesca", "Senasica México",
                                "fiebre aftosa México", "exportación carne México"],
            "forestal": ["Conafor reforestación", "deforestación México",
                         "tala ilegal México", "incendio forestal México",
                         "cambio uso de suelo forestal México", "plan manejo forestal"],
            "agua_agricola": ["riego agrícola México", "distrito de riego México",
                              "pozos agrícolas México", "eficiencia hídrica agricultura"]
        }
    },
    "transporte_logistica": {
        "nombre": "Transporte y Logística",
        "color": "#3b82f6",
        "subcategorias": {
            "transporte_terrestre": ["verificación vehicular México", "NOM autotransporte",
                                     "SICT México", "emisiones vehiculares México",
                                     "transporte de carga México", "diesel México precio"],
            "infraestructura_obra": ["carretera concesión México", "obra pública México",
                                     "autopista México", "APP infraestructura México",
                                     "MIA carretera México", "Capufe México"],
            "puertos_comercio": ["puerto México", "Manzanillo contenedor", "importación México",
                                 "exportación México", "nearshoring México",
                                 "corredor interoceánico México", "aduana México"]
        }
    },
    "salud_publica": {
        "nombre": "Salud Pública",
        "color": "#ec4899",
        "subcategorias": {
            "regulacion_sanitaria": ["Cofepris", "registro sanitario México",
                                     "alerta sanitaria México", "etiquetado alimentos México",
                                     "octágono nutricional México", "desabasto medicamento México"],
            "sustancias_plaguicidas": ["plaguicida México", "glifosato prohibición México",
                                       "herbicida México", "Cicoplafest México",
                                       "registro plaguicidas México"]
        }
    },
    "comercio_inversion": {
        "nombre": "Comercio e Inversión",
        "color": "#f97316",
        "subcategorias": {
            "politica_comercial": ["T-MEC México", "USMCA México", "arancel México",
                                   "antidumping México", "panel T-MEC",
                                   "retaliación comercial México", "OMC México"],
            "inversion": ["inversión extranjera México", "IED México", "nearshoring México",
                          "parque industrial nuevo México", "Proinversión México",
                          "fideicomiso inversión México"]
        }
    },
    "politica_gobernanza": {
        "nombre": "Política y Gobernanza",
        "color": "#8b5cf6",
        "subcategorias": {
            "ejecutivo_federal": ["Claudia Sheinbaum decreto", "decreto presidencial México",
                                  "gabinete federal México", "Semarnat acuerdo",
                                  "presupuesto federal México ambiental"],
            "legislativo_federal": ["Cámara de Diputados ley ambiental", "Senado México ambiental",
                                    "iniciativa ley ambiental México", "Gaceta Parlamentaria ambiental",
                                    "reforma constitucional ambiental México"],
            "gobiernos_estatales": ["gaceta oficial estatal ambiental", "ley estatal ambiental",
                                    "decreto estatal ambiental", "congreso local ambiental México"]
        }
    }
}

# Mapeo de keywords/términos a estados mexicanos
ESTADOS_KEYWORDS = {
    "Aguascalientes": ["Aguascalientes"],
    "Baja California": ["Baja California", "Tijuana", "Mexicali", "Ensenada"],
    "Baja California Sur": ["Baja California Sur", "La Paz BCS", "Los Cabos"],
    "Campeche": ["Campeche"],
    "Chiapas": ["Chiapas", "Tuxtla Gutiérrez", "San Cristóbal de las Casas"],
    "Chihuahua": ["Chihuahua", "Ciudad Juárez", "Juárez Chihuahua"],
    "Ciudad de México": ["Ciudad de México", "CDMX", "capitalina", "Jefatura de Gobierno"],
    "Coahuila": ["Coahuila", "Saltillo", "Torreón"],
    "Colima": ["Colima"],
    "Durango": ["Durango"],
    "Guanajuato": ["Guanajuato", "León Guanajuato", "Irapuato", "Celaya"],
    "Guerrero": ["Guerrero", "Acapulco", "Chilpancingo"],
    "Hidalgo": ["Hidalgo", "Pachuca"],
    "Jalisco": ["Jalisco", "Guadalajara", "Zapopan"],
    "México": ["Estado de México", "Edomex", "Toluca", "Ecatepec", "Naucalpan"],
    "Michoacán": ["Michoacán", "Morelia", "Uruapan"],
    "Morelos": ["Morelos", "Cuernavaca"],
    "Nayarit": ["Nayarit", "Tepic"],
    "Nuevo León": ["Nuevo León", "Monterrey", "regiomontano"],
    "Oaxaca": ["Oaxaca"],
    "Puebla": ["Puebla", "Angelópolis"],
    "Querétaro": ["Querétaro"],
    "Quintana Roo": ["Quintana Roo", "Cancún", "Playa del Carmen", "Tulum"],
    "San Luis Potosí": ["San Luis Potosí", "SLP"],
    "Sinaloa": ["Sinaloa", "Culiacán", "Mazatlán"],
    "Sonora": ["Sonora", "Hermosillo", "Guaymas", "Nogales Sonora"],
    "Tabasco": ["Tabasco", "Villahermosa"],
    "Tamaulipas": ["Tamaulipas", "Matamoros", "Tampico", "Reynosa"],
    "Tlaxcala": ["Tlaxcala"],
    "Veracruz": ["Veracruz", "Xalapa", "Coatzacoalcos"],
    "Yucatán": ["Yucatán", "Mérida"],
    "Zacatecas": ["Zacatecas"]
}


def google_news_rss(query: str) -> list[dict]:
    """Obtiene artículos de Google News RSS para una query."""
    q = urllib.parse.quote(query)
    url = f"https://news.google.com/rss/search?q={q}&hl=es-419&gl=MX&ceid=MX:es-419"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (SCOPE3-Monitor/1.0)"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            content = resp.read()
        root = ET.fromstring(content)
        items = []
        for item in root.findall(".//item")[:MAX_PER_KEYWORD]:
            title = item.findtext("title", "").strip()
            link = item.findtext("link", "").strip()
            pub_date = item.findtext("pubDate", "")
            source = item.findtext("source", "")
            # Limpiar título (Google News a veces añade " - Fuente" al final)
            if " - " in title:
                parts = title.rsplit(" - ", 1)
                title = parts[0].strip()
                if not source:
                    source = parts[1].strip()
            # Parsear fecha
            fecha_iso = ""
            if pub_date:
                try:
                    from email.utils import parsedate_to_datetime
                    fecha_iso = parsedate_to_datetime(pub_date).isoformat()
                except Exception:
                    fecha_iso = ""
            items.append({"titulo": title, "url": link, "fuente": source,
                          "fecha_publicacion": fecha_iso})
        return items
    except Exception as e:
        print(f"  ⚠ Error en '{query}': {e}")
        return []


def detect_state(titulo: str) -> str | None:
    """Detecta el estado mexicano mencionado en el título."""
    t = titulo.lower()
    for estado, kws in ESTADOS_KEYWORDS.items():
        for kw in kws:
            if kw.lower() in t:
                return estado
    return None


def make_id(titulo: str, url: str) -> str:
    return hashlib.md5((titulo + url).encode()).hexdigest()[:12]


def main():
    import urllib.parse  # noqa – needed inside google_news_rss
    print(f"🔍 SCOPE 3 Scraper — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")

    # Cargar noticias existentes para deduplicar
    existing_ids: set[str] = set()
    existing: list[dict] = []
    if OUTPUT_FILE.exists():
        try:
            with open(OUTPUT_FILE, encoding="utf-8") as f:
                existing = json.load(f)
            existing_ids = {a.get("id", "") for a in existing}
            print(f"  📂 {len(existing)} artículos existentes cargados")
        except Exception:
            existing = []

    nuevos: list[dict] = []

    for cat_clave, cat in CATEGORIAS.items():
        for sub_clave, keywords in cat["subcategorias"].items():
            for kw in keywords:
                print(f"  🔎 [{cat['nombre']} / {sub_clave}] {kw}")
                arts = google_news_rss(kw)
                for a in arts:
                    art_id = make_id(a["titulo"], a["url"])
                    if art_id in existing_ids:
                        continue
                    estado = detect_state(a["titulo"])
                    nuevos.append({
                        "id": art_id,
                        "titulo": a["titulo"],
                        "url": a["url"],
                        "fuente": a["fuente"],
                        "fecha_publicacion": a["fecha_publicacion"],
                        "categoria": cat_clave,
                        "categoria_nombre": cat["nombre"],
                        "subcategoria": sub_clave,
                        "keyword": kw,
                        "estado": estado,
                        "scrapeado_en": datetime.now(timezone.utc).isoformat()
                    })
                    existing_ids.add(art_id)
                time.sleep(SLEEP_BETWEEN_REQUESTS)

    print(f"\n✅ {len(nuevos)} artículos nuevos encontrados")

    # Combinar: nuevos primero, luego existentes, limitar total
    combined = nuevos + existing
    combined = sorted(combined, key=lambda x: x.get("fecha_publicacion", ""), reverse=True)
    combined = combined[:MAX_TOTAL]

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(combined, f, ensure_ascii=False, indent=2)

    print(f"💾 Guardado: {OUTPUT_FILE}  ({len(combined)} artículos totales)")


if __name__ == "__main__":
    import urllib.parse
    main()
