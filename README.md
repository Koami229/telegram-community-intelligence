# Telegram Community Intelligence

Backend para ingerir mensajes y metadatos multimedia de grupos o canales de Telegram a los que la cuenta autenticada tenga acceso legitimo.

## Alcance

El proyecto no evade permisos, restricciones de descarga, privacidad, invitaciones ni limites de Telegram. No intenta acceder a contenido que la sesion no pueda consultar. Antes de usarlo, confirma la autorizacion del propietario del grupo, la finalidad del tratamiento y las obligaciones de privacidad y derechos de autor aplicables.

La ingesta guarda texto y metadatos de medios. La descarga binaria esta desactivada por defecto y requiere habilitacion explicita.

## Preparacion

1. Crea un entorno virtual e instala dependencias:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

2. Copia `.env.example` como `.env` y completa las credenciales. Nunca publiques `.env` ni archivos `sessions/*.session`.

3. Crea y autentica la sesion de Telegram:

```powershell
python scripts/auth_telegram.py
```

4. Ejecuta las migraciones:

```powershell
alembic upgrade head
```

5. Define una API key larga en `INGESTION_API_KEY` y arranca el backend:

```powershell
python run.py
```

## Ejecucion con Docker Compose

Con Docker Desktop iniciado y un `.env` configurado:

```powershell
docker compose up --build
```

El compose inicia PostgreSQL y Redis, espera sus healthchecks, aplica las migraciones y arranca la API en `http://localhost:8000`. Los datos de PostgreSQL y Redis se guardan en volumenes Docker; la sesion de Telegram y los medios se montan desde `sessions/` y `media/`.

`.dockerignore` evita que sesiones, `.env`, medios y artefactos locales entren en la imagen durante el build.

`GET /health` comprueba liveness y siempre responde para monitorización básica. `GET /ready` indica si PostgreSQL y la sesión autorizada de Telegram están disponibles para operaciones de datos.

## Flujo autorizado

1. Registra un grupo accesible por la cuenta mediante `POST /api/groups` e incluye `"collection_authorized": true` solo cuando tengas autorización documentada.
2. Ingiere metadatos con `POST /api/groups/{group_id}/messages/ingest`.
3. Consulta los mensajes con `GET /api/groups/{group_id}/messages`.
4. Para descargar un medio, habilita `MEDIA_DOWNLOAD_ENABLED=true` y usa una peticion autenticada a `POST /api/groups/{group_id}/messages/media/{media_id}/download`.
5. Para borrar una copia local y su metadata, usa `DELETE /api/groups/{group_id}/messages/media/{media_id}`. Esto no borra el mensaje original de Telegram.
6. Para aplicar la retencion configurada, usa `DELETE /api/groups/{group_id}/messages/media/retention`. Con `MEDIA_RETENTION_DAYS=0` no se elimina nada.

Las operaciones de mensajes y medios requieren la cabecera:

```text
X-API-Key: <INGESTION_API_KEY>
```

La descarga aplica limite de tamano, lista de MIME permitidos, nombre generado por la aplicacion, escritura atomica y hash SHA-256.

Los grupos se crean con `collection_authorized=false`. La ingesta se rechaza hasta que la petición de registro confirme explícitamente la autorización de recopilación.

También puedes confirmar o revocar la decisión de un grupo existente con `POST /api/groups/{group_id}/authorization` y el cuerpo `{"confirmed": true}` o `{"confirmed": false}`. El sistema guarda la fecha de confirmación local, pero esta marca no sustituye contratos, consentimiento ni asesoramiento legal.

Cada cambio queda registrado en `GET /api/groups/{group_id}/authorization/audit`. Puedes enviar `X-Actor-Label` y un `reason`; no se almacena la API key.

## Pruebas

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Las pruebas actuales usan mocks. Antes de produccion, valida la migracion y el comportamiento contra una base PostgreSQL de prueba.

## Seguridad de sesiones

Una sesion Telegram concede acceso a la cuenta. Si alguna sesion fue subida a Git o compartida, revocala desde Telegram, elimina los archivos locales comprometidos y genera una sesion nueva. `.gitignore` evita nuevos commits, pero no elimina archivos que ya forman parte del historial.
