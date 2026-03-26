"use client";

import ELK from "elkjs/lib/elk.bundled.js";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import ReactFlow, {
  Background,
  Controls,
  Node as FlowNode,
  NodeMouseHandler,
} from "reactflow";
import "reactflow/dist/style.css";
import {
  AlertTriangle,
  ArrowRight,
  Layers,
  Loader2,
  Minus,
  Plus,
  RefreshCw,
  Send,
  SquareCheckBig,
  Trash2,
} from "lucide-react";

import { ConsolePanel } from "@/components/app/console-panel";
import {
  LayerGraphNode,
  type LayerGraphNodeData,
} from "@/components/app/layer-graph-node";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import {
  fetchBaselineQuestions,
  fetchGraph,
  fetchSession,
  fetchStatus,
  getJob,
  initGraph,
  postJob,
  saveSession,
  streamJobEvents,
  updateFocus,
} from "@/lib/api";
import {
  BaselineQuestion,
  ChatMessage,
  GraphResponse,
  Node,
  NodeProgress,
  Task,
} from "@/lib/types";

const DEFAULT_GRAPH_PATH = "out/graph.json";
const DEFAULT_SESSION_ID = "local-session";
const NODE_WIDTH = 260;
const NODE_HEIGHT = 128;

const elk = new ELK();
const nodeTypes = { layerNode: LayerGraphNode };

type BaselineAnswerMap = Record<string, string>;

interface TreeItem {
  node: Node;
  depth: number;
}

interface PlanDraft {
  tasks: Task[];
}

function nowIso() {
  return new Date().toISOString();
}

function cloneTasks(tasks: Task[]): Task[] {
  return tasks.map((task) => ({
    ...task,
    depends_on: [...task.depends_on],
  }));
}

function newTask(): Task {
  return {
    title: "",
    description: "",
    success_criteria: "",
    depends_on: [],
    estimate_hours: null,
    relative_timing: "TBD",
    due: "TBD",
    completed: false,
  };
}

function checkGlyph(state: NodeProgress["check_state"]) {
  if (state === "checked") {
    return "[x]";
  }
  if (state === "partial") {
    return "[~]";
  }
  return "[ ]";
}

function statusTone(status: Node["status"]) {
  if (status === "PLANNED") {
    return "default" as const;
  }
  if (status === "BASELINED") {
    return "secondary" as const;
  }
  return "outline" as const;
}

function fallbackFlowNodes(
  layerNodes: Node[],
  progressMap: Record<string, NodeProgress>
): FlowNode<LayerGraphNodeData>[] {
  return layerNodes.map((node, index) => {
    const progress = progressMap[node.id];
    const subtitle = progress
      ? `${progress.completed_tasks}/${progress.total_tasks} tasks`
      : "No tasks";
    return {
      id: node.id,
      type: "layerNode",
      draggable: false,
      position: {
        x: (index % 3) * (NODE_WIDTH + 48),
        y: Math.floor(index / 3) * (NODE_HEIGHT + 44),
      },
      data: {
        title: node.title,
        subtitle,
        status: node.status,
      },
    };
  });
}

async function elkFlowNodes(
  layerNodes: Node[],
  progressMap: Record<string, NodeProgress>
): Promise<FlowNode<LayerGraphNodeData>[]> {
  const fallback = fallbackFlowNodes(layerNodes, progressMap);
  if (fallback.length === 0) {
    return fallback;
  }

  const graphForLayout = {
    id: "layer-children",
    layoutOptions: {
      "elk.algorithm": "layered",
      "elk.direction": "RIGHT",
      "elk.spacing.nodeNode": "48",
      "elk.layered.spacing.nodeNodeBetweenLayers": "88",
      "elk.padding": "[top=32,left=24,bottom=32,right=24]",
    },
    children: layerNodes.map((node) => ({
      id: node.id,
      width: NODE_WIDTH,
      height: NODE_HEIGHT,
    })),
    // Synthetic chain edges only for layout direction. They are not rendered in React Flow.
    edges: layerNodes.slice(1).map((node, index) => ({
      id: `layout-${layerNodes[index].id}-${node.id}`,
      sources: [layerNodes[index].id],
      targets: [node.id],
    })),
  };

  const laidOut = (await elk.layout(graphForLayout as never)) as {
    children?: Array<{ id?: string; x?: number; y?: number }>;
  };
  const positions = new Map<string, { x: number; y: number }>();
  for (const child of laidOut.children ?? []) {
    if (!child.id) {
      continue;
    }
    positions.set(child.id, {
      x: child.x ?? 0,
      y: child.y ?? 0,
    });
  }

  return layerNodes.map((node, index) => {
    const progress = progressMap[node.id];
    const subtitle = progress
      ? `${progress.completed_tasks}/${progress.total_tasks} tasks`
      : "No tasks";
    return {
      id: node.id,
      type: "layerNode",
      draggable: false,
      position: positions.get(node.id) ?? fallback[index].position,
      data: {
        title: node.title,
        subtitle,
        status: node.status,
      },
    };
  });
}

