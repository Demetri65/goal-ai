from __future__ import annotations

import os
from typing import Protocol

from smart_got import prompts
from smart_got.llm_openai import OpenAIProvider
from smart_got.models import (
    BaselineApplyOutput,
    BaselineQA,
    BaselineQuestion,
    ChildDraft,
    Node,
    NodeBaseline,
    NodePlan,
    PlanOutput,
    SMARTFields,
    Task,
)

ProviderContext = str
OPENAI_TOKEN_MISSING_MESSAGE = "OpenAI generation is unavailable: OPENAI_API_KEY is not configured."


class LLMProvider(Protocol):
    def decompose(
        self,
        node: Node,
        context: ProviderContext,
        target_children: int,
        min_children: int,
        max_children: int,
    ) -> list[ChildDraft]:
        raise NotImplementedError

    def baseline_questions(self, node: Node, context: ProviderContext) -> list[BaselineQuestion]:
        raise NotImplementedError

    def baseline_apply(
        self,
        node: Node,
        siblings: list[Node],
        context: ProviderContext,
        qa_pairs: list[BaselineQA],
    ) -> BaselineApplyOutput:
        raise NotImplementedError

    def plan(self, node: Node, context: ProviderContext) -> PlanOutput:
        raise NotImplementedError


class MockProvider:
    _workstreams = [
        ("Scope", "Define Scope and Success", "Define acceptance criteria for this workstream", []),
        (
            "Resources",
            "Plan Resource Coverage",
            "Confirm staffing, budget, and tooling coverage",
            ["Define Scope and Success"],
        ),
        (
            "Stakeholders",
            "Align Stakeholder Owners",
            "Secure owner sign-off on priorities",
            ["Define Scope and Success"],
        ),
        (
            "Timeline",
            "Build Timeline",
            "Publish sequenced execution checkpoints",
            ["Define Scope and Success", "Plan Resource Coverage"],
        ),
        (
            "Operations",
            "Prepare Operations Logistics",
            "Document operational handoffs and dependencies",
            ["Build Timeline", "Plan Resource Coverage"],
        ),
        (
            "Risk",
            "Manage Risk and Compliance",
            "List top risks with assigned mitigations",
            ["Define Scope and Success"],
        ),
        (
            "Communications",
            "Set Communication Plan",
            "Set communication cadence and update channels",
            ["Align Stakeholder Owners"],
        ),
        (
            "Metrics",
            "Define Measurement Reporting",
            "Define KPI tracking and reporting rhythm",
            ["Define Scope and Success"],
        ),
        (
            "Readiness",
            "Confirm Execution Readiness",
            "Validate prerequisites before launch",
            ["Prepare Operations Logistics", "Manage Risk and Compliance"],
        ),
    ]

    @staticmethod
    def _ctx_str(context: ProviderContext, key: str) -> str:
        prefix = f"{key}:"
        for line in context.splitlines():
            if line.startswith(prefix):
                return line[len(prefix) :].strip()
        return ""

    @staticmethod
    def _split_answer(answer: str) -> list[str]:
        return [line.strip() for line in answer.splitlines() if line.strip()]

    @staticmethod
    def _first_answer(qa_pairs: list[BaselineQA], *categories: str) -> str:
        categories_lower = {item.lower() for item in categories}
        for qa in qa_pairs:
            if qa.answer.strip() and qa.category.lower() in categories_lower:
                return qa.answer.strip()
        return ""

    def decompose(
        self,
        node: Node,
        context: ProviderContext,
        target_children: int,
        min_children: int,
        max_children: int,
    ) -> list[ChildDraft]:
        del context
        count = max(min_children, min(target_children, max_children))
        drafts: list[ChildDraft] = []
        for workstream, title, measurable, depends_on in self._workstreams:
            if len(drafts) >= count:
                break
            specific = f"{title} for {node.title}"
            drafts.append(
                ChildDraft(
                    title=title,
                    workstream=workstream,
                    depends_on=depends_on,
                    smart=SMARTFields(
                        specific=specific,
                        measurable=measurable,
                        relevant=f"Supports {node.title}",
                    ),
                )
            )
        fallback_pairs = [
            ("Dependencies", "Dependency Coordination"),
            ("Quality", "Quality Validation"),
            ("Capacity", "Capacity Planning"),
            ("Vendors", "Vendor Coordination"),
            ("Launch", "Launch Preparation"),
        ]
        while len(drafts) < count:
            idx = len(drafts)
            workstream, title = fallback_pairs[idx % len(fallback_pairs)]
            drafts.append(
                ChildDraft(
                    title=title,
                    workstream=workstream,
                    depends_on=[drafts[-1].title] if drafts else [],
                    smart=SMARTFields(
                        specific=f"{title} for {node.title}",
                        measurable=f"Define measurable output for {title}",
                        relevant=f"Supports {node.title}",
                    ),
                )
            )
        return drafts

    def baseline_questions(self, node: Node, context: ProviderContext) -> list[BaselineQuestion]:
        root_title = self._ctx_str(context, "ROOT_TITLE") or node.title
        parent_title = self._ctx_str(context, "PARENT_TITLE") or None
        return prompts.build_baseline_questions(
            root_title=root_title,
            parent_title=parent_title,
            node_title=node.title,
        )

    def baseline_apply(
        self,
        node: Node,
        siblings: list[Node],
        context: ProviderContext,
        qa_pairs: list[BaselineQA],
    ) -> BaselineApplyOutput:
        del context
        sibling_titles = ", ".join(s.title for s in siblings[:3]) if siblings else "none yet"

        assumptions: list[str] = []
        constraints: list[str] = []
        unknowns: list[str] = []
        baseline_notes: list[str] = []
        for qa in qa_pairs:
            entries = self._split_answer(qa.answer)
            if qa.category == "assumptions":
                assumptions.extend(entries)
            elif qa.category == "constraints":
                constraints.extend(entries)
            elif qa.category == "unknowns":
                unknowns.extend(entries)
            else:
                baseline_notes.extend(entries)

        achievable = self._first_answer(qa_pairs, "achievable")
        resources = self._first_answer(qa_pairs, "resources")
        if not achievable and resources:
            achievable = f"Deliver with available resources: {resources}"
        elif achievable and resources:
            achievable = f"{achievable}; resources: {resources}"

        time_bound = self._first_answer(qa_pairs, "time_bound")
        if not time_bound:
            time_bound = "TBD"

        rationale_parts = [
            f"Patched Achievable from baseline capacity/resources input for '{node.title}'."
        ]
        if time_bound != "TBD":
            rationale_parts.append("Captured explicit deadline for TimeBound.")
        else:
            rationale_parts.append("No explicit deadline provided; TimeBound set to TBD.")
        rationale_parts.append(f"Sibling context sampled: {sibling_titles}.")

        return BaselineApplyOutput(
            smart_patch=SMARTFields(achievable=achievable, time_bound=time_bound),
            baseline=NodeBaseline(
                qa=qa_pairs,
                baseline_notes=baseline_notes,
                assumptions=assumptions,
                constraints=constraints,
                unknowns=unknowns,
            ),
            layer_mutations=[],
            rationale=" ".join(rationale_parts),
        )

    def plan(self, node: Node, context: ProviderContext) -> PlanOutput:
        del context
        tasks = [
            Task(
                title=f"Confirm scope for {node.title}",
                description="Validate scope boundaries and success checks with owners.",
                success_criteria="Scope and acceptance criteria are approved.",
                depends_on=[],
                estimate_hours=4.0,
                relative_timing="Week 1",
                due="TBD",
            ),
            Task(
                title=f"Assign owners and resources for {node.title}",
                description="Map accountable owners, capacity, and required tooling.",
                success_criteria="All work items have owners and resource coverage.",
                depends_on=[f"Confirm scope for {node.title}"],
                estimate_hours=6.0,
                relative_timing="Week 1-2",
                due="TBD",
            ),
            Task(
                title=f"Execute core work for {node.title}",
                description="Run planned activities and track completion metrics.",
                success_criteria="Core deliverables completed and measured.",
                depends_on=[f"Assign owners and resources for {node.title}"],
                estimate_hours=16.0,
                relative_timing="Week 2-4",
                due="TBD",
            ),
            Task(
                title=f"Review outcomes and adjust for {node.title}",
                description="Assess results, close gaps, and update next actions.",
                success_criteria="Outcome review completed and next actions documented.",
                depends_on=[f"Execute core work for {node.title}"],
                estimate_hours=5.0,
                relative_timing="Week 4",
                due="TBD",
            ),
        ]
        return PlanOutput(
            smart_patch=SMARTFields(),
            plan=NodePlan(tasks=tasks),
        )


def get_provider() -> LLMProvider:
    mode = os.getenv("SMARTGOT_LLM_MODE", "").strip().lower()
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if mode == "mock":
        return MockProvider()
    if not api_key:
        raise RuntimeError(OPENAI_TOKEN_MISSING_MESSAGE)
    return OpenAIProvider(api_key)
