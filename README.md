# Glass

Glass es una herramienta experimental para grabar sesiones reales y analizarlas como una linea de tiempo de actividades.

El proyecto nacio explorando vidrio, dedo, trazos y reconocimiento visual, pero la linea actual ya no es reconocimiento de dedo ni OCR de trazos. El foco actual es:

- grabar video real
- extraer capturas visuales espaciadas
- analizar actividad visual con OpenAI Vision
- generar una bitacora temporal
- producir `timeline.json`, `timeline.txt`, `summary.json` y `summary.txt`

## Flujo Actual

Interfaz local:

```powershell
streamlit run app.py
```

Grabacion desde consola:

```powershell
python glass_recorder.py
```

Luego:

```text
graba video
|
S guarda y sale
|
se ejecuta analisis automatico
|
genera timeline.json, timeline.txt, summary.json, summary.txt
```

## Archivos Principales

- `app.py`: interfaz Streamlit local centrada en iniciar una sesion y generar "Tu Reflejo".
- `glass_recorder.py`: graba video real, guarda metadata y lanza analisis automatico.
- `video_activity_analyzer.py`: analiza videos largos usando capturas visuales espaciadas y OpenAI Vision.
- `glass_core/recorder.py`: nucleo reutilizable de grabacion real usado por CLI y Streamlit.

## Instalacion

```powershell
pip install -r requirements.txt
```

Crea un archivo `.env` local:

```text
GLASS_MODE=local
OPENAI_API_KEY=tu_clave
MONGO_URI=tu_uri_mongodb
CLOUDINARY_CLOUD_NAME=tu_cloud_name
CLOUDINARY_API_KEY=tu_api_key
CLOUDINARY_API_SECRET=tu_api_secret
```

No subas `.env` a GitHub. MongoDB y Cloudinary son opcionales en esta fase: si faltan credenciales, Glass mantiene el flujo local y marca la persistencia remota como omitida.

## Modos De Ejecucion

Glass tiene dos modos:

- `GLASS_MODE=local`: grabador real. Usa OpenCV en el computador local, analiza el video, guarda archivos locales, espeja datos en MongoDB y sube el video a Cloudinary si hay credenciales.
- `GLASS_MODE=cloud`: visor. No intenta abrir camara ni usar OpenCV para grabar. Carga sesiones persistidas desde MongoDB y muestra videos desde Cloudinary si existen.

En Streamlit Community Cloud configura estos secrets desde el panel, no con `.env`:

```text
GLASS_MODE=cloud
OPENAI_API_KEY=...
MONGO_URI=...
CLOUDINARY_CLOUD_NAME=...
CLOUDINARY_API_KEY=...
CLOUDINARY_API_SECRET=...
```

La grabacion real con OpenCV solo funciona en modo local. En la nube, OpenCV correria en el servidor de Streamlit, no en el computador del usuario, por eso Glass Cloud funciona como visor de reflejos.

## Interfaz Glass

```powershell
streamlit run app.py
```

La app sigue un flujo unico:

- Inicio: una accion principal, `Iniciar sesion`.
- Sesion activa: cronometro grande, estado REC, detalle seleccionado y session ID.
- Transicion: generacion del reflejo.
- Tu Reflejo: duracion observada, timeline visual, categorias detectadas y lectura narrativa.

V1 esta pensada como instrumento de observacion del tiempo. La captura y el analisis productivos siguen evolucionando por etapas.

La interfaz Streamlit orquesta el nucleo:

```text
Iniciar sesion
|
GlassRecorder
|
video real
|
analyze_video(...)
|
Tu Reflejo
```

## Persistencia Remota Opcional

El almacenamiento local sigue siendo la fuente inmediata:

- `metadata.json`
- `timeline.json`
- `summary.json`
- `summary.txt`
- video local

Despues de un analisis exitoso, Glass intenta crear un espejo remoto:

- MongoDB `glass_sessions`: metadata de la sesion, estado del analisis y rutas locales.
- MongoDB `glass_analysis`: timeline y summary ya generados localmente.
- Cloudinary: solo el video final de la sesion.

Si MongoDB o Cloudinary fallan, el analisis local sigue siendo valido. El error queda registrado en `metadata.json` mediante campos como `mongo_status`, `cloudinary_status`, `cloudinary_video_url`, `cloudinary_public_id` y `persistence_error`.

## Trazabilidad Del Reflejo

Glass no debe mezclar sesiones.

El mapeo esperado es:

```text
sesion
|
metadata.json
|
video generado
|
analysis_output_dir
|
timeline.json + summary.json + summary.txt
|
Tu Reflejo
```

En la interfaz Streamlit, el reflejo solo se considera listo cuando el analisis pertenece a la sesion activa. Si no existe un analisis asociado a esa sesion, Glass deja el reflejo como pendiente en vez de mostrar resultados de otra sesion.

## Detalle Del Analisis

Opciones actuales:

- `10` = Muy detallado
- `20` = Detallado
- `30` = Balanceado, valor por defecto
- `60` = Rapido
- `120` = Panoramico

La interfaz lo expresa como puntos de observacion estimados, no como configuracion tecnica.

## Grabacion

```powershell
python glass_recorder.py
```

Controles:

- `S` = guardar video, cerrar y analizar automaticamente
- `P` = snapshot manual
- `ESC` = cerrar guardando

Las grabaciones quedan en:

```text
glass_recordings/YYYYMMDD-HHMMSS/
```

Cada sesion guarda:

- video `recording_YYYYMMDD-HHMMSS_duracion-HH-MM-SS.mp4`
- `metadata.json`
- snapshots manuales si se presiona `P`

## Analisis Manual

Tambien puedes analizar un video directamente:

```powershell
python video_activity_analyzer.py ruta\video.mp4 --every 120
```

El analisis genera:

```text
video_analysis/YYYYMMDD-HHMMSS/
|-- frames/
|-- timeline.json
|-- timeline.txt
|-- summary.json
`-- summary.txt
```

## Que Analiza

El analizador no usa audio. Solo usa capturas visuales del video.

El timeline puede servir para:

- habitos
- rutinas
- orden
- estudio
- trabajo
- limpieza
- descanso
- cocina
- higiene
- eventos visibles
- tiempos muertos

Cada segmento incluye:

- inicio y fin con `HH:MM:SS.mmm`
- categoria general
- actividad detectada
- confianza
- observaciones
- evidencia visual
- utilidad para habitos

## Privacidad Y GitHub

No deben subirse a GitHub:

- `.env`
- videos
- `glass_recordings/`
- `video_analysis/`
- modelos `.task`
- caches de Python
- experimentos archivados pesados

Revisa `.gitignore` antes de publicar.

## Archivo Historico

Las pruebas anteriores de Finger Lab, MediaPipe, trazos, OCR de caracteres, reconstruccion textual y pizarra visual quedan archivadas en:

```text
archive/experiments/
```

No forman parte del flujo actual.

## Proxima Fase

No implementada todavia.

Posibles siguientes pasos:

- iniciar y finalizar sesiones desde la interfaz
- vista mas rica de timeline y resumen
- historial persistente de sesiones
- posible MongoDB para persistencia
- posible Cloudinary para almacenamiento de videos/imagenes
- OpenAI Vision para analisis
