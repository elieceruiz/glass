from pathlib import Path
import json
import os
import re
import time
import traceback
from datetime import datetime

import streamlit as st
from dotenv import load_dotenv
from streamlit_autorefresh import st_autorefresh


BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")
RECORDINGS_DIR = BASE_DIR / "glass_recordings"
ANALYSIS_DIR = BASE_DIR / "video_analysis"
UPLOADS_DIR = BASE_DIR / "cloud_uploads"
GLASS_MODE = os.getenv("GLASS_MODE", "local").strip().lower() or "local"
GLASS_RECORDER_WEB_URL = os.getenv("GLASS_RECORDER_WEB_URL", "https://glass-recorder-web.vercel.app").strip()

DETAIL_OPTIONS = {
    10: ("Muy detallado", "más puntos de observación, lectura más fina"),
    20: ("Detallado", "buena lectura para sesiones con cambios frecuentes"),
    30: ("Balanceado", "equilibrio entre detalle y velocidad"),
    60: ("Rápido", "menos espera para sesiones largas"),
    120: ("Panorámico", "vista general del bloque de tiempo"),
}

CATEGORY_COLORS = {
    "higiene": "#67e8f9",
    "orden": "#86efac",
    "trabajo": "#c4b5fd",
    "estudio": "#93c5fd",
    "descanso": "#fde68a",
    "ausencia": "#cbd5e1",
    "tiempo_muerto": "#d1d5db",
    "limpieza": "#5eead4",
    "cocina": "#fdba74",
    "ejercicio": "#fda4af",
    "escritura": "#a7f3d0",
    "creatividad": "#f0abfc",
    "pensamiento": "#bfdbfe",
    "concentración": "#bae6fd",
    "concentracion": "#bae6fd",
    "incierto": "#e5e7eb",
}


st.set_page_config(
    page_title="Glass",
    page_icon="G",
    layout="centered",
    initial_sidebar_state="collapsed",
)


