import type {
  Node,
  NodeProgress,
  Task,
  VisibleStage,
  VisibleStageId,
  WorkflowStage,
} from "@/lib/types";

export type TimelineStepState = "complete" | "current" | "upcoming" | "loading";

export interface WorkflowTimelineStep {
  id: "baseline" | "questioning" | "build" | "select" | "plan";
  title: string;
  actor: "You" | "System";
  description: string;
  state: TimelineStepState;
}

interface DeriveWorkflowTimelineArgs {
  workflowStage: WorkflowStage;
  hasLayerChildren: boolean;
  draftNodeCount: number;
  draftingQuestionsPending: boolean;
  hasActiveDraftingQuestion: boolean;
  allDraftingQuestionsAnswered: boolean;
  activeOperationLabel: string | null;
}

function isPlanOperation(label: string | null) {
  const normalized = (label ?? "").toLowerCase();
  return (
    normalized.includes("plan") ||
    normalized.includes("task toggle") ||
    normalized.includes("subgoal toggle")
  );
}

function stepState(
  step: WorkflowTimelineStep["id"],
  args: DeriveWorkflowTimelineArgs
): TimelineStepState {
  const planOperation = isPlanOperation(args.activeOperationLabel);

  if (step === "baseline") {
    if (args.workflowStage === "drafting" && !args.hasLayerChildren) {
      return args.activeOperationLabel ? "loading" : "current";
    }
    return args.hasLayerChildren ? "complete" : "upcoming";
  }

  if (step === "questioning") {
    const questioningActive =
      args.workflowStage === "drafting" &&
      args.hasLayerChildren &&
      args.draftNodeCount > 0 &&
      (args.draftingQuestionsPending ||
        args.hasActiveDraftingQuestion ||
        args.allDraftingQuestionsAnswered);

    if (questioningActive) {
      return args.draftingQuestionsPending ? "loading" : "current";
    }
    return args.hasLayerChildren && args.draftNodeCount === 0 ? "complete" : "upcoming";
  }

  if (step === "build") {
    if (args.workflowStage === "building" && !planOperation) {
      return "loading";
    }
    if (
      args.hasLayerChildren &&
      (args.workflowStage === "selecting" || args.workflowStage === "planning")
    ) {
      return "complete";
    }
    return "upcoming";
  }

  if (step === "select") {
    if (args.workflowStage === "selecting") {
      return "current";
    }
    if (args.workflowStage === "planning") {
      return "complete";
    }
    return "upcoming";
  }

  if (args.workflowStage === "planning") {
    return planOperation ? "loading" : "current";
  }
  return "upcoming";
}

export function deriveWorkflowTimeline(
  args: DeriveWorkflowTimelineArgs
): WorkflowTimelineStep[] {
  const buildDescription =
    args.workflowStage === "building"
      ? args.activeOperationLabel ?? "System is building the next executable layer."
      : "System turns baseline answers into baselined and planned goals.";
  const planDescription =
    isPlanOperation(args.activeOperationLabel)
      ? args.activeOperationLabel ?? "System is updating the selected plan."
      : "Review tasks, edit details, and decide when to deepen the selected goal.";

  const steps: Array<Omit<WorkflowTimelineStep, "state">> = [
    {
      id: "baseline",
      title: "Baseline",
      actor: "You",
      description: "Set the goal frame before the first layer exists.",
    },
    {
      id: "questioning",
      title: "Questioning",
      actor: "You",
      description: "Answer evidence-based questions to clarify execution reality.",
    },
    {
      id: "build",
      title: "Build Graph",
      actor: "System",
      description: buildDescription,
    },
    {
      id: "select",
      title: "Select Goal",
      actor: "You",
      description: "Choose the goal you want to inspect or refine next.",
    },
    {
      id: "plan",
      title: "Plan Goal",
      actor: "You",
      description: planDescription,
    },
  ];

  return steps.map((step) => ({
    ...step,
    state: stepState(step.id, args),
  }));
}

