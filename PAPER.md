# SMART-GoT: A Stepwise SMART Goal-Setting Pipeline with an Adaptive Graph-of-Thought Backend

> **Note.** This is a *rudimentary start* of the paper.

---

## Abstract

Specific, measurable goals can improve performance, but writing them well is hard, and many people struggle to translate goals into doable plans that survive real-world constraints. Goal-setting research suggests that *specificity and measurement* matter, yet “one-shot” SMART writing can become mechanical and misleading when people don’t have baseline data or don’t understand the criteria. We propose **SMART-GoT**, a stage-based model that *first* drafts **Specific–Measurable–Relevant** goals, *then* uses baseline research to make **Attainable** and **Time-bound** constraints meaningful, and finally supports continuous revision as goals evolve. The backend represents **goals** as an **adaptive directed graph**, where each goal node also stores its metrics, baseline evidence, constraints, resources, and action plan. It uses **graph construction, expansion, evaluation, and pruning** to allocate LLM effort where uncertainty remains. We frame the system as mixed-initiative: the AI drafts and critiques, while the user edits and approves at stage gates to reduce overreliance and keep goals aligned with lived context.

---

## Author Keywords

SMART goals; goal setting; action planning; personal informatics; goal evolution; human–AI collaboration; metacognition; Graph of Thoughts; Adaptive Graph of Thoughts.

---

## 1 Introduction

Goal-setting theory shows that **clear, specific goals** can improve performance compared to vague intentions, in part by directing attention and supporting persistence and self-regulation [1].
In practice, many people still write goals that are aspirational but underspecified, then lose momentum once daily constraints, shifting priorities, and limited attention collide. Workplace studies describe fragmented attention and frequent task switching, which can make sustained planning and follow-through harder without external scaffolds [12, 13].

SMART criteria were introduced as a pragmatic checklist for writing goals and objectives [2]. Yet evaluation research warns that presenting SMART as a single “fill-in-the-blanks” step can be **unwise** in some contexts: stakeholders may need to *do homework* (e.g., gather baseline data) before “attainable” and “time-bound” can be set in a meaningful way [3].
In health and behavior change, goal setting is often paired with action planning, monitoring, and iterative adjustment rather than treated as a one-time event [4].

At the same time, personal informatics (PI) systems commonly support tracking and reflection, but classic stage models emphasize that PI use is iterative and can break down when goals and contexts shift [7].
Recent work on **changing health goals** reports that goals evolve for many reasons (progress, setbacks, new constraints), and PI tools often don’t sufficiently support goal change and re-planning [9, 10].

Large language models can help draft plans, but they also raise metacognitive demands: users must decide what to ask for, how to verify outputs, and when to revise goals rather than accept fluent text at face value [16].
Cognitive forcing functions—designs that slow users down and require deliberate checks—can reduce overreliance on AI suggestions in decision tasks, even if users don’t always “like” the extra effort [17].

**SMART-GoT** responds to these gaps with (1) a **stepwise SMART stage model** grounded in evaluation and behavior-change research, and (2) an **Adaptive Graph-of-Thought backend** that structures goal planning as graph construction, expansion, evaluation, and pruning.

### Contributions (initial)

1. A **stage-based SMART goal model** that operationalizes a *stepwise* SMART writing process: **Specific–Measurable–Relevant → baseline research → Attainable–Time-bound** [3].
2. A backend that **binds each stage** to **Adaptive Graph-of-Thought operations** (construct/expand/evaluate/prune), enabling budgeted, selective reasoning over a goal graph [19, 20].
3. A mixed-initiative control loop that uses **user edits as stage gates** to reduce overreliance and keep plans aligned with lived context [16, 17].

---

## 2 Related Work

### 2.1 Goal setting, SMART criteria, and “stepwise” objective writing

Goal-setting theory provides long-running empirical support that **specific goals** improve task performance more than vague goals, moderated by factors like feedback and task complexity [1].
SMART goal framing emerged as a managerial method for writing clearer objectives [2] and later spread broadly into evaluation and program planning contexts [3].

