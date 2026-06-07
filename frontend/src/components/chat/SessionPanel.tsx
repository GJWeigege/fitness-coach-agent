import { useMemo } from "react";
import { Button } from "../ui/Button";
import { Badge } from "../ui/Badge";
import { groupSessionsByTime } from "../../utils/formatSessionTime";
import type { SessionSummary, UserProfile } from "../../types";

type SessionPanelProps = {
  sessions: SessionSummary[];
  activeSessionId: string;
  isDraftSession: boolean;
  canSendChat: boolean;
  canManage: boolean;
  canViewAllSessions: boolean;
  currentUserId: string;
  filterUserId: string;
  users: UserProfile[];
  userNameById: (userId: string | null) => string;
  onSelect: (id: string) => void;
  onNew: () => void;
  onRefresh: () => void;
  onRename: (id: string) => void;
  onDelete: (id: string) => void;
  onFilterUserChange: (userId: string) => void;
};

function SessionItem({
  session,
  activeSessionId,
  isDraftSession,
  canManage,
  canViewAllSessions,
  currentUserId,
  userNameById,
  onSelect,
  onRename,
  onDelete,
}: {
  session: SessionSummary;
  activeSessionId: string;
  isDraftSession: boolean;
  canManage: boolean;
  canViewAllSessions: boolean;
  currentUserId: string;
  userNameById: (userId: string | null) => string;
  onSelect: (id: string) => void;
  onRename: (id: string) => void;
  onDelete: (id: string) => void;
}) {
  const isOwn = session.user_id === currentUserId;
  const ownerLabel = userNameById(session.user_id);

  return (
    <li className="session-item">
      <button
        type="button"
        className={
          activeSessionId === session.id && !isDraftSession
            ? "session-card session-card--active"
            : "session-card"
        }
        onClick={() => onSelect(session.id)}
      >
        <div className="session-card__row">
          <span className="session-card__title">{session.title || "未命名会话"}</span>
          {canViewAllSessions ? (
            <Badge variant={isOwn ? "info" : "default"} className="session-card__tag">
              {session.user_id ? (isOwn ? "我的" : ownerLabel) : "未知用户"}
            </Badge>
          ) : null}
        </div>
      </button>
      {canManage ? (
        <div className="session-item__actions">
          <button type="button" onClick={() => onRename(session.id)} title="重命名">
            ✎
          </button>
          <button type="button" onClick={() => onDelete(session.id)} title="删除">
            ×
          </button>
        </div>
      ) : null}
    </li>
  );
}

export function SessionPanel({
  sessions,
  activeSessionId,
  isDraftSession,
  canSendChat,
  canManage,
  canViewAllSessions,
  currentUserId,
  filterUserId,
  users,
  userNameById,
  onSelect,
  onNew,
  onRefresh,
  onRename,
  onDelete,
  onFilterUserChange,
}: SessionPanelProps) {
  const groupedSessions = useMemo(() => groupSessionsByTime(sessions), [sessions]);
  const hasTodayGroup = groupedSessions.some((g) => g.label === "今天");
  const showDraftUnderToday = isDraftSession && (sessions.length > 0 || !hasTodayGroup);

  const draftItem = (
    <li className="session-item">
      <button className="session-card session-card--active session-card--draft" type="button">
        <span className="session-card__title">新会话（草稿）</span>
      </button>
    </li>
  );

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
      {canViewAllSessions ? (
        <div className="session-panel__filter">
          <label className="session-panel__filter-label" htmlFor="session-user-filter">
            用户筛选
          </label>
          <select
            id="session-user-filter"
            className="session-panel__filter-select"
            value={filterUserId}
            onChange={(e) => onFilterUserChange(e.target.value)}
          >
            <option value="">全部用户</option>
            {currentUserId ? (
              <option value={currentUserId}>我的会话</option>
            ) : null}
            {users
              .filter((u) => u.id !== currentUserId)
              .map((u) => (
                <option key={u.id} value={u.id}>
                  {u.username}
                </option>
              ))}
          </select>
        </div>
      ) : null}
      <div className="session-list session-list--panel">
        {sessions.length === 0 && !isDraftSession ? (
          <p className="session-list__empty">
            {filterUserId ? "该用户暂无会话" : "暂无会话，点击上方创建"}
          </p>
        ) : (
          <>
            {showDraftUnderToday && !hasTodayGroup ? (
              <section className="session-group">
                <h4 className="session-group__title">今天</h4>
                <ul className="session-group__list">{draftItem}</ul>
              </section>
            ) : null}
            {groupedSessions.map((group) => (
              <section key={group.label} className="session-group">
                <h4 className="session-group__title">{group.label}</h4>
                <ul className="session-group__list">
                  {group.label === "今天" && isDraftSession ? draftItem : null}
                  {group.sessions.map((s) => (
                    <SessionItem
                      key={s.id}
                      session={s}
                      activeSessionId={activeSessionId}
                      isDraftSession={isDraftSession}
                      canManage={canManage}
                      canViewAllSessions={canViewAllSessions}
                      currentUserId={currentUserId}
                      userNameById={userNameById}
                      onSelect={onSelect}
                      onRename={onRename}
                      onDelete={onDelete}
                    />
                  ))}
                </ul>
              </section>
            ))}
          </>
        )}
      </div>
    </aside>
  );
}
