import { describe, expect, it } from "vitest";
import { currentMonth, monthLabel, monthOfWeek, shiftMonth } from "./month";

describe("monthOfWeek", () => {
  it("取该周周一所在月", () => {
    expect(monthOfWeek("2026-11-02")).toBe("2026-11");
  });
  it("跨月周整周算进周一所在月", () => {
    expect(monthOfWeek("2026-11-30")).toBe("2026-11");   // week_end 是 12-06
    expect(monthOfWeek("2026-10-26")).toBe("2026-10");   // week_end 是 11-01
  });
  it("周日归到该周周一所在月，而不是自己所在月", () => {
    // 11-01 是周日，其所在周的周一在 10 月
    expect(monthOfWeek("2026-11-01")).toBe("2026-10");
  });
});

describe("shiftMonth", () => {
  it("跨年翻月", () => {
    // brief 原文此处写的是 "2027-01"，但同一 it 里下一行已用 ("2026-12", 1) 断言 "2027-01"，
    // 且与 brief Step 3 指定的 `Date.UTC(y, m - 1 + delta, 1)` 口径矛盾：11 月 +1 应是 12 月。
    expect(shiftMonth("2026-11", 1)).toBe("2026-12");
    expect(shiftMonth("2026-11", -1)).toBe("2026-10");
    expect(shiftMonth("2026-12", 1)).toBe("2027-01");
    expect(shiftMonth("2026-01", -1)).toBe("2025-12");
  });
});

describe("monthLabel", () => {
  it("输出中文月份", () => {
    expect(monthLabel("2026-11")).toBe("2026年11月");
  });
});

describe("currentMonth", () => {
  it("返回 YYYY-MM", () => {
    expect(currentMonth(new Date("2026-11-15T02:00:00Z"))).toBe("2026-11");
  });
  it("按上海时区取月，不按 UTC", () => {
    // 16:30Z = 上海次日 00:30；按 UTC 取月会算成 2026-10
    expect(currentMonth(new Date("2026-10-31T16:30:00Z"))).toBe("2026-11");
  });
});
