import type { Graph, Node, NodeStatus } from "@/lib/types";

export function displayNodeTitle(
  node: Pick<Node, "title"> | null | undefined,
  fallback = "Untitled goal"
) {
  return node?.title.trim() ? node.title.trim() : fallback;
}

export function displayGoalStatus(status: NodeStatus) {
  if (status === "PLANNED") {
    return "Ready";
  }
  if (status === "BASELINED") {
    return "Baselined";
  }
  return "Needs clarity";
}

export function buildPathIds(graph: Graph, parentId: string, nodeId?: string) {
  const pathIds: string[] = [];
  const visited = new Set<string>();
  let currentId: string | null | undefined = parentId;

  while (currentId && !visited.has(currentId)) {
    visited.add(currentId);
    const currentNode: Node | undefined = graph.nodes[currentId];
    if (!currentNode) {
      break;
    }
    pathIds.push(currentNode.id);
    currentId = currentNode.parent_id;
  }

  const ordered = pathIds.reverse();
  if (nodeId && ordered[ordered.length - 1] !== nodeId) {
    ordered.push(nodeId);
  }
  return ordered;
}

export function resolveSuggestedPathIds(graph: Graph, node: Node) {
  if (node.suggested_path_ids.length > 0) {
    return node.suggested_path_ids;
  }

  const fallbackParentId = node.suggested_parent_id ?? node.parent_id ?? graph.root_id;
  return buildPathIds(graph, fallbackParentId, node.id);
}

export function formatPathText(graph: Graph, pathIds: string[], leafTitle?: string) {
  return pathIds
    .map((pathId, index) => {
      const isLeaf = index === pathIds.length - 1;
      if (isLeaf && leafTitle !== undefined) {
        return leafTitle.trim() || "Untitled goal";
      }
      return displayNodeTitle(graph.nodes[pathId]);
    })
    .join(" / ");
}
