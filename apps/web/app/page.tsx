"use client";

import type { ReactNode } from "react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import "reactflow/dist/style.css";
import {
  ArrowLeft,
  ArrowRight,
  LayoutGrid,
  Loader2,
  Maximize2,
  Plus,
  Sparkles,
} from "lucide-react";

import { GoalGraph } from "@/components/app/goal-graph";
import {
  NodeEditorDialog,
  type NodeEditorDialogMode,
  type NodeEditorSubmitPayload,
} from "@/components/app/node-editor-dialog";
import { NodeDetailSidebar } from "@/components/app/node-detail-sidebar";
import { StageChatPanel } from "@/components/app/stage-chat-panel";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Sheet, SheetContent } from "@/components/ui/sheet";
import { Textarea } from "@/components/ui/textarea";
import type { AgentCapabilityMatch } from "@/lib/agent-capabilities";
import { buildPathIds, displayNodeTitle } from "@/lib/graph-paths";
import {
  buildLayer,
  fetchBaselineQuestions,
  fetchGraph,
  fetchSession,
  fetchStatus,
  getJob,
  initGraph,
  mutateGraph,
  postJob,
  saveSession,
  streamJobEvents,
  updateFocus,
} from "@/lib/api";
import type {
  BaselineQuestion,
  Graph,
  GraphMutationAction,
  GraphResponse,
  JobEvent,
  Node,
  NodePosition,
  NodeProgress,
  UISessionMetadata,
  VisibleStageId,
  WorkflowStage,
} from "@/lib/types";
import { cn } from "@/lib/utils";
import { buildVisibleStages, deriveVisibleStageId } from "@/lib/workflow";

const DEFAULT_GRAPH_PATH = "out/graph.json";
const DEFAULT_SESSION_ID = "local-session";
const GRAPH_TOOLBAR_DRAG_TYPE = "application/x-goal-ai-node";
const EMPTY_SMART_FIELDS = {
  specific: "",
  measurable: "",
  achievable: "",
  relevant: "",
  time_bound: "",
} as const;

type BaselineAnswerMap = Record<string, string>;

function graphMissing(message: string | null) {
  return (message ?? "").includes("Graph file not found");
}

function normalizeAnswerMap(value: unknown): BaselineAnswerMap {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return {};
  }

  const next: BaselineAnswerMap = {};
  for (const [key, answer] of Object.entries(value as Record<string, unknown>)) {
    if (typeof answer === "string") {
      next[key] = answer;
    }
  }
  return next;
}

function firstUnansweredIndex(
  questions: BaselineQuestion[],
  answers: BaselineAnswerMap
) {
  const nextIndex = questions.findIndex((question) => !(answers[question.id] ?? "").trim());
  return nextIndex === -1 ? questions.length : nextIndex;
}

function logJobEvent(message: string) {
  if (process.env.NODE_ENV !== "production") {
    console.info(`[smartgot] ${message}`);
  }
}

function resolveSelectedNodeId(
  graph: Graph,
  currentId?: string | null,
  preferredId?: string | null
) {
  if (preferredId && graph.nodes[preferredId]) {
    return preferredId;
  }
  if (currentId && graph.nodes[currentId]) {
    return currentId;
  }
  const focusParent = graph.nodes[graph.focus_parent_id] ?? graph.nodes[graph.root_id];
  const layerChild = focusParent?.children_ids.find((childId) => graph.nodes[childId]);
  return layerChild ?? graph.root_id;
}

function resolveStage(
  payload: GraphResponse,
  selectedNodeId: string,
  preferredStage?: WorkflowStage
): WorkflowStage {
  if (preferredStage === "welcome" || preferredStage === "building") {
    return preferredStage;
  }

  const selectedNode = payload.graph.nodes[selectedNodeId];
  if (
    preferredStage === "planning" &&
    selectedNode &&
    selectedNode.status === "PLANNED"
  ) {
    return "planning";
  }
  if (preferredStage === "selecting") {
    return "selecting";
  }
  return payload.workflow.stage === "drafting" ? "drafting" : "selecting";
}

function findCreatedNodeId(beforeGraph: Graph | null, afterGraph: Graph) {
  if (!beforeGraph) {
    return afterGraph.root_id;
  }

  for (const nodeId of Object.keys(afterGraph.nodes)) {
    if (!beforeGraph.nodes[nodeId]) {
      return nodeId;
    }
  }
  return null;
}

