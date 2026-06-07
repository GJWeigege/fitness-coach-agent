import { describe, expect, it, vi, afterEach } from "vitest";
import { getSessionTimeGroup, groupSessionsByTime } from "./formatSessionTime";
import type { SessionSummary } from "../types";

function session(id: string, updatedAt: string): SessionSummary {
  return {
    id,
    user_id: "user-1",
    title: id,
    created_at: updatedAt,
    updated_at: updatedAt,
  };
}

function localIso(year: number, month: number, day: number, hour = 12): string {
  return new Date(year, month - 1, day, hour).toISOString();
}

describe("getSessionTimeGroup", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("classifies today, yesterday, recent, and earlier", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date(2026, 5, 7, 15, 0, 0));

    expect(getSessionTimeGroup(localIso(2026, 6, 7))).toBe("today");
    expect(getSessionTimeGroup(localIso(2026, 6, 6))).toBe("yesterday");
    expect(getSessionTimeGroup(localIso(2026, 6, 5))).toBe("recent");
    expect(getSessionTimeGroup(localIso(2026, 5, 31))).toBe("recent");
    expect(getSessionTimeGroup(localIso(2026, 5, 30))).toBe("earlier");
  });
});

describe("groupSessionsByTime", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("returns empty array for no sessions", () => {
    expect(groupSessionsByTime([])).toEqual([]);
  });

  it("groups sessions and sorts each bucket by updated_at desc", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date(2026, 5, 7, 15, 0, 0));

    const grouped = groupSessionsByTime([
      session("older-today", localIso(2026, 6, 7, 9)),
      session("newer-today", localIso(2026, 6, 7, 18)),
      session("yesterday", localIso(2026, 6, 6)),
    ]);

    expect(grouped.map((g) => g.label)).toEqual(["今天", "昨天"]);
    expect(grouped[0].sessions.map((s) => s.id)).toEqual(["newer-today", "older-today"]);
    expect(grouped[1].sessions.map((s) => s.id)).toEqual(["yesterday"]);
  });
});
