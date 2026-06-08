import { describe, expect, it } from "vitest";
import {
  formatFailureReason,
  getFailureReasonEntries,
  getFailureReasons,
} from "./benchmark";

describe("formatFailureReason", () => {
  it("maps known static codes to Chinese labels", () => {
    expect(formatFailureReason("intent_mismatch")).toBe("意图不匹配");
    expect(formatFailureReason("missing_citation")).toBe("缺少知识引用");
    expect(formatFailureReason("missing_disclaimer")).toBe("缺少免责声明");
    expect(formatFailureReason("banned_diagnosis")).toBe("含禁止的诊断表述");
    expect(formatFailureReason("missing_safety_review")).toBe("未记录安全审查步骤");
    expect(formatFailureReason("unfaithful_answer")).toBe("回答与参考要点不符");
    expect(formatFailureReason("run_error")).toBe("运行异常");
  });

  it("formats missing_tools prefix", () => {
    expect(formatFailureReason("missing_tools:knowledge_search,get_user_profile")).toBe(
      "缺少工具：knowledge_search、get_user_profile",
    );
  });

  it("formats plan_agents_mismatch prefix", () => {
    expect(
      formatFailureReason("plan_agents_mismatch:expected=training,nutrition,actual=training"),
    ).toBe("计划 agent 不匹配（期望 training,nutrition，实际 training）");
  });

  it("returns unknown codes unchanged", () => {
    expect(formatFailureReason("custom_code")).toBe("custom_code");
  });
});

describe("getFailureReasonEntries", () => {
  it("returns code/label pairs preserving backend codes as keys", () => {
    const entries = getFailureReasonEntries({
      failure_reasons: ["intent_mismatch", "missing_tools:knowledge_search"],
    });
    expect(entries).toEqual([
      { code: "intent_mismatch", label: "意图不匹配" },
      { code: "missing_tools:knowledge_search", label: "缺少工具：knowledge_search" },
    ]);
  });

  it("returns empty list when metrics missing or empty", () => {
    expect(getFailureReasonEntries(null)).toEqual([]);
    expect(getFailureReasonEntries({})).toEqual([]);
    expect(getFailureReasonEntries({ failure_reasons: [] })).toEqual([]);
  });
});

describe("getFailureReasons", () => {
  it("returns labels only for backward compatibility", () => {
    expect(
      getFailureReasons({
        failure_reasons: ["missing_safety_review"],
      }),
    ).toEqual(["未记录安全审查步骤"]);
  });
});
