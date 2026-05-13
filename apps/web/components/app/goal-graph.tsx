"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import ELK from "elkjs/lib/elk.bundled.js";
import type { ElkNode } from "elkjs/lib/elk-api";
import ReactFlow, {
  Background,
  Connection,
  Edge,
  MarkerType,
  Node as FlowNode,
  NodeMouseHandler,
  Position,
  useEdgesState,
  useNodesState,
  type ReactFlowInstance,
} from "reactflow";

import {
  LayerGraphNode,
  type LayerGraphNodeData,
} from "@/components/app/layer-graph-node";
import {
  assessAgentCapability,
  type AgentCapabilityMatch,
} from "@/lib/agent-capabilities";
import { displayNodeTitle } from "@/lib/graph-paths";
import type { Node, NodePosition, NodeProgress, SuggestedConnection } from "@/lib/types";

const START_X = 52;
const STACK_CENTER_Y = 0;
const STACK_GAP = 560;
const RANK_GAP = 300;
const RANK_ROW_GAP = 130;
const NODE_WIDTH = 560;
const BASE_NODE_HEIGHT = 230;
const MIN_TASK_NODE_HEIGHT = 320;
const TASK_CONTENT_OFFSET = 245;
const TASK_LINE_HEIGHT = 32;
const TASK_ROW_GAP = 12;
const TASK_TEXT_CHARS_PER_LINE = 42;
const elk = new ELK();
const nodeTypes = { layerNode: LayerGraphNode };

interface GoalGraphProps {
  focusParent: Node | null;
  layerNodes: Node[];
  nodeProgress: Record<string, NodeProgress>;
  selectedNodeId: string;
  suggestedConnections?: SuggestedConnection[];
  busyNodeId?: string | null;
  isDraftingLayer?: boolean;
  dragType: string;
  onSelectNode: (nodeId: string) => void;
  onInspectNode: (nodeId: string) => void;
  onCreateNodeAtPosition: (position: NodePosition) => void;
  onPersistNodePosition: (nodeId: string, position: NodePosition) => void;
  onCreateConnection: (sourceId: string, targetId: string) => void;
  onDeleteConnection: (sourceId: string, targetId: string) => void;
  onDeleteNodes: (nodeIds: string[]) => void;
  onAgentAssist: (nodeId: string, match: AgentCapabilityMatch) => void;
  onToggleTask: (nodeId: string, taskIndex: number, completed: boolean) => void;
  onRegisterCanvasApi?: (api: { fitView: () => void }) => void;
}

function hasIndirectPath(
  sourceId: string,
  targetId: string,
  adjacency: Map<string, Set<string>>,
  skippedEdge: readonly [string, string]
) {
  const stack = [...(adjacency.get(sourceId) ?? [])].filter(
    (nextId) => !(sourceId === skippedEdge[0] && nextId === skippedEdge[1])
  );
  const visited = new Set<string>();

  while (stack.length > 0) {
    const currentId = stack.pop();
    if (!currentId || visited.has(currentId)) {
      continue;
    }
    if (currentId === targetId) {
      return true;
    }
    visited.add(currentId);
    for (const nextId of adjacency.get(currentId) ?? []) {
      if (currentId === skippedEdge[0] && nextId === skippedEdge[1]) {
        continue;
      }
      stack.push(nextId);
    }
  }

  return false;
}

function simplifyTransitiveConnections(
  layerNodes: Node[],
  suggestedConnections: SuggestedConnection[]
) {
  const layerIds = new Set(layerNodes.map((node) => node.id));
  const validConnections = suggestedConnections.filter(
    (connection) =>
      connection.source_id !== connection.target_id &&
      layerIds.has(connection.source_id) &&
      layerIds.has(connection.target_id)
  );
  const adjacency = new Map<string, Set<string>>();

  for (const connection of validConnections) {
    const targets = adjacency.get(connection.source_id) ?? new Set<string>();
    targets.add(connection.target_id);
    adjacency.set(connection.source_id, targets);
  }

  return validConnections.filter(
    (connection) =>
      !hasIndirectPath(connection.source_id, connection.target_id, adjacency, [
        connection.source_id,
        connection.target_id,
      ])
  );
}

