# Reclamos Vecinales de La Matanza

Plataforma vecinal con registro, moderación, mapa, seguimiento privado y borrador imprimible. La aplicación requiere un servidor Python. GitHub conserva el código fuente.

## Prueba local

Se requiere Python 3.12 o posterior. Instalá las dependencias con `python -m pip install -r requirements.txt`. Probá con datos ficticios.

```bash
export RV_DEMO=1
export RV_SECRET="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"
export RV_ADMIN_PASSWORD="$(python -c 'import secrets; print(secrets.token_urlsafe(24))')"
printf '%s\n' "$RV_ADMIN_PASSWORD"
python app.py
```

Abrí http://127.0.0.1:8000 y usá `/#admin` para moderar. En PowerShell se asignan variables con `$env:RV_DEMO = "1"` y `$env:RV_SECRET = python -c "import secrets; print(secrets.token_urlsafe(48))"`. Aplicá la misma sintaxis a la clave de administración y ejecutá `python app.py`.

Conservá el mismo secreto entre reinicios. El secreto interviene en los comprobantes privados y evita duplicar apoyos. En la prueba local, el código de correo queda en un archivo privado, sin envío por internet. Para leerlo después de solicitarlo:

```bash
python -c 'import app; print((app.DATA / "demo-mail" / app.digest("mail:vecino@example.com")).read_text())'
```

## Operación

- `RV_DATA` apunta a un directorio privado y persistente, fuera del directorio que sirve el proxy. El servidor entrega únicamente los archivos públicos de su lista explícita.
- `RV_ORIGIN` contiene el origen HTTPS exacto. Para producción, conectar `app:application` a un servidor WSGI y un proxy HTTPS, con límite de cuerpo de 17 MiB y límites de conexión. Configurar el proxy y servidor WSGI para que `REMOTE_ADDR` refleje la IP real a partir de un proxy de confianza. La aplicación ignora encabezados de IP remitidos por el cliente.
- Definir `RV_ADMIN_PASSWORD` y `RV_SECRET` como secretos fuertes. Mantener privado el panel y limitar el acceso al volumen. El acceso administrativo inicial usa una clave compartida.
- `RV_PRIVACY_TEXT` presenta el responsable del tratamiento, propósito, plazo de guarda y canal para ejercer derechos. Sin este texto, el registro identificado y el correo de apoyos permanecen deshabilitados fuera del modo local. `RV_CONTACT_ENABLED=1` habilita además Sumate. Revisar su puesta en servicio antes de recibir solicitudes reales.
- Para los códigos de apoyo, configurar `RV_SMTP_HOST`, `RV_SMTP_FROM`, `RV_SMTP_PORT` (465 por defecto) y, si el proveedor lo requiere, `RV_SMTP_USER` y `RV_SMTP_PASSWORD`. Se usa SMTP sobre TLS.
- El mapa usa Leaflet y teselas de OpenStreetMap para uso moderado. El listado permanece disponible si no cargan las teselas. El mapa muestra hasta 500 reclamos recientes. La validación actual usa un rectángulo de latitud y longitud, con localidad elegida de una lista. La moderación debe verificar que el punto corresponda al partido.
- La ficha no expone identidad, correo ni número de expediente. Se publican la referencia y la descripción editadas por moderación y las imágenes conservadas tras la revisión. El número oficial y su historial se cargan manualmente y se consultan con la clave privada.

## Respaldo y restauración

Ejecutá `python backup.py /ruta/privada/copias`. Utiliza el respaldo consistente de SQLite y verifica integridad; incluye fotos y datos privados. Programalo con el planificador del servidor y definí rotación, copia cifrada fuera del servidor y permisos exclusivos. Conservá el secreto por separado.

Para restaurar, detener la aplicación y probar primero la copia en un directorio privado de ensayo con el nombre `reclamos.sqlite3`. Validar la consulta de reclamos y fotografías. Para pasar a producción, apuntar `RV_DATA` al directorio restaurado y conservar el directorio anterior hasta verificar el servicio. No mezclar archivos WAL de distintas bases.

## Migración a PostgreSQL

El esquema y el acceso están centralizados en `database.py`. Las fotos forman parte de la base y los IDs los genera la aplicación. La migración requerirá adaptar los parámetros SQL, sustituir BLOB por BYTEA y reemplazar `BEGIN IMMEDIATE` por transacciones con bloqueos de filas equivalentes. Migrar tablas en un orden que respete las referencias y verificar totales, fotos, claves de seguimiento y duplicados antes del cambio. SQLite sigue siendo la implementación activa.

## Pruebas

Ejecutá `PYTHONPATH=. python tests/test_platform.py` desde la raíz del repositorio. La prueba usa una base temporal y datos ficticios.

## Formularios por categoría

Elegí una categoría para abrir su formulario, ver qué datos conviene reunir y encontrar el canal de presentación. El botón de la sección abre el mapa con esa categoría aplicada. En el mapa se puede combinar categoría con localidad. Alumbrado público y maltrato animal tienen borradores orientativos con destinatario propio.

Fuentes para la orientación de ambos trámites:

- [Atención Ciudadana 147 de La Matanza](https://www.lamatanza.gov.ar/147).
- [Derecho Fácil sobre maltrato animal](https://www.argentina.gob.ar/justicia/derechofacil/leysimple/maltrato-animales).
- [Oficinas de denuncias del Ministerio Público de la Provincia de Buenos Aires](https://mpba.gov.ar/denuncia).
