import { Button } from "../ui/Button";
import type { SessionSummary } from "../../types";

type SessionPanelProps = {
  sessions: SessionSummary[];
  activeSessionId: string;
  isDraftSession: boolean;
  canSendChat: boolean;
  canManage: boolean;
  onSelect: (id: string) => void;
  onNew: () => void;
  onRefresh: () => void;
  onRename: (id: string) => void;
  onDelete: (id: string) => void;
};

export function SessionPanel({
  sessions,
  activeSessionId,
  isDraftSession,
  canSendChat,
  canManage,
  onSelect,
  onNew,
  onRefresh,
  onRename,
  onDelete,
}: SessionPanelProps) {
  return (
    <aside className="session-panel">
      <div className="session-panel__header">
        <h3>会话</h3>
        <div className="session-panel__actions">
          <Button variant="ghost" onClick={onRefresh}>
            刷新
          </Button>
          {canSendChat ? (
            <Button variant="primary" onClick={onNew}>
              + 新会话
            </Button>
          ) : null}
        </div>
      </div>
      <ul className="session-list session-list--panel">
        {isDraftSession ? (
          <li className="session-item">
            <button className="session-card session-card--active session-card--draft" type="button">
              <span className="session-card__title">新会话（草稿）</span>
            </button>
          </li>
        ) : null}
        {sessions.length === 0 && !isDraftSession ? (
          <li className="session-list__empty">暂无会话，点击上方创建</li>
        ) : (
          sessions.map((s) => (
            <li key={s.id} className="session-item">
              <button
                type="button"
                className={
                  activeSessionId === s.id && !isDraftSession
                    ? "session-card session-card--active"
                    : "session-card"
                }
                onClick={() => onSelect(s.id)}
              >
                <span className="session-card__title">{s.title || "未命名会话"}</span>
                <span className="session-card__time">{new Date(s.updated_at).toLocaleString()}</span>
              </button>
              {canManage ? (
                <div className="session-item__actions">
                  <button type="button" onClick={() => onRename(s.id)} title="重命名">
                    ✎
                  </button>
                  <button type="button" onClick={() => onDelete(s.id)} title="删除">
                    ×
                  </button>
                </div>
              ) : null}
            </li>
          ))
        )}
      </ul>
    </aside>
  );
}
