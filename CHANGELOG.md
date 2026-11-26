# Changelog

Todos los cambios relevantes de ReinventAR. El formato sigue [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/)
y la versión, [SemVer](https://semver.org/lang/es/). La versión vive en `app/__init__.py`.

## [Sin publicar]

### Agregado

- «re:Invent día por día» (Viaje y link desde Hoy): retiro del badge, keynotes, shuttles, Expo, certificaciones, re:Play, comidas, propinas, clima y enchufes, cada dato con su fuente. Anda sin señal.
- Las keynotes en Inicio dicen que hay traducción al español (latinoamericano) y traen el link al livestream.
- El aviso «Salí para…» de una charla reservada dice hasta qué hora entrar antes de que se libere el lugar (10 min antes).
- Pendientes nuevos: adaptador de enchufe tipo A, subir la foto a re:Invent, declarar la notebook (OM-121), evaluar pagar la tarjeta con dólares propios (a confirmar con el banco) y lugar para el swag.
- La cotización de respaldo (cuando nunca se pudo consultar) pasa a valores de noviembre de 2026.

## [1.3.4] - 2026-11-25

### Agregado

- Las charlas que AWS sumó al catálogo en los últimos 7 días dicen «Nueva · agregada el …» en la tarjeta y en la ficha, con un aviso de cuándo se sumó; las canceladas llevan la etiqueta «Cancelada» arriba del título.
- Entre sedes distintas, además de los minutos caminando, la forma más práctica de ir: el shuttle de re:Invent o el monorail gratis con el badge cuando queda lejos, o el puente Wynn–Venetian. En las charlas cerca de «está llena» el tiempo caminando sale en el momento de Google.
- En la ficha de la charla, «Cómo llegar a la sala»: pasos cortos por sede y por piso para no perderte adentro del hotel (andan sin señal), y «Llevame» te lleva a la entrada del área de convenciones en vez del hotel en general (Venetian, Caesars Forum, Caesars Palace y MGM Grand).

### Cambiado

- Las charlas cerca para aprovechar el rato aparecen también cuando avisan que hay mucha cola, no solo cuando está llena, y se abren en el momento en que tocás «Está llena» o «Hay mucha cola», sin recargar la ficha.

## [1.3.3] - 2026-11-25

### Agregado
- **Está llena: otras charlas cerca.** Si avisaron que un horario está lleno y no estás anotado, la ficha de la
  charla sugiere hasta 5 charlas de hoy que empiezan ahora o dentro de la hora, en la misma sede o a 15 minutos
  caminando como mucho, con la hora, la sede y cuánto se camina. No sugiere las que también avisaron llenas.
- **Mail obligatorio y verificado.** Quien no tiene el mail confirmado lo carga al entrar, en una pantalla que no se
  saltea. Le llega un código de 6 dígitos que vence en 15 minutos y tiene 5 intentos. El mail se guarda en minúsculas
  y no puede repetirse entre cuentas. Sin señal no se exige, para no trabar lo que anda sin conexión.
- **«¿Olvidaste tu contraseña?» en el login.** Con el usuario o el mail llega un código de 6 dígitos que vence en 10
  minutos, admite 5 intentos y sirve una sola vez. En la misma pantalla se escribe el código y la contraseña nueva. La
  respuesta es la misma exista o no la cuenta. Al elegir la contraseña nueva se cierran todas las sesiones, se borran las
  passkeys y llega un aviso por mail.
- **Mails con diseño propio.** Los mails del código, de la recuperación y del aviso de contraseña cambiada llegan en
  HTML (con su versión de texto) y llevan abajo el apartado «Seguridad»: quién lo pidió, cuándo (hora de Las Vegas),
  desde qué navegador y la IP enmascarada.
- **Admin › Usuarios muestra el mail** de cada persona y marca a quien todavía no lo verificó.
- Envío de mails configurable (`MAIL_PROVIDER`: SMTP, Resend, `fake` para desarrollo y tests, u `off`). Mientras
  esté en `off` (el default), el mail no se exige.
- **Admin › Usuarios › Borrar usuario.** Borra la cuenta y todo lo suyo, también lo del modo prueba: itinerario,
  eventos, viajes, gastos con sus fotos, documentos del bucket, las grabaciones que hizo (con el audio), sesiones,
  passkeys y notificaciones. Para confirmar hay que escribir el nombre del usuario. Un admin no se puede borrar a sí
  mismo ni a otro admin, y cada borrado queda registrado (quién, cuándo y qué se borró).

### Corregido
- **Ofertas: se ve por qué no hay bajas de precio de shows.** Si Ticketmaster no publica precios para ninguna función
  de la semana, el job de ofertas lo deja en el log en cada vuelta en vez de quedar vacío sin explicación.

## [1.3.2] - 2026-11-23

### Agregado
- **Dónde comer, con más filtros.** La distancia se elige con un deslizador de 5 a 30 minutos caminando y la
  lista se actualiza al soltarlo. El precio llega hasta $$$$. Se suman «Abierto ahora», puntaje mínimo (4 ★ o
  4,5 ★) y el orden: recomendados, más cerca o mejor puntaje.
- **Dónde comer por tipo de lugar.** «Dónde comer barato» suma chips para elegir comida rápida, dulces y postres
  (chocolaterías, heladerías, donas), café y panadería o restaurantes. Cada tipo es su propia búsqueda, así un local
  de dulces no queda tapado por las hamburgueserías. Cada lugar muestra su tipo («Tienda de chocolate»,
  «Hamburguesería»).
- **«Agregar al itinerario» en Mis códigos de Excel.** Un botón suma al itinerario, fijadas, las charlas de tu lista
  que todavía no están, en el horario que muestra el cruce (si pediste una repetición, esa). Cada charla dice si ya
  está en tu itinerario. Cuando no hay ninguna registrada, la pantalla explica que «Registradas» sale de las
  reservas marcadas y que se cargan con «Importar reservas de AWS».

### Corregido
- **Códigos de 4 dígitos y con sufijo.** «Cruzar con mi Excel» salteaba sin avisar los códigos de 4 dígitos
  (IND3313) y daba por inexistentes las charlas cuyo código lleva -S, -SC o -D (AIM121-S, SVC003-D0). Ahora los
  reconoce, y el buscador también los toma como código en lugar de mandarlos al asistente.
- **Buscar por código.** Al escribir el código de una charla (IND347) aparecía una sola tarjeta, con el primer
  horario, y el resto solo se encontraba filtrando por día. Ahora el código de la charla trae una tarjeta por cada
  horario, y el código de un horario (IND347-R1) trae solo ese, así «Agregar» suma el que buscaste. Agrupando por
  día, sede u hora, cada grupo muestra el horario que le corresponde.

## [1.3.1] - 2026-11-23

### Agregado
- **Charlas que AWS sube a YouTube.** Las keynotes, las mainstage y las breakout sessions llevan la etiqueta «Se
  publica en YouTube» en la ficha y en las tarjetas (itinerario, búsqueda, explorar). Al tocar «Grabar» en una de
  ellas, antes de empezar te avisa que AWS la publica en el canal AWS Events entre 24 y 48 h después y que no hace
  falta grabarla, con «Grabar igual» o «No grabar». Avisa una sola vez por charla y funciona sin señal. En «¿Te
  perdiste…?» ahora dice si esa charla sale en YouTube o no.

## [1.3.0] - 2026-11-23

### Agregado
- **Actividades.** En Viaje › Actividades hay dos pestañas: *Excursiones*, con tours, excursiones de un día y entradas de
  Viator para tus días en Las Vegas (precio desde, puntaje, duración y el botón «Reservar en Viator»), agrupadas por
  tipo; y *Cerca*, con museos, parques y atracciones ordenadas por distancia a donde estás o a tu próxima sesión.
  Excursiones aparece cuando el servidor tiene la clave de Viator.
- **Mi ficha.** En Ajustes › Mi ficha ves todo lo tuyo en una pantalla: perfil (rol, industria e intereses), vuelos y
  hotel, notificaciones, entrar con huella o cara, documentos, pendientes y charlas en tu agenda, con una barra de
  cuánto completaste. Cada bloque dice si le falta algo y te lleva a la pantalla donde se completa. Si falta algo
  importante (vuelo, hotel, notificaciones, documentos, perfil), el aviso de arriba te lo recuerda cuando no hay nada
  más urgente («Cargá tu hotel · Completar»); si lo cerrás vuelve en 24 h. Durante el viaje solo insiste con lo que
  sirve allá: el vuelo de vuelta y las notificaciones.
- **Cargar tus eventos desde Excel.** En Eventos › Mis eventos › Cargar desde Excel subís un .xlsx o .csv con hasta
  100 eventos (Nombre, Día, Inicio y Lugar; opcionales Fin, Tipo, Dirección, Link, Precio y Notas). Antes de guardar
  ves una vista previa con lo nuevo, lo que cambia y los errores de cada fila; las filas con error no se guardan. Si
  subís el mismo archivo otra vez no se duplica. Si el lugar es una sede de re:Invent, queda ubicado en el mapa. Hay
  un Excel de ejemplo para bajar y completar.
- **Conversor de unidades.** En Viaje › Conversor pasás °F a °C (con una tira de referencia de 60 a 95 °F), onzas,
  libras, tazas, pintas y galones a gramos y litros (con atajos como «16 oz steak = 454 g»), libras a kilos con los
  discos del gym, millas, pies y pulgadas a km, m y cm, mph a km/h, talles de ropa y calzado US ↔ AR/EU (de hombre y de
  mujer, aproximados), la propina con el impuesto de Las Vegas (8,375 %) y el total en pesos, y dólares a pesos con la
  cotización tarjeta y su antigüedad. Convierte mientras escribís, con coma o punto, ⇄ invierte y anda sin señal.
- **Leer con la cámara** (cuando esté habilitada). Dentro del conversor, sacale una foto a una carta o un cartel: te
  traduce lo que dice y pasa las unidades y los precios. Necesita señal; la foto no se guarda.
- **Charlas nuevas.** Cuando AWS suma charlas al catálogo, aparecen en Itinerario › Charlas nuevas (y en una tarjeta en
  Inicio): las de los últimos 7 días que todavía no pasaron, primero las que coinciden con tus intereses. Cada una se
  agrega a tu agenda con un toque (te avisamos si se superpone con algo) o se descarta, y no vuelve a aparecer. Te
  llega un solo aviso por tanda («3 charlas nuevas»), nunca de noche ni repetido; se apaga en Ajustes.

### Cambiado
- **Ofertas ya no queda en blanco.** Si todavía no hay ofertas vigentes, la pantalla explica de dónde salen
  (bajas de precio de shows cuando Ticketmaster publica precios, y ofertas de comida y outlets que carga el equipo) y
  lleva a Shows. Quien es admin ve además «Cargar una oferta».

## [1.2.0] - 2026-11-23

### Agregado
- **Más datos de tu vuelo.** La ficha del vuelo muestra a dónde va y a qué hora llega («A Houston (IAH) · llega
  16:40», en hora del destino), el avión y su matrícula, el mostrador de check-in, la terminal de llegada y la cinta
  de equipaje cuando la asignan. Te avisamos con una notificación en cuanto aparece la cinta.
- **«Próximo» en el aviso de arriba.** Cuando no hay nada más importante, el aviso de arriba te muestra lo que viene:
  tu vuelo desde 12 h antes («Próximo: UA1355 a Houston · sale 13:05 (+20 min) · puerta D12»), el check-in o el
  check-out del hotel, o la próxima charla del día. Tocalo para ir a la ficha.
- **Documentos de viaje.** En Viajes › Documentos de viaje podés subir el pasaporte, la ESTA o visa, el seguro, reservas,
  la entrada a re:Invent o la tarjeta de embarque (foto o PDF, hasta 8 MB). Solo vos los ves, se guardan cifrados y se
  borran solos 30 días después del viaje (o cuando toques «Borrar todos mis documentos»). Si alguno vence durante el
  viaje te avisamos. Con «Guardar en este teléfono» queda una copia cifrada para verlo sin señal; se borra al cerrar sesión.
- **Pendientes del viaje.** En Viaje, una checklist de lo que conviene tener resuelto antes de salir (ESTA o visa,
  pasaporte, seguro, eSIM, check-in de United, entrada de re:Invent, avisar al banco, dólares, documentos…). Tildás
  lo que ya hiciste, sumás lo tuyo con fecha límite si querés, y editás o borrás cualquiera (un sugerido que borrás
  no vuelve). La tarjeta de Viaje muestra cuántos llevás listos. Te avisamos 3 días antes y el mismo día de cada
  fecha límite, y los 3 días previos al viaje, a la mañana, cuántos te faltan. Se apaga en Ajustes.
- **Aviso si alguien ya está grabando la charla.** Al empezar a grabar una charla que otra persona ya está grabando,
  la app avisa «Ana ya está grabando esta charla» y deja elegir entre «Grabar igual» o «Ver la suya». Sin señal no
  pregunta: graba igual.
- **Compartir resumen.** En el detalle de una grabación, «Compartir resumen» abre WhatsApp (o lo que elijas) con el
  resumen en texto; si el celular no puede, lo copia. No incluye «Versus lo prometido» ni «Para llevar a Galicia».
- **Link público que vence.** En el menú ⋯, «Link público» arma un link de solo lectura al resumen que se abre sin
  cuenta (y se puede imprimir o guardar en PDF). Vence a los 14 días. No está disponible en modo prueba.

### Cambiado
- **Reintentar y eliminar una grabación, solo quien la grabó** (o un admin). Ver y exportar sigue igual para todos.

## [1.1.3] - 2026-11-23

### Agregado
- **Aviso de estado arriba de la app.** Un solo aviso, debajo de la barra, que te dice lo que importa en el momento:
  si estás sin señal y cuántas grabaciones y gastos esperan subirse, si algo no se pudo subir (con «Reintentar»),
  cuando vuelve la señal y se está subiendo todo, y si el servicio está caído o demorado (por ejemplo, «Las
  transcripciones vienen con demora. Tus grabaciones están guardadas y se procesan solas.»). Si hay más de un aviso,
  «+N» los muestra todos. Reemplaza los «Sin señal» que antes aparecían en cada pantalla.
- **Versión nueva y novedades.** Cuando hay una versión nueva, el aviso lo dice y «Ver novedades» muestra qué cambió,
  con «Actualizar ahora». Nunca aparece mientras grabás.
- **El día en Inicio.** Arriba de «Hoy»: qué día de re:Invent es, a qué hora es la keynote y cuántas charlas tenés.

## [1.1.2] - 2026-11-22

### Agregado
- **Editar vuelos y hoteles.** En Viajes, cada vuelo y cada hotel tiene «Editar» en su ficha: el formulario se abre
  con los datos cargados (también la ciudad de salida). Si cambiás la fecha, la hora o el vuelo, los avisos de
  check-in, demora y puerta se recalculan para el nuevo; cambiar solo la aerolínea o el nombre no repite avisos.
- **Excel de ejemplo para cruzar tus códigos.** En Itinerario › Cruzar con mi Excel, «Bajar un Excel de ejemplo» te da
  una planilla con la columna Código y unas instrucciones: la completás con las charlas que querés y la subís tal cual.

### Cambiado
- **Eventos y Shows llegan hasta el lunes 7/12 a las 13:00.** Podés encontrar fiestas, actividades y shows del sábado
  5, el domingo 6 y la mañana del lunes 7, y el admin puede cargar eventos por link hasta el 7/12.

## [1.1.1] - 2026-11-22

### Cambiado
- **Vuelos: «Sale de» acepta cualquier ciudad del mundo.** Escribís y aparecen las ciudades que coinciden, con su país
  (también por su nombre en castellano, como «Nueva York» o «San Pablo», o por el código del aeropuerto, como «HOU»).
  La hora de salida y la apertura del check-in se calculan con la zona horaria de esa ciudad; antes había solo seis
  ciudades para elegir y un vuelo desde Houston no se podía cargar con su hora local. Datos de ciudades de
  [GeoNames](https://www.geonames.org) (CC BY 4.0).

## [1.1.0] - 2026-11-22

El viaje además de la agenda: gastos, vuelos y hoteles, dónde comer, shows y ofertas, todo desde la pestaña Viaje.
Y una galería pública con un video corto por funcionalidad.

### Agregado
- **Pestaña Viaje** en la barra de abajo, con Dónde comer barato, Gastos, Ofertas y Vuelos y hoteles.
- **Gastos del viaje** (`#/gastos`). Cargás un gasto en segundos, en dólares o en pesos, con categoría, nota, día,
  Reintegrable, Individual o Compartido y foto del ticket. Ves lo gastado hoy y en todo el viaje contra tu
  presupuesto, las tres cotizaciones (oficial, blue y tarjeta) y el gasto por categoría. Cada gasto guarda la
  cotización del día en que lo hiciste, así que si el dólar se mueve después no cambia. Anda sin señal: se guarda en
  el celular y se sincroniza solo, también entre dos teléfonos tuyos. «Exportar reintegrables» baja un CSV con links
  a las fotos de los tickets.
- **Vuelos y hoteles** (`#/viajes`). Cargás tus vuelos y hoteles y te llega un aviso cuando abre el check-in de la
  aerolínea, unas horas antes del check-in del hotel y la noche anterior al check-out. Desde 24 h antes del vuelo
  también avisa si se demora, si cambia la puerta o si se cancela.
- **Dónde comer barato** (`#/comer`): lugares cerca de donde estás o de la sede de tu próxima charla, con puntaje,
  reseñas, precio, minutos caminando y Llevame. Se filtra por precio y por distancia.
- **Ofertas** (`#/ofertas`): bajas de precio de shows y ofertas de comida, compras y outlets, con filtro por
  categoría. En Ajustes, «Avisarme de ofertas» manda un push por las categorías que elijas.
- **¿Cuándo nos conviene ir a un show?** En la ficha de un show, las funciones de la semana ordenadas según tu
  itinerario: libre, justa (llegás con poco margen) o choca, con el motivo.
- **Eventos en todas las fechas.** En Eventos › Networking, «Todas las fechas» lista los eventos de toda la semana
  agrupados por día, y el filtro «Desde las 17» deja solo los que empiezan a las 17 o después.
- **Cruzar con mi Excel** (Itinerario): subís un `.xlsx` o `.csv` con los códigos de charla que querés y la app te
  dice cuáles ya registraste, cuáles te faltan, cuáles chocan entre sí, cuáles tenés de más y cuáles no existen.
- **Videos demo en `/demos/`.** Una página pública, sin login, con un video corto por funcionalidad: la app en el
  celular y, al costado, qué hace cada paso. Tiene buscador, secciones y reproductor, y cada video se comparte con su
  link (`/demos/#gastos`). Los videos no tienen sonido; debajo de cada uno, «Qué muestra el video» lo cuenta en texto.

### Cambiado
- **Administración por pestañas** (Estado, Usuarios, Eventos, Ofertas y LLM), cada una con su carga, su error con
  «Reintentar» y su estado vacío. Desactivar un usuario, cerrar sus sesiones o dar de baja una oferta piden
  confirmación. Estado muestra arriba lo que requiere atención, o «Todo en orden».
- **Itinerario:** las pestañas de día dicen «lun 30 nov» en vez de la fecha cruda.

### Corregido
- Los avisos push ya no se cortan para todos si falla el de una persona o la fuente de precios de shows, y una
  demora o un cambio de puerta que no llegó se vuelve a intentar.
- Gastos: tocar «Guardar» o «Borrar» dos veces ya no duplica el gasto ni apila dos confirmaciones, y la lista ya no
  queda en blanco en iPhone con iOS 16 o 17 viejo.
- Subir un Excel o CSV armado a propósito ya no puede tirar la app.
- Viajes, Ofertas y Dónde comer ya no se pisan si navegás antes de que termine de cargar una pantalla.

## [1.0.0] - 2026-11-15

La versión que va a re:Invent 2026: la app se puede usar entera sin señal en los salones (grabar, ver Hoy y el
Itinerario) y sube todo sola cuando vuelve la red.

### Agregado
- **Grabar sin señal.** Si no hay red al tocar «Nueva» o «Grabar», la grabación arranca igual y se guarda en el
  celular («Sin señal: se graba en el celular y se sube cuando vuelva»). Cuando vuelve la señal se crea en el servidor,
  se sube y, si ya habías tocado Terminar, se procesa sola, aunque hayas cerrado la app. El audio del celular no se
  borra hasta que el servidor confirma el cierre. «Descartar» también anda sin señal.
- **Terminar sin señal.** Si se corta la señal en medio de una grabación (empezaste en el pasillo con señal y en el
  salón no hay), «Terminar y procesar» la deja guardada en el celular: la pantalla dice «Terminada · esperando señal»
  y que podés cerrar la app. Cuando vuelve la red se sube y se procesa sola.
- **Inicio e Itinerario sin señal.** Hoy, el Itinerario, los anuncios sin reserva y la lista de grabaciones muestran lo
  último que cargaron, con la franja «Sin señal · datos de las HH:MM». Si el Wi-Fi conecta pero no responde, a los
  8 s muestra la copia. Al cerrar sesión se borra.
- **«Grabadas en este celular»** en Inicio: las grabaciones que todavía esperan señal, con su estado (Grabando,
  Pendiente de subir, Esperando señal) o el error si algo falló.
- **Ver la contraseña:** un ojo en cada campo de contraseña (al entrar y al cambiarla) la muestra u oculta. No tapa
  el ícono del gestor de contraseñas y al enviar vuelve a ocultarse. El ícono muestra el estado, como en Android:
  ojo tachado con la contraseña oculta, ojo abierto cuando se ve.
- **Tramos sin audio marcados.** Si una llamada o un audio de WhatsApp le saca el micrófono a la app más de 8 s, la
  transcripción lo marca con «— sin audio mm:ss–mm:ss —» (también en el Markdown exportado). La primera vez que
  grabás, un tip sugiere poner No molestar.
- **«Llevame» dentro de la app:** el mapa con el recorrido a pie, los minutos y la distancia se abren en la misma app,
  con «Abrir en Google Maps» si querés la navegación.
- **Buscar por código de charla:** «key002» o «aim204» encuentran la charla (también sus repeticiones, «AIM204-R1»).

### Cambiado
- **Modo sala** muestra «En pausa» cuando la grabación está pausada.
- Ajustes y «Tus grabaciones» sin señal muestran tu cuenta y la última copia en vez de «Sesión no válida».
- La distancia a la sede: «Estás en la sede» si estás a menos de 50 m; desde muy lejos (otra ciudad), solo los km.
- El ingreso con biometría dice «huella o rostro» (Face ID solo en iPhone).
- El Horario de la ficha se ve bien en el celular: la sede ocupa todo el ancho y los botones van abajo.
- Lo elegido se ve mejor en modo claro y oscuro: los filtros (días, tipos), las pestañas (Networking / Shows,
  Filtrar / Preguntar, Números) y «Agrupar» se marcan en naranja suave con borde, en vez de blanco que encandilaba en
  oscuro o gris apenas distinto del fondo.
- Al prender «Usar en qué sede estoy para los avisos» se prende también «Usar mi ubicación»: antes había que buscarla
  más arriba y la casilla parecía no tildarse.
- Las revisiones automáticas de eventos y de charlas de staging y de producción ya no se saltean entre sí.
- Una grabación hecha sin señal queda con la hora en que se grabó (no la de cuando volvió la señal) y no se duplica
  si la app se cierra justo mientras se sube.
- Langfuse y el panel de LiteLLM muestran quién hizo cada pedido al LLM en todos los caminos (también las grabaciones
  retomadas al reiniciar y la traducción por lotes). Los trabajos automáticos van como «sistema:eventos-auto»,
  «sistema:healthcheck», «sistema:temas» o «sistema:pipeline».

### Corregido
- Debajo de «¿Te sirvió este resumen?» ya no aparece la palabra «null» cuando nadie votó todavía (lo mismo en
  Administración › Eventos automáticos).
- Los errores se muestran en castellano en toda la app (antes salían textos del navegador como «Failed to fetch» o
  «NotAllowedError»). Sin red: «Sin conexión: revisá la señal y probá de nuevo.». Micrófono: «Necesito permiso para
  usar el micrófono.», «No encuentro ningún micrófono.» o «El micrófono está ocupado por otra app».
- **Notificaciones en iPhone:** «Activar notificaciones» podía quedar trabado sin explicación. Ahora, si la app está
  abierta en Safari, explica que hay que agregarla a la pantalla de inicio con «Abrir como app web»; si algo falla,
  dice qué. «Probar una notificación» solo aparece con las notificaciones activadas.
- El Wi-Fi de un hotel que contesta con su página de login ya no da un error raro: se toma como sin señal y se
  muestra la última copia.
- Al abrir la pantalla de grabar, el botón espera a que el micrófono esté listo («Abriendo el micrófono…»): antes,
  tocarlo enseguida daba «Primero abrí el micrófono».
- Hoy sin señal avisa: cuando muestra la última copia guardada (sin red o con un Wi-Fi con portal), lleva la franja
  «Sin señal · datos de las HH:MM», igual que el Itinerario.
- Títulos y resúmenes del catálogo oficial que AWS manda con caracteres rotos («fleetÂ», «â€”») se reparan al
  cargarlos. Las 8 charlas ya cargadas se corrigen con la próxima carga manual del catálogo.
- En la pantalla de grabar ya no aparece un «null» suelto al lado de «Todo subido».
- El aviso para instalar la app ya no promete que «funciona sin señal»: dice que abre aunque no haya señal.

## [0.22.0] - 2026-11-14

### Agregado
- **Los eventos se actualizan solos.** Cada 3 horas la app revisa el calendario de Luma de re:Invent y la lista de
  conferenceparties.com: suma los nuevos (con su resumen en castellano y el hotel más cercano) y actualiza los que
  cambiaron. Entran también los ~140 eventos de conferenceparties que no están en Luma; su botón lleva a la página del
  organizador.
- **Eventos cancelados.** Si un evento futuro deja de aparecer en su página en dos revisiones seguidas, se marca
  «Cancelado» (tachado y al final de la lista, también en el itinerario y en Inicio) y avisa por push a quien lo tenía
  en su itinerario. Si vuelve a aparecer, se descancela.
- **Aviso de eventos nuevos**: un push por tanda («3 eventos nuevos: …»), nunca de noche. Se apaga en Cuenta →
  Notificaciones con «Avisarme de eventos nuevos».
- **Shows en Eventos.** Arriba de Eventos, dos pestañas: **Networking** y **Shows**. En Shows están los conciertos,
  espectáculos, deportes y actividades de Las Vegas del 29/11 al 4/12, de Ticketmaster: una tarjeta por show con sus
  horarios del día, la sala, el precio «desde US$ X» (si Ticketmaster lo publica), filtros por día, por tipo (música,
  teatro y shows, comedia, deportes, actividades) y «↕ Más cerca». La ficha muestra las funciones de la semana para
  elegir cuál agregar al itinerario (queda fijada y avisa cuándo salir), «Cómo llegar» y el link **«Entradas en
  Ticketmaster»** (la compra se hace en su página). Se actualiza sola con la revisión de eventos; si una función se
  cancela o se posterga, avisa por push a quien la tiene en el itinerario, y si cambia de horario, avisa el cambio.
- Administración: estado de cada fuente, «Revisar ahora» y **«Agregar evento por link»** para los que no están en
  ninguna lista (pegás el link, la app arma el evento y lo revisás antes de guardar).
- **Charlas que se bajan o cambian.** La app revisa sola el catálogo oficial de AWS (el buscador público, sin tu
  usuario): cada 3 horas en noviembre y cada 30 minutos durante el evento. Si una charla deja de aparecer, avisa en la
  tarjeta, la ficha, el itinerario e Inicio («No aparece en el catálogo oficial desde las 14:30…»); si sigue sin
  aparecer en la revisión siguiente, queda **«Cancelada»** (tachada) y llega un push a quien la tenía («Se canceló
  AIM301 (mié 2/12 10:00)»). Si reaparece, vuelve a la normalidad.
- Los **cambios de sala u horario** se actualizan solos y el push dice qué cambió («AIM301 cambió de sala: ahora…»).
  Si AWS le cambia el código a una charla, sigue en tu itinerario con el código nuevo.
- Las **charlas nuevas** del catálogo oficial entran solas (con el resumen en inglés hasta la próxima carga) y se
  listan en Administración → Eventos automáticos para revisarlas.
- **¿Te sirvió este resumen? 👍 / 👎** debajo del resumen de cada grabación. Un voto por persona (otro toque lo quita)
  y se ve a cuántos les sirvió. Cada voto va al tablero de LLM («Útil»), para saber qué tan buenos salen los resúmenes.
- **«Está llena» y «Hay mucha cola»** en cada horario de la ficha de una charla. Desde 45 minutos antes de que empiece
  hasta que termina, quien está en la puerta avisa con un toque y el resto ve «Llena según 3 personas · hace 5 min».
  Cada persona deja un aviso por horario (otro toque lo quita), vale una hora y nunca se muestra quién avisó.
  Además, cada horario dice si es sin reserva («se entra por orden de llegada») o si la sala es chica.
- Los avisos de «llena» y «mucha cola» también aparecen en las tarjetas de **Hoy** (la charla de ahora y la que sigue,
  con los botones para avisar desde ahí) y en las del **itinerario**, junto con la pista de sala chica.

### Cambiado
- Staging puede usar su propia copia del catálogo (`CATALOGO_SCHEMA=reinvent_staging`, se arma con
  `scripts/preparar_catalogo_staging.py`) para probar la revisión automática sin tocar lo que ve producción.
- El botón «+ Itinerario» de las tarjetas de eventos ahora es naranja, como el resto de las acciones principales.
- Los avisos de «Cambió algo de tu itinerario» ya no llegan de noche: salen a la mañana, como el resto.
- Las tipografías (Inter y JetBrains Mono) las sirve la app y no Google Fonts: la letra es la misma, carga más rápido
  y se ve igual sin conexión.
- La app no aparece en buscadores (`robots.txt` y `noindex`).
- Las respuestas grandes viajan comprimidas (gzip): menos datos en el celular.
- `/health` ahora prueba también la base de datos y el disco; si alguno falla, responde 503.
- Las funciones con IA tienen un tope por persona (búsqueda en lenguaje natural, Preguntar, fichas, entrevista,
  armar itinerario y «Agregar evento por link»). Con uso normal no se alcanza; si se pasa, la app pide esperar unos
  minutos. Las fichas que ya estaban hechas no cuentan.

### Corregido
- **La pantalla de grabar no abría**: daba un error al armarse y quedaba en blanco.
- **Cortes de grabación en iPhone.** Si iOS corta el micrófono (una llamada, Siri, la pantalla bloqueada), se ve
  «Grabación pausada» y, al volver, la grabación sigue en una parte nueva sin mezclar ni romper el audio. Mientras
  dura el corte no sale el aviso de «No llega sonido».
- **Pedazos de audio rechazados.** Si el servidor rechaza un pedazo, ya no se borra en silencio: queda guardado, la
  pantalla dice «N sin subir» con un botón «Reintentar», y «Terminar» avisa en vez de quedarse esperando.
- La subida de lo pendiente ya no carga todas las grabaciones en memoria en cada vuelta: toma de a un pedazo.
- Con un Wi-Fi que conecta pero no responde, la app abre en unos 3 segundos con lo guardado en vez de quedar en
  blanco.
- Los íconos de la app se ven también sin conexión.
- En iPhone, «Activar notificaciones» pide el permiso al primer toque.
- Las notificaciones siguen llegando cuando el navegador renueva la suscripción, y tocar un aviso abre bien la app.
- Las imágenes de los eventos (Luma) salían rotas en un celular nuevo, en eventos nuevos o en algunos navegadores.
  Ahora las guarda el navegador directamente (siguen viéndose sin señal una vez vistas).
- En Android, el ícono chico de las notificaciones en la barra de estado se veía como un cuadrado blanco; ahora
  muestra las barras de ReinventAR.

### Seguridad
- FastAPI 0.162.2 con Starlette 1.10.0 (CVE-2025-62727, CVE-2026-48710, CVE-2026-54282); `pip-audit` sin
  vulnerabilidades conocidas.
- El límite de intentos de login por IP ya no se puede esquivar mandando un `X-Forwarded-For` falso: la IP sale de
  `X-Real-IP`, que pone el proxy de Railway.
- La CSP ya no permite Google Fonts.

## [0.21.0] - 2026-11-13

### Agregado
- **«¿La grabás?»: recordatorio para no olvidarte de grabar.** El aviso «X empieza en 5 min» de una charla fijada
  ahora pregunta «¿La grabás?» y, al tocarlo, abre esa charla lista para grabar con un botón «Empezar a grabar» (en
  iPhone hace falta ese toque para usar el micrófono). Si la charla empezó hace 2 a 6 minutos y nadie la está
  grabando, llega otro aviso. Nunca de 22 a 7, como mucho uno cada 30 minutos, y se apaga con «Recordarme grabar» en
  Ajustes › Notificaciones.
- **Usar en qué sede estoy para los avisos** (apagado por defecto, en Ajustes › Notificaciones): con la app abierta,
  el celular calcula en qué sede estás y manda solo eso, nunca tu posición. Con ese dato el aviso dice «Estás en el
  Venetian: ¿grabás X?», avisa también charlas no fijadas de tu itinerario si estás en esa sede, y no avisa si estás
  a 15 minutos o más caminando. Deja de usarse a los 45 minutos y se borra a las 2 horas; al apagarlo se borra al
  instante.
- **Tu re:Invent en números** (Itinerario › «Tu semana en números»). En *Mi semana*: cuántas charlas y keynotes
  tenés, horas ocupadas, kilómetros caminando entre sedes, choques y cambios de sede a los que no llegás; tu semana en
  franjas de 8 a 22 h con los choques en rojo y los «no llegás» marcados; la caminata por día; cuánto de tu agenda
  cubre cada prioridad de tu ficha (y qué tema pediste y no agendaste); el nivel de lo agendado y cuánto grabaste. En
  *Catálogo*: charlas por día (con las tuyas abajo), un mapa de calor día × hora con tus horarios marcados, y las
  charlas por tipo, sede y tema. Tocar una columna, celda o barra abre Buscar con ese filtro.
- **Buscar › Filtrar** suma la faceta «Hora de inicio» (ej. 13 h = empieza entre las 13:00 y las 13:59).
- Las grabaciones nuevas guardan quién las grabó; las de antes quedan sin dueño y no cuentan en «cuánto grabaste».
- **Anuncios sin reserva en Inicio.** Debajo de «Hoy», una fila que se desliza con el dedo (no se mueve sola) con
  las keynotes, el mainstage, los lanzamientos y los «What's new» a los que se entra por la cola, de los que quedan
  hoy (antes del evento y de noche, los del próximo día). Keynote y mainstage van en tarjeta oscura. Cada tarjeta
  dice desde qué hora hacer la cola y trae Agregar y Llevame; Grabar aparece solo con la charla en curso. Lo que ya
  está en tu itinerario no se repite y lo que terminó desaparece. La última tarjeta lleva a Buscar con el nuevo
  filtro «Anuncios» puesto.

### Arreglado
- **Agregar una charla ahora se nota.** El botón queda en naranja como «Agregada» (también si ya la tenías) y no
  vuelve a agregarla; si fue sin querer, otro toque la quita. En la ficha de la charla, el horario que ya está en tu
  itinerario tiene «Quitar».
- **Grabar sin que llegue sonido ya no deja una transcripción falsa.** Whisper inventaba un «Thank you.» sobre el
  silencio; ahora eso se descarta y la grabación avisa que no se escuchó voz, con qué revisar. Mientras grabás, si
  pasan unos segundos sin sonido aparece un aviso arriba del medidor («No llega sonido al micrófono»). La respuesta
  por voz de la entrevista también avisa si no se escuchó nada, en vez de devolver «Gracias.».

### Cambiado
- **Detalle de una grabación:** arriba quedan Volver, Compartir (el resumen en `.md`, en los celulares que pueden
  compartir archivos) y un menú ⋯ con Exportar y Eliminar; Eliminar sigue pidiendo confirmación. El título baja a
  24 px, el estado, quién la dio, dónde y cuánto duró van en una sola fila, y la ficha de la charla es un link
  «Ver la ficha de la charla ›». La transcripción muestra el castellano grande y el inglés abajo, con el minuto
  corto (12:40).
- **Llegando desde un buscador,** el momento encontrado queda marcado de borde a borde con una pastilla
  «Desde la búsqueda «…»» que se cierra con la ✕.
- **Preguntar:** el campo para escribir queda fijo abajo, sobre la barra de navegación, con un botón de enviar; sube
  con el teclado del celular y no tapa la última respuesta. La conversación se lee de la más vieja a la más nueva.
- **Inicio:** «Nueva» pasa al encabezado de *Tus grabaciones* y «Llevame» es un botón de solo ícono al lado de
  «Grabar esta charla». «Después» muestra la cuenta regresiva en la misma línea. Las grabaciones se ven más
  compactas: título y estado arriba, datos y duración abajo.
- **Buscar › Filtrar:** el botón de Filtros está dentro del campo de búsqueda con el número de filtros activos;
  «Convertir en filtros» aparece como sugerencia solo cuando escribiste algo; los filtros activos muestran solo el
  valor, «Agrupar» es un selector y «Limpiar» queda al lado del total de charlas. La tarjeta de cada charla sigue
  completa (speakers, resumen, Leer más, Agregar).

### Corregido
- **Mapa del itinerario con un solo lugar:** ya no queda con el zoom al máximo adentro del edificio; se ven las calles y los hoteles de alrededor.

### Seguridad
- **Sesiones más seguras:** el token se guarda hasheado en la base (un backup no sirve para entrar como nadie) y la sesión vence después de 30 días sin usar la app. Las sesiones abiertas siguen valiendo.
- **Login con límite de intentos:** después de 5 contraseñas mal en la misma cuenta, o de 20 desde el mismo lugar, hay que esperar 15 minutos. La respuesta tarda lo mismo exista o no el usuario.
- **La contraseña temporal se tiene que cambiar sí o sí:** hasta cambiarla, el servidor no deja usar nada más (antes lo controlaba solo la app).
- **Face ID / huella:** para agregar una passkey hay que haber entrado con la contraseña hace menos de 15 minutos. Al cambiar la contraseña, o si el admin la resetea, revoca las sesiones o desactiva al usuario, se borran sus passkeys y dejan de llegarle notificaciones.
- **Al cerrar sesión,** ese celular deja de recibir los avisos del usuario.
- **El mapa del itinerario** ya no arma HTML con títulos de eventos externos (podían ejecutar código).
- **Subidas con tope real:** el audio de las grabaciones, la voz de la entrevista y el `.ics` se cortan apenas pasan el máximo, sin cargarlos enteros en memoria; "Terminar" valida las partes de la grabación. Subir pedazos de audio ya no frena al resto de la app.
- **Cabeceras de seguridad** en todas las respuestas (CSP, no se puede embeber en otro sitio, HSTS).
- **Notificaciones:** solo se aceptan suscripciones de los servicios de push de los navegadores.
- **Google Places** puede usar una key propia del servidor (`GOOGLE_PLACES_SERVER_KEY`), separada de la que ve el navegador.

### Agregado
- **Langfuse se entiende mejor**: cada grabación queda en una sola traza (los pedazos de transcripción, la traducción y
  el resumen juntos) y las llamadas de una persona se agrupan por día en sesiones. Cada traza lleva la versión de la
  app, una versión del prompt (cambia solo si cambia el prompt) y los tags `prod`/`dev` y `prueba` para separar las
  pruebas de lo real.
- **Qué no se guarda en Langfuse**: de la entrevista guiada (repreguntas y ficha), de la respuesta dictada por voz y de
  las razones del armado guiado no se guarda ni lo que se le manda al modelo ni lo que contesta. En el chat, el briefing
  y el itinerario, si el pedido lleva tu ficha de la entrevista, no se guarda lo que se le manda al modelo; la respuesta
  sí (hace falta para depurar) y puede mencionar algo de tu ficha.
- **Calidad medida sola en producción**: con las claves de Langfuse en el servicio de la app (`LANGFUSE_PUBLIC_KEY`,
  `LANGFUSE_SECRET_KEY`), la app manda scores sobre cada traza: si el JSON vino bien, cuántas líneas de la traducción
  hubo que reintentar, cuántos códigos de charla inventó el chat o el briefing y cuántos momentos grabados citó el chat.
  Sin claves sigue todo igual. Si una grabación se reprocesa, sus scores se reemplazan en vez de duplicarse, y los del
  modo prueba quedan marcados.
- **Tablero de LLM en Cuenta → Admin**: los últimos 7 días de Langfuse sin salir de la app: costo por tarea y por día,
  demora p50 y p95 y errores por tarea (solo llamadas al modelo, sin el modo prueba), los scores de calidad (líneas
  faltantes, JSON válido, códigos inventados, momentos citados, 👍/👎) y el costo y las unidades del mes contra las
  50.000 del plan gratis (una cota superior estimada: trazas + observaciones + scores). Se actualiza cada
  5 minutos y tiene un link para abrir el proyecto en Langfuse. Necesita las claves de Langfuse en el servidor; sin
  ellas, dice que no está disponible.
- **Buscar en lo que grabaste**: en Inicio, arriba de tus grabaciones, un buscador que encuentra el momento de cada
  charla donde se habló de algo ("¿qué dijeron de Neptune?", "migrar Teradata"), por significado y por palabras, en
  castellano o en inglés. Cada resultado abre la transcripción en ese minuto. Las grabaciones viejas se indexan solas.
- **El chat de Buscar también responde con lo que grabaste**: además de las charlas del catálogo, usa lo que realmente
  se dijo en tus grabaciones y lo cita con un link al minuto (▶ 01:30). Debajo de la respuesta aparecen esos momentos.
- **Set para medir la búsqueda del catálogo** (`python -m scripts.evaluar_busqueda`): 30 preguntas con sus charlas
  relevantes, para comparar cambios en la búsqueda con números (acierto, recall y MRR en los primeros 10).

### Cambiado
- **Nueva cara, misma identidad** (naranja, Inter y JetBrains Mono): escala tipográfica de 6 pasos (los títulos de
  sección se separan de los de tarjeta), texto secundario con más contraste, un tinte suave por estado, radios más
  amables y, en oscuro, sin sombras (superficie y borde). Los emojis que hacían de íconos (🟠 🕒 📍 🎉 📌 ⚠ y el
  semáforo del armado guiado) y los glifos ✓ ✕ ＋ ↗ de los botones pasan a íconos que siguen el color del tema. Los
  avisos informativos (la cola, la opción sin reserva) usan su tinte azul en vez de gris.
- **Inicio**: «Ahora» se marca con borde naranja y un estado con punto; los avisos (cola, salí antes, superposición)
  son una fila tintada con ícono en vez de una tarjeta dentro de otra; el resto del día va en una lista agrupada.
- **Buscar**: una sola píldora de filtro, de 44 px, con el estado activo en tinta llena y ✕ para quitarlo. En Preguntar, la pregunta va como burbuja, las citas son pastillas (el código en gris y el momento ▶ en
  naranja, ya no en rojo) y los momentos grabados van en una lista agrupada.
- **Detalle de grabación**: el título usa el tamaño de título de sección. La barra inferior pasa a fondo sólido.
- **Sin señal**: la app guarda al instalarse todos sus módulos (antes faltaban el contador, los avisos de cambios, la
  ubicación, eventos y notificaciones, que se guardaban recién al usarlos).
- **La búsqueda entiende mejor lo que pedís**: nuevo modelo de embeddings (embeddinggemma, multilingüe y con textos
  largos) y plurales que encuentran el singular ("mainframes" → "mainframe"). En el set de 30 preguntas, de las charlas
  que tienen que aparecer entre las 10 primeras se encuentran el 81 % (antes 74 %). Mejora Buscar, el chat, el armado
  guiado y la búsqueda en lo grabado.
- **El servidor usa mucha menos memoria para la búsqueda**: el modelo de embeddings pasa a su versión de 4 bits y corre
  con 2 hilos fijos. Misma calidad en el set de 30 preguntas (81 % → 80 %) y en la búsqueda por nombre de speaker, con
  ~0,4 GB de RAM en vez de más de 3 GB en Railway. Además, al terminar el cálculo del catálogo le devuelve al sistema la
  memoria que quedó libre.
- **Responder con la voz, más claro**: un botón compacto con el micrófono y, mientras graba, una barra con punto rojo,
  tiempo y nivel del micrófono (como al grabar una charla), para terminar o cancelar. Al terminar muestra "Pasando a
  texto…".
- **Chips de intereses y filtros más prolijos**: forma de píldora, tilde al elegirlos y el mismo estilo en el armado
  rápido, la entrevista y Buscar.
- **"Convertir en filtros" responde más rápido y cuesta mucho menos**: usa Claude Haiku 5.5 y reaprovecha (prompt
  caching) la lista de facetas, que es la mayor parte del pedido. Los filtros se siguen validando contra los valores
  reales del catálogo.
- **Transcripción de charlas más precisa** (cuando el STT pasa por el gateway): usa Whisper large-v3 completo en vez del
  turbo, que se equivoca menos con acentos y ruido de sala.
- **Menos errores con nombres técnicos al transcribir**: el STT recibe un vocabulario de AWS y datos (lakehouse,
  Neptune, Trainium, Redshift…), en las charlas y en las respuestas por voz de la entrevista, que además pasan a
  Whisper large-v3 completo.

### Arreglado
- Las pestañas del detalle (y los días del itinerario) quedaban tapadas al bajar porque se pegaban a 68 px fijos: ahora
  se pegan justo debajo del encabezado, sea cual sea su alto (notch, cuenta regresiva, modo prueba).
- La franja de arriba y la barra con el logo eran dos bloques pegados arriba que se pisaban: ahora son uno solo.
- Contraste: «Deshacer» del aviso en oscuro (2,8:1) y la píldora «Listo» (3,8:1) pasan AA; los horarios y códigos que
  debían ir en mono ahora lo están.

## [0.20.0] - 2026-11-10

### Agregado
- **Armado guiado del itinerario** (la opción recomendada; el cuestionario de siempre queda como "Armado rápido"):
  - **Te conocemos**: una entrevista de una pregunta por pantalla (rol, día a día, equipo, desafío, trayectoria,
    nivel, qué usan, qué te querés llevar, qué evitar y ritmo del día). Las respuestas largas se pueden dictar con 🎤.
    La IA hace hasta dos repreguntas y arma tu ficha, que podés corregir.
  - **Armá tu día**: elegís con qué arrancás y te propone lo que sigue según tu ficha y la distancia, con un estado
    por opción: 🟢 a tiempo, 🟡 justo, 🟠 salí N min antes (y a qué hora), 🔴 se superpone (con cuántos minutos). Si la
    charla no está reservada, cuenta 30 min de cola. "☆ Para otro día" guarda una charla en pendientes y vuelve primera
    cuando se repite. También: pausa, arrancar más tarde y "Completá el resto del día por mí".
  - En el itinerario, cada charla muestra si salís antes y se puede marcar como **✓ Reservada**.
- **Avisos de cola y de "salí antes"**: si una charla no está reservada, el aviso push, el banner y "Hoy" cuentan
  30 min de cola ("hacé la cola desde las 09:30"). Si elegiste irte antes de una charla para llegar a la siguiente, te
  avisa a esa hora ("Salí a las 09:26 para llegar a…").
- **Pasar a mi calendario**: desde el itinerario, un `.ics` con todo (charlas, eventos y Mis eventos) para el calendario
  del teléfono, con alarma a la hora de la cola si no está reservada.
- Al terminar un día en el armado guiado: resumen, lo que quedó afuera, **personas para conocer** (speakers de tus
  charlas de ese día, primero los de clientes, con link a su ficha para charlar) y eventos para la noche que no se pisan.
- **Importar reservas de AWS**: subí el calendario (.ics) que exportás desde tu agenda del portal de re:Invent y esas
  charlas quedan en tu itinerario como "✓ Reservada" (sin cola). Si ya tenías la charla en otro horario, la pasa al
  reservado.
- La ficha de la entrevista también se usa en el **chat de búsqueda** (prioriza lo que te sirve), en la **ficha para
  charlar con un speaker o empresa** y en el **armado rápido**.
- **Mis eventos**: cargá los eventos que te dan los proveedores (Eventos › "＋ Mi evento"), con sede, lugar de Google
  o dirección. Quedan fijados en tu itinerario, ocupan su horario, aparecen en "Hoy" y avisan cuándo salir.
- Resumen de las charlas en castellano: la ficha y las tarjetas lo muestran traducido y tienen un botón para ver el
  original en inglés. La elección queda recordada en el celular. La búsqueda por texto también busca en la traducción.
- Claves extraídas del resumen de cada charla: servicios de AWS que menciona (completan los que AWS no etiquetó),
  otras tecnologías (Iceberg, MCP, dbt…), conceptos en castellano e inglés y enfoque (novedades, arquitectura, caso
  de cliente, práctica guiada…). Son filtros nuevos en Explorar, aparecen en la ficha de la charla y mejoran la búsqueda.

- Modo prueba por usuario, que se prende desde Admin › Usuarios. Lo que hace ese usuario queda aparte y sus datos reales
  no se tocan. El admin elige si la transcripción y el LLM son de prueba (gratis) o reales, puede simular la hora y la
  ubicación (una sede) para probar "Hoy" antes del evento, y adelantar el reloj. Arriba de la app se ve una franja
  "MODO PRUEBA". Los datos de prueba se borran con un botón.

- Ubicación y "Llevame":
  - En "Hoy", la charla de ahora y la próxima muestran a cuánto quedan, cuánto se tarda caminando (Routes API de
    Google) y a qué hora salir.
  - Cada horario de una charla muestra la distancia.
  - "Llevame" abre Google Maps con la navegación a pie.
  - El mapa marca dónde estás.
  - La ubicación se usa solo en el celular; se puede apagar en Ajustes.

- Pestaña **Eventos**: desayunos, happy hours, fiestas y meetups alrededor de re:Invent, con imagen, resumen en
  castellano, tipo, organizadores, anotados, precio, si piden aprobación y si están llenos. Filtros por día y tipo, y
  orden por cercanía. Se agregan al itinerario (quedan fijados), aparecen en "Hoy" y avisan si se superponen con una charla.

- Countdown de lo fijado: una franja arriba cuenta cuánto falta para la próxima charla o evento fijado, dice a qué hora
  salir y cambia de color cuando hay que salir ya. Avisa "Salí ahora" y "Empieza en 5 min" (ajustables en Ajustes ›
  Alertas). "Hoy" y la ficha de los eventos muestran el countdown.
- Avisos de cambios: si AWS cambia el horario o la sala de algo de tu itinerario, lo da de baja, o un evento se llena,
  aparece un aviso hasta que tocás "Entendido".
- Notificaciones en el celular (Web Push), que se activan en Ajustes. Llegan con la app cerrada: cuándo salir, cuándo
  empieza y los cambios. En iPhone funcionan con la app instalada en la pantalla de inicio.
- Charlas repetidas: la ficha muestra los otros horarios, cuál tenés, con qué chocaría cada uno, y "Cambiar a este"
  (conserva el 📌). "Me la perdí" ofrece los otros horarios y charlas parecidas que empiezan pronto. Después de una charla
  fijada, la app pregunta si llegaste.
- Admin › Chequeo funcional: prueba cada parte de la app (catálogo, búsqueda, datos de prueba aislados, reloj simulado,
  proveedores, procesos, claves) y, en el celular, ubicación, mapa, Routes API y notificaciones.

### Cambiado
- En el itinerario, "Bloquear" pasa a llamarse "📌 Fijar". Las charlas y eventos que se superponen se marcan.
- Las sedes y sus coordenadas salen de un maestro en la base (`reinvent.sede`) en lugar de estar fijas en el código.
  Los bares y restaurantes dentro de un hotel (Canonita, Tableau…) se muestran como sala de ese hotel.
- Perfil profesional de los speakers: los perfiles que resultaron ser de otra persona con el mismo nombre ya no se
  muestran (ni el cargo en la charla ni la trayectoria en la ficha). Los que no se pudieron confirmar llevan el aviso
  "Puede no ser esta persona". Se revisaron a mano y con un LLM unos 600 perfiles dudosos.
- La app vive en `reinventar.app`. Entrar por `www.reinventar.app` redirige al dominio sin www, que es donde funcionan
  las passkeys y los avisos. Las passkeys creadas en el dominio anterior hay que volver a registrarlas.

## [0.19.0] - 2026-11-06

### Agregado
- CI en GitHub Actions: tests de núcleo contra Postgres en cada PR y en cada push a `dev`.
- Promoción automática `dev` → `main` (fast-forward) cuando pasan los tests; Railway deploya con el push a `main`.
- Claude Code en GitHub: `@claude` en issues y PRs, con PRs contra `dev` y `CLAUDE.md` como guía del repo.

### Seguridad
- Dependencias instaladas desde locks con hashes y solo wheels (`requirements.lock`, `requirements-dev.lock`) en CI y en Docker.
- Acciones de GitHub fijadas por SHA de commit.
- Hashes de caché (embeddings, temas, briefings) con SHA-256 en lugar de SHA-1/MD5. Al desplegar se recalculan una vez.
- Los logs no incluyen el texto que escribe el usuario, y los rechazos de passkeys se loguean en una sola línea (sin inyección de líneas falsas).

### Arreglado
- Errores que se perdían en silencio en la PWA: reintentar el procesamiento, fijar una charla, quitar una passkey,
  cambiar de pestaña y leer el audio pendiente ahora avisan con un mensaje. La subida en segundo plano muestra el error.
- El service worker avisa en consola si no puede guardar en caché, en vez de fallar en silencio.
- Test de filtros en lenguaje natural que fallaba según el orden (carrera con el nombrado de temas en segundo plano).

## [0.18.0] - 2026-11-05

### Agregado
- Pantalla **Hoy** en el inicio: la charla de ahora, la próxima y el resto del día, con "Grabar esta charla" (`GET /api/today`).
- **Buscar** unificado, con dos modos: Filtrar (facetas en un panel inferior) y Preguntar (chat con RAG).
- Diálogos propios para confirmar y para pedir datos, "Deshacer" en las acciones destructivas, tags, skeletons y tarjetas con riel de tiempo.
- Fichas de charla, speaker y empresa con jerarquía nueva y la sección "Para conversar".
- Medidor de nivel por segmentos y estado de la grabación visible.
- Versión única de la app, informada en `/health` y verificada por tests.
- `CHANGELOG.md`, `.editorconfig`, `.gitattributes` y `requirements-dev.txt`.

### Cambiado
- Rediseño completo sobre los tokens de Brick v2: logo de onda de voz, navegación con íconos y fuentes Inter y JetBrains Mono.
- La navegación queda en tres secciones: Inicio, Buscar e Itinerario. `#/explorar` y `#/preguntar` redirigen a Buscar.
- Las URLs de los íconos llevan versión para que el navegador tome el logo nuevo.

### Arreglado
- Accesibilidad: foco al título de cada pantalla, salto al contenido, orden de encabezados y foco devuelto al cerrar diálogos.
- Menos saltos de diseño al cargar (fuentes de reemplazo con métricas ajustadas y placeholders).

## [0.1.0] - 2026-10-17

Primera versión. Las versiones entre 0.1.0 y 0.18.0 no se publicaron por separado; el detalle está en el historial de git.
Lo que se sumó en ese período:
- Grabación con cola offline, transcripción, traducción y resumen por tipo de sesión.
- Login por usuario y contraseña, passkeys (Face ID / huella) y módulo de administración.
- Itinerario recomendado con resolución de choques y mapa de venues.
- Catálogo de re:Invent en Postgres, con fichas navegables de charla, speaker y empresa.
- Búsqueda híbrida (embeddings + BM25), chat Preguntar, explorador por facetas, filtros en lenguaje natural y temas emergentes.
- Briefing para preparar una conversación y bloques de transcripción de 15 s.

[Sin publicar]: https://github.com/alejandrogenovese/reinventar/compare/v1.3.4...HEAD
[1.3.4]: https://github.com/alejandrogenovese/reinventar/compare/v1.3.3...v1.3.4
[1.3.3]: https://github.com/alejandrogenovese/reinventar/compare/v1.3.2...v1.3.3
[1.3.2]: https://github.com/alejandrogenovese/reinventar/compare/v1.3.1...v1.3.2
[1.3.1]: https://github.com/alejandrogenovese/reinventar/compare/v1.3.0...v1.3.1
[1.3.0]: https://github.com/alejandrogenovese/reinventar/compare/v1.2.0...v1.3.0
[1.2.0]: https://github.com/alejandrogenovese/reinventar/compare/v1.1.3...v1.2.0
[1.1.3]: https://github.com/alejandrogenovese/reinventar/compare/v1.1.2...v1.1.3
[1.1.2]: https://github.com/alejandrogenovese/reinventar/compare/v1.1.1...v1.1.2
[1.1.1]: https://github.com/alejandrogenovese/reinventar/compare/v1.1.0...v1.1.1
[1.1.0]: https://github.com/alejandrogenovese/reinventar/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/alejandrogenovese/reinventar/compare/v0.22.0...v1.0.0
[0.22.0]: https://github.com/alejandrogenovese/reinventar/compare/v0.21.0...v0.22.0
[0.21.0]: https://github.com/alejandrogenovese/reinventar/compare/v0.20.0...v0.21.0
[0.20.0]: https://github.com/alejandrogenovese/reinventar/compare/v0.19.0...v0.20.0
[0.19.0]: https://github.com/alejandrogenovese/reinventar/compare/v0.18.0...v0.19.0
[0.18.0]: https://github.com/alejandrogenovese/reinventar/compare/v0.1.0...v0.18.0
[0.1.0]: https://github.com/alejandrogenovese/reinventar/releases/tag/v0.1.0
