import type { SessionSummary } from "../types";

export type SessionTimeGroup = "today" | "yesterday" | "recent" | "earlier";

const GROUP_ORDER: { key: SessionTimeGroup; label: string }[] = [
  { key: "today", label: "今天" },
  { key: "yesterday", label: "昨天" },
  { key: "recent", label: "近7天" },
  { key: "earlier", label: "更早" },
];

/** 按浏览器本地时区的日历日分组（与后端 UTC ISO 时间戳配合使用）。 */
export function getSessionTimeGroup(iso: string): SessionTimeGroup {
  const date = new Date(iso);
  const now = new Date();
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const startOfDate = new Date(date.getFullYear(), date.getMonth(), date.getDate());
  const diffDays = Math.floor((startOfToday.getTime() - startOfDate.getTime()) / 86_400_000);

  if (diffDays === 0) return "today";
  if (diffDays === 1) return "yesterday";
  if (diffDays >= 2 && diffDays <= 7) return "recent";
  return "earlier";
}

export function groupSessionsByTime(
  sessions: SessionSummary[]
): { label: string; sessions: SessionSummary[] }[] {
  const buckets: Record<SessionTimeGroup, SessionSummary[]> = {
    today: [],
    yesterday: [],
    recent: [],
    earlier: [],
  };

  const sorted = [...sessions].sort(
    (a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime()
  );

  for (const session of sorted) {
    buckets[getSessionTimeGroup(session.updated_at)].push(session);
  }

  return GROUP_ORDER.filter((g) => buckets[g.key].length > 0).map((g) => ({
    label: g.label,
    sessions: buckets[g.key],
  }));
}
