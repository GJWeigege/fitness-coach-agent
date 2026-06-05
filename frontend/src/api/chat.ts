import { API_BASE, apiFetch, buildHeaders, parseError } from "./client";
import type { MessageItem, SessionSummary, StreamEvent } from "../types";

export async function fetchSessions(token: string, userId?: string): Promise<SessionSummary[]> {
  const url = new URL(`${API_BASE}/chat/sessions`);
  if (userId) url.searchParams.set("user_id", userId);
  const data = await apiFetch<{ sessions?: SessionSummary[] }>(url.toString(), {
    headers: buildHeaders(token),
  });
  return data.sessions || [];
}

export async function fetchSessionMessages(
  token: string,
  sessionId: string
): Promise<{ messages: MessageItem[]; session_id: string }> {
  const data = await apiFetch<{ messages?: MessageItem[]; session_id?: string }>(
    `${API_BASE}/chat/sessions/${sessionId}/messages`,
    { headers: buildHeaders(token) }
  );
  return {
    messages: data.messages || [],
    session_id: data.session_id || sessionId,
  };
}

export async function renameSession(token: string, sessionId: string, title: string): Promise<SessionSummary> {
  return apiFetch(`${API_BASE}/chat/sessions/${sessionId}`, {
    method: "PATCH",
    headers: buildHeaders(token, { "Content-Type": "application/json" }),
    body: JSON.stringify({ title }),
  });
}

export async function deleteSession(token: string, sessionId: string): Promise<void> {
  const response = await fetch(`${API_BASE}/chat/sessions/${sessionId}`, {
    method: "DELETE",
    headers: buildHeaders(token),
  });
  if (!response.ok) {
    throw new Error(await parseError(response, "删除会话失败"));
  }
}

export async function submitFeedback(token: string, messageId: string, rating: "up" | "down"): Promise<void> {
  await apiFetch(`${API_BASE}/chat/messages/${messageId}/feedback`, {
    method: "POST",
    headers: buildHeaders(token, { "Content-Type": "application/json" }),
    body: JSON.stringify({ rating }),
  });
}

export async function streamMessage(
  token: string,
  payload: { session_id?: string; message: string; use_rag: boolean },
  onEvent: (event: StreamEvent) => void
): Promise<void> {
  const response = await fetch(`${API_BASE}/chat/stream`, {
    method: "POST",
    headers: buildHeaders(token, { "Content-Type": "application/json" }),
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    throw new Error(await parseError(response, "发送消息失败"));
  }
  if (!response.body) {
    throw new Error("服务端未返回流式数据");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const chunks = buffer.split("\n\n");
    buffer = chunks.pop() || "";
    for (const block of chunks) {
      const line = block.split("\n").find((item) => item.startsWith("data: "));
      if (!line) continue;
      try {
        onEvent(JSON.parse(line.slice(6)));
      } catch {
        // ignore malformed event
      }
    }
  }
}