A key caution is that SMART is often taught as *simultaneous criteria satisfaction*, but Bjerke and Renger present a case where stakeholders **first wrote specific, measurable, and relevant objectives, then gathered baseline data**, and only after that could they set achievable and timely criteria [3].
This motivates our stage ordering: we treat baseline research as a prerequisite for attainability and time bounds rather than a post-hoc add-on.

### 2.2 Evidence that structured SMART goal interventions can help

Empirically, “SMART-style” goal interventions show mixed but meaningful benefits depending on outcome measures and context. In a randomized trial in simulation-based medical education, SMART-enhanced debriefing didn’t improve the *number/quality* of stated goals, but participants completed **more educational actions**, aligning with the practical intent of goal interventions [26].
In adolescent fitness, a randomized controlled trial combining SMART goal setting with training reported improvements in physical fitness metrics and exercise attitudes relative to control conditions [27].
In a short experimental intervention with university students, SMART goal instruction increased rated goal attainment and need satisfaction (with weaker effects on broader well-being), suggesting that structure may help people translate intent into action under some conditions [28].

We take these findings as support for a design stance: **the value of SMART is not just writing a sentence**, but creating a goal representation that can drive action selection, monitoring, and revision.

### 2.3 Action planning and implementation intentions

Goal setting alone often isn’t enough; health behavior change work emphasizes **action planning** and iterative adjustment [4].
A large meta-analysis shows that **implementation intentions** (“If situation X occurs, then I will do Y”) reliably improve goal achievement by linking cues to actions [5].
The Rubicon/action-phase perspective distinguishes **goal selection, planning, action, and evaluation**, highlighting that different cognitive tasks matter at different phases [6].
We use this as a theoretical bridge: our stages separate *goal specification* from *planning* and *evaluation* rather than blending them.

### 2.4 Personal informatics, goal evolution, and goal-directed tracking

The classic PI stage model (preparation → collection → integration → reflection → action) frames self-tracking as iterative and failure-prone when tools don’t support transitions between stages [7].
Recent PI work argues that “goal setting” in practice is more complex than static SMART statements: people hold multiple goals, revise them, and sometimes abandon them as life changes [9, 10].
Goal-directed self-tracking systems (e.g., MigraineTracker) show how explicit goals can shape what people collect and how they interpret data, while also surfacing tensions in sustained, chronic-condition tracking [8].
Self-experimentation tools like TummyTrials further show that systems can scaffold *hypothesis formation, testing, and interpretation*—a useful analogy for “baseline research” and feasibility checks in our pipeline [15].

### 2.5 Human–AI collaboration, metacognition, and safeguards against overreliance

Distributed cognition argues that cognitive work is often spread across people and artifacts; well-designed tools can “move work” into the environment and reduce internal load [11].
With generative AI, users face added metacognitive work: they must frame requests, assess correctness, and decide when to revise or verify outputs [16].
Cognitive forcing functions can reduce overreliance on AI suggestions by prompting deliberate reasoning, though they may raise perceived effort [17].
Systems like VISAR illustrate mixed-initiative workflows where AI supports drafting while users retain control through structured representations and revision [18].

### 2.6 Graph-structured reasoning with LLMs

Graph-of-Thoughts represents intermediate LLM outputs as nodes with dependencies, enabling branching, merging, and feedback loops beyond linear chains [19].
Adaptive Graph of Thoughts extends this with **selective expansion**, allocating test-time computation to subproblems that need more analysis [20].
Related agent paradigms (e.g., ReAct, Self-Ask) interleave reasoning with actions such as retrieval or tool use, which we reuse for baseline research and validation prompts [21, 22].
For mixed-initiative delegation, ReHAC models when to request human input during complex task solving, aligning with our “delegate nodes” concept [23].

---

## 3 A Stepwise SMART Stage Model

