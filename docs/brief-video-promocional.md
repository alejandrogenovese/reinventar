# ReinventAR — Brief para video promocional

> Documento de trabajo para producir un video corto que muestre lo que hace la app.
> Todo lo que está acá existe y funciona hoy; no agregar promesas que no estén en este brief.

---

## 1. En una frase

**ReinventAR es tu copiloto para AWS re:Invent: graba y resume cada charla en español, te arma la agenda ideal y te prepara para conversar con quien la da.**

## 2. Para quién

Profesionales de tecnología de habla hispana (en particular de Argentina y del mundo financiero) que viajan a AWS re:Invent en Las Vegas y quieren volver con conocimiento aprovechable, no con 40 fotos de slides y notas sueltas.

## 3. El problema

- re:Invent tiene **1.759 charlas** en 5 días, repartidas en varios hoteles del Strip. Elegir bien es casi imposible.
- Las charlas son en inglés, rápidas y densas. Tomar notas mientras escuchás hace que te pierdas la mitad.
- Las mejores oportunidades están en los pasillos: hablar con el speaker o con la gente de una empresa. Pero llegás sin saber quiénes son ni qué preguntarles.
- La señal en las salas es mala: cualquier app que dependa de internet en vivo falla justo cuando la necesitás.

## 4. La promesa (los 3 pilares)

| Pilar | Qué resuelve | Frase para el video |
|---|---|---|
| **Grabar y entender** | Grabás la charla con el celular; la app la transcribe, la traduce y la resume en español. | "Escuchá. Del resto se encarga ReinventAR." |
| **Elegir bien** | Te recomienda sesiones según tu perfil y te arma un itinerario por día, sin choques de horario. | "Tu re:Invent, armado para vos." |
| **Llegar preparado** | Fichas de cada charla, speaker y empresa, y un resumen de "Para conversar" generado por IA. | "Sabé con quién estás hablando antes de saludar." |

---

## 5. Funcionalidades (todas reales, para mostrar en pantalla)

### 5.1 Inicio — "Hoy"
- Muestra **la charla que está pasando ahora** y **la siguiente** según tu itinerario, en hora de Las Vegas.
- Botón naranja **"Grabar esta charla"**: un toque y ya estás grabando, con título, código, sala y speakers cargados.
- Si la charla ya está grabada, el botón ofrece "Seguir grabando" o "Ver grabación" en lugar de duplicarla.
- Debajo: el resto del día y tus grabaciones.

### 5.2 Grabación pensada para la sala
- Graba con el micrófono del celular o con un **micrófono inalámbrico DJI** (lo detecta solo).
- **Medidor de nivel de 24 segmentos** (verde, ámbar y rojo) que indica "Bien", "Alto" o "Satura".
- **Contador grande** y estado claro: "Grabando" con un punto rojo que titila, o "En pausa".
- **Modo sala**: pantalla negra con el contador tenue, para no molestar a nadie en la oscuridad y ahorrar batería.
- **Funciona sin señal**: el audio se guarda en el celular en pedazos y se sube solo cuando vuelve la conexión. Si se corta, se retoma donde quedó.

### 5.3 Transcripción, traducción y resumen
- Transcripción automática del audio en inglés.
- **Traducción al español en bloques de 15 segundos**, como subtítulos, con el original en inglés al lado.
- La traducción respeta los nombres propios de la charla: speakers, empresas y servicios.
- **Resumen estructurado**:
  - **TL;DR**.
  - **Anuncios** con el servicio de AWS destacado.
  - **Puntos clave**.
  - **Servicios mencionados**.
  - **Frases** textuales con su minuto.
  - **"Versus lo prometido"**: compara lo que se dijo con el abstract oficial de la charla.
  - **"Para llevar a Galicia"**: qué aplicar en el trabajo propio.
- Exportación a **Markdown** con un toque.

### 5.4 Itinerario con IA
- Un cuestionario corto: rol, experiencia, intereses y qué te interesa con tus palabras.
- La IA recomienda sesiones, **explica por qué te sirve cada una** y arma la agenda por día.
- **Resuelve los choques de horario** y te muestra qué quedó afuera y por qué.
- **Mapa** con las sedes del día, un color por día.
- Podés **bloquear** las que no querés perder (sobreviven si regenerás) o **quitarlas con "Deshacer"**.

