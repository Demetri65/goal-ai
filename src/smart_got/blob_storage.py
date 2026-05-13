from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any


def blob_enabled() -> bool:
    return bool(os.getenv("BLOB_READ_WRITE_TOKEN", "").strip())


def _blob_pathname(namespace: str, path: str | Path) -> str:
    raw = str(path).replace("\\", "/").strip()
    for prefix in ("/tmp/", f"{Path.cwd()}/"):
        if raw.startswith(prefix):
            raw = raw[len(prefix) :]
            break
    raw = raw.strip("/") or "default"
    safe = re.sub(r"[^A-Za-z0-9._/-]+", "_", raw)
    app_prefix = os.getenv("SMARTGOT_BLOB_PREFIX", "smartgot").strip().strip("/") or "smartgot"
    return f"{app_prefix}/{namespace}/{safe}"


def _blob_client() -> Any:
    try:
        from vercel.blob import BlobClient
    except ImportError as exc:  # pragma: no cover - only exercised when Blob is configured
        raise RuntimeError(
            "Vercel Blob storage is configured, but the `vercel` Python package is not installed."
        ) from exc
    return BlobClient()


def get_blob_text(namespace: str, path: str | Path) -> str | None:
    try:
        from vercel.blob.errors import BlobNotFoundError
    except ImportError:  # pragma: no cover - covered by _blob_client import guard
        BlobNotFoundError = FileNotFoundError  # type: ignore[assignment]

    try:
        result = _blob_client().get(_blob_pathname(namespace, path), access="private")
    except BlobNotFoundError:
        return None
    stream = getattr(result, "stream", None)
    if stream is None:
        return None
    chunks = [chunk for chunk in stream if chunk]
    if not chunks:
        return ""
    return b"".join(chunks).decode("utf-8")


def put_blob_text(namespace: str, path: str | Path, text: str) -> None:
    _blob_client().put(
        _blob_pathname(namespace, path),
        text.encode("utf-8"),
        access="private",
        content_type="application/json",
        overwrite=True,
    )