We define **four stages** for goal formation and evolution. The ordering is grounded in evidence that a **stepwise** SMART application can be necessary: *Specific–Measurable–Relevant first*, then baseline data, then Achievable and Timely criteria [3].

### Stage 1: Draft Specific–Measurable–Relevant (SMR)

The user begins by writing (or co-writing with the system) a goal that is:

* **Specific**: the target behavior/outcome is stated clearly.
* **Measurable**: success metrics are named (quantitative when possible).
* **Relevant**: the “why” is explicit, so later tradeoffs can be judged.

This stage reflects goal-setting theory’s emphasis on clarity/specificity [1] while deferring feasibility claims until evidence exists [3].

### Stage 2: Baseline research and reality mapping

Before setting “A” and “T,” the system prompts **baseline research**: current performance, constraints, available resources, and risks. This can mix self-tracking and external information seeking, consistent with PI models where preparation/collection/integration precede action [7].
We treat baseline collection as the hinge that makes later feasibility checks non-fictional [3].

### Stage 3: Add Attainable + Time-bound, then produce an action plan

With baseline evidence, the goal is revised to include:

* **Attainable**: constraints and capability limits are represented (not assumed).
* **Time-bound**: deadlines and milestones are chosen to match the baseline and constraints.

This stage also generates **implementation intentions** (if-then plans) for subgoals, since such plans improve goal achievement in meta-analytic evidence [5].

### Stage 4: Evaluate, prune, and adapt goals over time

Goal pursuit is not linear. Action-phase models emphasize post-action evaluation and revision [6], and PI research highlights that goals shift and tools often fail to support that shift well [9].
Stage 4 therefore supports: monitoring, detecting mismatch (goal too hard/easy), pruning outdated subgoals, and rewriting the goal without losing rationale or history.

---

## 4 Backend: SMART-GoT as an Adaptive Graph-of-Thought Planner

### 4.1 Core representation (goal nodes only)

We represent a user goal as a directed graph (G=(V,E)). Every node (v \in V) is a **goal node**: a structured goal object that can be nested without limit. A “subgoal” is not a different type—it’s just a goal node that is linked as a child of another goal. A goal node may also serve multiple parents when it supports more than one higher-level goal.

Each goal node stores the information that would otherwise be split across specialized node types, including:

* **SMR fields** (Specific statement, Measurable metric definition, Relevant rationale)
* **Baseline fields** (current value, evidence/source, confidence, timestamps)
* **Constraints** (time, money, access, health limits, risks)
* **A/T fields** (feasibility notes, milestones, deadlines)
* **Action plan fields** (ordered steps, if-then triggers, monitoring cadence)
* **Resources** (tools, templates, people, services)
* **Review prompts** (open questions and critiques to force reflection)
* **Evaluation metadata** (scores, reasons, last-updated)

Edges (E) capture relations between goal nodes, including decomposition (parent→child), cross-dependencies, and revision links. This keeps the representation compatible with Graph-of-Thoughts’ view of intermediate states as nodes with dependencies, while enforcing a single universal node type in the goal domain [19].

### 4.2 How SMART stages shape the goal graph

The SMART stages don’t just label progress—they **constrain graph shape** by controlling what can be created, expanded, scored, and kept.

* **Stage 1 (SMR)** → **Graph construction**: create a root goal node and require SMR fields before any deep nesting.
* **Stage 2 (baseline)** → **Graph expansion**: expand selectively by creating nested goal nodes for missing prerequisites and candidate subgoals, and by filling baseline fields inside relevant goal nodes.
* **Stage 3 (A+T + plans)** → **Graph evaluation**: score competing nested structures and plan fields against feasibility and alignment rubrics, then pick a consistent subgraph.
* **Stage 4 (adaptation)** → **Graph pruning/selection**: prune weak branches, merge near-duplicates, and rewrite goals while preserving revision traces.

