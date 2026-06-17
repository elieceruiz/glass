"""MongoDB mirror for Glass.

Local JSON files remain the source of truth for now. This module only mirrors
session and analysis data into MongoDB when MONGO_URI is available.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import json
import os

from dotenv import load_dotenv
from pymongo import ASCENDING, MongoClient
from pymongo.collection import Collection
from pymongo.database import Database


BASE_DIR = Path(__file__).resolve().parents[1]
DEFAULT_DB_NAME = "glass"
SESSION_COLLECTION = "glass_sessions"
ANALYSIS_COLLECTION = "glass_analysis"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def load_json(path: Path | str, default: Any) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return default


def mongo_uri() -> str:
    load_dotenv(BASE_DIR / ".env")
    uri = os.getenv("MONGO_URI", "").strip()
    if not uri:
        raise RuntimeError("Falta MONGO_URI en .env.")
    return uri


def get_client(timeout_ms: int = 5000) -> MongoClient:
    return MongoClient(mongo_uri(), serverSelectionTimeoutMS=timeout_ms)


def get_database(client: MongoClient | None = None) -> Database:
    client = client if client is not None else get_client()
    return client.get_default_database(DEFAULT_DB_NAME)


def collections(db: Database | None = None) -> tuple[Collection, Collection]:
    db = db if db is not None else get_database()
    return db[SESSION_COLLECTION], db[ANALYSIS_COLLECTION]


def ensure_indexes(db: Database | None = None) -> None:
    sessions, analyses = collections(db)
    sessions.create_index([("session_id", ASCENDING)], unique=True)
    sessions.create_index([("started_at", ASCENDING)])
    sessions.create_index([("analysis_status", ASCENDING)])
    analyses.create_index([("session_id", ASCENDING)], unique=True)
    analyses.create_index([("analysis_path", ASCENDING)])
    analyses.create_index([("created_at", ASCENDING)])


def normalize_document(data: dict[str, Any]) -> dict[str, Any]:
    normalized = {}
    for key, value in data.items():
        if isinstance(value, Path):
            normalized[key] = str(value)
        elif isinstance(value, dict):
            normalized[key] = normalize_document(value)
        elif isinstance(value, list):
            normalized[key] = [
                normalize_document(item) if isinstance(item, dict) else str(item) if isinstance(item, Path) else item
                for item in value
            ]
        else:
            normalized[key] = value
    return normalized


def save_session(session: dict[str, Any]) -> dict[str, Any]:
    session = normalize_document(session)
    session_id = session.get("session_id")
    if not session_id:
        raise ValueError("save_session requiere session_id.")

    db = get_database()
    ensure_indexes(db)
    sessions = db[SESSION_COLLECTION]
    now = utc_now()
    document = {
        **session,
        "updated_at": now,
    }
    result = sessions.update_one(
        {"session_id": session_id},
        {"$set": document, "$setOnInsert": {"created_at": now}},
        upsert=True,
    )
    return {"matched": result.matched_count, "modified": result.modified_count, "upserted_id": str(result.upserted_id)}


def update_session(session_id: str, updates: dict[str, Any]) -> dict[str, Any]:
    if not session_id:
        raise ValueError("update_session requiere session_id.")

    db = get_database()
    ensure_indexes(db)
    result = db[SESSION_COLLECTION].update_one(
        {"session_id": session_id},
        {"$set": {**normalize_document(updates), "updated_at": utc_now()}},
        upsert=False,
    )
    return {"matched": result.matched_count, "modified": result.modified_count}


def save_analysis(session_id: str | dict[str, Any], analysis_doc: dict[str, Any] | None = None) -> dict[str, Any]:
    if analysis_doc is None and isinstance(session_id, dict):
        analysis = session_id
        session_id = str(analysis.get("session_id", ""))
    else:
        analysis = {"session_id": session_id, **(analysis_doc or {})}
    analysis = normalize_document(analysis)
    session_id = str(analysis.get("session_id", ""))
    if not session_id:
        raise ValueError("save_analysis requiere session_id.")

    db = get_database()
    ensure_indexes(db)
    analyses = db[ANALYSIS_COLLECTION]
    now = utc_now()
    document = {
        **analysis,
        "updated_at": now,
    }
    result = analyses.update_one(
        {"session_id": session_id},
        {"$set": document, "$setOnInsert": {"created_at": now}},
        upsert=True,
    )
    return {"matched": result.matched_count, "modified": result.modified_count, "upserted_id": str(result.upserted_id)}


def get_session(session_id: str) -> dict[str, Any] | None:
    db = get_database()
    return db[SESSION_COLLECTION].find_one({"session_id": session_id}, {"_id": False})


def get_analysis(session_id: str) -> dict[str, Any] | None:
    db = get_database()
    return db[ANALYSIS_COLLECTION].find_one({"session_id": session_id}, {"_id": False})


def list_sessions(limit: int = 20) -> list[dict[str, Any]]:
    db = get_database()
    cursor = (
        db[SESSION_COLLECTION]
        .find({}, {"_id": False})
        .sort([("fecha_inicio", -1), ("updated_at", -1)])
        .limit(limit)
    )
    return list(cursor)


def list_analysis_for_sessions(session_ids: list[str]) -> dict[str, dict[str, Any]]:
    if not session_ids:
        return {}
    db = get_database()
    cursor = db[ANALYSIS_COLLECTION].find({"session_id": {"$in": session_ids}}, {"_id": False})
    return {item.get("session_id", ""): item for item in cursor}


def build_session_document(metadata_path: Path | str) -> dict[str, Any]:
    metadata_path = Path(metadata_path)
    metadata = load_json(metadata_path, {})
    if not metadata:
        raise ValueError(f"No pude leer metadata: {metadata_path}")
    return {
        **metadata,
        "metadata_path": str(metadata_path),
        "local_source": "metadata.json",
    }


def build_analysis_document(session_id: str, analysis_path: Path | str) -> dict[str, Any]:
    analysis_path = Path(analysis_path)
    timeline_path = analysis_path / "timeline.json"
    summary_path = analysis_path / "summary.json"
    return {
        "session_id": session_id,
        "analysis_path": str(analysis_path),
        "timeline_path": str(timeline_path),
        "summary_json_path": str(summary_path),
        "summary_txt_path": str(analysis_path / "summary.txt"),
        "timeline": load_json(timeline_path, []),
        "summary": load_json(summary_path, {}),
        "local_source": "timeline.json/summary.json",
    }


def validate_connection() -> dict[str, Any]:
    client = get_client()
    db = get_database(client)
    client.admin.command("ping")
    ensure_indexes(db)
    return {
        "ok": True,
        "database": db.name,
        "collections": [SESSION_COLLECTION, ANALYSIS_COLLECTION],
    }