function buildEdges(
  layerNodes: Node[],
  selectedNodeId: string,
  busyNodeId?: string | null,
  suggestedConnections: SuggestedConnection[] = []
): Edge[] {
  const layerIds = new Set(layerNodes.map((node) => node.id));
  return suggestedConnections.flatMap((connection) => {
    if (
      !layerIds.has(connection.source_id) ||
      !layerIds.has(connection.target_id) ||
      connection.source_id === connection.target_id
    ) {
      return [];
    }

    const emphasized =
      selectedNodeId === connection.source_id || selectedNodeId === connection.target_id;

    return [
      {
        id: `suggested-${connection.source_id}-${connection.target_id}`,
        source: connection.source_id,
        target: connection.target_id,
        type: "smoothstep",
        animated: false,
        markerEnd: {
          type: MarkerType.ArrowClosed,
          width: 14,
          height: 14,
          color: emphasized ? "rgba(127, 219, 202, 0.92)" : "rgba(127, 219, 202, 0.58)",
        },
        style: {
          stroke: emphasized ? "rgba(127, 219, 202, 0.84)" : "rgba(127, 219, 202, 0.42)",
          strokeDasharray: "6 8",
          strokeWidth: emphasized ? 1.8 : 1.25,
        },
        labelStyle: {
          fill: "rgba(225, 255, 250, 0.62)",
          fontSize: 10,
          fontWeight: 500,
        },
        labelBgStyle: {
          fill: "rgba(8, 8, 12, 0.82)",
          fillOpacity: 0.82,
        },
      },
    ];
  });
}

function fallbackLayoutNodes(layerNodes: Node[]) {
  return new Map(
    layerNodes.map((node, index) => [
      node.id,
      {
        x: START_X,
        y: STACK_CENTER_Y + (index - (layerNodes.length - 1) / 2) * STACK_GAP,
      },
    ])
  );
}

function taskBlurb(task: NonNullable<Node["plan"]>["tasks"][number]) {
  const title = task.title.trim();
  const description = task.description.trim();
  const text = description ? `${title}: ${description}` : title;
  return text.replace(/\s+/g, " ").trim();
}

function taskLineCount(task: NonNullable<Node["plan"]>["tasks"][number]) {
  return Math.max(1, Math.ceil(taskBlurb(task).length / TASK_TEXT_CHARS_PER_LINE));
}

function nodeHeight(node: Node) {
  const tasks = node.plan?.tasks ?? [];
  if (tasks.length === 0) {
    return BASE_NODE_HEIGHT;
  }
  const taskHeight = tasks.reduce(
    (height, task) => height + taskLineCount(task) * TASK_LINE_HEIGHT + TASK_ROW_GAP,
    0
  );
  return Math.max(MIN_TASK_NODE_HEIGHT, TASK_CONTENT_OFFSET + taskHeight);
}

