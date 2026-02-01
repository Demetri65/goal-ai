from __future__ import annotations

from typing import Protocol

from smart_got import prompts
from smart_got.models import ChildDraft, Node, SMARTFields


class LLMProvider(Protocol):
    def decompose(
        self,
        node: Node,
        siblings: list[Node],
        target_children: int,
        min_children: int,
        max_children: int,
    ) -> list[ChildDraft]:
        raise NotImplementedError

    def baseline_questions(self, root: Node, parent: Node | None, node: Node) -> list[str]:
        raise NotImplementedError


class MockProvider:
    _workstreams = [
        ("Define scope and success criteria", "Publish scope and success metrics"),
        ("Secure resources and budget", "Finalize budget and funding target"),
        ("Plan timeline and milestones", "Create a milestone timeline with dates"),
        ("Assign roles and owners", "Document owners for each workstream"),
        ("Design delivery plan", "Draft the delivery plan and logistics"),
        ("Marketing and outreach", "Launch outreach plan and track engagement"),
        ("Risk and compliance", "List top risks with mitigations"),
        ("Execution checklist", "Create an execution checklist"),
        ("Measurement and reporting", "Define KPIs and reporting cadence"),
    ]

    def decompose(
        self,
        node: Node,
        siblings: list[Node],
        target_children: int,
        min_children: int,
        max_children: int,
    ) -> list[ChildDraft]:
        del siblings
        count = max(min_children, min(target_children, max_children))
        drafts: list[ChildDraft] = []
        for title, measurable in self._workstreams:
            if len(drafts) >= count:
                break
            specific = f"{title} for {node.title}"
            drafts.append(
                ChildDraft(
                    title=title,
                    smart=SMARTFields(
                        specific=specific,
                        measurable=measurable,
                        relevant=f"Supports {node.title}",
                    ),
                )
            )
        while len(drafts) < count:
            idx = len(drafts) + 1
            title = f"Additional workstream {idx}"
            drafts.append(
                ChildDraft(
                    title=title,
                    smart=SMARTFields(
                        specific=f"{title} for {node.title}",
                        measurable=f"Define measurable output for {title}",
                        relevant=f"Supports {node.title}",
                    ),
                )
            )
        return drafts

    def baseline_questions(self, root: Node, parent: Node | None, node: Node) -> list[str]:
        return prompts.build_baseline_questions(
            root_title=root.title,
            parent_title=parent.title if parent else None,
            node_title=node.title,
        )


def get_provider() -> LLMProvider:
    return MockProvider()
