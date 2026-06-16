# Glass

Glass es una herramienta experimental para grabar sesiones reales y analizarlas como una linea de tiempo de actividades.

El proyecto nacio explorando vidrio, dedo, trazos y reconocimiento visual, pero la linea actual ya no es reconocimiento de dedo ni OCR de trazos. El foco actual es:

- grabar video real
- extraer frames espaciados
- analizar actividad visual con OpenAI Vision
- generar una bitacora temporal
- producir `timeline.json`, `timeline.txt`, `summary.json` y `summary.txt`

## Flujo Actual

```powershell
python glass_recorder.py
```

Luego:

```text
graba video
↓
S guarda y sale
↓
se ejecuta analisis automatico
↓
genera timeline.json, timeline.txt, summary.json, summary.txt
```

## Archivos Principales

- `glass_recorder.py`: graba video real, guarda metadata y lanza analisis automatico.
- `video_activity_analyzer.py`: analiza videos largos usando frames espaciados y OpenAI Vision.

## Instalacion

```powershell
pip install -r requirements.txt
```

Crea un archivo `.env` local:

```text
OPENAI_API_KEY=tu_clave
```

No subas `.env` a GitHub.

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
├── frames/
├── timeline.json
├── timeline.txt
├── summary.json
└── summary.txt
```

## Que Analiza

El analizador no usa audio. Solo usa frames.

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

- app Streamlit
- subir o seleccionar video
- ver timeline
- ver summary
- historial de sesiones
- posible MongoDB para persistencia
- posible Cloudinary para almacenamiento de videos/imagenes
- OpenAI Vision para analisis
