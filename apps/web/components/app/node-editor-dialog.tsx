"use client";

import { useEffect, useMemo, useState } from "react";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  buildPathIds,
  displayNodeTitle,
  formatPathText,
  resolveSuggestedPathIds,
} from "@/lib/graph-paths";
import type { Graph, Node, SMARTFields } from "@/lib/types";

export type NodeEditorDialogMode =
  | {
      kind: "edit";
      nodeId: string;
    }
  | null;

export interface NodeEditorSubmitPayload {
  nodeId: string;
  parentId: string;
  title: string;
  workstream: string;
  smart: SMARTFields;
}

interface NodeEditorDialogProps {
  open: boolean;
  graph: Graph | null;
  mode: NodeEditorDialogMode;
  pending?: boolean;
  onOpenChange: (open: boolean) => void;
  onSubmit: (payload: NodeEditorSubmitPayload) => void | Promise<void>;
  onDelete: (nodeId: string) => void | Promise<void>;
}

function emptySmartFields(): SMARTFields {
  return {
    specific: "",
    measurable: "",
    achievable: "",
    relevant: "",
    time_bound: "",
  };
}

function collectDescendantIds(graph: Graph, nodeId: string): Set<string> {
  const descendants = new Set<string>();
  const visit = (currentId: string) => {
    const current = graph.nodes[currentId];
    if (!current) {
      return;
    }
    for (const childId of current.children_ids) {
      descendants.add(childId);
      visit(childId);
    }
  };
  visit(nodeId);
  return descendants;
}

