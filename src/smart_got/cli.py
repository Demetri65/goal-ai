from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from smart_got.engine import (
    apply_baseline,
    build_context,
    decompose_node,
    init_graph,
    layer_children,
    layer_is_complete,
    plan_node,
    status_summary,
)
from smart_got.llm import MockProvider, get_provider
from smart_got.models import BaselineQA, NodeStatus
from smart_got.store import load_graph, save_graph

DEFAULT_GRAPH_PATH = "out/graph.json"


def _print_json(payload: object) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def _prompt_overwrite_or_continue(path: Path, existing_goal: str, requested_goal: str) -> str:
    prompt = (
        f"Graph already exists at '{path}' with root goal '{existing_goal}'.\n"
        f"Requested goal: '{requested_goal}'.\n"
        "Type 'c' to continue existing graph or 'o' to overwrite: "
    )
    while True:
        choice = input(prompt).strip().lower()
        if choice in {"c", "continue"}:
            return "continue"
        if choice in {"o", "overwrite"}:
            return "overwrite"
        print("Please type 'c' or 'o'.")


def _load_or_init_run_graph(goal: str, path: Path):
    if not path.exists():
        return init_graph(goal), True
    graph = load_graph(path)
    choice = _prompt_overwrite_or_continue(path, graph.nodes[graph.root_id].title, goal)
    if choice == "overwrite":
        return init_graph(goal), True
    return graph, False


def _child_bounds(target: int, tolerance: int) -> tuple[int, int]:
    bounded_target = max(1, target)
    bounded_tolerance = max(0, tolerance)
    min_children = max(1, bounded_target - bounded_tolerance)
    max_children = max(min_children, bounded_target + bounded_tolerance)
    return min_children, max_children


def _nearest_due(node) -> str:
    if node.plan is None:
        return "TBD"
    due_values = [
        task.due.strip()
        for task in node.plan.tasks
        if task.due and task.due.strip() and task.due.strip().upper() != "TBD"
    ]
    if not due_values:
        return "TBD"

    dated: list[tuple[datetime, str]] = []
    for item in due_values:
        try:
            dated.append((datetime.fromisoformat(item.replace("Z", "+00:00")), item))
        except ValueError:
            continue
    if dated:
        return min(dated, key=lambda x: x[0])[1]
    return sorted(due_values)[0]


def _print_layer_summary(graph, parent_id: str, as_json: bool) -> None:
    parent = graph.nodes[parent_id]
    rows = []
    for child_id in layer_children(graph, parent_id):
        node = graph.nodes[child_id]
        task_count = len(node.plan.tasks) if node.plan else 0
        rows.append(
            {
                "id": node.id,
                "workstream": node.workstream,
                "title": node.title,
                "tasks": task_count,
                "nearest_due": _nearest_due(node),
            }
        )

    if as_json:
        _print_json({"parent_id": parent_id, "parent_title": parent.title, "children": rows})
        return

    print(f"\nLayer Complete: {parent.title} ({parent.id})")
    for row in rows:
        print(
            f"- {row['id']} | {row['workstream']} | {row['title']} | "
            f"tasks:{row['tasks']} | due:{row['nearest_due']}"
        )


def _print_proposed_layer(graph, parent_id: str, as_json: bool) -> None:
    parent = graph.nodes[parent_id]
    rows = []
    for child_id in layer_children(graph, parent_id):
        node = graph.nodes[child_id]
        rows.append(
            {
                "id": node.id,
                "workstream": node.workstream,
                "title": node.title,
                "status": node.status,
            }
        )

    if as_json:
        _print_json(
            {
                "phase": "proposed_layer",
                "parent_id": parent_id,
                "parent_title": parent.title,
                "children": rows,
            }
        )
        return

    print(f"\nProposed Layer: {parent.title} ({parent.id})")
    for row in rows:
        print(
            f"- {row['id']} | {row['workstream']} | {row['title']} | status:{row['status']}"
        )


