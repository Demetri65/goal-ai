from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .io import load_graph, save_graph
from .interactive import InteractiveConfig, run_interactive_session
from .migrate import migrate_graph
from .render import render_bash_tree, render_summary
from .stages import StageError, answer_value, approve_gate, choose_plan, run_stage1, run_stage2, run_stage3, run_stage4


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="smartgot", description="SMART-GoT prototype CLI")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p1 = sub.add_parser("stage1", help="Stage 1: draft SMR graph")
    p1.add_argument("--intent", required=True)
    p1.add_argument("--rationale", default=None)
    p1.add_argument("--out", required=True)

    p_approve = sub.add_parser("approve", help="Approve a stage gate in a graph JSON")
    p_approve.add_argument("--graph", required=True)
    p_approve.add_argument("--stage", type=int, required=True)
    p_approve.add_argument("--note", default="")

    p_answer = sub.add_parser("answer", help="Set a baseline value in-place")
    p_answer.add_argument("--graph", required=True)
    p_answer.add_argument("--id", required=True)
    p_answer.add_argument("--value", required=True)

    p_choose = sub.add_parser("choose-plan", help="Choose a plan option in-place")
    p_choose.add_argument("--graph", required=True)
    p_choose.add_argument("--plan-id", required=True)

    p2 = sub.add_parser("stage2", help="Stage 2: add baseline questions + constraints")
    p2.add_argument("--graph", required=True)
    p2.add_argument("--out", required=True)

    p3 = sub.add_parser("stage3", help="Stage 3: generate plan options + scores")
    p3.add_argument("--graph", required=True)
    p3.add_argument("--out", required=True)

    p4 = sub.add_parser("checkin", help="Stage 4: check-in and adapt (toy)")
    p4.add_argument("--graph", required=True)
    p4.add_argument("--out", required=True)
    p4.add_argument("--progress", type=float, required=True)
    p4.add_argument("--friction", default="")
    p4.add_argument("--done", action="append", default=[], help="Completed goal id (repeatable or comma-separated)")
    p4.add_argument("--missed", action="append", default=[], help="Missed goal id (repeatable or comma-separated)")
    p4.add_argument("--reflection", default="", help="Reflection notes")
    p4.add_argument("--plan-add-step", action="append", default=[], help="Add a step to the chosen plan")
    p4.add_argument("--plan-remove-step", action="append", default=[], help="Remove a step from the chosen plan (exact match)")
    p4.add_argument("--plan-add-if-then", action="append", default=[], help="Add an if-then rule to the chosen plan")
    p4.add_argument("--time-bound-weeks", type=int, default=None, help="Override the chosen plan time bound")

    pm = sub.add_parser("migrate", help="Migrate legacy graph JSON to goal-only format")
    pm.add_argument("--graph", required=True)
    pm.add_argument("--out", required=True)

    pi = sub.add_parser("interactive", help="Run an interactive stage 1-4 session")
    pi.add_argument("--intent", required=True)
    pi.add_argument("--rationale", default=None)
    pi.add_argument("--out", required=True)
    pi.add_argument("--stage-dir", default=None, help="Optional directory to save stage1-4 JSON files")

    ps = sub.add_parser("summary", help="Print a human-readable summary of a graph")
    ps.add_argument("--graph", required=True)

    pv = sub.add_parser("validate", help="Validate that a graph JSON parses")
    pv.add_argument("--graph", required=True)

    args = parser.parse_args(argv)

    try:
        if args.cmd == "stage1":
            _require_openai_mode()
            g = run_stage1(intent=args.intent, rationale=args.rationale)
            save_graph(g, args.out)
            print(f"Wrote {args.out}")
            print("Goal tree:")
            print(render_bash_tree(g))
            print("Next: edit the JSON if needed, then approve stage 1 gate:")
            print(f"  smartgot approve --graph {args.out} --stage 1 --note \"ok\"")
            return 0

        if args.cmd == "approve":
            g = load_graph(args.graph)
            approve_gate(g, stage=args.stage, note=args.note)
            save_graph(g, args.graph)
            print(f"Approved stage {args.stage} in {args.graph}")
            return 0

        if args.cmd == "answer":
            g = load_graph(args.graph)
            answer_value(g, node_id=args.id, raw_value=args.value)
            save_graph(g, args.graph)
            print(f"Updated {args.id} in {args.graph}")
            return 0

        if args.cmd == "choose-plan":
            g = load_graph(args.graph)
            choose_plan(g, plan_id=args.plan_id)
            save_graph(g, args.graph)
            print(f"Chose {args.plan_id} in {args.graph}")
            return 0

        if args.cmd == "stage2":
            _require_openai_mode()
            g = load_graph(args.graph)
            g2 = run_stage2(g)
            save_graph(g2, args.out)
            print(f"Wrote {args.out}")
            print("Goal tree:")
            print(render_bash_tree(g2))
            print("Next: fill goal.v1.data.baseline.*.value fields, then approve stage 2 gate:")
            print(f"  smartgot approve --graph {args.out} --stage 2 --note \"baseline ok\"")
            return 0

        if args.cmd == "stage3":
            _require_openai_mode()
            g = load_graph(args.graph)
            g3 = run_stage3(g)
            save_graph(g3, args.out)
            print(f"Wrote {args.out}")
            print("Goal tree:")
            print(render_bash_tree(g3))
            print("Next: choose a plan, then approve stage 3 gate:")
            print(f"  smartgot choose-plan --graph {args.out} --plan-id goal.plan.option1")
            print(f"  smartgot approve --graph {args.out} --stage 3 --note \"plan chosen\"")
            return 0

        if args.cmd == "checkin":
            g = load_graph(args.graph)
            g4 = run_stage4(
                g,
                progress=float(args.progress),
                friction=args.friction,
                completed_goal_ids=_parse_csv_args(args.done),
                missed_goal_ids=_parse_csv_args(args.missed),
                reflection=args.reflection,
                plan_add_steps=_parse_csv_args(args.plan_add_step),
                plan_remove_steps=_parse_csv_args(args.plan_remove_step),
                plan_add_if_then=_parse_csv_args(args.plan_add_if_then),
                time_bound_weeks=args.time_bound_weeks,
            )
            save_graph(g4, args.out)
            print(f"Wrote {args.out}")
            print("Goal tree:")
            print(render_bash_tree(g4))
            return 0

        if args.cmd == "migrate":
            payload = json.loads(Path(args.graph).read_text(encoding="utf-8"))
            g = migrate_graph(payload)
            save_graph(g, args.out)
            print(f"Wrote {args.out}")
            return 0

        if args.cmd == "interactive":
            _require_openai_mode()
            stage_dir = Path(args.stage_dir) if args.stage_dir else None
            config = InteractiveConfig(
                intent=args.intent,
                rationale=args.rationale,
                out=Path(args.out),
                stage_dir=stage_dir,
            )
            _ = run_interactive_session(config)
            print(f"Wrote {args.out}")
            return 0

        if args.cmd == "summary":
            g = load_graph(args.graph)
            print(render_summary(g))
            return 0

        if args.cmd == "validate":
            _ = load_graph(args.graph)
            print("OK")
            return 0

    except StageError as e:
        print(f"StageError: {e}", file=sys.stderr)
        return 2
    except RuntimeError as e:
        print(f"RuntimeError: {e}", file=sys.stderr)
        return 2

    return 1


def _require_openai_mode() -> None:
    mode = os.getenv("SMARTGOT_LLM_MODE", "off").strip().lower()
    key_set = bool(os.getenv("OPENAI_API_KEY"))
    if mode != "openai":
        raise RuntimeError(
            "CLI requires SMARTGOT_LLM_MODE=openai (mock is test-only). "
            f"Current mode={mode!r}, OPENAI_API_KEY set={key_set}."
        )
    if not key_set:
        raise RuntimeError("OPENAI_API_KEY is not set. Export it or load it from .env before running the CLI.")


def _parse_csv_args(values: list[str]) -> list[str]:
    out: list[str] = []
    for raw in values:
        if not raw:
            continue
        for item in raw.split(","):
            item = item.strip()
            if item and item not in out:
                out.append(item)
    return out


if __name__ == "__main__":
    raise SystemExit(main())
