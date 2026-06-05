import { usePermissions } from "../contexts/AuthContext";
import { useSessions } from "../hooks/useSessions";
import { ChatInput } from "../components/chat/ChatInput";
import { ChatWindow } from "../components/chat/ChatWindow";
import { SessionPanel } from "../components/chat/SessionPanel";

export function ChatPage() {
  const chat = useSessions();
  const { canSendChat, canWriteFeedback, canManageOwnSession, canManageAllSession } = usePermissions();
  const canManage = canManageOwnSession || canManageAllSession;

  return (
    <div className="chat-layout">
      <SessionPanel
        sessions={chat.sessions}
        activeSessionId={chat.activeSessionId}
        isDraftSession={chat.isDraftSession}
        canSendChat={canSendChat}
        canManage={canManage}
        onSelect={chat.setActiveSessionId}
        onNew={chat.startNewSession}
        onRefresh={() => void chat.loadSessions()}
        onRename={(id) => void chat.rename(id)}
        onDelete={(id) => void chat.remove(id)}
      />
      <div className="chat-page">
        <ChatWindow
          messages={chat.messages}
          busy={chat.busy}
          canFeedback={canWriteFeedback}
          onFeedback={(id, rating) => void chat.rateMessage(id, rating)}
        />
        <ChatInput
          input={chat.input}
          useRag={chat.useRag}
          busy={chat.busy}
          canSend={canSendChat}
          onInputChange={chat.setInput}
          onRagChange={chat.setUseRag}
          onSubmit={() => void chat.sendMessage()}
        />
      </div>
    </div>
  );
}