def _ask_baseline(question_text: str) -> str:
    return input(f"{question_text}\n> ").strip()


def _confirm_baseline_layer(graph, parent_id: str) -> bool:
    parent = graph.nodes[parent_id]
    prompt = (
        f"Run baseline Q&A for all nodes in layer under '{parent.title}' ({parent.id})? [y/N]: "
    )
    while True:
        choice = input(prompt).strip().lower()
        if choice in {"y", "yes"}:
            return True
        if choice in {"", "n", "no"}:
            return False
        print("Please type 'y' or 'n'.")


def _collect_layer_baseline_answers(graph, parent_id: str, provider) -> list[BaselineQA]:
    parent = graph.nodes[parent_id]
    context = build_context(graph, parent_id)
    questions = provider.baseline_questions(parent, context)
    print(f"\nLayer Baseline Interview: {parent.title} ({parent.id})")
    answers: list[BaselineQA] = []
    for question in questions:
        answers.append(
            BaselineQA(
                id=question.id,
                question=question.question,
                answer=_ask_baseline(question.question),
                category=question.category,
            )
        )
    return answers


def _map_layer_answers_to_node(
    layer_answers: list[BaselineQA],
    node_questions,
) -> list[BaselineQA]:
    by_id = {item.id: item.answer for item in layer_answers if item.id and item.answer.strip()}
    by_category = {
        item.category: item.answer
        for item in layer_answers
        if item.category and item.answer.strip()
    }
    return [
        BaselineQA(
            id=question.id,
            question=question.question,
            answer=by_id.get(question.id, by_category.get(question.category, "")),
            category=question.category,
        )
        for question in node_questions
    ]


def _plan_node_with_fallback(graph, node_id: str, provider, as_json: bool):
    try:
        return plan_node(graph, node_id, provider)
    except Exception as exc:  # pragma: no cover - hard to deterministically force API failures
        if as_json:
            _print_json(
                {
                    "node_id": node_id,
                    "warning": "plan_generation_failed_using_fallback",
                    "error": str(exc),
                }
            )
        else:
            print(
                f"Plan generation failed for {node_id}; using mock fallback. "
                f"Reason: {exc}"
            )
        fallback = MockProvider()
        return plan_node(graph, node_id, fallback)


def _complete_layer(graph, parent_id: str, provider, graph_path: Path, as_json: bool):
    # Pass 1: baseline all draft nodes in the current layer.
    draft_ids = [
        child_id
        for child_id in layer_children(graph, parent_id)
        if graph.nodes[child_id].status == NodeStatus.DRAFT
    ]
    if draft_ids:
        layer_answers = _collect_layer_baseline_answers(graph, parent_id, provider)
        for child_id in draft_ids:
            node = graph.nodes.get(child_id)
            if node is None or node.status != NodeStatus.DRAFT:
                continue
            print(f"\nApplying Layer Baseline: {node.title} ({node.id})")
            context = build_context(graph, child_id)
            node_questions = provider.baseline_questions(node, context)
            qa_pairs = _map_layer_answers_to_node(layer_answers, node_questions)
            siblings = [
                sibling
                for sibling in graph.nodes.values()
                if sibling.parent_id == node.parent_id and sibling.id != node.id
            ]
            output = provider.baseline_apply(node, siblings, context, qa_pairs)
            graph = apply_baseline(
                graph,
                child_id,
                qa_pairs,
                smart_patch=output.smart_patch,
                baseline=output.baseline,
                layer_mutations=output.layer_mutations,
            )
            if output.layer_mutations:
                if as_json:
                    _print_json(
                        {
                            "node_id": child_id,
                            "applied_mutations_count": len(output.layer_mutations),
                        }
                    )
                else:
                    print(f"Applied mutations: {len(output.layer_mutations)}")

            if child_id in graph.nodes:
                graph = _plan_node_with_fallback(graph, child_id, provider, as_json)
            save_graph(graph, graph_path)

    # Pass 2: plan any previously-baselined nodes that still lack plans.
    while not layer_is_complete(graph, parent_id):
        progressed = False
        for child_id in list(layer_children(graph, parent_id)):
            node = graph.nodes.get(child_id)
            if node is None or node.status == NodeStatus.PLANNED:
                continue
            if child_id in graph.nodes:
                graph = _plan_node_with_fallback(graph, child_id, provider, as_json)
            save_graph(graph, graph_path)
            progressed = True
        if not progressed:
            break
    return graph


