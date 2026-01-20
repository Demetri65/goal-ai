from __future__ import annotations

import json
import os
import sys
from typing import Any

_ALLOWED_MODES = {"off", "openai", "mock"}
_CLIENT = None


def llm_enabled() -> bool:
    return _llm_mode() != "off"


def generate_text(
    messages: list[dict[str, str]],
    *,
    model: str | None = None,
    max_output_tokens: int | None = None,
) -> str:
    mode = _llm_mode()
    if mode == "off":
        raise RuntimeError("LLM mode is off. Set SMARTGOT_LLM_MODE=mock or openai.")
    if mode == "mock":
        return "mock response"
    return _openai_text(messages, model=model, max_output_tokens=max_output_tokens)


def generate_json(
    messages: list[dict[str, str]],
    schema: dict[str, Any],
    name: str,
    *,
    model: str | None = None,
    strict: bool = True,
    max_output_tokens: int | None = None,
) -> dict[str, Any]:
    mode = _llm_mode()
    if mode == "off":
        raise RuntimeError("LLM mode is off. Set SMARTGOT_LLM_MODE=mock or openai.")
    if mode == "mock":
        return _mock_json(name)
    output_text = _openai_text(
        messages,
        model=model,
        max_output_tokens=max_output_tokens,
        text_format={"type": "json_schema", "name": name, "schema": schema, "strict": strict},
    )
    if _llm_debug_enabled():
        print(f"[llm] name={name} model={_model_name(model)} output={_truncate(output_text)}", file=sys.stderr)
    try:
        return json.loads(output_text)
    except json.JSONDecodeError as exc:
        msg = f"Failed to parse JSON from OpenAI response: {exc}"
        if _llm_debug_enabled():
            msg += f"\nRaw output: {output_text}"
        raise RuntimeError(msg) from exc


def _llm_mode() -> str:
    mode = os.getenv("SMARTGOT_LLM_MODE", "off").strip().lower()
    if mode not in _ALLOWED_MODES:
        allowed = ", ".join(sorted(_ALLOWED_MODES))
        raise RuntimeError(f"Unsupported SMARTGOT_LLM_MODE={mode!r}. Use one of: {allowed}.")
    return mode


def _llm_debug_enabled() -> bool:
    return _env_truthy(os.getenv("SMARTGOT_LLM_DEBUG"))


def _truncate(text: str, limit: int = 2000) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "...(truncated)"


def _store_enabled() -> bool:
    return _env_truthy(os.getenv("SMARTGOT_STORE", "false"))


def _model_name(model: str | None) -> str:
    return model or os.getenv("SMARTGOT_MODEL", "gpt-5-mini")


def _env_truthy(value: str | None) -> bool:
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _openai_text(
    messages: list[dict[str, str]],
    *,
    model: str | None,
    max_output_tokens: int | None,
    text_format: dict[str, Any] | None = None,
) -> str:
    client = _openai_client()
    payload: dict[str, Any] = {
        "model": _model_name(model),
        "input": messages,
        "store": _store_enabled(),
    }
    if max_output_tokens is not None:
        payload["max_output_tokens"] = max_output_tokens
    if text_format is not None:
        payload["text"] = {"format": text_format}
    try:
        response = client.responses.create(**payload)
    except Exception as exc:
        msg = "OpenAI request failed. Check OPENAI_API_KEY and network access."
        if _llm_debug_enabled():
            msg = f"{msg} Error: {exc}"
        raise RuntimeError(msg) from exc
    output_text = getattr(response, "output_text", None)
    if not output_text:
        raise RuntimeError("OpenAI response did not include output_text.")
    return output_text


def _openai_client():
    global _CLIENT
    if _CLIENT is not None:
        return _CLIENT
    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY is not set. Export it to use SMARTGOT_LLM_MODE=openai.")
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError('OpenAI SDK not installed. Install with: pip install -e ".[llm]"') from exc
    _CLIENT = OpenAI()
    return _CLIENT


