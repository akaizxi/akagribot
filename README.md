# Akagri Spam — bot de Telegram, sin web

Subí `bot.py`, `Dockerfile` y `.gitignore` a la raíz de tu repositorio de GitHub. Railway puede usar ese repositorio; el Dockerfile arranca el bot automáticamente. No requiere dependencias externas, dominio ni puerto HTTP.

Variables en Railway:

| Variable | Valor |
|---|---|
| BOT_TOKEN | El token de este bot, obtenido en BotFather |
| OWNER_ID | ID numérico de la persona que administrará este bot |
| BOT_DATA_DIR | /data |

Conectá un Volume al servicio y montalo en `/data`. No alcanza con crear una variable: el volumen es lo que conserva grupos y mensajes. Mantené una réplica. Detené cualquier instalación anterior que use el mismo token. No subas el token al repositorio.

Si necesitás indicar un comando de inicio: `python bot.py`.

Abrí el chat privado del bot y mandá `/start`. Solo OWNER_ID puede usar el panel; no se concede acceso por nombre de usuario ni por ser la primera persona que escriba.

## Uso

1. Agregá el bot a tus grupos o canales autorizados, con permisos para publicar.
2. Entrá al dashboard con /start.
3. Creá una publicación, dale un nombre y mandá su contenido (texto o una foto).
4. Elegí destinos, frecuencia, fecha y botones opcionales.
5. Revisá la vista previa y activá la publicación con el botón de confirmación.

Podés crear hasta 100 publicaciones con configuraciones independientes y registrar hasta 100 grupos. Las fotos y el formato del texto se conservan usando los identificadores y entidades de Telegram. No admite álbumes ni videos.

Cada mensaje puede enviarse una vez o repetirse entre 1 y 43200 minutos. Las fechas se ingresan como DD/MM/AAAA HH:MM en horario de Argentina (UTC−3). Escribir `ahora` configura el inicio al activar. El envío puede retrasarse por límites de Telegram, red o cola de destinos.

Botones: una línea por botón con `Texto | https://enlace`. El primero ocupa una fila; los siguientes, hasta tres, van debajo. `quitar` los desactiva.

La pausa general conserva los estados individuales; reanudar no activa borradores. Editar contenido, destinos, botones o programación vuelve la publicación a borrador. Duplicar crea una copia en borrador sin fecha anterior. Cambiar solo el nombre no altera los envíos.

Los grupos se detectan mediante eventos de Telegram. Telegram no da una lista completa de todos los grupos históricos: si falta uno, agregalo por ID desde el panel. Si cambiás los permisos o vuelve a ingresar el bot, se actualizará su estado. El bot necesita permisos reales; ser miembro no garantiza permiso de enviar todo tipo de contenido.

## Reutilizar para clientes

Usá el mismo repositorio para crear **un servicio Railway por bot/cliente**, cada uno con su BOT_TOKEN, OWNER_ID y volumen. Así no hay web y cada cliente administra su bot en Telegram. Esta edición NO es el servidor multiusuario web anterior ni un bot central donde todos entregan sus tokens. No incluye pagos, suscripciones ni licencias.

## Datos y entregas

- Conserva los datos entre reinicios usando el volumen. No importa automáticamente la base del bot viejo; usa `akagri.sqlite3`.
- Un volumen queda asociado al ID del bot: si usás otro token de otro bot, necesitás otro volumen.
- Se respetan esperas 429. Hay separación mínima de 3,2 segundos por grupo y el programador procesa hasta un destino por segundo.
- Las repeticiones cuentan desde el último envío confirmado y no acumulan rondas perdidas.
- Si una entrega queda incierta por una caída o un error de red, se marca para revisión sin reenviarla automáticamente. Revisá Telegram antes de editar/reactivar.
- Los errores de permisos o contenido detienen ese destino. Consultá Historial y la ficha de la publicación.
- El token se lee de variables de entorno, no se guarda en SQLite. Protegé el volumen: contiene textos y datos de grupos.

Validado con pruebas simuladas; falta probar con tu token real y tus grupos después del despliegue. No se ha realizado prueba de carga.

Para probar localmente: Python 3.11 o posterior, configurar BOT_TOKEN y OWNER_ID en el entorno, y ejecutar `python bot.py`. Si no hay BOT_DATA_DIR, guarda datos en `datos/` junto al script.
