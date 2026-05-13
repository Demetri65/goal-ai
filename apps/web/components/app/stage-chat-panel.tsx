"use client";

import type { ReactNode } from "react";

import type { VisibleStage, VisibleStageId } from "@/lib/types";

interface StageChatPanelProps {
  stages: VisibleStage[];
  activeStageId: VisibleStageId;
  statusCard?: ReactNode;
  composer: ReactNode;
}

export function StageChatPanel({
  statusCard,
  composer,
}: StageChatPanelProps) {
  return (
    <div className="panel-border flex h-[214px] min-h-[184px] flex-col overflow-hidden rounded-[22px] border border-white/6 bg-card/72">
      <div className="min-h-0 flex-1 px-4 py-3.5">
        {statusCard}
      </div>

      <div className="border-t border-white/6 px-4 py-3">{composer}</div>
    </div>
  );
}
