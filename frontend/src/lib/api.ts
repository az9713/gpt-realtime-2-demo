export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    headers: { 'content-type': 'application/json', ...(init?.headers ?? {}) },
    ...init,
  });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}: ${await res.text()}`);
  return (await res.json()) as T;
}

export interface ConversationRow {
  id: string;
  vertical: string;
  surface: string;
  mode: string;
  language: string | null;
  agent_persona: string | null;
  started_at: string;
  ended_at: string | null;
  cost_usd: string;
}

export interface TurnRow {
  id: string;
  role: string;
  transcript: string | null;
  latency_ms: number | null;
  ts: string;
}

export interface TraceEvent {
  id: string;
  ts: string;
  kind: string;
  payload: Record<string, unknown>;
  cost_usd: string;
}

export interface PendingApproval {
  approval_id: string;
  conversation_id: string;
  tool_call_id: string;
  tool_name: string | null;
  args: Record<string, unknown> | null;
  blast_radius: string | null;
  requested_at: string;
  timeout_seconds: number;
}
