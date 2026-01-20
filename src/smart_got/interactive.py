from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path

from .io import save_graph
from .ops import refine_after_baseline
from .render import render_bash_tree, render_summary
from .schema import Graph, Node
from .stages import answer_value, approve_gate, choose_plan, run_stage1, run_stage2, run_stage3, run_stage4


@dataclass(frozen=True)
class InteractiveConfig:
    intent: str
    out: Path
    rationale: str | None = None
    stage_dir: Path | None = None
    show_summary: bool = True


def run_interactive_session(config: InteractiveConfig) -> Graph:
    if _llm_debug_enabled():
        print("LLM debug output is enabled (SMARTGOT_LLM_DEBUG=1).")
    _print_banner("Stage 1: draft goal + metric (LLM if enabled)")
    g1 = run_stage1(intent=config.intent, rationale=config.rationale)
    approve_gate(g1, 1, note="interactive ok")
    _maybe_summary(g1, config.show_summary)
    _print_diagram(g1)
    _save_stage(g1, config.stage_dir, "stage1.json")

    _print_banner("Stage 2: baseline questions")
    g2 = run_stage2(g1)
    _prompt_baselines(g2)
    _print_banner("Refine goal + subgoals from baseline")
    refine_after_baseline(g2)
    approve_gate(g2, 2, note="baseline ok")
    _maybe_summary(g2, config.show_summary)
    _print_diagram(g2)
    _save_stage(g2, config.stage_dir, "stage2.json")

    _print_banner("Stage 3: plan options + choose plan")
    g3 = run_stage3(g2)
    _choose_plan_interactive(g3)
    approve_gate(g3, 3, note="plan chosen")
    _maybe_summary(g3, config.show_summary)
    _print_diagram(g3)
    _save_stage(g3, config.stage_dir, "stage3.json")

    _print_banner("Stage 4: check-in / adapt")
    progress = _prompt_progress()
    friction = input("Friction notes (optional): ").strip()
    done_raw = input("Completed goal ids (comma-separated, optional): ").strip()
    missed_raw = input("Missed goal ids (comma-separated, optional): ").strip()
    reflection = input("Reflection (optional): ").strip()
    completed = _parse_id_list(done_raw)
    missed = _parse_id_list(missed_raw)
    g4 = run_stage4(
        g3,
        progress=progress,
        friction=friction,
        completed_goal_ids=completed,
        missed_goal_ids=missed,
        reflection=reflection,
    )
    _maybe_summary(g4, config.show_summary)
    _print_diagram(g4)
    _save_stage(g4, config.stage_dir, "stage4.json")

    save_graph(g4, config.out)
    return g4


def _print_banner(text: str) -> None:
    print("")
    print(text)
    print("-" * len(text))


def _maybe_summary(graph: Graph, show: bool) -> None:
    if show:
        print(render_summary(graph))


def _save_stage(graph: Graph, stage_dir: Path | None, name: str) -> None:
    if stage_dir is None:
        return
    stage_dir.mkdir(parents=True, exist_ok=True)
    save_graph(graph, stage_dir / name)


def _prompt_baselines(graph: Graph) -> None:
    goal = graph.root_goal()
    if goal is None:
        raise RuntimeError("goal.v1 not found in graph.")
    baseline = goal.data.baseline
    if not baseline:
        print("No baseline questions available.")
        return

    keys = _baseline_key_order(baseline)
    total = len(keys)
    while True:
        for idx, key in enumerate(keys, 1):
            entry = baseline[key]
            current = entry.value
            current_text = f" (current: {current!r})" if current not in (None, "") else ""
            prompt = f"[{idx}/{total}] {entry.question}{current_text}\n> "
            raw = input(prompt).strip()
            if raw == "":
                continue
            answer_value(graph, f"baseline.{key}", raw)
        if _count_answered(baseline) > 0:
            break
        print("At least one baseline value is required before stage 3.")


def _llm_debug_enabled() -> bool:
    value = os.getenv("SMARTGOT_LLM_DEBUG", "").strip().lower()
    return value in {"1", "true", "yes", "on"}


def _print_diagram(graph: Graph) -> None:
    print("Goal tree:")
    print(render_bash_tree(graph))


def _baseline_key_order(baseline: dict[str, object]) -> list[str]:
    base = ["time_per_week_hours", "hard_deadline", "key_constraints"]
    ordered = [k for k in base if k in baseline]
    extras = sorted(k for k in baseline.keys() if k not in ordered)
    return ordered + extras


def _count_answered(baseline: dict[str, object]) -> int:
    count = 0
    for entry in baseline.values():
        value = getattr(entry, "value", None)
        if value not in (None, ""):
            count += 1
    return count


def _choose_plan_interactive(graph: Graph) -> None:
    goal = graph.root_goal()
    if goal is None:
        raise RuntimeError("goal.v1 not found in graph.")

    plans = [n for n in graph.nodes.values() if _is_plan_goal(n)]
    if not plans:
        raise RuntimeError("No plan options found.")
    plans = sorted(plans, key=lambda n: n.id)

    default = goal.data.decision.chosen_plan_id
    if default not in {p.id for p in plans}:
        default = plans[0].id

    while True:
        print("Plan options:")
        for idx, plan in enumerate(plans, 1):
            score = plan.data.eval.score
            weeks = plan.data.plan.time_bound_weeks
            steps = len(plan.data.plan.steps)
            score_text = f" score={score:.2f}" if score is not None else ""
            print(f"  {idx}) {plan.id} weeks={weeks} steps={steps}{score_text}")
        raw = input(f"Choose plan (id or number) [default {default}]: ").strip()
        if raw == "" and default:
            choose_plan(graph, plan_id=default)
            return
        if raw.isdigit():
            idx = int(raw)
            if 1 <= idx <= len(plans):
                choose_plan(graph, plan_id=plans[idx - 1].id)
                return
            print("Invalid selection.")
            continue
        if raw in {p.id for p in plans}:
            choose_plan(graph, plan_id=raw)
            return
        print("Invalid selection.")


def _prompt_progress() -> float:
    while True:
        raw = input("Progress (0.0-1.0): ").strip()
        try:
            value = float(raw)
        except ValueError:
            print("Enter a number between 0 and 1.")
            continue
        if 0.0 <= value <= 1.0:
            return value
        print("Enter a number between 0 and 1.")


def _is_plan_goal(node: Node) -> bool:
    plan = node.data.plan
    return bool(plan.steps or plan.if_then or plan.time_bound_weeks is not None or plan.assumptions or plan.milestones)


def _parse_id_list(raw: str) -> list[str]:
    if not raw:
        return []
    return [item.strip() for item in raw.split(",") if item.strip()]
