from __future__ import annotations

import argparse
import json
from pathlib import Path

from smart_got.engine import apply_baseline, decompose_node, init_graph, status_summary
from smart_got.llm import get_provider
from smart_got.models import BaselineQA, NodeStatus, SMARTFields
from smart_got.store import load_graph, save_graph

DEFAULT_GRAPH_PATH = "graph.json"


def _print_json(payload: object) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def _load_or_init_graph(goal: str, path: Path):
    if path.exists():
        return load_graph(path)
    graph = init_graph(goal)
    save_graph(graph, path)
    return graph


def _prompt_smart_patch(current: SMARTFields) -> SMARTFields:
    print("Update SMART fields (enter to keep current values).")

    def ask(label: str, value: str) -> str:
        display = value if value else "-"
        response = input(f"{label} [{display}]: ").strip()
        return response

    return SMARTFields(
        specific=ask("Specific", current.specific),
        measurable=ask("Measurable", current.measurable),
        achievable=ask("Achievable", current.achievable),
        relevant=ask("Relevant", current.relevant),
        time_bound=ask("Time-bound", current.time_bound),
    )


def _run_baseline(graph, node_id: str, graph_path: Path, provider) -> object:
    node = graph.nodes[node_id]
    root = graph.nodes[graph.root_id]
    parent = graph.nodes.get(node.parent_id) if node.parent_id else None
    questions = provider.baseline_questions(root, parent, node)

    print(f"\nBaseline Q&A: {node.title} (layer {node.layer})")
    qa_pairs = []
    for question in questions:
        answer = input(f"{question}\n> ").strip()
        qa_pairs.append(BaselineQA(question=question, answer=answer))

    smart_patch = _prompt_smart_patch(node.smart)
    graph = apply_baseline(graph, node_id, qa_pairs, smart_patch)
    save_graph(graph, graph_path)
    return graph


def _summarize_children(graph, child_ids: list[str]) -> None:
    summaries = []
    for child_id in child_ids:
        node = graph.nodes[child_id]
        summaries.append(
            {
                "id": node.id,
                "title": node.title,
                "layer": node.layer,
                "parent_id": node.parent_id,
                "status": node.status,
                "smart": node.smart.model_dump(mode="json"),
            }
        )
    _print_json({"workstreams": summaries})


def _handle_run(args: argparse.Namespace) -> None:
    graph_path = Path(args.graph)
    provider = get_provider()
    graph = _load_or_init_graph(args.goal, graph_path)

    root = graph.nodes[graph.root_id]
    if root.status != NodeStatus.BASELINED:
        graph = _run_baseline(graph, root.id, graph_path, provider)
        root = graph.nodes[graph.root_id]

    if not root.children_ids:
        target = max(1, args.target_children)
        tolerance = max(0, args.tolerance)
        min_children = max(1, target - tolerance)
        max_children = max(min_children, target + tolerance)
        graph, child_ids = decompose_node(
            graph,
            root.id,
            provider,
            target_children=target,
            min_children=min_children,
            max_children=max_children,
        )
        save_graph(graph, graph_path)
        _summarize_children(graph, child_ids)

    for child_id in list(root.children_ids):
        node = graph.nodes[child_id]
        if node.status != NodeStatus.BASELINED:
            graph = _run_baseline(graph, child_id, graph_path, provider)

    _print_json({"graph": str(graph_path), **status_summary(graph)})


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="smartgot", description="Lean SMART-GoT CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="interactive goal workflow")
    run_parser.add_argument("--goal", required=True, help="root goal title")
    run_parser.add_argument(
        "--graph",
        default=DEFAULT_GRAPH_PATH,
        help=f"graph JSON path (default: {DEFAULT_GRAPH_PATH})",
    )
    run_parser.add_argument(
        "--target-children",
        type=int,
        default=7,
        help="target number of workstreams (default: 7)",
    )
    run_parser.add_argument(
        "--tolerance",
        type=int,
        default=2,
        help="plus/minus range for workstream count (default: 2)",
    )
    run_parser.set_defaults(func=_handle_run)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
