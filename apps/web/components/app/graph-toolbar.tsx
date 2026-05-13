"use client";

import { ArrowLeft, LayoutGrid, Maximize2, MoveDiagonal2, Plus } from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

interface GraphToolbarProps {
  canGoBack: boolean;
  canCreateNode: boolean;
  dragType: string;
  onCreateNode: () => void;
  onAutoLayout: () => void;
  onFitView: () => void;
  onBackLayer: () => void;
  className?: string;
}

export function GraphToolbar({
  canGoBack,
  canCreateNode,
  dragType,
  onCreateNode,
  onAutoLayout,
  onFitView,
  onBackLayer,
  className,
}: GraphToolbarProps) {
  return (
    <div
      className={cn(
        "pointer-events-none absolute left-4 top-4 z-10 flex flex-wrap items-center gap-2 rounded-[20px] border border-white/10 bg-[rgba(8,8,12,0.88)] p-2 shadow-[0_24px_80px_rgba(0,0,0,0.34)] backdrop-blur-md",
        className
      )}
    >
      <div className="pointer-events-auto flex items-center gap-2">
        <Button size="sm" variant="outline" onClick={onBackLayer} disabled={!canGoBack}>
          <ArrowLeft className="h-4 w-4" />
          Back
        </Button>
        <div
          className="flex items-center gap-2 rounded-xl border border-white/8 bg-white/[0.03] px-2 py-1.5"
          draggable={canCreateNode}
          onDragStart={(event) => {
            event.dataTransfer.setData(dragType, "node");
            event.dataTransfer.effectAllowed = "copy";
          }}
        >
          <Button size="sm" onClick={onCreateNode} disabled={!canCreateNode}>
            <Plus className="h-4 w-4" />
            New goal
          </Button>
          <div className="hidden items-center gap-1 text-[11px] text-white/38 sm:flex">
            <MoveDiagonal2 className="h-3.5 w-3.5" />
            Drag
          </div>
        </div>
        <Button size="sm" variant="outline" onClick={onAutoLayout}>
          <LayoutGrid className="h-4 w-4" />
          Auto layout
        </Button>
        <Button size="sm" variant="outline" onClick={onFitView}>
          <Maximize2 className="h-4 w-4" />
          Fit
        </Button>
      </div>
    </div>
  );
}
