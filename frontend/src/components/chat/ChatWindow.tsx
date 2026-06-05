import type { LocalMessage } from "../../types";
import { MessageBubble } from "./MessageBubble";
import { EmptyState } from "../ui/EmptyState";
import { ChatIcon } from "../ui/Icons";

type ChatWindowProps = {
  messages: LocalMessage[];
  busy: boolean;
  canFeedback?: boolean;
  onFeedback?: (messageId: string, rating: "up" | "down") => void;
};

export function ChatWindow({ messages, busy, canFeedback, onFeedback }: ChatWindowProps) {
  return (
    <section className="chat-window">
      {messages.length === 0 ? (
        <EmptyState
          icon={<ChatIcon />}
          title="开始新的对话"
          description="在下方输入训练或营养问题，健身教练将结合知识库为您解答"
        />
      ) : (
        <div className="chat-window__messages">
          {messages.map((msg) => (
            <MessageBubble
              key={msg.id}
              message={msg}
              canFeedback={canFeedback}
              onFeedback={onFeedback}
            />
          ))}
          {busy ? (
            <div className="typing-indicator">
              <span />
              <span />
              <span />
            </div>
          ) : null}
        </div>
      )}
    </section>
  );
}
