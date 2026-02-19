from smart_got import engine
from smart_got.llm import MockProvider, OpenAIProvider, get_provider
from smart_got.models import Milestone, NodePlan, PlanOutput, SMARTFields, Task


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


def test_mock_plan_output_has_due_and_relative_timing():
    provider = MockProvider()
    graph = engine.init_graph("Improve retention")
    node = graph.nodes[graph.root_id]
    context = engine.provider_context(graph, node.id)

    output = provider.plan(node, context)

    assert 3 <= len(output.plan.tasks) <= 6
    assert 1 <= len(output.plan.milestones) <= 3
    for task in output.plan.tasks:
        assert task.relative_timing
        assert task.due


def test_get_provider_prefers_openai_when_key_present(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.delenv("SMARTGOT_LLM_MODE", raising=False)
    assert isinstance(get_provider(), OpenAIProvider)

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
            milestones=[Milestone(title="Pilot checkpoint", due=None)],
        ),
    )
    monkeypatch.setattr(provider, "_parse_structured", lambda *args, **kwargs: parsed_output)

    output = provider.plan(node, context)

    assert output.plan.tasks
    for task in output.plan.tasks:
        assert task.relative_timing
        assert task.due is not None
        assert task.due != ""
