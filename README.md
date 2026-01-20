# SMART-GoT (prototype scaffold)

A minimal research prototype scaffold for **SMART-GoT**:
a stage-gated SMART goal pipeline with a goal-only graph backend.

This repo intentionally prioritizes:
- **small, readable modules**
- **JSON artifacts** for reproducibility / paper appendices
- a **CLI** that demonstrates Stage 1→4 plus stage gates (approve steps)

## Install (dev)

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev,llm]"
```

## LLM setup (optional)

The prototype defaults to heuristic drafts. To enable model calls via the OpenAI Responses API:

```bash
export OPENAI_API_KEY="sk-..."
export SMARTGOT_LLM_MODE=openai
export SMARTGOT_MODEL=gpt-5-mini   # or gpt-5.2
export SMARTGOT_STORE=false        # optional, defaults to false
```

For offline development/tests:

```bash
export SMARTGOT_LLM_MODE=mock
```

## Quickstart (CLI)

### 1) Stage 1: draft SMR graph

```bash
smartgot stage1 --intent "Write a SMART-GoT prototype" --out stage1.json
smartgot summary --graph stage1.json
```

Edit `stage1.json` if you want. Stage 2 requires the stage 1 gate plus `goal.v1` status set to `accepted` (approving stage 1 auto-accepts it unless you set it to `rejected`). Then approve the gate:

```bash
smartgot approve --graph stage1.json --stage 1 --note "Looks good"
```
Each stage command prints a bash-style goal tree showing `subgoal_of` dependencies.

### 2) Stage 2: add baseline questions / constraints

```bash
smartgot stage2 --graph stage1.json --out stage2.json
smartgot summary --graph stage2.json
```

Fill baseline `value` fields inside `goal.v1.data.baseline` in `stage2.json`. You can also use the helper command:

```bash
smartgot answer --graph stage2.json --id baseline.time_per_week_hours --value 3
smartgot answer --graph stage2.json --id baseline.hard_deadline --value 2025-01-01
```

Stage 3 requires the stage 2 gate plus at least one non-empty baseline value. Then:

Note: Stage 2 baseline questions are LLM-only. Set `SMARTGOT_LLM_MODE=openai` (or `mock` for offline tests).
The CLI now enforces `SMARTGOT_LLM_MODE=openai`; mock mode is reserved for tests and offline library use.
Stage 3 will automatically refine the goal + subgoals from baseline answers if that refinement hasn't been run yet.

```bash
smartgot approve --graph stage2.json --stage 2 --note "Baseline confirmed"
```

### 3) Stage 3: generate plan options + scores (A+T + plan)

```bash
smartgot stage3 --graph stage2.json --out stage3.json
smartgot summary --graph stage3.json
```

Stage 3 evaluates plan options but does not choose one. Pick a plan by editing `goal.v1.data.decision.chosen_plan_id` in `stage3.json` or use:

```bash
smartgot choose-plan --graph stage3.json --plan-id goal.plan.option2
```

Then:

```bash
smartgot approve --graph stage3.json --stage 3 --note "Chose a plan"
```

### 4) Stage 4: check-in / adapt (toy)

```bash
smartgot checkin --graph stage3.json --out stage4.json --progress 0.3 --friction "Time got tight"
smartgot summary --graph stage4.json
```
You can now record completed/missed goals and optionally adjust the chosen plan:

```bash
smartgot checkin \
  --graph stage3.json \
  --out stage4.json \
  --progress 0.5 \
  --done goal.subgoal.init.define_acceptance_criteria_for_the_prototype \
  --missed goal.subgoal.init.recruit_train_and_schedule_volunteers_wi \
  --reflection "Route approval slower than expected" \
  --plan-add-step "Finalize route approval paperwork" \
  --time-bound-weeks 8
```

## Interactive session (single command)

If you want a single command that walks through all stages interactively (including baseline Q&A, plan choice, and stage 4 progress), use:

```bash
smartgot interactive --intent "Write a SMART-GoT prototype" --out stage4.json --stage-dir ./runs/demo
```

Set `SMARTGOT_LLM_MODE=openai` to use the LLM during stages 1–3.
When enabled, the LLM also proposes initial subgoals and tailored baseline questions.
After you answer baseline questions, the interactive flow refines the goal and subgoals using those answers.

## Goal-only graph model

The graph uses a single node type (`goal`). Metric definitions, baselines, constraints,
plans, decisions, risks, resources, review prompts, and eval scores live inside `node.data`.
Goal nesting uses `subgoal_of` edges, and the root goal id is `goal.v1`.

## Migration (optional)

To migrate a legacy graph JSON that uses multiple node types:

```bash
smartgot migrate --graph old.json --out new.json
```
