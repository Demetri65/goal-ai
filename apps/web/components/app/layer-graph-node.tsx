"use client";

import type { NodeProps } from "reactflow";

import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import type { NodeStatus } from "@/lib/types";

export interface LayerGraphNodeData {
  title: string;
  subtitle: string;
  status: NodeStatus;
}

function statusClass(status: NodeStatus) {
  if (status === "PLANNED") {
    return "bg-emerald-500/10 border-emerald-400/40 text-emerald-200";
  }
  if (status === "BASELINED") {
    return "bg-amber-500/10 border-amber-400/40 text-amber-100";
  }
  return "bg-zinc-700/30 border-zinc-500/50 text-zinc-200";
}

function statusVariant(status: NodeStatus): "default" | "secondary" | "outline" {
  if (status === "PLANNED") {
    return "default";
  }
  if (status === "BASELINED") {
    return "secondary";
  }
  return "outline";
}

export function LayerGraphNode({ data, selected }: NodeProps<LayerGraphNodeData>) {
  return (
    <div
      className={cn(
        "w-[260px] rounded-lg border border-border/70 bg-card px-4 py-3 shadow-sm transition",
        statusClass(data.status),
        selected && "ring-2 ring-primary"
      )}
    >
      <div className="mb-2 flex items-start justify-between gap-3">
        <div className="space-y-1">
          <div className="text-sm font-semibold leading-tight text-foreground">{data.title}</div>
        </div>
        <Badge variant={statusVariant(data.status)}>{data.status}</Badge>
      </div>
      <div className="text-xs text-muted-foreground">{data.subtitle}</div>
    </div>
  );
}
