# SCOPE — Roadmap de producto

Organización de las notas de producto en etapas ejecutables. Cada punto conserva
el número de la nota original entre corchetes `[N]` para trazabilidad.

**Principios de ejecución**
- Cada etapa se libera completa antes de pasar a la siguiente: el sitio en vivo
  nunca queda a medias.
- Frontend primero cuando el dato ya existe; scraper nuevo solo cuando la etapa
  lo exige.
- Todo dato nuevo entra al pipeline automático (GitHub Actions diario) desde el
  día uno — nada capturado a mano.

---

## ✅ Hecho (previo a este roadmap)

- **Tema blanco** (el oscuro se probó y se descartó; se conservan el mapa de
  puntos, Helvetica y IBM Plex Mono para etiquetas técnicas).
- **Helvetica en toda la plataforma** — texto general en `Helvetica Neue / Helvetica / Arial`.
- Scraper automático diario (sesiones de comisiones + fotos de legisladores).
- Mi Consola v1 (wizard 5 pasos, filtrado client-side).

## ✅ Etapa 1 — COMPLETADA (2026-07-21)

Todos los puntos entregados: estado en noticias `[1]`, banner semanal con
semáforo (contenido editable en `data/semana.json`) `[3]`, mañaneras como
cintillo de noticiero `[2]`, widget Congreso unificado con logos de partido y
ley en discusión `[4]`, Centro de Alertas fuera del nav `[15]`, NOMs con
nomenclatura completa `[11]`, Radares como botón pulsante discreto `[19]`.

---

## ✅ Etapa 2 — COMPLETADA (2026-07-22)

- 2.1 `[18]` Patrón de mini menús en el nav (hover → dropdown). ✔
- 2.2 `[10]` "Regulación" reemplaza a Legislación+Normas, con submenú Nacional · Estatal · Internacional/Acuerdos · NOMs. ✔
- 2.3 `[9]` 10 acuerdos internacionales con estatus de México (París, Escazú, Kigali, Montreal, CBD, Basilea, Estocolmo, Rotterdam, Ramsar, CITES). ✔
- 2.4 `[17]` Botón DOF ▾ con hover: publicaciones de hoy/recientes filtradas por nuestros temas; clic abre la nota. ✔
- 2.5 `[14]` "Actores" reemplaza a Congreso Federal: gabinete ambiental federal (9 titulares verificados: SEMARNAT, CONAGUA, PROFEPA, SENER, Economía, SADER, CONAFOR, CONANP, ASEA) + comisiones del Congreso. **Pendiente para Etapa 3:** titulares de medio ambiente de las 32 entidades (requiere scraper de directorios).

## ✅ Etapa 3 — COMPLETADA v1 (2026-07-22)

- 3.1 `[5]` Toggle **México · Internacional** en Últimas Noticias: lo que el filtro "solo México" descartaba ahora se clasifica como Internacional. ✔
- 3.2 `[6]` "Sector Industrial" reemplaza a Riesgo Sectorial: vocación industrial rankeada por estado. ✔
- 3.3 `[8]` Perfil estilo Data México en el panel de estado: población Censo 2020, % nacional, capital (`data/perfil-estados.json`). ✔
- 3.4 `[7]` **DatosGob**: scraper del CKAN oficial (`scraper/scraper_datosgob.py`, en el auto-update diario) → bloque "Datos Abiertos Ambientales" en Radares con ~25 datasets por tema. ✔
- 3.5 `[12]` Estatus PNIC por NOM (derivado de tipo; estructura `NOM_EXTRA` lista para el scraper CONAMER) + flag de participación GEMI. ✔ estructura
- 3.6 `[13]` Mini menú expandible por NOM: estatus PNIC, GEMI, documentos (DOF + Catálogo Nacional de Regulaciones). ✔
- 3.7 `[20]` `data/materiales-prohibidos.json` v1 con 10 entidades documentadas, visible en el perfil de cada estado. ✔ v1

**Deuda de datos (para cerrar la etapa al 100%):**
1. PEA y unidades económicas por estado → requiere token gratuito de la API INEGI (registro en inegi.org.mx; el JSON ya tiene los campos en null).
2. Estatus PNIC real por NOM → scraper de CONAMER (hoy se deriva de vigente/proyecto).
3. Flags "GEMI activo" por NOM → **lo define el equipo GEMI** (llenar `NOM_EXTRA` en index.html o mover a JSON).
4. Materiales prohibidos: 22 entidades restantes por documentar.
5. Titulares ambientales de las 32 entidades (arrastrado de Etapa 2.5).

## Etapa 4 — Consola avanzada y membresía

Objetivo: convertir la personalización en el producto de pago.

| # | Qué | Detalle | Esfuerzo |
|---|-----|---------|----------|
| 4.1 `[12]` | Mis NOMs en la consola | Seleccionar NOMs propias en el wizard; la consola muestra su estatus PNIC y documentos. Depende de 3.5/3.6. | M |
| 4.2 `[16]` | Campanas de alerta | Cada aspecto regulatorio (NOM, iniciativa, comisión, estado) lleva una 🔔; suscribirse lo agrega a las alertas de tu consola. Base del futuro envío por correo. | L |
| 4.3 `[20]` | Materiales prohibidos en consola | Módulo que cruza tus entidades seleccionadas con las prohibiciones de materiales. Depende de 3.7. | M |
| 4.4 `[21]` | Membresía GEMI | Ventana/área de miembro: todo lo anterior consultable, login real (la config de consola ya está preparada para atarse a usuario). | L |

---

**Orden recomendado:** Etapa 1 completa (una semana de trabajo enfocado, todo
visible de inmediato) → 2.1–2.4 → 2.5 y Etapa 3 en paralelo (scrapers) → Etapa 4
cuando exista login.

Esfuerzo: S = horas · M = 1–2 días · L = requiere investigación de fuentes + scraper.