function rankLayoutNodes(
  layerNodes: Node[],
  suggestedConnections: SuggestedConnection[]
) {
  const nodeById = new Map(layerNodes.map((node) => [node.id, node]));
  const originalOrder = new Map(layerNodes.map((node, index) => [node.id, index]));
  const incoming = new Map<string, Set<string>>();
  const outgoing = new Map<string, Set<string>>();

  for (const connection of suggestedConnections) {
    if (!nodeById.has(connection.source_id) || !nodeById.has(connection.target_id)) {
      continue;
    }
    const targets = outgoing.get(connection.source_id) ?? new Set<string>();
    targets.add(connection.target_id);
    outgoing.set(connection.source_id, targets);

    const sources = incoming.get(connection.target_id) ?? new Set<string>();
    sources.add(connection.source_id);
    incoming.set(connection.target_id, sources);
  }

  const ranks = new Map<string, number>();
  const rankForNode = (nodeId: string, visiting = new Set<string>()): number => {
    const cached = ranks.get(nodeId);
    if (cached !== undefined) {
      return cached;
    }
    if (visiting.has(nodeId)) {
      return 0;
    }
    visiting.add(nodeId);
    const rank = Math.max(
      0,
      ...[...(incoming.get(nodeId) ?? [])].map((sourceId) => rankForNode(sourceId, visiting) + 1)
    );
    visiting.delete(nodeId);
    ranks.set(nodeId, rank);
    return rank;
  };

  for (const node of layerNodes) {
    rankForNode(node.id);
  }

  const idsByRank = new Map<number, string[]>();
  for (const node of layerNodes) {
    const rank = ranks.get(node.id) ?? 0;
    const ids = idsByRank.get(rank) ?? [];
    ids.push(node.id);
    idsByRank.set(rank, ids);
  }

  const sortedRanks = [...idsByRank.keys()].sort((a, b) => a - b);
  const orderWithinRank = new Map<string, number>();
  for (const rank of sortedRanks) {
    const ids = idsByRank.get(rank) ?? [];
    ids.sort((leftId, rightId) => {
      const leftNeighbors = [
        ...(incoming.get(leftId) ?? []),
        ...(outgoing.get(leftId) ?? []),
      ];
      const rightNeighbors = [
        ...(incoming.get(rightId) ?? []),
        ...(outgoing.get(rightId) ?? []),
      ];
      const leftMedian =
        leftNeighbors.reduce(
          (total, nodeId) =>
            total + (orderWithinRank.get(nodeId) ?? originalOrder.get(nodeId) ?? 0),
          0
        ) / Math.max(1, leftNeighbors.length);
      const rightMedian =
        rightNeighbors.reduce(
          (total, nodeId) =>
            total + (orderWithinRank.get(nodeId) ?? originalOrder.get(nodeId) ?? 0),
          0
        ) / Math.max(1, rightNeighbors.length);
      return leftMedian - rightMedian || (originalOrder.get(leftId) ?? 0) - (originalOrder.get(rightId) ?? 0);
    });
    ids.forEach((nodeId, index) => orderWithinRank.set(nodeId, index));
  }

  const positions = new Map<string, NodePosition>();
  for (const rank of sortedRanks) {
    const ids = idsByRank.get(rank) ?? [];
    const columnHeight = ids.reduce(
      (total, nodeId, index) =>
        total + nodeHeight(nodeById.get(nodeId) as Node) + (index === 0 ? 0 : RANK_ROW_GAP),
      0
    );
    let y = STACK_CENTER_Y - columnHeight / 2;

    for (const nodeId of ids) {
      const node = nodeById.get(nodeId);
      if (!node) {
        continue;
      }
      const height = nodeHeight(node);
      positions.set(nodeId, {
        x: START_X + rank * (NODE_WIDTH + RANK_GAP),
        y: y + height / 2,
      });
      y += height + RANK_ROW_GAP;
    }
  }

  return positions;
}

