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

- Tema oscuro terminal en toda la plataforma (mapa de puntos, paleta, IBM Plex Mono para datos).
- **Helvetica en toda la plataforma** — texto general en `Helvetica Neue / Helvetica / Arial`;
  IBM Plex Mono se conserva solo en etiquetas técnicas, fechas y números (es lo
  que da el carácter de instrumento; si se quiere Helvetica absoluta, es una línea).
- Scraper automático diario (sesiones de comisiones + fotos de legisladores).
- Mi Consola v1 (wizard 5 pasos, filtrado client-side).

---

## Etapa 1 — Pulido del dashboard (solo frontend; los datos ya existen)

Objetivo: que el dashboard se vea y lea como noticiero profesional. Sin scrapers nuevos.

| # | Qué | Detalle | Esfuerzo |
|---|-----|---------|----------|
| 1.1 `[1]` | Estado en Últimas Noticias | El campo `estado` ya viene en `noticias.json`; se muestra como etiqueta junto a la categoría (Agua · Nayarit). | S |
| 1.2 `[3]` | Banner semanal | Franja arriba de noticias: "Semana del 20 al 24 de julio" + noticia principal de la semana + semáforo de riesgo (verde/ámbar/rojo). La principal se elige por relevancia (categoría con más señal + recencia). | M |
| 1.3 `[2]` | Mañaneras como cintillo | El Observatorio del Ejecutivo se convierte en banner tipo chyron de noticiero (scroll horizontal continuo de citas de la CSP); deja de ocupar una tarjeta completa. | M |
| 1.4 `[4]` | Widget Congreso unificado | Una sola tarjeta Diputados + Senado. Cada fila: logo del partido del promovente + **solo la ley en discusión** (ej. "Ley de Aguas Nacionales") extraída del título; en Puntos de Acuerdo, el texto después de "por el que se exhorta". | M |
| 1.5 `[15]` | Quitar Centro de Alertas | Se elimina la pestaña; las alertas viven en el mapa (ya están ahí como señal territorial). | S |
| 1.6 `[11]` | NOMs con nomenclatura completa | Auditoría de las 12+ NOMs listadas: clave completa con año (NOM-001-SEMARNAT-2021, no NOM-001-SEMARNAT). | S |
| 1.7 `[19]` | Radares como botón discreto | Sale del nav principal; se vuelve un botón pequeño con pulso sutil (hidden button de alto valor). | S |

## Etapa 2 — Nueva arquitectura de navegación (mini menús)

Objetivo: navegación de plataforma seria — menús desplegables, jerarquía regulatoria clara.

| # | Qué | Detalle | Esfuerzo |
|---|-----|---------|----------|
| 2.1 `[18]` | Patrón de mini menús | Componente único de dropdown para el nav: clic/hover arriba → despliega. Base para 2.2–2.5. | M |
| 2.2 `[10]` | "Regulación" en vez de "Legislación" | Con submenú: Internacional · Nacional · Estatal · Acuerdos · NOMs. | M |
| 2.3 `[9]` | Acuerdos internacionales | Alta de contenido: Acuerdo de París, Escazú, Kigali, Montreal, CBD… con estatus de México en cada uno. | M |
| 2.4 `[17]` | Botón DOF con hover | En el nav: hover → publicaciones de HOY en el DOF filtradas por nuestros temas (dato ya existe en `dof.json`); clic → nota oficial. | M |
| 2.5 `[14]` | "Actores" en vez de "Congreso Federal" | Además del Congreso: organigrama ambiental federal (SEMARNAT, SENER, Economía, CONAGUA, PROFEPA, ASEA, CONAFOR…) y titulares de medio ambiente de las 32 entidades. **Requiere levantar datos** (titulares + fotos oficiales) → scraper de directorios oficiales. | L |

## Etapa 3 — Nuevas fuentes de datos

Objetivo: profundidad que nadie más tiene. Cada fuente entra al scraper diario.

| # | Qué | Detalle | Esfuerzo |
|---|-----|---------|----------|
| 3.1 `[5]` | Monitoreo internacional | Nueva sección en noticias: lo que hoy se descarta por el filtro "solo México" (Mongabay LatAm, etc.) se reclasifica como Internacional en vez de tirarse; se agregan feeds globales (UE, COP, plásticos). | M |
| 3.2 `[6]` | Vocación industrial por estado | Muere "Riesgo Sectorial"; nace "Sector Industrial" con la vocación económica real de cada entidad (censos económicos INEGI / Data México). | M |
| 3.3 `[8]` | Perfil de estado estilo Data México | Población, PEA, unidades económicas, sectores principales — API pública de Data México / INEGI. | M |
| 3.4 `[7]` | DatosGob ambiental | Inventario de datasets ambientales de datos.gob.mx (emisiones, agua, residuos) y qué métricas alimentan el perfil de estado y los radares. | L |
| 3.5 `[12]` | Tracker PNIC de NOMs | Estado de cada NOM en el Programa Nacional de Infraestructura de la Calidad (CONAMER/DOF): en revisión, consulta pública, publicada. Flag visible de si **GEMI participa activamente** en cada una. | L |
| 3.6 `[13]` | Documentos complementarios de NOMs | Mini menú expandible por NOM en la misma página: norma, modificaciones, acuerdos, guías, respuestas a comentarios. | M |
| 3.7 `[20]` | Materiales prohibidos por estado | Dataset propio: prohibiciones de plásticos/materiales por entidad (derivado de leyes estatales que ya monitoreamos + investigación puntual). Visible en el mapa/dashboard por estado. | L |

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