def _ensure_children(graph, parent_id: str, provider, target: int, tolerance: int):
    child_ids = layer_children(graph, parent_id)
    if child_ids:
        return graph, child_ids, False, True
    parent = graph.nodes[parent_id]
    while True:
        choice = input(
            f"No children under '{parent.title}' ({parent.id}). Decompose this node now? [y/N]: "
        ).strip().lower()
        if choice in {"y", "yes"}:
            break
        if choice in {"", "n", "no"}:
            return graph, [], False, False
        print("Please type 'y' or 'n'.")
    min_children, max_children = _child_bounds(target, tolerance)
    graph, child_ids = decompose_node(
        graph,
        parent_id,
        provider,
        target_children=max(1, target),
        min_children=min_children,
        max_children=max_children,
    )
    return graph, child_ids, True, True


def _select_next_focus(graph, parent_id: str) -> str | None:
    valid_ids = set(layer_children(graph, parent_id))
    while True:
        choice = input("Pick a node id to decompose deeper, or 'q' to quit: ").strip()
        if choice.lower() in {"q", "quit", "exit"}:
            return None
        if choice in valid_ids:
            return choice
        print("Invalid node id. Choose one from the current layer or 'q'.")


def _confirm_decompose(graph, node_id: str) -> bool:
    node = graph.nodes[node_id]
    if node.status != NodeStatus.PLANNED:
        print(
            f"Node '{node.title}' ({node.id}) is not planned yet. "
            "Run baseline + plan for this layer before decomposing deeper."
        )
        return False
    if node.children_ids:
        return True
    prompt = f"Decompose '{node.title}' ({node.id}) into the next layer? [y/N]: "
    while True:
        choice = input(prompt).strip().lower()
        if choice in {"y", "yes"}:
            return True
        if choice in {"", "n", "no"}:
            return False
        print("Please type 'y' or 'n'.")


def _handle_run(args: argparse.Namespace) -> None:
    graph_path = Path(args.graph)
    provider = get_provider()
    graph, is_new = _load_or_init_run_graph(args.goal, graph_path)

    if is_new:
        graph.focus_parent_id = graph.root_id
        graph.active_layer = 1
        save_graph(graph, graph_path)

    while True:
        parent_id = graph.focus_parent_id or graph.root_id
        if parent_id not in graph.nodes:
            parent_id = graph.root_id
            graph.focus_parent_id = parent_id
        graph, _, decomposed_now, requested = _ensure_children(
            graph,
            parent_id,
            provider,
            target=args.target_children,
            tolerance=args.tolerance,
        )
        save_graph(graph, graph_path)
        if not requested:
            if args.json:
                _print_json(
                    {
                        "graph": str(graph_path),
                        "action": "decompose_skipped",
                        "focus_parent_id": parent_id,
                    }
                )
            else:
                print("Decomposition skipped. Exiting without baseline/planning this layer.")
            return

        pending_children = [
            child_id
            for child_id in layer_children(graph, parent_id)
            if graph.nodes[child_id].status != NodeStatus.PLANNED
        ]
        if decomposed_now or pending_children:
            _print_proposed_layer(graph, parent_id, as_json=args.json)

        if pending_children:
            if _confirm_baseline_layer(graph, parent_id):
                graph = _complete_layer(
                    graph,
                    parent_id,
                    provider,
                    graph_path,
                    as_json=args.json,
                )
            elif not args.json:
                print("Skipped baseline/planning for this layer.")
        _print_layer_summary(graph, parent_id, as_json=args.json)

        while True:
            selected = _select_next_focus(graph, parent_id)
            if selected is None:
                if args.json:
                    _print_json({"graph": str(graph_path), **status_summary(graph)})
                else:
                    print(f"Saved graph to {graph_path}")
                return
            if _confirm_decompose(graph, selected):
                graph.focus_parent_id = selected
                graph.active_layer += 1
                save_graph(graph, graph_path)
                break
            if args.json:
                _print_json({"skipped_node": selected, "action": "decompose_cancelled"})
            else:
                print(f"Skipped decomposition for {selected}. Choose another node or quit.")