async function layoutChildNodes(
  layerNodes: Node[],
  suggestedConnections: SuggestedConnection[]
) {
  const autoNodeIds = new Set(
    layerNodes
      .filter((node) => node.ui.layout_mode !== "manual" || node.ui.position === null)
      .map((node) => node.id)
  );

  if (autoNodeIds.size === 0) {
    return new Map<string, NodePosition>();
  }

  const rankedPositions = rankLayoutNodes(layerNodes, suggestedConnections);
  if (rankedPositions.size > 0) {
    return new Map(
      Array.from(rankedPositions.entries()).filter(([nodeId]) => autoNodeIds.has(nodeId))
    );
  }

  const layerIds = new Set(layerNodes.map((node) => node.id));
  const elkGraph: ElkNode = {
    id: "goal-layer",
    layoutOptions: {
      "elk.algorithm": "layered",
      "elk.direction": "RIGHT",
      "elk.padding": "[top=64,left=64,bottom=64,right=64]",
      "elk.spacing.nodeNode": "124",
      "elk.spacing.componentComponent": "140",
      "elk.layered.spacing.nodeNodeBetweenLayers": "184",
      "elk.layered.nodePlacement.strategy": "BRANDES_KOEPF",
      "elk.layered.considerModelOrder.strategy": "NODES_AND_EDGES",
      "elk.layered.crossingMinimization.forceNodeModelOrder": "true",
    },
    children: layerNodes.map((node) => ({
      id: node.id,
      width: NODE_WIDTH,
      height: nodeHeight(node),
    })),
    edges: suggestedConnections.flatMap((connection) => {
      if (
        connection.source_id === connection.target_id ||
        !layerIds.has(connection.source_id) ||
        !layerIds.has(connection.target_id)
      ) {
        return [];
      }
      return [
        {
          id: `elk-${connection.source_id}-${connection.target_id}`,
          sources: [connection.source_id],
          targets: [connection.target_id],
        },
      ];
    }),
  };

  try {
    const layout = await elk.layout(elkGraph);
    const positions = new Map<string, NodePosition>();
    for (const child of layout.children ?? []) {
      if (!autoNodeIds.has(child.id)) {
        continue;
      }
      positions.set(child.id, {
        x: child.x ?? START_X,
        y: child.y ?? STACK_CENTER_Y,
      });
    }
    return positions;
  } catch (error) {
    console.warn("[smartgot] ELK layout failed; falling back to stacked layout.", error);
    const fallback = fallbackLayoutNodes(layerNodes);
    return new Map(
      Array.from(fallback.entries()).filter(([nodeId]) => autoNodeIds.has(nodeId))
    );
  }
}

