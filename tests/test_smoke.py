import pytest

from smart_got.io import load_graph, save_graph
from smart_got.stages import StageError, answer_value, approve_gate, choose_plan, run_stage1, run_stage2, run_stage3


@pytest.fixture(autouse=True)
def _llm_mock(monkeypatch):
    monkeypatch.setenv("SMARTGOT_LLM_MODE", "mock")


def test_end_to_end_smoke(tmp_path):
    g1 = run_stage1(intent="build a prototype")
    approve_gate(g1, 1, note="ok")
    assert g1.nodes["goal.v1"].status == "accepted"
    initial_subgoals = [nid for nid in g1.nodes if nid.startswith("goal.subgoal.init.")]
    assert 5 <= len(initial_subgoals) <= 9
    g2 = run_stage2(g1)
    assert all(n.type == "goal" for n in g2.nodes.values())

    # Fill at least one baseline value to satisfy stage3 precondition
    answer_value(g2, "baseline.time_per_week_hours", "3")

    approve_gate(g2, 2, note="baseline ok")
    g3 = run_stage3(g2)

    plans = [n for n in g3.nodes.values() if n.id.startswith("goal.plan.")]
    assert len(plans) >= 1
    assert any(p.data.eval.score is not None for p in plans)
    assert g3.nodes["goal.v1"].data.decision.chosen_plan_id is None

    p = tmp_path / "graph.json"
    save_graph(g3, p)
    g_loaded = load_graph(p)
    assert "goal.v1" in g_loaded.nodes


def test_stage2_requires_accepted_goal():
    g1 = run_stage1(intent="draft a goal")
    g1.nodes["goal.v1"].status = "rejected"
    approve_gate(g1, 1, note="rejected goal")
    assert g1.nodes["goal.v1"].status == "rejected"
    with pytest.raises(StageError):
        run_stage2(g1)


def test_answer_value_sets_baseline():
    g1 = run_stage1(intent="track baseline")
    approve_gate(g1, 1, note="ok")
    g2 = run_stage2(g1)
    answer_value(g2, "baseline.time_per_week_hours", "3")
    assert g2.nodes["goal.v1"].data.baseline["time_per_week_hours"].value == 3


def test_choose_plan_updates_decision_and_statuses():
    g1 = run_stage1(intent="choose a plan")
    approve_gate(g1, 1, note="ok")
    g2 = run_stage2(g1)
    answer_value(g2, "baseline.time_per_week_hours", "2")
    approve_gate(g2, 2, note="baseline ok")
    g3 = run_stage3(g2)

    choose_plan(g3, "goal.plan.option2")
    assert g3.nodes["goal.v1"].data.decision.chosen_plan_id == "goal.plan.option2"
    assert g3.nodes["goal.plan.option2"].status == "accepted"
    assert g3.nodes["goal.plan.option1"].status == "proposed"


def test_mock_llm_stage1_and_stage3(monkeypatch):
    monkeypatch.setenv("SMARTGOT_LLM_MODE", "mock")
    g1 = run_stage1(intent="build a prototype")
    assert not g1.nodes["goal.v1"].text.startswith("I will ")
    approve_gate(g1, 1, note="ok")
    g2 = run_stage2(g1)
    answer_value(g2, "baseline.time_per_week_hours", "4")
    approve_gate(g2, 2, note="baseline ok")
    g3 = run_stage3(g2)
    assert g3.nodes["goal.plan.option1"].data.plan.assumptions
