import {
  GraphResponse,
  JobAccepted,
  JobEvent,
  JobRecord,
  UISession,
} from "@/lib/types";

const API_BASE = process.env.NEXT_PUBLIC_SMARTGOT_API ?? "http://127.0.0.1:8001";

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const hasBody = init?.body !== undefined && init?.body !== null;
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      ...(hasBody ? { "Content-Type": "application/json" } : {}),
      ...(init?.headers ?? {}),
    },
    cache: "no-store",
  });
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as { detail?: string } | null;
    throw new Error(payload?.detail ?? `API error ${response.status}`);
  }
  return (await response.json()) as T;
}

export function getApiBase() {
  return API_BASE;
}

export function fetchGraph(path: string) {
  return apiFetch<GraphResponse>(`/api/v1/graph?path=${encodeURIComponent(path)}`);
}

export function initGraph(path: string, goal: string, overwrite = false) {
  return apiFetch<GraphResponse>("/api/v1/graph/init", {
    method: "POST",
    body: JSON.stringify({
      path,
      goal,
      overwrite,
    }),
  });
}

export function fetchStatus(path: string) {
  return apiFetch<{ updated_at: string; focus_parent_id: string; active_layer: number }>(
    `/api/v1/status?path=${encodeURIComponent(path)}`
  );
}

export function fetchNode(nodeId: string, path: string) {
  return apiFetch(`/api/v1/nodes/${encodeURIComponent(nodeId)}?path=${encodeURIComponent(path)}`);
}

export function fetchBaselineQuestions(nodeId: string, path: string) {
  return apiFetch<{ questions: Array<{ id: string; question: string; category: string }> }>(
    `/api/v1/baseline/questions?node_id=${encodeURIComponent(nodeId)}&path=${encodeURIComponent(path)}`
  );
}

export function postJob(endpoint: string, body: unknown) {
  return apiFetch<JobAccepted>(`/api/v1/jobs/${endpoint}`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function getJob(jobId: string) {
  return apiFetch<JobRecord>(`/api/v1/jobs/${encodeURIComponent(jobId)}`);
}

export async function updateFocus(body: unknown) {
  return apiFetch<{ focus_parent_id: string; active_layer: number; updated_at: string }>(
    "/api/v1/focus",
    {
      method: "POST",
      body: JSON.stringify(body),
    }
  );
}

export function streamJobEvents(jobId: string, onEvent: (event: JobEvent) => void) {
  const source = new EventSource(
    `${API_BASE}/api/v1/jobs/${encodeURIComponent(jobId)}/events`
  );

  source.onmessage = (message) => {
    if (!message.data) {
      return;
    }
    const payload = JSON.parse(message.data) as JobEvent;
    onEvent(payload);
  };

  return source;
}

export function fetchSession(sessionId: string) {
  return apiFetch<UISession>(`/api/v1/ui-session/${encodeURIComponent(sessionId)}`);
}

export function saveSession(sessionId: string, messages: unknown[], metadata: Record<string, unknown>) {
  return apiFetch<UISession>(`/api/v1/ui-session/${encodeURIComponent(sessionId)}`, {
    method: "PUT",
    body: JSON.stringify({ messages, metadata }),
  });
}