export function formatTaskRollup(task: Task) {
  const parts = [task.relative_timing, task.due].filter(Boolean);
  return parts.length > 0 ? parts.join(" · ") : "Timing not set";
}

export function nextNodeAction(node: Node | null, progress: NodeProgress | null) {
  if (!node) {
    return "Select a goal to inspect details.";
  }

  if (node.status === "DRAFT") {
    return "Edit or clarify this goal before planning.";
  }

  if (node.status === "BASELINED") {
    return "Generate a plan.";
  }

  if (!progress || progress.total_tasks === 0) {
    return "Generate tasks for this goal.";
  }

  const nextTask = node.plan?.tasks.find((task) => !task.completed) ?? null;
  if (nextTask) {
    const timing = formatTaskRollup(nextTask);
    return `${timing}: ${nextTask.title}`;
  }

  if (node.children_ids.length > 0) {
    return "All tasks are complete. Deepen the goal or review outcomes.";
  }

  return "All tasks are complete for this goal.";
}

interface VisibleStageArgs {
  workflowStage: WorkflowStage;
  hasLayerChildren: boolean;
  selectedNode: Node | null;
  hasActiveDraftingQuestion: boolean;
  draftingQuestionsPending: boolean;
  allDraftingQuestionsAnswered: boolean;
  activeOperationLabel: string | null;
}

export function deriveVisibleStageId(args: VisibleStageArgs): VisibleStageId {
  if (args.workflowStage === "welcome") {
    return "define";
  }

  if (args.workflowStage === "building") {
    return "build";
  }

  if (args.workflowStage === "drafting" && !args.hasLayerChildren) {
    return "define";
  }

  if (args.workflowStage === "drafting") {
    return "clarify";
  }

  return "refine";
}

export function buildVisibleStages(args: VisibleStageArgs): VisibleStage[] {
  const activeStageId = deriveVisibleStageId(args);
  const refinePrimaryLabel =
    args.selectedNode?.status === "BASELINED"
      ? "Generate plan"
      : args.selectedNode?.status === "PLANNED"
        ? "Open editor"
        : args.selectedNode
          ? "Convert goal"
          : "Select a goal";

  const stages: Record<VisibleStageId, VisibleStage> = {
    define: {
      id: "define",
      title: "Define",
      description: "Decompose this goal when ready.",
      primaryActionLabel: "Decompose goal",
      helpText: "Quiet until the first layer exists.",
    },
    clarify: {
      id: "clarify",
      title: "Clarify",
      description: args.hasActiveDraftingQuestion
        ? "Answer the next question."
        : args.draftingQuestionsPending
          ? "Preparing the next prompt."
          : args.allDraftingQuestionsAnswered
            ? "Questions are complete."
            : "Clarify this layer before building.",
      primaryActionLabel: args.hasActiveDraftingQuestion ? "Send answer" : "Build graph",
      helpText: "Keep answers concrete.",
    },
    build: {
      id: "build",
      title: "Build",
      description: args.activeOperationLabel ?? "Goals are streaming in.",
      primaryActionLabel: "Building graph",
      helpText: "Updates arrive one goal at a time.",
    },
    refine: {
      id: "refine",
      title: "Refine",
      description: args.selectedNode
        ? `Adjust ${args.selectedNode.title.trim() || "this goal"} or go deeper.`
        : "Pick a goal to edit or deepen.",
      primaryActionLabel: refinePrimaryLabel,
      helpText: "Keep the canvas clean.",
    },
  };

  return (["define", "clarify", "build", "refine"] as const).map((stageId) => ({
    ...stages[stageId],
    title: stages[stageId].title,
    description: stages[stageId].description,
  }));
}

export function visibleStageTitle(stageId: VisibleStageId) {
  return buildVisibleStages({
    workflowStage: "welcome",
    hasLayerChildren: false,
    selectedNode: null,
    hasActiveDraftingQuestion: false,
    draftingQuestionsPending: false,
    allDraftingQuestionsAnswered: false,
    activeOperationLabel: null,
  }).find((stage) => stage.id === stageId)?.title ?? "Define";
}
