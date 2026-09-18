# Guía de usuario de BlindRSS

## Guía de usuario de BlindRSS {#user-guide}

BlindRSS es un cliente de escritorio y podcast de fácil lectura de pantalla.
RSS y Atom alimenta, juega podcast y video recintos, y funciona bien en sus
propia o contra una cuenta anfitriona como Miniflux, Inoreader, The Old Reader, o
BazQux.

Esta guía se almacena dentro de la aplicación, por lo que funciona sin internet
Presione F1 en cualquier lugar de BlindRSS para abrirlo.
control, diálogo, elemento de menú o ventana que está utilizando tiene su propia sección, F1
abre la guía en esa sección en lugar de al principio.

Todo aquí es accesible desde el teclado. Utilice la lista de contenidos para mover
entre secciones, o el cuadro de búsqueda para encontrar una palabra en cualquier lugar de la guía.

## Comienzo {#getting-started}

Cuando BlindRSS comienza por primera vez no tiene ningún alimento. Hay varias maneras
para añadir algunos:

- Presione Ctrl+N para agregar un pienso por dirección. Ver Añadir un pienso.
- Presione Ctrl+Shift+F para buscar directorios podcast y feed por nombre.
  Encontrar Podcasts y RSS Feeds.
- Importar un archivo OPML exportado de otro lector. Ver Importar OPML.
- Importar un archivo de YouTube Takeout para suscribirte a cada canal que ya tengas
  ver Importar un archivo de toma de YouTube.
- Inicie sesión en una cuenta alojada bajo Herramientas, Ajustes, Proveedor y BlindRSS
  lee las suscripciones ya en esa cuenta. Ver Cuentas en línea y
  Proveedores.

Una vez que tenga alimentos, presione F5 para refrescarlos.
lista de artículos, y cuentas sin leer aparecen junto a cada alimento en el árbol.

Los tres lugares que vale la pena visitar temprano son Herramientas, Ajustes (cómo BlindRSS
Comportamientos), Herramientas, Atajos de teclado (cada comando y su clave), y esto
guía.

## La ventana principal {#main-window}

La ventana principal tiene cuatro regiones principales más una barra de menús y una barra de estado. (Tab)
Shift+Tab se mueve entre ellos, y los paneles de ciclo F6 en la mayoría de los gestores de ventanas.

- Los alimentadores y carpetas arbol a la izquierda.
- El campo de búsqueda por encima de la lista de artículos.
- La lista de artículos.
- El panel de lectura debajo de la lista de artículos.

La barra de menú contiene Archivo, Editar, Ver, Jugador, Herramientas y Ayuda.
llegar a ella, luego utilizar las teclas de flecha. Cada elemento del menú tiene una llave de acceso en cada
lenguaje de interfaz, y la barra de menús se envuelve a ambos lados.

Tamaños, la alimentación seleccionada y el estado de la ventana se recuerdan entre las carreras.
"Recuerde el último feed/folder seleccionado en la puesta en marcha" en Ajustes, Controles Generales
si BlindRSS reabre en el pienso que fue la última lectura.

## Lista de piensos y carpetas {#feed-tree}

El árbol de la izquierda lista tus alimentos, las categorías que los agrupan, Smart
Carpetas, búsquedas guardadas y vistas incorporadas (Todas las semillas, Favoritos, Delete d
Artículos, y Alimentación con Errores).

- Up and Down arrows se mueve entre los elementos.
- Right Arrow expande una categoría, Left Arrow la colapsa.
- Enter o seleccionar un artículo carga sus artículos en la lista de artículos.
- F2 abre propiedades para el pienso seleccionado o la categoría.
- Applications key o Shift+F10 abre el menú contextual.

Cada alimento muestra su recuento sin leer.
Recordado, así que el árbol se ve igual la próxima vez que empieces.

Los alimentos que no actualizaron todavía se enumeran normalmente; los alimentos con errores
La vista los recoge para que un alimento que calladamente dejó de funcionar no se desnude.

## Lista de artículos {#article-list}

La lista de artículos muestra los artículos de lo que se selecciona en el árbol, después
se ha aplicado el filtro de artículo actual, orden de orden y plazo de búsqueda.

- Up and Down arrows se mueve entre los artículos; el panel de lectura sigue.
- Enter abre el artículo seleccionado.
- Shift+Up y Shift+Down extienden la selección, así que las acciones a granel funcionan en varios
  artículos a la vez.
- Backspace toggles read and unread on the selected article.
- Delete elimina los artículos seleccionados; Shift+ Delete los elimina sin el
  El aviso de confirmación.
- Ctrl+D añade o elimina un favorito.
- Applications key o Shift+F10 abre el menú contextual.

Que columnas aparecen, y en qué orden, es configurable globalmente y por alimento.
Ver columnas Lista de Artículo.

## Reading Pane {#reading-pane}

El panel de lectura debajo de la lista de artículos contiene el texto del artículo seleccionado.
Es un área de texto sólo lectura, por lo que un lector de pantalla puede leerla línea por línea, palabra
por palabra, o carácter por carácter, y el texto puede ser seleccionado y copiado.

- Ctrl+F busca dentro del texto del artículo.
- F3 y Shift+F3 se mueven al siguiente y último partido.
- Enter en un enlace en el texto abre ese enlace.

Cómo se presenta el texto es configurable en Ajustes, Alimentación y Artículos:
títulos se pueden anunciar, lista de artículos marcados con balas y números,
comillas marcadas, enlaces mostrados con su dirección, tablas descritas y imagen
texto alt incluido. El texto alt de la imagen también puede ser forzado en o apagado para una alimentación
del menú contextual de ese feed.

Si un pienso sólo publica un breve resumen, BlindRSS puede buscar el artículo completo
texto. Ver Full-Text Artículo Recuperación.

## Ventana de artículos {#article-window}

Abrir un artículo puede ponerlo en una ventana propia más que en la lectura
pane, que da el artículo toda la pantalla y lo mantiene abierto mientras se mueve
en la lista.

La ventana es un área de texto sólo lectura con la misma lectura, selección y
comportamiento de encontrar en texto como el panel de lectura. Escape lo cierra.

## Búsqueda {#search-field}

El campo de búsqueda por encima de la lista de artículos filtra la vista actual mientras escribe
y comprometerse con Enter.

- Ctrl+E se centra en el campo de búsqueda.
- Enter aplica el término.
- Escape , o el botón claro, lo vacía y restaura la lista completa.

El campo de búsqueda se puede ocultar si nunca lo utiliza; el menú Ver tiene un
Mostrar / evitar comando Search Field. Si la búsqueda coincide con los títulos solamente o
títulos y texto del artículo se establece en Configuración, Alimentación y Artículos bajo "Buscar
Partidos".

Una búsqueda que desea guardar puede ser convertido en una búsqueda guardada que permanece en el
Ver búsquedas persistentes.

## Status Bar {#status-bar}

La barra de estado en la parte inferior de la ventana principal tiene tres campos:

- Mensajes transitorios como cuántos artículos coincide un filtro.
- Actividad de fondo, como una actualización de alimentación o una descarga en curso.
- Estado de reproducción: lo que está jugando, y el tiempo transcurrido y restante.