export function GoalGraph({
  focusParent,
  layerNodes,
  selectedNodeId,
  suggestedConnections = [],
  busyNodeId,
  isDraftingLayer = false,
  dragType,
  onSelectNode,
  onInspectNode,
  onCreateNodeAtPosition,
  onPersistNodePosition,
  onCreateConnection,
  onDeleteConnection,
  onDeleteNodes,
  onAgentAssist,
  onToggleTask,
  onRegisterCanvasApi,
}: GoalGraphProps) {
  const [flowNodes, setFlowNodes, onNodesChange] = useNodesState<LayerGraphNodeData>([]);
  const [flowEdges, setFlowEdges, onEdgesChange] = useEdgesState<Edge>([]);
  const flowRef = useRef<ReactFlowInstance<LayerGraphNodeData, Edge> | null>(null);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const lastFocusIdRef = useRef<string | null>(null);
  const lastLayoutSignatureRef = useRef<string | null>(null);
  const shouldFitAfterInitRef = useRef(false);
  const selectedNodeIdRef = useRef(selectedNodeId);
  selectedNodeIdRef.current = selectedNodeId;

  const fitView = useCallback(() => {
    const instance = flowRef.current;
    if (!instance) {
      return;
    }
    window.requestAnimationFrame(() => {
      window.requestAnimationFrame(() => {
        instance.fitView({
          padding: 0.06,
          minZoom: 0.15,
          maxZoom: 1.8,
          duration: 0,
        });
      });
    });
  }, []);

  const scheduleFitView = useCallback(() => {
    fitView();
    window.setTimeout(() => fitView(), 120);
  }, [fitView]);

  useEffect(() => {
    if (!onRegisterCanvasApi) {
      return;
    }
    onRegisterCanvasApi({ fitView });
  }, [fitView, onRegisterCanvasApi]);

  const visibleConnections = useMemo(() => {
    return simplifyTransitiveConnections(layerNodes, suggestedConnections);
  }, [layerNodes, suggestedConnections]);

  const edges = useMemo(() => {
    return buildEdges(layerNodes, selectedNodeId, busyNodeId, visibleConnections);
  }, [busyNodeId, layerNodes, selectedNodeId, visibleConnections]);

  const layoutSignature = useMemo(() => {
    const nodeSignature = layerNodes
      .map((node) => {
        const position = node.ui.position;
        return [
          node.id,
          node.ui.layout_mode,
          position ? `${position.x},${position.y}` : "auto",
          node.plan?.tasks.length ?? 0,
          nodeHeight(node),
        ].join(":");
      })
      .join("|");
    const edgeSignature = visibleConnections
      .map((connection) => `${connection.source_id}>${connection.target_id}`)
      .join("|");
    return `${focusParent?.id ?? "none"}::${nodeSignature}::${edgeSignature}`;
  }, [focusParent?.id, layerNodes, visibleConnections]);

  useEffect(() => {
    let cancelled = false;

    async function applyLayout() {
      if (!focusParent) {
        setFlowNodes([]);
        setFlowEdges([]);
        return;
      }

      const autoPositions = await layoutChildNodes(layerNodes, visibleConnections);
      if (cancelled) {
        return;
      }

      const nextNodes: FlowNode<LayerGraphNodeData>[] = layerNodes.map((node, index) => {
        const height = nodeHeight(node);
        const agentAssist = assessAgentCapability(node);
        return {
          id: node.id,
          type: "layerNode",
          draggable: true,
          selectable: true,
          selected: node.id === selectedNodeIdRef.current,
          sourcePosition: Position.Right,
          targetPosition: Position.Left,
          position:
            node.ui.layout_mode === "manual" && node.ui.position
              ? node.ui.position
              : autoPositions.get(node.id) ?? {
                  x: START_X,
                  y: STACK_CENTER_Y + (index - (layerNodes.length - 1) / 2) * STACK_GAP,
                },
          style: {
            width: NODE_WIDTH,
            minHeight: height,
          },
          data: {
            title: displayNodeTitle(node),
            status: node.status,
            kind: "goal" as const,
            tasks:
              node.plan?.tasks.map((task, taskIndex) => ({
                index: taskIndex,
                blurb: taskBlurb(task),
                completed: task.completed,
              })) ?? [],
            taskCount: node.plan?.tasks.length ?? 0,
            completedTaskCount: node.plan?.tasks.filter((task) => task.completed).length ?? 0,
            width: NODE_WIDTH,
            height,
            busy: false,
            agentAssist: agentAssist ?? undefined,
            onAgentAssist: agentAssist ? () => onAgentAssist(node.id, agentAssist) : undefined,
            onInspect: () => onInspectNode(node.id),
            onToggleTask: (taskIndex, completed) => onToggleTask(node.id, taskIndex, completed),
          },
        };
      });

      setFlowNodes(nextNodes);

      const hasManualNodes = layerNodes.some(
        (node) => node.ui.layout_mode === "manual" && node.ui.position
      );
      const focusChanged = lastFocusIdRef.current !== focusParent.id;
      const layoutChanged = lastLayoutSignatureRef.current !== layoutSignature;
      lastLayoutSignatureRef.current = layoutSignature;

      if (focusChanged || (!hasManualNodes && layoutChanged)) {
        lastFocusIdRef.current = focusParent.id;
        shouldFitAfterInitRef.current = true;
        if (flowRef.current) {
          shouldFitAfterInitRef.current = false;
          scheduleFitView();
        }
      }
    }

    applyLayout();

    return () => {
      cancelled = true;
    };
  }, [
    fitView,
    focusParent,
    layerNodes,
    layoutSignature,
    onAgentAssist,
    onInspectNode,
    onToggleTask,
    scheduleFitView,
    setFlowEdges,
    setFlowNodes,
    visibleConnections,
  ]);

  useEffect(() => {
    setFlowEdges(edges);
  }, [edges, setFlowEdges]);

  useEffect(() => {
    setFlowNodes((currentNodes) =>
      currentNodes.map((node) => ({
        ...node,
        selected: node.id === selectedNodeId,
        data: {
          ...node.data,
          busy: busyNodeId === node.id,
        },
      }))
    );
  }, [busyNodeId, selectedNodeId, setFlowNodes]);

  useEffect(() => {
    const element = containerRef.current;
    if (!element) {
      return;
    }

    const observer = new ResizeObserver(() => {
      if (lastFocusIdRef.current === focusParent?.id) {
        fitView();
      }
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, [fitView, focusParent?.id]);

  const handleNodeClick = useCallback<NodeMouseHandler>(
    (_event, node) => {
      if (!layerNodes.some((layerNode) => layerNode.id === node.id)) {
        return;
      }
      onSelectNode(node.id);
    },
    [layerNodes, onSelectNode]
  );

  const handleDrop = useCallback(
    (event: React.DragEvent<HTMLDivElement>) => {
      if (!event.dataTransfer.types.includes(dragType)) {
        return;
      }
      event.preventDefault();
      const instance = flowRef.current;
      if (!instance) {
        return;
      }
      const position = instance.screenToFlowPosition({
        x: event.clientX,
        y: event.clientY,
      });
      onCreateNodeAtPosition(position);
    },
    [dragType, onCreateNodeAtPosition]
  );

  const handleConnect = useCallback(
    (connection: Connection) => {
      if (!connection.source || !connection.target || connection.source === connection.target) {
        return;
      }
      onCreateConnection(connection.source, connection.target);
    },
    [onCreateConnection]
  );

  if (!focusParent) {
    return (
      <div className="flex h-full items-center justify-center px-4 text-sm text-muted-foreground">
        No focus layer available yet.
      </div>
    );
  }

  if (layerNodes.length === 0) {
    return (
      <div className="flex h-full items-center justify-center px-5 text-center">
        <div className="max-w-sm rounded-[22px] border border-white/8 bg-white/[0.035] px-5 py-4">
          <div className="text-[10px] font-medium uppercase tracking-[0.18em] text-white/34">
            {isDraftingLayer ? "Decomposing layer" : "No goals yet"}
          </div>
          <div className="mt-2 text-[15px] font-medium text-white">
            {isDraftingLayer
              ? `Building sub-goals for ${displayNodeTitle(focusParent, "this goal")}`
              : `No sub-goals created for ${displayNodeTitle(focusParent, "this goal")}`}
          </div>
          <div className="mt-1.5 text-[12px] leading-5 text-white/48">
            {isDraftingLayer
              ? "Goals will appear here one by one as AIMIGO decomposes the layer."
              : "Choose decompose to generate the first visible graph layer."}
          </div>
        </div>
      </div>
    );
  }

  return (
    <div
      ref={containerRef}
      className="h-full w-full"
      onDragOver={(event) => {
        if (event.dataTransfer.types.includes(dragType)) {
          event.preventDefault();
          event.dataTransfer.dropEffect = "copy";
        }
      }}
      onDrop={handleDrop}
    >
      <ReactFlow
        nodes={flowNodes}
        edges={flowEdges}
        nodeTypes={nodeTypes}
        minZoom={0.15}
        maxZoom={1.8}
        fitView={false}
        onInit={(instance) => {
          flowRef.current = instance;
          if (shouldFitAfterInitRef.current) {
            shouldFitAfterInitRef.current = false;
            scheduleFitView();
          }
        }}
        onNodeClick={handleNodeClick}
        onNodeDragStop={(_event, node) => {
          onPersistNodePosition(node.id, node.position);
        }}
        onConnect={handleConnect}
        onEdgesDelete={(deletedEdges) => {
          for (const edge of deletedEdges) {
            onDeleteConnection(edge.source, edge.target);
          }
        }}
        onNodesDelete={(deletedNodes) => {
          onDeleteNodes(deletedNodes.map((node) => node.id));
        }}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        nodesDraggable
        nodesConnectable
        elementsSelectable
        deleteKeyCode={["Backspace", "Delete"]}
        proOptions={{ hideAttribution: true }}
      >
        <Background gap={28} size={1} color="rgba(255,255,255,0.05)" />
      </ReactFlow>
    </div>
  );
}
