from smart_got import prompts
from smart_got.engine import init_graph


def test_decompose_prompt_constraints_present():
    text = prompts.decompose_instructions().lower()
    assert "5 to 9" in text
    assert "non-overlapping" in text
    assert "collectively cover" in text
    assert "do not use ampersands" in text
    assert "subgoal n" in text
    assert "chronological display order" in text
    assert "sequential" in text
    assert "parallel" in text
    assert "transitive" in text
    assert "left to right" in text
    assert "cycles" in text


def test_baseline_question_prompt_constraints_present():
    text = prompts.baseline_questions_instructions().lower()
    assert "4 to 8" in text
    assert "5 to 7" in text
    assert "exactly one question" in text
    assert "research-backed methods" in text
    assert "achievable" in text
    assert "timebound" in text or "time_bound" in text
    assert "specific and measurable" in text
    assert "constraints" in text
    assert "risks" in text
    assert "guide" in text
    assert "research_basis" in text


def test_baseline_apply_prompt_constraints_present():
    text = prompts.baseline_apply_instructions().lower()
    assert "smart_patch.achievable" in text
    assert "smart_patch.time_bound" in text
    assert "smart_patch.specific" in text
    assert "smart_patch.measurable" in text
    assert "smart_patch.relevant" in text
    assert "same parent layer" in text


def test_plan_prompt_constraints_present():
    text = prompts.plan_instructions().lower()
    assert "success_criteria" in text
    assert "depends_on" in text
    assert "estimate_hours" in text
    assert "due and relative_timing" in text
    assert "do not default to five" in text
    assert "sibling task counts" in text
    assert "sibling plan task details" in text
    assert "overlapping tasks" in text
    assert "chronological execution order" in text
    assert "current smart timebound" in text
    assert "dependencies forward in time" in text
    assert "title under 54 characters" in text
    assert "description under 110 characters" in text
    assert "prefer 3 or 4 tasks" in text


def test_build_decompose_input_mentions_target_and_context():
    graph = init_graph("Launch pilot")
    node = graph.nodes[graph.root_id]
    payload = prompts.build_decompose_input(
        node=node,
        context="ROOT_TITLE: Launch pilot",
        target_children=7,
        min_children=5,
        max_children=9,
    )
    assert "Target child count: 7" in payload
    assert "allowed range 5-9" in payload
    assert "ROOT_TITLE: Launch pilot" in payload


def test_build_baseline_questions_auto_generated_constraints():
    questions = prompts.build_baseline_questions(
        root_title="Plan a 10k charity run",
        parent_title="Operations",
        node_title="Volunteer coordination",
    )
    assert 4 <= len(questions) <= 8
    categories = {item.category for item in questions}
    assert "achievable" in categories
    assert "time_bound" in categories
    assert "constraints" in categories
    assert "unknowns" in categories
    assert "assumptions" in categories

    question_text = " ".join(item.question for item in questions).lower()
    assert "volunteer coordination" in question_text
    assert "operations" in question_text or "10k charity run" in question_text
    assert all(item.guide for item in questions)
    assert all(item.research_basis for item in questions)
    assert all(item.question.count("?") <= 1 for item in questions)
    assert all(len(item.question) <= 100 for item in questions)