Están deliberadamente separados para que un mensaje refrescante no pueda sobreescribir una búsqueda
el resultado cuenta mientras lo estás leyendo.

## Menús contextuales {#context-menus}

El árbol de alimentación y la lista de artículos tienen un menú contextual, abierto con el
Applications key o Shift+F10 . Mantienen los comandos que se aplican a lo que sea
seleccionados — refrescante, marcado leer, editar, eliminar, copiar enlaces, cola
medios, etcétera.

Los menús contextuales soportan F1 también: con un elemento destacado, F1 abre el
sección de esta guía que lo explica.

## Añadiendo una alimentación {#adding-feeds}

El archivo, Add Feed ( Ctrl+N ) se suscribe a un feed por dirección.

Pruebe o escriba la dirección de la alimentación, o del propio sitio — BlindRSS se ve
para una alimentación en la página cuando la dirección no es una alimentación.
Canal de YouTube o dirección de lista de reproducción, perfil Mastodonte o Bluesky, PieFed o
Comunidad Lemmy, una página SoundCloud o Mixcloud, o un Reddit o Groups.io
dirección, y BlindRSS lo convierte en una alimentación.

Elija la categoría en la que debe entrar o dejarla sin categorizar.
"Open in HTML view" opción hace que los artículos de este feed se abran en la rica vista
por defecto.

Si no conoce la dirección, use Encontrar Podcasts y RSS Feeds en su lugar.

## Detección de las semillas en una página {#detect-feeds}

File, Detectar Feeds en Page toma la dirección de una página web ordinaria y listas
los feeds que página anuncia, por lo que puede suscribirse sin cazar para los
El enlace de alimentación.

Este es el comando correcto cuando un sitio tiene un enlace "subscribe" o "RSS"
no se puede llegar fácilmente, o cuando la página ofrece varios feeds (todas las entradas, una
categoría, comentarios) y desea elegir.

## Encontrar Podcasts y RSS Feeds {#find-podcast}

Herramientas, Encontrar un podcast o RSS Feed ( Ctrl+Shift+F ) búsquedas podcast y feed
directorios por nombre, tema o dirección del sitio, para que pueda suscribirse sin
Conociendo cualquier dirección de alimentación.

1. Escriba lo que está buscando en el cuadro de búsqueda — un nombre de podcast, un tema,
  o una dirección del sitio.
2. Elige una fuente o déjala en "Todas las fuentes".
3. Presione Enter o el botón Buscar.
4. Arrow a través de la lista de resultados. Cada fila muestra el título, que directorio él
  vino de, y detalles.
5. Presione Enter en un resultado, o elija OK, para suscribirse a él.

Las búsquedas corren contra varios directorios a la vez y los resultados llegan como cada uno
una respuesta, por lo que la lista crece mientras la lee. Escape cierra el diálogo y
Para la búsqueda.

## Podcast y Feed Directories {#podcast-directories}

El cuadro Fuente en Encontrar un podcast o RSS Feed elige dónde buscar.
"Todas las fuentes", "Todas las fuentes de podcast", y "Todas las fuentes de alimentación RSS", estas
Los directorios están disponibles individualmente:

- Dirección de podcast: iTunes (Apple Podcasts), gPodder, fyd, Podverse,
  SoundCloud y Mixcloud.
- Directores de alimentación: NewsBlur, Feedspot, Google News, Bing News y Feedly.
- Búsqueda de sitios y comunidades: YouTube, Reddit, Groups.io, y el Fediverse —
  Mastodonte, Bluesky, PieFed y Lemmy o Kbin, cada uno también seleccionable por sí mismo.
- Descubrimiento basado en direcciones: Feedsearch, y el propio escáner web de BlindRSS, que
  embrague un sitio y busque alimentos en él.

No se utiliza un directorio único. Búsqueda de "Todas las fuentes" consultas del podcast
y grupos RSS juntos y fusiona los resultados, manteniendo una amplia consulta de Google News
feeds debajo de los partidos de alimentación directa.

## Suscribir a un Resultado de Búsqueda {#subscribing}

En cualquiera de los diálogos de búsqueda — Encontrar un podcast o RSS Feed, Búsqueda de vídeo, o
El botón encontrar de Podcast Archive — pulsando Enter en un resultado, o eligiendo OK con
seleccionó, se suscribe a ella.

BlindRSS resuelve el resultado a una dirección de alimentación real primero, así que suscribirse a un
podcast encontrado en un directorio, un canal de YouTube o una cuenta Fediverse
el nuevo alimento aparece en el árbol y es refrescado
inmediatamente.

Si lo desea en una categoría particular, muévelo después de su contexto
menú o desde Propiedades Feed.

## Podcast Archive {#podcast-archive}

Herramientas, Archivo de Podcast navega por la historia del episodio completo de un podcast — ambos el
episodios todavía en su alimentación y los más viejos BlindRSS recuperados — y
los descarga en lotes.

Muchos piensos podcast publican sólo los episodios más recientes.
automáticamente en el fondo; esta ventana es donde usted ve su estado,
retratar a mano, y descargar lo que encontró.

- Elija el podcast en la caja Podcast.
- Los episodios de filtro estrechan la lista mientras escribes.
- Rescan archivo corre recuperación de nuevo para ese podcast.
- Encontrar o añadir podcast abre la búsqueda de alimentación para que pueda archivar un podcast que haga
  aún no se suscriben.
- Juega el episodio seleccionado, Descargar las descargas seleccionadas, y Descargar
  todo descarga la lista visible.
- Cancelar descargas detiene un lote que está funcionando.

La ventana permanece abierta mientras un lote descarga, para que puedas seguir leyendo.

## Búsqueda de vídeo {#video-search}

Herramientas, Búsqueda de vídeo busca cada sitio web yt-dlp puede preguntar, en una sola vez, y permite
juegas, colas o suscribes a lo que encuentra.

- Escriba un término de búsqueda y presione Enter o el botón Buscar.
- El cuadro de alcance limita la búsqueda a un sitio; la búsqueda predeterminada todos ellos.
- Los resultados llegan cuando cada sitio responde, los sitios principales primero.
  Llegar como los propietarios de lugares están llenos mientras se resuelven.
- Cargar Más Resultados bloquea otro lote de cada sitio.
- Ordenar por un encabezado de columna reordena lo que ha llegado.

Los videos idénticos encontrados en varios sitios se fusionan en una fila.
son excluidos a menos que "Habilitar sitios adultos en Búsqueda de Video" se activa
Ajustes, Avanzado.

## Abrir un artículo por URL {#open-article-url}

Archivo, Open Article toma la dirección de cualquier página web y la lee en BlindRSS
como si fuera un artículo — texto extraído, en el panel de lectura, con el mismo
leer opciones como todo lo demás.

Úsalo para una página de un solo paso que te enviaron, sin suscribirte a nada.
la página es un foro o un hilo de discusión, BlindRSS lee todo el hilo.
Foro y discusión.

## Abrir una URL de medios {#open-media-url}

Archivo, Open Media URL reproduce audio o vídeo desde una dirección en la red integrada
jugador sin suscribirse a nada.

