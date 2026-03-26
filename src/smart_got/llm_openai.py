from __future__ import annotations

import os
import re
from typing import TypeVar

from pydantic import BaseModel, Field

from smart_got import prompts
from smart_got.models import (
    BaselineApplyOutput,
    BaselineQA,
    BaselineQuestion,
    ChildDraft,
    Node,
    PlanOutput,
    SMARTFields,
    Task,
)

TModel = TypeVar("TModel", bound=BaseModel)


class _DecomposeOutput(BaseModel):
    children: list[ChildDraft] = Field(default_factory=list)


class _BaselineQuestionsOutput(BaseModel):
    questions: list[BaselineQuestion] = Field(default_factory=list)


class OpenAIProvider:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.model = os.getenv("SMARTGOT_OPENAI_MODEL", "gpt-4.1")
        self._client = None

    def _get_client(self):
        if self._client is not None:
            return self._client
        try:
            from openai import OpenAI  # type: ignore
        except ImportError as exc:  # pragma: no cover - only happens when package missing
            raise RuntimeError(
                "OpenAI SDK is not installed. Install the `openai` package or set "
                "SMARTGOT_LLM_MODE=mock."
            ) from exc
        self._client = OpenAI(api_key=self.api_key)
        return self._client

    def _extract_output_text(self, response: object) -> str:
        text = getattr(response, "output_text", "")
        if isinstance(text, str) and text.strip():
            return text
        output_items = getattr(response, "output", [])
        for item in output_items if isinstance(output_items, list) else []:
            content_items = getattr(item, "content", [])
            for content in content_items if isinstance(content_items, list) else []:
                maybe_text = getattr(content, "text", "")
                if isinstance(maybe_text, str) and maybe_text.strip():
                    return maybe_text
        return ""

    def _fallback_json_schema(
        self,
        schema: type[TModel],
        schema_name: str,
        instructions: str,
        prompt_input: str,
    ) -> TModel:
        client = self._get_client()
        response = client.responses.create(
            model=self.model,
            instructions=instructions,
            input=prompt_input,
            text={
                "format": {
                    "type": "json_schema",
                    "name": schema_name,
                    "schema": schema.model_json_schema(),
                    "strict": True,
                }
            },
        )
        raw = self._extract_output_text(response)
        if not raw:
            raise RuntimeError(f"OpenAI {schema_name} returned empty output.")
        return schema.model_validate_json(raw)

    def _parse_structured(
        self,
        schema: type[TModel],
        schema_name: str,
        instructions: str,
        prompt_input: str,
    ) -> TModel:
        client = self._get_client()
        parse_fn = getattr(client.responses, "parse", None)
        if callable(parse_fn):
            response = parse_fn(
                model=self.model,
                instructions=instructions,
                input=prompt_input,
                text_format=schema,
            )
            parsed = getattr(response, "output_parsed", None)
            if isinstance(parsed, schema):
                return parsed
            if parsed is not None:
                return schema.model_validate(parsed)
            raw = self._extract_output_text(response)
            if raw:
                return schema.model_validate_json(raw)
            raise RuntimeError(f"OpenAI {schema_name} parse returned no structured output.")

        return self._fallback_json_schema(schema, schema_name, instructions, prompt_input)

    @staticmethod
    def _normalize_node_text(value: str) -> str:
        cleaned = re.sub(r"\s*&\s*", " and ", value.strip())
        return re.sub(r"\s+", " ", cleaned)

    @staticmethod
    def _is_placeholder_title(value: str) -> bool:
        return bool(
            re.search(
                r"\b(subgoal|task|workstream|child)\s*\d+\b",
                value.strip().lower(),
            )
        )

    @staticmethod
    def _clean_children(
        node: Node,
        children: list[ChildDraft],
        min_children: int,
        max_children: int,
    ) -> list[ChildDraft]:
        cleaned: list[ChildDraft] = []
        seen: set[tuple[str, str]] = set()
        for child in children:
            title = OpenAIProvider._normalize_node_text(child.title)
            workstream = OpenAIProvider._normalize_node_text(child.workstream)
            if not title or not workstream:
                continue
            if OpenAIProvider._is_placeholder_title(title):
                continue
            key = (title.lower(), workstream.lower())
            if key in seen:
                continue
            seen.add(key)
            smart = child.smart
            if not smart.specific.strip():
                smart.specific = f"{title} for {node.title}"
            if not smart.measurable.strip():
                smart.measurable = f"Define measurable output for {title}"
            if not smart.relevant.strip():
                smart.relevant = f"Supports {node.title}"
            cleaned.append(
                ChildDraft(
                    title=title,
                    workstream=workstream,
                    smart=smart,
                )
            )

        fallback = [
            ("Scope", "Define Scope and Success"),
            ("Resources", "Plan Resource Coverage"),
            ("Timeline", "Build Timeline"),
            ("Risk", "Manage Risk and Compliance"),
            ("Operations", "Prepare Operations Logistics"),
            ("Stakeholders", "Align Stakeholder Owners"),
            ("Communications", "Set Communication Plan"),
        ]
        idx = 0
        while len(cleaned) < min_children and idx < len(fallback):
            workstream, title = fallback[idx]
            idx += 1
            key = (title.lower(), workstream.lower())
            if key in seen:
                continue
            seen.add(key)
            cleaned.append(
                ChildDraft(
                    title=title,
                    workstream=workstream,
                    smart=SMARTFields(
                        specific=f"{title} for {node.title}",
                        measurable=f"Define measurable output for {title}",
                        relevant=f"Supports {node.title}",
                    ),
                )
            )
        return cleaned[:max_children]

    @staticmethod
    def _ensure_question_count(node: Node, context: str, questions: list[BaselineQuestion]) -> list[BaselineQuestion]:
        if 4 <= len(questions) <= 8:
            return questions
        root_title = node.title
        parent_title = None
        for line in context.splitlines():
            if line.startswith("ROOT_TITLE:"):
                root_title = line.split(":", 1)[1].strip() or root_title
            if line.startswith("PARENT_TITLE:"):
                parent_title = line.split(":", 1)[1].strip() or None
        fallback = prompts.build_baseline_questions(root_title, parent_title, node.title)
        return fallback[:8]

    @staticmethod
    def _first_answer(qa_pairs: list[BaselineQA], categories: set[str]) -> str:
        for qa in qa_pairs:
            if qa.category.lower() in categories and qa.answer.strip():
                return qa.answer.strip()
        return ""

    @staticmethod
    def _normalize_plan(output: PlanOutput, node: Node) -> PlanOutput:
        tasks = output.plan.tasks[:6]
        if len(tasks) < 3:
            tasks.extend(
                [
                    Task(
                        title=f"Confirm scope for {node.title}",
                        description="Validate scope boundaries and acceptance criteria.",
                        success_criteria="Scope approved by owner.",
                        depends_on=[],
                        estimate_hours=4.0,
                        relative_timing="Week 1",
                        due="TBD",
                    ),
                    Task(
                        title=f"Execute core work for {node.title}",
                        description="Deliver planned outputs and track completion.",
                        success_criteria="Core outputs delivered and reviewed.",
                        depends_on=[f"Confirm scope for {node.title}"],
                        estimate_hours=12.0,
                        relative_timing="Week 2-3",
                        due="TBD",
                    ),
                    Task(
                        title=f"Review and close for {node.title}",
                        description="Evaluate outcomes and close open issues.",
                        success_criteria="Review complete and next actions captured.",
                        depends_on=[f"Execute core work for {node.title}"],
                        estimate_hours=4.0,
                        relative_timing="Week 4",
                        due="TBD",
                    ),
                ]
            )

        normalized_tasks: list[Task] = []
        for task in tasks[:6]:
            normalized_tasks.append(
                Task(
                    title=task.title.strip() or f"Task for {node.title}",
                    description=task.description,
                    success_criteria=task.success_criteria.strip() or "Definition of done is documented.",
                    depends_on=task.depends_on,
                    estimate_hours=task.estimate_hours,
                    relative_timing=task.relative_timing or "TBD",
                    due=task.due or "TBD",
                )
            )
        output.plan.tasks = normalized_tasks
        return output

    def decompose(
        self,
        node: Node,
        context: str,
        target_children: int,
        min_children: int,
        max_children: int,
    ) -> list[ChildDraft]:
        parsed = self._parse_structured(
            _DecomposeOutput,
            "decompose_output",
            prompts.decompose_instructions(),
            prompts.build_decompose_input(
                node=node,
                context=context,
                target_children=target_children,
                min_children=min_children,
                max_children=max_children,
            ),
        )
        return self._clean_children(node, parsed.children, min_children, max_children)

    def baseline_questions(self, node: Node, context: str) -> list[BaselineQuestion]:
        parsed = self._parse_structured(
            _BaselineQuestionsOutput,
            "baseline_questions_output",
            prompts.baseline_questions_instructions(),
            prompts.build_baseline_questions_input(node=node, context=context),
        )
        questions = self._ensure_question_count(node, context, parsed.questions)
        return questions[:8]

    def baseline_apply(
        self,
        node: Node,
        siblings: list[Node],
        context: str,
        qa_pairs: list[BaselineQA],
    ) -> BaselineApplyOutput:
        output = self._parse_structured(
            BaselineApplyOutput,
            "baseline_apply_output",
            prompts.baseline_apply_instructions(),
            prompts.build_baseline_apply_input(
                node=node,
                context=context,
                siblings=siblings,
                qa_pairs=qa_pairs,
            ),
        )

        achievable = output.smart_patch.achievable.strip()
        time_bound = output.smart_patch.time_bound.strip()
        if not achievable:
            resources_answer = self._first_answer(qa_pairs, {"resources", "achievable"})
            if resources_answer:
                achievable = resources_answer
        if not time_bound:
            time_bound = self._first_answer(qa_pairs, {"time_bound"}) or "TBD"
        output.smart_patch = SMARTFields(
            specific=output.smart_patch.specific,
            measurable=output.smart_patch.measurable,
            achievable=achievable,
            relevant=output.smart_patch.relevant,
            time_bound=time_bound,
        )
        return output

    def plan(self, node: Node, context: str) -> PlanOutput:
        output = self._parse_structured(
            PlanOutput,
            "plan_output",
            prompts.plan_instructions(),
            prompts.build_plan_input(node=node, context=context),
        )
        return self._normalize_plan(output, node)
