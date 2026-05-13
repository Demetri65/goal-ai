export type NodeStatus = "DRAFT" | "BASELINED" | "PLANNED";
export type CheckState = "unchecked" | "partial" | "checked";
export type WorkflowStage = "welcome" | "drafting" | "building" | "selecting" | "planning";
export type VisibleStageId = "define" | "clarify" | "build" | "refine";
export type LayoutMode = "auto" | "manual";

export interface SMARTFields {
  specific: string;
  measurable: string;
  achievable: string;
  relevant: string;
  time_bound: string;
}

export interface BaselineQA {
  id: string;
  question: string;
  answer: string;
  category: string;
}

export interface NodeBaseline {
  qa: BaselineQA[];
  baseline_notes: string[];
  assumptions: string[];
  constraints: string[];
  unknowns: string[];
}

export interface Task {
  title: string;
  description: string;
  success_criteria: string;
  depends_on: string[];
  estimate_hours: number | null;
  relative_timing: string | null;
  due: string | null;
  completed: boolean;
}

export interface NodePlan {
  tasks: Task[];
}

export interface NodePosition {
  x: number;
  y: number;
}

export interface NodeUI {
  layout_mode: LayoutMode;
  position: NodePosition | null;
}

export interface Node {
  id: string;
  title: string;
  workstream: string;
  layer: number;
  parent_id: string | null;
  children_ids: string[];
  smart: SMARTFields;
  baseline: NodeBaseline | null;
  plan: NodePlan | null;
  status: NodeStatus;
  ui: NodeUI;
  suggested_parent_id: string | null;
  suggested_path_ids: string[];
}

export interface SuggestedConnection {
  source_id: string;
  target_id: string;
  label: string;
  rationale: string;
}

export interface Graph {
  root_id: string;
  nodes: Record<string, Node>;
  created_at: string;
  updated_at: string;
  focus_parent_id: string;
  active_layer: number;
  suggested_connections: SuggestedConnection[];
}

export interface NodeProgress {
  total_tasks: number;
  completed_tasks: number;
  check_state: CheckState;
}

export interface GraphResponse {
  graph: Graph;
  node_progress: Record<string, NodeProgress>;
  workflow: WorkflowState;
}

export interface WorkflowState {
  stage: Exclude<WorkflowStage, "welcome" | "building">;
  allowed_actions: string[];
  focus_parent_id: string;
  selected_node_id: string | null;
  total_children: number;
  planned_children: number;
}

export interface JobAccepted {
  job_id: string;
  status: "queued" | "running" | "succeeded" | "failed";
}

export interface JobRecord {
  id: string;
  kind: string;
  status: "queued" | "running" | "succeeded" | "failed";
  started_at: string | null;
  finished_at: string | null;
  error: string | null;
  graph_updated_at: string | null;
}

export interface JobEvent {
  job_id: string;
  type: string;
  status: "queued" | "running" | "succeeded" | "failed";
  message: string;
  timestamp: string;
  sequence?: number;
  changed_node_ids?: string[];
  graph_snapshot?: GraphResponse;
}

export interface BaselineQuestion {
  id: string;
  question: string;
  category: string;
  guide: string;
  research_basis: string;
}

export interface UISession {
  session_id: string;
  updated_at: string;
  messages: ChatMessage[];
  metadata: Record<string, unknown>;
}

export interface UISessionMetadata {
  selectedNodeId?: string;
  workflowStage?: WorkflowStage;
  graphPath?: string;
  chatInput?: string;
  draftingParentId?: string | null;
  draftingQuestionIndex?: number;
  draftingAnswers?: Record<string, string>;
  sidebarOpen?: boolean;
  activeTaskIndex?: number | null;
}

export type GraphMutationAction =
  | {
      action: "create_node";
      parent_id: string;
      title: string;
      workstream?: string;
      smart: SMARTFields;
      status?: NodeStatus;
      position?: NodePosition | null;
      layout_mode?: LayoutMode;
      baseline?: NodeBaseline | null;
    }
  | {
      action: "update_node";
      node_id: string;
      title?: string;
      workstream?: string;
      smart?: SMARTFields;
      baseline?: NodeBaseline | null;
      baseline_notes?: string[];
      assumptions?: string[];
      constraints?: string[];
      unknowns?: string[];
      status?: NodeStatus;
    }
  | {
      action: "move_node";
      node_id: string;
      parent_id: string;
    }
  | {
      action: "delete_node";
      node_id: string;
    }
  | {
      action: "set_position";
      node_id: string;
      position?: NodePosition | null;
      layout_mode?: LayoutMode;
    }
  | {
      action: "upsert_suggested_connection";
      source_id: string;
      target_id: string;
      label?: string;
      rationale?: string;
    }
  | {
      action: "delete_suggested_connection";
      source_id: string;
      target_id: string;
    };

export interface VisibleStage {
  id: VisibleStageId;
  title: string;
  description: string;
  primaryActionLabel: string;
  helpText?: string;
}

export interface ChatMessage {
  role: "user" | "assistant" | "system";
  content: string;
  created_at: string;
}
