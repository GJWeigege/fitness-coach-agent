import type { Citation, LocalMessage } from "../../types";
import { BotIcon, UserIcon } from "../ui/Icons";
import { Badge } from "../ui/Badge";
import { AgentStepsPanel } from "./AgentStepsPanel";
import { MarkdownContent } from "./MarkdownContent";

const CITATION_PREVIEW_LEN = 200;

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

function citationSourceLabel(item: Citation): string | null {
  if (item.source === "hybrid" || (item.keyword_hit && (item.vector_score ?? 0) > 0)) {
    return "混合";
  }
  if (item.keyword_hit) {
    return "关键词";
  }
  if (item.source === "vector") {
    return "向量";
  }
  return null;
}

function CitationItem({ item }: { item: Citation }) {
  const displayScore = item.rerank_score ?? item.vector_score ?? item.score;
  const sourceLabel = citationSourceLabel(item);
  const isLong = item.content.length > CITATION_PREVIEW_LEN;
  const preview = isLong ? `${item.content.slice(0, CITATION_PREVIEW_LEN)}…` : item.content;

  return (
    <li>
      <span className="citation-score">[{displayScore.toFixed(3)}]</span>
      {sourceLabel ? <span className="citation-source">{sourceLabel}</span> : null}
      {isLong ? (
        <>
          <span>{preview}</span>
          <details className="citation-expand">
            <summary>展开全文</summary>
            {item.content}
          </details>
        </>
      ) : (
        item.content
      )}
    </li>
  );
}

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
        <div className="message__content">
          {message.content ? (
            isAssistant ? (
              <MarkdownContent content={message.content} />
            ) : (
              message.content
            )
          ) : isUser ? (
            ""
          ) : (
            "思考中..."
          )}
        </div>
        {message.citations && message.citations.length > 0 ? (
          <details className="message__citations">
            <summary>引用知识片段（{message.citations.length}）</summary>
            <ul>
              {message.citations.map((item) => (
                <CitationItem key={item.chunk_id} item={item} />
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