Acepta enlaces de medios directos y direcciones de página que yt-dlp puede resolver -
YouTube, Rumble, Odysee, SoundCloud y muchos más.
otro artículo y se puede añadir a la cola de juego.

## Eliminación de una alimentación {#removing-feeds}

Archivo, Eliminar Suscripciones Feed de la alimentación seleccionada. El mismo comando está en
el menú contextual de la alimentación.

La eliminación de un pienso elimina sus artículos de la base de datos.
todo lo que ya ha descargado en el disco. Si utiliza un proveedor de alojamiento, el
El descrédito también se envía a esa cuenta.

Para eliminar toda una categoría y todo en ella, utilice Delete Category y Feeds
en el menú contextual de la categoría. Ver Categorías y Subcategorías.

## Propiedades federales {#feed-properties}

F2 , o Editar Feed en el menú contextual, abre las propiedades del seleccionado
Alimento.

- Su título, que usted puede anular; "Reset Title to Feed Default" en el
  context menu pone el propio título de la alimentación de nuevo.
- Su dirección y la categoría a la que pertenece.
- Si los nuevos artículos de él plantean una notificación.
- Si se abre en la rica vista HTML.
- Su propio diseño de columnas de la lista de artículos, en la pestaña Lista de encabezados, sobrescribiendo la
  global.

Ver ficha Descripción del menú contextual de la lista de artículos muestra la descripción
el alimento mismo publica.

## Categorías y Subcategorías {#categories}

Categorías grupos se alimentan en el árbol, y pueden anidar: una categoría puede contener
tanto alimentos como subcategorías adicionales.

- File, Add Category crea uno.
- Añadir Subcategoría en el menú contextual de una categoría crea uno dentro de ella.
- Editar Categoría renombra o lo mueve. Ver Categoría Propiedades.
- Eliminar Categoría elimina la categoría pero mantiene sus feeds.
- Delete Category and Feeds elimina la categoría y descríbete de
  todo en ella.
- Importar OPML Aquí importa un archivo directamente en esa categoría.
- Exportar Categoría a OPML exporta sólo esa rama.

Algunos proveedores hospedados mantienen categorías en una sola lista plana.
caso, BlindRSS lo dice y las opciones de "move to parent" no están disponibles.

## Categoría {#category-properties}

Editar Categoría abre las propiedades de la categoría: su nombre, y el padre
categoría se sienta debajo.

Renombrar una categoría mantiene todos sus piensos. Moviéndolo mueve toda la rama,
incluyendo cualquier subcategoría.

## Refreshing Feeds {#refreshing}

- F5 refresca cada alimento.
- Ctrl+F5 refresca sólo el alimento seleccionado o la categoría.
- Shift+F5 detiene un refresco que está funcionando.
- Actualizar Categoría en el menú contextual de una categoría refresca esa rama.

Sólo una de las semillas de refrescos y Stop Refresh está disponible en un momento, por lo que la
El comando teclado coincide con lo que el menú ofrece.
status bar field.

El refrigerio automático está configurado en Configuración, Alimentación y Artículos: el
intervalo, cuántos feeds refrescan a la vez, cuántas conexiones por host, el
per-feed timeout, y cuántas veces un alimento fallido es retriado. "Automáticamente
refrescante alimenta al principio" refresca todo en el lanzamiento, y la startup
opción de carga de trabajo elige entre usar el caché y forzar un refresco completo.

## Alimentación con errores {#feed-errors}

La vista Feeds with Errores, y Archivo, Ver Errores Feed, lista los feeds cuyos
la última actualización falló, con la razón.

Un pienso que silenciosamente dejó de funcionar se parece exactamente a un pienso sin nuevo
artículos, por lo que esta visión existe. De ella se puede:

- Refresh Seleccionado, para intentarlo de nuevo ahora.
- Copia detalles, para poner el texto de error en el portapapeles.
- Propiedades de alimentación, para corregir la dirección.
- Retire Feed, cuando el pienso se haya ido para siempre.

Las causas comunes son un alimento movido o retirado, un sitio que ahora requiere un navegador
check (ver Importing Site Cookies), y una salida temporal del servidor.

## Importación de OPML {#import-opml}

OPML es el formato de archivo estándar para una lista de suscripciones de alimentación.
lector puede exportar uno, así que OPML es cómo mueve sus suscripciones de otro
lector en BlindRSS sin agregar uno a la vez.

Archivo, Importación OPML pide el archivo y añade cada alimento en él, manteniendo el
categoría estructura del archivo describe. Feeds you are already subscribed to are
no duplicado.

Importar OPML Aquí, en el menú contextual de una categoría, pone toda la importación dentro
esa categoría en lugar de en el nivel superior.

Para obtener un archivo OPML de otro lector, busque "Export", "Backup", o
"Suscripciones" en su configuración.

## Exporting OPML {#export-opml}

Archivo, Export OPML escribe todas sus suscripciones, con sus categorías, a una
Archivo OPML.

Úsalo para respaldar tus suscripciones, para moverlas a otro lector o
máquina, o para compartir un conjunto de alimentos con otra persona. Exportar Categoría a OPML
en el menú contextual de una categoría exporta sólo esa rama.

## Importar un archivo de captura de YouTube {#import-youtube-takeout}

Google Takeout es el servicio de exportación de datos de Google. Un archivo de YouTube Takeout es un
Archivo ZIP que contiene sus datos de YouTube, incluyendo la lista de canales que usted
archivo, Import YouTube Takeout lee que ZIP y le suscribe a
esos canales como feeds, por lo que los nuevos vídeos de cada canal llegan como artículos.

Para obtener el archivo:

1. Vaya a takeout.google.com y firme con la cuenta de Google su YouTube
  Están subscripciones.
2. Elija "Deseleccionar todo", luego seleccione sólo YouTube y YouTube Music.
3. En "Todos los datos de YouTube incluidos", mantenga al menos "suscripciones"; "historia" y
  "jugalistas" son opcionales y BlindRSS también puede utilizarlos.
4. Exportar una vez como archivo ZIP, y esperar el correo electrónico de Google — un archivo grande puede
  tomar horas.
5. Descargar el ZIP y apuntar este comando en él.

BlindRSS entonces muestra lo que encontró, agrupado por fuente, y le permite elegir lo que
grupos a importar:

- Suscripciones: los canales que sigues.
- Historia: canales que has visto pero no sigues.
- Tus propios canales.
- Lista de reproducción, como alimento propio.

Se eliminan direcciones duplicadas, por lo que importando un segundo archivo más tarde añade sólo
lo que es nuevo. El ZIP nunca se desenvasa al disco; sólo los pequeños archivos de datos dentro
se lee.

## Búsquedas persistentes {#persistent-search}

Una búsqueda persistente es un término de búsqueda que permanece en el árbol como su propio objeto, por lo que
los artículos que coinciden son siempre una tecla de flecha.

Herramientas, Configure Persistent Search administra la lista: Añadir crea uno de un
término, Eliminar la elimina. Cada búsqueda guardada aparece en el árbol y es
re-evaluado cada vez que lo selecciona, por lo que siempre refleja la corriente
artículos.

