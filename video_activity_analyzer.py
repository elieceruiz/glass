"""video_activity_analyzer.py - bitacora precisa de actividad en video.

No envia el video completo ni audio. Extrae frames espaciados usando FPS e
indice real de frame, guarda imagenes locales y envia solo esos frames a
OpenAI Vision en lotes pequeños.
"""

from pathlib import Path
import argparse
import base64
import json
import os
import re
import sys
import time

import cv2
from dotenv import load_dotenv
from openai import OpenAI, OpenAIError


BASE_DIR = Path(__file__).resolve().parent
ANALYSIS_DIR = BASE_DIR / "video_analysis"
DEFAULT_MODEL = "gpt-4.1-mini"
DEFAULT_EVERY_SECONDS = 120
BATCH_SIZE = 6
JPEG_QUALITY = 90


def now_stamp():
    return time.strftime("%Y%m%d-%H%M%S")


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


def timestamp_for_filename(timestamp):
    return timestamp.replace(":", "-").replace(".", "-")


def encode_image(path):
    return "data:image/jpeg;base64," + base64.b64encode(path.read_bytes()).decode("ascii")


def strip_markdown_fences(text):
    lines = (text or "").strip().splitlines()
    if lines and re.match(r"^```(?:json|JSON)?\s*$", lines[0].strip()):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


def parse_json_response(raw_text, fallback):
    raw = raw_text or ""
    attempts = [raw.strip(), strip_markdown_fences(raw)]
    first = raw.find("{")
    last = raw.rfind("}")
    if first != -1 and last != -1 and last > first:
        attempts.append(raw[first:last + 1])

    for candidate in attempts:
        if not candidate:
            continue
        try:
            data = json.loads(candidate)
            return data if isinstance(data, dict) else fallback
        except json.JSONDecodeError:
            pass

    fallback["raw_response"] = raw
    fallback["error"] = "json_parse_failed"
    return fallback


def create_analysis_dirs():
    analysis_path = ANALYSIS_DIR / now_stamp()
    frames_path = analysis_path / "frames"
    frames_path.mkdir(parents=True, exist_ok=True)
    return analysis_path, frames_path


def open_video(video_path):
    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        raise ValueError(f"No pude abrir el video: {video_path}")
    return capture


def read_video_info(capture):
    fps = float(capture.get(cv2.CAP_PROP_FPS) or 0)
    frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    if fps <= 0:
        raise ValueError("El video no reporta FPS valido.")
    duration = frame_count / fps if frame_count else 0.0
    return fps, frame_count, duration


def extract_frames(video_path, every_seconds):
    analysis_path, frames_path = create_analysis_dirs()
    capture = open_video(video_path)
    fps, frame_count, duration = read_video_info(capture)
    step_frames = max(1, int(round(every_seconds * fps)))

    frames = []
    target_frame = 0
    index = 1

    print("=== Extraccion de frames ===")
    print(f"Video: {video_path}")
    print(f"FPS real: {fps:.6f}")
    print(f"Frames totales: {frame_count}")
    print(f"Duracion total: {seconds_to_timestamp(duration)}")
    print(f"Intervalo solicitado: cada {every_seconds} segundos")
    print(f"Paso aproximado: {step_frames} frames")

    while target_frame < frame_count:
        capture.set(cv2.CAP_PROP_POS_FRAMES, target_frame)
        ok, frame = capture.read()
        if not ok or frame is None:
            break

        actual_frame = int(capture.get(cv2.CAP_PROP_POS_FRAMES)) - 1
        if actual_frame < 0:
            actual_frame = target_frame

        timestamp_seconds = actual_frame / fps
        timestamp = seconds_to_timestamp(timestamp_seconds)
        frame_path = frames_path / f"frame_{timestamp_for_filename(timestamp)}.jpg"
        cv2.imwrite(str(frame_path), frame, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])

        frames.append({
            "index": index,
            "frame_index": actual_frame,
            "timestamp_seconds": timestamp_seconds,
            "timestamp": timestamp,
            "path": frame_path,
        })
        print(f"Frame {index}: frame_index={actual_frame} timestamp={timestamp} -> {frame_path.name}")

        index += 1
        target_frame += step_frames

    capture.release()
    return analysis_path, frames, fps, frame_count, duration