### 5.5 Buscar — dos modos en una pantalla
- **Filtrar**:
  - Búsqueda en vivo, y **"Convertir en filtros"**: escribís "bancos el martes" y la app lo traduce a filtros (sector Finanzas + día martes).
  - **Panel de filtros** que sube desde abajo, con **conteo en vivo** en cada opción y el botón "Ver 89 charlas".
  - Filtros por sector, día, empresa, tópico, sede, nivel, servicio de AWS, seniority y nuevos lanzamientos.
  - **Temas emergentes**: 30 temas descubiertos por IA agrupando todas las charlas por significado, no por las etiquetas oficiales.
  - **Agrupar por** cualquier faceta, por ejemplo Finanzas → empresa → charlas.
- **Preguntar**:
  - Un chat sobre todo el catálogo.
  - Preguntás "¿qué bancos cuentan cómo usan agentes con Bedrock?" y responde **citando las charlas exactas** con links a su ficha.
  - Combina búsqueda por significado con búsqueda por palabras.

### 5.6 Fichas navegables: charla → speaker → empresa
- **Charla**: de qué se trata, quién la da (cargo y empresa), horarios como tarjetas, servicios de AWS, tus grabaciones y charlas relacionadas.
- **Speaker**: perfil profesional (cargo, trayectoria, educación, skills, LinkedIn), todas sus charlas y con quién comparte escenario.
- **Empresa**: sector e industria, quiénes de esa empresa vienen a re:Invent y todas sus charlas.
- **"Para conversar"**: un bloque destacado que arma con IA una ficha de preparación:
  - Quién es la persona.
  - Qué hace su empresa con AWS.
  - Qué presenta en re:Invent.
  - **Temas para abrir la conversación, cruzados con tu propio perfil**.
  - Preguntas sugeridas.
  - Qué tener en cuenta.

### 5.7 Detalles que suman
- **App instalable (PWA)**: se agrega a la pantalla de inicio del iPhone o Android como una app más, abre a pantalla completa y funciona sin señal.
- **Entrada con Face ID o huella** (passkeys): sin tipear contraseñas en el evento.
- **Modo claro y oscuro**, el oscuro pensado para salas con poca luz.
- **Accesibilidad 100/100 en Lighthouse** en todas las pantallas: funciona con lector de pantalla y teclado.
- Diseño basado en **Brick v2**, el design system de Banco Galicia.

---

## 6. Números para usar en pantalla

| Dato | Valor |
|---|---|
| Charlas en el catálogo | **1.759** |
| Speakers | **~3.000** (2.999) |
| Perfiles profesionales de speakers | **2.660** |
| Empresas | **365** |
| Temas emergentes descubiertos por IA | **30** |
| Duración de cada bloque de subtítulos | **15 segundos** |
| Accesibilidad (Lighthouse) | **100/100** |

---

## 7. Identidad visual

- **Logo**:
  - Cinco barras de una onda de voz sobre fondo casi negro (`#1a1a1a`).
  - Cuatro barras naranjas (`#fa6400`) y la del centro, más alta, en blanco (`#f4f4f4`).
  - Representa grabar, escuchar y entender.
  - Archivos: `web/icons/icon.svg` y `web/icons/icon-512.png`.
- **Wordmark**: "Reinvent**AR**", con "AR" en naranja oscuro (`#a84308`).
- **Paleta** (Brick v2, Banco Galicia):
  - Naranja de marca `#fa6400`.
  - Naranja suave `#ffe2ce`.
  - Gris de fondo `#f4f4f4`.
  - Texto `#2b2b2b`.
  - Rojo de grabación `#c51111`.
  - Verde `#258825`.
  - Ámbar `#e99d09`.
- **Tipografía**: Inter para la interfaz y JetBrains Mono para horarios y el contador.
- **Tono visual**: limpio, mucho aire, un solo botón naranja por pantalla, tarjetas blancas con sombra suave.

## 8. Tono del video

- Español rioplatense, cercano y con energía, pero profesional: es para gente de tecnología.
- Mostrar más que contar: la app en uso, toques reales y transiciones rápidas.
- Ritmo ágil de 60 a 90 segundos. Música electrónica suave, que evoque Las Vegas de noche sin ser casino.
- Cerrar con una promesa clara, no con una lista de features.

---

## 9. Guion sugerido (≈ 75 s)