def read_json(path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return default


def clean_text(value):
    text = str(value or "")
    try:
        repaired = text.encode("latin1").decode("utf-8")
        if repaired.count("�") <= text.count("�"):
            return repaired
    except (UnicodeEncodeError, UnicodeDecodeError):
        pass
    return text


def timestamp_to_seconds(value):
    try:
        hh, mm, rest = clean_text(value).split(":")
        ss, ms = rest.split(".")
        return int(hh) * 3600 + int(mm) * 60 + int(ss) + int(ms) / 1000
    except (ValueError, AttributeError):
        return 0.0


def seconds_to_timestamp(seconds, milliseconds=False):
    seconds = max(0, float(seconds or 0))
    whole = int(seconds)
    ms = int((seconds - whole) * 1000)
    base = f"{whole // 3600:02d}:{(whole % 3600) // 60:02d}:{whole % 60:02d}"
    return f"{base}.{ms:03d}" if milliseconds else base


def load_analysis(path):
    path = Path(path)
    if not path.exists():
        return {}
    return {
        "path": path,
        "timeline": read_json(path / "timeline.json", []),
        "summary": read_json(path / "summary.json", {}),
    }


def load_cloud_sessions():
    try:
        from glass_core.db import list_analysis_for_sessions, list_sessions

        metadata_items = list_sessions(limit=20)
        analysis_by_session = list_analysis_for_sessions([
            str(item.get("session_id", "")) for item in metadata_items if item.get("session_id")
        ])
    except Exception as exc:
        st.warning(f"No pude cargar sesiones desde MongoDB: {type(exc).__name__}: {exc}")
        return []

    sessions = []
    for item in metadata_items:
        session_id = str(item.get("session_id") or "")
        analysis_doc = analysis_by_session.get(session_id, {})
        sessions.append({
            "id": session_id,
            "path": item.get("session_dir") or item.get("metadata_path") or "",
            "source": "mongo",
            "metadata": item,
            "analysis": {
                "path": analysis_doc.get("analysis_path", ""),
                "timeline": analysis_doc.get("timeline", []),
                "summary": analysis_doc.get("summary", {}),
            },
            "mtime": timestamp_to_seconds(item.get("duracion_hhmmss", "00:00:00.000")),
        })
    return sessions


def load_sessions():
    if GLASS_MODE == "cloud":
        return load_cloud_sessions()

    sessions = []
    known_paths = set()

    if RECORDINGS_DIR.exists():
        for path in RECORDINGS_DIR.iterdir():
            if not path.is_dir():
                continue
            metadata = read_json(path / "metadata.json", {})
            analysis_path = metadata.get("analysis_output_dir")
            analysis = load_analysis(analysis_path) if analysis_path else {}
            if analysis.get("path"):
                known_paths.add(str(analysis["path"]))
            sessions.append({
                "id": path.name,
                "path": path,
                "source": "recording",
                "metadata": metadata,
                "analysis": analysis,
                "mtime": path.stat().st_mtime,
            })

    if ANALYSIS_DIR.exists():
        for path in ANALYSIS_DIR.iterdir():
            if not path.is_dir() or str(path) in known_paths:
                continue
            analysis = load_analysis(path)
            if analysis:
                sessions.append({
                    "id": path.name,
                    "path": path,
                    "source": "analysis_orphan",
                    "metadata": {},
                    "analysis": analysis,
                    "mtime": path.stat().st_mtime,
                })

    return sorted(sessions, key=lambda item: item.get("mtime", 0), reverse=True)


def latest_reflection():
    sessions = load_sessions()
    return sessions[0] if sessions else None


def active_session_reflection():
    active_id = st.session_state.get("active_session_id")
    if not active_id:
        return None

    cloud_reflection = st.session_state.get("cloud_active_reflection")
    if GLASS_MODE == "cloud" and cloud_reflection and cloud_reflection.get("id") == active_id:
        return cloud_reflection

    for session in load_sessions():
        if GLASS_MODE != "cloud" and session.get("source") != "recording":
            continue
        if session.get("id") == active_id:
            return session
    return None


def traceability(session):
    detail, label, _ = selected_detail()
    if not session:
        return {
            "session_id": st.session_state.get("active_session_id", "sesión actual"),
            "recording": "pendiente",
            "analysis": "pendiente",
            "detail": f"{detail}s · {label}",
            "status": "sin análisis asociado a esta sesión",
        }

    metadata = session.get("metadata", {})
    video = metadata.get("video") or "pendiente"
    analysis_path = metadata.get("analysis_output_dir") or ""
    analysis = session.get("analysis", {})
    timeline_ok = bool(analysis.get("timeline"))
    summary_ok = bool(analysis.get("summary"))
    status = "asociado" if analysis_path and timeline_ok and summary_ok else "incompleto"

    return {
        "session_id": session.get("id", ""),
        "recording": clean_text(video),
        "analysis": clean_text(analysis_path or "pendiente"),
        "detail": f"{detail}s · {label}",
        "status": status,
    }


def session_duration(session):
    metadata = session.get("metadata", {})
    if metadata.get("duracion_hhmmss"):
        return clean_text(metadata["duracion_hhmmss"]).split(".")[0]
    if metadata.get("duracion_segundos"):
        return seconds_to_timestamp(metadata["duracion_segundos"])
    summary = session.get("analysis", {}).get("summary", {})
    return clean_text(summary.get("duracion_total", "00:00:00")).split(".")[0]


def summary_list(summary, key):
    value = summary.get(key, []) if isinstance(summary, dict) else []
    if isinstance(value, list):
        return value
    return [value] if value else []


def category_color(category):
    return CATEGORY_COLORS.get(clean_text(category).lower(), "#bfdbfe")


def category_totals(summary, timeline):
    times = summary.get("tiempo_por_categoria", {}) if isinstance(summary, dict) else {}
    percentages = summary.get("porcentaje_por_categoria", {}) if isinstance(summary, dict) else {}
    categories = sorted(set(times) | set(percentages), key=lambda item: str(item).lower())
    if categories:
        return [
            {
                "categoria": clean_text(category),
                "tiempo": clean_text(times.get(category, "")),
                "porcentaje": percentages.get(category, ""),
            }
            for category in categories
        ]

    totals = {}
    for item in timeline or []:
        category = clean_text(item.get("categoria_general", "incierto"))
        start = timestamp_to_seconds(item.get("inicio"))
        end = timestamp_to_seconds(item.get("fin"))
        totals[category] = totals.get(category, 0) + max(0, end - start)

    total_seconds = sum(totals.values()) or 1
    return [
        {
            "categoria": category,
            "tiempo": seconds_to_timestamp(seconds),
            "porcentaje": round((seconds / total_seconds) * 100, 1),
        }
        for category, seconds in sorted(totals.items(), key=lambda item: item[1], reverse=True)
    ]


def css():
    st.markdown(
        """
        <style>
        .stApp {
            background:
                radial-gradient(circle at 50% 8%, rgba(125, 211, 252, 0.24), transparent 28rem),
                radial-gradient(circle at 95% 18%, rgba(196, 181, 253, 0.16), transparent 24rem),
                linear-gradient(135deg, #f6fafb 0%, #edf4f7 48%, #fbfdfe 100%);
            color: #0f172a;
        }
        .stApp, .stApp p, .stApp li {
            color: #0f172a;
        }
        header,
        [data-testid="stHeader"],
        [data-testid="stMainMenu"],
        [data-testid="stDeployButton"],
        [data-testid="stAppDeployButton"],
        [data-testid="stToolbarActions"],
        section[data-testid="stSidebar"],
        [data-testid="stSidebar"],
        [data-testid="collapsedControl"],
        [data-testid="stSidebarCollapsedControl"],
        [data-testid="stToolbar"],
        [data-testid="stDecoration"],
        [data-testid="stStatusWidget"],
        button[kind="header"],
        [data-testid="stBaseButton-header"],
        [data-testid="stBaseButton-headerNoPadding"] {
            display: none;
        }
        [data-testid="stAlert"] {
            background: #dbeafe;
            border: 1px solid #93c5fd;
            color: #0f172a;
        }
        [data-testid="stAlert"] p,
        [data-testid="stAlert"] div,
        [data-testid="stAlert"] span {
            color: #0f172a !important;
        }
        .block-container {
            max-width: 920px;
            padding-top: 2.4rem;
            padding-bottom: 3rem;
        }
        .screen {
            min-height: 48vh;
            display: flex;
            flex-direction: column;
            justify-content: center;
            text-align: center;
            gap: 1.15rem;
        }
        .brand {
            color: #2563eb;
            text-transform: uppercase;
            letter-spacing: 0.16em;
            font-size: 0.78rem;
            font-weight: 800;
        }
        .title {
            font-size: clamp(3.4rem, 9vw, 7.5rem);
            line-height: 0.92;
            letter-spacing: -0.055em;
            margin: 0.1rem 0;
            font-weight: 780;
        }
        .subtitle {
            font-size: 1.2rem;
            color: #475569;
            margin-bottom: 0.6rem;
        }
        .timer {
            font-variant-numeric: tabular-nums;
            font-size: clamp(3.2rem, 10vw, 7.2rem);
            line-height: 1;
            font-weight: 780;
            letter-spacing: -0.04em;
            color: #0f172a;
        }
        .recording {
            color: #dc2626;
            letter-spacing: 0.12em;
            font-weight: 800;
            font-size: 1rem;
        }
        .glass-card {
            background: rgba(255,255,255,0.94);
            border: 1px solid rgba(210, 225, 233, 0.95);
            border-radius: 24px;
            padding: 1.35rem 1.45rem;
            box-shadow: 0 20px 60px rgba(15, 23, 42, 0.08);
            backdrop-filter: blur(18px);
            text-align: left;
            color: #0f172a;
        }
        .center-card {
            text-align: center;
        }
        .primary button {
            height: 3.4rem;
            border-radius: 999px;
            font-size: 1.05rem;
            font-weight: 760;
        }
        .muted {
            color: #334155;
        }
        .camera-frame {
            border: 1px solid #dbe7ee;
            border-radius: 22px;
            padding: 0.85rem;
            background: rgba(255,255,255,0.94);
            box-shadow: inset 0 0 0 1px rgba(255,255,255,0.45);
        }
        .camera-frame img {
            border-radius: 16px;
        }
        .countdown {
            font-size: clamp(8rem, 20vw, 15rem);
            line-height: 0.9;
            font-weight: 820;
            letter-spacing: -0.07em;
        }
        .timeline-wrap {
            background: rgba(255,255,255,0.94);
            border: 1px solid #dbe7ee;
            border-radius: 24px;
            padding: 1rem;
            color: #0f172a;
        }
        .timeline-bar {
            display: flex;
            height: 46px;
            overflow: hidden;
            border-radius: 999px;
            border: 1px solid rgba(148, 163, 184, 0.35);
            background: #e5e7eb;
        }
        .timeline-segment {
            min-width: 5px;
            height: 100%;
        }
        .legend {
            display: flex;
            gap: 0.45rem;
            flex-wrap: wrap;
            margin-top: 0.85rem;
            justify-content: center;
        }
        .pill {
            display: inline-flex;
            align-items: center;
            gap: 0.35rem;
            border: 1px solid #dbe7ee;
            border-radius: 999px;
            padding: 0.28rem 0.62rem;
            background: rgba(255,255,255,0.94);
            color: #0f172a;
            font-size: 0.86rem;
        }
        .dot {
            width: 10px;
            height: 10px;
            border-radius: 99px;
            display: inline-block;
            border: 1px solid rgba(15,23,42,0.12);
        }
        .metric-row {
            display: grid;
            grid-template-columns: repeat(3, minmax(0, 1fr));
            gap: 0.8rem;
            margin: 1.2rem 0;
        }
        .soft-metric {
            background: rgba(248, 250, 252, 0.96);
            border: 1px solid #dbe7ee;
            border-radius: 16px;
            padding: 1rem;
            text-align: center;
            color: #0f172a;
        }
        .soft-metric b {
            display: block;
            font-size: 1.38rem;
            line-height: 1.1;
        }
        .chapter {
            border-left: 3px solid #7dd3fc;
            padding: 0.15rem 0 0.9rem 1rem;
            margin: 0.45rem 0;
        }
        .chapter-time {
            color: #2563eb;
            font-size: 0.85rem;
            font-weight: 760;
        }
        .chapter-title {
            font-size: 1.05rem;
            font-weight: 720;
            margin: 0.15rem 0;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def reset_flow():
    st.session_state.stage = "inicio"
    st.session_state.countdown_started = None
    st.session_state.session_started = None
    st.session_state.session_finished = None
    st.session_state.observed_seconds = 0.0
    st.session_state.active_session_id = None
    st.session_state.active_started_at = None
    st.session_state.active_video_path = None
    st.session_state.active_analysis_path = None
    st.session_state.detail_seconds = 30
    st.session_state.active_detail_seconds = None
    st.session_state.recording_status = "idle"
    st.session_state.analysis_status = "idle"
    st.session_state.recorder = None
    st.session_state.recording_result = None
    st.session_state.analysis_error = ""
    st.session_state.analysis_started = False
    st.session_state.stop_requested = False
    st.session_state.stop_in_progress = False
    st.session_state.stop_completed = False
    st.session_state.persistence_warning = ""
    st.session_state.cloud_active_reflection = None


def app_log(message):
    print(message, flush=True)


def update_metadata_file(metadata_path, fields):
    metadata_path = Path(metadata_path)
    metadata = read_json(metadata_path, {})
    metadata.update(fields)
    metadata_path.write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")
    return metadata


def mirror_session_to_mongo(metadata_path):
    try:
        from glass_core.db import build_session_document, save_session

        result = save_session(build_session_document(metadata_path))
        app_log(f"Mongo session mirror OK: {result}")
        return True
    except Exception as exc:
        app_log(f"Mongo session mirror skipped/error: {type(exc).__name__}: {exc}")
        return False


def mirror_analysis_to_mongo(session_id, analysis_path):
    try:
        from glass_core.db import build_analysis_document, save_analysis

        result = save_analysis(session_id, build_analysis_document(session_id, analysis_path))
        app_log(f"Mongo analysis mirror OK: {result}")
        return True
    except Exception as exc:
        app_log(f"Mongo analysis mirror skipped/error: {type(exc).__name__}: {exc}")
        return False


def persist_successful_session(recorder, analysis_path, video_path):
    if recorder is None:
        return

    session_id = st.session_state.get("active_session_id")
    metadata_path = recorder.metadata_path
    fields = {
        "mongo_status": "skipped",
        "cloudinary_status": "skipped",
        "cloudinary_video_url": "",
        "cloudinary_public_id": "",
        "persistence_error": "",
    }
    errors = []

    try:
        from glass_core.db import build_session_document, save_session

        save_session(build_session_document(metadata_path))
        fields["mongo_status"] = "success"
        app_log("Mongo session mirror OK.")
    except Exception as exc:
        fields["mongo_status"] = "error"
        errors.append(f"Mongo session: {type(exc).__name__}: {exc}")
        app_log(f"Mongo session mirror error: {type(exc).__name__}: {exc}")

    try:
        from glass_core.db import build_analysis_document, save_analysis

        save_analysis(session_id, build_analysis_document(session_id, analysis_path))
        app_log("Mongo analysis mirror OK.")
    except Exception as exc:
        fields["mongo_status"] = "error"
        errors.append(f"Mongo analysis: {type(exc).__name__}: {exc}")
        app_log(f"Mongo analysis mirror error: {type(exc).__name__}: {exc}")

    try:
        from glass_core.cloudinary_store import upload_video

        upload = upload_video(video_path, session_id)
        fields["cloudinary_status"] = "success"
        fields["cloudinary_video_url"] = upload.get("secure_url", "")
        fields["cloudinary_public_id"] = upload.get("public_id", "")
        fields["cloudinary_resource_type"] = upload.get("resource_type", "video")
        fields["cloudinary_bytes"] = upload.get("bytes")
        fields["cloudinary_duration"] = upload.get("duration")
        app_log(f"Cloudinary video upload OK: {fields['cloudinary_public_id']}")
    except Exception as exc:
        message = str(exc)
        fields["cloudinary_status"] = "skipped" if "Faltan credenciales" in message else "error"
        errors.append(f"Cloudinary: {type(exc).__name__}: {exc}")
        app_log(f"Cloudinary video upload skipped/error: {type(exc).__name__}: {exc}")

    fields["persistence_error"] = " | ".join(errors)
    update_metadata_file(metadata_path, fields)
    if fields["mongo_status"] == "success":
        try:
            from glass_core.db import update_session

            update_session(session_id, fields)
        except Exception as exc:
            app_log(f"Mongo persistence status update error: {type(exc).__name__}: {exc}")
    if errors:
        st.session_state.persistence_warning = fields["persistence_error"]


def safe_session_id(session_id):
    cleaned = re.sub(r"[^A-Za-z0-9_-]+", "-", str(session_id or "").strip())
    return cleaned.strip("-")[:80]


def query_param(name):
    value = st.query_params.get(name)
    if isinstance(value, list):
        return str(value[0]) if value else ""
    return str(value or "").strip()


def cloud_reflection_from_docs(session_doc, analysis_doc):
    session_id = str(session_doc.get("session_id") or analysis_doc.get("session_id") or "")
    return {
        "id": session_id,
        "path": session_doc.get("session_dir") or session_doc.get("metadata_path") or "",
        "source": "mongo",
        "metadata": session_doc,
        "analysis": {
            "path": analysis_doc.get("analysis_path", ""),
            "timeline": analysis_doc.get("timeline", []),
            "summary": analysis_doc.get("summary", {}),
        },
        "mtime": timestamp_to_seconds(session_doc.get("duracion_hhmmss", "00:00:00.000")),
    }


def load_existing_cloud_reflection(session_id):
    try:
        from glass_core.db import get_analysis, get_session

        session_doc = get_session(session_id) or {}
        analysis_doc = get_analysis(session_id) or {}
    except Exception as exc:
        app_log(f"No pude consultar MongoDB para evitar reproceso: {type(exc).__name__}: {exc}")
        return None

    timeline = analysis_doc.get("timeline") or []
    summary = analysis_doc.get("summary") or {}
    if session_doc and timeline and summary and session_doc.get("analysis_status") == "success":
        return cloud_reflection_from_docs(session_doc, analysis_doc)
    return None


def ensure_state():
    if "stage" not in st.session_state:
        reset_flow()


def start_countdown():
    st.session_state.active_detail_seconds = st.session_state.get("detail_seconds", 30)
    st.session_state.recording_status = "preparando"
    st.session_state.analysis_status = "pendiente"
    st.session_state.stage = "cuenta"
    st.session_state.countdown_started = time.time()
    st.rerun()


def start_recording():
    if GLASS_MODE == "cloud":
        st.session_state.analysis_error = (
            "En cloud, la captura empieza desde Glass Recorder Web."
        )
        st.session_state.stage = "inicio"
        st.rerun()

    from glass_core.recorder import GlassRecorder

    session_id = datetime.now().strftime("%Y%m%d-%H%M%S")
    detail_seconds = st.session_state.get("active_detail_seconds") or st.session_state.get("detail_seconds", 30)
    recorder = GlassRecorder(
        session_id=session_id,
        output_root=RECORDINGS_DIR,
        fps=15,
        resolution=(640, 480),
        auto_analyze=False,
        analysis_every_seconds=detail_seconds,
    )

    try:
        recorder.start()
    except Exception as exc:
        st.session_state.recording_status = "error"
        st.session_state.analysis_status = "skipped"
        st.session_state.analysis_error = f"{type(exc).__name__}: {exc}"
        st.session_state.stage = "reflejo"
        st.rerun()

    st.session_state.recorder = recorder
    st.session_state.stage = "activa"
    st.session_state.session_started = time.time()
    st.session_state.session_finished = None
    st.session_state.active_started_at = recorder.started_at
    st.session_state.active_session_id = session_id
    st.session_state.active_video_path = "grabando..."
    st.session_state.active_analysis_path = "pendiente"
    st.session_state.recording_status = "activa"
    st.session_state.analysis_status = "pendiente"
    st.session_state.stop_requested = False
    st.session_state.stop_in_progress = False
    st.session_state.stop_completed = False
    st.rerun()


def request_finish_session():
    if st.session_state.get("stop_requested"):
        return
    st.session_state.stop_requested = True
    st.session_state.recording_status = "stopping"
    st.session_state.stage = "stopping"
    st.rerun()


def finish_session():
    if st.session_state.get("stop_completed"):
        st.session_state.stage = "generando"
        st.rerun()
    if st.session_state.get("stop_in_progress"):
        return
    st.session_state.stop_in_progress = True
    st.session_state.recording_status = "stopping"
    app_log("Finalizando sesión...")

    now = time.time()
    recorder = st.session_state.get("recorder")
    st.session_state.session_finished = now
    st.session_state.observed_seconds = max(0.0, now - float(st.session_state.session_started or now))
    try:
        if recorder is None:
            raise RuntimeError("No hay grabador activo para detener.")
        result = recorder.stop()
        app_log(f"Video cerrado: {result.video_path}")
        st.session_state.recording_result = result
        st.session_state.active_video_path = str(result.video_path)
        st.session_state.observed_seconds = result.duration_seconds
        st.session_state.recording_status = "finalizada"
        st.session_state.analysis_status = "pendiente"
    except Exception as exc:
        st.session_state.recording_status = "error"
        st.session_state.analysis_status = "skipped"
        st.session_state.analysis_error = f"{type(exc).__name__}: {exc}"
        app_log(f"Error al finalizar sesión: {st.session_state.analysis_error}")
    st.session_state.stop_completed = True
    st.session_state.stop_in_progress = False
    st.session_state.stage = "generando"
    st.rerun()


def estimate_observation_points(minutes, detail_seconds):
    return max(1, int((minutes * 60) / detail_seconds))


def estimate_analysis_time(points):
    minutes = max(1, round(points / 28))
    return f"~{minutes} min"


def selected_detail():
    value = st.session_state.get("active_detail_seconds") or st.session_state.get("detail_seconds", 30)
    label, description = DETAIL_OPTIONS.get(value, DETAIL_OPTIONS[30])
    return value, label, description


def write_session_analysis_error(message, full_traceback=""):
    session_id = st.session_state.get("active_session_id")
    if not session_id:
        return None
    session_dir = RECORDINGS_DIR / session_id
    session_dir.mkdir(parents=True, exist_ok=True)
    error_path = session_dir / "analysis_error.txt"
    body = str(message).strip() + "\n"
    if full_traceback:
        body += "\n" + full_traceback
    error_path.write_text(body, encoding="utf-8")
    return error_path


def resolve_current_video_path():
    result = st.session_state.get("recording_result")
    recorder = st.session_state.get("recorder")

    if result is None and recorder is not None:
        result = getattr(recorder, "result", None)
        if result is not None:
            st.session_state.recording_result = result
            st.session_state.active_video_path = str(result.video_path)

    video_path = getattr(result, "video_path", None)
    if video_path is None:
        candidate = st.session_state.get("active_video_path")
        if candidate and candidate != "grabando...":
            video_path = Path(candidate)

    if video_path is None or not Path(video_path).exists():
        raise RuntimeError("No hay video grabado para analizar.")
    return Path(video_path)


def run_current_analysis():
    from video_activity_analyzer import analyze_video

    recorder = st.session_state.get("recorder")
    detail_seconds = st.session_state.get("active_detail_seconds") or st.session_state.get("detail_seconds", 30)
    video_path = resolve_current_video_path()

    st.session_state.analysis_status = "running"
    st.session_state.analysis_error = ""
    st.session_state.active_analysis_path = "analizando..."

    try:
        app_log(f"Ejecutando análisis con detalle: {detail_seconds}s")
        app_log("DEBUG app: antes de analyze_video() en flujo local.")
        analysis = analyze_video(video_path, every_seconds=detail_seconds)
        app_log("DEBUG app: analyze_video() completado en flujo local.")
    except Exception as exc:
        message = f"{type(exc).__name__}: {exc}"
        full_traceback = traceback.format_exc()
        error_path = write_session_analysis_error(message, full_traceback)
        st.session_state.analysis_status = "error"
        st.session_state.analysis_error = message
        st.session_state.active_analysis_path = str(error_path) if error_path else "error"
        if recorder is not None:
            try:
                recorder.update_analysis_metadata("error", "", message)
                update_metadata_file(recorder.metadata_path, {
                    "mongo_status": "skipped",
                    "cloudinary_status": "skipped",
                    "cloudinary_video_url": "",
                    "cloudinary_public_id": "",
                    "persistence_error": "Analisis local fallido; persistencia remota omitida.",
                })
            except Exception:
                pass
        app_log(f"Análisis falló: {message}")
        app_log(full_traceback)
        return False

    analysis_path = analysis["analysis_path"]
    st.session_state.active_analysis_path = analysis_path
    st.session_state.analysis_status = "success"
    if recorder is not None:
        recorder.update_analysis_metadata("success", analysis_path, "")
        persist_successful_session(recorder, analysis_path, video_path)
    app_log(f"Análisis terminado: {analysis_path}")
    app_log("Reflejo listo.")
    return True


def render_diagnostics():
    value, label, _ = selected_detail()
    st.markdown("### Diagnóstico temporal")
    st.markdown(
        f"""
        <div class="glass-card">
            <div><b>Detalle seleccionado:</b> {value}s · {label}</div>
            <div><b>Session ID:</b> {st.session_state.get("active_session_id") or "pendiente"}</div>
            <div><b>Estado de grabación:</b> {st.session_state.get("recording_status", "idle")}</div>
            <div><b>Estado de análisis:</b> {st.session_state.get("analysis_status", "idle")}</div>
            <div><b>Ruta del video:</b> {st.session_state.get("active_video_path") or "pendiente"}</div>
            <div><b>Ruta del análisis:</b> {st.session_state.get("active_analysis_path") or "pendiente"}</div>
            <div><b>Error:</b> {st.session_state.get("analysis_error") or "ninguno"}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def timeline_html(timeline):
    if not timeline:
        return ""

    total = max(timestamp_to_seconds(timeline[-1].get("fin")), 1)
    segments = []
    legend = []
    seen = set()

    for item in timeline:
        start = timestamp_to_seconds(item.get("inicio"))
        end = timestamp_to_seconds(item.get("fin"))
        category = clean_text(item.get("categoria_general", "incierto"))
        activity = clean_text(item.get("actividad_detectada", "actividad"))
        color = category_color(category)
        width = max(1.2, ((end - start) / total) * 100)
        segments.append(
            f'<div class="timeline-segment" title="{category}: {activity}" '
            f'style="width:{width:.2f}%; background:{color};"></div>'
        )
        if category not in seen:
            seen.add(category)
            legend.append(
                f'<span class="pill"><span class="dot" style="background:{color};"></span>{category}</span>'
            )

    return f"""
    <div class="timeline-wrap">
        <div class="timeline-bar">{''.join(segments)}</div>
        <div class="legend">{''.join(legend)}</div>
    </div>
    """


def render_start():
    if GLASS_MODE == "cloud":
        render_cloud_viewer()
        return

    st.markdown(
        """
        <section class="screen">
            <div>
                <div class="brand">Glass</div>
                <h1 class="title">Glass</h1>
                <div class="subtitle">Observatorio personal de actividad</div>
            </div>
            <div class="timer">00:00:00</div>
        </section>
        """,
        unsafe_allow_html=True,
    )

    st.markdown('<div class="primary">', unsafe_allow_html=True)
    if st.button("Iniciar sesión", use_container_width=True, type="primary"):
        start_countdown()
    st.markdown("</div>", unsafe_allow_html=True)

    st.write("")
    detail = st.select_slider(
        "Detalle del análisis",
        options=list(DETAIL_OPTIONS.keys()),
        value=st.session_state.get("detail_seconds", 30),
        format_func=lambda value: DETAIL_OPTIONS[value][0],
    )
    st.session_state.detail_seconds = detail
    points = estimate_observation_points(60, detail)
    label, description = DETAIL_OPTIONS[detail]
    st.caption(
        f"{label}: aproximadamente {points} puntos de observación por hora. "
        f"Tiempo estimado de lectura: {estimate_analysis_time(points)}. {description}."
    )

    st.markdown(
        """
        <div style="text-align:center; margin-top:1rem;" class="muted">
            Registra un bloque real de tiempo.<br>
            Después Glass lo convierte en tu reflejo.
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.write("")


def render_countdown():
    started = float(st.session_state.countdown_started or time.time())
    elapsed = time.time() - started
    remaining = max(0, 3 - int(elapsed))

    st.markdown(
        f"""
        <section class="screen">
            <div>
                <div class="brand">Glass</div>
                <div class="subtitle">Preparando observación</div>
            </div>
            <div class="countdown">{remaining or 1}</div>
            <div class="muted">La sesión empieza ahora.</div>
        </section>
        """,
        unsafe_allow_html=True,
    )

    if elapsed >= 3:
        start_recording()
    time.sleep(0.2)
    st.rerun()


def render_active_clock():
    started = float(st.session_state.session_started or time.time())
    elapsed = time.time() - started
    st.markdown(
        f"""
        <section style="text-align:center; padding-top:1.4rem;">
            <div class="brand">Glass</div>
            <div class="recording">● REC</div>
            <div class="timer">{seconds_to_timestamp(elapsed, milliseconds=True)}</div>
        </section>
        """,
        unsafe_allow_html=True,
    )


def render_active():
    st_autorefresh(interval=1000, key="recording_clock_refresh")
    render_active_clock()
    detail, label, _ = selected_detail()
    session_id = st.session_state.get("active_session_id") or "pendiente"
    recording_status = st.session_state.get("recording_status", "idle")
    st.markdown(
        f"""
        <div class="glass-card center-card">
            <div><b>Detalle seleccionado:</b> {detail}s · {label}</div>
            <div><b>Session ID:</b> {session_id}</div>
            <div><b>Estado de grabación:</b> {recording_status}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.write("")
    st.markdown('<div class="primary">', unsafe_allow_html=True)
    disabled = st.session_state.get("recording_status") != "activa" or st.session_state.get("stop_requested", False)
    if st.button("Finalizar sesión", use_container_width=True, type="primary", disabled=disabled):
        request_finish_session()
    st.markdown("</div>", unsafe_allow_html=True)


def render_stopping():
    st.markdown(
        """
        <section class="screen">
            <div>
                <div class="brand">Glass</div>
                <h2>Finalizando sesión...</h2>
                <div class="muted">Cerrando video real antes de analizar.</div>
            </div>
        </section>
        """,
        unsafe_allow_html=True,
    )
    finish_session()


def render_generating():
    observed = seconds_to_timestamp(st.session_state.observed_seconds)
    detail, label, _ = selected_detail()
    session_id = st.session_state.get("active_session_id") or "pendiente"
    video_path = st.session_state.get("active_video_path") or "pendiente"
    st.markdown(
        f"""
        <section class="screen">
            <div>
                <div class="brand">Glass</div>
                <div class="timer">{observed}</div>
                <div class="subtitle">observados</div>
            </div>
            <div class="glass-card center-card">
                <h2 style="margin-top:0;">Generando tu reflejo...</h2>
                <p class="muted">Glass está observando los momentos principales.</p>
                <p><b>Análisis en curso</b></p>
                <p class="muted">Esto puede tardar varios minutos.</p>
                <p class="muted">Sesión: {session_id}</p>
                <p class="muted">Video: {video_path}</p>
                <p class="muted">Detalle seleccionado: {detail}s · {label}</p>
            </div>
        </section>
        """,
        unsafe_allow_html=True,
    )

    if not st.session_state.get("analysis_started"):
        st.session_state.analysis_started = True
        with st.spinner("Analizando video real..."):
            run_current_analysis()

    st.session_state.stage = "reflejo"
    st.rerun()


def narrative_sentence(summary, timeline):
    totals = category_totals(summary, timeline)
    if not totals:
        return "Glass terminó la observación. Cuando exista análisis disponible, esta lectura se volverá más precisa."

    ordered = sorted(totals, key=lambda item: float(item.get("porcentaje") or 0), reverse=True)
    main = ordered[0]["categoria"]
    second = ordered[1]["categoria"] if len(ordered) > 1 else None
    if second:
        return (
            f"La mayor parte de esta sesión estuvo dedicada a {main}. "
            f"También aparecieron momentos de {second}, creando un ritmo visible entre actividad y pausa."
        )
    return f"La sesión estuvo marcada principalmente por {main}, con un ritmo bastante concentrado."


def render_categories(summary, timeline):
    totals = category_totals(summary, timeline)
    if not totals:
        st.info("Aún no hay categorías detectadas para este reflejo.")
        return

    cols = st.columns(min(3, len(totals)))
    for index, item in enumerate(totals[:3]):
        percent = item.get("porcentaje")
        label = f"{percent}%" if percent != "" else item.get("tiempo", "")
        cols[index % len(cols)].markdown(
            f"""
            <div class="soft-metric">
                <span class="muted">{item['categoria']}</span>
                <b>{label}</b>
                <span class="muted">{item.get('tiempo', '')}</span>
            </div>
            """,
            unsafe_allow_html=True,
        )


def event_text(event):
    if isinstance(event, dict):
        category = clean_text(event.get("categoria_general") or event.get("categoria") or "")
        activity = clean_text(event.get("actividad_detectada") or event.get("actividad") or "")
        title = category or activity or "Momento observado"
        description = clean_text(event.get("observaciones") or event.get("descripcion") or activity)
        start = clean_text(event.get("inicio", ""))
        end = clean_text(event.get("fin", ""))
        if start and end:
            time_range = f"{start} → {end}"
        else:
            time_range = start or end
        return title, description, time_range
    return clean_text(event), "", ""


def render_narrative(summary, timeline):
    events = timeline[:4] if timeline else summary_list(summary, "eventos_principales")
    st.markdown(
        f"""
        <div class="glass-card">
            <h3 style="margin-top:0;">Lectura narrativa</h3>
            <p>{narrative_sentence(summary, timeline)}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if events:
        st.write("")
        for event in events[:4]:
            title, description, time_range = event_text(event)
            st.markdown(
                f"""
                <div class="chapter">
                    <div class="chapter-time">{time_range}</div>
                    <div class="chapter-title">{title}</div>
                    <div class="muted">{description}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )


def render_recorder_cta():
    if GLASS_RECORDER_WEB_URL:
        st.link_button(
            "Grabar nuevo reflejo",
            GLASS_RECORDER_WEB_URL,
            use_container_width=True,
            type="primary",
        )
    else:
        st.warning("No hay URL configurada para Glass Recorder Web.")


def render_result(show_brand=True, show_cloud_cta=True):
    reflection = active_session_reflection()
    if reflection is None and GLASS_MODE == "cloud":
        reflection = latest_reflection()
    summary = reflection.get("analysis", {}).get("summary", {}) if reflection else {}
    timeline = reflection.get("analysis", {}).get("timeline", []) if reflection else []
    duration = seconds_to_timestamp(st.session_state.observed_seconds)
    if reflection:
        duration = session_duration(reflection)
    trace = traceability(reflection)

    brand_html = '<div class="brand">Glass</div>' if show_brand else ""
    st.markdown(
        (
            '<section style="text-align:center; padding:2rem 0 1.2rem;">'
            f"{brand_html}"
            '<h1 class="title">Tu Reflejo</h1>'
            '<div class="subtitle">Así se fue tu tiempo.</div>'
            "</section>"
            '<div class="metric-row">'
            f'<div class="soft-metric"><span class="muted">Duración observada</span><b>{duration}</b></div>'
            f'<div class="soft-metric"><span class="muted">Momentos principales</span><b>{len(timeline)}</b></div>'
            f'<div class="soft-metric"><span class="muted">Lectura</span><b>{"lista" if timeline else "pendiente"}</b></div>'
            "</div>"
        ),
        unsafe_allow_html=True,
    )

    if timeline:
        st.markdown(timeline_html(timeline), unsafe_allow_html=True)
    else:
        st.info(
            "La sesión terminó, pero todavía no hay un análisis asociado a esta sesión. "
            "Glass no mostrará un reflejo de otra sesión."
        )
        if st.session_state.get("analysis_status") == "error":
            st.error(f"El análisis falló: {st.session_state.get('analysis_error')}")
            if st.button("Reintentar análisis", use_container_width=True, type="primary"):
                st.session_state.analysis_started = False
                st.session_state.analysis_error = ""
                st.session_state.analysis_status = "pendiente"
                st.session_state.stage = "generando"
                st.rerun()

    metadata = reflection.get("metadata", {}) if reflection else {}
    cloudinary_url = metadata.get("cloudinary_video_url", "")
    if cloudinary_url:
        st.write("")
        st.video(cloudinary_url)

    persistence_error = st.session_state.get("persistence_warning") or metadata.get("persistence_error", "")
    if persistence_error:
        st.warning(f"Persistencia remota incompleta: {persistence_error}")

    with st.expander("Trazabilidad de este reflejo", expanded=not bool(timeline)):
        st.write(f"Sesión: `{trace['session_id']}`")
        st.write(f"Detalle: `{trace['detail']}`")
        st.write(f"Video: `{trace['recording']}`")
        st.write(f"Análisis: `{trace['analysis']}`")
        st.write(f"Estado: `{trace['status']}`")

    st.write("")
    st.markdown("### Categorías detectadas")
    render_categories(summary, timeline)

    st.write("")
    render_narrative(summary, timeline)

    st.write("")
    if GLASS_MODE == "cloud":
        if show_cloud_cta:
            render_recorder_cta()
    elif st.button("Iniciar otra sesión", use_container_width=True, type="primary"):
        reset_flow()
        st.rerun()


def render_cloud_viewer():
    st.markdown(
        """
        <section style="text-align:center; padding:2rem 0 1.2rem;">
            <h1 class="title">Glass</h1>
            <div class="subtitle">Tu observatorio de reflejos</div>
        </section>
        """,
        unsafe_allow_html=True,
    )

    st.markdown('<div class="primary">', unsafe_allow_html=True)
    render_recorder_cta()
    st.markdown("</div>", unsafe_allow_html=True)

    session_id = safe_session_id(query_param("session_id"))

    if session_id:
        reflection = load_existing_cloud_reflection(session_id)
        if reflection:
            st.session_state.cloud_active_reflection = reflection
            st.session_state.active_session_id = session_id
            st.session_state.analysis_status = "success"
            st.session_state.active_analysis_path = reflection.get("analysis", {}).get("path", "")
            st.session_state.active_video_path = reflection.get("metadata", {}).get("cloudinary_video_url", "")
            st.session_state.observed_seconds = timestamp_to_seconds(
                reflection.get("metadata", {}).get("duracion_hhmmss", "00:00:00.000")
            )
            render_result(show_brand=False, show_cloud_cta=False)
            return
        else:
            st.warning(
                "Tu reflejo aún se está generando. Intenta actualizar en unos segundos."
            )
            return

    sessions = load_sessions()
    if not sessions:
        st.warning("Aún no hay reflejos disponibles.")
        return

    st.session_state.active_session_id = sessions[0]["id"]
    render_result(show_brand=False, show_cloud_cta=False)


def main():
    ensure_state()
    css()

    if GLASS_MODE == "cloud":
        render_cloud_viewer()
        return

    if st.session_state.stage == "inicio":
        render_start()
    elif st.session_state.stage == "cuenta":
        render_countdown()
    elif st.session_state.stage == "activa":
        render_active()
    elif st.session_state.stage == "stopping":
        render_stopping()
    elif st.session_state.stage == "generando":
        render_generating()
    elif st.session_state.stage == "reflejo":
        render_result()


if __name__ == "__main__":
    main()