def frame_batches(frames, batch_size):
    for start in range(0, len(frames), batch_size):
        yield frames[start:start + batch_size]


def analyze_batch(client, batch, model):
    prompt = (
        "Analiza estos frames extraidos de un video largo para crear una bitacora general de habitos, rutinas, actividades y eventos. "
        "No hay audio ni video completo, solo imagenes individuales. "
        "Para cada timestamp clasifica libremente lo que observas con una estructura estable. "
        "No te limites a baño o ducha. Debe servir para ordenar una pieza, estudiar, trabajar, cocinar, descansar, limpiar, ejercicio o cualquier rutina. "
        "categoria_general debe ser abierta y flexible; ejemplos no obligatorios: higiene, estudio, trabajo, orden, descanso, desplazamiento, escritura, creatividad, limpieza, cocina, ejercicio, tiempo_muerto, ausencia, otro. "
        "actividad_detectada debe ser especifica. No digas solo 'persona visible' si puedes inferir una actividad. "
        "Si no hay evidencia suficiente, usa categoria_general 'incierto' o 'ausencia'. "
        "Mantén timestamps exactos HH:MM:SS.mmm. "
        "Devuelve SOLO JSON valido con esta forma exacta: "
        "{\"items\":[{\"timestamp\":\"00:00:00.000\",\"frame_index\":0,"
        "\"categoria_general\":\"...\",\"actividad_detectada\":\"...\",\"confianza\":80,"
        "\"observaciones\":\"...\",\"evidencia_visual\":\"...\",\"utilidad_habito\":\"...\"}]}"
    )

    content = [{"type": "input_text", "text": prompt}]
    for item in batch:
        content.append({
            "type": "input_text",
            "text": (
                f"timestamp exacto: {item['timestamp']} | "
                f"frame_index: {item['frame_index']} | archivo: {item['path'].name}"
            ),
        })
        content.append({"type": "input_image", "image_url": encode_image(item["path"])})

    fallback = {
        "items": [
            {
                "timestamp": item["timestamp"],
                "frame_index": item["frame_index"],
                "categoria_general": "incierto",
                "actividad_detectada": "error de analisis",
                "confianza": 0,
                "observaciones": "",
                "evidencia_visual": "",
                "utilidad_habito": "",
            }
            for item in batch
        ]
    }

    try:
        response = client.responses.create(
            model=model,
            input=[{"role": "user", "content": content}],
        )
        data = parse_json_response(response.output_text, fallback)
    except OpenAIError as exc:
        data = fallback
        for item in data["items"]:
            item["observaciones"] = f"OpenAIError: {exc}"
    except Exception as exc:
        data = fallback
        for item in data["items"]:
            item["observaciones"] = f"{type(exc).__name__}: {exc}"

    return data.get("items", [])


def normalize_activity(text):
    return re.sub(r"\s+", " ", str(text).strip().lower())


def segment_key(item):
    return (
        normalize_activity(item.get("categoria_general", "")),
        normalize_activity(item.get("actividad_detectada", "")),
    )


def item_for_frame(raw_items, frame):
    for item in raw_items:
        if int(item.get("frame_index", -1) or -1) == frame["frame_index"]:
            return item
    for item in raw_items:
        if str(item.get("timestamp", "")) == frame["timestamp"]:
            return item
    return {
        "timestamp": frame["timestamp"],
        "frame_index": frame["frame_index"],
        "categoria_general": "incierto",
        "actividad_detectada": "sin clasificar",
        "confianza": 0,
        "observaciones": "",
        "evidencia_visual": "",
        "utilidad_habito": "",
    }