| # | Tiempo | Imagen | Texto en pantalla / voz en off |
|---|---|---|---|
| 1 | 0–5 s | Strip de Las Vegas de noche, fundido a un celular con el logo de onda | "1.759 charlas. 5 días. Una sola vez al año." |
| 2 | 5–12 s | Alguien en una sala oscura de conferencias, mirando el celular | "¿Cómo volvés de re:Invent con algo más que fotos de slides?" |
| 3 | 12–20 s | **Inicio "Hoy"**: tarjeta "Ahora" resaltada → toque en **"Grabar esta charla"** | "ReinventAR sabe dónde tenés que estar. Un toque y grabás." |
| 4 | 20–28 s | **Pantalla de grabación**: medidor en verde y contador corriendo → **Modo sala** en negro | "Graba con tu micrófono, aunque no haya señal." |
| 5 | 28–38 s | **Transcripción** en bloques ES/EN → **Resumen**: TL;DR, Anuncios y "Para llevar a Galicia" | "Al terminar: transcripta, traducida y resumida en español. Con lo que anunciaron y lo que te sirve a vos." |
| 6 | 38–48 s | **Buscar**: escribir "bancos el martes" → "Convertir en filtros" → chips → "Ver N charlas" | "Buscá como hablás." |
| 7 | 48–55 s | **Preguntar**: pregunta y respuesta con códigos de charla resaltados | "O preguntale. Te responde citando las charlas exactas." |
| 8 | 55–63 s | **Itinerario**: mapa con colores por día y tarjetas con el horario a la izquierda | "Tu agenda, armada por IA, sin choques de horario." |
| 9 | 63–71 s | **Ficha de speaker** → bloque naranja **"Para conversar"** desplegándose | "Y antes de saludar a un speaker, sabé de qué hablarle." |
| 10 | 71–75 s | Logo grande con el wordmark ReinventAR | "**ReinventAR.** Tu re:Invent, entendido." |

**Remates alternativos para el cierre**: "Escuchá. Del resto se encarga ReinventAR." · "Volvé de Las Vegas sabiendo más." · "re:Invent, en tu idioma."

---

## 10. Capturas a grabar (rutas de la app)

App en producción: `https://reinventar-production.up.railway.app`. Grabarla en un celular, o en el navegador con un ancho de 390 px.

| Escena | Ruta | Qué preparar antes |
|---|---|---|
| Inicio "Hoy" | `#/` | Itinerario con charlas del día; para que aparezca "Ahora", grabar durante el evento o simular la hora |
| Grabación | `#/grabar/{id}` | Tocar "Grabar esta charla" desde Hoy; hablar cerca del micrófono para que el medidor se mueva |
| Modo sala | botón "Modo sala" en la grabación | Grabando |
| Transcripción y resumen | `#/s/{id}` | Una grabación ya procesada, con estado "Listo" |
| Buscar › Filtrar | `#/buscar` | Escribir "bancos el martes" y tocar "Convertir en filtros"; abrir "Filtros" |
| Buscar › Preguntar | `#/buscar?modo=preguntar` | Tocar un ejemplo o escribir una pregunta |
| Itinerario | `#/itinerario` | Itinerario generado desde el cuestionario |
| Ficha de charla | `#/charla/ARC407` | — |
| Ficha de speaker + Para conversar | `#/speaker/{id}` (desde la ficha de charla) | Tocar "Preparar conversación" |
| Temas emergentes | `#/buscar?agrupar=tema` | — |
| Instalación | Safari › Compartir › "Agregar a inicio" | Mostrar el ícono nuevo en la pantalla de inicio |

Sugerencia: grabar en **modo oscuro** las escenas de sala (grabación y modo sala) y en **modo claro** el resto, para que el contraste cuente la historia.

---

## 11. Cosas a NO decir ni mostrar

- **No** decir que transcribe en vivo: transcribe, traduce y resume **al terminar** la grabación (tarda unos minutos).
- **No** presentarla como una app oficial de AWS ni de re:Invent, ni usar sus logos: es una herramienta independiente que usa el catálogo público del evento.
- **No** mostrar datos personales reales en primer plano (perfiles de speakers, usuarios, contraseñas). Usar desenfoque o personas que hayan dado su permiso.
- **No** mostrar la pantalla de administración ni los ajustes de cuenta.
- **No** prometer funciones que no existen todavía, como subir un archivo de audio en lugar de grabar o descripciones de charlas en español nativo.

## 12. Bajo el capó (por si el video tiene una versión técnica)

- **Backend**: FastAPI sobre Postgres, desplegado en Railway.
- **Frontend**: PWA en JavaScript sin frameworks, con service worker para funcionar sin señal.
- **Transcripción**: Whisper (large-v3-turbo).
- **Traducción, chat y fichas**: Claude Sonnet 5.5.
- **Resúmenes**: Claude Opus 5.5.
- **Búsqueda híbrida (RAG)**: embeddings multilingües más BM25, fusionados con RRF, con citas validadas contra el catálogo real.
- **Temas emergentes**: k-means esférico sobre los embeddings, con nombres puestos por IA.
- **Datos**: catálogo, speakers, perfiles y empresas en Postgres; las grabaciones se suben en pedazos de hasta 5 MB y son reanudables.