Úsalo para un tema que sigues a través de cada alimento — nombre de una persona, un producto, un
lugar. Para cualquier cosa más estructurada que una frase, utilice carpetas inteligentes.

## Carpetas inteligentes {#smart-folders}

Una carpeta inteligente es una carpeta en el árbol cuyo contenido se define por una regla
en lugar de por qué alimentar un artículo vino de.

Nueva carpeta inteligente, en el menú contextual del árbol, abre el editor de reglas.
un conjunto de condiciones unidas por "tomar todo" (y) o "tomar cualquier" (o), y grupos
de las condiciones pueden anidar, por lo que "(A y B) o C" es expresible.

Las condiciones prueban estos campos:

- Sí/no campos: leer, favorito, abierto, actualizado.
- Campos de texto: título, contenido, descripción, autor, feed, url y etiqueta — el
  categorías o etiquetas que el propio sitio publica.

El uso de condiciones de texto contiene, no contiene, equivale o comienza con.

Las carpetas inteligentes nunca se mueven ni copian nada; son una vista sobre los artículos
Para cambiar los artículos a medida que llegan, utilice las Reglas de Filtro.

## Reglas de filtro {#filter-rules}

Herramientas, Reglas de Filtro es el motor de intercambio de artículos de BlindRSS.
entrando artículos de la manera en que los filtros de correo electrónico se ejecutan sobre el correo entrante.

Cada regla combina una condición — el mismo editor de reglas Smart Folders utiliza— con una
conjunto de medidas:

- Mueva el artículo a una categoría.
- También etiqueta con una categoría, dejándolo donde está.
- Marca que lee.
- Marcarlo favorito.
- Delete, siguiendo el comportamiento de eliminación configurado.
- Skip its new-article notification.

Reglas ejecutadas en orden de lista, y cada regla habilitada que coincida con contribuye a su
acciones. Una regla marcada para detener termina el oleoducto para ese artículo una vez que tiene
coinciden, así que las reglas más tarde nunca lo ven.
Gana.

Una regla sin acciones no hace nada y es rechazada, así que una regla medio terminada
no puede tragar artículos en silencio.

## Artículo Filtro {#article-filter}

Ver, Artículo Filtro limita cada vista por estado leído y por si un artículo
los dos grupos se combinan.

- Ctrl+1 : todos los artículos.
- Ctrl+2 : sin leer solamente.
- Ctrl+3 : sólo lectura.
- Ctrl+4 : medios y no medios.
- Ctrl+5 : con medios solamente.
- Ctrl+6 : sin medios solamente.

El filtro se aplica a lo que se selecciona en el árbol, incluyendo carpetas inteligentes
y búsquedas guardadas, y persiste entre carreras. "Con medios solamente" es el
manera más rápida de convertir un pienso mixto en una lista de podcast.

## Ordenar artículos {#sorting}

View, Sort By orders the article list by date, name, author, description, feed,
o estado. Ascendiendo mueve la dirección; el default es el más nuevo primero.

El tipo se aplica a cada vista y se recuerda entre carreras.
es útil en todas las semillas y en carpetas inteligentes, donde los artículos provienen de muchos
fuentes a la vez.

## Artículo Lista Columnas {#list-headers}

Las columnas en la lista de artículos, su orden, y sus anchos son suyos a
configuración, lista de encabezados establece el diseño global; una lista de alimentación
La pestaña Headers la anula para ese feed, y "Utilice el diseño de la columna global"
apaga la anulación.

Menos columnas significan menos para un lector de pantalla para leer en cada fila, así que es
vale la pena quitar cualquier que nunca use.

## Artículos de apertura {#opening-articles}

Enter en un artículo en la lista lo abre. Dependiendo del artículo y su
configuración, que significa el panel de lectura, una ventana propia, o el HTML rico
vista.

- Abrir Artículo en el menú contextual hace lo mismo.
- Abra en Browser da la dirección del artículo a su navegador web del sistema.
- Open Accessible Browser lee la página dentro de BlindRSS en su lugar.
  Navegador accesible.

Abrir un artículo lo lee a menos que haya cambiado ese comportamiento.

## Leer y no leer artículos {#read-status}

- Backspace , o Toggle Read/Unread, voltea el artículo seleccionado.
- Ctrl+Shift+R marca todo en la vista actual como leído.
- Marcar todos los elementos como Leer, en el menú contextual de una fuente o categoría, hace lo mismo
  para esa rama.
- Marcar como leer y marcar como leer en el menú contextual de la lista de artículos actuar en el
  selección completa, y decir cuántos artículos afectarán.

Los recuentos no leídos aparecen junto a cada alimento en el árbol.
leer artículos enteramente.

## Favoritos {#favorites}

Ctrl+D añade el artículo seleccionado a Favoritos, o lo elimina si ya está
La vista de los favoritos en el árbol lista todo lo que ha marcado.

Los favoritos sobreviven a la política de retención: un artículo que usted ha protagonizado no
eliminado cuando los artículos más antiguos se limpian. Favorito también es utilizable como
condición en carpetas inteligentes y reglas de filtro.

## Delete d Artículos {#deleted-articles}

Lo que hace Delete es configurable en Ajustes, General, bajo "Cuando borro un
artículo":

- Muévete a Delete d Artículos, donde se puede restaurar.
- Retíralo permanentemente.
- Muévete a una categoría que nombre.

Con el primer ajuste, la vista Delete d Artículos en el árbol lista lo que usted
Retirada, Restaurar pone un artículo de vuelta, y eliminando desde dentro esa vista
lo quita para siempre.

"Confirma antes de borrar artículos" controla el aviso de confirmación.
Shift+ Delete siempre se salta.

## Recuperación del artículo de texto completo {#full-text}

Muchos piensos publican sólo un titular y una frase o dos.
la página del artículo y extraer el texto real, por lo que el panel de lectura muestra todo
artículo en lugar de un teaser.

Esto sucede automáticamente a medida que pasa por la lista, en el fondo, y
el resultado es caché. "Cache texto completo en el fondo" en Ajustes, Alimentación y
Artículos prefija los artículos alrededor de su posición para mover abajo la lista
no espera en la red.

Si un sitio se niega a ser leído en absoluto, generalmente está detrás de un cheque del navegador.
Importar las cookies del sitio.

## Rich Full-Text View {#rich-view}

Ctrl+Shift+H cambia el panel de lectura a la rica vista HTML, que hace que el
artículo la forma en que un navegador, con encabezados, listas, tablas y enlaces como
elementos reales que un lector de pantalla puede navegar con sus propios comandos estructurales.

La vista simple del texto es el predeterminado porque es más rápido y nunca sorprende
la rica vista vale la pena para artículos cuya estructura tiene significado.

Una alimentación se puede configurar para siempre abrir en la rica vista desde sus propiedades federales, y
enlaces en la vista rica abierta en su navegador de sistema en lugar de dentro de la vista.

## Navegador accesible {#accessible-browser}

Ver, Open Accessible Browser abre una página dentro de BlindRSS en una ventana construida
para lectura de pantalla, en lugar de entregarlo a su navegador del sistema.

