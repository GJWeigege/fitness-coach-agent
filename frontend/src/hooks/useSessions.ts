import { useCallback, useEffect, useRef, useState } from "react";
import {
  deleteSession,
  fetchSessionMessages,
  fetchSessions,
  renameSession,
  streamMessage,
  submitFeedback,
} from "../api";
import { useAuth } from "../contexts/AuthContext";
import { useApp } from "../contexts/AppContext";
import type { AgentStepEvent, LocalMessage, SessionSummary, StreamEvent } from "../types";

function appendStep(steps: AgentStepEvent[], evt: StreamEvent): AgentStepEvent[] {
  if (evt.type !== "step" || !evt.phase || !evt.summary) return steps;
  return [
    ...steps,
    {
      phase: evt.phase,
      summary: evt.summary,
      step_index: evt.step_index,
      detail: evt.detail,
    },
  ];
}

function hydrateMessages(loaded: Awaited<ReturnType<typeof fetchSessionMessages>>["messages"]): LocalMessage[] {
  return loaded.map((m) => {
    const steps = m.steps || [];
    const routingStep = steps.find((step) => step.phase === "routing");
    const routingIntent = routingStep?.detail?.intent;
    return {
      ...m,
      citations: m.citations,
      steps,
      runId: m.agent_run_id,
      runStatus: m.run_status ?? undefined,
      intent: m.intent ?? (routingIntent ? String(routingIntent) : undefined),
      agent_trace_summary:
        m.step_count != null ? `agent · ${m.step_count} 步 · ${m.latency_ms || 0}ms` : undefined,
    };
  });
}

function updateAssistant(
  prev: LocalMessage[],
  assistantId: string,
  updater: (msg: LocalMessage) => LocalMessage
): LocalMessage[] {
  return prev.map((item) => (item.id === assistantId ? updater(item) : item));
}

