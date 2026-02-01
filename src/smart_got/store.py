from __future__ import annotations

import json
from pathlib import Path

from smart_got.models import Graph


def load_graph(path: str | Path) -> Graph:
    path = Path(path)
    data = json.loads(path.read_text())
    return Graph.model_validate(data)


def save_graph(graph: Graph, path: str | Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = graph.model_dump(mode="json")
    payload = json.dumps(data, indent=2, sort_keys=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(payload)
    tmp_path.replace(path)