Es la herramienta adecuada para una página que necesita ser leída en lugar de interactuar
con, y para sitios cuya propia interfaz es difícil de navegar. Comparte
Ajustes de cookies y de identidad del navegador de BlindRSS, así que páginas detrás de un navegador
comprobar abierto aquí también una vez que haya importado galletas para ellos.

## Videos de YouTube {#youtube}

Se puede suscribir un canal de YouTube o una dirección de lista de reproducción como cualquier alimento.
vídeos luego llegan como artículos, con la descripción, la transcripción, y
capítulo inline, por lo que se puede leer un vídeo en lugar de observar.

Playback pasa por yt-dlp. Ajustes, YouTube lo controla:

- Un archivo de cookies, que permite que BlindRSS vea restricciones de edad y solo miembros
  videos a los que tiene acceso. Se puede importar desde un navegador directamente, o
  recogido automáticamente de las exportaciones de cookies.txt en su carpeta Descargas.
- "Play YouTube descargando primero", que es más lento para empezar y mucho más
  confiable.
- La carpeta de caché de reproducción y su tamaño máximo, con un botón para limpiarla.

Importar YouTube Takeout te suscribe a cada canal que ya sigues
Un paso.

## Temas de debate y foro {#forums}

Reddit, Lemmy, Groups.io y Google Groups son leídos como hilos enteros más bien
que como un post a la vez: abrir una discusión le da el post original
y las respuestas en un texto continuo, que es mucho más rápido de leer
que seguir un hilo en un navegador.

Suscribir obras de la misma manera que cualquier alimento — pegar la dirección del subreddit,
comunidad, o grupo. Los repositorios GitHub son compatibles de la misma manera, como son
Cuentas y comunidades Mastodonte, Bluesky y PieFed.

## Cortar, Copiar y Pegar {#clipboard}

El menú Editar contiene los comandos de portapapeles estándar — Corte ( Ctrl+X ), Copia
( Ctrl+C ), Paste ( Ctrl+V ), y Seleccionar todo ( Ctrl+A ) — y trabajan en cada texto
campo y en el panel de lectura.

BlindRSS añade comandos que copian cosas que sabe:

- Copia Link, la dirección del artículo.
- Copy Media Link, la dirección de su audio o vídeo.
- Texto de la copia, el texto del artículo como leído en el panel de lectura.
- Copiar URL Feed, la dirección del feed seleccionado.
- Copiar enlace de imagen, en un artículo con una imagen.

## El Jugador incorporado {#player}

BlindRSS juega podcast y video recintos en sí mismo, a través de VLC, por lo que la reproducción
Ctrl+Shift+P muestra o oculta la ventana del jugador,
y la reproducción continúa de cualquier manera.

Playback es suavizado por un proxy local de rango-cache, por lo que buscar en un
episodio largo es rápido incluso en una conexión lenta. Corrientes que necesitan resolver -
YouTube, Rumble, Odysee, pasa primero por Yt-dlp.

"Mostrar la ventana del reproductor al iniciar la reproducción" en Ajustes, Media Player decide
si la ventana aparece por sí sola cuando algo comienza.

## Controles de jugadores {#player-controls}

La ventana del reproductor tiene, en orden de la pestaña: el estado de reproducción, la posición
deslizador, tiempo transcurrido y total, rebobinar y botones de avance rápido, la caja de velocidad,
el botón de capítulos, y el deslizador de volumen. Cada uno de ellos es accesible y
operable del teclado, y cada uno anuncia su valor actual.

- Ctrl+P juega y pausa.
- Ctrl+S para.
- Ctrl+Left y Ctrl+Right rebobinan y avanzan rápido y repiten mientras se celebran.
  macOS, Option+Left y Option+Right hacen lo mismo, porque Ctrl+Left y
  Ctrl+Right pertenece al Control de Misión allí.
- Ctrl+Up y Ctrl+Down cambian el volumen.

Las teclas de búsqueda y volumen funcionan desde cualquier lugar en BlindRSS mientras que algo es
jugando, incluyendo desde dentro de un diálogo, así que nunca tienes que encontrar al jugador
ventana para pausar.

## Atajos del teclado del jugador {#player-shortcuts}

- Ctrl+Shift+P : mostrar o ocultar la ventana del jugador.
- Ctrl+P : jugar o pausar.
- Ctrl+S : Para.
- Ctrl+Left y Ctrl+Right : rebobinar y avanzar rápidamente ( Option+Left y Ctrl+Right
  Option+Right en macOS).
- Ctrl+Up y Ctrl+Down : volumen arriba y abajo.
- Ctrl+Shift+U , Ctrl+Shift+D , Ctrl+Shift+N : más rápido, más lento, volver a la normalidad
  velocidad.
- Ctrl+Shift+E : el ecualizador.
- Ctrl+Shift+C : la cola de juego.
- Ctrl+Shift+T y Ctrl+Shift+V : siguiente y anterior en la cola.

Todos estos son remappable en Herramientas, Atajos de teclado.
predeterminado deliberadamente a letras en lugar de a Ctrl+Shift+digit o
Ctrl+Shift+period , porque Windows y algunos complementos NVDA toman los antes de cualquier
la aplicación los ve.

## Playback Speed {#playback-speed}

Player, Playback Speed cambia lo rápido que juegan los medios, de media velocidad a triple
velocidad, con el campo preservado.

- Ctrl+Shift+U acelera, Ctrl+Shift+D disminuye, Ctrl+Shift+N vuelve a 1x.
- El submenú tiene pasos fijos: 0,5x, 0,75x, 1x, 1,25x, 1,5x, 1,75x, 2x, 2,5x,
  y 3x.
- La ventana del jugador tiene una caja de velocidad que se puede configurar directamente.

"Default Playback Speed" en Ajustes, Media Player establece la velocidad de todo
comienza en.

## Equalizer {#equalizer}

Ctrl+Shift+E , o Player, Equalizer, abre un ecualizador de diez bandas con un preamplificador.

- "Ecualizador de habilitación" activa todo el asunto.
- Cada banda es un slider que anuncia su ganancia a medida que lo cambia.
- Guardar como Preset almacena las bandas actuales bajo un nombre; Delete Preset elimina
  Uno.
- Reset (Flat) devuelve cada banda a cero.

El ecualizador se aplica a todo lo que juega BlindRSS, y su entorno es
Lo recordamos.

## Capítulos {#chapters}

Los podcasts y videos de YouTube suelen llevar capítulos.
ellos, Jugador, Capítulos los enumera y saltar a uno busca allí.

- Los capítulos submenú se llenan una vez que se conocen los capítulos del tema, y dice
  "No hay capítulos disponibles" cuando no tiene ninguno.
- La ventana del jugador tiene un botón de capítulos y una caja de capítulos.
- Enlaces Capítulo, en el menú contextual de la lista de artículos, enumera los enlaces un capítulo
  La descripción contiene.

Los capítulos están cargados en el fondo mientras se mueve a través de la lista, por lo que son
Normalmente listo antes de presionar el juego.

## Play Queue {#play-queue}

La cola de juego es la lista de lo que juega después.

- Ctrl+Shift+C abre la ventana de cola.
- Ctrl+Shift+T y Ctrl+Shift+V juegan el siguiente y anterior artículo.
- Añadir a Play Queue y Eliminar de Play Queue, en el contexto de la lista de artículos
  menú, cámbialo.

