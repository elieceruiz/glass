# AUDIT REPORT - Glass

Fecha: 2026-06-16

## Estado Actual

El proyecto `finger-lab` evoluciono desde pruebas de dedo, caracteres y reconstruccion textual hacia una linea util actual:

- `glass_recorder.py`
- `video_activity_analyzer.py`
- grabacion real de video
- analisis automatico post-grabacion
- `metadata.json`
- `timeline.json`
- `timeline.txt`
- `summary.json`
- `summary.txt`

La identidad "glass" se mantiene como memoria del origen: vidrio, observacion visual y registro de sesiones reales.

## Nucleo Actual

| Ruta | Uso | Decision | Riesgo |
| --- | --- | --- | --- |
| `glass_recorder.py` | Graba video real, guarda metadata y lanza analisis automatico. | Conservar en raiz | Alto si se mueve o cambia. Es el flujo principal. |
| `video_activity_analyzer.py` | Extrae frames, analiza con OpenAI Vision y genera timeline/resumen. | Conservar en raiz | Alto si se mueve o cambia. Lo importa `glass_recorder.py`. |
| `requirements.txt` | Dependencias del flujo actual. | Conservar y simplificar | Medio. Debe incluir OpenCV, OpenAI y dotenv. |
| `.env.example` | Plantilla segura de configuracion. | Crear/conservar | Bajo. No debe contener claves reales. |
| `.gitignore` | Evita subir secretos, videos, analisis y modelos grandes. | Crear/conservar | Alto si falta. |
| `README.md` | Documentacion principal del nuevo enfoque Glass. | Reescribir | Medio. Debe explicar flujo actual, no Finger Lab antiguo. |

## Experimentos Descartados

| Ruta | Uso Historico | Decision | Riesgo |
| --- | --- | --- | --- |
| `finger_lab.py` | Captura de caracteres con dedo, MediaPipe, OpenAI y seleccion textual. | Archivar en `archive/experiments/` | Bajo para flujo actual; alto solo para reproducir experimentos viejos. |
| `glass_board.py` | Pizarra visual con dedo. | Archivar en `archive/experiments/` | Bajo para flujo actual. |
| `recognize_with_openai.py` | Reconocimiento por caracter, palabras y reconstruccion. | Archivar en `archive/experiments/` | Bajo para flujo actual. |
| `analyze_character.py` | Analisis geometrico de caracteres. | Archivar en `archive/experiments/` | Bajo. |
| `analyze_session.py` | Analisis por carpeta de caracteres. | Archivar en `archive/experiments/` | Bajo. |
| `compose_session.py` | Composicion visual de caracteres. | Archivar en `archive/experiments/` | Bajo. |
| `hand_landmarker.task` | Modelo MediaPipe para seguimiento de mano. | Archivar en `archive/experiments/` y excluir de Git | Bajo para flujo actual; archivo pesado. |
| `finger_sessions/` | Sesiones de caracteres capturados. | Archivar en `archive/experiments/` y excluir de Git | Bajo para flujo actual; datos generados. |
| `finger_recordings_archive/` | Videos antiguos de dedo. | Archivar en `archive/experiments/` y excluir de Git | Bajo para flujo actual; datos pesados. |
| `glass_sessions/` | Sesiones de pizarra visual. | Archivar en `archive/experiments/` y excluir de Git | Bajo para flujo actual. |
| `archive/old_experiments/` | Pruebas anteriores ya archivadas. | Mover dentro de `archive/experiments/old_experiments/` | Bajo. |
| `ARCHIVED.txt`, `README_ARCHIVE.md`, `README_GLASS_BOARD.md`, `CLEANUP_REPORT.md` | Documentacion historica. | Archivar en `archive/experiments/` | Bajo. |

## Datos Pesados y Carpetas Que No Deben Ir a GitHub

| Ruta/Patron | Motivo | Decision |
| --- | --- | --- |
| `.env` | Contiene `OPENAI_API_KEY` real. | Ignorar, no subir. |
| `glass_recordings/` | Videos reales y snapshots. | Mantener local, ignorar. |
| `video_analysis/` | Frames extraidos y resultados generados. | Mantener local, ignorar. |
| `*.mp4`, `*.avi`, `*.mov`, `*.mkv`, `*.webm` | Videos pesados/privados. | Ignorar. |
| `*.task` | Modelos grandes. | Ignorar. |
| `__pycache__/`, `*.pyc` | Cache local de Python. | Ignorar/archivar. |

## Riesgos De Romper Flujo Actual

1. `glass_recorder.py` importa `analyze_video` desde `video_activity_analyzer.py`; ambos deben permanecer juntos en raiz.
2. `.env` debe permanecer local para que el analisis automatico use `OPENAI_API_KEY`.
3. `glass_recordings/` y `video_analysis/` no deben moverse porque son salidas actuales del flujo.
4. Archivar MediaPipe y Finger Lab no rompe el flujo actual porque `glass_recorder.py` no usa MediaPipe.
5. Simplificar `requirements.txt` no debe quitar `opencv-python`, `openai` ni `python-dotenv`.

## Decision General

Conservar en raiz solo la linea Glass actual y preparar el proyecto para GitHub/futura migracion a Streamlit.

No borrar permanentemente archivos en esta iteracion. Archivar experimentos en:

```text
archive/experiments/
```