def _handle_status(args: argparse.Namespace) -> None:
    graph_path = Path(args.graph)
    graph = load_graph(graph_path)
    summary = status_summary(graph)
    if args.json:
        _print_json(summary)
        return

    root = graph.nodes[graph.root_id]
    print(f"Graph: {graph_path}")
    print(f"Root goal: {root.title}")
    print(f"Focus parent: {summary['focus_parent_id']}")
    print(f"Active layer: {summary['active_layer']}")
    print("Layers:")
    for layer, count in summary["layers"].items():
        baselined = summary["baselined"].get(layer, 0)
        planned = summary["planned"].get(layer, 0)
        print(f"- {layer}: total={count}, baselined={baselined}, planned={planned}")


def _handle_show(args: argparse.Namespace) -> None:
    graph_path = Path(args.graph)
    graph = load_graph(graph_path)
    node = graph.nodes.get(args.node_id)
    if node is None:
        raise KeyError(f"Node not found: {args.node_id}")

    if args.json:
        _print_json(node.model_dump(mode="json"))
        return

    print(f"Node: {node.id}")
    print(f"Title: {node.title}")
    print(f"Workstream: {node.workstream}")
    print(f"Status: {node.status}")
    print(f"Layer: {node.layer}")
    print(f"Parent: {node.parent_id or '-'}")
    print(f"Children: {', '.join(node.children_ids) if node.children_ids else '-'}")
    print("SMART:")
    print(f"- Specific: {node.smart.specific or '-'}")
    print(f"- Measurable: {node.smart.measurable or '-'}")
    print(f"- Achievable: {node.smart.achievable or '-'}")
    print(f"- Relevant: {node.smart.relevant or '-'}")
    print(f"- TimeBound: {node.smart.time_bound or '-'}")
    qa_count = len(node.baseline.qa) if node.baseline else 0
    task_count = len(node.plan.tasks) if node.plan else 0
    print(f"Baseline QA count: {qa_count}")
    print(f"Plan tasks: {task_count}")


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
    run_parser.add_argument(
        "--json",
        action="store_true",
        help="print machine-readable JSON for summaries",
    )
    run_parser.set_defaults(func=_handle_run)

    status_parser = subparsers.add_parser("status", help="show graph status")
    status_parser.add_argument(
        "--graph",
        default=DEFAULT_GRAPH_PATH,
        help=f"graph JSON path (default: {DEFAULT_GRAPH_PATH})",
    )
    status_parser.add_argument(
        "--json",
        action="store_true",
        help="print machine-readable JSON",
    )
    status_parser.set_defaults(func=_handle_status)

    show_parser = subparsers.add_parser("show", help="show a single node")
    show_parser.add_argument("node_id", help="node id to display")
    show_parser.add_argument(
        "--graph",
        default=DEFAULT_GRAPH_PATH,
        help=f"graph JSON path (default: {DEFAULT_GRAPH_PATH})",
    )
    show_parser.add_argument(
        "--json",
        action="store_true",
        help="print machine-readable JSON",
    )
    show_parser.set_defaults(func=_handle_show)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