En la ventana de cola, Play comienza el elemento seleccionado, Move Up and Move Down
reordenar la cola, Eliminar gotas un artículo, y Limpiar Todo vacía. La cola
sobrevive descansando.

## Casting a otros dispositivos {#casting}

BlindRSS puede enviar lo que reproduce a un dispositivo de su red: Chromecast, altavoces AirPlay, reproductores DLNA/UPnP, altavoces Sonos, reproductores Roku y Kodi. Un episodio continúa en el dispositivo desde donde se estaba reproduciendo, y la pausa, el avance y retroceso y la posición funcionan allí igual que en local (Roku no permite avanzar ni retroceder).

Elija el dispositivo en el diálogo de transmisión; BlindRSS transmite a través de su propio proxy local, de modo que un dispositivo que no puede obtener la dirección original por sí mismo reproduce igualmente el elemento. Los controles de reproducción siguen funcionando desde BlindRSS mientras transmite.

## Skip Silence {#silence-skipping}

"Skip Silence (Experimental)" en Ajustes, Media Player detecta pasajes silenciosos
durante la reproducción y salta sobre ellos, que notablemente acorta podcasts hablar
con largas pausas.

Analiza el audio como se reproduce, por lo que cuesta algo de CPU y es marcada experimental.
Apágalo si la reproducción no es suave.

## Descarga de medios {#downloads}

- Descarga guarda el audio o vídeo del artículo seleccionado con su formato predeterminado.
- Descargar Como te permite elegir el formato primero.

Las descargas deben encenderse con "Enable Downloads" en Ajustes.
carpeta, la política de retención, y el formato de descarga de vídeo predeterminado se establecen en
la misma página; la carpeta predeterminada es la carpeta Descargas del sistema.

El progreso aparece en el segundo campo de barras de estado, y los artículos descargados juegan desde
disco después en lugar de sobre la red. El archivo Podcast puede descargar
todo el catálogo de un podcast en un lote.

## Ajustes {#settings}

Herramientas, Ajustes ( Ctrl+comma ) tiene todas las opciones, en las pestañas: General, Alimentación y
Artículos, YouTube, Media Player, Proveedor, Notificaciones, Traducir, Lista
Headers, Advanced, and CAPTCHA Solving.

Ctrl+Tab y Ctrl+Shift+Tab se mueven entre pestañas; Tab se mueve a través de los controles
en la ficha actual. OK aplica todo, Cancelar descartes todo. Tab
posiciones se mantienen estables entre liberaciones, porque se convierten en memoria muscular.

Presionar F1 en una pestaña abre la sección de la pestaña de esta guía.

## Ajustes: General {#settings-general}

- Interface language, and whether BlindRSS follows your system language. A
  el cambio tiene efecto en el reinicio. Ver Interface Language.
- "Recuerde el último feed/folder seleccionado en la startup".
- "Confirma antes de eliminar los artículos", y lo que elimina — se mueve a Delete d
  Artículos, eliminar permanentemente o pasar a una categoría que nombre.
- "Modo de depuración (show consola on startup)", que también escribe una rotación
  blindrss.log junto a sus datos.
- Inicio y bandeja: cerca de la bandeja, minimizar la bandeja, empezar en la bandeja, siempre
  empezar a maximizar, y comprobar las actualizaciones en el inicio.

## Ajustes: Alimentación y artículos {#settings-feeds}

- El intervalo de actualización automático, de cinco minutos a cuatro horas.
- Tanto si la búsqueda coincide con los títulos como con los títulos y el texto del artículo.
- Refrigerios máximos concurrentes, conexiones máximas por host, el tiempo de alimentación,
  y cuántas veces se retira un alimento fallido.
- Vistas máximas en caché, y "Cache texto completo en fondo".
- "Refrigere automáticamente los piensos al principio", y la carga de trabajo de actualización de la startup:
  use el caché, refresque completamente al inicio, o siempre refresque completamente.
- Retención de artículos, que decide cuánto tiempo se guardan los artículos.
  nunca removido por retención.
- Cómo se presenta el texto del artículo: anunciar encabezados, marcar elementos con
  balas y números, citas de marca, mostrar enlaces con su dirección, describir
  tablas, e incluyen texto alt de imagen.

## Ajustes: YouTube {#settings-youtube}

- El archivo yt-dlp cookies, con un botón Navegando, un "Import from browser"
  botón, y una opción para recoger las exportaciones de cookies.txt de sus Descargas
  Carpeta automáticamente.
- Leyendo las cookies directamente desde un navegador instalado.
- "Play YouTube descargando primero", que comienza más lentamente pero es el más
  opción confiable.
- La carpeta de reproducción de YouTube, su tamaño máximo en megabytes, y un
  botón para aclararlo ahora.

Las cookies son lo que hacen que los vídeos solos y limitados por edad sean jugables, y ellos
son lo que un "firme para confirmar que no eres un bot" error es pedir.

## Ajustes: Media Player {#settings-media-player}

- La tarjeta de sonido preferida, o el sistema predeterminado.
- "Skip Silence (Experimental)".
- La velocidad de reproducción predeterminada.
- "Mostrar la ventana del reproductor al iniciar la reproducción".
- El tamaño de caché de red en milisegundos, que intercambia retraso de inicio para
  resiliencia en una conexión lenta.
- Caminos a ffmpeg, ffprobe y yt-dlp. Deja un blanco a auto-detecto; un camino
  Usted puso anula la detección, y lo que se detectó se muestra al lado de cada uno.
- Descargas: si las descargas están habilitadas, la carpeta de descarga, la retención
  política, y el formato de descarga de vídeo predeterminado.
- Suena: si BlindRSS juega sus sonidos de notificación.

## Ajustes: Proveedor {#settings-provider}

Elige dónde viven tus suscripciones: localmente en BlindRSS, o en un host
Ver Cuentas y Proveedores en línea para lo que cada uno necesita.

La página muestra qué proveedor está activo y las credenciales para ella — un Miniflux
dirección y clave API, un ID de aplicación de Inoreader y clave con un botón Autorizar, o
una dirección de correo electrónico y contraseña para The Old Reader o BazQux. Autorización clara
firma una cuenta de Inoreader.

El proveedor local utiliza los alimentos que agrega dentro de la aplicación con Add Feed y
Importar OPML.

## Ajustes: Notificaciones {#settings-notifications}

- "Habilitar notificaciones para nuevos artículos", y si el nombre de la alimentación aparece
  en el texto de notificación.
- El número máximo de notificaciones por refresco, y si un resumen
  La notificación se muestra una vez que se llega a esa tapa.
- Test Notification envía uno ahora.
- Excluir Feeds elige alimentos que nunca lo notificarán.
- Anuncios: qué eventos BlindRSS habla directamente a su lector de pantalla,
  por evento, con un botón de anuncio de prueba que envía una prueba a través de ambos
  discurso y Braille.

## Ajustes: Traducir {#settings-translate}

Activa la traducción automática del contenido del artículo, y elige el servicio que
lo hace.

