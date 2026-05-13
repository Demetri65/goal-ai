from __future__ import annotations

import json
from pathlib import Path

from smart_got.blob_storage import blob_enabled, get_blob_text, put_blob_text
from smart_got.models import Graph


def graph_exists(path: str | Path) -> bool:
    if blob_enabled():
        return get_blob_text("graphs", path) is not None
    return Path(path).exists()


def load_graph(path: str | Path) -> Graph:
    if blob_enabled():
        data = get_blob_text("graphs", path)
        if data is None:
            raise FileNotFoundError(path)
        return Graph.model_validate_json(data)
    path = Path(path)
    data = json.loads(path.read_text())
    return Graph.model_validate(data)


def save_graph(graph: Graph, path: str | Path) -> None:
    data = graph.model_dump(mode="json")
    payload = json.dumps(data, indent=2, sort_keys=True)
    if blob_enabled():
        put_blob_text("graphs", path, payload)
        return
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(payload)
    tmp_path.replace(path)
