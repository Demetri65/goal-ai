from types import SimpleNamespace

import pytest

from smart_got import engine
from smart_got.llm import (
    MockProvider,
    OpenAIProvider,
    get_provider,
)
from smart_got.models import BaselineQuestion, ChildDraft, NodePlan, PlanOutput, SMARTFields, Task


def test_mock_baseline_questions_focus_on_achievable_and_timebound():
    provider = MockProvider()
    graph = engine.init_graph("Ship an onboarding revamp")
    node = graph.nodes[graph.root_id]
    context = engine.provider_context(graph, node.id)

    questions = provider.baseline_questions(node, context)
    categories = {item.category for item in questions}

    assert "achievable" in categories
    assert "time_bound" in categories
    assert "constraints" in categories
    assert "resources" in categories
    assert all(item.guide for item in questions)
    assert all(item.research_basis for item in questions)


def test_mock_plan_output_has_due_and_relative_timing():
    provider = MockProvider()
    graph = engine.init_graph("Improve retention")
    node = graph.nodes[graph.root_id]
    context = engine.provider_context(graph, node.id)

    output = provider.plan(node, context)

    assert 3 <= len(output.plan.tasks) <= 6
    for task in output.plan.tasks:
        assert task.relative_timing
        assert task.due


def test_get_provider_prefers_openai_when_key_present(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.delenv("SMARTGOT_LLM_MODE", raising=False)
    assert isinstance(get_provider(), OpenAIProvider)


def test_get_provider_requires_openai_token_when_not_in_mock_mode(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("SMARTGOT_LLM_MODE", raising=False)

    with pytest.raises(RuntimeError, match="OPENAI_API_KEY is not configured"):
        get_provider()


def test_get_provider_allows_explicit_mock_mode(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("SMARTGOT_LLM_MODE", "mock")
    assert isinstance(get_provider(), MockProvider)


def test_openai_plan_ensures_due_fields_without_network(monkeypatch):
    provider = OpenAIProvider("test-key")
    graph = engine.init_graph("Improve retention")
    node = graph.nodes[graph.root_id]
    context = engine.build_context(graph, node.id)

    parsed_output = PlanOutput(
        smart_patch=SMARTFields(),
        plan=NodePlan(
            tasks=[
                Task(
                    title="Draft scope",
                    description="Scope the effort",
                    success_criteria="Scope documented",
                    depends_on=[],
                    estimate_hours=2.0,
                    relative_timing="Week 1",
                    due=None,
                ),
                Task(
                    title="Execute pilot",
                    description="Run pilot",
                    success_criteria="Pilot completed",
                    depends_on=["Draft scope"],
                    estimate_hours=8.0,
                    relative_timing="Week 2",
                    due="",
                ),
                Task(
                    title="Review pilot",
                    description="Review outcomes",
                    success_criteria="Findings documented",
                    depends_on=["Execute pilot"],
                    estimate_hours=3.0,
                    relative_timing="Week 3",
                    due="2026-07-01",
                ),
            ],
        ),
    )
    monkeypatch.setattr(provider, "_parse_structured", lambda *args, **kwargs: parsed_output)

    output = provider.plan(node, context)

    assert output.plan.tasks
    for task in output.plan.tasks:
        assert task.relative_timing
        assert task.due is not None
        assert task.due != ""


def test_openai_plan_compacts_verbose_task_fields_without_network(monkeypatch):
    provider = OpenAIProvider("test-key")
    graph = engine.init_graph("Improve retention")
    node = graph.nodes[graph.root_id]
    context = engine.build_context(graph, node.id)

    parsed_output = PlanOutput(
        smart_patch=SMARTFields(),
        plan=NodePlan(
            tasks=[
                Task(
                    title="Write an extremely long discovery and implementation task title that should not spill across the entire graph card",
                    description="Map every source, owner, deadline, review point, approval gate, and unknown in a compact way that still tells the executor what to do next.",
                    success_criteria="A concise artifact exists with the owners, dates, risks, blockers, and next action agreed by the responsible team.",
                    relative_timing="During the first week after the current planning session completes",
                    due="No later than the final stakeholder review meeting in the current planning window",
                ),
                Task(title="Run pilot", description="Pilot with users", success_criteria="Pilot complete"),
                Task(title="Review outcomes", description="Review data", success_criteria="Findings documented"),
            ],
        ),
    )
    monkeypatch.setattr(provider, "_parse_structured", lambda *args, **kwargs: parsed_output)

    output = provider.plan(node, context)
    task = output.plan.tasks[0]

    assert len(task.title) <= 54
    assert len(task.description) <= 110
    assert len(task.success_criteria) <= 100
    assert len(task.relative_timing) <= 32
    assert len(task.due) <= 40


def test_openai_decompose_rejects_short_output_without_padding(monkeypatch):
    provider = OpenAIProvider("test-key")
    graph = engine.init_graph("Improve retention")
    node = graph.nodes[graph.root_id]
    context = engine.build_context(graph, node.id)

    monkeypatch.setattr(
        provider,
        "_parse_structured",
        lambda *args, **kwargs: SimpleNamespace(
            children=[
                ChildDraft(
                    title="Scope",
                    workstream="Scope",
                    smart=SMARTFields(
                        specific="Define scope",
                        measurable="Scope documented",
                        relevant="Supports retention",
                    ),
                )
            ]
        ),
    )

    with pytest.raises(RuntimeError, match="must contain between 5 and 9 valid child goals"):
        provider.decompose(node, context, target_children=7, min_children=5, max_children=9)


def test_openai_baseline_questions_reject_invalid_count_without_fallback(monkeypatch):
    provider = OpenAIProvider("test-key")
    graph = engine.init_graph("Improve retention")
    node = graph.nodes[graph.root_id]
    context = engine.build_context(graph, node.id)

    monkeypatch.setattr(
        provider,
        "_parse_structured",
        lambda *args, **kwargs: SimpleNamespace(
            questions=[
                BaselineQuestion(
                    id="q1",
                    question="What is the goal?",
                    category="specific",
                    guide="Describe the target outcome.",
                    research_basis="Clear targets improve execution.",
                ),
                BaselineQuestion(
                    id="q2",
                    question="What is blocked?",
                    category="constraints",
                    guide="Describe the main blocker.",
                    research_basis="Constraint mapping reduces slippage.",
                ),
            ]
        ),
    )

    with pytest.raises(RuntimeError, match="must contain between 4 and 8 questions"):
        provider.baseline_questions(node, context)


def test_openai_plan_rejects_short_output_without_padding(monkeypatch):
    provider = OpenAIProvider("test-key")
    graph = engine.init_graph("Improve retention")
    node = graph.nodes[graph.root_id]
    context = engine.build_context(graph, node.id)

    parsed_output = PlanOutput(
        smart_patch=SMARTFields(),
        plan=NodePlan(
            tasks=[
                Task(
                    title="Draft scope",
                    description="Scope the effort",
                    success_criteria="Scope documented",
                    depends_on=[],
                    estimate_hours=2.0,
                    relative_timing="Week 1",
                    due="TBD",
                ),
                Task(
                    title="Execute pilot",
                    description="Run pilot",
                    success_criteria="Pilot completed",
                    depends_on=["Draft scope"],
                    estimate_hours=8.0,
                    relative_timing="Week 2",
                    due="TBD",
                ),
            ],
        ),
    )
    monkeypatch.setattr(provider, "_parse_structured", lambda *args, **kwargs: parsed_output)

    with pytest.raises(RuntimeError, match="must contain between 3 and 6 tasks"):
        provider.plan(node, context)