def build_frame_classifications(frames, raw_items):
    classifications = []
    for frame in frames:
        item = item_for_frame(raw_items, frame)
        classifications.append({
            "timestamp": frame["timestamp"],
            "timestamp_seconds": frame["timestamp_seconds"],
            "frame_index": frame["frame_index"],
            "categoria_general": str(item.get("categoria_general", "incierto")),
            "actividad_detectada": str(item.get("actividad_detectada", item.get("actividad", "sin clasificar"))),
            "confianza": int(item.get("confianza", 0) or 0),
            "observaciones": str(item.get("observaciones", "")),
            "evidencia_visual": str(item.get("evidencia_visual", "")),
            "utilidad_habito": str(item.get("utilidad_habito", "")),
        })
    return classifications


def merge_similar_segments(classifications, duration):
    if not classifications:
        return []

    timeline = []
    current = {
        "inicio": classifications[0]["timestamp"],
        "inicio_seconds": classifications[0]["timestamp_seconds"],
        "fin": "",
        "categoria_general": classifications[0]["categoria_general"],
        "actividad_detectada": classifications[0]["actividad_detectada"],
        "confianzas": [classifications[0]["confianza"]],
        "observaciones": [classifications[0]["observaciones"]],
        "evidencia_visual": [classifications[0]["evidencia_visual"]],
        "utilidad_habito": [classifications[0]["utilidad_habito"]],
    }
    current_key = segment_key(classifications[0])

    for item in classifications[1:]:
        key = segment_key(item)
        if key == current_key:
            current["confianzas"].append(item["confianza"])
            if item["observaciones"]:
                current["observaciones"].append(item["observaciones"])
            if item["evidencia_visual"]:
                current["evidencia_visual"].append(item["evidencia_visual"])
            if item["utilidad_habito"]:
                current["utilidad_habito"].append(item["utilidad_habito"])
        else:
            current["fin"] = item["timestamp"]
            timeline.append(finalize_segment(current))
            current = {
                "inicio": item["timestamp"],
                "inicio_seconds": item["timestamp_seconds"],
                "fin": "",
                "categoria_general": item["categoria_general"],
                "actividad_detectada": item["actividad_detectada"],
                "confianzas": [item["confianza"]],
                "observaciones": [item["observaciones"]],
                "evidencia_visual": [item["evidencia_visual"]],
                "utilidad_habito": [item["utilidad_habito"]],
            }
            current_key = key

    current["fin"] = seconds_to_timestamp(duration)
    timeline.append(finalize_segment(current))
    return timeline


def finalize_segment(segment):
    confidences = segment.pop("confianzas")
    observations = [item for item in segment.pop("observaciones") if item]
    evidence = [item for item in segment.pop("evidencia_visual") if item]
    utility = [item for item in segment.pop("utilidad_habito") if item]
    segment.pop("inicio_seconds", None)
    segment["confianza"] = int(round(sum(confidences) / max(1, len(confidences))))
    segment["observaciones"] = " | ".join(dict.fromkeys(observations))
    segment["evidencia_visual"] = " | ".join(dict.fromkeys(evidence))
    segment["utilidad_habito"] = " | ".join(dict.fromkeys(utility))
    return segment


def timestamp_to_seconds(timestamp):
    match = re.match(r"^(\d{2}):(\d{2}):(\d{2})\.(\d{3})$", str(timestamp))
    if not match:
        return 0.0
    hours, minutes, seconds, millis = [int(part) for part in match.groups()]
    return hours * 3600 + minutes * 60 + seconds + millis / 1000