export function NodeEditorDialog({
  open,
  graph,
  mode,
  pending,
  onOpenChange,
  onSubmit,
  onDelete,
}: NodeEditorDialogProps) {
  const currentNode = useMemo(() => {
    if (!graph || !mode || mode.kind !== "edit") {
      return null;
    }
    return graph.nodes[mode.nodeId] ?? null;
  }, [graph, mode]);

  const [title, setTitle] = useState("");
  const [workstream, setWorkstream] = useState("");
  const [parentId, setParentId] = useState("root");
  const [smart, setSmart] = useState<SMARTFields>(emptySmartFields);
  const [deleteConfirm, setDeleteConfirm] = useState(false);

  useEffect(() => {
    if (!mode) {
      setDeleteConfirm(false);
      return;
    }

    if (mode.kind === "edit" && currentNode) {
      setTitle(currentNode.title);
      setWorkstream(currentNode.workstream);
      setParentId(currentNode.parent_id ?? graph?.root_id ?? "root");
      setSmart(currentNode.smart);
      setDeleteConfirm(false);
    }
  }, [currentNode, graph?.root_id, mode]);

  const candidateParents = useMemo(() => {
    if (!graph || !currentNode) {
      return [] as Node[];
    }
    const disallowed = collectDescendantIds(graph, currentNode.id);
    disallowed.add(currentNode.id);
    return Object.values(graph.nodes).filter((node) => !disallowed.has(node.id));
  }, [currentNode, graph]);

  const suggestedParentId = currentNode?.suggested_parent_id ?? null;
  const suggestedParentAvailable = Boolean(
    suggestedParentId && graph?.nodes[suggestedParentId]
  );
  const currentPath = useMemo(() => {
    if (!graph || !currentNode) {
      return "";
    }
    return formatPathText(graph, buildPathIds(graph, parentId, currentNode.id), title);
  }, [currentNode, graph, parentId, title]);

  const suggestedPath = useMemo(() => {
    if (!graph || !currentNode) {
      return "";
    }
    return formatPathText(graph, resolveSuggestedPathIds(graph, currentNode), title);
  }, [currentNode, graph, title]);

  const pathChanged =
    Boolean(currentNode) &&
    parentId !== (suggestedParentId ?? currentNode?.parent_id ?? graph?.root_id ?? "root");

  if (!mode) {
    return null;
  }

  const saveLabel =
    currentNode?.status === "DRAFT"
      ? "Convert goal"
      : "Save";

  const description = pathChanged
    ? "This goal is currently using a custom path."
    : "Adjust the goal details and path.";

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Edit goal</DialogTitle>
          <DialogDescription>{description}</DialogDescription>
        </DialogHeader>

        <div className="grid gap-4 px-6 py-6">
          <div className="grid gap-2">
            <label className="text-[11px] uppercase tracking-[0.16em] text-white/36" htmlFor="node-title">
              Title
            </label>
            <Input
              id="node-title"
              value={title}
              onChange={(event) => setTitle(event.target.value)}
              placeholder="Name the goal"
            />
          </div>

          <div className="grid gap-2 md:grid-cols-[minmax(0,1fr)_220px]">
            <div className="grid gap-2">
              <label className="text-[11px] uppercase tracking-[0.16em] text-white/36" htmlFor="node-workstream">
                Workstream
              </label>
              <Input
                id="node-workstream"
                value={workstream}
                onChange={(event) => setWorkstream(event.target.value)}
                placeholder="Short label"
              />
            </div>
            {currentNode?.id !== graph?.root_id ? (
              <div className="grid gap-2">
                <label className="text-[11px] uppercase tracking-[0.16em] text-white/36" htmlFor="node-parent">
                  Parent
                </label>
                <select
                  id="node-parent"
                  className="flex h-10 w-full rounded-xl border border-input bg-white/[0.02] px-4 py-2 text-sm text-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                  value={parentId}
                  onChange={(event) => setParentId(event.target.value)}
                >
                  {candidateParents.map((node) => (
                    <option key={node.id} value={node.id}>
                      {displayNodeTitle(node)}
                    </option>
                  ))}
                </select>
              </div>
            ) : null}
          </div>

          <div className="rounded-[20px] border border-white/8 bg-white/[0.025] px-4 py-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="text-[11px] uppercase tracking-[0.16em] text-white/34">Path</div>
              {pathChanged && suggestedParentAvailable ? (
                <Button
                  size="sm"
                  variant="outline"
                  disabled={pending}
                  onClick={() => setParentId(suggestedParentId ?? graph?.root_id ?? "root")}
                >
                  Use suggested
                </Button>
              ) : null}
            </div>
            <div className="mt-3 grid gap-3 md:grid-cols-2">
              <div>
                <div className="text-[10px] uppercase tracking-[0.14em] text-white/24">Current</div>
                <div className="mt-1 text-[13px] leading-6 text-white/72">{currentPath}</div>
              </div>
              <div>
                <div className="text-[10px] uppercase tracking-[0.14em] text-white/24">AI baseline</div>
                <div className="mt-1 text-[13px] leading-6 text-white/56">{suggestedPath}</div>
              </div>
            </div>
          </div>

          <div className="grid gap-3 md:grid-cols-2">
            {(
              [
                ["specific", "Specific"],
                ["measurable", "Measurable"],
                ["achievable", "Achievable"],
                ["relevant", "Relevant"],
              ] as const
            ).map(([field, label]) => (
              <div key={field} className="grid gap-2">
                <label
                  className="text-[11px] uppercase tracking-[0.16em] text-white/36"
                  htmlFor={`smart-${field}`}
                >
                  {label}
                </label>
                <Textarea
                  id={`smart-${field}`}
                  rows={3}
                  value={smart[field]}
                  onChange={(event) =>
                    setSmart((previous) => ({
                      ...previous,
                      [field]: event.target.value,
                    }))
                  }
                />
              </div>
            ))}
          </div>

          <div className="grid gap-2">
            <label className="text-[11px] uppercase tracking-[0.16em] text-white/36" htmlFor="smart-time-bound">
              Time bound
            </label>
            <Textarea
              id="smart-time-bound"
              rows={3}
              value={smart.time_bound}
              onChange={(event) =>
                setSmart((previous) => ({
                  ...previous,
                  time_bound: event.target.value,
                }))
              }
            />
          </div>
        </div>

        <DialogFooter>
          <div className="flex items-center gap-2">
            {currentNode && currentNode.id !== graph?.root_id ? (
              deleteConfirm ? (
                <>
                  <div className="text-sm text-white/54">
                    Delete this goal and its descendants?
                  </div>
                  <Button
                    variant="destructive"
                    size="sm"
                    disabled={pending}
                    onClick={() => void onDelete(currentNode.id)}
                  >
                    Confirm delete
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={pending}
                    onClick={() => setDeleteConfirm(false)}
                  >
                    Cancel
                  </Button>
                </>
              ) : (
                <Button
                  variant="outline"
                  size="sm"
                  disabled={pending}
                  onClick={() => setDeleteConfirm(true)}
                >
                  Delete goal
                </Button>
              )
            ) : null}
          </div>

          <div className="flex items-center gap-2">
            <Button variant="outline" onClick={() => onOpenChange(false)} disabled={pending}>
              Cancel
            </Button>
            <Button
              disabled={pending || !title.trim() || !workstream.trim()}
              onClick={() =>
                void onSubmit({
                  nodeId: currentNode?.id ?? "",
                  parentId,
                  title: title.trim(),
                  workstream: workstream.trim(),
                  smart,
                })
              }
            >
              {saveLabel}
            </Button>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
