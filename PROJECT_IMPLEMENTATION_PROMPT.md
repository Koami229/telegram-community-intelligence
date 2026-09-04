# Prompt maestro para evolucionar el proyecto

Actua como ingeniero senior de Python, FastAPI, SQLAlchemy, Alembic y Telethon. Trabaja sobre este repositorio y mejora el sistema de ingesta autorizada de Telegram de forma incremental, verificable y mantenible.

## Objetivo

Construir una plataforma que permita archivar mensajes y metadatos de fotos, videos, documentos, audio y otros medios de grupos o canales de Telegram a los que la cuenta autenticada tenga acceso legitimo. El sistema debe servir para moderacion, auditoria, analisis interno o preservacion con autorizacion.

## Limites obligatorios

- No evadas privacidad, permisos, restricciones de descarga, controles de acceso, invitaciones, rate limits ni mecanismos antiabuso de Telegram.
- No intentes acceder a grupos privados, mensajes o archivos que la cuenta no pueda consultar mediante la API oficial y su sesion autorizada.
- No implementes scraping de cuentas, perfiles o miembros sin una base legal y una finalidad documentada.
- La descarga binaria debe estar desactivada por defecto; primero guarda metadatos y permite habilitarla por grupo mediante una configuracion explicita.
- Respeta los terminos de Telegram, derechos de autor, privacidad y la legislacion aplicable. Incluye retencion, borrado y exportacion de datos.
- No registres API hashes, tokens, contrasenas, cadenas de sesion, contenido completo de mensajes ni datos personales innecesarios en logs.

## Estado actual que debes preservar

El backend ya contiene:

- FastAPI en `app/main.py`.
- Modelos SQLAlchemy y migracion Alembic inicial.
- Resolucion autorizada de grupos en `app/services/group_service.py`.
- Sincronizacion de miembros en `app/services/sync_service.py`.
- Monitorizacion de eventos en `app/workers/monitoring.py`.
- Cliente y autenticacion Telethon en `app/telegram/`.
- Tests unitarios en `tests/`.

No hagas refactors amplios ni rompas las APIs existentes.

## Alcance funcional por fases

### Fase 0: seguridad y operabilidad

1. Mantener sesiones, `.env`, bases locales, exports y media fuera de Git.
2. Documentar que una sesion Telegram comprometida debe revocarse y regenerarse.
3. Añadir autenticacion a la API antes de exponer datos.
4. Añadir auditoria de quien inicia una ingesta y de que grupo se procesa.
5. Añadir configuracion de limites: tamano maximo, tipos permitidos, ruta de almacenamiento, retencion y descarga binaria.

### Fase 1: modelo de mensajes y medios

Crear modelos y migracion para:

- `TelegramMessage`: grupo, id del mensaje, fecha, autor opcional, texto opcional, tipo y hash de contenido.
- `TelegramMedia`: mensaje, tipo, nombre seguro, MIME, tamano, identificador remoto no secreto, ruta local opcional, hash SHA-256, estado de descarga y timestamps.

Usar claves unicas por grupo y `telegram_message_id`; evitar duplicados en reintentos.

### Fase 2: ingesta autorizada

Implementar un servicio aislado, por ejemplo `app/services/message_ingestion_service.py`, que:

- Verifique conexion y autorizacion antes de cada trabajo.
- Verifique que el grupo esta registrado y activo en la base de datos.
- Use `iter_messages` de Telethon con limites explicitos (`limit`, `min_id`, `max_id`, fechas).
- Respete `FloodWaitError` y falle de forma reanudable.
- Guarde primero metadatos; descargue solo si el grupo y la tarea lo permiten.
- Use nombres de archivo generados por la aplicacion, nunca nombres sin sanear recibidos del mensaje.
- Calcule SHA-256 mientras escribe y use escritura atomica a un directorio controlado.
- No descargue archivos ejecutables por defecto y rechace tamanos superiores al limite.
- Guarde cursores y estado de tarea para reanudar sin duplicar.

### Fase 3: API y trabajos

Anadir endpoints autenticados para:

- Iniciar una ingesta historica con filtros de fecha/tipo.
- Consultar estado, progreso y errores.
- Listar mensajes y medios con paginacion.
- Solicitar borrado de un grupo, mensaje o medio segun la politica de retencion.
- Exportar metadatos en JSONL/CSV sin incluir secretos.

Usar un sistema de tareas durable para produccion. `asyncio.create_task` puede mantenerse solo para desarrollo y debe tener registro, cancelacion y recuperacion en shutdown.

### Fase 4: calidad

- Tests unitarios para parseo y politicas.
- Tests de integracion con PostgreSQL y Alembic.
- Tests con Telethon mockeado para mensajes, medios, FloodWait y permisos insuficientes.
- Prueba de idempotencia y reanudacion.
- Prueba de limites de tamano, MIME, path traversal y borrado.
- Lint, type checking y compilacion.

## Forma de trabajar

Antes de cada edicion:

1. Identifica el archivo y simbolo que controlan el comportamiento.
2. Formula una hipotesis comprobable y un test barato que pueda refutarla.
3. Haz el cambio minimo.
4. Ejecuta inmediatamente el test o comprobacion mas estrecha.
5. No ocultes fallos de infraestructura: reporta dependencias, variables de entorno y servicios faltantes.

## Criterios de aceptacion

Una fase solo esta terminada cuando:

- La migracion puede aplicarse y revertirse.
- La ingesta no accede a grupos no registrados o no autorizados.
- Reintentar la misma tarea no duplica mensajes ni medios.
- Las tareas se pueden reanudar desde un cursor persistido.
- Los binarios no se descargan sin una opcion explicita.
- Los secretos y sesiones no aparecen en Git ni en logs.
- Los tests relevantes pasan y las limitaciones quedan documentadas.

Empieza por auditar el estado real del repositorio, despues implementa solo la Fase 0 y la primera pieza pequena de la Fase 1. No simules que una restriccion de Telegram puede eliminarse: cuando el acceso no existe, devuelve un error claro y seguro.