- "Habilitar la traducción automática para el contenido del artículo".
- El proveedor: Grok (xAI), Groq, OpenAI, OpenRouter, Gemini o Qwen.
- El idioma objetivo, elegido de la lista o escrito como un código como en, es,
  fr, o pt-BR.
- Una clave de API para el proveedor elegido, y opcionalmente un modelo específico.
  OpenRouter, "Load OpenRouter Models" incluye la lista de modelos disponibles.

Grok y Groq son diferentes servicios con nombres confusos similares: Grok es
xAI's, con llaves de consola.x.ai que comienzan con "xai-"; Groq acoge LLaMA y
Mistral, con llaves libres de consola.groq.com que comienzan con "gsk ".

Esto traduce el texto del artículo. Para cambiar el idioma de BlindRSS
interfaz, ver Interface Language.

## Ajustes: Lista de encabezados {#settings-list-headers}

Establece el diseño de la columna global de la lista de artículos: qué columnas aparecen, en qué
orden y cuán ancho. Ver Columnas Listas de Artículo.

Un pienso individual puede anular esto de sus propias Propiedades Alimentadas.

## Ajustes: Avanzado {#settings-advanced}

- Ubicación del almacenamiento de datos: mantenga su base de datos y configuraciones en los datos del usuario
  carpeta o en la carpeta de aplicación, con ambos caminos mostrados.
  app-folder opción es lo que hace una instalación portátil.
- Actualizaciones: "Instalar automáticamente actualizaciones sin confirmación".
- Identificación del navegador: qué navegador BlindRSS se identifica como cuando
  alimentación de búsqueda, o una cadena de comandos personalizados que escriba. La cadena efectiva
  se muestra a continuación. Esto importa para sitios que bloquean clientes desconocidos.
- Búsqueda de vídeo: "Habilitar sitios para adultos en Búsqueda de vídeo", por defecto.

## Ajustes: CAPTCHA Solving {#settings-captcha}

Una ruta opt-in, pagada, de última generación para sitios que responden con un CAPTCHA que
Las cookies importadas no pueden pasar.

"Hable CAPTCHA servicio de resolución" lo activa, y el campo clave API mantiene su
cuenta clave con el servicio de resolución. Se aplican tarifas por resolución, por lo que es
de forma predeterminada y sólo después de que todo lo demás haya fallado.

Pruebe Importar Cookies del Sitio primero; es gratis y resuelve la mayoría de los casos.

## Cuentas y proveedores en línea {#providers}

BlindRSS puede mantener sus suscripciones en sí, o leerlas de un hospedador
configuración, Proveedor elige qué.

- Local: las suscripciones viven en la propia base de datos de BlindRSS en esta máquina.
  está sincronizado en cualquier lugar.
- Miniflux: necesita la dirección de su servidor Miniflux y una clave de API de su
  Ajustes de cuenta Miniflux.
- Inoreader: necesita un ID de aplicación y clave de aplicación de la página de desarrolladores de Inoreader, entonces
  el botón Autorizar para iniciar sesión.
- El lector antiguo: necesita su dirección de correo electrónico de cuenta y contraseña.
- BazQux: necesita su dirección de correo electrónico de cuenta y contraseña.

Con un proveedor hospedado, leer estado, suscripciones y categorías son las
la cuenta, así que te siguen a cualquier otro dispositivo firmado en la misma
Algunos proveedores mantienen categorías en una sola lista plana, y BlindRSS
dice que en lugar de ofrecer anidación que no se pegaría.

## Notificaciones {#notifications}

BlindRSS plantea una notificación del sistema cuando llegan nuevos artículos, sujeto a
Ajustes, notificaciones.

- Las notificaciones pueden apagarse completamente.
- El nombre de alimentación se puede incluir en el texto.
- Una tapa limita cuántos llegan por refresco, con un resumen opcional
  notificación una vez que se alcance la tapa.
- Los piensos individuales pueden ser excluidos, ya sea de Excluir las Alimentación en Ajustes o
  desde "Notificaciones para esta alimentación" en el menú contextual de la alimentación.
- Una Regla de Filtro puede suprimir la notificación para los artículos que coincide.

Por separado, los anuncios hablan los eventos elegidos directamente a su lector de pantalla
a través de la propia interfaz de NVDA o JAWS, y a través de Braille, que consigue a través de
incluso cuando una notificación del sistema no lo hace.

## Traducción {#translation}

Con traducción activada en Ajustes, Traducir, texto del artículo se traduce
en su idioma de destino mientras lo lee, utilizando el servicio AI que configura.

La traducción ocurre a la demanda y está caché, por lo que la relección de un artículo no
necesita una conexión a Internet y su propia clave API con la
Servicio elegido.

La interfaz de aplicación se traduce por separado, a través de sus propios catálogos.
Ver Interface Language.

## Importar las cookies del sitio {#site-cookies}

Algunos sitios ponen una página de verificación del navegador — típicamente un Cloudflare "checking
su navegador" desafío — en frente de su contenido.
una sesión que ya pasó el desafío en un navegador real, así que BlindRSS
no puede atraparlos por sí solos.

Herramientas, Importar Cookies del Sitio le da esa sesión:

1. Abra el sitio web en su navegador web y espere a que termine de cargar.
2. Exportar sus cookies a un archivo cookies.txt con un navegador cookie.txt
  extensión. Para los navegadores basados en Chrome, el diálogo se vincula a "Obtener cookies.txt
  Muy bien.
3. Elija el archivo exportado en el diálogo.
4. Pruebe la cadena User-Agent de su navegador en el campo de abajo.
  web para "lo que es mi agente de usuario" lo muestra. Cloudflare requiere exactamente
  Usuario-Agent la cookie fue emitida, así que esto importa.

Los navegadores de la familia Firefox tienen una ruta de un solo clic: "Import from Browser" lee
su base de datos de cookies directamente. Los navegadores basados en cromo encriptan el suyo, que
Es por eso que necesitan la extensión.

## Atajos de teclado {#keyboard-shortcuts}

Herramientas, Atajos de teclado lista cada comando en BlindRSS, agrupado por categoría,
con su llave actual, y le permite cambiar cualquiera de ellos.

- Seleccione un comando y elija Cambiar atajo.
  la siguiente combinación clave que presionas.
- Eliminar atajo deja un comando sin límites; todavía funciona desde su menú.
- Reset All to Defaults restaura las llaves enviadas.

Los atajos se envían antes de que los aceleradores del menú y trabajen en toda la ventana,
incluyendo mientras que la ventana del jugador tiene foco, y la ruta del teclado anuncia
en sí mismo donde la ruta del menú permanece en silencio. Sus cambios se almacenan con sus
configuración y sobrevivir las actualizaciones.

## Atajos de teclado predeterminados {#shortcuts-reference}

Feeds:

- Ctrl+N : Add Feed.
- F5 : Refresh Feeds. Shift+F5 : Stop Refresh. Ctrl+F5 : Refresh el pienso seleccionado.
- F2 : Editar Feed o Categoría.
- Ctrl+Shift+R : Marcar todos los elementos como Leer.
- Ctrl+Shift+F : Encuentre un podcast o una fuente RSS.

Artículos y opiniones:

- Ctrl+D : añadir o quitar de los favoritos.
- Backspace : toggle read and unread. Delete : delete. Shift+ Delete : delete
  sin confirmar.
