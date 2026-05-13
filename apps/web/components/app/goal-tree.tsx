"use client";

import { useEffect, useMemo, useState } from "react";
import { CheckCheck, ChevronRight } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { displayGoalStatus } from "@/lib/graph-paths";
import { cn } from "@/lib/utils";
import type { Graph, Node, NodeProgress } from "@/lib/types";

interface GoalTreeProps {
  graph: Graph;
  focusParentId: string | null;
  selectedNodeId: string;
  nodeProgress: Record<string, NodeProgress>;
  onNodeSelect: (nodeId: string) => void | Promise<void>;
  onToggleNodeProgress?: (nodeId: string, progress: NodeProgress) => void | Promise<void>;
}

function statusVariant(status: Node["status"]): "default" | "secondary" | "outline" {
  if (status === "PLANNED") {
    return "default";
  }
  if (status === "BASELINED") {
    return "secondary";
  }
  return "outline";
}

function collectAncestorIds(graph: Graph, startId: string | null | undefined) {
  const ids = new Set<string>();
  let currentId = startId ?? null;

  while (currentId) {
    ids.add(currentId);
    currentId = graph.nodes[currentId]?.parent_id ?? null;
  }

  ids.add(graph.root_id);
  return ids;
}

function hasTreeChildren(graph: Graph, node: Node) {
  return node.children_ids.some((childId) => Boolean(graph.nodes[childId]));
}

export function GoalTree({
  graph,
  focusParentId,
  selectedNodeId,
  nodeProgress,
  onNodeSelect,
  onToggleNodeProgress,
}: GoalTreeProps) {
  const focusParent = focusParentId ? graph.nodes[focusParentId] ?? null : null;
  const focusLayerChildIds = useMemo(
    () => new Set(focusParent?.children_ids ?? []),
    [focusParent?.children_ids]
  );

  const alwaysOpenIds = useMemo(() => {
    const ids = collectAncestorIds(graph, selectedNodeId);
    for (const id of collectAncestorIds(graph, focusParentId)) {
      ids.add(id);
    }
    return ids;
  }, [focusParentId, graph, selectedNodeId]);

  const [openNodeIds, setOpenNodeIds] = useState<Record<string, boolean>>({});

  useEffect(() => {
    setOpenNodeIds((previous) => {
      const next = { ...previous };
      for (const id of alwaysOpenIds) {
        next[id] = true;
      }
      return next;
    });
  }, [alwaysOpenIds]);

  const renderNode = (nodeId: string, depth = 0): JSX.Element | null => {
    const node = graph.nodes[nodeId];
    if (!node) {
      return null;
    }

    const hasChildren = hasTreeChildren(graph, node);
    const isOpen = openNodeIds[node.id] ?? alwaysOpenIds.has(node.id);
    const isSelected = selectedNodeId === node.id;
    const isFocusParent = focusParentId === node.id;
    const isLayerGoal = focusLayerChildIds.has(node.id);
    const progress = nodeProgress[node.id];

    return (
      <Collapsible
        key={node.id}
        open={hasChildren ? isOpen : undefined}
        onOpenChange={(open) =>
          setOpenNodeIds((previous) => ({
            ...previous,
            [node.id]: open,
          }))
        }
      >
        <div className="space-y-1" style={{ marginLeft: depth === 0 ? 0 : depth * 6 }}>
          <div className="flex items-start gap-1">
            <div className="flex w-4 shrink-0 justify-center pt-1.5">
              {hasChildren ? (
                <CollapsibleTrigger asChild>
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    className="h-4 w-4 rounded-full text-white/26 hover:text-white/72"
                  >
                    <ChevronRight
                      className={cn("h-3 w-3 transition-transform", isOpen && "rotate-90")}
                    />
                  </Button>
                </CollapsibleTrigger>
              ) : (
                <span className="mt-[7px] h-1.5 w-1.5 rounded-full bg-white/[0.12]" />
              )}
            </div>

            <div className="flex min-w-0 flex-1 items-stretch gap-1">
              <button
                type="button"
                className={cn(
                  "group flex min-w-0 flex-1 flex-col rounded-[12px] border px-2 py-1.5 text-left transition",
                  isSelected
                    ? "border-primary/20 bg-primary/[0.1]"
                    : isFocusParent
                      ? "border-white/8 bg-white/[0.045]"
                      : isLayerGoal
                        ? "border-white/6 bg-white/[0.025]"
                        : "border-transparent bg-transparent hover:border-white/6 hover:bg-white/[0.02]"
                )}
                onClick={() => {
                  void onNodeSelect(node.id);
                }}
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <div className="truncate text-[12px] font-medium leading-tight text-white/92">{node.title}</div>
                    <div className="mt-0.5 flex flex-wrap items-center gap-1 text-[8px] uppercase tracking-[0.14em] text-white/28">
                      <span>{node.workstream}</span>
                      {isFocusParent ? <span className="text-violet-200/72">Focus</span> : null}
                      {!isFocusParent && isLayerGoal ? (
                        <span className="text-white/36">Layer</span>
                      ) : null}
                    </div>
                  </div>

                  <Badge
                    variant={statusVariant(node.status)}
                    className="rounded-full border-white/6 bg-transparent px-1.5 py-0.5 text-[8px] uppercase tracking-[0.1em] text-white/48"
                  >
                    {displayGoalStatus(node.status)}
                  </Badge>
                </div>

                <div className="mt-1.5 flex flex-wrap items-center gap-1.5 text-[9px] text-white/34">
                  <span>
                    {progress ? `${progress.completed_tasks}/${progress.total_tasks} tasks` : "No plan"}
                  </span>
                  <span>{node.children_ids.length} subgoals</span>
                </div>
              </button>

              {progress && progress.total_tasks > 0 && onToggleNodeProgress ? (
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  className={cn(
                    "mt-1 h-6 w-6 shrink-0 rounded-full border border-white/6 bg-transparent text-white/38 hover:bg-white/[0.02] hover:text-white/68",
                    progress.check_state === "checked" && "border-primary/16 bg-primary/[0.1] text-primary"
                  )}
                  onClick={() => {
                    void onToggleNodeProgress(node.id, progress);
                  }}
                >
                  <CheckCheck className="h-3 w-3" />
                </Button>
              ) : null}
            </div>
          </div>

          {hasChildren ? (
            <CollapsibleContent className="overflow-hidden">
              <div className="ml-3 border-l border-white/5 pl-1">
                {node.children_ids.map((childId) => renderNode(childId, depth + 1))}
              </div>
            </CollapsibleContent>
          ) : null}
        </div>
      </Collapsible>
    );
  };

  return (
    <div className="space-y-1.5">
      {renderNode(graph.root_id)}
    </div>
  );
}
