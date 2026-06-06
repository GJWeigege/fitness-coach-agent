import type { LocalMessage } from "../../types";
import { useChatScroll } from "../../hooks/useChatScroll";
import { MessageBubble } from "./MessageBubble";
import { EmptyState } from "../ui/EmptyState";
import { ChatIcon, ChevronDownIcon } from "../ui/Icons";

type ChatWindowProps = {
  messages: LocalMessage[];
  busy: boolean;
  canFeedback?: boolean;
  onFeedback?: (messageId: string, rating: "up" | "down") => void;
};

export function ChatWindow({ messages, busy, canFeedback, onFeedback }: ChatWindowProps) {
  const {
    containerRef,
    bottomRef,
    messagesRef,
    showScrollButton,
    handleScroll,
    handleScrollToBottom,
  } = useChatScroll(messages, busy);

  return (
    <div className="chat-window-wrapper">
      <div className="chat-window" ref={containerRef} onScroll={handleScroll}>
        {messages.length === 0 ? (
          <EmptyState
            icon={<ChatIcon />}
            title="开始新的对话"
            description="在下方输入训练或营养问题，健身教练将结合知识库为您解答"
          />
        ) : (
          <div className="chat-window__messages" ref={messagesRef}>
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
            <div ref={bottomRef} className="chat-window__bottom-anchor" aria-hidden="true" />
          </div>
        )}
      </div>
      {showScrollButton ? (
        <button
          type="button"
          className="chat-window__scroll-btn"
          onClick={handleScrollToBottom}
          aria-label="滚动到最新消息"
        >
          <ChevronDownIcon />
        </button>
      ) : null}
    </div>
  );
}
