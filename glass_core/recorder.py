"""Nucleo de grabacion real para Glass.

Este modulo no conoce Streamlit ni OpenAI. Solo se encarga de abrir camara,
grabar video, cerrar recursos y escribir metadata de la sesion.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
import threading
import time
from typing import Callable

import cv2


BASE_DIR = Path(__file__).resolve().parents[1]
CAMERA_INDEXES = range(6)


@dataclass
class RecordingResult:
    session_id: str
    session_dir: Path
    video_path: Path
    metadata_path: Path
    duration_seconds: float
    duration_hhmmss: str
    codec: str
    started_at: str
    ended_at: str


def now_stamp() -> str:
    return time.strftime("%Y%m%d-%H%M%S")


def now_text() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def seconds_to_timestamp(seconds: float) -> str:
    milliseconds_total = max(0, int(round(seconds * 1000)))
    hours = milliseconds_total // 3_600_000
    milliseconds_total %= 3_600_000
    minutes = milliseconds_total // 60_000
    milliseconds_total %= 60_000
    secs = milliseconds_total // 1000
    millis = milliseconds_total % 1000
    return f"{hours:02d}:{minutes:02d}:{secs:02d}.{millis:03d}"


def duration_for_filename(seconds: float) -> str:
    return seconds_to_timestamp(seconds).split(".")[0].replace(":", "-")


def resolve_output_root(output_root: Path | str) -> Path:
    path = Path(output_root)
    if not path.is_absolute():
        path = BASE_DIR / path
    return path


class GlassRecorder:
    def __init__(
        self,
        session_id: str,
        output_root: Path | str = "glass_recordings",
        fps: int = 15,
        resolution: tuple[int, int] = (640, 480),
        auto_analyze: bool = False,
        analysis_every_seconds: int = 30,
        show_window: bool = False,
        window_name: str = "glass_recorder",
        enable_snapshots: bool = False,
        overlay_controls_text: str = "",
        on_status: Callable[[str], None] | None = None,
    ):
        self.session_id = session_id
        self.output_root = resolve_output_root(output_root)
        self.fps = fps
        self.resolution = resolution
        self.auto_analyze = auto_analyze
        self.analysis_every_seconds = analysis_every_seconds
        self.show_window = show_window
        self.window_name = window_name
        self.enable_snapshots = enable_snapshots
        self.overlay_controls_text = overlay_controls_text
        self.on_status = on_status or (lambda message: None)

        self.session_dir = self.output_root / self.session_id
        self.snapshots_dir = self.session_dir / "snapshots"
        self.metadata_path = self.session_dir / "metadata.json"
        self.preview_path = self.session_dir / "preview.jpg"
        self.preview_temp_path = self.session_dir / "preview_tmp.jpg"

        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None
        self.result: RecordingResult | None = None
        self.error: str = ""

        self.camera = None
        self.writer = None
        self.temp_video_path: Path | None = None
        self.codec = ""
        self.camera_index: int | None = None
        self.fps_real = float(fps)
        self.started_at = ""
        self.ended_at = ""
        self.frame_index = 0
        self.snapshot_count = 0
        self.last_preview_time = 0.0

    @property
    def is_running(self) -> bool:
        return bool(self.thread and self.thread.is_alive())

    def start(self) -> None:
        if self.is_running:
            return

        self.session_dir.mkdir(parents=True, exist_ok=True)
        if self.enable_snapshots:
            self.snapshots_dir.mkdir(parents=True, exist_ok=True)

        self.camera, self.camera_index, self.fps_real = self.open_camera()
        self.writer, self.temp_video_path, self.codec = self.create_writer()
        if self.writer is None or self.temp_video_path is None:
            if self.camera is not None:
                self.camera.release()
            raise RuntimeError("No pude iniciar grabacion MP4 ni AVI.")

        self.started_at = now_text()
        self.stop_event.clear()
        self.thread = threading.Thread(target=self._record_loop, name=f"glass-recorder-{self.session_id}", daemon=True)
        self.thread.start()

    def stop(self) -> RecordingResult:
        self.stop_event.set()
        if self.thread is not None and self.thread.is_alive():
            self.thread.join()
        if self.error:
            raise RuntimeError(self.error)
        if self.result is None:
            raise RuntimeError("La grabacion no produjo resultado.")
        return self.result

    def wait(self) -> RecordingResult:
        if self.thread is not None:
            self.thread.join()
        if self.error:
            raise RuntimeError(self.error)
        if self.result is None:
            raise RuntimeError("La grabacion no produjo resultado.")
        return self.result

    def open_camera(self):
        width, height = self.resolution
        for index in CAMERA_INDEXES:
            camera = cv2.VideoCapture(index, cv2.CAP_DSHOW)
            camera.set(cv2.CAP_PROP_FRAME_WIDTH, width)
            camera.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
            camera.set(cv2.CAP_PROP_FPS, self.fps)

            if not camera.isOpened():
                camera.release()
                self.on_status(f"Camara indice {index}: no abre.")
                continue

            ok, frame = camera.read()
            if not ok or frame is None:
                camera.release()
                self.on_status(f"Camara indice {index}: abre pero no entrega frames validos.")
                continue

            real_width = int(camera.get(cv2.CAP_PROP_FRAME_WIDTH)) or width
            real_height = int(camera.get(cv2.CAP_PROP_FRAME_HEIGHT)) or height
            fps_real = float(camera.get(cv2.CAP_PROP_FPS) or self.fps)
            self.on_status(f"Camara usada: indice {index}")
            self.on_status(f"Resolucion real reportada: {real_width}x{real_height}")
            self.on_status(f"FPS real reportado: {fps_real:.2f}")
            return camera, index, fps_real

        raise RuntimeError(
            "No se encontro camara disponible. Cierra DroidCam, Zoom, navegador u otra app que use camara."
        )

    def create_writer(self):
        width, height = self.resolution
        mp4_path = self.session_dir / "recording_temp.mp4"
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        writer = cv2.VideoWriter(str(mp4_path), fourcc, self.fps, (width, height))
        if writer.isOpened():
            return writer, mp4_path, "mp4v"

        writer.release()
        avi_path = self.session_dir / "recording_temp.avi"
        fourcc = cv2.VideoWriter_fourcc(*"MJPG")
        writer = cv2.VideoWriter(str(avi_path), fourcc, self.fps, (width, height))
        if writer.isOpened():
            self.on_status("MP4 fallo. Usando fallback AVI MJPG.")
            return writer, avi_path, "MJPG"

        writer.release()
        return None, None, ""

    def read_frame(self):
        ok, frame = self.camera.read()
        if not ok or frame is None:
            return None
        width, height = self.resolution
        frame = cv2.resize(frame, (width, height), interpolation=cv2.INTER_AREA)
        return cv2.flip(frame, 1)

    def draw_overlay(self, frame, timestamp: str, system_time: str) -> None:
        width, _ = self.resolution
        cv2.rectangle(frame, (0, 0), (width, 108), (0, 0, 0), -1)
        cv2.putText(frame, "GLASS RECORDER", (18, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2, cv2.LINE_AA)
        cv2.putText(frame, "REC", (18, 64), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2, cv2.LINE_AA)
        cv2.circle(frame, (78, 56), 8, (0, 0, 255), -1)
        cv2.putText(frame, f"grabacion: {timestamp} | sistema: {system_time}", (110, 64), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 2, cv2.LINE_AA)
        if self.overlay_controls_text:
            cv2.putText(frame, self.overlay_controls_text, (18, 92), cv2.FONT_HERSHEY_SIMPLEX, 0.48, (255, 255, 255), 1, cv2.LINE_AA)

    def _record_loop(self) -> None:
        try:
            while not self.stop_event.is_set():
                loop_start = time.time()
                frame = self.read_frame()
                if frame is None:
                    self.on_status("No pude leer frame de camara. Cerrando.")
                    break

                timestamp_seconds = self.frame_index / max(self.fps_real, 1)
                timestamp = seconds_to_timestamp(timestamp_seconds)
                display = frame.copy()
                self.draw_overlay(display, timestamp, now_text())
                self.writer.write(display)
                self.update_preview(display)
                self.frame_index += 1

                if self.show_window:
                    cv2.imshow(self.window_name, display)
                    key = cv2.waitKey(1) & 0xFF
                    if key in (ord("p"), ord("P")) and self.enable_snapshots:
                        self.save_snapshot(display)
                    if key in (ord("s"), ord("S")):
                        self.on_status("Guardando y saliendo con S.")
                        self.stop_event.set()
                    if key == 27:
                        self.on_status("Saliendo con ESC, guardando grabacion.")
                        self.stop_event.set()

                delay = max(0, (1 / self.fps) - (time.time() - loop_start))
                if delay > 0:
                    time.sleep(delay)
        except Exception as exc:
            self.error = f"{type(exc).__name__}: {exc}"
        finally:
            self.result = self._finalize()

    def save_snapshot(self, frame) -> None:
        self.snapshot_count += 1
        self.snapshots_dir.mkdir(parents=True, exist_ok=True)
        snapshot_path = self.snapshots_dir / f"manual_{self.snapshot_count:03d}.png"
        cv2.imwrite(str(snapshot_path), frame)
        self.on_status(f"Snapshot manual guardado: {snapshot_path}")

    def update_preview(self, frame) -> None:
        now = time.time()
        if now - self.last_preview_time < 1:
            return
        self.last_preview_time = now
        if cv2.imwrite(str(self.preview_temp_path), frame, [cv2.IMWRITE_JPEG_QUALITY, 82]):
            self.preview_temp_path.replace(self.preview_path)

    def _finalize(self) -> RecordingResult:
        if self.writer is not None:
            self.writer.release()
        if self.camera is not None:
            self.camera.release()
        if self.show_window:
            cv2.destroyAllWindows()

        duration_seconds = self.frame_index / max(self.fps_real, 1)
        final_path = self.rename_video(duration_seconds)
        self.ended_at = now_text()
        result = RecordingResult(
            session_id=self.session_id,
            session_dir=self.session_dir,
            video_path=final_path,
            metadata_path=self.metadata_path,
            duration_seconds=duration_seconds,
            duration_hhmmss=seconds_to_timestamp(duration_seconds),
            codec=self.codec,
            started_at=self.started_at,
            ended_at=self.ended_at,
        )
        self.save_metadata(result, analysis_status="skipped")
        return result

    def rename_video(self, duration_seconds: float) -> Path:
        if self.temp_video_path is None:
            raise RuntimeError("No existe video temporal para cerrar.")
        final_path = self.session_dir / (
            f"recording_{self.session_id}_duracion-{duration_for_filename(duration_seconds)}"
            f"{self.temp_video_path.suffix}"
        )
        if final_path.exists():
            final_path.unlink()
        self.temp_video_path.rename(final_path)
        return final_path

    def save_metadata(
        self,
        result: RecordingResult,
        analysis_status: str,
        analysis_output_dir: str = "",
        analysis_error: str = "",
    ) -> None:
        metadata = {
            "session_id": self.session_id,
            "fecha_inicio": result.started_at,
            "fecha_fin": result.ended_at,
            "duracion_segundos": round(result.duration_seconds, 3),
            "duracion_hhmmss": result.duration_hhmmss,
            "camara_usada": self.camera_index,
            "resolucion": list(self.resolution),
            "fps": self.fps,
            "fps_real": self.fps_real,
            "snapshots_manual_count": self.snapshot_count,
            "modo": "glass_recorder",
            "video": str(result.video_path),
            "codec": result.codec,
            "auto_analysis_enabled": self.auto_analyze,
            "analysis_every_seconds": self.analysis_every_seconds,
            "analysis_status": analysis_status,
            "analysis_output_dir": analysis_output_dir,
            "analysis_error": analysis_error,
            "detail_seconds": self.analysis_every_seconds,
        }
        self.metadata_path.write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")

    def update_analysis_metadata(
        self,
        analysis_status: str,
        analysis_output_dir: str = "",
        analysis_error: str = "",
    ) -> None:
        if self.result is None:
            raise RuntimeError("No hay resultado de grabacion para actualizar metadata.")
        self.save_metadata(self.result, analysis_status, analysis_output_dir, analysis_error)