Adaptive Graph of Thoughts motivates *selective expansion*—only expanding subproblems that need more analysis—rather than a fixed “always expand” pipeline [20].

### 4.3 Planning loop and budget control

The planner runs a budgeted loop that alternates generation, scoring, and pruning. Budget can be expressed in tokens, time, depth, or node count, aligned with test-time adaptive reasoning goals [20].

**Algorithm sketch (backend only).**

```text
Init graph G with root goal node.

while budget_remaining(G) and not goal_satisfied(G):
    n = pop_next_node(G)

    # 1) Propose
    proposed = LLM_Proposed_Subgoals(goal, context, adaptive_k(n))

    # 2) Integrate
    integrate_all(G, proposed)

    # User gate: expose draft graph for edits/approval.

    # 3) Evaluate
    score_nodes(G)   # rubric-based judge and/or heuristics

    # 4) Prune + merge
    prune_low_value(G)
    merge_equivalent(G)

# 5) Propose delegation
delegate_nodes(G)
```

This is deliberately mixed-initiative: GenAI systems can impose metacognitive demands, so we design stage gates as “thinking checkpoints,” not optional UI sugar [16, 17].

### 4.4 Goal-node scoring and “LLM-as-a-judge” rubrics

Evaluation attaches scores and reasons to **goal nodes** (including their nested children and internal fields). We combine heuristics (e.g., SMR completeness checks) with rubric-based judging. LLM-as-a-judge work shows that strong LLM judges can align with human preferences on some open-ended evaluations, but also has known biases (verbosity, position), so the rubric must be explicit and auditable [24].
For structured scoring, we adopt form-like criteria prompts similar to LLM-based evaluation frameworks that separate task definition from evaluation criteria [25].

### 4.5 Baseline research via “reason-act” prompting

Baseline research often requires retrieval and small actions (searching, comparing options, summarizing constraints). ReAct motivates interleaving reasoning with actions to reduce hallucinated planning and support dynamic plan updates [21].
Self-Ask suggests explicitly generating follow-up questions before committing to an answer, which we reuse as “baseline questions” stored inside goal nodes and as prompts for nested prerequisite-goals in Stage 2 [22].

### 4.6 Delegation and human intervention

Delegation operates over **goal nodes**: the backend may recommend which nested goals should be handled by the agent, deferred, or explicitly assigned to the user. This is treated as a policy problem, echoing work on reinforcement-learned human-agent collaboration policies [23].
This is also a safety and alignment measure: forcing user review can reduce overreliance and keep goals grounded in the user’s constraints and values [17].

---

## 5 Front-End Interface

*(Intentionally left blank.)*

---

## 6 Interaction Flow and Visual Design

*(Intentionally left blank.)*

---

## 7 User Study and Evaluation Plan

*(Intentionally left blank.)*

---

## References

**[1]** Edwin A. Locke and Gary P. Latham. 2002. *Building a Practically Useful Theory of Goal Setting and Task Motivation: A 35-Year Odyssey.* American Psychologist.

**[2]** George T. Doran. 1981. *There’s a S.M.A.R.T. way to write management’s goals and objectives.* Management Review.

**[3]** May Britt Bjerke and Ralph Renger. 2017. *Being smart about writing SMART objectives.* Evaluation and Program Planning 61 (2017), 125–127.

**[4]** Ryan R. Bailey. 2019. *Goal Setting and Action Planning for Health Behavior Change.* American Journal of Lifestyle Medicine.

**[5]** Peter M. Gollwitzer and Paschal Sheeran. 2006. *Implementation Intentions and Goal Achievement: A Meta-Analysis of Effects and Processes.* Advances in Experimental Social Psychology 38, 69–119.

**[6]** Peter M. Gollwitzer. 1990. *Action Phases and Mind-Sets.* (Rubicon / action-phase model).

**[7]** Ian Li, Anind K. Dey, and Jodi Forlizzi. 2010. *A Stage-Based Model of Personal Informatics Systems.* In Proc. CHI.

