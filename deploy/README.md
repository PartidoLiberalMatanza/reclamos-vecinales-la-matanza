# Prueba con acceso restringido en PythonAnywhere

Crear una aplicación en la pestaña **Web**, con **Manual configuration** y Python 3.13. Usar el subdominio HTTPS que indica el panel y activar **Force HTTPS** antes de abrir el enlace o ingresar credenciales.

En una consola Bash de la cuenta, ejecutar:

```bash
git clone --branch desarrollo/plataforma-vecinal https://github.com/PartidoLiberalMatanza/reclamos-vecinales-la-matanza.git
cd reclamos-vecinales-la-matanza
python3.13 -m venv "$HOME/.virtualenvs/reclamos-vecinales"
"$HOME/.virtualenvs/reclamos-vecinales/bin/python" -m pip install --no-cache-dir -r requirements.txt
"$HOME/.virtualenvs/reclamos-vecinales/bin/python" deploy/configurar_prueba.py https://TU_USUARIO.pythonanywhere.com
```

En la pestaña **Web**, asignar el directorio del entorno virtual y reemplazar el contenido del archivo WSGI con:

```python
import runpy
from pathlib import Path

entry = Path.home() / "reclamos-vecinales-la-matanza" / "deploy" / "staging_wsgi.py"
application = runpy.run_path(str(entry))["application"]
```

Recargar la aplicación. Verificar primero que, en una ventana privada, se pide usuario y contraseña antes de servir la portada. El usuario de la prueba es `prueba`. La segunda contraseña generada corresponde al panel de administración.

Usar datos ficticios. Registrar un reclamo anónimo, moderarlo, comprobar que aparece en el mapa y consultar el seguimiento. Recargar el servicio y volver a comprobar que el reclamo sigue disponible. El entorno de prueba usa una base SQLite independiente y deshabilita registros identificados, solicitudes de Sumate y verificación por correo.

El plan gratuito tiene una cuota de 512 MiB y una fecha de vencimiento para la aplicación que se debe renovar. Reservar la base y las copias fuera del repositorio. El alojamiento de prueba no sustituye una decisión de operación pública, en especial sobre capacidad, correo y privacidad.

- [Aplicaciones web en PythonAnywhere](https://help.pythonanywhere.com/pages/WebAppBasics)
- [Activar HTTPS](https://help.pythonanywhere.com/pages/ForcingHTTPS)
- [Límites del plan gratuito](https://help.pythonanywhere.com/pages/FreeAccountsFeatures)
