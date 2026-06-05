import type { LocalMessage } from "../../types";
import { BotIcon, UserIcon } from "../ui/Icons";
import { Badge } from "../ui/Badge";
import { AgentStepsPanel } from "./AgentStepsPanel";

const roleLabels: Record<string, string> = {
  user: "用户",
  assistant: "健身教练",
  system: "系统",
};

const intentLabels: Record<string, string> = {
  training: "训练",
  nutrition: "营养",
  recovery: "恢复",
  safety: "安全",
  profile: "档案",
  chitchat: "闲聊",
  unknown: "未知",
};

type MessageBubbleProps = {
  message: LocalMessage;
  canFeedback?: boolean;
  onFeedback?: (messageId: string, rating: "up" | "down") => void;
};

export function MessageBubble({ message, canFeedback, onFeedback }: MessageBubbleProps) {
  const isUser = message.role === "user";
  const isAssistant = message.role === "assistant";
  const roleClass = isUser
    ? "message message--user"
    : message.role === "system"
      ? "message message--system"
      : "message message--assistant";

  return (
    <article className={roleClass}>
      <div className="message__avatar">{isUser ? <UserIcon /> : <BotIcon />}</div>
      <div className="message__body">
        <div className="message__meta">
          {roleLabels[message.role] || message.role}
          {message.intent ? (
            <Badge variant="info">{intentLabels[message.intent] || message.intent}</Badge>
          ) : null}
        </div>
        <div className="message__content">{message.content || (isUser ? "" : "思考中...")}</div>
        {message.citations && message.citations.length > 0 ? (
          <details className="message__citations">
            <summary>引用知识片段（{message.citations.length}）</summary>
            <ul>
              {message.citations.map((item) => (
                <li key={item.chunk_id}>
                  <span className="citation-score">[{item.score.toFixed(2)}]</span>
                  {item.content}
                </li>
              ))}
            </ul>
          </details>
        ) : null}
        {isAssistant ? (
          <AgentStepsPanel
            steps={message.steps || []}
            runStatus={message.runStatus}
            traceSummary={message.agent_trace_summary}
          />
        ) : null}
        {canFeedback && isAssistant && message.content && onFeedback ? (
          <div className="message__feedback">
            <button
              type="button"
              className={message.feedback === "up" ? "feedback-btn feedback-btn--active" : "feedback-btn"}
              onClick={() => onFeedback(message.id, "up")}
              title="有帮助"
            >
              👍
            </button>
            <button
              type="button"
              className={message.feedback === "down" ? "feedback-btn feedback-btn--active" : "feedback-btn"}
              onClick={() => onFeedback(message.id, "down")}
              title="无帮助"
            >
              👎
            </button>
          </div>
        ) : null}
      </div>
    </article>
  );
}