- Ctrl+E : enfocar el campo de búsqueda.
- Ctrl+Shift+H : rica vista de texto completo.
- Ctrl+1 a Ctrl+3 : todo, sin leer, leer. Ctrl+4 a Ctrl+6 : medios y no medios,
  con medios, sin medios.

Jugador:

- Ctrl+P : jugar o pausar. Ctrl+S : parar. Ctrl+Shift+P : mostrar o ocultar el jugador.
- Ctrl+Left y Ctrl+Right : buscar. Ctrl+Up y Ctrl+Down : volumen.
- Ctrl+Shift+U , Ctrl+Shift+D , Ctrl+Shift+N : velocidad arriba, abajo, normal.
- Ctrl+Shift+E : ecualizador.
- Ctrl+Shift+C : cola de juego. Ctrl+Shift+T y Ctrl+Shift+V : siguiente y anterior.

Aplicación:

- F1 : esta guía, abierta en la sección para lo que esté usando.
- Ctrl+comma : Ajustes.
- Ctrl+Shift+A : anunciar la versión en ejecución.
- Ctrl+X , Ctrl+C , Ctrl+V , Ctrl+A : cortar, copiar, pegar, seleccionar todo.

Comandos no listados aquí barco sin límites y se puede dar cualquier llave en Herramientas,
Atajos de teclado.

## Interface Language {#language}

La interfaz de BlindRSS se traduce en quince idiomas.
elige uno, o lo deja siguiendo su lenguaje del sistema.
efecto cuando se reinicia.

Las traducciones se entregan entre las versiones de aplicación y con ellas,
por lo que una traducción corregida le llega sin esperar una nueva versión.

Esta guía sigue el mismo idioma cuando existe una guía traducida para ella, y
vuelve al inglés cuando no lo hace.

## Tray Icon y Media Keys {#tray}

BlindRSS puede vivir en la bandeja del sistema.
la ventana lo envía a la bandeja, ya sea minimizando, y si comienza
Ahí.

El icono de la bandeja tiene controles de reproducción y vuelve a abrir la ventana principal.
teclas multimedia del teclado — play/pause, stop, next, previous — control BlindRSS
jugador en todo el sistema.

## Añadiendo atajos de escritorio {#desktop-shortcuts}

File, Add Shortcuts crea atajos a BlindRSS en el escritorio, en el Start
Menú, y en la barra de tareas. Ataque los que desea y elija OK; el resultado de
cada uno es reportado de vuelta.

Una entrada de menú de inicio es también lo que Windows requiere antes de que una aplicación puede
elevar notificaciones, por lo que vale la pena tener incluso si usted lanza BlindRSS otro
Por cierto.

## Checking for Updates {#updates}

Ayuda, Check for Updates pregunta si una versión más nueva está disponible y ofrece
instalarlo.

Cada actualización se verifica antes de que se aplique: su SHA-256 debe coincidir con el
publicado manifiesto, y en Windows su firma Authenticode debe ser válida.
actualización que falla o el cheque no está instalado.

"Compruebe las actualizaciones de inicio" en Ajustes, General hace esto automáticamente, y
"Instalar automáticamente actualizaciones sin confirmación" en Ajustes, Avanzado
Los aplica sin preguntar. Sus configuraciones, bases de datos y descargas son
intacto por una actualización.

## Anunciando la versión {#version}

Ayuda, Anuncio versión ( Ctrl+Shift+A ) habla la versión BlindRSS en ejecución
directamente a su lector de pantalla.

El propio comando del lector de pantalla "versión de aplicación de informes" lee el
el recurso de versión ejecutable, que funciona para una construcción instalada pero reporta
Versión de Python cuando BlindRSS se ejecuta desde la fuente.
responder de cualquier manera.

## Acerca de BlindRSS {#about}

Ayuda, Acerca muestra la versión, la licencia y enlaces: el perfil GitHub, el
repositorio, y el cambio.

BlindRSS está bajo la licencia del MIT: utilizarla, cambiarla, redistribuirla o
empaquetarlo para los repositorios de distribución, sin permiso necesario.

## Usando esta ventana de ayuda {#help-window}

Esta ventana es un lector sencillo y totalmente accesible para el guía.

- La lista de contenidos contiene cada sección. Arrow a través de ella; seleccionando una sección
  salta el texto y anuncia su título.
- El área de texto es sólo lectura y seleccionable, por lo que un lector de pantalla puede leerlo
  línea por línea y puede copiarlo.
- Ctrl+F se mueve a la caja de búsqueda. Introduzca una palabra y presione Enter para saltar al
  próxima ocurrencia.
- F3 encuentra la próxima ocurrencia, Shift+F3 el anterior. Búsqueda envuelve alrededor.
- Tab y Shift+Tab se mueven entre el cuadro de búsqueda, la lista de contenidos y el
  texto.
- Escape cierra la ventana.

F1 en cualquier lugar de BlindRSS abre esta ventana en la sección para cualquier cosa que seas
usando — el control enfocado, el diálogo activo, el elemento de menú resaltado, o
Cuando no hay sección para ello, el guía se abre al principio.

La guía se muestra en el lenguaje de interfaz de BlindRSS cuando una traducción de ella
existe, y en inglés de otro modo.

## Solución de problemas {#troubleshooting}

Un alimento dejó de actualizar. Mira en Feeds con Errores por la razón.
necesita su dirección corregida en Feed Properties; un sitio que exija un cheque del navegador
necesita Importar Cookies del Sitio.

No se reproducirá un vídeo de YouTube. Importar cookies de YouTube en Ajustes, YouTube y
Enciende "Play YouTube descargando primero". Un "señal para confirmar que no eres un
error bot siempre significa cookies.

Cambia la caché de red en Ajustes, Media Player y gira
Skip Silence, que es experimental y cuesta CPU.

Un sitio no devuelve nada. Cambia la identificación del navegador en Ajustes,
Avanzadas; algunos sitios rechazan a clientes desconocidos de forma directa.

Nada habla cuando un comando funciona.
Notificaciones: cada evento puede ser encendido o apagado individualmente, y hay un
Botón de prueba.

Algo se comporta extrañamente y quieres reportarlo.
Ajustes, General, reproducir el problema, y adjuntar el blindrss.log escrito
junto a su configuración y datos.

## Apoyo y comunidad {#support}

Los errores y las solicitudes de características pertenecen al rastreador de problemas GitHub, en
github.com/serrebidev/BlindRSS/issues.

Para preguntas, ayuda y noticias de lanzamiento, el grupo SerrebiProjects en Telegram en
t.me/SerrebiProjects es el lugar más rápido para obtener una respuesta.

Las traducciones son siempre bienvenidas. Si usted habla uno de los idiomas compatibles
y algo lee mal, una solicitud de tirado que arreglará casi seguro que
aceptado — ver locale/README.md en el repositorio para cómo se colocan los archivos
lo mismo ocurre con esta guía: una copia traducida pertenece a
docs/help/<language>.md, manteniendo los marcadores {#anchor} exactamente como están en
el archivo Inglés tan sensible al contexto ayuda sigue funcionando.
