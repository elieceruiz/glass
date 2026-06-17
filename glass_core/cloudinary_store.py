"""Optional Cloudinary video storage for Glass.

Local video files remain the immediate source. Cloudinary is only an additional
mirror used when credentials are available.
"""

from __future__ import annotations

from pathlib import Path
import os

import cloudinary
import cloudinary.api
import cloudinary.uploader
from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parents[1]


def cloudinary_credentials() -> dict[str, str]:
    load_dotenv(BASE_DIR / ".env")
    credentials = {
        "cloud_name": os.getenv("CLOUDINARY_CLOUD_NAME", "").strip(),
        "api_key": os.getenv("CLOUDINARY_API_KEY", "").strip(),
        "api_secret": os.getenv("CLOUDINARY_API_SECRET", "").strip(),
    }
    missing = [key for key, value in credentials.items() if not value]
    if missing:
        raise RuntimeError(f"Faltan credenciales Cloudinary: {', '.join(missing)}")
    return credentials


def configure_cloudinary() -> None:
    credentials = cloudinary_credentials()
    cloudinary.config(
        cloud_name=credentials["cloud_name"],
        api_key=credentials["api_key"],
        api_secret=credentials["api_secret"],
        secure=True,
    )


def upload_video(video_path: Path | str, session_id: str) -> dict:
    video_path = Path(video_path)
    if not video_path.exists():
        raise FileNotFoundError(f"No existe el video para Cloudinary: {video_path}")
    if not session_id:
        raise ValueError("upload_video requiere session_id.")

    configure_cloudinary()
    result = cloudinary.uploader.upload_large(
        str(video_path),
        resource_type="video",
        folder=f"glass/sessions/{session_id}",
        public_id=video_path.stem,
        overwrite=True,
    )
    return {
        "secure_url": result.get("secure_url", ""),
        "public_id": result.get("public_id", ""),
        "resource_type": result.get("resource_type", "video"),
        "bytes": result.get("bytes"),
        "duration": result.get("duration"),
    }


def validate_connection() -> dict:
    credentials = cloudinary_credentials()
    cloudinary.config(
        cloud_name=credentials["cloud_name"],
        api_key=credentials["api_key"],
        api_secret=credentials["api_secret"],
        secure=True,
    )
    usage = cloudinary.api.usage()
    return {
        "ok": True,
        "cloud_name": credentials["cloud_name"],
        "plan": usage.get("plan"),
    }