def category_stats(timeline, duration):
    totals = {}
    for item in timeline:
        category = str(item.get("categoria_general", "incierto")).strip() or "incierto"
        start = timestamp_to_seconds(item.get("inicio", "00:00:00.000"))
        end = timestamp_to_seconds(item.get("fin", "00:00:00.000"))
        totals[category] = totals.get(category, 0.0) + max(0.0, end - start)

    time_by_category = {
        category: seconds_to_timestamp(seconds)
        for category, seconds in sorted(totals.items())
    }
    percent_by_category = {
        category: round((seconds / duration) * 100, 2) if duration > 0 else 0
        for category, seconds in sorted(totals.items())
    }
    return time_by_category, percent_by_category


def summarize_timeline(client, timeline, duration, model):
    time_by_category, percent_by_category = category_stats(timeline, duration)
    prompt = (
        "Resume este timeline general de habitos, rutinas, actividades y eventos. "
        "No lo limites a ducha ni a presencia de personas. "
        "Devuelve SOLO JSON valido con claves exactas: duracion_total, tiempo_por_categoria, "
        "porcentaje_por_categoria, eventos_principales, tiempos_muertos, oportunidades_reduccion_tiempo, "
        "patrones_observados, momentos_relevantes_detectados, recomendaciones. "
        "Usa timestamps HH:MM:SS.mmm cuando menciones momentos."
    )
    fallback = {
        "duracion_total": seconds_to_timestamp(duration),
        "tiempo_por_categoria": time_by_category,
        "porcentaje_por_categoria": percent_by_category,
        "eventos_principales": [],
        "tiempos_muertos": [],
        "oportunidades_reduccion_tiempo": [],
        "patrones_observados": [],
        "momentos_relevantes_detectados": [],
        "recomendaciones": [],
    }
    try:
        response = client.responses.create(
            model=model,
            input=[
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": prompt},
                        {
                            "type": "input_text",
                            "text": json.dumps(
                                {
                                    "duracion_total": seconds_to_timestamp(duration),
                                    "tiempo_por_categoria_calculado": time_by_category,
                                    "porcentaje_por_categoria_calculado": percent_by_category,
                                    "timeline": timeline,
                                },
                                ensure_ascii=False,
                            ),
                        },
                    ],
                }
            ],
        )
        summary = parse_json_response(response.output_text, fallback)
        summary["tiempo_por_categoria"] = summary.get("tiempo_por_categoria") or time_by_category
        summary["porcentaje_por_categoria"] = summary.get("porcentaje_por_categoria") or percent_by_category
        return summary
    except Exception as exc:
        fallback["eventos_principales"] = [f"No se pudo generar resumen automatico: {type(exc).__name__}: {exc}"]
        return fallback


def write_outputs(analysis_path, timeline, summary, duration, source_video, fps, frame_count):
    timeline_json = analysis_path / "timeline.json"
    timeline_txt = analysis_path / "timeline.txt"
    summary_json = analysis_path / "summary.json"
    summary_txt = analysis_path / "summary.txt"

    timeline_json.write_text(json.dumps(timeline, indent=2, ensure_ascii=False), encoding="utf-8")
    summary_json.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

    lines = []
    for item in timeline:
        lines.append(
            f"{item['inicio']} - {item['fin']} | {item['categoria_general']} | "
            f"{item['actividad_detectada']} | confianza {item['confianza']} | "
            f"{item['observaciones']} | evidencia: {item['evidencia_visual']} | utilidad: {item['utilidad_habito']}"
        )
    timeline_txt.write_text("\n".join(lines) + "\n", encoding="utf-8")

    summary_lines = [
        f"video: {source_video}",
        f"duracion total: {seconds_to_timestamp(duration)}",
        f"fps real: {fps:.6f}",
        f"frames totales: {frame_count}",
        "",
        "tiempo por categoria_general:",
    ]
    for category, value in summary.get("tiempo_por_categoria", {}).items():
        summary_lines.append(f"- {category}: {value}")

    summary_lines.append("")
    summary_lines.append("porcentaje por categoria_general:")
    for category, value in summary.get("porcentaje_por_categoria", {}).items():
        summary_lines.append(f"- {category}: {value}%")

    summary_lines.extend([
        "",
        "eventos principales:",
    ])
    for item in summary.get("eventos_principales", []):
        summary_lines.append(f"- {item}")

    summary_lines.append("")
    summary_lines.append("tiempos muertos o ausencia de actividad visible:")
    for item in summary.get("tiempos_muertos", []):
        summary_lines.append(f"- {item}")

    summary_lines.append("")
    summary_lines.append("oportunidades para reducir tiempo:")
    for item in summary.get("oportunidades_reduccion_tiempo", []):
        summary_lines.append(f"- {item}")

    summary_lines.append("")
    summary_lines.append("patrones observados:")
    for item in summary.get("patrones_observados", []):
        summary_lines.append(f"- {item}")

    summary_lines.append("")
    summary_lines.append("momentos relevantes detectados:")
    for item in summary.get("momentos_relevantes_detectados", []):
        summary_lines.append(f"- {item}")

    summary_lines.append("")
    summary_lines.append("recomendaciones practicas:")
    for item in summary.get("recomendaciones", []):
        summary_lines.append(f"- {item}")

    summary_txt.write_text("\n".join(summary_lines) + "\n", encoding="utf-8")
    return timeline_json, timeline_txt, summary_json, summary_txt


