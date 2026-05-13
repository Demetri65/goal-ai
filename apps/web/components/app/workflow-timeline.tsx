"use client";

import { Loader2 } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import type { WorkflowTimelineStep } from "@/lib/workflow";

interface WorkflowTimelineProps {
  steps: WorkflowTimelineStep[];
  className?: string;
}

function stateStyles(state: WorkflowTimelineStep["state"]) {
  if (state === "loading") {
    return {
      rail: "border-primary/30 bg-primary/[0.08]",
      dot: "bg-primary text-primary-foreground",
      copy: "text-white",
    };
  }

  if (state === "current") {
    return {
      rail: "border-white/12 bg-white/[0.04]",
      dot: "bg-white text-black",
      copy: "text-white",
    };
  }

  if (state === "complete") {
    return {
      rail: "border-emerald-300/16 bg-emerald-400/[0.08]",
      dot: "bg-emerald-300 text-black",
      copy: "text-white/82",
    };
  }

  return {
    rail: "border-white/6 bg-transparent",
    dot: "bg-white/12 text-white/42",
    copy: "text-white/50",
  };
}

export function WorkflowTimeline({ steps, className }: WorkflowTimelineProps) {
  return (
    <div className={cn("space-y-2.5", className)}>
      {steps.map((step, index) => {
        const styles = stateStyles(step.state);

        return (
          <div
            key={step.id}
            className={cn(
              "rounded-[18px] border px-3.5 py-3 transition",
              styles.rail
            )}
          >
            <div className="flex items-start gap-3">
              <div className="flex flex-col items-center pt-0.5">
                <div
                  className={cn(
                    "flex h-6 w-6 items-center justify-center rounded-full text-[11px] font-medium",
                    styles.dot
                  )}
                >
                  {step.state === "loading" ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    String(index + 1).padStart(2, "0")
                  )}
                </div>
                {index < steps.length - 1 ? (
                  <div className="mt-1 h-8 w-px bg-white/8" />
                ) : null}
              </div>

              <div className="min-w-0 flex-1">
                <div className="flex items-start justify-between gap-3">
                  <div className={cn("text-sm font-medium", styles.copy)}>{step.title}</div>
                  <Badge
                    variant="outline"
                    className="rounded-full border-white/8 bg-white/[0.03] px-2 py-0.5 text-[9px] uppercase tracking-[0.14em] text-white/58"
                  >
                    {step.actor}
                  </Badge>
                </div>
                <div className="mt-1 text-[12px] leading-5 text-white/48">{step.description}</div>
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}