def _mock_json(name: str) -> dict[str, Any]:
    if name == "stage1_output":
        return {
            "goal_text": "Complete the prototype with a working SMART-GoT scaffold.",
            "rationale": "A runnable prototype makes the research concrete and testable.",
            "metric": {
                "name": "prototype_complete",
                "unit": "percent",
                "method": "manual checklist",
                "target_value": 100,
            },
            "forcing_questions": [
                "What concrete deliverable shows completion?",
                "How will progress be measured week to week?",
                "Why does this matter now?",
            ],
        }
    if name == "stage2_baselines":
        return {
            "time_per_week_hours": "How many hours per week can you spend on implementation?",
            "hard_deadline": "Do you have a deadline for the first demo?",
            "key_constraints": "List any key constraints (time, money, access, health).",
            "extra": [
                "What is the current completion percentage (0-100)?",
            ],
        }
    if name == "stage1_subgoals":
        return {
            "subgoals": [
                "Define acceptance criteria for the prototype",
                "Identify missing components in the scaffold",
                "Build a minimal end-to-end demo",
                "Gather example data for evaluation",
                "Draft a short validation checklist",
                "Set a weekly review cadence",
                "List known risks and blockers",
            ]
        }
    if name == "stage2_refine":
        return {
            "goal_text": "Create a concise plan to organize a 10 km charity run, aligned with available time and constraints.",
            "subgoals": [
                {
                    "id": "goal.subgoal.init.define_acceptance_criteria_for_the_prototype",
                    "text": "Clarify success criteria and scope for the event",
                    "tasks": ["Define success metrics", "Confirm scope boundaries"],
                    "depends_on": [],
                },
                {
                    "id": "goal.subgoal.init.identify_missing_components_in_the_scaffold",
                    "text": "Confirm route and permitting requirements",
                    "tasks": ["Identify required permits", "Draft route approval checklist"],
                    "depends_on": [],
                },
                {
                    "id": "goal.subgoal.init.build_a_minimal_end_to_end_demo",
                    "text": "Set up registration and donation workflow",
                    "tasks": ["Choose a registration platform", "Define donation tracking"],
                    "depends_on": [],
                },
                {
                    "id": "goal.subgoal.init.gather_example_data_for_evaluation",
                    "text": "Plan volunteer roles and staffing needs",
                    "tasks": ["List volunteer roles", "Estimate volunteer headcount"],
                    "depends_on": [],
                },
                {
                    "id": "goal.subgoal.init.draft_a_short_validation_checklist",
                    "text": "Draft safety and medical plan outline",
                    "tasks": ["Identify medical coverage needs", "Outline emergency response steps"],
                    "depends_on": [],
                },
                {
                    "id": "goal.subgoal.init.set_a_weekly_review_cadence",
                    "text": "Create fundraising and sponsorship plan",
                    "tasks": ["Define sponsorship tiers", "Outline fundraising channels"],
                    "depends_on": [],
                },
                {
                    "id": "goal.subgoal.init.list_known_risks_and_blockers",
                    "text": "List risks and mitigation strategies",
                    "tasks": ["List top risks", "Draft mitigation actions"],
                    "depends_on": [],
                },
            ],
        }
    if name.startswith("stage3_plan_"):
        flavor = "aggressive" if "aggressive" in name else "conservative"
        time_bound_weeks = 4 if flavor == "aggressive" else 6
        steps = [
            "Confirm the SMART goal and metric definitions.",
            "Fill baseline values for time and current status.",
            "Schedule recurring work blocks to implement missing pieces.",
            "Ship a minimal end-to-end demo and iterate.",
        ]
        if_then = [
            "If a session starts late, then shorten scope and complete a tiny task.",
            "If progress stalls, then reduce the next milestone and keep momentum.",
        ]
        return {
            "time_bound_weeks": time_bound_weeks,
            "steps": steps,
            "if_then": if_then,
            "assumptions": [
                "Weekly time budget remains stable.",
                "Key dependencies are available when needed.",
            ],
        }
    raise RuntimeError(f"No mock output available for schema name {name!r}.")