**[8]** Yasaman S. Sefidgar et al. 2024. *MigraineTracker: Examining Patient Experiences with Goal-Directed Self-Tracking for a Chronic Condition.*

**[9]** Masoud Ekhtiar et al. 2025. *Changing Health Goals with Personal Informatics.*

**[10]** Masoud Ekhtiar et al. 2023. *Goals for Goal Setting: A Scoping Review on Personal Informatics.* In Proc. DIS.

**[11]** James Hollan, Edwin Hutchins, and David Kirsh. 2000. *Distributed Cognition: Toward a New Foundation for Human–Computer Interaction Research.* ACM TOCHI 7, 2, 174–196.

**[12]** Gloria Mark, Shamsi T. Iqbal, Mary Czerwinski, and Paul Johns. 2014. *Bored Mondays and Focused Afternoons: The Rhythm of Attention and Online Activity in the Workplace.* In Proc. CHI.

**[13]** Victor M. González and Gloria Mark. 2004. *“Constant, Constant, Multi-tasking Craziness”: Managing Multiple Working Spheres.* In Proc. CHI.

**[14]** Matthew Jörke, Yasaman S. Sefidgar, Talie Massachi, Jina Suh, and Gonzalo Ramos. 2023. *Pearl: A Technology Probe for Machine-Assisted Reflection on Personal Data.* In Proc. IUI.

**[15]** Ruchi Karkar et al. 2017. *TummyTrials: A Feasibility Study of Using Self-Experimentation to Detect Individualized Food Triggers.* In Proc. CHI.

**[16]** Bob Tankelevitch et al. 2024. *The Metacognitive Demands and Opportunities of Generative AI.*

**[17]** Zana Buçinca, Maja Barbara Malaya, and Krzysztof Z. Gajos. 2021. *To Trust or to Think: Cognitive Forcing Functions Can Reduce Overreliance on AI in AI-assisted Decision-making.* Proc. ACM HCI 5, CSCW1, Article 188.

**[18]** (VISAR) Zhang et al. 2023. *VISAR: A Human–AI Argumentative Writing Assistant with Visual Programming and Rapid Draft Prototyping.* In Proc. UIST.

**[19]** Maciej Besta et al. 2024. *Graph of Thoughts: Solving Elaborate Problems with Large Language Models.* (arXiv / AAAI).

**[20]** Tushar Pandey et al. 2025. *Adaptive Graph of Thoughts: Test-Time Adaptive Reasoning Unifying Chain, Tree, and Graph Structures.* arXiv:2502.05078.

**[21]** Shunyu Yao et al. 2023. *ReAct: Synergizing Reasoning and Acting in Language Models.* In Proc. ICLR.

**[22]** Ofir Press et al. 2022. *Measuring and Narrowing the Compositionality Gap in Language Models.* (Self-Ask).

**[23]** Xueyang Feng et al. 2024. *Large Language Model-based Human-Agent Collaboration for Complex Task Solving.* (ReHAC).

**[24]** Lianmin Zheng et al. 2023. *Judging LLM-as-a-Judge with MT-Bench and Chatbot Arena.* arXiv:2306.05685.

**[25]** Yang Liu et al. 2023. *G-Eval: NLG Evaluation using GPT-4 with Better Human Alignment.* In Proc. EMNLP.

**[26]** Ali Aghera et al. 2018. *A Randomized Trial of SMART Goal Enhanced Debriefing after Simulation to Promote Educational Actions.* (Open-access version).

**[27]** Y. Lu et al. 2022. *Effects of a SMART Goal Setting and 12-Week Core Strength Training Intervention on Physical Fitness and Exercise Attitudes in Adolescents: A Randomized Controlled Trial.*

**[28]** (SMART intervention) Bahrami et al. 2022. *Applying SMART Goal Intervention Leads to Greater Goal Attainment, Need Satisfaction and Positive Affect.* International Journal of Mental Health Promotion.
