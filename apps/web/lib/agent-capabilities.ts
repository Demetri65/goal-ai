import type { Node, Task } from "@/lib/types";

export type AgentCapabilityConfidence = "medium" | "high";

export interface MockAgentTool {
  id: string;
  label: string;
  capability: string;
  keywords: string[];
}

export interface AgentCapabilityMatch {
  agentId: string;
  agentName: string;
  confidence: AgentCapabilityConfidence;
  tools: Pick<MockAgentTool, "id" | "label" | "capability">[];
  executableTaskCount: number;
  totalTaskCount: number;
  rationale: string;
}

export const MOCK_FIELD_AGENT = {
  id: "field-ops-agent",
  name: "FieldOps Agent",
  description:
    "A mock general-purpose agent with browser, document, data, scheduling, communications, and workflow tools.",
  tools: [
    {
      id: "browser_research",
      label: "Web research",
      capability:
        "Finds, compares, summarizes, and cites public information, options, requirements, and vendors.",
      keywords: [
        "analyze",
        "benchmark",
        "compare",
        "evaluate",
        "find",
        "identify",
        "investigate",
        "market",
        "options",
        "research",
        "requirements",
        "review",
        "source",
        "vendor",
      ],
    },
    {
      id: "document_writer",
      label: "Document drafting",
      capability:
        "Drafts briefs, plans, outlines, scripts, templates, reports, summaries, and decision memos.",
      keywords: [
        "brief",
        "content",
        "copy",
        "draft",
        "memo",
        "outline",
        "plan",
        "proposal",
        "report",
        "script",
        "summarize",
        "template",
        "write",
      ],
    },
    {
      id: "data_table",
      label: "Tables and analysis",
      capability:
        "Builds trackers, budgets, scorecards, estimates, calculations, and structured comparison tables.",
      keywords: [
        "budget",
        "calculate",
        "cost",
        "estimate",
        "forecast",
        "metrics",
        "scorecard",
        "spreadsheet",
        "table",
        "track",
        "tracker",
      ],
    },
    {
      id: "communications",
      label: "Communications",
      capability:
        "Drafts emails, follow-ups, stakeholder updates, outreach messages, and response templates.",
      keywords: [
        "contact",
        "email",
        "follow up",
        "follow-up",
        "invite",
        "message",
        "notify",
        "outreach",
        "respond",
        "stakeholder",
        "update",
      ],
    },
    {
      id: "calendar_scheduler",
      label: "Scheduling",
      capability:
        "Creates timelines, milestone plans, deadline maps, appointment drafts, and meeting schedules.",
      keywords: [
        "appointment",
        "book",
        "calendar",
        "deadline",
        "meeting",
        "milestone",
        "schedule",
        "timeline",
      ],
    },
    {
      id: "forms_records",
      label: "Forms and records",
      capability:
        "Prepares applications, intake forms, documentation packets, checklists, and file-ready records.",
      keywords: [
        "application",
        "checklist",
        "documentation",
        "file",
        "form",
        "intake",
        "packet",
        "record",
        "submit",
        "upload",
      ],
    },
    {
      id: "code_automation",
      label: "Code and automation",
      capability:
        "Writes small scripts, automations, API workflows, tests, parsers, and repeatable data-processing jobs.",
      keywords: [
        "api",
        "automate",
        "code",
        "deploy",
        "integrate",
        "parse",
        "prototype",
        "script",
        "test",
      ],
    },
    {
      id: "workflow_runner",
      label: "Workflow execution",
      capability:
        "Organizes repeatable work, tracks status, prepares handoffs, sequences steps, and reviews completion criteria.",
      keywords: [
        "assign",
        "coordinate",
        "handoff",
        "monitor",
        "organize",
        "prioritize",
        "review",
        "sequence",
        "status",
        "workflow",
      ],
    },
  ] satisfies MockAgentTool[],
} as const;