export default function HomePage() {
  const [graphPath] = useState(DEFAULT_GRAPH_PATH);
  const [sessionId] = useState(DEFAULT_SESSION_ID);
  const [graphData, setGraphData] = useState<GraphResponse | null>(null);
  const [selectedNodeId, setSelectedNodeId] = useState<string>("root");
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([]);
  const [chatInput, setChatInput] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [activeJobId, setActiveJobId] = useState<string | null>(null);
  const [mobileTab, setMobileTab] = useState("graph");
  const [detailSheetOpen, setDetailSheetOpen] = useState(false);
  const [isDesktopViewport, setIsDesktopViewport] = useState(true);
  const [newGoalTitle, setNewGoalTitle] = useState("");
  const [creatingGraph, setCreatingGraph] = useState(false);

  const [nodeTitle, setNodeTitle] = useState("");
  const [smartSpecific, setSmartSpecific] = useState("");
  const [smartMeasurable, setSmartMeasurable] = useState("");
  const [smartAchievable, setSmartAchievable] = useState("");
  const [smartRelevant, setSmartRelevant] = useState("");
  const [smartTimeBound, setSmartTimeBound] = useState("");
  const [planDraft, setPlanDraft] = useState<PlanDraft>({ tasks: [] });
  const [baselineQuestions, setBaselineQuestions] = useState<BaselineQuestion[]>([]);
  const [baselineAnswers, setBaselineAnswers] = useState<BaselineAnswerMap>({});
  const [flowNodes, setFlowNodes] = useState<FlowNode<LayerGraphNodeData>[]>([]);

  const lastKnownUpdatedAtRef = useRef<string>("");
  const lastLocalMutationAtRef = useRef<number>(0);
  const isEditingRef = useRef(false);
  const elkFailureNotifiedRef = useRef(false);

  const graph = graphData?.graph ?? null;
  const nodeProgress = useMemo(() => graphData?.node_progress ?? {}, [graphData]);
  const selectedNode = graph ? graph.nodes[selectedNodeId] ?? null : null;

  const appendMessage = useCallback((role: ChatMessage["role"], content: string) => {
    setChatMessages((previous) => [...previous, { role, content, created_at: nowIso() }]);
  }, []);

  useEffect(() => {
    const mediaQuery = window.matchMedia("(min-width: 1024px)");
    const applyViewport = () => setIsDesktopViewport(mediaQuery.matches);
    applyViewport();
    mediaQuery.addEventListener("change", applyViewport);
    return () => mediaQuery.removeEventListener("change", applyViewport);
  }, []);

  const refreshGraph = useCallback(
    async (options?: { externalChange?: boolean }) => {
      const payload = await fetchGraph(graphPath);
      setGraphData(payload);
      lastKnownUpdatedAtRef.current = payload.graph.updated_at;

      setSelectedNodeId((current) => {
        if (payload.graph.nodes[current]) {
          return current;
        }
        return payload.graph.root_id;
      });

      if (options?.externalChange) {
        appendMessage("system", "Graph changed externally. Refreshed latest state.");
      }
    },
    [appendMessage, graphPath]
  );

  const handleCreateGraph = useCallback(async () => {
    const goal = newGoalTitle.trim();
    if (!goal) {
      setError("Goal title is required.");
      return;
    }
    setCreatingGraph(true);
    setError(null);
    try {
      const payload = await initGraph(graphPath, goal);
      setGraphData(payload);
      setSelectedNodeId(payload.graph.root_id);
      lastKnownUpdatedAtRef.current = payload.graph.updated_at;
      appendMessage("system", `Created graph for goal: ${goal}`);
      setNewGoalTitle("");
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      if (message.includes("already exists")) {
        await refreshGraph();
        appendMessage("system", "Graph already existed. Loaded current graph.");
        setNewGoalTitle("");
        return;
      }
      setError(message);
    } finally {
      setCreatingGraph(false);
    }
  }, [appendMessage, graphPath, newGoalTitle, refreshGraph]);

  const runJob = useCallback(
    async (endpoint: string, body: Record<string, unknown>, label: string) => {
      setError(null);
      const accepted = await postJob(endpoint, { ...body, path: graphPath });
      setActiveJobId(accepted.job_id);
      appendMessage("system", `${label}: queued (${accepted.job_id.slice(0, 8)})`);

      await new Promise<void>((resolve, reject) => {
        const stream = streamJobEvents(accepted.job_id, (event) => {
          appendMessage("system", `[${event.type}] ${event.message}`);
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
      setActiveJobId(null);
      if (record.status !== "succeeded") {
        throw new Error(record.error ?? `${label} failed`);
      }

      lastLocalMutationAtRef.current = Date.now();
      await refreshGraph();
    },
    [appendMessage, graphPath, refreshGraph]
  );

  useEffect(() => {
    let cancelled = false;

    async function init() {
      setLoading(true);
      try {
        await refreshGraph();
        const session = await fetchSession(sessionId);
        if (!cancelled && session.messages.length > 0) {
          setChatMessages(
            session.messages
              .filter((item): item is ChatMessage => typeof item.content === "string")
              .map((item) => ({
                role: item.role ?? "system",
                content: item.content,
                created_at: item.created_at ?? nowIso(),
              }))
          );
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : String(err));
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
  }, [refreshGraph, sessionId]);

  useEffect(() => {
    if (!selectedNode) {
      setDetailSheetOpen(false);
      return;
    }

    setNodeTitle(selectedNode.title);
    setSmartSpecific(selectedNode.smart.specific);
    setSmartMeasurable(selectedNode.smart.measurable);
    setSmartAchievable(selectedNode.smart.achievable);
    setSmartRelevant(selectedNode.smart.relevant);
    setSmartTimeBound(selectedNode.smart.time_bound);
    setPlanDraft({ tasks: cloneTasks(selectedNode.plan?.tasks ?? []) });

    const questionAnswers: BaselineAnswerMap = {};
    for (const qa of selectedNode.baseline?.qa ?? []) {
      questionAnswers[qa.id] = qa.answer;
    }
    setBaselineAnswers(questionAnswers);
    setBaselineQuestions([]);
  }, [selectedNode]);

  useEffect(() => {
    const interval = window.setInterval(() => {
      void (async () => {
        if (!graph || isEditingRef.current) {
          return;
        }
        try {
          const status = await fetchStatus(graphPath);
          if (status.updated_at !== lastKnownUpdatedAtRef.current) {
            const externallyUpdated = Date.now() - lastLocalMutationAtRef.current > 2500;
            await refreshGraph({ externalChange: externallyUpdated });
          }
        } catch {
          // Keep polling; surface errors only on explicit actions.
        }
      })();
    }, 4000);

    return () => window.clearInterval(interval);
  }, [graph, graphPath, refreshGraph]);

  useEffect(() => {
    const timeout = window.setTimeout(() => {
      if (chatMessages.length === 0) {
        return;
      }
      void saveSession(sessionId, chatMessages, {
        selectedNodeId,
        graphPath,
      });
    }, 500);

    return () => window.clearTimeout(timeout);
  }, [chatMessages, graphPath, selectedNodeId, sessionId]);

  const treeItems = useMemo<TreeItem[]>(() => {
    if (!graph) {
      return [];
    }

    const result: TreeItem[] = [];
    const walk = (nodeId: string, depth: number) => {
      const node = graph.nodes[nodeId];
      if (!node) {
        return;
      }
      result.push({ node, depth });
      for (const childId of node.children_ids) {
        walk(childId, depth + 1);
      }
    };

    walk(graph.root_id, 0);
    return result;
  }, [graph]);

  const focusParent = graph ? graph.nodes[graph.focus_parent_id] ?? null : null;
  const layerNodes = useMemo(() => {
    if (!graph || !focusParent) {
      return [] as Node[];
    }
    return focusParent.children_ids
      .map((id) => graph.nodes[id])
      .filter((node): node is Node => Boolean(node));
  }, [focusParent, graph]);

  useEffect(() => {
    let cancelled = false;

    async function runLayout() {
      if (!layerNodes.length) {
        setFlowNodes([]);
        return;
      }

      try {
        const nodes = await elkFlowNodes(layerNodes, nodeProgress);
        if (!cancelled) {
          setFlowNodes(nodes);
        }
        elkFailureNotifiedRef.current = false;
      } catch {
        if (cancelled) {
          return;
        }
        setFlowNodes(fallbackFlowNodes(layerNodes, nodeProgress));
        if (!elkFailureNotifiedRef.current) {
          elkFailureNotifiedRef.current = true;
          const message = "ELK layout failed. Using fallback grid placement.";
          setError(message);
          appendMessage("system", message);
        }
      }
    }

    void runLayout();

    return () => {
      cancelled = true;
    };
  }, [appendMessage, layerNodes, nodeProgress]);

  const onFlowNodeClick = useCallback<NodeMouseHandler>(
    (_event, node) => {
      if (!graph || !graph.nodes[node.id]) {
        const message = `Node data missing for '${node.id}'.`;
        setError(message);
        appendMessage("system", message);
        setDetailSheetOpen(false);
        return;
      }
      setSelectedNodeId(node.id);
      setDetailSheetOpen(true);
    },
    [appendMessage, graph]
  );

  const jumpToNodeLayer = useCallback(
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
      await refreshGraph();
      setSelectedNodeId(nodeId);
      setDetailSheetOpen(false);
    },
    [graph, graphPath, refreshGraph]
  );

  const handlePrevLayer = useCallback(async () => {
    if (!graph || !focusParent?.parent_id) {
      return;
    }
    await updateFocus({
      path: graphPath,
      focus_parent_id: focusParent.parent_id,
      active_layer: (graph.nodes[focusParent.parent_id]?.layer ?? 0) + 1,
    });
    await refreshGraph();
    setDetailSheetOpen(false);
  }, [focusParent, graph, graphPath, refreshGraph]);

  const handleNextLayer = useCallback(async () => {
    if (!graph) {
      return;
    }
    const nextFocus = layerNodes.find((node) => node.id === selectedNodeId) ?? layerNodes[0];
    if (!nextFocus) {
      return;
    }
    await updateFocus({
      path: graphPath,
      focus_parent_id: nextFocus.id,
      active_layer: nextFocus.layer + 1,
    });
    await refreshGraph();
    setSelectedNodeId(nextFocus.id);
    setDetailSheetOpen(false);
  }, [graph, graphPath, layerNodes, refreshGraph, selectedNodeId]);

  const handleGenerateBaselineQuestions = useCallback(async () => {
    if (!selectedNode) {
      return;
    }
    try {
      const payload = await fetchBaselineQuestions(selectedNode.id, graphPath);
      const questions = payload.questions;
      setBaselineQuestions(questions);
      setBaselineAnswers((previous) => {
        const next = { ...previous };
        for (const item of questions) {
          if (next[item.id] === undefined) {
            next[item.id] = "";
          }
        }
        return next;
      });
      appendMessage("assistant", `Loaded ${questions.length} baseline questions.`);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, [appendMessage, graphPath, selectedNode]);

  const handleApplyBaseline = useCallback(async () => {
    if (!selectedNode) {
      return;
    }
    try {
      const qaPairs = baselineQuestions.map((question) => ({
        id: question.id,
        question: question.question,
        category: question.category,
        answer: baselineAnswers[question.id] ?? "",
      }));

      await runJob(
        "baseline-apply",
        {
          node_id: selectedNode.id,
          qa_pairs: qaPairs,
        },
        "Baseline apply"
      );
      appendMessage("assistant", "Baseline applied successfully.");
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      setError(message);
      appendMessage("assistant", `Baseline apply failed: ${message}`);
    }
  }, [appendMessage, baselineAnswers, baselineQuestions, runJob, selectedNode]);

  const handleSaveNode = useCallback(async () => {
    if (!selectedNode) {
      return;
    }
    isEditingRef.current = false;
    try {
      await runJob(
        "node-update",
        {
          node_id: selectedNode.id,
          title: nodeTitle,
          smart_patch: {
            specific: smartSpecific,
            measurable: smartMeasurable,
            achievable: smartAchievable,
            relevant: smartRelevant,
            time_bound: smartTimeBound,
          },
        },
        "Node update"
      );
      appendMessage("assistant", "Node edits saved.");
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      setError(message);
      appendMessage("assistant", `Node save failed: ${message}`);
    }
  }, [
    appendMessage,
    nodeTitle,
    runJob,
    selectedNode,
    smartAchievable,
    smartMeasurable,
    smartRelevant,
    smartSpecific,
    smartTimeBound,
  ]);

  const handleSavePlan = useCallback(async () => {
    if (!selectedNode) {
      return;
    }
    isEditingRef.current = false;
    try {
      await runJob(
        "plan-replace",
        {
          node_id: selectedNode.id,
          tasks: planDraft.tasks,
        },
        "Plan replace"
      );
      appendMessage("assistant", "Plan edits saved.");
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      setError(message);
      appendMessage("assistant", `Plan save failed: ${message}`);
    }
  }, [appendMessage, planDraft.tasks, runJob, selectedNode]);

  const handleDecompose = useCallback(async () => {
    if (!selectedNode) {
      return;
    }
    try {
      await runJob("decompose", { node_id: selectedNode.id }, "Decompose");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, [runJob, selectedNode]);

  const handleGeneratePlan = useCallback(async () => {
    if (!selectedNode) {
      return;
    }
    try {
      await runJob("plan-generate", { node_id: selectedNode.id }, "Plan generation");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, [runJob, selectedNode]);

  const handleAddNode = useCallback(async () => {
    if (!selectedNode) {
      return;
    }
    try {
      await runJob(
        "node-add",
        {
          parent_id: selectedNode.id,
          title: `New node under ${selectedNode.title}`,
          workstream: "General",
          smart: {
            specific: `Define scope for ${selectedNode.title}`,
            measurable: "Define measurable output",
            achievable: "",
            relevant: `Supports ${selectedNode.title}`,
            time_bound: "",
          },
        },
        "Node add"
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, [runJob, selectedNode]);

  const handleDeleteNode = useCallback(async () => {
    if (!selectedNode) {
      return;
    }
    try {
      await runJob("node-delete", { node_id: selectedNode.id }, "Node delete");
      setDetailSheetOpen(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, [runJob, selectedNode]);

  const handleBulkToggle = useCallback(
    async (nodeId: string, progress: NodeProgress) => {
      const completed = progress.check_state !== "checked";
      try {
        await runJob(
          "subgoal-toggle",
          {
            node_id: nodeId,
            completed,
          },
          "Subgoal toggle"
        );
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      }
    },
    [runJob]
  );

  const toggleTaskAtIndex = useCallback(
    async (taskIndex: number, completed: boolean) => {
      if (!selectedNode) {
        return;
      }
      try {
        await runJob(
          "task-toggle",
          {
            node_id: selectedNode.id,
            task_index: taskIndex,
            completed,
          },
          "Task toggle"
        );
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      }
    },
    [runJob, selectedNode]
  );

  const handleChatSend = useCallback(async () => {
    const text = chatInput.trim();
    if (!text) {
      return;
    }
    appendMessage("user", text);
    setChatInput("");

    const normalized = text.toLowerCase();
    if (normalized.includes("decompose")) {
      await handleDecompose();
      return;
    }
    if (normalized.includes("baseline") && normalized.includes("question")) {
      await handleGenerateBaselineQuestions();
      return;
    }
    if (normalized.includes("apply") && normalized.includes("baseline")) {
      await handleApplyBaseline();
      return;
    }
    if (normalized.includes("generate") && normalized.includes("plan")) {
      await handleGeneratePlan();
      return;
    }
    if (normalized.includes("save") && normalized.includes("plan")) {
      await handleSavePlan();
      return;
    }
    if (normalized.includes("save") && normalized.includes("node")) {
      await handleSaveNode();
      return;
    }
    if (normalized.includes("add node") || normalized.includes("create node")) {
      await handleAddNode();
      return;
    }
    if (normalized.includes("delete") && normalized.includes("node")) {
      await handleDeleteNode();
      return;
    }

    appendMessage(
      "assistant",
      "I can run workflow actions: decompose, baseline questions/apply, generate plan, add/delete node, save node, and save plan."
    );
  }, [
    appendMessage,
    chatInput,
    handleAddNode,
    handleApplyBaseline,
    handleDecompose,
    handleDeleteNode,
    handleGenerateBaselineQuestions,
    handleGeneratePlan,
    handleSaveNode,
    handleSavePlan,
  ]);

  if (loading) {
    return (
      <div className="flex h-screen items-center justify-center gap-3 text-sm text-muted-foreground">
        <Loader2 className="h-5 w-5 animate-spin" />
        Loading SMART-GoT console...
      </div>
    );
  }

  if (!graph || !selectedNode) {
    const graphMissing = (error ?? "").includes("Graph file not found");
    return (
      <div className="flex h-screen flex-col items-center justify-center gap-3 p-6 text-sm">
        <AlertTriangle className="h-5 w-5 text-destructive" />
        <div>{error ?? "Graph unavailable."}</div>
        {graphMissing ? (
          <div className="w-full max-w-md space-y-2 rounded-md border border-border bg-card/50 p-4">
            <div className="text-xs font-semibold uppercase tracking-[0.14em] text-muted-foreground">
              Create Goal
            </div>
            <Input
              value={newGoalTitle}
              onChange={(event) => setNewGoalTitle(event.target.value)}
              placeholder="Enter your SMART goal title"
              onKeyDown={(event) => {
                if (event.key === "Enter") {
                  event.preventDefault();
                  void handleCreateGraph();
                }
              }}
            />
            <Button onClick={() => void handleCreateGraph()} disabled={creatingGraph || !newGoalTitle.trim()}>
              {creatingGraph ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  Creating...
                </>
              ) : (
                "Create Graph"
              )}
            </Button>
          </div>
        ) : null}
        <Button variant="outline" onClick={() => void refreshGraph()}>
          Retry
        </Button>
      </div>
    );
  }

  const graphActionButtons = (
    <>
      <Button variant="outline" size="sm" onClick={() => void handlePrevLayer()}>
        Prev Layer
      </Button>
      <Button variant="outline" size="sm" onClick={() => void handleNextLayer()}>
        Next Layer
      </Button>
    </>
  );

  return (
    <div className="flex h-screen w-full flex-col lg:flex-row">
      <aside className="h-[34vh] border-b border-border bg-card/60 p-3 lg:h-full lg:w-[320px] lg:border-b-0 lg:border-r">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-xs font-semibold uppercase tracking-[0.14em] text-muted-foreground">
            Goal Tree
          </h2>
          <Badge variant="outline">{Object.keys(graph.nodes).length} nodes</Badge>
        </div>
        <ScrollArea className="h-[calc(34vh-42px)] lg:h-[calc(100%-42px)]">
          <div className="space-y-1 pr-2">
            {treeItems.map(({ node, depth }) => {
              const progress = nodeProgress[node.id];
              const hasTaskCheckbox = Boolean(progress && progress.total_tasks > 0);
              const isSelected = selectedNodeId === node.id;
              return (
                <button
                  key={node.id}
                  className={`w-full rounded-md border px-2 py-1.5 text-left transition ${
                    isSelected
                      ? "border-primary bg-primary/10"
                      : "border-transparent hover:border-border hover:bg-accent/30"
                  }`}
                  style={{ paddingLeft: `${depth * 14 + 8}px` }}
                  onClick={() => {
                    void jumpToNodeLayer(node.id);
                  }}
                >
                  <div className="flex items-center justify-between gap-2">
                    <div className="min-w-0">
                      <div className="truncate text-sm font-medium">{node.title}</div>
                    </div>
                    <div className="flex items-center gap-2">
                      {hasTaskCheckbox ? (
                        <span
                          role="button"
                          tabIndex={0}
                          onClick={(event) => {
                            event.stopPropagation();
                            void handleBulkToggle(node.id, progress);
                          }}
                          className="rounded px-1 text-sm hover:bg-muted"
                        >
                          {checkGlyph(progress.check_state)}
                        </span>
                      ) : null}
                      <Badge variant={statusTone(node.status)}>{node.status}</Badge>
                    </div>
                  </div>
                </button>
              );
            })}
          </div>
        </ScrollArea>
      </aside>

      <main className="flex min-h-0 flex-1 flex-col gap-3 p-3 lg:p-4">
        <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
          <Layers className="h-4 w-4" />
          Parent:
          <span className="font-semibold text-foreground">{focusParent?.title}</span>
          <span className="font-mono text-[11px]">({focusParent?.id})</span>
          <span className="mx-1">|</span>
          Graph path:
          <span className="font-mono text-[11px] text-foreground">{graphPath}</span>
          {activeJobId ? (
            <span className="inline-flex items-center gap-1 text-primary">
              <Loader2 className="h-3 w-3 animate-spin" /> job {activeJobId.slice(0, 8)}
            </span>
          ) : null}
          <Button
            variant="outline"
            size="sm"
            className="ml-auto h-7"
            onClick={() => void refreshGraph()}
          >
            <RefreshCw className="mr-1 h-3.5 w-3.5" /> Refresh
          </Button>
        </div>

        {error ? (
          <div className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive-foreground">
            {error}
          </div>
        ) : null}

        <div className="hidden min-h-0 flex-1 gap-3 lg:grid lg:grid-rows-[1.2fr_0.8fr]">
          <ConsolePanel
            title="Layer Graph"
            description="Displayed sub goals"
            actions={graphActionButtons}
            className="min-h-0"
            contentClassName="min-h-0 p-0"
          >
            <div className="flex h-full flex-col">
              <div className="min-h-0 flex-1">
                {layerNodes.length > 0 ? (
                  <ReactFlow
                    nodes={flowNodes}
                    edges={[]}
                    nodeTypes={nodeTypes}
                    fitView
                    onNodeClick={onFlowNodeClick}
                    className="h-full w-full"
                  >
                    <Controls showInteractive={false} />
                    <Background gap={18} size={1} />
                  </ReactFlow>
                ) : (
                  <div className="flex h-full items-center justify-center px-4 text-sm text-muted-foreground">
                    No nodes in this layer. Decompose this parent or move to another layer.
                  </div>
                )}
              </div>
            </div>
          </ConsolePanel>

          <ConsolePanel
            title="Guided Workflow Chat"
            description="Command actions and monitor asynchronous job events"
            className="min-h-0"
            contentClassName="grid min-h-0 grid-rows-[1fr_auto] gap-3"
          >
            <ScrollArea className="rounded-md border bg-muted/20 p-3">
              <div className="space-y-2">
                {chatMessages.length === 0 ? (
                  <div className="text-sm text-muted-foreground">
                    Ask for an action, for example: &quot;decompose this node&quot; or
                    &quot;generate plan&quot;.
                  </div>
                ) : null}
                {chatMessages.map((message, index) => (
                  <div
                    key={`${message.created_at}-${index}`}
                    className={`rounded-md px-3 py-2 text-sm ${
                      message.role === "user"
                        ? "ml-auto max-w-[78%] bg-primary text-primary-foreground"
                        : message.role === "assistant"
                          ? "max-w-[78%] bg-secondary text-secondary-foreground"
                          : "max-w-full bg-muted text-muted-foreground"
                    }`}
                  >
                    {message.content}
                  </div>
                ))}
              </div>
            </ScrollArea>

            <div className="grid grid-cols-[1fr_auto] gap-2">
              <Input
                value={chatInput}
                onChange={(event) => setChatInput(event.target.value)}
                placeholder="Type instruction or ask for the next step"
                onKeyDown={(event) => {
                  if (event.key === "Enter") {
                    event.preventDefault();
                    void handleChatSend();
                  }
                }}
              />
              <Button onClick={() => void handleChatSend()}>
                <Send className="mr-1 h-4 w-4" /> Send
              </Button>
            </div>
          </ConsolePanel>
        </div>

        <div className="min-h-0 flex-1 lg:hidden">
          <Tabs value={mobileTab} onValueChange={setMobileTab} className="flex h-full flex-col">
            <TabsList className="w-full">
              <TabsTrigger value="graph" className="flex-1">
                Graph
              </TabsTrigger>
              <TabsTrigger value="chat" className="flex-1">
                Chat
              </TabsTrigger>
            </TabsList>

            <TabsContent value="graph" className="min-h-0 flex-1">
              <ConsolePanel
                title="Layer Graph"
                description="Tap a node to edit in drawer"
                actions={graphActionButtons}
                className="h-full"
                contentClassName="min-h-0 p-0"
              >
                <div className="min-h-0 h-full">
                  {layerNodes.length > 0 ? (
                    <ReactFlow
                      nodes={flowNodes}
                      edges={[]}
                      nodeTypes={nodeTypes}
                      fitView
                      onNodeClick={onFlowNodeClick}
                      className="h-full w-full"
                    >
                      <Controls showInteractive={false} />
                      <Background gap={16} size={1} />
                    </ReactFlow>
                  ) : (
                    <div className="flex h-full items-center justify-center px-4 text-sm text-muted-foreground">
                      No nodes in this layer.
                    </div>
                  )}
                </div>
              </ConsolePanel>
            </TabsContent>

            <TabsContent value="chat" className="min-h-0 flex-1">
              <ConsolePanel
                title="Workflow Chat"
                description="Run actions from natural language"
                className="h-full"
                contentClassName="grid min-h-0 grid-rows-[1fr_auto] gap-2"
              >
                <ScrollArea className="rounded-md border p-2">
                  <div className="space-y-2">
                    {chatMessages.map((message, index) => (
                      <div
                        key={`${message.created_at}-${index}`}
                        className={`rounded-md px-3 py-2 text-sm ${
                          message.role === "user"
                            ? "bg-primary text-primary-foreground"
                            : message.role === "assistant"
                              ? "bg-secondary text-secondary-foreground"
                              : "bg-muted text-muted-foreground"
                        }`}
                      >
                        {message.content}
                      </div>
                    ))}
                  </div>
                </ScrollArea>
                <div className="grid grid-cols-[1fr_auto] gap-2">
                  <Input
                    value={chatInput}
                    onChange={(event) => setChatInput(event.target.value)}
                    placeholder="Ask for next action"
                  />
                  <Button onClick={() => void handleChatSend()}>Send</Button>
                </div>
              </ConsolePanel>
            </TabsContent>
          </Tabs>
        </div>
      </main>

      <Sheet
        open={detailSheetOpen}
        onOpenChange={(open) => {
          setDetailSheetOpen(open);
          if (!open) {
            isEditingRef.current = false;
          }
        }}
      >
        <SheetContent
          side={isDesktopViewport ? "right" : "bottom"}
          className={
            isDesktopViewport
              ? "w-[680px] max-w-none overflow-hidden border-l"
              : "h-[92vh] w-full max-w-none overflow-hidden rounded-t-xl border-t"
          }
        >
          {selectedNode ? (
            <>
              <SheetHeader>
                <SheetTitle>{selectedNode.title}</SheetTitle>
                <SheetDescription>
                  Node {selectedNode.id} · layer {selectedNode.layer}
                </SheetDescription>
              </SheetHeader>

              <div className="my-4 flex flex-wrap gap-2">
                <Button size="sm" onClick={() => void handleDecompose()}>
                  <Layers className="mr-1 h-4 w-4" /> Decompose
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => void handleGenerateBaselineQuestions()}
                >
                  <ArrowRight className="mr-1 h-4 w-4" /> Baseline Questions
                </Button>
                <Button variant="outline" size="sm" onClick={() => void handleApplyBaseline()}>
                  Apply Baseline
                </Button>
                <Button variant="outline" size="sm" onClick={() => void handleGeneratePlan()}>
                  <SquareCheckBig className="mr-1 h-4 w-4" /> Generate Plan
                </Button>
                <Button variant="secondary" size="sm" onClick={() => void handleSaveNode()}>
                  Save Node
                </Button>
                <Button variant="secondary" size="sm" onClick={() => void handleSavePlan()}>
                  Save Plan
                </Button>
                <Button variant="secondary" size="sm" onClick={() => void handleAddNode()}>
                  <Plus className="mr-1 h-4 w-4" /> Add Node
                </Button>
                <Button variant="destructive" size="sm" onClick={() => void handleDeleteNode()}>
                  <Trash2 className="mr-1 h-4 w-4" /> Delete Node
                </Button>
              </div>

              <Separator />

              <ScrollArea
                className={
                  isDesktopViewport
                    ? "h-[calc(100vh-220px)] pr-3"
                    : "h-[calc(92vh-220px)] pr-3"
                }
              >
                <div className="space-y-5 py-4">
                  <div className="space-y-3">
                    <div className="text-xs font-semibold uppercase tracking-[0.14em] text-muted-foreground">
                      SMART Fields
                    </div>

                    <div className="grid gap-2">
                      <label className="text-xs text-muted-foreground">Title</label>
                      <Input
                        value={nodeTitle}
                        onChange={(event) => {
                          isEditingRef.current = true;
                          setNodeTitle(event.target.value);
                        }}
                      />
                    </div>

                    <div className="grid gap-2">
                      <label className="text-xs text-muted-foreground">Specific</label>
                      <Textarea
                        value={smartSpecific}
                        onChange={(event) => {
                          isEditingRef.current = true;
                          setSmartSpecific(event.target.value);
                        }}
                      />
                    </div>

                    <div className="grid gap-2">
                      <label className="text-xs text-muted-foreground">Measurable</label>
                      <Textarea
                        value={smartMeasurable}
                        onChange={(event) => {
                          isEditingRef.current = true;
                          setSmartMeasurable(event.target.value);
                        }}
                      />
                    </div>

                    <div className="grid gap-2">
                      <label className="text-xs text-muted-foreground">Achievable</label>
                      <Textarea
                        value={smartAchievable}
                        onChange={(event) => {
                          isEditingRef.current = true;
                          setSmartAchievable(event.target.value);
                        }}
                      />
                    </div>

                    <div className="grid gap-2">
                      <label className="text-xs text-muted-foreground">Relevant</label>
                      <Textarea
                        value={smartRelevant}
                        onChange={(event) => {
                          isEditingRef.current = true;
                          setSmartRelevant(event.target.value);
                        }}
                      />
                    </div>

                    <div className="grid gap-2">
                      <label className="text-xs text-muted-foreground">Time Bound</label>
                      <Input
                        value={smartTimeBound}
                        onChange={(event) => {
                          isEditingRef.current = true;
                          setSmartTimeBound(event.target.value);
                        }}
                      />
                    </div>
                  </div>

                  <Separator />

                  <div className="space-y-3">
                    <div className="text-xs font-semibold uppercase tracking-[0.14em] text-muted-foreground">
                      Baseline Q&A
                    </div>
                    {baselineQuestions.length === 0 ? (
                      <div className="rounded-md border border-border/80 bg-muted/20 px-3 py-2 text-sm text-muted-foreground">
                        Generate baseline questions to edit/apply answers.
                      </div>
                    ) : null}

                    {baselineQuestions.map((question) => (
                      <div key={question.id} className="space-y-1 rounded-md border border-border/60 p-3">
                        <div className="text-xs text-muted-foreground">[{question.category}]</div>
                        <div className="text-sm">{question.question}</div>
                        <Textarea
                          value={baselineAnswers[question.id] ?? ""}
                          onChange={(event) => {
                            isEditingRef.current = true;
                            setBaselineAnswers((previous) => ({
                              ...previous,
                              [question.id]: event.target.value,
                            }));
                          }}
                        />
                      </div>
                    ))}
                  </div>

                  <Separator />

                  <div className="space-y-3">
                    <div className="text-xs font-semibold uppercase tracking-[0.14em] text-muted-foreground">
                      Task Editor
                    </div>

                    {planDraft.tasks.map((task, index) => (
                      <div
                        key={`${task.title}-${index}`}
                        className="space-y-2 rounded-md border border-border/70 p-3"
                      >
                        <div className="flex items-center gap-2">
                          <Checkbox
                            checked={task.completed}
                            onCheckedChange={(checked) => {
                              const isChecked = checked === true;
                              setPlanDraft((previous) => {
                                const nextTasks = cloneTasks(previous.tasks);
                                nextTasks[index].completed = isChecked;
                                return { ...previous, tasks: nextTasks };
                              });
                              void toggleTaskAtIndex(index, isChecked);
                            }}
                          />
                          <Input
                            value={task.title}
                            onChange={(event) => {
                              isEditingRef.current = true;
                              const value = event.target.value;
                              setPlanDraft((previous) => {
                                const nextTasks = cloneTasks(previous.tasks);
                                nextTasks[index].title = value;
                                return { ...previous, tasks: nextTasks };
                              });
                            }}
                            placeholder="Task title"
                          />
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => {
                              isEditingRef.current = true;
                              setPlanDraft((previous) => ({
                                ...previous,
                                tasks: previous.tasks.filter((_, itemIndex) => itemIndex !== index),
                              }));
                            }}
                          >
                            <Minus className="h-4 w-4" />
                          </Button>
                        </div>

                        <Textarea
                          value={task.description}
                          onChange={(event) => {
                            isEditingRef.current = true;
                            const value = event.target.value;
                            setPlanDraft((previous) => {
                              const nextTasks = cloneTasks(previous.tasks);
                              nextTasks[index].description = value;
                              return { ...previous, tasks: nextTasks };
                            });
                          }}
                          placeholder="Description"
                        />

                        <Input
                          value={task.success_criteria}
                          onChange={(event) => {
                            isEditingRef.current = true;
                            const value = event.target.value;
                            setPlanDraft((previous) => {
                              const nextTasks = cloneTasks(previous.tasks);
                              nextTasks[index].success_criteria = value;
                              return { ...previous, tasks: nextTasks };
                            });
                          }}
                          placeholder="Success criteria"
                        />

                        <Input
                          value={task.depends_on.join(", ")}
                          onChange={(event) => {
                            isEditingRef.current = true;
                            const dependsOn = event.target.value
                              .split(",")
                              .map((item) => item.trim())
                              .filter(Boolean);
                            setPlanDraft((previous) => {
                              const nextTasks = cloneTasks(previous.tasks);
                              nextTasks[index].depends_on = dependsOn;
                              return { ...previous, tasks: nextTasks };
                            });
                          }}
                          placeholder="Depends on task titles"
                        />

                        <div className="grid gap-2 sm:grid-cols-2">
                          <Input
                            value={task.relative_timing ?? ""}
                            onChange={(event) => {
                              isEditingRef.current = true;
                              const value = event.target.value;
                              setPlanDraft((previous) => {
                                const nextTasks = cloneTasks(previous.tasks);
                                nextTasks[index].relative_timing = value;
                                return { ...previous, tasks: nextTasks };
                              });
                            }}
                            placeholder="Relative timing"
                          />
                          <Input
                            value={task.due ?? ""}
                            onChange={(event) => {
                              isEditingRef.current = true;
                              const value = event.target.value;
                              setPlanDraft((previous) => {
                                const nextTasks = cloneTasks(previous.tasks);
                                nextTasks[index].due = value;
                                return { ...previous, tasks: nextTasks };
                              });
                            }}
                            placeholder="Due"
                          />
                        </div>
                      </div>
                    ))}

                    <div className="flex flex-wrap gap-2">
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => {
                          isEditingRef.current = true;
                          setPlanDraft((previous) => ({
                            ...previous,
                            tasks: [...previous.tasks, newTask()],
                          }));
                        }}
                      >
                        <Plus className="mr-1 h-4 w-4" /> Add Task
                      </Button>
                      <Button size="sm" onClick={() => void handleSavePlan()}>
                        Save Plan Edits
                      </Button>
                    </div>
                  </div>
                </div>
              </ScrollArea>
            </>
          ) : (
            <div className="py-8 text-sm text-muted-foreground">No node selected.</div>
          )}
        </SheetContent>
      </Sheet>
    </div>
  );
}
