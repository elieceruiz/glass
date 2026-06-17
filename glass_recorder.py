"""glass_recorder.py - CLI de grabacion real para Glass.

Mantiene el flujo de consola con ventana OpenCV y controles S/P/ESC, pero la
grabacion, cierre de recursos y metadata viven en glass_core.recorder.
"""

from pathlib import Path
import sys
import time

try:
    import cv2  # noqa: F401 - valida dependencia para mensaje claro en CLI
except ModuleNotFoundError:
    print("Falta opencv-python. Ejecuta: python -m pip install opencv-python")
    sys.exit(1)

from glass_core.recorder import GlassRecorder


FRAME_WIDTH = 640
FRAME_HEIGHT = 480
TARGET_FPS = 15
AUTO_ANALYZE = True
ANALYSIS_EVERY_SECONDS = 120

BASE_DIR = Path(__file__).resolve().parent
RECORDINGS_DIR = BASE_DIR / "glass_recordings"
WINDOW_NAME = "glass_recorder"


def now_stamp():
    return time.strftime("%Y%m%d-%H%M%S")


def run_auto_analysis(recorder, video_path):
    if not AUTO_ANALYZE:
        recorder.update_analysis_metadata("skipped")
        return "skipped", "", ""

    try:
        from video_activity_analyzer import analyze_video

        print("=== Analisis automatico post-grabacion ===")
        print(f"Video: {video_path}")
        print(f"Intervalo: {ANALYSIS_EVERY_SECONDS} segundos")
        result = analyze_video(video_path, ANALYSIS_EVERY_SECONDS)
        analysis_path = result["analysis_path"]
        recorder.update_analysis_metadata("success", analysis_path, "")
        print(f"Analisis generado: {analysis_path}")
        return "success", analysis_path, ""
    except Exception as exc:
        message = f"{type(exc).__name__}: {exc}"
        error_path = recorder.session_dir / "analysis_error.txt"
        error_path.write_text(message + "\n", encoding="utf-8")
        recorder.update_analysis_metadata("error", "", message)
        print(f"ERROR analisis automatico: {message}")
        print(f"Error guardado en: {error_path}")
        return "error", "", message


def print_instructions():
    print("glass_recorder")
    print("Graba video real del vidrio. No usa IA, OCR, MediaPipe ni tracking.")
    print()
    print("Controles:")
    print("  S   guardar y salir")
    print("  P   snapshot manual")
    print("  ESC salir guardando")
    print()


def main():
    print_instructions()

    recorder = GlassRecorder(
        session_id=now_stamp(),
        output_root=RECORDINGS_DIR,
        fps=TARGET_FPS,
        resolution=(FRAME_WIDTH, FRAME_HEIGHT),
        auto_analyze=AUTO_ANALYZE,
        analysis_every_seconds=ANALYSIS_EVERY_SECONDS,
        show_window=True,
        window_name=WINDOW_NAME,
        enable_snapshots=True,
        overlay_controls_text="S = guardar y salir | P = snapshot | ESC = salir guardando",
        on_status=print,
    )

    try:
        recorder.start()
        print(f"Sesion: {recorder.session_dir}")
        print(f"Grabando: {recorder.temp_video_path}")
        print("inicio:")
        print(recorder.started_at)
        result = recorder.wait()
        run_auto_analysis(recorder, result.video_path)
        print(f"Metadata guardada: {result.metadata_path}")
        print("Grabacion cerrada.")
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}")


if __name__ == "__main__":
    main()