const PHYSICAL_ONLY_PATTERNS = [
  /\battend\b/,
  /\barrive\b/,
  /\bassemble\b/,
  /\bclean\b/,
  /\bcook\b/,
  /\bdeliver\b/,
  /\bdrive\b/,
  /\bdrop off\b/,
  /\bexercise\b/,
  /\binstall\b/,
  /\bin person\b/,
  /\bin-person\b/,
  /\blift\b/,
  /\bmove\b/,
  /\bpaint\b/,
  /\bpick up\b/,
  /\brepair\b/,
  /\brun\b/,
  /\bship\b/,
  /\btravel\b/,
  /\bvisit\b/,
  /\bwalk\b/,
  /\bworkout\b/,
];

const AGENT_COMPLETION_PATTERNS = [
  /\banaly[sz]e\b/,
  /\bautomate\b/,
  /\bbook\b/,
  /\bcalculate\b/,
  /\bcode\b/,
  /\bcompare\b/,
  /\bcoordinate\b/,
  /\bdocument\b/,
  /\bdraft\b/,
  /\bemail\b/,
  /\bevaluate\b/,
  /\bfind\b/,
  /\bidentify\b/,
  /\bmessage\b/,
  /\borganize\b/,
  /\bplan\b/,
  /\bprepare\b/,
  /\bresearch\b/,
  /\breview\b/,
  /\bschedule\b/,
  /\bsummari[sz]e\b/,
  /\btrack\b/,
  /\bwrite\b/,
];

function taskText(task: Task) {
  return [
    task.title,
    task.description,
    task.success_criteria,
    task.relative_timing,
    task.due,
    ...task.depends_on,
  ]
    .filter(Boolean)
    .join(" ")
    .toLowerCase();
}

function matchTools(text: string) {
  return MOCK_FIELD_AGENT.tools.filter((tool) =>
    tool.keywords.some((keyword) => text.includes(keyword))
  );
}

function hasPattern(text: string, patterns: RegExp[]) {
  return patterns.some((pattern) => pattern.test(text));
}

function canAgentCompleteTask(text: string, tools: readonly MockAgentTool[]) {
  if (tools.length === 0) {
    return false;
  }

  const hasPhysicalAction = hasPattern(text, PHYSICAL_ONLY_PATTERNS);
  const hasAgentAction = hasPattern(text, AGENT_COMPLETION_PATTERNS);
  return !hasPhysicalAction || hasAgentAction;
}

export function assessAgentCapability(node: Node): AgentCapabilityMatch | null {
  const tasks = node.plan?.tasks ?? [];
  if (node.status !== "PLANNED" || tasks.length === 0) {
    return null;
  }

  const taskMatches = tasks.map((task) => {
    const text = taskText(task);
    const tools = matchTools(text);
    return {
      tools,
      executable: canAgentCompleteTask(text, tools),
    };
  });

  const executableTaskCount = taskMatches.filter((match) => match.executable).length;
  const requiredTaskCount = Math.max(1, Math.ceil(tasks.length * 0.6));
  if (executableTaskCount < requiredTaskCount) {
    return null;
  }

  const toolIds = new Set<string>();
  const tools = taskMatches
    .flatMap((match) => match.tools)
    .filter((tool) => {
      if (toolIds.has(tool.id)) {
        return false;
      }
      toolIds.add(tool.id);
      return true;
    })
    .map(({ id, label, capability }) => ({ id, label, capability }));

  const confidence =
    executableTaskCount === tasks.length && tools.length >= 2 ? "high" : "medium";
  const toolLabels = tools.slice(0, 3).map((tool) => tool.label).join(", ");

  return {
    agentId: MOCK_FIELD_AGENT.id,
    agentName: MOCK_FIELD_AGENT.name,
    confidence,
    tools,
    executableTaskCount,
    totalTaskCount: tasks.length,
    rationale: `${executableTaskCount}/${tasks.length} tasks match ${toolLabels || "available agent tools"}.`,
  };
}
