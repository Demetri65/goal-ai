export type NodeStatus = "DRAFT" | "BASELINED" | "PLANNED";
export type CheckState = "unchecked" | "partial" | "checked";

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
}

export interface Graph {
  root_id: string;
  nodes: Record<string, Node>;
  created_at: string;
  updated_at: string;
  focus_parent_id: string;
  active_layer: number;
}

export interface NodeProgress {
  total_tasks: number;
  completed_tasks: number;
  check_state: CheckState;
}

export interface GraphResponse {
  graph: Graph;
  node_progress: Record<string, NodeProgress>;
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
}

export interface BaselineQuestion {
  id: string;
  question: string;
  category: string;
}

export interface UISession {
  session_id: string;
  updated_at: string;
  messages: ChatMessage[];
  metadata: Record<string, unknown>;
}

export interface ChatMessage {
  role: "user" | "assistant" | "system";
  content: string;
  created_at: string;
}
