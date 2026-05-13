"use client";

import { Bot, Sparkles, Target } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  buildPathIds,
  displayGoalStatus,
  displayNodeTitle,
  formatPathText,
  resolveSuggestedPathIds,
} from "@/lib/graph-paths";
import { assessAgentCapability } from "@/lib/agent-capabilities";
import type { Graph, Node, NodeProgress } from "@/lib/types";
import { formatTaskRollup, nextNodeAction } from "@/lib/workflow";

interface NodeDetailSidebarProps {
  graph: Graph | null;
  selectedNode: Node | null;
  selectedProgress: NodeProgress | null;
  focusParent: Node | null;
  onOpenEditor: () => void;
  onCreateChild: () => void;
  onCreateSibling: () => void;
  onGeneratePlan: () => void;
  onGoDeeper: () => void;
  onFocusSelectedNode: () => void;
}

function smartRows(node: Node) {
  return [
    ["Specific", node.smart.specific],
    ["Measurable", node.smart.measurable],
    ["Achievable", node.smart.achievable],
    ["Relevant", node.smart.relevant],
    ["Time bound", node.smart.time_bound],
  ].filter(([, value]) => value.trim());
}

export function NodeDetailSidebar({
  graph,
  selectedNode,
  selectedProgress,
  focusParent,
  onOpenEditor,
  onCreateChild,
  onCreateSibling,
  onGeneratePlan,
  onGoDeeper,
  onFocusSelectedNode,
}: NodeDetailSidebarProps) {
  if (!selectedNode) {
    return (
      <div className="flex h-full items-center justify-center px-6 text-sm text-white/44">
        Select a goal to inspect its structure and next actions.
      </div>
    );
  }

  const nextTask =
    selectedNode.plan?.tasks.find((task) => !task.completed) ?? selectedNode.plan?.tasks[0] ?? null;
  const smart = smartRows(selectedNode);
  const isFocusNode = selectedNode.id === focusParent?.id;
  const currentPath = graph
    ? formatPathText(
        graph,
        buildPathIds(
          graph,
          selectedNode.parent_id ?? graph.root_id,
          selectedNode.id
        )
      )
    : null;
  const suggestedPath = graph ? formatPathText(graph, resolveSuggestedPathIds(graph, selectedNode)) : null;
  const pathChanged = Boolean(suggestedPath && currentPath && suggestedPath !== currentPath);
  const workstreamLabel = selectedNode.workstream.trim() || "General";
  const agentCapability = assessAgentCapability(selectedNode);

  return (
    <div className="flex h-full min-h-0 flex-col bg-[rgba(9,9,12,0.96)]">
      <div className="border-b border-white/6 px-5 py-5">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="text-[10px] uppercase tracking-[0.16em] text-white/30">
              Goal inspector
            </div>
            <div className="mt-2 truncate text-[20px] font-medium tracking-[-0.03em] text-white">
              {displayNodeTitle(selectedNode)}
            </div>
            <div className="mt-1 text-sm text-white/40">{workstreamLabel}</div>
          </div>
          <Badge
            variant={selectedNode.status === "PLANNED" ? "default" : "outline"}
            className="rounded-full border-white/8 bg-white/[0.04] px-2 py-0.5 text-[9px] uppercase tracking-[0.12em]"
          >
            {displayGoalStatus(selectedNode.status)}
          </Badge>
        </div>

        <div className="mt-4 grid gap-2">
          <div className="rounded-[18px] border border-white/8 bg-white/[0.03] px-3 py-2.5 text-[13px] text-white/68">
            {nextNodeAction(selectedNode, selectedProgress)}
          </div>
          <div className="flex flex-wrap gap-2">
            <Button size="sm" onClick={onOpenEditor}>
              Edit goal
            </Button>
            <Button size="sm" variant="outline" onClick={onCreateChild}>
              Add child
            </Button>
            <Button size="sm" variant="outline" onClick={onCreateSibling} disabled={!selectedNode.parent_id}>
              Add sibling
            </Button>
            {selectedNode.status !== "PLANNED" ? (
              <Button size="sm" variant="outline" onClick={onGeneratePlan}>
                <Sparkles className="h-4 w-4" />
                Generate plan
              </Button>
            ) : (
              <Button size="sm" variant="outline" onClick={onGoDeeper}>
                Deepen
              </Button>
            )}
            {!isFocusNode ? (
              <Button size="sm" variant="outline" onClick={onFocusSelectedNode}>
                <Target className="h-4 w-4" />
                Focus here
              </Button>
            ) : null}
          </div>
        </div>
      </div>

      <ScrollArea className="soft-scrollbar min-h-0 flex-1">
        <div className="space-y-5 px-5 py-5">
          <section className="rounded-[22px] border border-white/8 bg-white/[0.03] p-4">
            <div className="grid grid-cols-3 gap-2 text-[12px] text-white/64">
              <div className="rounded-[16px] bg-black/20 px-3 py-3">
                <div className="text-white/34">Tasks</div>
                <div className="mt-1 text-white">
                  {selectedProgress
                    ? `${selectedProgress.completed_tasks}/${selectedProgress.total_tasks}`
                    : `${selectedNode.plan?.tasks.length ?? 0}`}
                </div>
              </div>
              <div className="rounded-[16px] bg-black/20 px-3 py-3">
                <div className="text-white/34">Children</div>
                <div className="mt-1 text-white">{selectedNode.children_ids.length}</div>
              </div>
              <div className="rounded-[16px] bg-black/20 px-3 py-3">
                <div className="text-white/34">Layer</div>
                <div className="mt-1 text-white">{selectedNode.layer}</div>
              </div>
            </div>
          </section>

          {agentCapability ? (
            <section className="rounded-[22px] border border-primary/20 bg-primary/[0.07] p-4">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <div className="text-[11px] uppercase tracking-[0.16em] text-white/30">
                    AI agent
                  </div>
                  <div className="mt-2 flex items-center gap-2 text-sm text-white">
                    <Bot className="h-4 w-4 text-primary" />
                    {agentCapability.agentName}
                  </div>
                </div>
                <Badge className="rounded-full border-primary/20 bg-primary/[0.15] px-2 py-0.5 text-[9px] uppercase tracking-[0.12em] text-white">
                  {agentCapability.confidence}
                </Badge>
              </div>
              <div className="mt-3 text-[13px] leading-6 text-white/66">
                {agentCapability.rationale}
              </div>
              <div className="mt-3 flex flex-wrap gap-2">
                {agentCapability.tools.map((tool) => (
                  <span
                    key={tool.id}
                    title={tool.capability}
                    className="rounded-full border border-white/8 bg-black/20 px-2.5 py-1 text-[11px] text-white/62"
                  >
                    {tool.label}
                  </span>
                ))}
              </div>
            </section>
          ) : null}

          {currentPath ? (
            <section className="rounded-[22px] border border-white/8 bg-white/[0.03] p-4">
              <div className="text-[11px] uppercase tracking-[0.16em] text-white/30">Path</div>
              <div className="mt-3 text-[13px] leading-6 text-white/72">{currentPath}</div>
              {pathChanged && suggestedPath ? (
                <div className="mt-2 text-[12px] leading-5 text-white/42">
                  AI baseline: {suggestedPath}
                </div>
              ) : null}
            </section>
          ) : null}

          {smart.length > 0 ? (
            <section className="rounded-[22px] border border-white/8 bg-white/[0.03] p-4">
              <div className="text-[11px] uppercase tracking-[0.16em] text-white/30">SMART</div>
              <div className="mt-3 space-y-3">
                {smart.map(([label, value]) => (
                  <div key={label}>
                    <div className="text-[10px] uppercase tracking-[0.14em] text-white/26">
                      {label}
                    </div>
                    <div className="mt-1 text-[13px] leading-6 text-white/72">{value}</div>
                  </div>
                ))}
              </div>
            </section>
          ) : null}

          {nextTask ? (
            <section className="rounded-[22px] border border-white/8 bg-white/[0.03] p-4">
              <div className="text-[11px] uppercase tracking-[0.16em] text-white/30">Next task</div>
              <div className="mt-3 text-sm text-white">{nextTask.title}</div>
              <div className="mt-1 text-[12px] leading-5 text-white/52">
                {formatTaskRollup(nextTask)}
              </div>
              {nextTask.description ? (
                <div className="mt-3 text-[13px] leading-6 text-white/66">{nextTask.description}</div>
              ) : null}
            </section>
          ) : null}
        </div>
      </ScrollArea>
    </div>
  );
}
