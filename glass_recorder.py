"""glass_recorder.py - grabacion simple de vidrio en video real.

No usa MediaPipe, OpenAI, OCR ni tracking. Solo abre camara, aplica mirror,
graba video y permite snapshots manuales.
"""

from pathlib import Path
import json
import sys
import time

try:
    import cv2
except ModuleNotFoundError:
    print("Falta opencv-python. Ejecuta: python -m pip install opencv-python")
    sys.exit(1)


CAMERA_INDEXES = range(6)
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


def now_text():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def seconds_to_timestamp(seconds):
    """Convierte segundos flotantes a HH:MM:SS.mmm."""
    milliseconds_total = max(0, int(round(seconds * 1000)))
    hours = milliseconds_total // 3_600_000
    milliseconds_total %= 3_600_000
    minutes = milliseconds_total // 60_000
    milliseconds_total %= 60_000
    secs = milliseconds_total // 1000
    millis = milliseconds_total % 1000
    return f"{hours:02d}:{minutes:02d}:{secs:02d}.{millis:03d}"


def duration_for_filename(seconds):
    """Devuelve HH-MM-SS para nombres de archivo."""
    return seconds_to_timestamp(seconds).split(".")[0].replace(":", "-")


def open_camera():
    """Busca automaticamente una camara disponible entre indices 0..5."""
    for index in CAMERA_INDEXES:
        camera = cv2.VideoCapture(index, cv2.CAP_DSHOW)
        camera.set(cv2.CAP_PROP_FRAME_WIDTH, FRAME_WIDTH)
        camera.set(cv2.CAP_PROP_FRAME_HEIGHT, FRAME_HEIGHT)
        camera.set(cv2.CAP_PROP_FPS, TARGET_FPS)

        if not camera.isOpened():
            camera.release()
            print(f"Camara indice {index}: no abre.")
            continue

        ok, frame = camera.read()
        if not ok or frame is None:
            camera.release()
            print(f"Camara indice {index}: abre pero no entrega frames validos.")
            continue

        width = int(camera.get(cv2.CAP_PROP_FRAME_WIDTH)) or FRAME_WIDTH
        height = int(camera.get(cv2.CAP_PROP_FRAME_HEIGHT)) or FRAME_HEIGHT
        fps = camera.get(cv2.CAP_PROP_FPS) or TARGET_FPS

        print(f"Camara usada: indice {index}")
        print(f"Resolucion real reportada: {width}x{height}")
        print(f"FPS real reportado: {fps:.2f}")
        return camera, index, fps

    print("No se encontro camara disponible.")
    print("Cierra DroidCam, Zoom, navegador u otra app que use camara, y vuelve a intentar.")
    return None, None, None


def create_session():
    stamp = now_stamp()
    session_dir = RECORDINGS_DIR / stamp
    snapshots_dir = session_dir / "snapshots"
    snapshots_dir.mkdir(parents=True, exist_ok=True)
    return session_dir, snapshots_dir, stamp


def create_writer(session_dir):
    """Crea VideoWriter MP4 y usa AVI MJPG como fallback si falla."""
    mp4_path = session_dir / "recording_temp.mp4"
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(mp4_path), fourcc, TARGET_FPS, (FRAME_WIDTH, FRAME_HEIGHT))
    if writer.isOpened():
        return writer, mp4_path, "mp4v"

    writer.release()
    avi_path = session_dir / "recording_temp.avi"
    fourcc = cv2.VideoWriter_fourcc(*"MJPG")
    writer = cv2.VideoWriter(str(avi_path), fourcc, TARGET_FPS, (FRAME_WIDTH, FRAME_HEIGHT))
    if writer.isOpened():
        print("MP4 fallo. Usando fallback AVI MJPG.")
        return writer, avi_path, "MJPG"

    writer.release()
    print("ERROR: no pude iniciar grabacion MP4 ni AVI.")
    return None, None, ""


def final_video_path(session_dir, session_stamp, duration_seconds, suffix):
    duration_text = duration_for_filename(duration_seconds)
    return session_dir / f"recording_{session_stamp}_duracion-{duration_text}{suffix}"


def rename_video(temp_path, session_dir, session_stamp, duration_seconds):
    final_path = final_video_path(session_dir, session_stamp, duration_seconds, temp_path.suffix)
    if final_path.exists():
        final_path.unlink()
    temp_path.rename(final_path)
    return final_path


def read_frame(camera):
    ok, frame = camera.read()
    if not ok or frame is None:
        return None
    frame = cv2.resize(frame, (FRAME_WIDTH, FRAME_HEIGHT), interpolation=cv2.INTER_AREA)
    return cv2.flip(frame, 1)


