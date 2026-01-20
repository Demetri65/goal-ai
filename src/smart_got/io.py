from __future__ import annotations

import json
from pathlib import Path

from .schema import Graph


def load_graph(path: str | Path) -> Graph:
    p = Path(path)
    data = json.loads(p.read_text(encoding="utf-8"))
    return Graph.model_validate(data)


def save_graph(graph: Graph, path: str | Path) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = graph.model_dump(mode="json", exclude_none=True)
    p.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
