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
                "OpenAI generation is unavailable: the `openai` package is not installed."
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
                    depends_on=[
                        OpenAIProvider._normalize_node_text(dependency)
                        for dependency in child.depends_on
                        if dependency.strip()
                    ],
                    smart=smart,
                )
            )
        if len(cleaned) < min_children or len(cleaned) > max_children:
            raise RuntimeError(
                f"OpenAI decompose output for '{node.title}' must contain between "
                f"{min_children} and {max_children} valid child goals."
            )
        return cleaned

    @staticmethod
    def _ensure_question_count(
        node: Node, context: str, questions: list[BaselineQuestion]
    ) -> list[BaselineQuestion]:
        del context
        if not 4 <= len(questions) <= 8:
            raise RuntimeError(
                f"OpenAI baseline question output for '{node.title}' must contain "
                "between 4 and 8 questions."
            )
        for question in questions:
            if (
                not question.question.strip()
                or not question.guide.strip()
                or not question.research_basis.strip()
            ):
                raise RuntimeError(
                    f"OpenAI baseline question output for '{node.title}' must include "
                    "non-empty question, guide, and research_basis fields."
                )
            if question.question.count("?") > 1:
                raise RuntimeError(
                    f"OpenAI baseline question output for '{node.title}' must ask "
                    "one question per item."
                )
        return questions

    @staticmethod
    def _first_answer(qa_pairs: list[BaselineQA], categories: set[str]) -> str:
        for qa in qa_pairs:
            if qa.category.lower() in categories and qa.answer.strip():
                return qa.answer.strip()
        return ""

    @staticmethod
    def _compact_text(value: str | None, fallback: str, max_chars: int) -> str:
        text = " ".join((value or "").split()) or fallback
        if len(text) <= max_chars:
            return text

        clipped = text[: max_chars - 3].rsplit(" ", 1)[0].rstrip(" ,.;:")
        if not clipped:
            clipped = text[: max_chars - 3].rstrip(" ,.;:")
        return f"{clipped}..."

    @staticmethod
    def _normalize_plan(output: PlanOutput, node: Node) -> PlanOutput:
        tasks = output.plan.tasks
        if len(tasks) < 3 or len(tasks) > 6:
            raise RuntimeError(
                f"OpenAI plan output for '{node.title}' must contain between 3 and 6 tasks."
            )

        normalized_tasks: list[Task] = []
        for task in tasks:
            normalized_tasks.append(
                Task(
                    title=OpenAIProvider._compact_text(
                        task.title,
                        f"Task for {node.title}",
                        54,
                    ),
                    description=OpenAIProvider._compact_text(
                        task.description,
                        "Complete the next concrete step.",
                        110,
                    ),
                    success_criteria=OpenAIProvider._compact_text(
                        task.success_criteria,
                        "Definition of done is documented.",
                        100,
                    ),
                    depends_on=task.depends_on,
                    estimate_hours=task.estimate_hours,
                    relative_timing=OpenAIProvider._compact_text(
                        task.relative_timing,
                        "TBD",
                        32,
                    ),
                    due=OpenAIProvider._compact_text(task.due, "TBD", 40),
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
        return questions

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
