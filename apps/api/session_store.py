from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from apps.api.types import UISessionPayload, now_iso
from smart_got.blob_storage import blob_enabled, get_blob_text, put_blob_text

SESSION_DIR = Path("/tmp/smartgot/ui_sessions") if os.getenv("VERCEL") else Path("out/ui_sessions")


class UISessionRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str
    updated_at: str = Field(default_factory=now_iso)
    messages: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


def _safe_session_id(session_id: str) -> str:
    cleaned = "".join(ch for ch in session_id if ch.isalnum() or ch in {"-", "_"})
    if not cleaned:
        raise ValueError("session_id must contain at least one alphanumeric character")
    return cleaned


def _session_path(session_id: str) -> Path:
    safe_id = _safe_session_id(session_id)
    SESSION_DIR.mkdir(parents=True, exist_ok=True)
    return SESSION_DIR / f"{safe_id}.json"


def load_session(session_id: str) -> UISessionRecord:
    safe_id = _safe_session_id(session_id)
    if blob_enabled():
        data = get_blob_text("ui_sessions", f"{safe_id}.json")
        if data is None:
            return UISessionRecord(session_id=safe_id)
        return UISessionRecord.model_validate_json(data)
    path = _session_path(session_id)
    if not path.exists():
        return UISessionRecord(session_id=safe_id)
    data = json.loads(path.read_text())
    return UISessionRecord.model_validate(data)


def save_session(session_id: str, payload: UISessionPayload) -> UISessionRecord:
    safe_id = _safe_session_id(session_id)
    record = UISessionRecord(
        session_id=safe_id,
        updated_at=now_iso(),
        messages=payload.messages,
        metadata=payload.metadata,
    )
    if blob_enabled():
        put_blob_text("ui_sessions", f"{safe_id}.json", record.model_dump_json(indent=2))
        return record
    path = _session_path(safe_id)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(record.model_dump_json(indent=2))
    tmp.replace(path)
    return record