export default function HomePage() {
  const [graphPath] = useState(DEFAULT_GRAPH_PATH);
  const [sessionId] = useState(DEFAULT_SESSION_ID);
  const [graphData, setGraphData] = useState<GraphResponse | null>(null);
  const [selectedNodeId, setSelectedNodeId] = useState("root");
  const [workflowStage, setWorkflowStage] = useState<WorkflowStage>("welcome");
  const [chatInput, setChatInput] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [activeJobId, setActiveJobId] = useState<string | null>(null);
  const [busyNodeId, setBusyNodeId] = useState<string | null>(null);
  const [activeOperationLabel, setActiveOperationLabel] = useState<string | null>(null);
  const [newGoalTitle, setNewGoalTitle] = useState("");
  const [creatingGraph, setCreatingGraph] = useState(false);
  const [draftingQuestions, setDraftingQuestions] = useState<BaselineQuestion[]>([]);
  const [draftingAnswers, setDraftingAnswers] = useState<BaselineAnswerMap>({});
  const [draftingParentId, setDraftingParentId] = useState<string | null>(null);
  const [draftingQuestionIndex, setDraftingQuestionIndex] = useState(0);
  const [draftingQuestionsError, setDraftingQuestionsError] = useState<string | null>(null);
  const [editorMode, setEditorMode] = useState<NodeEditorDialogMode>(null);
  const [editorPending, setEditorPending] = useState(false);
  const [inspectorOpen, setInspectorOpen] = useState(false);
  const [canvasApi, setCanvasApi] = useState<{ fitView: () => void } | null>(null);

  const lastKnownUpdatedAtRef = useRef("");
  const lastLocalMutationAtRef = useRef(0);
  const selectedNodeIdRef = useRef("root");
  const composerTextareaRef = useRef<HTMLTextAreaElement | null>(null);

  useEffect(() => {
    if (error) {
      console.error("[smartgot]", error);
    }
  }, [error]);

  const graph = graphData?.graph ?? null;
  const nodeProgress = useMemo(() => graphData?.node_progress ?? {}, [graphData]);
  const focusParent = graph
    ? graph.nodes[graph.focus_parent_id] ?? graph.nodes[graph.root_id] ?? null
    : null;
  const selectedNode = graph ? graph.nodes[selectedNodeId] ?? null : null;

  const layerNodes = useMemo(() => {
    if (!graph || !focusParent) {
      return [] as Node[];
    }
    return focusParent.children_ids
      .map((childId) => graph.nodes[childId])
      .filter((node): node is Node => Boolean(node));
  }, [focusParent, graph]);
  const breadcrumbNodes = useMemo(() => {
    if (!graph || !focusParent) {
      return [] as Node[];
    }
    return buildPathIds(graph, focusParent.id)
      .map((nodeId) => graph.nodes[nodeId])
      .filter((node): node is Node => Boolean(node));
  }, [focusParent, graph]);

  const hasLayerChildren = layerNodes.length > 0;
  const draftNodeCount = layerNodes.filter((node) => node.status === "DRAFT").length;
  const selectedProgress = selectedNode ? nodeProgress[selectedNode.id] ?? null : null;
  const currentDraftingQuestion =
    workflowStage === "drafting" && draftNodeCount > 0
      ? draftingQuestions[draftingQuestionIndex] ?? null
      : null;
  const allDraftingQuestionsAnswered =
    workflowStage === "drafting" &&
    draftNodeCount > 0 &&
    draftingQuestions.length > 0 &&
    draftingQuestionIndex >= draftingQuestions.length;
  const draftingQuestionsPending =
    workflowStage === "drafting" &&
    hasLayerChildren &&
    draftNodeCount > 0 &&
    draftingQuestions.length === 0 &&
    !draftingQuestionsError;
  const showWelcome = !graph || workflowStage === "welcome";

  const visibleStages = useMemo(
    () =>
      buildVisibleStages({
        workflowStage,
        hasLayerChildren,
        selectedNode,
        hasActiveDraftingQuestion: Boolean(currentDraftingQuestion),
        draftingQuestionsPending,
        allDraftingQuestionsAnswered,
        activeOperationLabel,
      }),
    [
      activeOperationLabel,
      allDraftingQuestionsAnswered,
      currentDraftingQuestion,
      draftingQuestionsPending,
      hasLayerChildren,
      selectedNode,
      workflowStage,
    ]
  );

  const visibleStageId = useMemo<VisibleStageId>(
    () =>
      deriveVisibleStageId({
        workflowStage,
        hasLayerChildren,
        selectedNode,
        hasActiveDraftingQuestion: Boolean(currentDraftingQuestion),
        draftingQuestionsPending,
        allDraftingQuestionsAnswered,
        activeOperationLabel,
      }),
    [
      activeOperationLabel,
      allDraftingQuestionsAnswered,
      currentDraftingQuestion,
      draftingQuestionsPending,
      hasLayerChildren,
      selectedNode,
      workflowStage,
    ]
  );
  const activeVisibleStage = visibleStages.find((stage) => stage.id === visibleStageId);

  const resetDraftingState = useCallback(() => {
    setDraftingQuestions([]);
    setDraftingAnswers({});
    setDraftingParentId(null);
    setDraftingQuestionIndex(0);
    setDraftingQuestionsError(null);
    setChatInput("");
  }, []);

  const applyGraphPayload = useCallback(
    (
      payload: GraphResponse,
      options?: {
        preferredSelectedNodeId?: string | null;
        preferredStage?: WorkflowStage;
        keepStage?: boolean;
      }
    ) => {
      setGraphData(payload);
      lastKnownUpdatedAtRef.current = payload.graph.updated_at;

      const nextSelectedNodeId = resolveSelectedNodeId(
        payload.graph,
        selectedNodeIdRef.current,
        options?.preferredSelectedNodeId
      );
      selectedNodeIdRef.current = nextSelectedNodeId;
      setSelectedNodeId(nextSelectedNodeId);

      if (!options?.keepStage) {
        setWorkflowStage(resolveStage(payload, nextSelectedNodeId, options?.preferredStage));
      }

      setError(null);
    },
    []
  );

  const refreshGraph = useCallback(
    async (options?: {
      preferredSelectedNodeId?: string | null;
      preferredStage?: WorkflowStage;
      keepStage?: boolean;
    }) => {
      const payload = await fetchGraph(graphPath);
      applyGraphPayload(payload, options);
    },
    [applyGraphPayload, graphPath]
  );

  const syncComposerHeight = useCallback(() => {
    const textarea = composerTextareaRef.current;
    if (!textarea) {
      return;
    }
    textarea.style.height = "0px";
    textarea.style.height = `${Math.min(textarea.scrollHeight, 160)}px`;
  }, []);

  const consumeJob = useCallback(
    async (
      accepted: { job_id: string },
      label: string,
      options?: {
        preferredStage?: WorkflowStage;
        preferredSelectedNodeId?: string | null;
      }
    ) => {
      setActiveJobId(accepted.job_id);
      setActiveOperationLabel(label);

      try {
        await new Promise<void>((resolve, reject) => {
          const stream = streamJobEvents(accepted.job_id, (event) => {
            if (event.graph_snapshot) {
              applyGraphPayload(event.graph_snapshot, {
                preferredSelectedNodeId:
                  options?.preferredSelectedNodeId ??
                  (event.changed_node_ids?.[0] ?? selectedNodeIdRef.current),
                keepStage: true,
              });
            }

            logJobEvent(event.message);

            if (event.type === "completed") {
              stream.close();
              resolve();
            }
            if (event.type === "failed") {
              stream.close();
              reject(new Error(event.message));
            }
          });

          stream.onerror = () => {
            stream.close();
            reject(new Error("SSE stream error"));
          };
        });

        const record = await getJob(accepted.job_id);
        if (record.status !== "succeeded") {
          throw new Error(record.error ?? `${label} failed`);
        }
      } finally {
        setActiveJobId(null);
        setActiveOperationLabel(null);
      }
    },
    [applyGraphPayload]
  );

  const runJob = useCallback(
    async (
      endpoint: string,
      body: Record<string, unknown>,
      label: string,
      options?: {
        preferredStage?: WorkflowStage;
        preferredSelectedNodeId?: string | null;
      }
    ) => {
      setError(null);
      const accepted = await postJob(endpoint, { ...body, path: graphPath });
      await consumeJob(accepted, label, options);
      lastLocalMutationAtRef.current = Date.now();
      await refreshGraph({
        preferredSelectedNodeId: options?.preferredSelectedNodeId,
        preferredStage: options?.preferredStage,
      });
    },
    [consumeJob, graphPath, refreshGraph]
  );

  const applyGraphMutation = useCallback(
    async (
      mutation: GraphMutationAction,
      options?: {
        preferredSelectedNodeId?: string | null;
        preferredStage?: WorkflowStage;
      }
    ) => {
      const beforeGraph = graph;
      const payload = await mutateGraph(graphPath, mutation);
      lastLocalMutationAtRef.current = Date.now();
      applyGraphPayload(payload, {
        preferredSelectedNodeId:
          options?.preferredSelectedNodeId ??
          findCreatedNodeId(beforeGraph, payload.graph) ??
          options?.preferredSelectedNodeId,
        preferredStage: options?.preferredStage,
      });
      return payload;
    },
    [applyGraphPayload, graph, graphPath]
  );

  useEffect(() => {
    selectedNodeIdRef.current = selectedNodeId;
  }, [selectedNodeId]);

  useEffect(() => {
    let cancelled = false;

    async function init() {
      setLoading(true);

      try {
        const session = await fetchSession(sessionId).catch(() => null);
        const metadata = (session?.metadata ?? {}) as UISessionMetadata;

        if (!cancelled) {
          setChatInput(typeof metadata.chatInput === "string" ? metadata.chatInput : "");
          setDraftingParentId(
            typeof metadata.draftingParentId === "string" ? metadata.draftingParentId : null
          );
          setDraftingQuestionIndex(
            typeof metadata.draftingQuestionIndex === "number"
              ? metadata.draftingQuestionIndex
              : 0
          );
          setDraftingAnswers(normalizeAnswerMap(metadata.draftingAnswers));
        }

        try {
          const payload = await fetchGraph(graphPath);
          if (cancelled) {
            return;
          }
          applyGraphPayload(payload, {
            preferredSelectedNodeId:
              typeof metadata.selectedNodeId === "string" ? metadata.selectedNodeId : null,
            preferredStage: metadata.workflowStage,
          });
        } catch (err) {
          const message = err instanceof Error ? err.message : String(err);
          if (cancelled) {
            return;
          }
          if (graphMissing(message)) {
            setGraphData(null);
            setSelectedNodeId("root");
            setWorkflowStage("welcome");
            setError(null);
          } else {
            setError(message);
          }
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }

    void init();

    return () => {
      cancelled = true;
    };
  }, [applyGraphPayload, graphPath, sessionId]);

  useEffect(() => {
    if (!graph || activeJobId) {
      return;
    }

    const interval = window.setInterval(() => {
      void (async () => {
        try {
          const status = await fetchStatus(graphPath);
          if (status.updated_at !== lastKnownUpdatedAtRef.current) {
            const externalChange = Date.now() - lastLocalMutationAtRef.current > 2500;
            await refreshGraph({ keepStage: externalChange ? false : undefined });
          }
        } catch {
          // Ignore polling errors until the next user action.
        }
      })();
    }, 4000);

    return () => window.clearInterval(interval);
  }, [activeJobId, graph, graphPath, refreshGraph]);

  useEffect(() => {
    if (loading) {
      return;
    }

    const timeout = window.setTimeout(() => {
      void saveSession(sessionId, [], {
        selectedNodeId,
        workflowStage,
        graphPath,
        chatInput,
        draftingParentId,
        draftingQuestionIndex,
        draftingAnswers,
      });
    }, 500);

    return () => window.clearTimeout(timeout);
  }, [
    chatInput,
    draftingAnswers,
    draftingParentId,
    draftingQuestionIndex,
    graphPath,
    loading,
    selectedNodeId,
    sessionId,
    workflowStage,
  ]);

  useEffect(() => {
    if (!layerNodes.length) {
      return;
    }
    if (!layerNodes.some((node) => node.id === selectedNodeId)) {
      setSelectedNodeId(layerNodes[0].id);
    }
  }, [layerNodes, selectedNodeId]);

  useEffect(() => {
    if (!focusParent || workflowStage !== "drafting") {
      return;
    }

    if (draftNodeCount === 0) {
      const hasDraftingState =
        draftingQuestions.length > 0 ||
        Object.keys(draftingAnswers).length > 0 ||
        draftingQuestionIndex !== 0 ||
        draftingParentId !== focusParent.id;

      if (hasDraftingState) {
        setDraftingQuestions([]);
        setDraftingAnswers({});
        setDraftingParentId(focusParent.id);
        setDraftingQuestionIndex(0);
        setDraftingQuestionsError(null);
      }
      return;
    }

    if (draftingParentId === focusParent.id && draftingQuestions.length > 0) {
      return;
    }
    if (draftingParentId === focusParent.id && draftingQuestionsError) {
      return;
    }

    let cancelled = false;
    setDraftingQuestionsError(null);

    void (async () => {
      try {
        const payload = await fetchBaselineQuestions(focusParent.id, graphPath);
        if (cancelled) {
          return;
        }

        const restoredAnswers =
          draftingParentId === focusParent.id ? draftingAnswers : {};
        const nextAnswers: BaselineAnswerMap = {};
        for (const question of payload.questions) {
          nextAnswers[question.id] = restoredAnswers[question.id] ?? "";
        }

        setDraftingQuestions(payload.questions);
        setDraftingParentId(focusParent.id);
        setDraftingAnswers(nextAnswers);
        setDraftingQuestionIndex(firstUnansweredIndex(payload.questions, nextAnswers));
        setDraftingQuestionsError(null);
      } catch (err) {
        if (!cancelled) {
          const message = err instanceof Error ? err.message : String(err);
          setError(message);
          setDraftingParentId(focusParent.id);
          setDraftingQuestionsError(message);
        }
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [
    draftNodeCount,
    draftingAnswers,
    draftingParentId,
    draftingQuestionIndex,
    draftingQuestionsError,
    draftingQuestions.length,
    focusParent,
    graphPath,
    workflowStage,
  ]);

  useEffect(() => {
    syncComposerHeight();
  }, [chatInput, syncComposerHeight, workflowStage]);

  const handleCreateGraph = useCallback(async () => {
    const goal = newGoalTitle.trim();
    if (!goal) {
      setError("Goal title is required.");
      return;
    }

    setCreatingGraph(true);
    setError(null);

    try {
      const payload = await initGraph(graphPath, goal, true);
      setChatInput("");
      resetDraftingState();
      setNewGoalTitle("");
      applyGraphPayload(payload, {
        preferredSelectedNodeId: payload.graph.root_id,
        preferredStage: "building",
      });
      logJobEvent(`Decomposing the first layer for ${goal}.`);

      const accepted = await postJob("decompose", {
        path: graphPath,
        node_id: payload.graph.root_id,
        target_children: 7,
        min_children: 5,
        max_children: 9,
      });
      await consumeJob(accepted, "Decomposing first layer", {
        preferredSelectedNodeId: payload.graph.root_id,
        preferredStage: "drafting",
      });
      lastLocalMutationAtRef.current = Date.now();
      resetDraftingState();
      await refreshGraph({
        preferredSelectedNodeId: payload.graph.root_id,
        preferredStage: "drafting",
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setWorkflowStage((currentStage) => (currentStage === "building" ? "drafting" : "welcome"));
    } finally {
      setCreatingGraph(false);
    }
  }, [
    applyGraphPayload,
    consumeJob,
    graphPath,
    newGoalTitle,
    refreshGraph,
    resetDraftingState,
  ]);

  const handleReplaceGoal = useCallback(() => {
    setNewGoalTitle("");
    setChatInput("");
    resetDraftingState();
    setError(null);
    setWorkflowStage("welcome");
  }, [resetDraftingState]);

  const handleSubmitDraftingAnswer = useCallback(() => {
    if (!currentDraftingQuestion) {
      return;
    }

    const answer = chatInput.trim();
    if (!answer) {
      setError("Answer is required.");
      return;
    }

    setDraftingAnswers((previous) => ({
      ...previous,
      [currentDraftingQuestion.id]: answer,
    }));
    setDraftingQuestionIndex((previous) => previous + 1);
    setChatInput("");
    setError(null);
  }, [
    chatInput,
    currentDraftingQuestion,
  ]);

  const handleBuildLayer = useCallback(async () => {
    if (!focusParent) {
      return;
    }

    if (!hasLayerChildren) {
      logJobEvent(`Decomposing the first layer for ${focusParent.title}.`);
      setWorkflowStage("building");
      try {
        await runJob(
          "decompose",
          {
            node_id: focusParent.id,
            target_children: 7,
            min_children: 5,
            max_children: 9,
          },
          "Decomposing first layer",
          {
            preferredSelectedNodeId: focusParent.id,
            preferredStage: "drafting",
          }
        );
        resetDraftingState();
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
        setWorkflowStage("drafting");
      }
      return;
    }

    if (draftNodeCount > 0 && !allDraftingQuestionsAnswered) {
      setError("Finish the clarification questions before building the graph.");
      return;
    }

    const layerQaPairs =
      draftNodeCount === 0
        ? []
        : draftingQuestions.map((question) => ({
            id: question.id,
            question: question.question,
            category: question.category,
            answer: draftingAnswers[question.id] ?? "",
          }));

    setWorkflowStage("building");
    try {
      const accepted = await buildLayer(graphPath, focusParent.id, layerQaPairs);
      await consumeJob(accepted, "Building graph", {
        preferredSelectedNodeId: selectedNodeId,
        preferredStage: "selecting",
      });
      lastLocalMutationAtRef.current = Date.now();
      resetDraftingState();
      await refreshGraph({ preferredStage: "selecting" });
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setWorkflowStage("drafting");
    }
  }, [
    allDraftingQuestionsAnswered,
    consumeJob,
    draftNodeCount,
    draftingAnswers,
    draftingQuestions,
    focusParent,
    graphPath,
    hasLayerChildren,
    refreshGraph,
    resetDraftingState,
    runJob,
    selectedNodeId,
  ]);

  const handleBackLayer = useCallback(async () => {
    if (!graph || !focusParent?.parent_id) {
      return;
    }

    const parentId = focusParent.parent_id;
    await updateFocus({
      path: graphPath,
      focus_parent_id: parentId,
      active_layer: (graph.nodes[parentId]?.layer ?? 0) + 1,
    });
    resetDraftingState();
    await refreshGraph({ preferredSelectedNodeId: parentId });
  }, [focusParent, graph, graphPath, refreshGraph, resetDraftingState]);

  const handleGoDeeper = useCallback(async () => {
    if (!selectedNode || selectedNode.status !== "PLANNED") {
      return;
    }

    await updateFocus({
      path: graphPath,
      focus_parent_id: selectedNode.id,
      active_layer: selectedNode.layer + 1,
    });
    resetDraftingState();
    await refreshGraph({ preferredSelectedNodeId: selectedNode.id });
  }, [graphPath, refreshGraph, resetDraftingState, selectedNode]);

  const handleFocusSelectedNode = useCallback(
    async (nodeId: string) => {
      if (!graph) {
        return;
      }
      const node = graph.nodes[nodeId];
      if (!node) {
        return;
      }
      const layerParentId = node.parent_id ?? graph.root_id;
      await updateFocus({
        path: graphPath,
        focus_parent_id: layerParentId,
        active_layer: (graph.nodes[layerParentId]?.layer ?? 0) + 1,
      });
      resetDraftingState();
      await refreshGraph({ preferredSelectedNodeId: nodeId });
    },
    [graph, graphPath, refreshGraph, resetDraftingState]
  );

  const handleGeneratePlan = useCallback(async () => {
    if (!selectedNode) {
      return;
    }
    setBusyNodeId(selectedNode.id);
    try {
      await runJob(
        "plan-generate",
        { node_id: selectedNode.id },
        "Generating goal plan",
        {
          preferredSelectedNodeId: selectedNode.id,
          preferredStage: "planning",
        }
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusyNodeId(null);
    }
  }, [runJob, selectedNode]);

  const handleAgentAssist = useCallback(
    (nodeId: string, match: AgentCapabilityMatch) => {
      const node = graph?.nodes[nodeId] ?? null;
      setSelectedNodeId(nodeId);
      setWorkflowStage("planning");
      setInspectorOpen(true);
      logJobEvent(
        `${match.agentName} is available for ${
          node ? displayNodeTitle(node) : "this goal"
        }: ${match.rationale}`
      );
    },
    [graph]
  );

  const handleToggleTask = useCallback(
    async (nodeId: string, taskIndex: number, completed: boolean) => {
      const node = graph?.nodes[nodeId];
      if (!node) {
        return;
      }
      try {
        await runJob(
          "task-toggle",
          {
            node_id: nodeId,
            task_index: taskIndex,
            completed,
          },
          "Updating task",
          {
            preferredSelectedNodeId: nodeId,
            preferredStage: node.status === "PLANNED" ? "planning" : workflowStage,
          }
        );
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      }
    },
    [graph, runJob, workflowStage]
  );

  const openEditorForSelection = useCallback(() => {
    if (!selectedNode) {
      return;
    }
    setEditorMode({
      kind: "edit",
      nodeId: selectedNode.id,
    });
  }, [selectedNode]);

  const createEmptyNode = useCallback(
    async (
      parentId: string,
      options?: {
        position?: NodePosition;
        layoutMode?: "auto" | "manual";
        revealParentId?: string;
      }
    ) => {
      if (!graph) {
        return;
      }

      setError(null);

      try {
        const response = await applyGraphMutation(
          {
            action: "create_node",
            parent_id: parentId,
            title: "",
            workstream: "General",
            smart: { ...EMPTY_SMART_FIELDS },
            status: "DRAFT",
            position: options?.position,
            layout_mode: options?.layoutMode,
          },
          {
            preferredStage: parentId === focusParent?.id ? undefined : workflowStage,
          }
        );

        const createdNodeId = findCreatedNodeId(graph, response.graph);
        if (!createdNodeId) {
          return;
        }

        if (parentId !== focusParent?.id || options?.revealParentId) {
          const nextFocusParentId = options?.revealParentId ?? parentId;
          const nextFocusParent = response.graph.nodes[nextFocusParentId];
          await updateFocus({
            path: graphPath,
            focus_parent_id: nextFocusParentId,
            active_layer: (nextFocusParent?.layer ?? 0) + 1,
          });
          await refreshGraph({ preferredSelectedNodeId: createdNodeId });
        } else {
          setSelectedNodeId(createdNodeId);
        }

        logJobEvent("Added an empty goal.");
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      }
    },
    [
      applyGraphMutation,
      focusParent?.id,
      graph,
      graphPath,
      refreshGraph,
      workflowStage,
    ]
  );

  const handleAddChildNode = useCallback(() => {
    if (!selectedNode) {
      return;
    }
    void createEmptyNode(selectedNode.id, { revealParentId: selectedNode.id });
  }, [createEmptyNode, selectedNode]);

  const handleAddSiblingNode = useCallback(() => {
    if (!selectedNode?.parent_id) {
      return;
    }
    void createEmptyNode(selectedNode.parent_id);
  }, [createEmptyNode, selectedNode]);

  const handleCreateNodeFromToolbar = useCallback(() => {
    if (!focusParent) {
      return;
    }
    void createEmptyNode(focusParent.id);
  }, [createEmptyNode, focusParent]);

  const handleCreateNodeAtPosition = useCallback(
    (position: NodePosition) => {
      if (!focusParent) {
        return;
      }
      void createEmptyNode(focusParent.id, {
        position,
        layoutMode: "manual",
      });
    },
    [createEmptyNode, focusParent]
  );

  const handleEditorSubmit = useCallback(
    async (payload: NodeEditorSubmitPayload) => {
      if (!graph) {
        return;
      }

      setEditorPending(true);
      setError(null);

      try {
        const editingNode = graph.nodes[payload.nodeId];
        if (!editingNode) {
          return;
        }

        if (payload.parentId !== (editingNode.parent_id ?? graph.root_id)) {
          await applyGraphMutation({
            action: "move_node",
            node_id: editingNode.id,
            parent_id: payload.parentId,
          });
        }

        await applyGraphMutation(
          {
            action: "update_node",
            node_id: editingNode.id,
            title: payload.title,
            workstream: payload.workstream,
            smart: payload.smart,
            status: editingNode.status === "DRAFT" ? "BASELINED" : editingNode.status,
          },
          {
            preferredSelectedNodeId: editingNode.id,
            preferredStage:
              editingNode.status === "PLANNED" ? "planning" : workflowStage,
          }
        );

        if (
          payload.parentId !== (editingNode.parent_id ?? graph.root_id) &&
          payload.parentId !== focusParent?.id
        ) {
          const nextParent = graph.nodes[payload.parentId];
          await updateFocus({
            path: graphPath,
            focus_parent_id: payload.parentId,
            active_layer: (nextParent?.layer ?? 0) + 1,
          });
          await refreshGraph({ preferredSelectedNodeId: editingNode.id });
        }

        logJobEvent(
          editingNode.status === "DRAFT"
            ? `Converted ${payload.title || "Untitled goal"} into a real goal.`
            : `Updated ${payload.title || "Untitled goal"}.`
        );

        setEditorMode(null);
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      } finally {
        setEditorPending(false);
      }
    },
    [
      applyGraphMutation,
      focusParent?.id,
      graph,
      graphPath,
      refreshGraph,
      workflowStage,
    ]
  );

  const handleDeleteGoals = useCallback(
    async (nodeIds: string[], options?: { closeEditor?: boolean; showPending?: boolean }) => {
      if (!graph) {
        return;
      }
      const uniqueNodeIds = Array.from(new Set(nodeIds)).filter((nodeId) => {
        const node = graph.nodes[nodeId];
        return node && node.id !== graph.root_id;
      });
      if (uniqueNodeIds.length === 0) {
        return;
      }
      if (options?.showPending) {
        setEditorPending(true);
      }
      setError(null);
      try {
        for (const nodeId of uniqueNodeIds) {
          const title = displayNodeTitle(graph.nodes[nodeId], "the goal");
          await applyGraphMutation({
            action: "delete_node",
            node_id: nodeId,
          });
          logJobEvent(`Deleted ${title}.`);
        }
        if (uniqueNodeIds.includes(selectedNodeId)) {
          setInspectorOpen(false);
        }
        if (options?.closeEditor) {
          setEditorMode(null);
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      } finally {
        if (options?.showPending) {
          setEditorPending(false);
        }
      }
    },
    [applyGraphMutation, graph, selectedNodeId]
  );

  const handleEditorDelete = useCallback(
    async (nodeId: string) => {
      await handleDeleteGoals([nodeId], { closeEditor: true, showPending: true });
    },
    [handleDeleteGoals]
  );

  const handlePersistNodePosition = useCallback(
    (nodeId: string, position: NodePosition) => {
      void applyGraphMutation({
        action: "set_position",
        node_id: nodeId,
        position,
        layout_mode: "manual",
      }).catch((err) => {
        setError(err instanceof Error ? err.message : String(err));
      });
    },
    [applyGraphMutation]
  );

  const handleAutoLayout = useCallback(async () => {
    if (!layerNodes.length) {
      canvasApi?.fitView();
      return;
    }
    try {
      for (const node of layerNodes) {
        if (node.ui.layout_mode === "manual") {
          await applyGraphMutation({
            action: "set_position",
            node_id: node.id,
            layout_mode: "auto",
          });
        }
      }
      canvasApi?.fitView();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, [applyGraphMutation, canvasApi, layerNodes]);

  const handleCreateConnection = useCallback(
    async (sourceId: string, targetId: string) => {
      if (!graph) {
        return;
      }
      const source = graph.nodes[sourceId];
      const target = graph.nodes[targetId];
      if (!source || !target) {
        return;
      }
      if (source.parent_id !== target.parent_id) {
        setError("Edges can only be assigned between sibling goals.");
        return;
      }
      try {
        await applyGraphMutation({
          action: "upsert_suggested_connection",
          source_id: sourceId,
          target_id: targetId,
        });
        logJobEvent(`Connected ${displayNodeTitle(source)} to ${displayNodeTitle(target)}.`);
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      }
    },
    [applyGraphMutation, graph]
  );

  const handleDeleteConnection = useCallback(
    async (sourceId: string, targetId: string) => {
      try {
        await applyGraphMutation({
          action: "delete_suggested_connection",
          source_id: sourceId,
          target_id: targetId,
        });
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      }
    },
    [applyGraphMutation]
  );

  const renderWelcome = () => (
    <div className="flex h-screen w-full items-center justify-center px-6">
      <div className="w-full max-w-2xl rounded-[28px] border border-border bg-card/90 px-8 py-12 text-center shadow-[0_36px_90px_rgba(0,0,0,0.42)]">
        <Badge
          variant="outline"
          className="mb-5 rounded-full border-white/10 bg-white/[0.03] px-3 py-1"
        >
          {graph ? "Replace goal" : "Canvas-first"}
        </Badge>
        <h1 className="text-4xl font-semibold tracking-[-0.04em] text-white">Start with a goal</h1>
        <div className="mt-3 text-sm text-white/48">
          The graph becomes the primary workspace as soon as the goal is created.
        </div>
        <div className="mt-8 flex flex-col gap-3 sm:flex-row">
          <Input
            value={newGoalTitle}
            onChange={(event) => setNewGoalTitle(event.target.value)}
            placeholder="Enter goal"
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                event.preventDefault();
                void handleCreateGraph();
              }
            }}
          />
          <Button
            onClick={() => void handleCreateGraph()}
            disabled={creatingGraph || !newGoalTitle.trim()}
          >
            {creatingGraph ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <ArrowRight className="h-4 w-4" />
            )}
          </Button>
        </div>
      </div>
    </div>
  );

  const renderComposerShell = (content: ReactNode) => (
    <div className="rounded-[24px] border border-white/8 bg-black/24 px-3 py-2.5 backdrop-blur-sm">
      {content}
    </div>
  );

  const renderStatusCard = (
    eyebrow: string,
    title: string,
    description?: string,
    options?: { loading?: boolean }
  ) => (
    <div className="rounded-[18px] border border-white/8 bg-white/[0.035] px-4 py-3">
      <div className="flex items-start gap-3">
        {options?.loading ? (
          <Loader2 className="mt-0.5 h-4 w-4 animate-spin text-primary" />
        ) : null}
        <div className="min-w-0">
          <div className="text-[10px] uppercase tracking-[0.16em] text-white/38">{eyebrow}</div>
          <div className="mt-1.5 text-[14px] leading-5 text-white">{title}</div>
          {description ? (
            <div className="mt-1 text-[12px] leading-5 text-white/48">{description}</div>
          ) : null}
        </div>
      </div>
    </div>
  );

  const statusCard =
    visibleStageId === "clarify" && currentDraftingQuestion
      ? renderStatusCard(
          `${currentDraftingQuestion.category} · ${draftingQuestionIndex + 1}/${draftingQuestions.length}`,
          currentDraftingQuestion.question
        )
      : visibleStageId === "build"
        ? renderStatusCard(
            "Build",
            activeOperationLabel ?? "Building graph",
            undefined,
            { loading: true }
          )
        : null;

  const renderComposer = () => {
    if (visibleStageId === "define") {
      return renderComposerShell(
        <div className="flex items-center justify-between gap-3">
          <div>
            <div className="text-sm text-white/60">Decompose this goal into first-layer goals.</div>
          </div>
          <Button size="sm" onClick={() => void handleBuildLayer()} disabled={activeJobId !== null}>
            {activeJobId ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Sparkles className="h-4 w-4" />
            )}
            Decompose goal
          </Button>
        </div>
      );
    }

    if (visibleStageId === "clarify") {
      if (currentDraftingQuestion) {
        return renderComposerShell(
          <div className="flex items-end gap-2">
            <Textarea
              ref={composerTextareaRef}
              rows={1}
              className="max-h-[160px] min-h-0 resize-none border-0 bg-transparent px-0 py-1 text-[14px] leading-6 text-white placeholder:text-white/28 focus-visible:ring-0"
              value={chatInput}
              onChange={(event) => setChatInput(event.target.value)}
              onInput={() => syncComposerHeight()}
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey) {
                  event.preventDefault();
                  handleSubmitDraftingAnswer();
                }
              }}
            />
            <Button
              size="icon"
              className="h-9 w-9 rounded-full"
              onClick={handleSubmitDraftingAnswer}
              disabled={activeJobId !== null || !chatInput.trim()}
            >
              <ArrowRight className="h-4 w-4" />
            </Button>
          </div>
        );
      }

      if (draftingQuestionsPending) {
        return renderComposerShell(
          <div className="flex items-center gap-3 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin text-primary" />
            Preparing prompts
          </div>
        );
      }

      if (draftingQuestionsError) {
        return renderComposerShell(
          <div className="flex items-center justify-between gap-3">
            <div className="min-w-0 text-sm text-white/50">Prompt prep failed.</div>
            <Button
              size="sm"
              variant="outline"
              onClick={() => {
                setDraftingParentId(null);
                setDraftingQuestionsError(null);
              }}
            >
              Retry
            </Button>
          </div>
        );
      }

      return renderComposerShell(
        <div className="flex items-center justify-between gap-3">
          <div>
            <div className="text-sm text-white/60">Clarification complete.</div>
          </div>
          <Button
            size="sm"
            onClick={() => void handleBuildLayer()}
            disabled={activeJobId !== null || !allDraftingQuestionsAnswered}
          >
            {activeJobId ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Sparkles className="h-4 w-4" />
            )}
            Build graph
          </Button>
        </div>
      );
    }

    if (visibleStageId === "build") {
      return renderComposerShell(
        <div className="flex items-center gap-3 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin text-primary" />
          {activeOperationLabel ?? "Building graph"}
        </div>
      );
    }

    return renderComposerShell(
      <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
        <div className="text-sm text-white/50">
          {selectedNode
            ? `Selected ${selectedNode.title.trim() || "Untitled goal"}.`
            : "Select a goal."}
        </div>
        <Button
          size="sm"
          onClick={() => {
            if (!selectedNode) {
              return;
            }
            if (selectedNode.status === "BASELINED") {
              void handleGeneratePlan();
              return;
            }
            openEditorForSelection();
          }}
          disabled={!selectedNode || activeJobId !== null}
        >
          {selectedNode?.status === "BASELINED" ? "Generate plan" : "Open editor"}
        </Button>
      </div>
    );
  };

  if (loading) {
    return (
      <div className="flex h-screen items-center justify-center gap-3 text-sm text-muted-foreground">
        <Loader2 className="h-5 w-5 animate-spin" />
        Loading AIMIGO...
      </div>
    );
  }

  if (showWelcome) {
    return (
      <div className="app-shell overflow-hidden bg-background">
        {renderWelcome()}
      </div>
    );
  }

  return (
    <div className="app-shell flex h-screen w-full flex-col overflow-hidden">
      <header className="border-b border-white/6 px-4 py-4 lg:px-5">
        <div className="flex items-center justify-between gap-4">
          <div className="min-w-0">
            <nav
              aria-label="Goal path"
              className="flex min-w-0 flex-wrap items-center gap-2 text-[11px] uppercase tracking-[0.13em] text-white/34"
            >
              <span className="font-medium text-white/62">AIMIGO</span>
              {breadcrumbNodes.map((node) => (
                <span key={node.id} className="flex min-w-0 items-center gap-2">
                  <span className="text-white/20">/</span>
                  <span className="max-w-[18rem] truncate text-white/58">
                    {displayNodeTitle(node, "Untitled goal")}
                  </span>
                </span>
              ))}
            </nav>
            <div className="mt-2 flex min-w-0 flex-wrap items-center gap-2">
              <div className="min-w-0 truncate text-[18px] font-medium tracking-[-0.02em] text-white">
                {displayNodeTitle(focusParent, "Goal")}
              </div>
              <div className="flex shrink-0 flex-wrap items-center gap-1.5">
                <Button size="sm" variant="outline" onClick={() => void handleBackLayer()} disabled={!focusParent?.parent_id}>
                  <ArrowLeft className="h-4 w-4" />
                  Back
                </Button>
                <Button
                  size="sm"
                  draggable={Boolean(focusParent)}
                  onDragStart={(event) => {
                    event.dataTransfer.setData(GRAPH_TOOLBAR_DRAG_TYPE, "node");
                    event.dataTransfer.effectAllowed = "copy";
                  }}
                  onClick={handleCreateNodeFromToolbar}
                  disabled={!focusParent}
                >
                  <Plus className="h-4 w-4" />
                  New goal
                </Button>
                <Button size="sm" variant="outline" onClick={() => void handleAutoLayout()}>
                  <LayoutGrid className="h-4 w-4" />
                  Auto layout
                </Button>
                <Button size="sm" variant="outline" onClick={() => canvasApi?.fitView()}>
                  <Maximize2 className="h-4 w-4" />
                  Fit
                </Button>
              </div>
            </div>
          </div>

          <div className="flex min-w-0 items-center gap-2">
            {activeVisibleStage ? (
              <div className="hidden max-w-[360px] rounded-[18px] border border-white/8 bg-white/[0.035] px-3 py-2 text-right md:block">
                <div className="text-[10px] uppercase tracking-[0.16em] text-white/34">
                  {activeVisibleStage.title}
                </div>
                <div className="mt-1 truncate text-[12px] text-white/54">
                  {activeVisibleStage.description}
                </div>
              </div>
            ) : null}
            <Button variant="ghost" size="sm" onClick={handleReplaceGoal}>
              Replace
            </Button>
          </div>
        </div>
      </header>

      <div className="flex min-h-0 flex-1 overflow-hidden">
        <main className="flex min-h-0 flex-1 flex-col overflow-hidden px-4 py-4 lg:px-5 lg:py-5">
          <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-hidden">
            <section className="graph-stage panel-border relative flex min-h-[340px] flex-1 flex-col overflow-hidden rounded-[26px] border border-white/6 p-3 lg:min-h-0">
              <div className="min-h-0 flex-1 rounded-[22px] border border-white/6 bg-black/12 p-2">
                <GoalGraph
                  focusParent={focusParent}
                  layerNodes={layerNodes}
                  nodeProgress={nodeProgress}
                  selectedNodeId={selectedNodeId}
                  suggestedConnections={graph?.suggested_connections ?? []}
                  busyNodeId={busyNodeId}
                  isDraftingLayer={workflowStage === "building" && !hasLayerChildren}
                  dragType={GRAPH_TOOLBAR_DRAG_TYPE}
                  onSelectNode={(nodeId) => {
                    setSelectedNodeId(nodeId);
                    setWorkflowStage(graph?.nodes[nodeId]?.status === "PLANNED" ? "planning" : "selecting");
                  }}
                  onInspectNode={(nodeId) => {
                    setSelectedNodeId(nodeId);
                    setWorkflowStage(graph?.nodes[nodeId]?.status === "PLANNED" ? "planning" : "selecting");
                    setInspectorOpen(true);
                  }}
                  onCreateNodeAtPosition={handleCreateNodeAtPosition}
                  onPersistNodePosition={handlePersistNodePosition}
                  onCreateConnection={handleCreateConnection}
                  onDeleteConnection={handleDeleteConnection}
                  onDeleteNodes={(nodeIds) => {
                    void handleDeleteGoals(nodeIds);
                  }}
                  onAgentAssist={handleAgentAssist}
                  onToggleTask={(nodeId, taskIndex, completed) => {
                    void handleToggleTask(nodeId, taskIndex, completed);
                  }}
                  onRegisterCanvasApi={setCanvasApi}
                />
              </div>
            </section>

            <div className="min-h-0">
              <StageChatPanel
                stages={visibleStages}
                activeStageId={visibleStageId}
                statusCard={statusCard}
                composer={renderComposer()}
              />
            </div>
          </div>
        </main>
      </div>

      <Sheet open={inspectorOpen} onOpenChange={setInspectorOpen}>
        <SheetContent
          side="right"
          className="w-full border-white/8 bg-[rgba(9,9,12,0.98)] p-0 sm:max-w-md lg:max-w-[380px]"
        >
          <NodeDetailSidebar
            graph={graph}
            selectedNode={selectedNode}
            selectedProgress={selectedProgress}
            focusParent={focusParent}
            onOpenEditor={openEditorForSelection}
            onCreateChild={handleAddChildNode}
            onCreateSibling={handleAddSiblingNode}
            onGeneratePlan={() => void handleGeneratePlan()}
            onGoDeeper={() => void handleGoDeeper()}
            onFocusSelectedNode={() => void handleFocusSelectedNode(selectedNode?.id ?? "")}
          />
        </SheetContent>
      </Sheet>

      <NodeEditorDialog
        open={editorMode !== null}
        graph={graph}
        mode={editorMode}
        pending={editorPending}
        onOpenChange={(open) => {
          if (!open) {
            setEditorMode(null);
          }
        }}
        onSubmit={handleEditorSubmit}
        onDelete={handleEditorDelete}
      />
    </div>
  );
}