def analyze_video(video_path, every_seconds=DEFAULT_EVERY_SECONDS, model=DEFAULT_MODEL):
    """Analiza un video y devuelve rutas de salida para uso CLI o automatico."""
    load_dotenv(BASE_DIR / ".env")
    if not os.getenv("OPENAI_API_KEY"):
        raise ValueError("Falta OPENAI_API_KEY en .env. No se imprimira ninguna clave.")

    video_path = Path(video_path).resolve()
    if not video_path.exists():
        raise ValueError(f"No existe el video: {video_path}")
    if every_seconds <= 0:
        raise ValueError("--every debe ser mayor que 0")

    analysis_path, frames, fps, frame_count, duration = extract_frames(video_path, every_seconds)
    if not frames:
        raise ValueError("No se extrajeron frames.")

    client = OpenAI()
    raw_items = []

    print("\n=== Analisis OpenAI Vision por lotes ===")
    for batch_index, batch in enumerate(frame_batches(frames, BATCH_SIZE), start=1):
        print(f"Lote {batch_index}: {len(batch)} frame(s)")
        raw_items.extend(analyze_batch(client, batch, model))

    classifications = build_frame_classifications(frames, raw_items)
    timeline = merge_similar_segments(classifications, duration)
    summary = summarize_timeline(client, timeline, duration, model)
    timeline_json, timeline_txt, summary_json, summary_txt = write_outputs(
        analysis_path, timeline, summary, duration, video_path, fps, frame_count
    )

    return {
        "analysis_path": str(analysis_path),
        "frames_path": str(analysis_path / "frames"),
        "timeline_json": str(timeline_json),
        "timeline_txt": str(timeline_txt),
        "summary_json": str(summary_json),
        "summary_txt": str(summary_txt),
    }


def main():
    parser = argparse.ArgumentParser(description="Analiza actividad de un video usando frames espaciados.")
    parser.add_argument("video", help="Ruta al video .mp4/.avi")
    parser.add_argument("--every", type=float, default=DEFAULT_EVERY_SECONDS, help="Intervalo en segundos entre frames")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Modelo OpenAI a usar")
    args = parser.parse_args()

    try:
        result = analyze_video(args.video, args.every, args.model)
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}")
        return 1

    print("\n=== Salida ===")
    print(f"Analisis: {result['analysis_path']}")
    print(f"Frames: {result['frames_path']}")
    print(f"timeline.json: {result['timeline_json']}")
    print(f"timeline.txt:  {result['timeline_txt']}")
    print(f"summary.json:  {result['summary_json']}")
    print(f"summary.txt:   {result['summary_txt']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