export function useSessions() {
  const { token } = useAuth();
  const { setError } = useApp();
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [activeSessionId, setActiveSessionId] = useState("");
  const [isDraftSession, setIsDraftSession] = useState(false);
  const [messages, setMessages] = useState<LocalMessage[]>([]);
  const [input, setInput] = useState("");
  const [useRag, setUseRag] = useState(true);
  const [busy, setBusy] = useState(false);
  const initialSessionPicked = useRef(false);

  const loadSessionMessages = useCallback(
    async (sessionId: string) => {
      if (!token) return;
      const data = await fetchSessionMessages(token, sessionId);
      setMessages(hydrateMessages(data.messages));
    },
    [token]
  );

  const loadSessions = useCallback(async () => {
    if (!token) return;
    try {
      setSessions(await fetchSessions(token));
    } catch (err) {
      setError((err as Error).message);
    }
  }, [token, setError]);

  useEffect(() => {
    if (!token) return;
    void loadSessions();
  }, [token, loadSessions]);

  useEffect(() => {
    if (initialSessionPicked.current || isDraftSession || activeSessionId || sessions.length === 0) {
      return;
    }
    initialSessionPicked.current = true;
    setActiveSessionId(sessions[0].id);
  }, [sessions, activeSessionId, isDraftSession]);

  useEffect(() => {
    if (!token || !activeSessionId) {
      if (!activeSessionId && isDraftSession) {
        setMessages([]);
      }
      return;
    }
    void (async () => {
      try {
        await loadSessionMessages(activeSessionId);
      } catch (err) {
        setError((err as Error).message);
      }
    })();
  }, [activeSessionId, token, setError, loadSessionMessages, isDraftSession]);

  function selectSession(sessionId: string) {
    setIsDraftSession(false);
    setActiveSessionId(sessionId);
  }

  async function sendMessage() {
    if (!token || !input.trim()) return;

    setBusy(true);
    setError("");
    const draft = input;
    setInput("");

    const tempUserMessage: LocalMessage = {
      id: crypto.randomUUID(),
      role: "user",
      content: draft,
      created_at: new Date().toISOString(),
    };
    const tempAssistantId = crypto.randomUUID();
    setMessages((prev) => [
      ...prev,
      tempUserMessage,
      {
        id: tempAssistantId,
        role: "assistant",
        content: "",
        created_at: new Date().toISOString(),
        citations: [],
        steps: [],
      },
    ]);

    let resolvedSessionId = activeSessionId;

    const handleEvent = (evt: StreamEvent) => {
      if (evt.type === "run" && evt.run_id) {
        setMessages((prev) =>
          updateAssistant(prev, tempAssistantId, (item) => ({
            ...item,
            runId: evt.run_id,
            traceId: evt.trace_id,
          }))
        );
      } else if (evt.type === "session" && evt.session_id) {
        resolvedSessionId = evt.session_id;
        setIsDraftSession(false);
        setActiveSessionId(evt.session_id);
        setMessages((prev) =>
          updateAssistant(prev, tempAssistantId, (item) => ({
            ...item,
            citations: evt.citations || item.citations,
          }))
        );
      } else if (evt.type === "step") {
        setMessages((prev) =>
          updateAssistant(prev, tempAssistantId, (item) => ({
            ...item,
            steps: appendStep(item.steps || [], evt),
            intent:
              evt.phase === "routing" && evt.detail?.intent
                ? String(evt.detail.intent)
                : item.intent,
          }))
        );
      } else if (evt.type === "tool_call") {
        setMessages((prev) =>
          updateAssistant(prev, tempAssistantId, (item) => ({
            ...item,
            steps: [
              ...(item.steps || []),
              {
                phase: "tool_call",
                summary: `调用 ${evt.tool}：${JSON.stringify(evt.arguments || {})}`,
              },
            ],
          }))
        );
      } else if (evt.type === "tool_result") {
        setMessages((prev) =>
          updateAssistant(prev, tempAssistantId, (item) => ({
            ...item,
            citations: evt.citations || item.citations,
            steps: [
              ...(item.steps || []),
              {
                phase: "tool_result",
                summary: evt.output_preview || "工具返回",
              },
            ],
          }))
        );
      } else if (evt.type === "delta") {
        setMessages((prev) =>
          updateAssistant(prev, tempAssistantId, (item) => ({
            ...item,
            content: `${item.content}${evt.content || ""}`,
          }))
        );
      } else if (evt.type === "replace") {
        setMessages((prev) =>
          updateAssistant(prev, tempAssistantId, (item) => ({
            ...item,
            content: evt.content || "",
          }))
        );
      } else if (evt.type === "done") {
        setMessages((prev) =>
          updateAssistant(prev, tempAssistantId, (item) => ({
            ...item,
            id: evt.assistant_message_id || item.id,
            runStatus: evt.status,
            agent_trace_summary:
              item.agent_trace_summary ||
              (evt.step_count != null ? `agent · ${evt.step_count} 步 · ${evt.latency_ms || 0}ms` : undefined),
          }))
        );
      } else if (evt.type === "error") {
        setError(evt.message || "流式输出失败");
      }
    };

    try {
      await streamMessage(
        token,
        { session_id: activeSessionId || undefined, message: draft, use_rag: useRag },
        handleEvent
      );
      if (resolvedSessionId) {
        setIsDraftSession(false);
        await loadSessionMessages(resolvedSessionId);
      }
      void loadSessions();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function rateMessage(messageId: string, rating: "up" | "down") {
    if (!token) return;
    try {
      await submitFeedback(token, messageId, rating);
      setMessages((prev) =>
        prev.map((m) => (m.id === messageId ? { ...m, feedback: rating } : m))
      );
    } catch (err) {
      setError((err as Error).message);
    }
  }

  async function rename(sessionId: string) {
    if (!token) return;
    const title = prompt("请输入新会话名称");
    if (!title) return;
    try {
      await renameSession(token, sessionId, title);
      await loadSessions();
    } catch (err) {
      setError((err as Error).message);
    }
  }

  async function remove(sessionId: string) {
    if (!token) return;
    if (!confirm("确认删除该会话？")) return;
    try {
      await deleteSession(token, sessionId);
      if (activeSessionId === sessionId) {
        setIsDraftSession(true);
        setActiveSessionId("");
        setMessages([]);
      }
      await loadSessions();
    } catch (err) {
      setError((err as Error).message);
    }
  }

  function startNewSession() {
    setIsDraftSession(true);
    setActiveSessionId("");
    setMessages([]);
  }

  return {
    sessions,
    activeSessionId,
    isDraftSession,
    setActiveSessionId: selectSession,
    messages,
    input,
    setInput,
    useRag,
    setUseRag,
    busy,
    loadSessions,
    loadSessionMessages,
    sendMessage,
    rateMessage,
    rename,
    remove,
    startNewSession,
  };
}
