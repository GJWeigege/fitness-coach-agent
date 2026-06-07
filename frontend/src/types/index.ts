export type UserProfile = {
  id: string;
  username: string;
  role: string;
  permissions: string[];
  is_active: boolean;
  created_at: string;
};

export type KnowledgeDocument = {
  id: string;
  title: string;
  status: string;
  created_at: string;
  updated_at: string;
  chunk_count: number;
};

export type SessionSummary = {
  id: string;
  user_id: string | null;
  title: string | null;
  created_at: string;
  updated_at: string;
};

export type Citation = {
  chunk_id: string;
  document_id: string;
  chunk_index: number;
  content: string;
  score: number;
};

export type AgentStepEvent = {
  phase: string;
  summary: string;
  step_index?: number;
  detail?: Record<string, unknown>;
};

export type MessageItem = {
  id: string;
  role: "user" | "assistant" | "system" | string;
  content: string;
  created_at: string;
  citations?: Citation[];
  agent_run_id?: string;
  feedback?: "up" | "down" | null;
  steps?: AgentStepEvent[];
  run_status?: string | null;
  step_count?: number | null;
  latency_ms?: number | null;
  intent?: string | null;
};

export type LocalMessage = MessageItem & {
  citations?: Citation[];
  steps?: AgentStepEvent[];
  runId?: string;
  traceId?: string;
  runStatus?: string;
  intent?: string;
  agent_trace_summary?: string;
};

export type StreamEvent = {
  type: string;
  content?: string;
  session_id?: string;
  citations?: Citation[];
  message?: string;
  run_id?: string;
  trace_id?: string;
  phase?: string;
  summary?: string;
  step_index?: number;
  detail?: Record<string, unknown>;
  tool?: string;
  arguments?: Record<string, unknown>;
  output_preview?: string;
  status?: string;
  step_count?: number;
  latency_ms?: number;
  model_name?: string;
  assistant_message_id?: string;
};

export type AgentRunListItem = {
  id: string;
  trace_id: string;
  session_id: string;
  intent: string | null;
  status: string;
  step_count: number;
  total_latency_ms: number | null;
  model_name: string | null;
  memory_summary_updated: boolean;
  created_at: string;
  finished_at: string | null;
};

export type AgentRunDetail = AgentRunListItem & {
  error_message: string | null;
  prompt_tokens: number | null;
  completion_tokens: number | null;
  memory_compacted: boolean;
  dropped_message_count: number;
  timeline: {
    id: string;
    step_index: number;
    phase: string;
    summary: string | null;
    payload: Record<string, unknown> | null;
    duration_ms: number | null;
    status: string;
    created_at: string;
  }[];
};
