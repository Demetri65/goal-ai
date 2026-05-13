"use client";

import { Bot, Loader2, Maximize2 } from "lucide-react";
import { Handle, Position, type NodeProps } from "reactflow";

import { Checkbox } from "@/components/ui/checkbox";
import type { AgentCapabilityMatch } from "@/lib/agent-capabilities";
import { cn } from "@/lib/utils";
import type { NodeStatus } from "@/lib/types";

interface LayerGraphTaskData {
  index: number;
  blurb: string;
  completed: boolean;
}

export interface LayerGraphNodeData {
  title: string;
  status: NodeStatus;
  kind: "focus" | "goal";
  tasks?: LayerGraphTaskData[];
  taskCount?: number;
  completedTaskCount?: number;
  width?: number;
  height?: number;
  busy?: boolean;
  agentAssist?: AgentCapabilityMatch;
  onAgentAssist?: () => void;
  onInspect?: () => void;
  onToggleTask?: (taskIndex: number, completed: boolean) => void;
}

function statusClass(status: NodeStatus, kind: LayerGraphNodeData["kind"]) {
  if (kind === "focus") {
    return "border-white/8 bg-[rgba(18,18,22,0.96)] text-white";
  }
  if (status === "PLANNED") {
    return "border-violet-300/25 bg-[rgba(103,93,214,0.24)] text-white";
  }
  if (status === "BASELINED") {
    return "border-white/8 bg-[rgba(31,32,40,0.9)] text-white/88";
  }
  return "border-white/6 bg-[rgba(20,20,25,0.88)] text-zinc-200";
}

export function LayerGraphNode({ data, selected }: NodeProps<LayerGraphNodeData>) {
  return (
    <div
      style={{
        width: data.width ?? 560,
        minHeight: data.height ?? 230,
      }}
      className={cn(
        "relative overflow-hidden rounded-[20px] border px-7 py-6",
        statusClass(data.status, data.kind),
        selected && "outline outline-2 outline-offset-2 outline-primary/80"
      )}
    >
      <Handle
        type="target"
        position={Position.Left}
        isConnectable={data.kind === "goal"}
        className="!h-3 !w-3 !border-2 !border-white/24 !bg-[rgba(8,8,12,0.96)]"
      />
      <Handle
        type="source"
        position={Position.Right}
        isConnectable={data.kind === "goal"}
        className="!h-3 !w-3 !border-2 !border-primary/50 !bg-primary"
      />
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0 flex-1">
          <div className="line-clamp-4 break-words text-[30px] font-semibold leading-[1.12] text-white">
            {data.title}
          </div>
        </div>
        <div className="flex items-center gap-1.5">
          {data.agentAssist && data.onAgentAssist ? (
            <button
              type="button"
              className="nodrag nopan flex h-7 w-7 items-center justify-center rounded-full border border-primary/35 bg-primary/[0.14] text-primary-foreground shadow-[0_0_18px_rgba(132,116,255,0.18)] transition hover:border-primary/70 hover:bg-primary/[0.24] hover:text-white"
              aria-label={`Open ${data.agentAssist.agentName} for ${data.title}`}
              title={`${data.agentAssist.agentName}: ${data.agentAssist.rationale}`}
              onClick={(event) => {
                event.stopPropagation();
                data.onAgentAssist?.();
              }}
              onPointerDown={(event) => event.stopPropagation()}
            >
              <Bot className="h-3.5 w-3.5" />
            </button>
          ) : null}
          {data.onInspect ? (
            <button
              type="button"
              className="nodrag nopan flex h-7 w-7 items-center justify-center rounded-full border border-white/8 bg-white/[0.04] text-white/58 transition hover:border-white/18 hover:bg-white/[0.08] hover:text-white"
              aria-label={`Open inspector for ${data.title}`}
              onClick={(event) => {
                event.stopPropagation();
                data.onInspect?.();
              }}
              onPointerDown={(event) => event.stopPropagation()}
            >
              <Maximize2 className="h-3.5 w-3.5" />
            </button>
          ) : null}
          {data.busy ? <Loader2 className="h-3.5 w-3.5 animate-spin text-primary" /> : null}
        </div>
      </div>
      {data.busy ? (
        <div className="mt-5 flex items-center gap-2 border-t border-white/8 pt-4 text-[16px] text-primary">
          <Loader2 className="h-4 w-4 animate-spin" />
          Generating tasks
        </div>
      ) : data.taskCount ? (
        <div className="mt-5 border-t border-white/8 pt-4">
          <div className="text-[12px] uppercase tracking-[0.14em] text-white/34">
            {data.completedTaskCount ?? 0}/{data.taskCount} tasks
          </div>
          <div className="mt-3 space-y-3">
            {(data.tasks ?? []).map((task) => (
              <div
                key={`${task.index}-${task.blurb}`}
                className="nodrag nopan flex min-w-0 items-start gap-3"
                onClick={(event) => event.stopPropagation()}
                onPointerDown={(event) => event.stopPropagation()}
              >
                <Checkbox
                  checked={task.completed}
                  aria-label={`Mark task ${task.index + 1} ${task.completed ? "incomplete" : "complete"}`}
                  className="mt-1.5 h-6 w-6 rounded-md border-white/22 bg-black/20 data-[state=checked]:border-primary data-[state=checked]:bg-primary [&_svg]:h-5 [&_svg]:w-5"
                  onCheckedChange={(checked) => {
                    data.onToggleTask?.(task.index, checked === true);
                  }}
                />
                <div
                  className={cn(
                    "min-w-0 flex-1 whitespace-normal break-words text-[22px] leading-8 text-white/76",
                    task.completed && "text-white/36 line-through decoration-white/30"
                  )}
                >
                  {task.blurb}
                </div>
              </div>
            ))}
          </div>
        </div>
      ) : null}
    </div>
  );
}