def draw_overlay(frame, timestamp, system_time):
    cv2.rectangle(frame, (0, 0), (FRAME_WIDTH, 108), (0, 0, 0), -1)
    cv2.putText(frame, "GLASS RECORDER", (18, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2, cv2.LINE_AA)
    cv2.putText(frame, "REC", (18, 64), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2, cv2.LINE_AA)
    cv2.circle(frame, (78, 56), 8, (0, 0, 255), -1)
    cv2.putText(frame, f"grabacion: {timestamp} | sistema: {system_time}", (110, 64), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 2, cv2.LINE_AA)
    cv2.putText(frame, "S = guardar y salir | P = snapshot | ESC = salir guardando", (18, 92), cv2.FONT_HERSHEY_SIMPLEX, 0.48, (255, 255, 255), 1, cv2.LINE_AA)


def save_metadata(
    session_dir,
    start_text,
    end_text,
    duration_seconds,
    camera_index,
    fps_real,
    snapshot_count,
    video_path,
    codec,
    analysis_status,
    analysis_output_dir="",
    analysis_error="",
):
    metadata = {
        "fecha_inicio": start_text,
        "fecha_fin": end_text,
        "duracion_segundos": round(duration_seconds, 3),
        "duracion_hhmmss": seconds_to_timestamp(duration_seconds),
        "camara_usada": camera_index,
        "resolucion": [FRAME_WIDTH, FRAME_HEIGHT],
        "fps": TARGET_FPS,
        "fps_real": fps_real,
        "snapshots_manual_count": snapshot_count,
        "modo": "glass_recorder",
        "video": str(video_path) if video_path else "",
        "codec": codec,
        "auto_analysis_enabled": AUTO_ANALYZE,
        "analysis_every_seconds": ANALYSIS_EVERY_SECONDS,
        "analysis_status": analysis_status,
        "analysis_output_dir": analysis_output_dir,
        "analysis_error": analysis_error,
    }
    path = session_dir / "metadata.json"
    path.write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Metadata guardada: {path}")


def run_auto_analysis(session_dir, video_path):
    if not AUTO_ANALYZE:
        return "skipped", "", ""

    try:
        from video_activity_analyzer import analyze_video

        print("=== Analisis automatico post-grabacion ===")
        print(f"Video: {video_path}")
        print(f"Intervalo: {ANALYSIS_EVERY_SECONDS} segundos")
        result = analyze_video(video_path, ANALYSIS_EVERY_SECONDS)
        print(f"Analisis generado: {result['analysis_path']}")
        return "success", result["analysis_path"], ""
    except Exception as exc:
        message = f"{type(exc).__name__}: {exc}"
        error_path = session_dir / "analysis_error.txt"
        error_path.write_text(message + "\n", encoding="utf-8")
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

    camera, camera_index, fps_real = open_camera()
    if camera is None:
        return
    fps_real = fps_real if fps_real and fps_real > 0 else TARGET_FPS

    session_dir, snapshots_dir, session_stamp = create_session()
    writer, video_path, codec = create_writer(session_dir)
    if writer is None:
        camera.release()
        return

    start_text = now_text()
    start_time = time.time()
    frame_index = 0
    duration_seconds = 0.0
    snapshot_count = 0
    analysis_status = "skipped"
    analysis_output_dir = ""
    analysis_error = ""

    print(f"Sesion: {session_dir}")
    print(f"Grabando: {video_path}")
    print("inicio:")
    print(start_text)

    try:
        while True:
            loop_start = time.time()
            frame = read_frame(camera)
            if frame is None:
                print("No pude leer frame de camara. Cerrando.")
                break

            timestamp_seconds = frame_index / fps_real
            timestamp = seconds_to_timestamp(timestamp_seconds)
            system_time = now_text()
            display = frame.copy()
            draw_overlay(display, timestamp, system_time)
            writer.write(display)
            frame_index += 1
            duration_seconds = frame_index / fps_real
            cv2.imshow(WINDOW_NAME, display)

            key = cv2.waitKey(1) & 0xFF
            if key in (ord("p"), ord("P")):
                snapshot_count += 1
                snapshot_path = snapshots_dir / f"manual_{snapshot_count:03d}.png"
                cv2.imwrite(str(snapshot_path), display)
                print(f"Snapshot manual guardado: {snapshot_path}")
            if key in (ord("s"), ord("S")):
                print("Guardando y saliendo con S.")
                break
            if key == 27:
                print("Saliendo con ESC, guardando grabacion.")
                break

            elapsed_loop = time.time() - loop_start
            delay = max(0, (1 / TARGET_FPS) - elapsed_loop)
            if delay > 0:
                time.sleep(delay)

    finally:
        writer.release()
        camera.release()
        cv2.destroyAllWindows()
        final_path = rename_video(video_path, session_dir, session_stamp, duration_seconds)
        end_text = now_text()
        analysis_status, analysis_output_dir, analysis_error = run_auto_analysis(session_dir, final_path)
        save_metadata(
            session_dir,
            start_text,
            end_text,
            duration_seconds,
            camera_index,
            fps_real,
            snapshot_count,
            final_path,
            codec,
            analysis_status,
            analysis_output_dir,
            analysis_error,
        )
        print("Grabacion cerrada.")


if __name__ == "__main__":
    main()
